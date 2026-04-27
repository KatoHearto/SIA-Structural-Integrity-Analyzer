# SPRINT 25 — Frappe Plugin: ORM Resolution + Semantic Enrichment

**Version:** 3.54 → 3.55  
**File:** `god_mode_v3.py`  
**Workers:** A (lines 1–8730) · B (lines 8730–end + README + CHANGES)

---

## Goal

Two additions to the Frappe plugin:

1. **ORM Resolution** — when Python code calls `frappe.get_doc("DocType", ...)`,
   `frappe.new_doc(...)`, `frappe.get_all(...)`, `frappe.db.get_value(...)` etc., add an
   `orm_load` edge from the calling symbol to the matching DocType graph node.

2. **Semantic Enrichment** — introduce a new `orm_dynamic_load` semantic signal that fires
   on any Python symbol using Frappe ORM calls (regardless of whether `--plugin frappe` is
   active), and enrich `hooks.py`-style modules with `input_boundary` / `time_or_randomness`
   signals when the plugin is active.

---

## New Semantic Signal: `orm_dynamic_load` (Worker A · lines 205–275)

### `SEMANTIC_SIGNAL_WEIGHTS` — add:
```python
"orm_dynamic_load": 2.5,
```

### `SEMANTIC_CRITICAL_SIGNALS` — add `"orm_dynamic_load"`.

### `SEMANTIC_EXTERNAL_IO_SIGNALS` — add `"orm_dynamic_load"`.

### `BEHAVIORAL_FLOW_STEP_ORDER` — add at position 7 (same layer as `database_io`):
```python
"orm_dynamic_load": 7,
```

**Rationale:** `orm_dynamic_load` signals that a symbol loads arbitrary DocType instances at
runtime — the exact type is determined by a string, not the type system. This is a risk signal
comparable to `database_io` in weight.

---

## ORM Regex Patterns (Worker A · define as module-level constants near line 70)

Add after `JS_LIKE_SUFFIXES`:

```python
_FRAPPE_ORM_LOAD_RE = re.compile(
    r'\bfrappe\.(?:get_doc|new_doc|get_cached_doc|get_last_doc|get_single|get_all|get_list|get_value)\s*\(\s*["\']([^"\']+)["\']',
)
_FRAPPE_DB_RE = re.compile(
    r'\bfrappe\.db\.(?:get_value|set_value|get_all|exists|count|delete|get_singles_value)\s*\(\s*["\']([^"\']+)["\']',
)
```

These are used in two places: semantic span detection and ORM edge resolution.

---

## Update `_extract_python_semantic_spans` (Worker A · line ~4987)

### A — `orm_dynamic_load` signal (unconditional, no plugin required)

Inside the per-line loop, after the existing `error_handling` block (around line 5065), add:

```python
            if re.search(r'\bfrappe\.(?:get_doc|new_doc|get_cached_doc|get_last_doc|get_single|get_all|get_list)\s*\(', text):
                self._record_semantic_ref(refs, node, "orm_dynamic_load", lineno, lineno,
                                         "Frappe ORM call loads a DocType instance dynamically.")
            elif re.search(r'\bfrappe\.db\.\w+\s*\(', text):
                self._record_semantic_ref(refs, node, "orm_dynamic_load", lineno, lineno,
                                         "Frappe low-level DB call touches the database layer.")
```

Use `elif` for the `frappe.db` branch so that `frappe.get_doc` (which is higher priority) wins
when both appear on the same line.

### B — Frappe `hooks.py` enrichment (only when plugin active)

After the `orm_dynamic_load` block above, add:

```python
            if "frappe" in self.active_plugins:
                if re.search(r'\bdoc_events\s*=\s*\{', text):
                    self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno,
                                             "Frappe doc_events hook — registers document event handlers.")
                if re.search(r'\bscheduler_events\s*=\s*\{', text):
                    self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno,
                                             "Frappe scheduler_events — registers time-driven tasks.")
                if re.search(r'\boverride_whitelisted_methods\s*=\s*\{', text):
                    self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno,
                                             "Frappe override_whitelisted_methods — alters API access control.")
```

