# SPRINT 36 — Absence Detection: Graph Symmetry

**Version:** 3.65 → 3.66  
**File:** `god_mode_v3.py`

---

## Goal

SIA detects what is missing by comparing symmetric structures within the graph.
Not "this code is wrong" — "this code is incomplete." The output is a new
`absence_warnings` section in the report, parallel to `architectural_warnings`.

---

## Root Cause / Motivation

Static analysis traditionally finds what is present and wrong. The harder problem
is finding what should be present but isn't. A missing delete() paired with
create(), a missing auth guard on write while reads are guarded, a missing error
handler for a documented failure mode — these are never flagged today because there
is nothing there to flag.

---

## Changes

### 1. Symmetry Rule Engine

Define a set of symmetry rules that express expectations:

```python
_SYMMETRY_RULES = [
    # CRUD symmetry
    SymmetryRule("crud_delete",
        if_exists=r"(create|insert|add)_(\w+)",
        expect=r"(delete|remove|trash)_\2",
        severity="medium",
        message="create/insert without corresponding delete — orphan data risk"),

    SymmetryRule("crud_update",
        if_exists=r"(create|insert)_(\w+)",
        expect=r"(update|patch|modify)_\2",
        severity="low",
        message="create without update — immutable-only pattern, verify intentional"),

    # Auth symmetry
    SymmetryRule("auth_write_missing",
        if_exists_signal="auth_guard",
        on_pattern=r"get_|list_|fetch_",
        expect_signal="auth_guard",
        on_pattern_counterpart=r"set_|create_|update_|delete_",
        severity="high",
        message="read endpoint is guarded, paired write endpoint is not"),

    # Validation symmetry
    SymmetryRule("validate_before_save",
        if_exists=r"(\w+)\.save\(\)",
        expect_signal="validation_guard",
        in_same_scope=True,
        severity="medium",
        message="save() called without prior validation guard in same function"),

    # Guard coverage
    SymmetryRule("guard_outlier",
        if_N_of_N_siblings_have_signal="validation_guard",
        threshold=0.75,   # if ≥75% of sibling functions have it
        expect_signal="validation_guard",
        severity="high",
        message="N-1 of N similar functions have validation guard — this one does not"),
]
```

### 2. Sibling Detection

Two functions are siblings if they:
- Share the same class or module
- Have similar naming patterns (same prefix/suffix family)
- Have similar call signatures (same parameter count / types)

Sibling groups are computed once during graph build and stored as node metadata.

### 3. Absence Warning Format

New top-level section `absence_warnings` in the JSON report:

```json
{
  "absence_warnings": [
    {
      "rule": "guard_outlier",
      "severity": "high",
      "node_id": "smartversorgt_crm.api:polaris_register",
      "message": "3 of 4 sibling functions have validation_guard — polaris_register does not",
      "siblings_with_guard": [
        "smartversorgt_crm.api:_polaris_token",
        "smartversorgt_crm.api:polaris_sync",
        "smartversorgt_crm.api:polaris_get_approvals"
      ],
      "expected_signal": "validation_guard",
      "suggestion": "Add input validation before first external call (see siblings for pattern)"
    }
  ]
}
```

### 4. Report Section + CLI

`sia scan` report gains an `absence_warnings` section.
`sia scan --no-absence` skips symmetry analysis (for speed on large codebases).

Summary line added to report header:
```
13007 nodes | 40967 edges | 64 cycles | 772 arch. warnings | 23 absence warnings
```

### 5. `sia brief` Integration

`sia brief --task extend <node_id>` uses absence warnings as input instead of
architectural warnings — generating a brief for adding what is missing rather than
fixing what is wrong.

### 6. Version Bump

`3.65` → `3.66`

---

## Validation

- Self-analysis: SIA's own codebase must produce ≥1 `crud_delete` absence warning
  (there are create operations without delete counterparts in workspace management)
- Frappe bench: `auth_write_missing` must fire on at least one CRM endpoint pair
- smartversorgt_crm: `guard_outlier` must fire on `polaris_register` (3 of 4
  sibling functions have validation guards — it did not before Sprint 35's fix)
- `--no-absence` flag suppresses the section cleanly with no errors
- Absence warnings do NOT appear in `architectural_warnings` — separate section only

---

## What Does NOT Change

- `architectural_warnings` logic is unchanged
- Absence warnings do not affect risk scores or exploitability scores
- All existing CLI flags and outputs remain backward compatible
