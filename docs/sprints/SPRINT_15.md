# Sprint 15 Briefing

Read `WORKER_GUIDE.md` first. This sprint is driven by SIA's self-analysis: when run against
its own codebase, `_build_ask_context_pack` scored highest (49.0) due to high instability and
408 lines in a single method. Worker B refactors it into focused helpers. Worker A adds a
recursion-depth guard to the confirmed mutual-recursion cycle found in the JS/TS barrel resolver.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — Add recursion depth guard to barrel resolver cycle

**Background:** SIA's self-analysis found a confirmed cycle:
`_resolve_js_like_binding_reference_with_barrel` ↔ `_resolve_js_like_binding_target_with_barrel`
The mutual recursion is intentional (barrel file resolution requires it), but there is no depth
limit. A pathological JS/TS project with deeply nested barrel re-exports could cause unbounded
recursion or Python's recursion limit.

**Where:** Find both methods — search for `def _resolve_js_like_binding_reference_with_barrel`
and `def _resolve_js_like_binding_target_with_barrel`.

**Change:** Add a `_depth` parameter (default `0`) to both methods. At the top of each method,
add a guard:

```python
if _depth > 8:
    return None
```

Update all internal recursive call sites to pass `_depth + 1`. Do NOT change external call
sites that call these methods without `_depth` — the default value handles those.

**Verification:**
```bash
python -m py_compile god_mode_v3.py
rg -n "_depth" god_mode_v3.py
python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only
```
Expected: `parse_errors=0`, no crash.

**Do not bump the version** — Worker B handles that.

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–end, plus docs

### Task B1 — Refactor `_build_ask_context_pack` into 3 helpers

**Where:** `_build_ask_context_pack` currently lives at lines 8974–9381 (408 lines).

Extract exactly three private helper methods. Insert them **directly before**
`_build_ask_context_pack` (i.e. before line 8974). The main method becomes an ~100-line
orchestrator that calls the three helpers in order.

---

#### Helper 1 — `_rank_ask_candidates`

Extract lines 8979–9044 (the candidate-ranking block) into:

```python
def _rank_ask_candidates(
    self,
    analysis: Dict[str, object],
    inbound: Dict[str, List],
) -> Tuple[List[Dict[str, object]], Dict[str, float], Dict[str, Dict[str, object]], List[Dict[str, object]]]:
```

This block builds `base_candidates`, filters and sorts them, calls
`_build_query_evidence_paths`, computes `path_bonus_by_node` and `best_path_by_node`,
assembles and sorts `ranked_targets`, adds `rank` numbers, and returns:
`(ranked_targets, path_bonus_by_node, best_path_by_node, query_paths)`

The two inner `def` closures (`matches_query_focus_node`, `matches_query_focus_path`) move
into this helper as well since they are only used here.

---

#### Helper 2 — `_select_ask_slices`

Extract lines 9046–9188 (the slice-selection block) into:

```python
def _select_ask_slices(
    self,
    analysis: Dict[str, object],
    ranked_targets: List[Dict[str, object]],
    query_paths: List[Dict[str, object]],
    best_path_by_node: Dict[str, Dict[str, object]],
    query_ambiguity_watchlist: List[Dict[str, object]],
    inbound: Dict[str, List],
    line_budget: int,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], Dict[str, List], List[Dict[str, object]]]:
```

This block selects `selected_paths`, builds `selected_semantic_refs`, builds `slice_specs`
for primary targets, path-support slices, and ambiguity slices, and returns:
`(slice_specs, selected_paths, path_refs_by_anchor, selected_semantic_refs)`

`path_refs_by_anchor` is computed via `self._path_refs_by_anchor(selected_paths)` at the
start of this block (line 9061) — keep it inside this helper.

---

#### Helper 3 — `_build_ask_flow_data`

Extract lines 9190–9214 (the flow-construction block) into:

```python
def _build_ask_flow_data(
    self,
    analysis: Dict[str, object],
    ranked_targets: List[Dict[str, object]],
    merged_slices: List[Dict[str, object]],
    selected_paths: List[Dict[str, object]],
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
```

This block calls `_build_selected_flow_summaries`, `_build_selected_flow_chains`,
`_build_flow_gaps`, and returns:
`(selected_flow_summaries, selected_flow_chains, flow_gaps)`

