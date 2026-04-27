# SPRINT 23 — Generic String-to-Symbol Resolution (`dynamic_dispatch`)

**Version:** 3.52 → 3.53  
**File:** `god_mode_v3.py` (13 609 lines)  
**Workers:** A (lines 1–8730) · B (lines 8730–end + fixture + README)

---

## Goal

When any symbol's source body contains a string literal that looks like a dotted importable path
(`"some.module.function"`) and that path resolves to a known symbol in the graph, SIA should:

1. Add a `"string_ref"` edge from the containing symbol to the target.
2. Mark the **target** symbol with the new `dynamic_dispatch` semantic signal.

This is framework-agnostic: Frappe `hooks.py`, Django `INSTALLED_APPS`/`signals.connect()`, Celery
task name strings, Laravel service providers, and any other string-dispatch pattern are all covered
automatically with no framework-specific code.

---

## New Semantic Signal: `dynamic_dispatch`

A symbol tagged `dynamic_dispatch` is **called via a string reference somewhere in the codebase**
rather than a direct import. This is a structural risk: refactoring the symbol's qualified name
silently breaks the callers.

### Constants to add/update (Worker A · lines 206–272)

**`SEMANTIC_SIGNAL_WEIGHTS`** — add:
```python
"dynamic_dispatch": 2.0,
```

**`SEMANTIC_CRITICAL_SIGNALS`** — add `"dynamic_dispatch"` to the set.

**`BEHAVIORAL_FLOW_STEP_ORDER`** — add at position 15 (appended after `"time_or_randomness": 14`):
```python
"dynamic_dispatch": 15,
```

Do NOT add `dynamic_dispatch` to `SEMANTIC_SIDE_EFFECT_SIGNALS`, `SEMANTIC_BOUNDARY_SIGNALS`, or
`SEMANTIC_GUARD_SIGNALS` — it is a purely structural signal.

---

## New Fields on `SymbolNode` (Worker A · lines 386–427)

Add two new fields at the end of the `@dataclass SymbolNode` block, after
`behavioral_flow_summary`:

```python
raw_string_refs: Set[str] = field(default_factory=set)
resolved_string_refs: Set[str] = field(default_factory=set)
```

Also update the `SymbolNode` constructor call in `_parse_non_python_file` (line 1076) to pass
`raw_string_refs` from the payload dict:

```python
raw_string_refs=set(payload.get("raw_string_refs", set())),
```

---

## New AST Visitor: `StringRefCollector` (Worker A · after line 614)

Add immediately after the `ImportCollector` class (which ends around line 613), before the
`StructuralIntegrityAnalyzerV3` class definition:

```python
_STRING_REF_RE = re.compile(r'^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*){1,}$')

class StringRefCollector(ast.NodeVisitor):
    """Collects string literals that look like dotted importable paths."""
    def __init__(self) -> None:
        self.refs: Set[str] = set()

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            v = node.value
            if _STRING_REF_RE.match(v):
                self.refs.add(v)
        self.generic_visit(node)

    # Python <3.8 compat
    def visit_Str(self, node: ast.Str) -> None:  # type: ignore[attr-defined]
        v = node.s
        if _STRING_REF_RE.match(v):
            self.refs.add(v)
        self.generic_visit(node)

    # Do not descend into nested function/class defs (their strings belong to them)
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return
```

---

## Harvesting String Refs in Python Payloads (Worker A · lines ~900–1010)

In `_parse_python_file`, both the class-body loop and the function-body loop already produce
payloads with `raw_calls`. Add `raw_string_refs` to each payload dict.

For **class bodies** (around line 960–980), after computing `class_calls`:
```python
_src = StringRefCollector()
_src.visit(class_node)
class_string_refs = _src.refs - class_calls - raw_imports_set
```
Then add to the payload dict:
```python
"raw_string_refs": class_string_refs,
```

For **function bodies** (around line 990–1010), after computing `fn_calls`:
```python
_src = StringRefCollector()
_src.visit(fn_node)
fn_string_refs = _src.refs - fn_calls - raw_imports_set
```
Then add to the payload dict:
```python
"raw_string_refs": fn_string_refs,
```

---

## New Helper: `_harvest_string_refs` (Worker A · place near `_extract_js_like_calls`)

Add a private instance method that all non-Python extractors call:

