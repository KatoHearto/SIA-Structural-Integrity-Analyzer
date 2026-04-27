# Sprint 16 Briefing

Read `WORKER_GUIDE.md` first. Both tasks are pure refactoring — behavior must be identical after
the changes. Worker A decomposes `_build_analysis_result` (261 lines). Worker B decomposes
`_build_work_packet` (231 lines), then bumps the version and updates docs.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — Refactor `_build_analysis_result` into 2 helpers

**Where:** `_build_analysis_result` currently lives at lines 7148–7408 (261 lines).

Extract exactly two private helper methods. Insert them **directly before**
`_build_analysis_result` (i.e. before line 7148). The main method becomes an ~160-line
orchestrator that calls the two helpers in order.

---

#### Helper 1 — `_build_analysis_result_claim`

Extract lines 7280–7307 (the if/elif/else chain that builds the claim text) into:

```python
def _build_analysis_result_claim(
    self,
    outcome_mode: str,
    symbol_label: str,
    behavior_phrase: str,
    requested_phrase: str,
    context_phrase: str,
    decisive_signals: List[str],
    ambiguity_item: Dict[str, object],
) -> Tuple[str, str]:
```

This block produces `claim` and `claim_short` based on `outcome_mode`. Returns
`(claim, claim_short)`.

The four lines just before the block (lines 7275–7278) that compute `symbol_label`,
`behavior_phrase`, `requested_phrase`, and `context_phrase` stay **in the main method**
and are passed as arguments.

---

#### Helper 2 — `_build_analysis_result_metadata`

Extract lines 7308–7380 (missing_evidence list, decisive_outcome_rule assignment, minimal_basis
dict, evidence_refs list, result_reasoning_notes list) into:

```python
def _build_analysis_result_metadata(
    self,
    outcome_mode: str,
    missing_signals: List[str],
    primary_gap: Dict[str, object],
    ambiguity_item: Dict[str, object],
    flow_gap_refs: List[str],
    ambiguity_refs: List[str],
    primary_chain: Dict[str, object],
    primary_summary: Dict[str, object],
    decisive_signals: List[str],
    primary_target_id: str,
    supporting_slice_refs: List[str],
    supporting_flow_refs: List[str],
    supporting_path_refs: List[str],
    semantic_refs: List[Dict[str, object]],
) -> Tuple[List[Dict[str, object]], Dict[str, object], List[str], List[str]]:
```

Returns `(missing_evidence, minimal_basis, evidence_refs, result_reasoning_notes)`.

`decisive_outcome_rule` is an internal variable computed inside this helper and used only
within `minimal_basis` — it does **not** need to be in the return tuple.

---

#### Resulting `_build_analysis_result` skeleton

```python
def _build_analysis_result(self, query, analysis, ranked_targets, ...):
    outcome_mode = str(analysis_plan.get("recommended_outcome_mode", "unproven") or "unproven")
    # ... setup block (lines 7163–7278, unchanged) ...
    # primary_target_id, primary_chain, primary_path, primary_gap, primary_summary,
    # ambiguity_item, matched_signals, requested_signals, summary_signals, chain_signals,
    # primary_related_nodes, semantic_refs, decisive_signals, missing_signals,
    # minimal_open_sequence, supporting_slice_refs, supporting_flow_refs,
    # supporting_path_refs, flow_gap_refs, ambiguity_refs, forbidden_overreach,
    # next_best_request, symbol_label, behavior_phrase, requested_phrase, context_phrase
    # all stay exactly where they are now.

    claim, claim_short = self._build_analysis_result_claim(
        outcome_mode, symbol_label, behavior_phrase, requested_phrase, context_phrase,
        decisive_signals, ambiguity_item,
    )

    missing_evidence, minimal_basis, evidence_refs, result_reasoning_notes = (
        self._build_analysis_result_metadata(
            outcome_mode, missing_signals, primary_gap, ambiguity_item,
            flow_gap_refs, ambiguity_refs, primary_chain, primary_summary,
            decisive_signals, primary_target_id,
            supporting_slice_refs, supporting_flow_refs, supporting_path_refs, semantic_refs,
        )
    )

    return {
        "outcome_mode": outcome_mode,
        "claim": claim,
        "claim_short": claim_short,
        # ... rest of return dict (lines 7383–7408) unchanged ...
    }
```

The return dict at lines 7381–7408 stays exactly as it is — `claim`, `claim_short`,
`missing_evidence`, `minimal_basis`, `evidence_refs`, and `result_reasoning_notes` are
now local variables populated by the two helpers.

---

### Verification for Worker A

```bash
python -m py_compile god_mode_v3.py
rg -n "def _build_analysis_result_claim\|def _build_analysis_result_metadata" god_mode_v3.py
python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only
```

Expected: `parse_errors=0`, no crash, `nodes=74, edges=58`.

**Do not bump the version** — Worker B handles that.

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–end, plus docs. Note: `_build_work_packet` starts at
line 8442 (slightly before the usual boundary) — edit it as part of this task.

### Task B1 — Refactor `_build_work_packet` into 2 helpers

**Where:** `_build_work_packet` currently lives at lines 8442–8672 (231 lines).

Extract exactly two private helper methods. Insert them **directly before**
`_build_work_packet` (i.e. before line 8442). The main method becomes an ~70-line
orchestrator.

---

#### Helper 1 — `_build_work_packet_targets`

Extract lines 8470–8577 (all target-list construction: primary_targets, supporting_targets,
allowed_claims, disallowed_claims, answer_targets, patch_targets, refactor_targets) into:

```python
def _build_work_packet_targets(
    self,
    task_kind: str,
    worker_mode: str,
    analysis_result: Dict[str, object],
    primary_target_id: str,
    ambiguity_item: Dict[str, object],
    selected_slices: List[Dict[str, object]],
    read_order_refs: Set[str],
    supporting_symbols: List[str],
    analysis: Dict[str, object],
    primary_path: Dict[str, object],
    primary_chain: Dict[str, object],
) -> Tuple[
    List[Dict[str, object]],
    List[Dict[str, object]],
    List[Dict[str, object]],
    List[Dict[str, object]],
    List[Dict[str, object]],
    List[Dict[str, object]],
    List[Dict[str, object]],
]:
```

Returns `(primary_targets, supporting_targets, answer_targets, patch_targets, refactor_targets, allowed_claims, disallowed_claims)`.

`read_order_refs` is computed at line 8482 (`{str(item.get("slice_ref", "")) for item in read_order ...}`)
in the **original** method — keep that one line in the main method before the call to this helper and pass it as an argument.

---

#### Helper 2 — `_build_work_packet_completion`

Extract lines 8579–8628 (the completion_criteria dict, stop_conditions list, and
execution_notes list) into:

```python
def _build_work_packet_completion(
    self,
    outcome_mode: str,
    worker_mode: str,
    followup_ask: Dict[str, object],
    analysis: Dict[str, object],
    analysis_result: Dict[str, object],
    primary_path: Dict[str, object],
) -> Tuple[Dict[str, object], List[Dict[str, object]], List[str]]:
```

Returns `(completion_criteria, stop_conditions, execution_notes)`.

`followup_enabled = bool(followup_ask.get("enabled"))` at line 8599 moves **inside**
this helper (it is only used here).

---

#### Resulting `_build_work_packet` skeleton

```python
def _build_work_packet(self, query, analysis, analysis_plan, analysis_result,
                       selected_slices, selected_flow_chains, selected_paths,
                       flow_gaps, ambiguity_watchlist, escalation_controller, followup_ask):
    primary_target_id = str(analysis_result.get("minimal_basis", {}).get("primary_symbol", "") or "")
    primary_chain = self._select_primary_flow_chain(primary_target_id, selected_flow_chains)
    primary_path  = self._select_primary_evidence_path(primary_target_id, selected_paths)
    ambiguity_item = self._primary_ambiguity_item(primary_target_id, ambiguity_watchlist)
    task_kind    = self._infer_worker_task_kind(analysis, analysis_result)
    worker_mode  = self._choose_worker_mode(task_kind, analysis_result, ambiguity_watchlist, followup_ask)
    read_order   = self._build_work_packet_read_order(worker_mode, analysis_result, analysis_plan,
                                                      selected_slices, followup_ask)
    supporting_symbols = self._work_packet_supporting_symbols(primary_target_id, primary_chain, primary_path)
    read_order_refs = {str(item.get("slice_ref", "")) for item in read_order if str(item.get("slice_ref", ""))}

    (primary_targets, supporting_targets, answer_targets,
     patch_targets, refactor_targets,
     allowed_claims, disallowed_claims) = self._build_work_packet_targets(
        task_kind, worker_mode, analysis_result, primary_target_id,
        ambiguity_item, selected_slices, read_order_refs, supporting_symbols,
        analysis, primary_path, primary_chain,
    )

    outcome_mode = str(analysis_result.get("outcome_mode", "unproven") or "unproven")
    completion_criteria, stop_conditions, execution_notes = self._build_work_packet_completion(
        outcome_mode, worker_mode, followup_ask, analysis, analysis_result, primary_path,
    )

    # ... recommended_option_ref line (line 8628 in original) ...

    return {
        "task": query,
        # ... rest of return dict (lines 8630–8672, unchanged) ...
    }
```

**Important:** Line 8628 in the original (`recommended_option_ref = str(...)`) appears just after
the completion block — keep it in the main method between the `_build_work_packet_completion`
call and the return dict.

---

### Task B2 — Version bump and docs

**Version:** Bump `god_mode_v3.py` line 672 from `"3.45"` to `"3.46"`.

**CHANGES.md:** Append:

```markdown
## Sprint 16 — Refactoring: _build_analysis_result + _build_work_packet decomposition (v3.46)

### Change 1 — `_build_analysis_result` decomposed into 2 helpers
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | ~7148–7408 |
| **Category** | Refactoring |

Extracted `_build_analysis_result_claim` (outcome-specific claim text builder) and
`_build_analysis_result_metadata` (missing_evidence, minimal_basis, evidence_refs,
result_reasoning_notes) from the 261-line method.
Main method is now an ~160-line orchestrator. Behavior unchanged.

### Change 2 — `_build_work_packet` decomposed into 2 helpers
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | ~8442–8672 |
| **Category** | Refactoring |

Extracted `_build_work_packet_targets` (all target list construction: primary, supporting,
answer, patch, refactor, allowed_claims, disallowed_claims) and
`_build_work_packet_completion` (completion_criteria, stop_conditions, execution_notes)
from the 231-line method.
Main method is now an ~70-line orchestrator. Behavior unchanged.
```

**WORKER_GUIDE.md:** Update Current state:
- Version: `**3.46**`
- Sprint history: `18 passes (Runs 1–3 autonomous, Sprints 1–16)`

---

### Verification for Worker B

```bash
python -m py_compile god_mode_v3.py
```

```bash
python god_mode_v3.py .polyglot_graph_fixture --out test_s16.json --ask "Wo wird Auth durchgesetzt?" --bundle-dir test_s16_bundle
```

Must complete without error. Node/edge counts must be `nodes=74, edges=58`.

```bash
rg -n "def _build_work_packet_targets\|def _build_work_packet_completion" god_mode_v3.py
rg -n '"version"' god_mode_v3.py
```

---

## Handoff

- Worker A → `worker_output_a.md`
- Worker B → `worker_output_b.md`
