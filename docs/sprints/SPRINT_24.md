# SPRINT 24 — Frappe Plugin: Foundation + DocType JSON Parser

**Version:** 3.53 → 3.54  
**File:** `god_mode_v3.py` (13 609+ lines)  
**Workers:** A (lines 1–8730) · B (lines 8730–end + fixture + README)

---

## Goal

Add an optional Frappe plugin (`--plugin frappe`) that:

1. Scans Frappe DocType JSON files and creates `kind="doctype"` graph nodes.
2. Extracts Link-field → DocType dependencies and Child-table → DocType dependencies as edges.
3. Resolves each DocType to its Python controller file and adds a `doctype_controller` edge.
4. Builds two new internal indices (`frappe_doctype_name_to_node`,
   `frappe_doctype_snake_to_node`) needed by the ORM resolver in Sprint 25.

No Frappe-specific code runs unless `--plugin frappe` is passed. Zero overhead for non-Frappe
projects.

---

## New Field on `SymbolNode` (Worker A · after line ~433)

Add one field at the very end of the `@dataclass SymbolNode` block, after
`behavioral_flow_summary`:

```python
plugin_data: Dict[str, object] = field(default_factory=dict)
```

This is the forward-compatible extension point for all plugin data. No Frappe-specific fields on
the dataclass itself.

---

## Changes to `__init__` (Worker A · line 652)

Add a new parameter and three new instance attributes:

**Parameter** (add after `filter_languages`):
```python
plugins: Optional[List[str]] = None,
```

**Instance attributes** (add after `self.filter_languages = ...` on line 680):
```python
self.active_plugins: Set[str] = set(p.lower() for p in (plugins or []))
self.frappe_doctype_name_to_node: Dict[str, str] = {}   # "Sales Invoice" -> node_id
self.frappe_doctype_snake_to_node: Dict[str, str] = {}  # "sales_invoice"  -> node_id
```

---

## Changes to `_scan_files` (Worker A · line 766)

At the end of `_scan_files`, after the existing `os.walk` loop, add:

```python
        if "frappe" in self.active_plugins:
            self._scan_frappe_json_files()
```

---

## New Method: `_detect_frappe_project` (Worker A · after `_discover_js_resolver_configs`)

```python
def _detect_frappe_project(self) -> bool:
    """Return True if root looks like a Frappe bench or app."""
    for name in ("apps.txt", "sites/apps.txt"):
        if os.path.isfile(os.path.join(self.root_dir, name)):
            return True
    for name in ("pyproject.toml", "requirements.txt", "setup.py"):
        path = os.path.join(self.root_dir, name)
        if os.path.isfile(path):
            try:
                content = open(path, encoding="utf-8").read()
                if "frappe" in content.lower():
                    return True
            except OSError:
                pass
    return False
```

Call this from `_scan_files` — if `"frappe"` is NOT in `self.active_plugins` but
`_detect_frappe_project()` returns True, print exactly one advisory line:

```python
            print(
                "[SIA] Frappe project detected. Re-run with --plugin frappe for DocType analysis.",
                file=sys.stderr,
            )
```

Print it only once (use a guard: `if "frappe" not in self.active_plugins and self._detect_frappe_project():`)

---

## New Method: `_scan_frappe_json_files` (Worker A · after `_detect_frappe_project`)

```python
def _scan_frappe_json_files(self) -> None:
    """Walk the project and register all Frappe DocType JSON files as graph nodes."""
    import fnmatch as _fnmatch
    norm_excludes = [p.rstrip("/\\") for p in self.exclude_globs]
    for root, dirs, files in os.walk(self.root_dir):
        dirs[:] = [d for d in dirs if not should_ignore_dir(d)]
        if norm_excludes:
            dirs[:] = [d for d in dirs if not any(_fnmatch.fnmatch(d, p) for p in norm_excludes)]
        for file_name in files:
            if not file_name.endswith(".json"):
                continue
            full_path = os.path.join(root, file_name)
            rel_path = os.path.relpath(full_path, self.root_dir)
            try:
                with open(full_path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            if data.get("doctype") != "DocType":
                continue
            self._parse_frappe_doctype_file(rel_path, data)
```