---

## New Method: `_resolve_frappe_orm_calls` (Worker A · after `_resolve_frappe_doctype_edges`)

Place immediately after `_resolve_frappe_doctype_edges` (around line 3390):

```python
def _resolve_frappe_orm_calls(self) -> None:
    """Add orm_load edges from Python symbols to DocType nodes they load via Frappe ORM."""
    if "frappe" not in self.active_plugins:
        return
    if not self.frappe_doctype_name_to_node:
        return
    for node_id, node in self.nodes.items():
        if node.language != "Python":
            continue
        content = self._read_project_text(node.file)
        if not content:
            continue
        matched_doctypes: Set[str] = set()
        for m in _FRAPPE_ORM_LOAD_RE.finditer(content):
            matched_doctypes.add(m.group(1))
        for m in _FRAPPE_DB_RE.finditer(content):
            matched_doctypes.add(m.group(1))
        for dt_name in sorted(matched_doctypes):
            target = self.frappe_doctype_name_to_node.get(dt_name)
            if not target or target == node_id:
                continue
            outcome = self._resolution(
                target=target,
                kind="orm_load",
                confidence=0.85,
                reason=f"Frappe ORM call references DocType `{dt_name}` via string argument.",
            )
            self._add_edge(node_id, target, "orm_load", outcome)
```

---

## Wire `_resolve_frappe_orm_calls` into `_resolve_edges` (Worker A)

Inside `_resolve_edges`, after the existing call to `self._resolve_frappe_doctype_edges()`
(currently around line 3287), add immediately below:

```python
        self._resolve_frappe_orm_calls()
```

**Final order inside `_resolve_edges`:**
1. bases loop
2. calls loop
3. imports loop
4. `self._resolve_string_refs()`
5. `self._resolve_frappe_doctype_edges()`
6. `self._resolve_frappe_orm_calls()`   ← NEW
7. indegree + Ca/Ce computation

---

## Version Bump (Worker A · line 727)

```python
"version": "3.55",
```

---

## Worker B Tasks

### 1. Update `_run_sia_why` (line ~13739)

In the outgoing edges section, label `orm_load` edges distinctly. After the existing outgoing
edges block, add a check:

```python
        orm_targets = [
            e["target"] for e in report.get("edge_details", [])
            if e.get("source") == node_id and "orm_load" in e.get("kinds", [])
        ]
        if orm_targets:
            print(f"\n  ORM load targets ({len(orm_targets)}):")
            for t in sorted(orm_targets):
                print(f"    ~ {t}")
```

Use `~` as the prefix (distinct from `->` for static edges and `->` for string_refs) to indicate
a dynamic ORM load.

### 2. Update `_build_markdown_report` (line ~13636)

In the existing Frappe DocType Coupling section, update the table header to include an ORM column:

Change the table header from:
```
| DocType | Link fields | Child tables | Controller |
```
to:
```
| DocType | Link fields | Child tables | Controller | ORM callers |
```

For the ORM callers column, count inbound `orm_load` edges for each DocType node:
```python
orm_callers = len([
    e for e in report.get("edge_details", [])
    if e.get("target") == n.get("id") and "orm_load" in e.get("kinds", [])
])
orm_col = str(orm_callers) if orm_callers else "—"
```

### 3. Update `.frappe_fixture/testapp/testapp/selling/doctype/sales_order/sales_order.py`

The current fixture already contains `frappe.get_doc("Customer", self.customer)`. No change
needed — this is the primary ORM resolution test case.

Add one more ORM call to make the test richer. Update `sales_order.py` to also call
`frappe.get_all("Sales Order Item", ...)`:

```python
import frappe
from frappe.model.document import Document


class SalesOrder(Document):
    def validate(self):
        self.total = sum(row.amount for row in self.items)

    def on_submit(self):
        customer_doc = frappe.get_doc("Customer", self.customer)
        all_items = frappe.get_all("Sales Order Item", filters={"parent": self.name})
        frappe.db.set_value("Sales Order", self.name, "status", "Submitted")
```