```python
@staticmethod
def _harvest_string_refs(body: str, exclude: Optional[Set[str]] = None) -> Set[str]:
    """Return dotted-path string literals from body that look like importable paths."""
    found: Set[str] = set()
    for m in re.finditer(r'["\']([A-Za-z_]\w*(?:\.[A-Za-z_]\w*){1,})["\']', body):
        candidate = m.group(1)
        # Reject paths with version-like segments (e.g. "v2.3") or too many components (noise)
        if len(candidate.split(".")) > 8:
            continue
        found.add(candidate)
    if exclude:
        found -= exclude
    return found
```

---

## Harvesting String Refs in Non-Python Payloads (Worker A · lines ~1250–2600)

For every language's `_extract_*_symbol_payloads` method, add `"raw_string_refs"` to each
returned payload dict.  Call `self._harvest_string_refs(body, exclude=raw_calls | raw_imports)`
where `raw_calls` and `raw_imports` are the sets already computed for that payload.

Languages and their extractor methods:
- `_extract_js_like_symbol_payloads` (JS/TS) — lines ~1250–1440
- `_parse_go_module` (Go) — lines ~1440–1690
- `_parse_java_module` (Java) — lines ~1690–2000
- `_extract_csharp_symbol_payloads` — lines ~1925–2002
- `_extract_kotlin_symbol_payloads` — lines ~2002–2200
- `_extract_php_symbol_payloads` — lines ~2199–2365
- `_extract_ruby_symbol_payloads` — lines ~2386–2600

Pattern for each payload dict — add one line:
```python
"raw_string_refs": self._harvest_string_refs(body, exclude=raw_calls | raw_imports),
```

If a particular extractor builds payloads without separate `raw_calls`/`raw_imports` sets, pass
`exclude=None` and the deduplication will happen later in `_resolve_string_refs`.

---

## New Method: `_resolve_string_refs` (Worker A · insert at line 3028)

Place this method immediately after `_resolve_edges` ends (line 3027), before
`_classify_unresolved_call` (line 3029).

```python
def _resolve_string_refs(self) -> None:
    """Resolve dotted-path string literals to graph nodes and add string_ref edges."""
    for node_id, node in self.nodes.items():
        node.resolved_string_refs.clear()
        if not node.raw_string_refs:
            continue
        for raw in sorted(node.raw_string_refs):
            # Skip strings already covered by static edges
            if raw in node.raw_imports or raw in node.raw_calls:
                continue
            target = self._resolve_string_ref_target(raw, node)
            if target is None or target == node_id:
                continue
            node.resolved_string_refs.add(target)
            outcome = self._resolution(
                target=target,
                kind="string_ref",
                confidence=0.75,
                reason=f"Resolved string literal `\"{raw}\"` to symbol `{target}`.",
            )
            self._add_edge(node_id, target, "string_ref", outcome)

def _resolve_string_ref_target(self, raw: str, caller: SymbolNode) -> Optional[str]:
    """Try to match a dotted string literal against known graph symbols."""
    # 1. Exact fully-qualified match
    if raw in self.fq_to_id:
        return self.fq_to_id[raw]
    # 2. Suffix match: walk from longest suffix down to 2 components
    parts = raw.split(".")
    for length in range(len(parts) - 1, 1, -1):
        suffix = ".".join(parts[-length:])
        if suffix in self.fq_to_id:
            return self.fq_to_id[suffix]
    # 3. Short-name match on last component (only if unambiguous)
    last = parts[-1]
    candidates = self.short_index.get(last, [])
    if len(candidates) == 1:
        return candidates[0]
    return None
```

**Important:** `_resolve_string_refs()` must be called from **inside** `_resolve_edges()`, inserted
between the end of the raw-imports loop (line 3011) and the indegree computation block
(line 3013). This ensures Ca/Ce, SCC, PageRank, and betweenness all include string_ref edges.

Insert at line 3012 (between the two existing blocks):
```python
        self._resolve_string_refs()
```

---

## Injecting `dynamic_dispatch` in `_extract_semantic_signals` (Worker A · line 4509)

In `_extract_semantic_signals`, after the `elif node.language == "Ruby":` branch (line 4542),
before `refs = self._dedupe_semantic_refs(refs, limit=12)` (line 4544), add:

```python
            if node.resolved_string_refs:
                refs.append({
                    "signal": "dynamic_dispatch",
                    "file": node.file,
                    "lines": [],
                    "reason": (
                        f"Invoked via {len(node.resolved_string_refs)} dynamic string "
                        f"reference(s) — renaming this symbol silently breaks callers."
                    ),
                })
