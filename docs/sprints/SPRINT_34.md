# SPRINT 34 — Chirurgisches Worker Briefing (`sia brief`)

**Version:** 3.63 → 3.64  
**File:** `god_mode_v3.py`  
**Requires:** Sprint 32 + 33 (taint data + exploitability scores)

---

## Goal

`sia brief <node_id>` generates a minimal, task-specific briefing that gives an
LLM worker exactly what it needs to fix a specific warning — and nothing else.
No 40,000-edge context dumps. No encyclopedia. Surgical precision.

---

## Root Cause / Motivation

The existing `--llm-context` flag produces a full project context pack. Useful for
orientation, not for execution. A worker tasked with "add validation to function X"
does not need the entire codebase — it needs: the function, the pattern to follow,
the constraint, and how to verify the fix.

The gap between "here is a warning" and "here is exactly what to do" is currently
bridged manually. This sprint closes that gap.

---

## Changes

### 1. New CLI Command: `sia brief`

```
sia brief <node_id> [--task fix|extend|verify] [--output text|json|markdown]
```

- `node_id`: any node ID from the SIA report (e.g. `smartversorgt_crm.api:polaris_register`)
- `--task fix` (default): generate a fix brief for the top warning on this node
- `--task extend`: generate a brief for adding missing functionality (requires Sprint 36)
- `--task verify`: generate verification instructions only
- `--output markdown` (default): human and LLM readable

### 2. Brief Structure

Output sections, in order:

```markdown
## TASK
One sentence: what needs to be done and why.
Source: warning rule + exploitability score.

## LOCATION
File: smartversorgt_crm/api.py
Line: 234
Function: polaris_register()

## WHY
Taint path (from Sprint 33):
  HTTP POST /api/method/... → lead_id (http_param)
  → polaris_register(lead_id)
  → frappe.db.set_value("CRM Lead", lead_id, ...)  ← sink

## PATTERN
Closest existing guard in this codebase (from Sprint 38 if available,
else from SIA's existing guard signal detection):

  File: smartversorgt_crm/api.py, line 89
  Function: _polaris_token()
  Code:
    if not zip_code or not re.match(r'\d{5}', zip_code):
        raise frappe.ValidationError("Ungültige PLZ")

## REQUIRED CHANGE
Concrete suggestion modeled on the pattern above.
Insertion point: line 234, before frappe.db.set_value call.

  if not insurance_number or not re.match(r'[A-Z][0-9]{9}', insurance_number):
      raise frappe.ValidationError("Ungültige Versicherungsnummer")

## CONSTRAINTS
- Do NOT modify: hooks.py, site_config.json
- Do NOT change the @frappe.whitelist() decorator
- Keep existing function signature unchanged
- frappe.ValidationError is the correct exception class here

## CONTEXT
Only these functions are relevant. Do not read further:
  1. polaris_register() — the function to fix [full source follows]
  2. _polaris_token() — the pattern to follow [full source follows]

## VERIFY
After applying the fix, run:
  curl -X POST .../api/method/smartversorgt_crm.api.polaris_register \
    -d '{"lead_id": ""}' → expect HTTP 417 ValidationError
  
  Then re-run: sia scan --taint → exploitability_score for this node should drop to 0.0
```

### 3. Pattern Matching Logic

To find the "closest existing guard":
1. Get all nodes in the same module with a `validation_guard` signal
2. Score by: same file > same class > same module > same language
3. Extract the code window (±5 lines around the guard) as the pattern example
4. If no guard exists in same module, search codebase-wide

### 4. Context Extraction

Pull only the source lines for:
- The target function (full body)
- The pattern function (full body)
- Any directly called functions that are part of the taint path

Explicitly exclude everything else. The brief must not contain more than ~200 lines
of source total.

### 5. Version Bump

`3.63` → `3.64`

---

## Validation

- `sia brief smartversorgt_crm.api:polaris_register` on the Frappe bench must
  produce a brief referencing `_polaris_token` as the pattern, with the
  `insurance_number` regex as the suggested fix
- `sia brief --output json` must be valid JSON with all sections present
- Brief source context must not exceed 250 lines total
- `--task verify` output must include a `sia scan` re-run command

---

## What Does NOT Change

- `sia scan` output is unchanged
- Existing `--llm-context` flag still works as before (full context pack)
- `sia brief` is additive — requires a prior `sia scan` report to exist