---

## New Method: `_parse_frappe_doctype_file` (Worker A · after `_scan_frappe_json_files`)

```python
@staticmethod
def _frappe_snake(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")

def _parse_frappe_doctype_file(self, rel_path: str, data: Dict[str, object]) -> None:
    """Register a Frappe DocType JSON as a graph node."""
    dt_name: str = str(data.get("name", ""))
    if not dt_name:
        return
    dt_snake = self._frappe_snake(dt_name)
    dt_module: str = str(data.get("module", ""))

    # Derive controller path: same directory, same snake_name, .py extension.
    # e.g. app/module/doctype/sales_order/sales_order.json
    #   -> app/module/doctype/sales_order/sales_order.py
    controller_path = str(Path(rel_path).with_suffix(".py").as_posix())
    # The stem of the file must match snake_name to be a valid controller path.
    if Path(rel_path).stem != dt_snake:
        controller_path = str(
            (Path(rel_path).parent / f"{dt_snake}.py").as_posix()
        )

    # Collect link and child-table references (DocType names, may contain spaces).
    link_refs: List[str] = []
    child_refs: List[str] = []
    for field_def in data.get("fields", []):
        if not isinstance(field_def, dict):
            continue
        ftype = str(field_def.get("fieldtype", ""))
        opts = str(field_def.get("options", "")).strip()
        if not opts:
            continue
        if ftype == "Link":
            link_refs.append(opts)
        elif ftype in ("Table", "Table MultiSelect"):
            child_refs.append(opts)

    node_id = f"frappe.doctype.{dt_snake}:{dt_snake}"
    module = f"frappe.doctype.{dt_snake}"
    qualname = dt_snake

    node = SymbolNode(
        node_id=node_id,
        module=module,
        qualname=qualname,
        kind="doctype",
        language="FrappeDocType",
        file=rel_path,
        lines=[1, 1],
        plugin_data={
            "frappe_doctype_name": dt_name,
            "frappe_module": dt_module,
            "frappe_snake": dt_snake,
            "frappe_link_refs": link_refs,
            "frappe_child_refs": child_refs,
            "frappe_controller_path": controller_path,
            "frappe_is_single": bool(data.get("issingle")),
            "frappe_is_virtual": bool(data.get("is_virtual")),
        },
    )
    self.nodes[node_id] = node
    self.frappe_doctype_name_to_node[dt_name] = node_id
    self.frappe_doctype_snake_to_node[dt_snake] = node_id
```

---

## Changes to `_build_indices` (Worker A · line ~2875)

At the end of `_build_indices`, after the existing loop, add DocType nodes to the standard
lookup indices so that `_resolve_string_refs` can find them by name:

```python
        for dt_name, nid in self.frappe_doctype_name_to_node.items():
            # Register by snake_name in fq_to_id for string-ref resolution
            snake = self._frappe_snake(dt_name)
            self.fq_to_id[snake] = nid
            self.fq_to_id[dt_name] = nid           # exact name match (for ORM in Sprint 25)
            self.short_index[snake].append(nid)
```

---

## New Method: `_resolve_frappe_doctype_edges` (Worker A · after `_resolve_string_refs`)

Place this method immediately after `_resolve_string_ref_target` (around line 3220):

