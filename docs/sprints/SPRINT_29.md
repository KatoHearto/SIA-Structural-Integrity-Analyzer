# SPRINT 29 — Architectural Warnings: Combination-Rule Engine

**Version:** 3.58 → 3.59  
**File:** `god_mode_v3.py`  
**Workers:** A (lines 1–8730) · B (lines 8730–end + README + CHANGES + WORKER_GUIDE)

---

## Goal

SIA can now detect dangerous signal *combinations* per symbol and surface them as named
architectural warnings — distinct from the raw signal list and the risk score. A warning
fires when a node's own semantic signals and its `reachable_guards` (Sprint 28) match a
predefined anti-pattern rule.

Sprint 29 implements:

1. Two new private methods: `_evaluate_arch_rules` (per-node) and
   `_compute_architectural_warnings` (iterates all nodes).
2. A new field `architectural_warnings` on `SymbolNode`.
3. The 8 canonical anti-pattern rules (see below).
4. Output: `"architectural_warnings"` top-level JSON key + per-node inline field +
   Markdown section + `--why` display.

No new signals. No new edge kinds. No CLI flags. No changes to risk scoring.

---

## The 8 Rules

| ID | Severity | Trigger |
|----|----------|---------|
| `unguarded_entry` | critical | `input_boundary` present AND neither `auth_guard` nor `validation_guard` anywhere in own signals or `reachable_guards` |
| `untrusted_deserialization` | critical | `deserialization` present AND `validation_guard` absent in own signals and `reachable_guards` |
| `concurrent_mutation` | high | `concurrency` + `state_mutation` both present AND `error_handling` absent from own signals |
| `cache_coherence_risk` | high | `caching` + `state_mutation` + `concurrency` all present in own signals |
| `open_network_call` | high | `network_io` present AND `error_handling` absent from both own signals and `reachable_guards` |
| `unguarded_db_write` | high | `database_io` + `state_mutation` both present AND `auth_guard` absent in own signals and `reachable_guards` |
| `double_indirection` | medium | `orm_dynamic_load` + `dynamic_dispatch` both present in own signals |
| `stateful_input_boundary` | medium | `input_boundary` + `state_mutation` both present AND `validation_guard` absent from own signals (reachable not checked here — validation of input must be local) |

---

## Worker A Tasks (lines 1–8730)

### 1. Add `architectural_warnings` field to `SymbolNode` (line ~455)

After `reachable_guards`:

```python
    reachable_guards: Set[str] = field(default_factory=set)
    architectural_warnings: List[Dict[str, object]] = field(default_factory=list)
```

`List` and `Dict` are already imported from `typing`.

---

### 2. Wire into main analysis loop (line ~729)

Current sequence:
```python
        self._extract_semantic_signals()
        self._propagate_guard_signals()
        self._compute_risk_scores()
        self._extract_behavioral_flows()
```

Change to:
```python
        self._extract_semantic_signals()
        self._propagate_guard_signals()
        self._compute_architectural_warnings()
        self._compute_risk_scores()
        self._extract_behavioral_flows()
```

`_compute_architectural_warnings` must run after `_propagate_guard_signals`
(needs `reachable_guards`) and before `_compute_risk_scores` (warnings must be
populated before the JSON report is assembled).

---

### 3. New methods — place after `_propagate_guard_signals` ends, before `_extract_python_semantic_spans` begins

Insert both methods in that gap:

```python
    def _evaluate_arch_rules(self, node: "SymbolNode") -> List[Dict[str, object]]:
        """Return architectural-warning dicts for every anti-pattern rule that fires."""
        if not node.semantic_signals:
            return []
        warnings: List[Dict[str, object]] = []
        own: Set[str] = set(node.semantic_signals)
        reach: Set[str] = node.reachable_guards
        all_guards: Set[str] = own | reach

        if "input_boundary" in own:
            if "auth_guard" not in all_guards and "validation_guard" not in all_guards:
                warnings.append({
                    "rule": "unguarded_entry",
                    "severity": "critical",
                    "message": (
                        "Accepts external input without authentication or validation guard "
                        "anywhere in the 2-level call chain."
                    ),
                })

        if "deserialization" in own and "validation_guard" not in all_guards:
            warnings.append({
                "rule": "untrusted_deserialization",
                "severity": "critical",
                "message": (
                    "Deserializes external data without a validation guard — "
                    "classic injection or RCE risk."
                ),
            })

        if "concurrency" in own and "state_mutation" in own and "error_handling" not in own:
            warnings.append({
                "rule": "concurrent_mutation",
                "severity": "high",
                "message": (
                    "Concurrent execution combined with mutable state and no error handling — "
                    "race condition or deadlock risk."
                ),
            })

        if "caching" in own and "state_mutation" in own and "concurrency" in own:
            warnings.append({
                "rule": "cache_coherence_risk",
                "severity": "high",
                "message": (
                    "Cache writes combined with concurrent state mutation — "
                    "stale reads or write-after-write conflicts possible."
                ),
            })

        if "network_io" in own and "error_handling" not in own and "error_handling" not in reach:
            warnings.append({
                "rule": "open_network_call",
                "severity": "high",
                "message": (
                    "Outbound network call with no error handling in this symbol or its callers — "
                    "failures propagate silently."
                ),
            })

        if "database_io" in own and "state_mutation" in own and "auth_guard" not in all_guards:
            warnings.append({
                "rule": "unguarded_db_write",
                "severity": "high",
                "message": (
                    "Writes to the database without an authentication guard "
                    "in this symbol or its callers."
                ),
            })

        if "orm_dynamic_load" in own and "dynamic_dispatch" in own:
            warnings.append({
                "rule": "double_indirection",
                "severity": "medium",
                "message": (
                    "Dynamic ORM load combined with string-based dispatch — "
                    "two layers of runtime indirection make this symbol hard to trace statically."
                ),
            })

        if "input_boundary" in own and "state_mutation" in own and "validation_guard" not in own:
            warnings.append({
                "rule": "stateful_input_boundary",
                "severity": "medium",
                "message": (
                    "Mutates state from an external input boundary without first validating "
                    "the input — save-before-validate pattern."
                ),
            })

        return warnings

    def _compute_architectural_warnings(self) -> None:
        """Populate architectural_warnings on every node by evaluating all anti-pattern rules."""
        for node in self.nodes.values():
            node.architectural_warnings = self._evaluate_arch_rules(node)
```

---

### 4. Add `architectural_warning_count` to `meta` dict (line ~745)

In the `"meta"` dict inside the report, add after `"parse_error_count"`:

```python
                "parse_error_count": len(self.parse_errors),
                "architectural_warning_count": sum(
                    len(n.architectural_warnings) for n in self.nodes.values()
                ),
                "ask_query_present": bool(ask_context_pack),
```

---

### 5. Add top-level `"architectural_warnings"` to the report dict (line ~764)

In the report dict, add after `"parse_errors": self.parse_errors,`:

```python
            "parse_errors": self.parse_errors,
            "architectural_warnings": [
                {
                    "node_id": node.node_id,
                    "language": node.language,
                    "kind": node.kind,
                    "file": node.file,
                    "warnings": list(node.architectural_warnings),
                }
                for node in sorted(self.nodes.values(), key=lambda n: n.node_id)
                if node.architectural_warnings
            ],
```

---

### 6. Add `architectural_warnings` to node serialization (line ~6269)

After the `reachable_guards` line in `_node_payload`:

```python
            **({"reachable_guards": sorted(node.reachable_guards)} if node.reachable_guards else {}),
            **({"architectural_warnings": list(node.architectural_warnings)} if node.architectural_warnings else {}),
```

---

### 7. Add `architectural_warnings` to `_top_risks` (line ~6330)

After the `reachable_guards` line in `_top_risks`:

```python
                    **({"reachable_guards": sorted(node.reachable_guards)} if node.reachable_guards else {}),
                    **({"architectural_warnings": list(node.architectural_warnings)} if node.architectural_warnings else {}),
```

---

### 8. Version bump (line ~746)

```python
"version": "3.59",
```

---

## Worker B Tasks (lines 8730–end + docs)

### 1. Add Architectural Warnings section to `_build_markdown_report` (line ~13908)

Insert before `return "\n".join(lines)` (i.e., after the existing Frappe DocType section):

```python
    arch_warnings: List[Dict[str, object]] = report.get("architectural_warnings", [])
    if arch_warnings:
        total = sum(len(entry.get("warnings", [])) for entry in arch_warnings)
        lines.append("\n## Architectural Warnings\n")
        lines.append(
            f"**{total} warning{'s' if total != 1 else ''} across "
            f"{len(arch_warnings)} symbol{'s' if len(arch_warnings) != 1 else ''}.**\n"
        )
        lines.append("| Severity | Symbol | Rule | Message |")
        lines.append("|----------|--------|------|---------|")
        _sev_order = {"critical": 0, "high": 1, "medium": 2}
        rows = []
        for entry in arch_warnings:
            sym = str(entry.get("node_id", ""))
            for w in entry.get("warnings", []):
                sev = str(w.get("severity", "medium"))
                rows.append((
                    _sev_order.get(sev, 99),
                    sym,
                    sev,
                    str(w.get("rule", "")),
                    str(w.get("message", "")),
                ))
        rows.sort()
        for _, sym, sev, rule, msg in rows:
            lines.append(f"| **{sev}** | `{sym}` | `{rule}` | {msg} |")
        lines.append("")
```

