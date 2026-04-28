# SPRINT 39 — Prescriptive Output: Fix Suggestions

**Version:** 3.68 → 3.69  
**File:** `god_mode_v3.py`  
**Requires:** Sprint 38 (pattern library), Sprint 33 (taint paths), Sprint 37 (spec gaps)

---

## Goal

Every warning — architectural or absence — gains a concrete `suggestion` block:
a ready-to-apply code snippet modeled on the codebase's own patterns, with exact
insertion point, spec reference if applicable, and a quality confidence score.

This is the final piece that transforms SIA from "here is what is wrong" to
"here is exactly what to write."

---

## Root Cause / Motivation

After Sprint 34's `sia brief`, a worker receives context and a manually-derived
suggestion. Sprint 39 makes the suggestion automatic and codebase-grounded. The
brief becomes fully generated — not just scoped context, but a concrete, ready
code snippet that follows the project's own conventions.

---

## Changes

### 1. Suggestion Engine

For each warning (architectural or absence), the suggestion engine runs:

**Step 1 — Find matching pattern**
Query the pattern library (Sprint 38) for the best match:
- Match by: guard_type needed (inferred from warning rule), language, domain hint
  (inferred from parameter name / field name in the taint path)
- Score: quality_score × domain_similarity × language_match

**Step 2 — Adapt pattern to context**
Take the canonical pattern and substitute:
- Variable name: replace pattern's variable with the actual parameter name at the
  insertion point
- Regex: if spec (Sprint 37) provides a format constraint, use that regex;
  else use the pattern's regex as a placeholder with a `# TODO: adjust regex` note
- Exception class: use the same class as the pattern unless the target module
  imports a different one
- Error message: adapt to include the actual field name

**Step 3 — Determine insertion point**
From the taint path (Sprint 33): the suggestion inserts immediately before the
first sink the tainted parameter reaches.

From absence warnings (Sprint 36/37): insert at the start of the function body,
or before the first relevant operation (save(), external call, etc.)

**Step 4 — Validate syntactically**
Run `ast.parse()` on the suggestion snippet in isolation. If it fails, fall back
to a template with `# ADAPT:` markers rather than broken code.

### 2. Suggestion Block in Warnings

Every warning in `architectural_warnings` and `absence_warnings` gains:

```json
{
  "rule": "unguarded_db_write",
  "severity": "high",
  "exploitability_score": 0.91,
  "suggestion": {
    "confidence": 0.84,
    "pattern_source": "PL-001",
    "insertion_file": "smartversorgt_crm/api.py",
    "insertion_line": 234,
    "insertion_position": "before_first_sink",
    "imports_to_add": ["re"],
    "code": "if not insurance_number or not re.match(r'[A-Z][0-9]{9}', insurance_number):\n    raise frappe.ValidationError(f'Ungültige Versicherungsnummer: {insurance_number}')",
    "spec_reference": "POLARIS_API.md:57 — insuranceNumber format",
    "note": null
  }
}
```

**Confidence score** (0.0–1.0):
- 1.0: exact pattern match + spec-confirmed regex + valid syntax
- 0.7–0.9: pattern match + inferred regex (needs review)
- 0.4–0.6: no pattern match, template generated with ADAPT markers
- < 0.4: no suggestion generated (warning too ambiguous)

### 3. `sia brief` Enhancement

`sia brief` in Sprint 34 already has a `## REQUIRED CHANGE` section. Sprint 39
populates it from the suggestion engine instead of the ad-hoc proximity search:

```markdown
## REQUIRED CHANGE
Confidence: 0.84 | Pattern: PL-001 | Spec: POLARIS_API.md:57

Insert at: smartversorgt_crm/api.py line 234

```python
if not insurance_number or not re.match(r'[A-Z][0-9]{9}', insurance_number):
    raise frappe.ValidationError(f'Ungültige Versicherungsnummer: {insurance_number}')
```

Add import: `import re` (if not already present)
```

### 4. Suggestion Quality Report

New `meta` summary:

```json
"suggestion_coverage": {
  "warnings_with_suggestion": 698,
  "warnings_without_suggestion": 74,
  "avg_confidence": 0.71,
  "high_confidence": 412,
  "needs_review": 286
}
```

### 5. `--no-suggestions` Flag

Skips suggestion generation (saves ~5% scan time on large codebases). Useful for
CI runs where only warning counts matter.

### 6. Version Bump

`3.68` → `3.69`

---

## Validation

- Self-analysis: every SIA warning on its own code must have a suggestion block
  with confidence ≥ 0.4
- Frappe bench: `polaris_register` unguarded_db_write suggestion must contain
  the `insurance_number` regex from POLARIS_API.md (requires `--spec` flag)
- `ast.parse()` on all generated snippets must pass (no syntactically broken code)
- Confidence < 0.4 warnings: suggestion field is null, not missing or errored
- `--no-suggestions` produces identical warning counts with null suggestion fields

---

## What Does NOT Change

- Suggestions are never applied automatically — SIA remains read-only
- Warning detection logic unchanged — suggestions are a reporting layer only
- A suggestion with confidence < 0.4 still shows the warning; it just has no
  code snippet
- All prior CLI commands and flags remain backward compatible