```python
def _resolve_frappe_doctype_edges(self) -> None:
    """Add edges from DocType nodes to linked DocTypes and their controllers."""
    if "frappe" not in self.active_plugins:
        return
    for node_id, node in list(self.nodes.items()):
        if node.kind != "doctype":
            continue
        pd = node.plugin_data

        # DocType → linked DocType (Link fields)
        for ref_name in pd.get("frappe_link_refs", []):
            target = self.frappe_doctype_name_to_node.get(ref_name)
            if target and target != node_id:
                outcome = self._resolution(
                    target=target,
                    kind="doctype_link",
                    confidence=1.0,
                    reason=f"Link field references DocType `{ref_name}`.",
                )
                self._add_edge(node_id, target, "doctype_link", outcome)

        # DocType → child DocType (Table fields)
        for ref_name in pd.get("frappe_child_refs", []):
            target = self.frappe_doctype_name_to_node.get(ref_name)
            if target and target != node_id:
                outcome = self._resolution(
                    target=target,
                    kind="doctype_child",
                    confidence=1.0,
                    reason=f"Table field embeds child DocType `{ref_name}`.",
                )
                self._add_edge(node_id, target, "doctype_child", outcome)

        # DocType → Python controller module node
        ctrl_path = str(pd.get("frappe_controller_path", ""))
        if ctrl_path:
            target = self.file_module_node.get(ctrl_path)
            if not target:
                # Try OS-style path as fallback
                target = self.file_module_node.get(ctrl_path.replace("/", os.sep))
            if target and target != node_id:
                outcome = self._resolution(
                    target=target,
                    kind="doctype_controller",
                    confidence=0.9,
                    reason=f"Conventional Frappe controller path `{ctrl_path}`.",
                )
                self._add_edge(node_id, target, "doctype_controller", outcome)
```

---

## Wire `_resolve_frappe_doctype_edges` into `_resolve_edges` (Worker A)

In `_resolve_edges`, after the call to `self._resolve_string_refs()` (currently around line 3158)
and before the indegree computation block, add:

```python
        self._resolve_frappe_doctype_edges()
```

**Order inside `_resolve_edges` must be:**
1. bases loop
2. calls loop
3. imports loop
4. `self._resolve_string_refs()`
5. `self._resolve_frappe_doctype_edges()`   ← NEW
6. indegree + Ca/Ce computation

---

## Update `_node_payload` (Worker A · line ~5581)

In `_node_payload`, add a top-level key after `"resolved_string_refs"`:

```python
            **({"plugin_data": dict(node.plugin_data)} if node.plugin_data else {}),
```

This emits `plugin_data` only when non-empty, keeping the output clean for non-Frappe nodes.

---

## Worker B Tasks

### 1. Add `--plugin` CLI argument (`main()` · line ~13645)

After the `--filter-language` argument block (~line 13730), add:

```python
    parser.add_argument(
        "--plugin",
        default="",
        metavar="NAMES",
        help=(
            "Comma-separated plugin names to activate (e.g. 'frappe'). "
            "Currently supported: frappe."
        ),
    )
```

In the analyzer construction block (~line 13805), change:

```python
    analyzer = StructuralIntegrityAnalyzerV3(
        args.root,
        exclude_globs=args.exclude or [],
        filter_languages=_filter_langs,
        plugins=[p.strip() for p in args.plugin.split(",") if p.strip()] if args.plugin else None,
    )
```

### 2. Update `_run_sia_why` (line ~13239)

After the existing Coupling section, add a Frappe block for `kind="doctype"` nodes:

```python
        if node_entry.get("kind") == "doctype":
            pd = node_entry.get("plugin_data", {})
            print(f"\nFrappe DocType: {pd.get('frappe_doctype_name', '')}  "
                  f"module={pd.get('frappe_module', '')}  "
                  f"single={pd.get('frappe_is_single', False)}  "
                  f"virtual={pd.get('frappe_is_virtual', False)}")
            link_refs = pd.get("frappe_link_refs", [])
            child_refs = pd.get("frappe_child_refs", [])
            if link_refs:
                print(f"  Link fields → {', '.join(link_refs)}")
            if child_refs:
                print(f"  Child tables → {', '.join(child_refs)}")
            ctrl = pd.get("frappe_controller_path", "")
            if ctrl:
                print(f"  Controller: {ctrl}")
```

### 3. Update `_build_markdown_report` (line ~13155)

At the end of the report (before the final `return lines` / `return "\n".join(lines)`), add a
Frappe DocType section if any doctype nodes are present in the report:

```python
    doctype_nodes = [
        n for n in report.get("nodes", [])
        if n.get("kind") == "doctype"
    ]
    if doctype_nodes:
        lines.append("\n## Frappe DocType Coupling\n")
        lines.append("| DocType | Link fields | Child tables | Controller |")
        lines.append("|---------|------------|--------------|------------|")
        for n in sorted(doctype_nodes, key=lambda x: x.get("qualname", "")):
            pd = n.get("plugin_data", {})
            name = pd.get("frappe_doctype_name", n.get("qualname", ""))
            links = ", ".join(pd.get("frappe_link_refs", [])) or "—"
            children = ", ".join(pd.get("frappe_child_refs", [])) or "—"
            ctrl = pd.get("frappe_controller_path", "—")
            lines.append(f"| {name} | {links} | {children} | `{ctrl}` |")
```

### 4. Create Fixture Directory `.frappe_fixture/`

Create the following files. The fixture models a minimal Frappe app called `testapp` with three
DocTypes: **Customer**, **Sales Order** (links to Customer, has child table), and
**Sales Order Item** (child DocType).

**`.frappe_fixture/apps.txt`**
```
testapp
```

**`.frappe_fixture/testapp/testapp/selling/doctype/customer/customer.json`**
```json
{
  "doctype": "DocType",
  "name": "Customer",
  "module": "Selling",
  "fields": [
    {"fieldtype": "Data", "fieldname": "customer_name", "label": "Customer Name"},
    {"fieldtype": "Link", "fieldname": "customer_group", "label": "Customer Group", "options": "Customer Group"},
    {"fieldtype": "Link", "fieldname": "territory", "label": "Territory", "options": "Territory"}
  ],
  "issingle": 0,
  "is_virtual": 0
}
```

**`.frappe_fixture/testapp/testapp/selling/doctype/customer/customer.py`**
```python
import frappe
from frappe.model.document import Document


class Customer(Document):
    def validate(self):
        if not self.customer_name:
            frappe.throw("Customer Name is required")

    def on_submit(self):
        frappe.db.set_value("Customer", self.name, "status", "Active")
```

**`.frappe_fixture/testapp/testapp/selling/doctype/sales_order/sales_order.json`**
```json
{
  "doctype": "DocType",
  "name": "Sales Order",
  "module": "Selling",
  "fields": [
    {"fieldtype": "Link", "fieldname": "customer", "label": "Customer", "options": "Customer"},
    {"fieldtype": "Table", "fieldname": "items", "label": "Items", "options": "Sales Order Item"},
    {"fieldtype": "Currency", "fieldname": "total", "label": "Total"}
  ],
  "issingle": 0,
  "is_virtual": 0
}
```

**`.frappe_fixture/testapp/testapp/selling/doctype/sales_order/sales_order.py`**
```python
import frappe
from frappe.model.document import Document


class SalesOrder(Document):
    def validate(self):
        self.total = sum(row.amount for row in self.items)

    def on_submit(self):
        customer_doc = frappe.get_doc("Customer", self.customer)
        frappe.db.set_value("Sales Order", self.name, "status", "Submitted")
```

**`.frappe_fixture/testapp/testapp/selling/doctype/sales_order_item/sales_order_item.json`**
```json
{
  "doctype": "DocType",
  "name": "Sales Order Item",
  "module": "Selling",
  "fields": [
    {"fieldtype": "Data", "fieldname": "item_code", "label": "Item Code"},
    {"fieldtype": "Float", "fieldname": "qty", "label": "Quantity"},
    {"fieldtype": "Currency", "fieldname": "rate", "label": "Rate"},
    {"fieldtype": "Currency", "fieldname": "amount", "label": "Amount"}
  ],
  "issingle": 0,
  "is_virtual": 0
}
```

**`.frappe_fixture/testapp/testapp/selling/doctype/sales_order_item/sales_order_item.py`**
```python
from frappe.model.document import Document


class SalesOrderItem(Document):
    def validate(self):
        self.amount = (self.qty or 0) * (self.rate or 0)
```

**`.frappe_fixture/testapp/testapp/hooks.py`**
```python
app_name = "testapp"
app_title = "Test App"

doc_events = {
    "Sales Order": {
        "on_submit": "testapp.testapp.selling.doctype.sales_order.sales_order.on_submit_hook",
        "validate": "testapp.testapp.selling.doctype.sales_order.sales_order.validate_hook",
    },
    "Customer": {
        "after_insert": "testapp.testapp.selling.doctype.customer.customer.after_insert_hook",
    },
}

scheduler_events = {
    "daily": [
        "testapp.testapp.selling.doctype.customer.customer.daily_cleanup",
    ]
}
```

