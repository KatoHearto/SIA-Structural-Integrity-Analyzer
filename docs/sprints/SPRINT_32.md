# SPRINT 32 — Taint-Flow: Source Classification

**Version:** 3.61 → 3.62  
**File:** `god_mode_v3.py`

---

## Goal

SIA can identify which inputs are externally controlled (tainted). This is the
foundation for Sprint 33's propagation — without knowing what is tainted at the
boundary, propagation has no starting point.

---

## Root Cause / Motivation

Current `unguarded_db_write` and `untrusted_deserialization` warnings fire on any
node that writes to the DB or deserializes without a visible guard, regardless of
whether that node is reachable from external input at all. This produces a high
false-positive rate (see: 636 frappe warnings that are all internal).

Taint source classification separates "externally reachable input" from "internal
data" at the boundary — allowing all downstream analysis to be scoped correctly.

---

## Changes

### 1. Taint Source Taxonomy

Define a taxonomy of taint source kinds in a new constant block:

```python
_TAINT_SOURCE_KINDS = {
    "http_param":    ["frappe.form_dict", "frappe.request.json", "frappe.local.form_dict"],
    "cli_arg":       ["sys.argv", "argparse", "click.argument", "click.option"],
    "event_hook":    ["doc.as_dict()", "frappe.get_doc"],   # hook callback args
    "file_read":     ["open(", "json.load", "yaml.safe_load", "toml.load"],
    "env_var":       ["os.environ", "os.getenv"],
    "external_api":  ["requests.get", "requests.post", "httpx.get", "httpx.post"],
}
```

### 2. Entry Point Tagging

During node construction in `_build_graph()`, tag each node that is a taint
source entry point:

- Python: functions decorated with `@frappe.whitelist()`, `@click.command()`,
  functions named `main()` that consume `sys.argv`
- JavaScript: exported functions receiving `event`, `req`, `ctx` parameters
- Frappe-specific: functions registered in `hooks.py` under `doc_events`,
  `scheduler_events`, `on_submit`

Store on the node: `"taint_entry": True, "taint_sources": [list of source kinds]`

### 3. Parameter Taint Marking

For each taint entry point, mark its parameters as tainted:

```python
# Example: polaris_register(lead_id: str) decorated with @frappe.whitelist()
# → lead_id is marked as tainted (http_param)
```

Store as `"tainted_params": {"lead_id": "http_param"}` on the node.

### 4. `--taint` CLI Flag

Add `--taint` flag to `sia scan`. When set, taint analysis runs and taint metadata
is included in the JSON report under each node's entry. Default: off (no performance
impact on standard scans).

When `--taint` is active, include a `taint_sources` summary in the report `meta`:

```json
"taint_summary": {
  "entry_points": 47,
  "tainted_params": 183,
  "source_breakdown": {"http_param": 120, "file_read": 38, "event_hook": 25}
}
```

### 5. Version Bump

`3.61` → `3.62`

---

## Validation

- `python -m py_compile god_mode_v3.py` — OK
- Self-analysis with `--taint`: SIA's own `_run_sia_why` and `_run_sia_diff._load`
  must appear as taint entry points with `file_read` source kind
- Frappe bench run with `--taint`: `polaris_register` must show `lead_id` as
  `http_param` tainted parameter
- `taint_entry_count > 0` for smartversorgt_crm bench

---

## What Does NOT Change

- Standard `sia scan` without `--taint` is functionally identical to v3.61
- No existing warning rules are modified
- No changes to graph structure — taint data is additive metadata on existing nodes
