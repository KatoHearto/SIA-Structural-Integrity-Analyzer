# SPRINT 28 — Guard Propagation: `reachable_guards` on every node

**Version:** 3.57 → 3.58  
**File:** `god_mode_v3.py`  
**Workers:** A (lines 1–8730) · B (lines 8730–end + README + CHANGES + WORKER_GUIDE)

---

## Goal

Before Sprint 29 can fire meaningful "architectural warning" rules (e.g., "unguarded DB access"),
SIA must know whether a symbol's callers already provide a guard — so a well-designed service
method that has no `@login_required` of its own but is always called from an authenticated
controller is NOT falsely flagged.

This sprint adds a single post-extraction pass:

1. Build a **reverse adjacency map** from the existing `self.adj` graph.
2. For each node, collect every `SEMANTIC_GUARD_SIGNALS` signal that appears on its **callers
   at depth 1 and depth 2**.
3. Store the result as `reachable_guards: Set[str]` on the node.
4. Surface `reachable_guards` in JSON output and `--why` display.

No new signals. No new edge kinds. No CLI flags. Pure read-only post-processing.

---

## Worker A Tasks (lines 1–8730)

### 1. Add `reachable_guards` field to `SymbolNode` (line ~454)

After the `plugin_data` field (currently the last field in `SymbolNode`):

```python
    plugin_data: Dict[str, object] = field(default_factory=dict)
    reachable_guards: Set[str] = field(default_factory=set)
```

The `Set` type is already imported (`from typing import ... Set`).

---

### 2. Wire `_propagate_guard_signals()` into the main analysis loop (line ~728)

The current call sequence in the `analyze()` / `run()` method is:

```python
        self._extract_semantic_signals()
        self._compute_risk_scores()
        self._extract_behavioral_flows()
```

Change to:

```python
        self._extract_semantic_signals()
        self._propagate_guard_signals()
        self._compute_risk_scores()
        self._extract_behavioral_flows()
```

`_propagate_guard_signals` must run **after** `_extract_semantic_signals` (it reads
`node.semantic_signals`) and **before** `_compute_risk_scores` (Sprint 29 will use
`reachable_guards` in scoring; even now it must be populated in time for the JSON report).

---

### 3. New method `_propagate_guard_signals` (place after `_populate_contained_semantics`)

Insert the following method between `_populate_contained_semantics` and
`_extract_python_semantic_spans` (i.e., after the method that ends around line 5033
and before the method that starts with `def _extract_python_semantic_spans`):

```python
    def _propagate_guard_signals(self) -> None:
        """Populate reachable_guards on each node: guard signals from callers at depth ≤ 2."""
        rev_adj: Dict[str, Set[str]] = defaultdict(set)
        for src, dsts in self.adj.items():
            for dst in dsts:
                if src != dst:
                    rev_adj[dst].add(src)

        for node_id, node in self.nodes.items():
            node.reachable_guards = set()
            depth1: Set[str] = rev_adj.get(node_id, set())
            for caller_id in depth1:
                caller = self.nodes.get(caller_id)
                if caller:
                    node.reachable_guards.update(
                        s for s in caller.semantic_signals
                        if s in SEMANTIC_GUARD_SIGNALS
                    )
            for caller_id in depth1:
                for caller2_id in rev_adj.get(caller_id, set()):
                    caller2 = self.nodes.get(caller2_id)
                    if caller2:
                        node.reachable_guards.update(
                            s for s in caller2.semantic_signals
                            if s in SEMANTIC_GUARD_SIGNALS
                        )
```

`SEMANTIC_GUARD_SIGNALS = {"validation_guard", "auth_guard", "error_handling"}` is already
defined at module level. `defaultdict` is already imported. No new imports needed.

---

### 4. Add `reachable_guards` to the full node serialization (line ~6239)

In the method that builds the per-node JSON dict (the one that contains
`"semantic_signals": list(node.semantic_signals)` around line 6239), add the field
immediately after `semantic_signals`:

```python
            "semantic_signals": list(node.semantic_signals),
            **({"reachable_guards": sorted(node.reachable_guards)} if node.reachable_guards else {}),
```

This mirrors the existing pattern used for `plugin_data`:
```python
            **({"plugin_data": dict(node.plugin_data)} if node.plugin_data else {}),
```

Omitting the key when empty keeps the JSON compact for the common case (nodes with no
guarded callers).

---

### 5. Add `reachable_guards` to `_top_risks` (line ~6299)

In `_top_risks`, the dict built per node currently ends with `behavioral_flow_steps`.
Add the new field after `"semantic_signals"`:

```python
                    "semantic_signals": list(node.semantic_signals),
                    **({"reachable_guards": sorted(node.reachable_guards)} if node.reachable_guards else {}),
                    "semantic_summary": dict(node.semantic_summary),
```

This makes the field accessible in `--why` mode (which reads from `top_risks`).

---

### 6. Version bump (line ~744)

```python
"version": "3.58",
```

---

## Worker B Tasks (lines 8730–end + docs)

### 1. Add `reachable_guards` display to `_run_sia_why` (line ~13882)

**In the `risk_entry` branch** (around line 13939–13941), after the signals display:

Find:
```python
        if signals:
            print()
            print(f"Semantic signals: {', '.join(signals)}")
    elif node_entry:
```

Replace with:
```python
        if signals:
            print()
            print(f"Semantic signals: {', '.join(signals)}")
        reachable = sorted(str(g) for g in risk_entry.get("reachable_guards", []) if g)
        if reachable:
            print(f"Guard coverage (from callers, depth ≤ 2): {', '.join(reachable)}")
    elif node_entry:
```

**In the `node_entry` branch** (around line 13962–13964), after the signals display:

Find:
```python
        if signals:
            print()
            print(f"Semantic signals: {', '.join(signals)}")

    detail_entry = node_entry if isinstance(node_entry, dict) ...
```

Replace with:
```python
        if signals:
            print()
            print(f"Semantic signals: {', '.join(signals)}")
        reachable = sorted(str(g) for g in node_entry.get("reachable_guards", []) if g)
        if reachable:
            print(f"Guard coverage (from callers, depth ≤ 2): {', '.join(reachable)}")

    detail_entry = node_entry if isinstance(node_entry, dict) ...
```

---

### 2. Update `CHANGES.md`

Add after the Sprint 27 section:

```markdown
## Sprint 28 — Guard Propagation: `reachable_guards` (v3.58)

- New `reachable_guards: Set[str]` field on every `SymbolNode`
- `_propagate_guard_signals()`: post-extraction pass that traverses the reverse call graph
  (depth ≤ 2) and collects `SEMANTIC_GUARD_SIGNALS` from callers onto each node
- Called between `_extract_semantic_signals()` and `_compute_risk_scores()` in the main loop
- Surfaces in JSON output (`reachable_guards` key, omitted when empty) and `--why` display
- Foundation for Sprint 29 architectural combination-rule warnings
```

### 3. Update `WORKER_GUIDE.md`

Find:
```
- Sprint history: 30 passes (Runs 1–3 autonomous, Sprints 1–27)
```
Replace with:
```
- Sprint history: 31 passes (Runs 1–3 autonomous, Sprints 1–28)
```

Update version reference `3.57` → `3.58`.

### 4. Update `README.md`

**Development History table** — add:
```
| Sprint 28 | Guard propagation: `reachable_guards` from callers (depth ≤ 2) |
```

**Passes line** — update:
```
SIA was developed in **31 passes** (3 autonomous runs + 28 directed sprints)
```

---

## Validation Checklist (Brain)

After workers submit, Brain verifies:

1. `SymbolNode` has `reachable_guards: Set[str] = field(default_factory=set)` after `plugin_data`.
2. `_propagate_guard_signals` method exists and uses `rev_adj` + `SEMANTIC_GUARD_SIGNALS`.
3. Call order in main loop: `_extract_semantic_signals()` → `_propagate_guard_signals()` →
   `_compute_risk_scores()`.
4. Node JSON serialization includes `reachable_guards` (conditionally).
5. `_top_risks` output includes `reachable_guards` (conditionally).
6. `meta.version == "3.58"`.
7. Running SIA on `.polyglot_graph_fixture` produces `parse_errors == 0`.
8. A node that is ONLY called from nodes with `auth_guard` should show `auth_guard` in
   `reachable_guards` in the JSON output.
9. `--why` for such a node prints `"Guard coverage (from callers, depth ≤ 2): auth_guard"`.
10. `CHANGES.md` has Sprint 28 entry.
11. `WORKER_GUIDE.md` says "31 passes".
12. `README.md` development history has Sprint 28 row.

---

## What Does NOT Change

- No new semantic signals.
- No new edge kinds or CLI flags.
- `SEMANTIC_GUARD_SIGNALS` definition unchanged — propagation uses the existing set.
- All Sprint 27 behavior (concurrency, caching signals) remains intact.
- `reachable_guards` is populated but NOT yet used in `_compute_risk_scores` — that is Sprint 29's job.
- A node's own `semantic_signals` are not modified; `reachable_guards` is strictly additive.