Note: `merged_slices` is computed at line 9190–9191 (merge + annotate step) — keep those
two lines **inside `_build_ask_context_pack`** before the call to this helper, since
`merged_slices` is also needed for the downstream objects block.

---

#### Resulting `_build_ask_context_pack` skeleton

After extraction the main method should look like this:

```python
def _build_ask_context_pack(self, query: str, line_budget: int = 110) -> Dict[str, object]:
    inbound = self._inbound_adj()
    analysis = self._build_query_analysis(query)
    query_ambiguity_watchlist = self._build_query_ambiguity_watchlist(analysis, [], limit=4)

    ranked_targets, path_bonus_by_node, best_path_by_node, query_paths = (
        self._rank_ask_candidates(analysis, inbound)
    )
    # re-build ambiguity watchlist now that ranked_targets is known
    query_ambiguity_watchlist = self._build_query_ambiguity_watchlist(
        analysis, ranked_targets, limit=4
    )

    slice_specs, selected_paths, path_refs_by_anchor, selected_semantic_refs = (
        self._select_ask_slices(
            analysis, ranked_targets, query_paths, best_path_by_node,
            query_ambiguity_watchlist, inbound, line_budget,
        )
    )

    merged_slices = self._merge_slice_specs(slice_specs)
    merged_slices = [self._annotate_slice_path_refs(spec, path_refs_by_anchor) for spec in merged_slices]
    selected_symbols = {symbol for spec in merged_slices for symbol in spec.get("symbols", [])}

    selected_flow_summaries, selected_flow_chains, flow_gaps = self._build_ask_flow_data(
        analysis, ranked_targets, merged_slices, selected_paths,
    )

    # ... deferred + downstream objects + pack assembly (lines 9216–9381, unchanged)
```

**Important:** `query_ambiguity_watchlist` is called twice in the original — once at line 9046
with an empty list (before ranked_targets exists) and again would need ranked_targets. Check
the original carefully: line 9046 calls it with `ranked_targets` already built. Move the
single call inside `_rank_ask_candidates` is NOT correct — it belongs in the main method
after `_rank_ask_candidates` returns. Keep the single call at line 9046 position in the
orchestrator, passing the now-available `ranked_targets`.

---

### Task B2 — Version bump and docs

**Version:** Bump `god_mode_v3.py` line 672 from `"3.44"` to `"3.45"`.

**CHANGES.md:** Append:

```markdown
## Sprint 15 — Refactoring: _build_ask_context_pack decomposition + barrel resolver depth guard (v3.45)

### Change 1 — Barrel resolver recursion depth guard
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | `_resolve_js_like_binding_reference_with_barrel`, `_resolve_js_like_binding_target_with_barrel` |
| **Category** | Defensive fix |

Added `_depth` parameter (max 8) to both mutually-recursive barrel resolver methods.
Prevents unbounded recursion on pathological JS/TS projects with deeply nested star re-exports.

### Change 2 — `_build_ask_context_pack` decomposed into 3 helpers
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | ~8974–9381 |
| **Category** | Refactoring |

Extracted `_rank_ask_candidates` (candidate ranking + path bonuses),
`_select_ask_slices` (slice selection for primary targets, path support, ambiguity),
and `_build_ask_flow_data` (flow summaries, chains, gaps) from the 408-line monolith.
Main method is now an ~100-line orchestrator. Behavior unchanged.
```

**WORKER_GUIDE.md:** Update Current state:
- Version: `**3.45**`
- Sprint history: `17 passes (Runs 1–3 autonomous, Sprints 1–15)`

---

### Verification for Worker B

```bash
python -m py_compile god_mode_v3.py
```

```bash
python god_mode_v3.py .polyglot_graph_fixture --out test_refactor.json --ask "Wo wird Auth durchgesetzt?" --bundle-dir test_refactor_bundle
```
Must complete without error. Compare node/edge counts with previous runs: nodes=74, edges=58.

```bash
rg -n "def _rank_ask_candidates\|def _select_ask_slices\|def _build_ask_flow_data" god_mode_v3.py
rg -n '"version"' god_mode_v3.py
```

---

## Handoff

- Worker A → `worker_output_a.md`
- Worker B → `worker_output_b.md`