This produces three ORM edges from `SalesOrder` to:
- `frappe.doctype.customer:customer` (via `frappe.get_doc`)
- `frappe.doctype.sales_order_item:sales_order_item` (via `frappe.get_all`)
- `frappe.doctype.sales_order:sales_order` (via `frappe.db.set_value` — self-reference, must be skipped)

The self-reference (`"Sales Order"` → its own DocType node) should be skipped by the
`target == node_id` guard in `_resolve_frappe_orm_calls`. But the calling symbol
(`SalesOrder` class) has a different node_id from the `sales_order` DocType node, so this
guard doesn't apply at the symbol level. The edge `SalesOrder class → sales_order DocType` via
`frappe.db.set_value("Sales Order", ...)` is valid and should be created.

### 4. Update README

- Change version badge `3.54` → `3.55`
- In the **Plugin: Frappe** section, extend the bullet list:
  ```
  - Resolve `frappe.get_doc(...)`, `frappe.get_all(...)`, `frappe.db.*()` calls to DocType nodes (`orm_load` edges)
  - Emit `orm_dynamic_load` semantic signal on any symbol using Frappe ORM calls
  - Enrich `hooks.py` modules with `input_boundary`, `time_or_randomness`, `auth_guard` signals
  ```

### 5. Update `CHANGES.md`

Add a Sprint 25 entry:

```markdown
## Sprint 25 — v3.55

- Frappe plugin: ORM resolution — `frappe.get_doc/new_doc/get_all/get_list/db.*` calls
  create `orm_load` edges to DocType nodes
- New semantic signal `orm_dynamic_load` (weight 2.5) — fires on Frappe ORM usage
- Frappe `hooks.py` enrichment: `doc_events` → `input_boundary`,
  `scheduler_events` → `time_or_randomness`, `override_whitelisted_methods` → `auth_guard`
```

---

## Validation Checklist (Brain)

After workers submit, Brain verifies:

1. `"orm_dynamic_load": 2.5` in `SEMANTIC_SIGNAL_WEIGHTS`.
2. `"orm_dynamic_load"` in `SEMANTIC_CRITICAL_SIGNALS` and `SEMANTIC_EXTERNAL_IO_SIGNALS`.
3. `_FRAPPE_ORM_LOAD_RE` and `_FRAPPE_DB_RE` defined at module level.
4. `_extract_python_semantic_spans` emits `orm_dynamic_load` for lines containing
   `frappe.get_doc(...)` or `frappe.db.*()`.
5. `_extract_python_semantic_spans` emits `input_boundary` for `doc_events = {` when plugin active.
6. `_extract_python_semantic_spans` emits `time_or_randomness` for `scheduler_events = {` when plugin active.
7. `_resolve_frappe_orm_calls()` exists, is called after `_resolve_frappe_doctype_edges()` in `_resolve_edges`.
8. Running SIA on `.frappe_fixture` with `--plugin frappe` produces:
   - At least 2 `orm_load` edges from `SalesOrder` to `customer` and `sales_order_item` DocType nodes
   - `orm_dynamic_load` signal on `SalesOrder` (Python class node)
   - `input_boundary` signal on `hooks.py` module node
   - `time_or_randomness` signal on `hooks.py` module node
9. Running SIA on `.frappe_fixture` **without** `--plugin frappe` produces `orm_dynamic_load`
   on `SalesOrder` (signal fires unconditionally) but zero `orm_load` edges.
10. `meta.version == "3.55"`.

---

## What Does NOT Change

- Non-Frappe projects: `orm_dynamic_load` can only appear if the source code literally contains
  `frappe.get_doc(...)` — no risk of false positives in Django/Rails/Go codebases.
- `orm_load` edges are strictly opt-in via `--plugin frappe`.
- `_resolve_string_refs()` is unchanged — DocType names with spaces are not valid dotted-path
  identifiers and are not harvested by `StringRefCollector`.
- `LANGUAGE_BY_SUFFIX` unchanged.
- All previously validated Sprint 24 behavior (DocType nodes, doctype_link/child/controller
  edges) remains intact.
