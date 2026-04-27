# SPRINT 26 — Frappe Plugin: Polish + JS Cross-Language + Documentation

**Version:** 3.55 → 3.56  
**File:** `god_mode_v3.py` + fixture files + documentation  
**Workers:** A (version bump only) · B (everything else)

---

## Goal

Close out the three-sprint Frappe plugin series:

1. Complete the Frappe fixture with a JS client script that demonstrates cross-language
   `frappe.call()` resolution via Sprint 23's existing `string_ref` mechanism.
2. Extend `sales_order.py` to include a `frappe.get_all("Sales Order Item", ...)` call so
   the `sales_order_item` DocType node also receives an `orm_load` edge.
3. Bring all documentation (`CHANGES.md`, `WORKER_GUIDE.md`, `README.md`) fully up to date
   through Sprint 26.

No new features, no new signals, no architectural changes.

---

## Worker A — Version Bump Only (line 736)

```python
"version": "3.56",
```

That is Worker A's only task.

---

## Worker B Tasks

### 1. Update `.frappe_fixture/testapp/testapp/selling/doctype/sales_order/sales_order.py`

Add `frappe.get_all("Sales Order Item", ...)` to `on_submit` so the `sales_order_item` DocType
node receives an `orm_load` edge:

```python
import frappe
from frappe.model.document import Document


class SalesOrder(Document):
    def validate(self):
        self.total = sum(row.amount for row in self.items)

    def on_submit(self):
        customer_doc = frappe.get_doc("Customer", self.customer)
        customer_name = frappe.db.get_value("Customer", self.customer, "customer_name")
        all_items = frappe.get_all("Sales Order Item", filters={"parent": self.name})
        frappe.db.set_value("Sales Order", self.name, "status", "Submitted")
```

### 2. Add JS Client Script Fixture

Create `.frappe_fixture/testapp/testapp/selling/doctype/sales_order/sales_order_form.js`:

```javascript
// Frappe form script for Sales Order.
// SIA resolves frappe.call method strings to Python symbols via string_ref edges.

frappe.ui.form.on("Sales Order", {
    onload: function(frm) {
        frappe.call({
            method: "testapp.testapp.selling.doctype.sales_order.sales_order.SalesOrder.validate",
            args: { name: frm.doc.name }
        });
    },
    customer: function(frm) {
        frappe.call({
            method: "testapp.testapp.selling.doctype.customer.customer.Customer.on_submit",
            args: { name: frm.doc.customer }
        });
    }
});
```

The strings `"testapp.testapp.selling.doctype.sales_order.sales_order.SalesOrder.validate"` and
`"testapp.testapp.selling.doctype.customer.customer.Customer.on_submit"` match `_STRING_REF_RE`
and are harvested by `_harvest_string_refs`. `_resolve_string_refs` then resolves them to the
Python method nodes, producing `string_ref` edges from the JS module to Python symbols —
cross-language coupling visible without any Frappe-specific JS code.

### 3. Update `CHANGES.md`

Sprint 25 entry already exists but is in a non-standard format. Add clean entries for Sprints
23, 24, and 26 in the same Markdown style as Sprint 22 (the last clean entry before Sprint 23).

Append after the Sprint 22 section (around line 1220, before the Gemini-generated Sprint 25 block):

```markdown
## Sprint 23 — Generic String-to-Symbol Resolution + `dynamic_dispatch` (v3.53)

- New semantic signal `dynamic_dispatch` (weight 2.0) — fires on symbols invoked via string
  literal references; renaming silently breaks callers
- New `StringRefCollector` AST visitor harvests dotted-path string literals from Python bodies
- `_harvest_string_refs()` regex helper for all non-Python languages
- `_resolve_string_refs()` post-graph pass: matches harvested strings to known symbols, adds
  `string_ref` edges
- Called inside `_resolve_edges()` before Ca/Ce computation so coupling metrics include
  string-ref edges
- Fixture: `.polyglot_graph_fixture/pyapp/hooks.py` demonstrates Frappe/Django-style hook
  registration; 3 string_ref edges and 3 dynamic_dispatch signals on fixture run

## Sprint 24 — Frappe Plugin: Foundation + DocType JSON Parser (v3.54)

- `--plugin NAMES` CLI flag; currently supports `frappe`
- `plugin_data: Dict[str, object]` extension field on `SymbolNode` (forward-compatible)
- DocType JSON files parsed as `kind="doctype"`, `language="FrappeDocType"` graph nodes
- `doctype_link` edges for Link fields, `doctype_child` edges for Table fields
- `doctype_controller` edges resolve each DocType to its Python controller class
- Auto-detection: advisory printed to stderr when Frappe project detected without `--plugin`
- `--why` extended to show DocType info (module, Link fields, Child tables, controller path)
- Markdown report: Frappe DocType Coupling section added
- Fixture: `.frappe_fixture/` with Customer, Sales Order, Sales Order Item DocTypes

## Sprint 26 — Frappe Plugin: Polish + JS Cross-Language + Documentation (v3.56)

- Fixture `sales_order.py`: added `frappe.get_all("Sales Order Item", ...)` → `orm_load`
  edge to `sales_order_item` DocType
- New JS fixture `sales_order_form.js`: `frappe.call({method: "..."})` strings resolve to
  Python methods via Sprint 23 `string_ref` mechanism (cross-language edges, no Frappe-
  specific JS code needed)
- Documentation: `CHANGES.md`, `WORKER_GUIDE.md`, `README.md` updated through Sprint 26
```

