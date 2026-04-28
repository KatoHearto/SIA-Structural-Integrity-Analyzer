# SPRINT 33 — Taint-Flow: Propagation + Exploitability Score

**Version:** 3.62 → 3.63  
**File:** `god_mode_v3.py`  
**Requires:** Sprint 32 (taint source classification)

---

## Goal

Propagate taint through the call graph from sources (Sprint 32) to sinks, compute
backwards reachability from each warning node to entry points, and produce a single
`exploitability_score` per warning that replaces severity-only ranking.

---

## Root Cause / Motivation

A critical warning in dead code (0 callers) is less urgent than a medium warning
reachable from 12 public HTTP endpoints. Current severity is severity-only.
Exploitability = severity × reachability. This sprint adds the reachability half.

---

## Changes

### 1. Sink Taxonomy

Define sinks — locations where tainted data causes damage:

```python
_TAINT_SINKS = {
    "db_write":      ["frappe.db.set_value", "frappe.db.sql", "doc.save()", "doc.insert()"],
    "db_read_inject":["frappe.db.sql(", "frappe.db.get_value("],  # parameterized risk
    "os_exec":       ["subprocess.run", "subprocess.Popen", "os.system", "os.popen"],
    "eval_exec":     ["eval(", "exec(", "compile("],
    "file_write":    ["open(.*'w'", "shutil.copy", "pathlib.*write"],
    "external_send": ["requests.post", "requests.put", "smtplib", "httpx.post"],
    "deserialize":   ["json.loads(", "yaml.load(", "pickle.loads("],
}
```

### 2. Forward Taint Propagation

Walk the call graph forward from each tainted entry point parameter. A node
inherits taint if:
- It is called by a tainted node AND receives the tainted value as an argument
- It reads from a tainted data structure (frappe.form_dict, request body)

Propagation stops at:
- A node that applies a recognized validation guard on the tainted param
- A node with `taint_entry: False` and no tainted callers

Store on each node: `"taint_reaches_sink": bool, "taint_path": [node_id, ...]`

### 3. Backwards Reachability

For each warning node: traverse call graph in reverse, count how many taint
entry points can reach it.

```python
reachability_score = len(reachable_entry_points) / max(1, total_entry_points)
```

Store on each warning: `"reachable_from": [entry_point_node_ids]`,
`"reachability_score": float 0.0–1.0`

### 4. Exploitability Score

Combine severity, reachability, and taint confirmation:

```python
SEVERITY_WEIGHTS = {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.1}

exploitability = (
    SEVERITY_WEIGHTS[warning.severity]
    * reachability_score
    * (1.5 if taint_confirmed else 1.0)  # bonus if taint actually reaches this sink
)
```

Range: 0.0 (unreachable dead code) → 1.5 (critical, fully reachable, taint confirmed).

### 5. Report Changes

In `architectural_warnings` section, each warning gains:

```json
{
  "rule": "unguarded_db_write",
  "severity": "high",
  "exploitability_score": 0.91,
  "taint_confirmed": true,
  "reachability_score": 0.87,
  "reachable_from": ["smartversorgt_crm.api:polaris_register"],
  "taint_path": ["http_param:lead_id", "polaris_register", "frappe.db.set_value"]
}
```

Warnings are sorted by `exploitability_score` descending, not severity.

In `meta`:
```json
"exploitability_summary": {
  "confirmed_exploitable": 12,
  "likely_false_positive": 689,
  "unresolved": 71
}
```

### 6. Version Bump

`3.62` → `3.63`

---

## Validation

- Self-analysis: SIA's own `_run_sia_diff._load` must show taint path
  `file_read → _load → json.load (sink:deserialize)` with exploitability > 0
- Frappe bench: frappe framework warnings must have `reachability_score < 0.1`
  (they are internal), dramatically reducing their priority
- smartversorgt_crm bench: `fix_role:get_db_creds` must have exploitability > 0.8
  (was reachable from app root before cleanup — now 0.0 since file deleted ✓)
- Total warnings unchanged — exploitability_score changes ordering only

---

## What Does NOT Change

- Warning count is identical — this sprint re-ranks, does not add or remove warnings
- All existing signal detection logic unchanged
- `--taint` flag from Sprint 32 required; without it exploitability_score = null
