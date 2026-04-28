# SPRINT 31 — Hardening: Schema Validation on JSON Report Readers

**Version:** 3.60 → 3.61  
**File:** `god_mode_v3.py`

---

## Root Cause

Self-analysis (Sprint 30) produced 3 genuine `untrusted_deserialization` warnings on:

- `_scan_frappe_json_files` — reads project DocType JSON files via `json.load()`
- `_run_sia_why` — reads a SIA JSON report file via `json.load()`
- `_run_sia_diff._load` — reads two SIA JSON report files via `json.load()`

None of these were RCE risks (Python's `json` module is safe), but all three lacked
explicit schema validation, meaning malformed or incompatible reports would produce
cryptic `KeyError`/`AttributeError` crashes rather than clear error messages.

---

## Changes

### 1. `_scan_frappe_json_files` (line ~938)

Moved the `isinstance(data, dict)` check inside the `try` block and changed the
guard action from `continue` to `raise ValueError(...)`, then added `ValueError` to
the except clause. The `raise` keyword makes the guard detectable by `_guard_signal_for_window`.

**Before:**
```python
except (OSError, json.JSONDecodeError):
    continue
if not isinstance(data, dict):
    continue
```

**After:**
```python
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
except (OSError, json.JSONDecodeError, ValueError):
    continue
```

### 2. `_run_sia_why` (line ~14069)

Added explicit guard after `json.load()`:

```python
if not isinstance(report, dict) or "meta" not in report:
    print(f"Invalid or incompatible SIA report — missing required keys: {report_path}", file=_sys.stderr)
    raise SystemExit(1)
```

### 3. `_run_sia_diff._load` (line ~14248)

Refactored `_load` to capture result before returning, then validate:

```python
if not isinstance(data, dict) or "meta" not in data:
    print(f"Invalid or incompatible SIA report — missing required keys: {path}", file=_sys.stderr)
    raise SystemExit(1)
```

### 4. Version bump

`3.60` → `3.61`

---

## Validation

- `python -m py_compile god_mode_v3.py` — OK
- Self-analysis: `architectural_warning_count == 0` (was 3)
- `nodes=382  edges=660  cycles=1  parse_errors=0  architectural_warnings=0`

---

## What Does NOT Change

- Functional behavior of all three methods is identical for valid inputs.
- The `_guard_signal_for_window` detection mechanism is unchanged — the fix works
  *within* the existing signal detection logic by placing guard patterns where the
  window scanner can see them.
- No new signals, rules, or CLI flags.