Also add `.frappe_fixture/` to `.gitignore` (it can stay — it is fixture data like `.polyglot_graph_fixture`). But add `.frappe_fixture/` as an exclusion in `.siaignore` if the user adds one, since SIA's own self-analysis should not scan it.

### 5. Update `.gitignore`

No change needed — `.frappe_fixture/` should be committed (it's a test fixture, not runtime output).

### 6. Version Bump (line 719)

```python
"version": "3.54",
```

### 7. Update `README.md`

- Change version badge `3.53` → `3.54`
- Update semantic signals count from "14" to "15" (dynamic_dispatch was added in Sprint 23)
- Add `--plugin` row to CLI Reference table:

```
| `--plugin NAMES` | — | Activate optional plugins (currently: `frappe`) |
```

- Add a new section **Plugin: Frappe** after the `.siaignore` section:

```markdown
## Plugin: Frappe

Activate with `--plugin frappe` to parse Frappe DocType JSON definitions:

```bash
python god_mode_v3.py ./my-frappe-app --plugin frappe
```

SIA will:
- Create `kind="doctype"` graph nodes for every DocType JSON found
- Add `doctype_link` edges for Link fields and `doctype_child` edges for Table fields
- Resolve each DocType to its Python controller via the Frappe path convention
- Detect `hooks.py` string references automatically (via Sprint 23 string-ref resolution)

If SIA detects a Frappe project without the flag, it prints an advisory to stderr.
```

---

## Validation Checklist (Brain)

After workers submit, Brain verifies:

1. `plugin_data: Dict[str, object]` field exists on `SymbolNode`.
2. `__init__` accepts `plugins=` parameter; `self.active_plugins`, `self.frappe_doctype_name_to_node`, `self.frappe_doctype_snake_to_node` are initialized.
3. `_detect_frappe_project()` exists and checks `apps.txt` and text file content.
4. `_scan_frappe_json_files()` exists, only called when `"frappe" in self.active_plugins`.
5. `_parse_frappe_doctype_file()` creates a `SymbolNode` with `kind="doctype"`, `language="FrappeDocType"`, and populates both `frappe_doctype_name_to_node` and `frappe_doctype_snake_to_node`.
6. `_build_indices` registers DocType nodes in `fq_to_id` and `short_index`.
7. `_resolve_frappe_doctype_edges()` is called from within `_resolve_edges()` **after** `_resolve_string_refs()` and **before** the indegree block.
8. `_node_payload()` emits `plugin_data` when non-empty.
9. `--plugin` CLI flag exists, is parsed, and passed to the analyzer constructor.
10. `_run_sia_why` handles `kind="doctype"` nodes.
11. `_build_markdown_report` has a Frappe DocType Coupling section.
12. All six `.frappe_fixture/` files exist with correct content.
13. Running `python god_mode_v3.py .frappe_fixture --plugin frappe --no-git-hotspots --summary-only` produces:
    - At least 3 DocType nodes (Customer, Sales Order, Sales Order Item)
    - At least 2 `doctype_link` edges (Sales Order → Customer)
    - At least 1 `doctype_child` edge (Sales Order → Sales Order Item)
    - At least 3 `doctype_controller` edges (one per DocType)
    - parse_errors = 0
14. `meta.version == "3.54"`.

---

## What Does NOT Change

- `LANGUAGE_BY_SUFFIX` — `.json` is NOT added to it. DocType files are scanned via a separate plugin-specific walk.
- `_filter_languages` logic — `FrappeDocType` language is NOT subject to `--filter-language`.
- The standard import/call/string-ref resolution pipeline — DocType edges bypass it entirely via `_resolve_frappe_doctype_edges`.
- Self-analysis results — running SIA on `god_mode_v3.py` without `--plugin frappe` is unchanged.