```

---

## Update `_node_payload` (Worker A · line 5581)

In the `"metrics"` dict inside `_node_payload`, add after `"heuristic_candidate_count"`:
```python
"string_ref_count": len(node.resolved_string_refs),
```

Also add a top-level key after `"semantic_signals"`:
```python
"resolved_string_refs": sorted(node.resolved_string_refs),
```

---

## Version Bump (Worker A · line 684)

```python
"version": "3.53",
```

---

## Worker B Tasks

### 1. Update `_run_sia_why` (line ~13239)

In the Coupling section of `--why` output, after the existing Ca/Ce/instability lines, add:

```
Dynamic string refs  {len(node.resolved_string_refs)} resolved target(s)
```

If `node.resolved_string_refs` is non-empty, also print the targets:
```
  → target.symbol.name
  → other.symbol.name
```

Use the same indentation style as the existing incoming-edges block.

### 2. Update `_build_markdown_report` (line ~13155)

In the top-risks table, the existing columns are already populated via `_top_risks`. No change
needed to the table structure — the `dynamic_dispatch` signal will appear automatically in the
`Semantic Signals` column because it's now part of `node.semantic_signals`.

Optionally add a footnote below the table:
```
> **dynamic_dispatch** — symbol is invoked via a string literal reference; renaming it silently breaks callers.
```

### 3. Add Fixture File: `.polyglot_graph_fixture/pyapp/hooks.py`

Create this new file to demonstrate string-ref resolution:

```python
# Frappe/Django-style hook registration using string references.
# SIA should resolve these to pyapp.ops symbols and add string_ref edges.

doc_events = {
    "SalesInvoice": {
        "on_submit": "pyapp.ops.fetch_profile",
        "validate": "pyapp.ops.read_cli_payload",
    },
}

scheduler_events = {
    "daily": "pyapp.ops.StateWriter",
}
```

The strings `"pyapp.ops.fetch_profile"`, `"pyapp.ops.read_cli_payload"`, and
`"pyapp.ops.StateWriter"` all exist in `.polyglot_graph_fixture/pyapp/ops.py` and should be
resolved to real graph nodes, producing `string_ref` edges from a `hooks` module node to each
target. The targets should receive the `dynamic_dispatch` semantic signal.

### 4. Update `README.md`

Change the version badge from `3.52` to `3.53`:
```
![Version](https://img.shields.io/badge/Version-3.53-orange)
```

---

## Validation Checklist (Brain)

After workers submit, Brain will verify:

1. `_STRING_REF_RE` is defined at module level and matches only `word.word+` patterns.
2. `StringRefCollector` is placed after `ImportCollector` and before `StructuralIntegrityAnalyzerV3`.
3. `raw_string_refs` and `resolved_string_refs` are in `SymbolNode` dataclass.
4. `_harvest_string_refs` is a `@staticmethod` or normal method, callable from all language extractors.
5. `self._resolve_string_refs()` is called inside `_resolve_edges()`, before the indegree block.
6. `_resolve_string_refs()` and `_resolve_string_ref_target()` are defined after `_resolve_edges`.
7. `dynamic_dispatch` is in `SEMANTIC_SIGNAL_WEIGHTS` and `SEMANTIC_CRITICAL_SIGNALS`.
8. `_extract_semantic_signals()` injects `dynamic_dispatch` for nodes with `resolved_string_refs`.
9. `_node_payload()` includes `string_ref_count` in metrics and `resolved_string_refs` as list.
10. `_run_sia_why()` shows resolved string ref targets.
11. `.polyglot_graph_fixture/pyapp/hooks.py` exists with the three string references.
12. `meta.version == "3.53"`.
13. Running SIA on `.polyglot_graph_fixture/` produces at least 3 `string_ref` edges and at least
    one node with `dynamic_dispatch` signal (the ops.py symbols referenced from hooks.py).

---

## What Does NOT Change

- No new CLI flag. String-ref resolution is always-on.
- `_resolve_string_ref_target` must **not** create false positives: version strings like `"1.0.0"`,
  file paths like `"src/main"`, and plain words like `"name"` must not match because
  `_STRING_REF_RE` requires each component to start with `[A-Za-z_]` and the string must have
  ≥2 components.
- The `external_io` synthetic signal logic is unchanged.
- No changes to `_tarjan_scc`, `_compute_pagerank`, or `_compute_betweenness` — they all operate
  on `self.adj` which is already populated correctly by `_resolve_edges` (which now includes
  string_ref edges before returning).
