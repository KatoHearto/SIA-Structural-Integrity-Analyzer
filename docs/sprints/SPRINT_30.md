# SPRINT 30 — Calibration Fix: `pathlib.Path` false positive in `input_boundary`

**Version:** 3.59 → 3.60  
**File:** `god_mode_v3.py`  
**Workers:** A (lines 1–8730) · B (lines 8730–end + README + CHANGES + WORKER_GUIDE)

---

## Root Cause

Self-analysis (Sprint 29) produced 24 architectural warnings, 21 of which were false
positives. All traced to a single pattern in `_extract_python_semantic_spans`:

```python
re.search(r"\b(?:Body|Query|Path|Form|Header|Cookie|Depends)\s*\(", text)
```

`Path` was intended to match FastAPI's `Path(...)` dependency injection parameter.
It also matches `pathlib.Path(some_file)` — which SIA uses throughout its own
file-scanning code. Every method containing `Path(...)` incorrectly received an
`input_boundary` signal, which then triggered `unguarded_entry` for all of them.

FastAPI routes are still detected by the 6 remaining patterns in the same block
(`Body`, `Query`, `Form`, `Header`, `Cookie`, `Depends`) plus the existing
`@\w*(?:route|get|post|put|delete|patch)\b` and `request.*` patterns.
Removing `Path` from this group causes zero real coverage loss.

---

## Worker A Task (lines 1–8730)

### 1. Fix the `input_boundary` pattern (line 5239)

Find:
```python
                or re.search(r"\b(?:Body|Query|Path|Form|Header|Cookie|Depends)\s*\(", text)
```

Replace with:
```python
                or re.search(r"\b(?:Body|Query|Form|Header|Cookie|Depends)\s*\(", text)
```

One word removed (`Path|`). Nothing else changes in this block.

### 2. Version bump (line ~748)

```python
"version": "3.60",
```

---

## Worker B Tasks (lines 8730–end + docs)

### 1. Update `CHANGES.md`

```markdown
## Sprint 30 — Calibration Fix: `pathlib.Path` false positive (v3.60)

- Removed `Path` from the Python `input_boundary` alternation pattern
  (`\b(?:Body|Query|Form|Header|Cookie|Depends)\s*\(`)
- `pathlib.Path(...)` no longer triggers `input_boundary`, eliminating
  the cascade of false-positive `unguarded_entry` architectural warnings
  on file-reading methods
- Self-analysis: 24 → 3 architectural warnings (all remaining are genuine
  `untrusted_deserialization` findings on JSON-loading code)
- FastAPI route detection unaffected — 6 other patterns cover all web boundaries
```

### 2. Update `WORKER_GUIDE.md`

```
- Sprint history: 33 passes (Runs 1–3 autonomous, Sprints 1–30)
```

Update version reference `3.59` → `3.60`.

### 3. Update `README.md`

**Self-Analysis block** — update the node/edge count and add warning count:

```
nodes=382  edges=660  cycles=1  parse_errors=0  architectural_warnings=3
```

**Development History table** — add:
```
| Sprint 30 | Calibration: fix `pathlib.Path` false positive in `input_boundary` |
```

**Passes line** — update:
```
SIA was developed in **33 passes** (3 autonomous runs + 30 directed sprints)
```

---

## Validation Checklist (Brain)

1. Line 5239: pattern no longer contains `Path|`.
2. `meta.version == "3.60"`.
3. Running SIA on itself (`python god_mode_v3.py . --out self.json --no-git-hotspots`)
   produces `architectural_warning_count == 3` (only the three `untrusted_deserialization`
   warnings on `_scan_frappe_json_files`, `_run_sia_diff`, `_run_sia_why` remain).
4. `source_group` and `source_qualname` no longer appear in `architectural_warnings`.
5. `CHANGES.md` has Sprint 30 entry.
6. `WORKER_GUIDE.md` says "33 passes".
7. `README.md` self-analysis block shows `architectural_warnings=3`.

---

## What Does NOT Change

- All other `input_boundary` patterns in `_extract_python_semantic_spans` are unchanged.
- No other language extractors are affected.
- The `unguarded_entry` rule logic itself is unchanged — the fix is upstream in the signal.
- The 3 genuine `untrusted_deserialization` warnings remain as real findings.
