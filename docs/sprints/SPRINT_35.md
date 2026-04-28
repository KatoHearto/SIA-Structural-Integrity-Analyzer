# SPRINT 35 — Verifikations-Loop (`sia verify`)

**Version:** 3.64 → 3.65  
**File:** `god_mode_v3.py`  
**Requires:** Sprint 33 (exploitability scores), Sprint 34 (worker briefs)

---

## Goal

`sia verify <before_report> <after_report> [--task <brief_id>]` confirms whether
a specific warning was correctly resolved after a worker ran. Closes the loop:
SIA briefs the worker, worker fixes, SIA verifies.

---

## Root Cause / Motivation

Today `sia diff` compares two reports at the summary level. It tells you warning
counts changed. It does not tell you: was this specific taint path actually broken?
Was the guard inserted at the right point? Did the fix introduce a regression
elsewhere?

A worker that receives a brief (Sprint 34) should get back a verifikation result
that confirms the fix worked — not just that the warning disappeared.

---

## Changes

### 1. New CLI Command: `sia verify`

```
sia verify <before.json> <after.json> [--node <node_id>] [--strict]
```

- Compares two SIA scan reports (both generated with `--taint`)
- `--node`: focus on a specific node's warnings (typically the one in the brief)
- `--strict`: treat any new warning anywhere as a regression, not just in the target

### 2. Per-Node Resolution Check

For each warning in the before-report:

**FIXED** — the warning is gone AND:
- The taint path is broken (a guard signal now appears on the path)
- OR the sink is no longer reachable from that entry point
- OR the node no longer exists (deleted)

**SUPERFICIALLY_FIXED** — the warning is gone BUT:
- The taint path still flows through (guard is elsewhere, not on the path)
- OR exploitability_score dropped but is not zero
- Flag: "Warning removed but taint path unconfirmed — manual review advised"

**REGRESSED** — a new warning appeared that was not in the before-report.
Classified as: same node (regression in fix), adjacent node (collateral), unrelated.

**UNCHANGED** — warning present in both reports, no score change.

### 3. Verification Report Output

```markdown
## SIA Verification Report
Before: sia_report_before.json (2026-04-27T19:50Z, v3.65)
After:  sia_report_after.json  (2026-04-27T20:15Z, v3.65)
Node focus: smartversorgt_crm.api:polaris_register

### Result: FIXED ✓
Warning resolved: unguarded_db_write (was exploitability 0.91)

Verification:
  Taint path broken at: polaris_register() line 234
  Guard detected: validation_guard (insurance_number regex check)
  Exploitability after: 0.00

### Regressions: NONE

### Summary
  Fixed:               1
  Superficially fixed: 0
  Regressed:           0
  Unchanged:           6
```

### 4. Integration with `sia brief`

`sia brief` output (Sprint 34) now includes a ready-to-run verify command
at the bottom of every brief:

```
## VERIFY
# Run after fix:
sia scan --taint -o report_after.json .
sia verify report_before.json report_after.json --node smartversorgt_crm.api:polaris_register
```

### 5. Machine-Readable Output

`--output json` for `sia verify`:

```json
{
  "node": "smartversorgt_crm.api:polaris_register",
  "result": "FIXED",
  "exploitability_before": 0.91,
  "exploitability_after": 0.00,
  "taint_path_broken": true,
  "guard_inserted_at": "polaris_register:234",
  "regressions": [],
  "summary": {"fixed": 1, "superficial": 0, "regressed": 0, "unchanged": 6}
}
```

### 6. Version Bump

`3.64` → `3.65`

---

## Validation

- Run SIA on Frappe bench before cleanup → save report_before.json
- Run SIA after cleanup → save report_after.json
- `sia verify report_before.json report_after.json` must show:
  - `fix_role:get_db_creds` → FIXED (node deleted)
  - `run_fixes:get_db_creds` → FIXED (node deleted)
  - No regressions
- `--strict` mode must catch any new warning introduced by accident
- Superficially_fixed detection: manually introduce a fix that removes the warning
  without breaking the taint path → must be caught as SUPERFICIALLY_FIXED

---

## What Does NOT Change

- `sia diff` remains unchanged (summary-level comparison)
- `sia verify` is a separate, additive command
- Standard `sia scan` without `--taint` still works; `sia verify` on such reports
  skips taint path verification and falls back to presence/absence check only