The Gemini-generated Sprint 25 entry (starting at line 1221 with `# CHANGES — Coordinated
Development Pass`) should be **replaced** with this clean entry:

```markdown
## Sprint 25 — Frappe Plugin: ORM Resolution + Semantic Enrichment (v3.55)

- New semantic signal `orm_dynamic_load` (weight 2.5) — fires on Python symbols using
  Frappe ORM calls (`frappe.get_doc`, `frappe.get_all`, `frappe.db.*`)
- `_resolve_frappe_orm_calls()`: adds `orm_load` edges from Python callers to DocType nodes
  (only when `--plugin frappe` active)
- `_extract_python_semantic_spans`: Frappe ORM patterns emit `orm_dynamic_load`
  unconditionally; `doc_events` → `input_boundary`, `scheduler_events` →
  `time_or_randomness`, `override_whitelisted_methods` → `auth_guard` when plugin active
- `"orm_load": (0.85, "high")` added to `RESOLUTION_CONFIDENCE`
```

### 4. Update `WORKER_GUIDE.md`

Find the line that currently says:
```
- Sprint history: 24 passes (Runs 1–3 autonomous, Sprints 1–22)
```

Replace with:
```
- Sprint history: 29 passes (Runs 1–3 autonomous, Sprints 1–26)
```

Find the line listing supported languages:
```
Supported languages: Python, JavaScript/TypeScript, Go, Java, Rust, C#, Kotlin, PHP, Ruby.
```

Add after it (or update in context):
```
Optional plugin: --plugin frappe (DocType JSON, ORM resolution, hooks.py enrichment).
```

Also update any version references from `3.52` / `3.53` / `3.54` / `3.55` → `3.56`.

### 5. Update `README.md`

**Self-Analysis section** — replace the existing numbers block:
```
nodes=360  edges=616  cycles=1  parse_errors=0
```
with:
```
nodes=379  edges=657  cycles=1  parse_errors=0
```

And update the top-ranked method line:
```
Top-ranked method: `_build_ask_context_pack` (score=48.5, Ce=29, instability=0.97)
```
to:
```
Top-ranked method: `_build_ask_context_pack` (score=48.5, Ce=29, instability=0.97) — correctly identified as the most complex orchestrator in the codebase.
```
(Keep this line unchanged if it already matches — just verify.)

**JSON output example** — change `"version": "3.54"` → `"3.55"` (the example in the Output
section shows the format; it doesn't need to match the exact current version, but it should not
be two versions behind).

**Semantic signals count** — find `"14 behavioral categories"` and change to `"16 behavioral
categories"` (dynamic_dispatch and orm_dynamic_load were added in Sprints 23 and 25).

**Semantic signals block** — update:
```
network_io       database_io      filesystem_io    process_io
config_access    input_boundary   output_boundary  validation_guard
auth_guard       error_handling   serialization    deserialization
state_mutation   time_or_randomness
```
to:
```
network_io       database_io      filesystem_io    process_io
config_access    input_boundary   output_boundary  validation_guard
auth_guard       error_handling   serialization    deserialization
state_mutation   time_or_randomness  dynamic_dispatch  orm_dynamic_load
```

**Development History table** — the table currently ends with:
```
| Sprint 25 | Frappe Plugin: ORM resolution + Semantic enrichment |
```
Add:
```
| Sprint 26 | Frappe Plugin: JS cross-language, polish, documentation |
```

Also update the header line from:
```
SIA was developed in **24 passes** (3 autonomous runs + 22 directed sprints)
```
to:
```
SIA was developed in **29 passes** (3 autonomous runs + 26 directed sprints)
```

---

## Validation Checklist (Brain)

After workers submit, Brain verifies:

1. `meta.version == "3.56"` in `god_mode_v3.py` at line 736.
2. `.frappe_fixture/testapp/testapp/selling/doctype/sales_order/sales_order.py` contains
   `frappe.get_all("Sales Order Item", ...)`.
3. `.frappe_fixture/testapp/testapp/selling/doctype/sales_order/sales_order_form.js` exists
   with two `frappe.call({method: "..."})` strings.
4. Running `python god_mode_v3.py .frappe_fixture --plugin frappe --no-git-hotspots` produces:
   - At least 1 `orm_load` edge targeting `frappe.doctype.sales_order_item:sales_order_item`
   - At least 2 `string_ref` edges from the JS form script to Python method nodes
   - `parse_errors == 0`
5. `CHANGES.md` has clean entries for Sprints 23, 24, 25, 26.
6. `WORKER_GUIDE.md` says "29 passes" and mentions `--plugin frappe`.
7. `README.md` self-analysis block shows `nodes=379  edges=657`.
8. `README.md` semantic signals block includes `dynamic_dispatch` and `orm_dynamic_load`.
9. `README.md` development history says "29 passes" and Sprint 26 is in the table.

---

## What Does NOT Change

- No code changes to `god_mode_v3.py` beyond the version bump.
- All previously validated Sprint 23–25 behavior remains intact.
- `.gitignore` unchanged.