---

### 2. Add warnings display to `_run_sia_why` (line ~14041)

Insert before the closing `print(sep)` line (after the cycles section):

```python
    arch_warnings_for_symbol: List[Dict[str, object]] = []
    for aw in report.get("architectural_warnings", []):
        if str(aw.get("node_id", "")) == symbol:
            arch_warnings_for_symbol = list(aw.get("warnings", []))
            break
    if not arch_warnings_for_symbol and detail_entry:
        arch_warnings_for_symbol = list(detail_entry.get("architectural_warnings", []))
    if arch_warnings_for_symbol:
        print()
        print(f"Architectural Warnings ({len(arch_warnings_for_symbol)}):")
        for w in arch_warnings_for_symbol:
            sev = str(w.get("severity", "?")).upper()
            rule = str(w.get("rule", ""))
            msg = str(w.get("message", ""))
            print(f"  [{sev}] {rule}: {msg}")
```

---

### 3. Update `CHANGES.md`

Add after the Sprint 28 section:

```markdown
## Sprint 29 — Architectural Warnings: Combination-Rule Engine (v3.59)

- New `architectural_warnings: List[Dict]` field on `SymbolNode`
- `_evaluate_arch_rules()`: evaluates 8 anti-pattern rules using own signals + `reachable_guards`
- `_compute_architectural_warnings()`: iterates all nodes, called between guard propagation
  and risk scoring
- 8 rules: `unguarded_entry`, `untrusted_deserialization` (critical); `concurrent_mutation`,
  `cache_coherence_risk`, `open_network_call`, `unguarded_db_write` (high);
  `double_indirection`, `stateful_input_boundary` (medium)
- `"architectural_warnings"` top-level key in JSON report and per-node in `nodes[]`
- `meta.architectural_warning_count` added
- Markdown report: Architectural Warnings table (severity-sorted)
- `--why`: shows warnings for the queried symbol
```

### 4. Update `WORKER_GUIDE.md`

Find:
```
- Sprint history: 31 passes (Runs 1–3 autonomous, Sprints 1–28)
```
Replace with:
```
- Sprint history: 32 passes (Runs 1–3 autonomous, Sprints 1–29)
```

Update version reference `3.58` → `3.59`.

### 5. Update `README.md`

**Development History table** — add:
```
| Sprint 29 | Architectural warnings: 8 combination-rule anti-patterns |
```

**Passes line** — update:
```
SIA was developed in **32 passes** (3 autonomous runs + 29 directed sprints)
```

---

## Validation Checklist (Brain)

After workers submit, Brain verifies:

1. `SymbolNode` has `architectural_warnings: List[Dict[str, object]] = field(default_factory=list)`.
2. `_evaluate_arch_rules` method exists; contains all 8 rule blocks with correct severity labels.
3. `_compute_architectural_warnings` method exists and calls `_evaluate_arch_rules`.
4. Call order: `_propagate_guard_signals()` → `_compute_architectural_warnings()` → `_compute_risk_scores()`.
5. `meta.architectural_warning_count` key present in report.
6. Top-level `"architectural_warnings"` key present in report.
7. Per-node `"architectural_warnings"` present conditionally in `_node_payload` and `_top_risks`.
8. `meta.version == "3.59"`.
9. Running SIA on `.polyglot_graph_fixture` produces `parse_errors == 0`.
10. Running SIA on `.frappe_fixture --plugin frappe` produces at least 1 architectural warning
    (the `SalesOrder.on_submit` method has `database_io` + `state_mutation` with no auth guard
    anywhere — should trigger `unguarded_db_write`).
11. Markdown report includes `## Architectural Warnings` section when warnings exist.
12. `--why SalesOrder.on_submit <report>` prints `[HIGH] unguarded_db_write: ...`.
13. `CHANGES.md` has Sprint 29 entry.
14. `WORKER_GUIDE.md` says "32 passes".
15. `README.md` development history has Sprint 29 row.

---

## What Does NOT Change

- Risk score formula (`_compute_risk_scores`) unchanged — warnings are surfaced separately.
- `SEMANTIC_GUARD_SIGNALS`, `SEMANTIC_CRITICAL_SIGNALS`, all signal weights unchanged.
- All Sprint 28 `reachable_guards` behavior remains intact.
- No new signals, edge kinds, or CLI flags.
- Rules are intentionally strict on the "security" rules (critical) and looser on structural
  rules (medium) — some false positives on public APIs are expected and acceptable in v1.
