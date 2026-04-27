# CHANGES — Autonomous Bug-Fix Pass

**File audited:** `god_mode_v3.py` (14 150 lines, single source file)
  
**Audit scope:** Full file, every line read.

---

## Bugs Found and Fixed

### Bug 1 — `accepted_claims` includes disallowed claims
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | 11009 (original) |
| **Category** | Logic Error |
| **Severity** | Medium |

**Root cause.** `validate_worker_result_payload` computed `accepted_claims` with only
an `in allowed_claims` predicate. A claim that appeared in *both* `allowed_claims` and
`disallowed_claims` ended up in both `accepted_claims` and `rejected_claims`
simultaneously, contradicting the validation contract.

**Fix.** Added `and claim not in disallowed_claims` to the `accepted_claims` filter so
disallowed strings are always rejected even when they also appear in the allowed list.

---

### Bug 2 — `_tarjan_scc` can hit Python's recursion limit on large graphs
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | 3138–3179 (original) |
| **Category** | Runtime Error |
| **Severity** | Medium |

**Root cause.** Tarjan's algorithm was implemented as a straightforward recursive DFS
(`strongconnect` calls itself). Python's default recursion limit is 1 000. A codebase
with a linear dependency chain longer than ~990 nodes would raise `RecursionError`
and abort the entire analysis.

**Fix.** Added `import sys` to the module-level imports and wrapped the body of
`_tarjan_scc` in a `try/finally` block that temporarily raises `sys.setrecursionlimit`
to `max(old_limit, len(self.nodes) * 2 + 500)` before the DFS, then restores the
original limit unconditionally on exit — whether the DFS succeeded or raised.

---

### Bug 3 — `"version"` key mis-indented in `run()` meta dict
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | 661 (original) |
| **Category** | Code Quality |
| **Severity** | Low |

**Root cause.** The `"version": "3.29"` key inside the `"meta"` dictionary was indented
at 8 spaces while every other key in the same dict used 16 spaces. Python does not
error on inconsistent intra-dict indentation, but the visual mis-alignment was
misleading and broke automated style linting.

**Fix.** Re-indented `"version"` to 16 spaces to match its siblings.

---

### Bug 4 — Dead code in `_build_read_order_coverage`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | 10884–10885 (original) |
| **Category** | Code Quality |
| **Severity** | Low |

**Root cause.** After the main for-loop, the block
```python
if not missing_required_refs and len(matched) < len(required_refs):
    missing_required_refs = required_refs[len(matched):]
```
can never execute. The only early exit from the loop is `break` inside the
`if not found:` branch, which always sets `missing_required_refs` before breaking.
If the loop completes normally, every required ref was matched, so
`len(matched) == len(required_refs)` and the condition is False.

**Fix.** Removed the dead block.

---

### Bug 5 — Redundant identity list-comprehension in `_build_work_packet_allowed_claims`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | 8107 (original) |
| **Category** | Code Quality |
| **Severity** | Low |

**Root cause.** The return expression
```python
return [claim for claim in list(dict.fromkeys(item for item in claims if item))[:2]]
```
wraps an already-materialized `list` in an outer list-comprehension that copies it
element-by-element with no transformation — pure noise.

**Fix.** Simplified to:
```python
return list(dict.fromkeys(item for item in claims if item))[:2]
```

---

## Issues Intentionally Left Unchanged

| Location | Description | Reason |
|---|---|---|
| `_compute_betweenness` line 3285 | `if sigma[vertex] == 0: continue` — dead code (sigma is always >0 for any node pushed to the BFS stack) | Left as a harmless defensive guard; removing it offers no correctness benefit. |
| `_tarjan_scc` recursion algorithm | Converting to iterative Tarjan would be architecturally cleaner | The minimal `setrecursionlimit` fix is sufficient and less invasive. |

---

## Assumptions

- No other source files exist; `god_mode_v3.py` is the entire codebase.
- The project is a static analysis tool (SIA v3). Runtime correctness of the
  validator and the Tarjan SCC are the highest-priority concerns.
- `sys.setrecursionlimit` restore via `finally` is safe because `_tarjan_scc` is
  called synchronously from `run()` with no concurrent threads that could observe
  the temporary limit change in typical usage.

---

---

# CHANGES — Autonomous Bug-Fix Pass (Run 2)

**Date:** 2026-04-24  
**File audited:** `god_mode_v3.py` (14 150 lines, single source file)
  
**Audit scope:** Full file re-read (lines 1–11 537). All five Session 1 fixes confirmed present and correct. One new bug found and fixed.

**Fixture directories** (present in workspace but correctly excluded from analysis via `should_ignore_dir`):
- `.sia_fixture/` — Python fixture (base.py, service.py, util.py)
- `.multilang_fixture/` — multi-language fixture (Go, Rust, TypeScript, Java)
- `.polyglot_graph_fixture/` — polyglot fixture (Python, Go, Rust, TS, Java DI suite, AdminController)

The earlier assumption "No other source files exist" was incorrect with respect to fixture directories. These directories are intentionally ignored by `should_ignore_dir` because their names begin with `.`, so they have no effect on analysis correctness.

---

## Session 1 Fixes Re-verified

| Bug | Location | Status |
|---|---|---|
| Bug 1 — `accepted_claims` disallowed filter | line 11014 | ✓ Confirmed present |
| Bug 2 — Tarjan recursion limit guard | lines 3139–3187 | ✓ Confirmed present |
| Bug 3 — `"version"` key indentation | line 662 | ✓ Confirmed present |
| Bug 4 — Dead code in `_build_read_order_coverage` | removed | ✓ Confirmed removed |
| Bug 5 — Redundant identity list-comprehension | line 8115 | ✓ Confirmed present |

---

## Bug 6 — `first_divergence` incorrectly set for complete sequences
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | 10906 (in `_build_read_order_coverage` return dict) |
| **Category** | Data Correctness |
| **Severity** | Low |

**Root cause.** The inner while loop inside `_build_read_order_coverage` sets
`first_divergence` whenever an observed ref does not match the current required
ref during scanning. If the required ref is found later in the same scan pass,
`found` becomes `True` and the loop moves on — but `first_divergence` remains
set. When all required refs are eventually matched (`sequence_status =
"complete_in_order"`), the return dict still contained a non-None
`first_divergence` pointing to a spuriously flagged scan position. Any consumer
checking `if result["first_divergence"]:` as a proxy for "did the sequence
diverge" would receive the wrong answer.

**Fix.** Changed the return expression from
```python
"first_divergence": first_divergence,
```
to
```python
"first_divergence": first_divergence if sequence_status != "complete_in_order" else None,
```
so that `first_divergence` is always `None` when the sequence is complete,
matching its semantic contract.

---

## Issues Intentionally Left Unchanged (Run 2)

| Location | Description | Reason |
|---|---|---|
| `_build_read_order_coverage` else branch | `else: sequence_status = "partial_in_order"` — unreachable dead code. When `len(matched) != len(required_refs)`, the `if not found:` branch always sets `first_divergence` before breaking, so the final `elif first_divergence:` branch always catches partial sequences before the `else` can fire. | Harmless; removing the branch could surprise a future reader wondering about the missing case. Left in place as a dead-but-documenting fallback. |

---

## Assumptions (Run 2)

- All Session 1 fixes are verified correct and present.
- The `first_divergence` field is informational only and not used in any
  decision logic inside `validate_worker_result_payload` or
  `build_worker_result_report`; the fix therefore cannot regress existing
  validation behavior.
- Fixture directories (`.sia_fixture`, `.multilang_fixture`,
  `.polyglot_graph_fixture`) are correctly excluded by the existing
  `should_ignore_dir` predicate and are not part of the analyzed codebase.

---

# CHANGES — Autonomous Bug-Fix Pass (Run 3)

**Date:** 2026-04-24  
**File audited:** `god_mode_v3.py` (current on-disk `version = "3.29"` before this run)  
**Audit scope:** Delta audit against confirmed 3.29 state. Previously closed fixes rechecked only where needed for new findings.

---

## Previously Confirmed And Rechecked

- `version = "3.29"` present in `meta`
- `Run 2` already present in `CHANGES.md`
- Fixes 1–5 still present
- Bug 6 (`first_divergence` for complete sequences) still fixed
- Work-packet ambiguity targets, full required read sequence, and non-terminal report handling remained closed on re-read

---

## Bug 7 — `required_primary_symbols` was exported as mandatory but not enforced for terminal results
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Location** | `validate_worker_result_payload`, worker validation rule export, worker result prompt |
| **Category** | Contract / Validator Inconsistency |
| **Severity** | Medium |

**Repro.** Starting from the valid Auth worker result, removing
`result_slots.inspected_symbols` entirely still produced a valid, accepted
terminal result, even though `worker_result_template.required_primary_symbols`
explicitly exported `java.com.example.web:AdminController.audit` as required.

**Root cause.** The validator only checked missing primary symbols inside
```python
if required_primary_symbols and inspected_symbols:
```
which means an empty `inspected_symbols` list bypassed the check entirely. This
made `required_primary_symbols` behave like optional metadata even for terminal
results, contradicting the contract name and exported template.

**Fix.**
- Added a new exported rule:
  `must_cover_required_primary_symbols_for_terminal_result`
- Upgraded missing required primary symbols to a validator **violation** for
  terminal completion states
- Kept non-terminal states permissive
- Tightened `worker_result_prompt` so terminal results must record required
  primary symbols explicitly

---

## Verification (Run 3)

- `py_compile`: passed
- Polyglot fixture run: passed
- Workspace self-test: passed
- Ask runs rechecked: Auth, Disk, AppShell, Notify all passed
- Negative validator repro:
  - terminal Auth result with empty `inspected_symbols` is now rejected
- Positive validator repro:
  - valid Auth result with required primary symbol recorded remains accepted

---

# CHANGES — Coordinated Development Pass (Run 4)

**Date:** 2026-04-24
**File:** `god_mode_v3.py` — bumped `version = "3.30"` → `"3.31"`
**Team:** Brain (Claude Code, orchestrator) + Worker A (Codex, iterative Tarjan) + Worker B (Codex, code-quality)
**Scope:** Two parallel, non-overlapping changes integrated and verified.

---

## Change 1 — Iterative Tarjan SCC (Worker A)
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | 3147–3204 (post-edit) |
| **Category** | Architecture / Performance |
| **Severity** | Medium |

**Root cause.** The `_tarjan_scc` implementation was recursive. Bug 2 (Pass 1) patched this with `sys.setrecursionlimit`, which temporarily mutates global Python state and is fragile in multi-threaded scenarios.

**Fix.** Replaced the recursive `strongconnect` inner function and the `setrecursionlimit` try/finally block with a fully iterative implementation using an explicit `call_stack`. Each frame stores `(v, neighbors_iterator, child)`:
- `child is not None` triggers lowlink back-propagation from the completed child (mirrors the post-recursion `lowlink[v] = min(lowlink[v], lowlink[w])` step).
- `StopIteration` on the neighbor iterator triggers SCC-root check and Tarjan-stack emission.
- Back-edges (`w in on_stack`) update lowlink directly.

The `import sys` at module level is retained (used elsewhere). `sys.setrecursionlimit` calls are fully removed. Determinism is preserved: `sorted(self.nodes)` and `sorted(self.adj[v])` are unchanged.

---

## Change 2 — `"version"` key indentation re-fixed (Worker B)
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | 670 (post-edit) |
| **Category** | Code Quality |
| **Severity** | Low |

**Root cause.** The `"version"` key inside the `"meta"` dict was re-misindented (8 spaces instead of 16) when the version string was updated from `"3.29"` to `"3.30"` during Pass 3. Bug 3 (Pass 1) had originally fixed this, but the Pass 3 version-update accidentally re-introduced it.

**Fix.** Re-indented to 16 spaces to match all sibling keys in `"meta"`.

---

## Change 3 — `terminal_states` deduplicated into `WORKER_TERMINAL_STATES` constant (Worker B)
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | 193–199 (new constant), 11098, 11227 (references) |
| **Category** | Code Quality |
| **Severity** | Low |

**Root cause.** The identical set `{"completed_within_bounds", "stopped_on_guardrail", "stopped_on_ambiguity", "stopped_on_insufficient_evidence", "invalid_result"}` was defined inline in both `validate_worker_result_payload` and `build_worker_result_report`. Any future addition of a new terminal state required two synchronized edits.

**Fix.** Extracted as module-level constant `WORKER_TERMINAL_STATES: Set[str]` placed directly after `WORKER_COMPLETION_STATES`. Both functions now reference the constant.

---

## Verification (Run 4)

- `py_compile`: passed (both pre- and post-Tarjan-replacement)
- `rg` spot-checks: `setrecursionlimit` absent, `WORKER_TERMINAL_STATES` present at line 193, `"version": "3.31"` correctly indented at 16 spaces, both `terminal_states = WORKER_TERMINAL_STATES` references confirmed

---

## Process Note

Run 4 introduced a **3-LLM coordinated workflow**: Brain (Claude Code) maintained full architectural context, generated task briefings, and performed integration + verification. Two parallel Codex workers handled non-overlapping code regions with zero merge conflicts. Worker outputs were delivered inline for this sprint; a file-based handoff protocol (`worker_output_a.md` / `worker_output_b.md`) is adopted from Sprint 2 onward for direct file reads.

---

## Open Risks (Run 3)

- `required_primary_symbols` is now enforced for terminal results, but remains
  advisory for non-terminal states by design
- Claim acceptance is still string-contract based; that is intentional and
  unchanged in this run

---

# CHANGES — Coordinated Development Pass (Sprint 2 / Run 5)

**Date:** 2026-04-24
**File:** `god_mode_v3.py` — bumped `version = "3.31"` → `"3.32"`
**Team:** Brain (Claude Code, orchestrator) + Worker A (Codex) + Worker B (Codex)
**Scope:** Three low-severity code-quality fixes. Full file re-audit confirmed no remaining medium/high severity bugs.

---

## Change 1 — Redundant `SEMANTIC_EXTERNAL_IO_SIGNALS` union removed (Worker A)
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | 4018, 4050, 4059 |
| **Category** | Code Quality |
| **Severity** | Low |

**Root cause.** `SEMANTIC_EXTERNAL_IO_SIGNALS = {"network_io","database_io","filesystem_io","process_io"}` is a proper subset of `SEMANTIC_SIDE_EFFECT_SIGNALS = {"external_io","network_io","database_io","filesystem_io","process_io","state_mutation"}`. Three occurrences in `_build_behavioral_flow_steps` and `_behavioral_flow_summary_for_node` computed `SEMANTIC_SIDE_EFFECT_SIGNALS | SEMANTIC_EXTERNAL_IO_SIGNALS` or the equivalent `or step_kind in SEMANTIC_EXTERNAL_IO_SIGNALS` check, all of which evaluated identically to `SEMANTIC_SIDE_EFFECT_SIGNALS` alone.

**Fix.** Removed the redundant union/OR at all three sites, leaving only `SEMANTIC_SIDE_EFFECT_SIGNALS`.

---

## Change 2 — Dead branch in `_recommended_analysis_outcome_mode` removed (Worker A)
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | 6163–6164 (removed) |
| **Category** | Code Quality |
| **Severity** | Low |

**Root cause.** Inside `if matched_signals: if not covered_signals:`, the code read:
```python
if selected_paths or flow_gaps:
    return "unproven"
return "unproven"
```
Both branches returned `"unproven"`, so the conditional was dead.

**Fix.** Removed the dead `if` branch, leaving only `return "unproven"`.

---

## Change 3 — Redundant `{source, target}` literal removed (Worker B)
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | 10360 |
| **Category** | Code Quality |
| **Severity** | Low |

**Root cause.** In `_build_project_architecture_paths`, `hops` is always initialized as `[_path_hop_payload(source, target)]`, guaranteeing `source` and `target` appear in the hop source/target comprehensions. The explicit `{source, target}` literal in the union was therefore always redundant.

**Fix.** Removed `{source, target} |` from the set union expression.

---

## Change 4 — Version bump to 3.32 (Worker B)
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | 670 |
| **Category** | Housekeeping |

Bumped `"version": "3.31"` → `"3.32"` at 16-space indentation.

---

## Verification (Sprint 2)

- `py_compile`: passed (Worker A and Worker B independently)
- `rg` spot-checks: zero hits for all removed patterns; `"version": "3.32"` confirmed at 16-space indentation on line 670

---

## Process Note

Sprint 2 used the file-based handoff protocol introduced in Run 4: both Codex workers wrote results directly to `worker_output_a.md` and `worker_output_b.md`; Brain read these files directly without copy-paste.

---

## Open Issues After Sprint 2

- `if sigma[vertex] == 0: continue` at `_compute_betweenness` line 3310 — intentionally left as harmless defensive guard
- `else: sequence_status = "partial_in_order"` in `_build_read_order_coverage` — intentionally left as dead-but-documenting fallback
- Full-file audit found no remaining medium or high severity correctness bugs

---

## Sprint 3 — Usability Pass (v3.33)

### Change 1 — `should_ignore_dir` skips `ask_bundle` prefix
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | 470 |
| **Category** | Performance / Correctness |

`ask_bundle_*` output directories were not in the ignore list, causing SIA to walk into them
on every run against the project root. Extended `should_ignore_dir` to skip the `ask_bundle`
prefix, matching the existing `llm_bundle` prefix pattern.

### Change 2 — Async Python semantic signals
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | ~3748–3759 |
| **Category** | Feature |

Extended `_extract_python_semantic_spans` with three async-specific detection patterns:
- `aiohttp.ClientSession` → `network_io`
- `aiofiles.open` → `filesystem_io`
- `asyncio.create_subprocess_exec/shell` → `process_io`

These patterns were absent, causing async Python codebases to produce false-negative results
for the three affected signals.

### Change 3 — `requirements.txt` created
| | |
|---|---|
| **File** | `requirements.txt` (new) |
| **Category** | Documentation |

Added project root `requirements.txt` documenting the stdlib-only dependency model and optional
`tomli` / `git` CLI requirements.

---

## Sprint 4 — Analysis Quality Pass (v3.34)

### Change 1 — Extended Python `output_boundary` detection
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3778 |
| **Category** | Feature |

Extended `_extract_python_semantic_spans` `output_boundary` pattern from two names
(`jsonify`, `Response`) to twelve, covering FastAPI, Starlette, and Django response
constructors (`JSONResponse`, `HTMLResponse`, `StreamingResponse`, `FileResponse`,
`ORJSONResponse`, `RedirectResponse`, `PlainTextResponse`, `UJSONResponse`,
`HttpResponse`, `JsonResponse`, `HttpResponseRedirect`, `StreamingHttpResponse`).

### Change 2 — Added `abort(` and `redirect(` to guard action patterns
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~270 |
| **Category** | Feature |

Flask's `abort()` and Django/Flask's `redirect()` short-circuit the request path the
same way `raise` does. Added both to `SEMANTIC_GUARD_ACTION_PATTERNS` so guards using
these calls are correctly detected.

### Change 3 — Fixed `requirements.txt` (`gitpython` reference removed)
| | |
|---|---|
| **File** | `requirements.txt` |
| **Category** | Bug fix / Documentation |

The file incorrectly listed `gitpython` as an optional dependency. The git hotspot
feature (`_compute_git_hotspots`) uses `subprocess` to call the `git` CLI binary
directly — no Python package is needed. Replaced with a note about the `git` binary.

---

## Sprint 5 — Polyglot Signal Coverage (v3.35)

### Change 1 — Go extractor: `output_boundary`, `serialization`, `deserialization`, `state_mutation`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | ~3907–3926 |
| **Category** | Feature |

Extended `_extract_go_semantic_spans` with four previously absent signals:
`output_boundary` (w.Write, w.WriteHeader, json.NewEncoder(w).Encode, http.Error/Redirect),
`serialization` (json.Marshal/MarshalIndent), `deserialization` (json.Unmarshal/NewDecoder),
`state_mutation` (struct field assignment).

### Change 2 — Rust extractor: `error_handling`, `database_io`, `serialization`, `deserialization`, `state_mutation`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | ~3934–3956 |
| **Category** | Feature |

Extended `_extract_rust_semantic_spans` with five previously absent signals:
`error_handling` (.unwrap/.expect/? operator/Err), `database_io` (diesel/sqlx/tokio-postgres),
`serialization` (serde_json::to_string/to_vec/to_writer), `deserialization`
(`serde_json::from_str/from_reader/from_slice/from_value), `state_mutation` (self.field =).

### Change 3 — JS/TS extractor: `database_io`, `auth_guard`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | ~3879–3891 |
| **Category** | Feature |

Extended `_extract_js_like_semantic_spans` with two previously absent signals:
`database_io` (Prisma, Mongoose/Model, TypeORM helpers, Knex, pool/client/db.query),
`auth_guard` (jwt.verify/decode/sign, passport.authenticate, common auth helper names).

---

## Sprint 6 — Signal Depth Pass (v3.36)

### Change 1 — Python `input_boundary`: Django and FastAPI patterns
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3781 |
| **Category** | Feature |

Extended `_extract_python_semantic_spans` `input_boundary` detection to cover Django request
field access (`request.GET/POST/data/body/json/form/files/args`) and FastAPI dependency injection
parameter markers (`Body`, `Query`, `Path`, `Form`, `Header`, `Cookie`, `Depends`).

### Change 2 — Python `state_mutation`: collection mutations on `self`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3776 |
| **Category** | Feature |

Extended `state_mutation` to also detect subscript writes on self attributes
(`self.d[key] = ...`) and common mutating collection methods (`append`, `extend`,
`insert`, `update`, `setdefault`, `pop`, `remove`, `clear`, `add`, `discard`).

### Change 3 — Go extractor: `auth_guard` + guard-window enabled
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3913 |
| **Category** | Feature |

Switched `_extract_go_semantic_spans` loop to enumerated form, added `auth_guard`
detection (Authorization header access, jwt.Parse, middleware names), and wired in
`_guard_signal_for_window` — the only extractor that previously lacked it.

---

## Sprint 7 — Final Signal Coverage (v3.37)

### Change 1 — Python `database_io`: Django ORM and asyncpg
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3763 |
| **Category** | Feature |

Extended `_extract_python_semantic_spans` `database_io` pattern with Django ORM class-method
queries (`objects.filter/get/create/update/delete/all/exclude/annotate/aggregate/bulk_create`),
Django model instance `.save()` / `.delete()`, and asyncpg `conn.fetch/fetchrow/fetchval`.

### Change 2 — Python `auth_guard`: decorator patterns
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3797 |
| **Category** | Feature |

Added direct detection of Python auth/permission decorators (`@login_required`,
`@permission_required`, `@jwt_required`, `@token_required`, `@requires_auth`,
`@authenticated`, `@auth_required`, `@requires_permission`) as `auth_guard` signals.
Previously these were only caught probabilistically via the guard-window keyword search.

### Change 3 — Go `database_io`: GORM patterns
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3921 |
| **Category** | Feature |

Extended Go `database_io` to include GORM method chains:
`db.Where`, `db.Find`, `db.First`, `db.Last`, `db.Create`, `db.Save`, `db.Delete`,
`db.Update`, `db.Updates`, `db.Preload`, `db.Joins`.

### Change 4 — Rust: `input_boundary`, `output_boundary`, `auth_guard`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | ~3983–4000 |
| **Category** | Feature |

Added three previously absent signals to `_extract_rust_semantic_spans`:
`input_boundary` (Actix-web route macros `#[get/post/…]`, `web::Path/Json/Query/Form`,
`HttpRequest`), `output_boundary` (`HttpResponse::Ok/Created/…`, `web::Json(`,
`impl Responder`), `auth_guard` (bearer token, `jwt::decode`, Authorization header,
`Identity` API).

### Change 5 — JS/TS `output_boundary`: Express render/file/redirect
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3885 |
| **Category** | Feature |

Extended `_extract_js_like_semantic_spans` `output_boundary` pattern to also catch
`res.render(`, `res.sendFile(`, `res.download(`, and `res.redirect(`.

---

## Sprint 8 — Risk Reasoning + Rust Consistency (v3.38)

### Change 1 — Pipeline order: semantic signals before risk scores
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | 656–657 |
| **Category** | Bug fix |

`_compute_risk_scores()` was called before `_extract_semantic_signals()`, so `node.semantic_signals`
was always empty when `_reasons_for` ran. Swapped the order so semantic signals are available
during risk-reason generation.

### Change 2 — Semantic signal context in `_reasons_for`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3485 |
| **Category** | Feature |

Added a new reason: when a node carries critical semantic signals (`SEMANTIC_CRITICAL_SIGNALS`)
and is also under structural coupling pressure (instability ≥ 0.7, Ca ≥ 3, or Ce ≥ 3), the
risk reason now explicitly names the signals. This makes top-risk output actionable rather than
purely structural.

### Change 3 — Rust extractor: guard-window enabled
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3968 |
| **Category** | Feature |

Switched `_extract_rust_semantic_spans` loop to enumerated form and added
`_guard_signal_for_window` call. Rust is now consistent with all other four extractors.

---

## Sprint 9 — Bug Fixes: Encoding + Validation Guard (v3.39)

### Change 1 — `UnicodeDecodeError` crash in `_parse_file`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~842 |
| **Category** | Bug fix |

`_parse_file` only caught `SyntaxError` and `OSError`. A `.py` file with non-UTF-8
encoding (Latin-1, CP1252, etc.) raised `UnicodeDecodeError` which is a `ValueError`
subclass — not caught — and aborted the entire analysis run. Fixed by broadening the
`OSError` clause to `(OSError, UnicodeDecodeError)`.

### Change 2 — `UnicodeDecodeError` crash in `_read_project_text`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4874 |
| **Category** | Bug fix |

Same encoding issue in `_read_project_text`, which is called during bundle generation
and inventory building. Non-UTF-8 source files would abort bundle output. Fixed by
broadening the `except OSError` to `except (OSError, UnicodeDecodeError)`.

### Change 3 — `_looks_like_validation_guard` false positives reduced
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3593 |
| **Category** | Bug fix |

Bare `"==" in text` and `"!=" in text` triggers caused virtually any `if`-with-comparison
that had a nearby `return`/`raise` to be labeled `validation_guard`. Replaced with a
targeted regex that only matches comparisons against null/empty/boolean sentinels
(`None`, `null`, `undefined`, `""`, `''`, `0`, `False`, `True`). Also added
`" is not none"` as an explicit positive case.

---

## Sprint 10 — Direct Schema Validation + Axum Input Boundaries (v3.40)

### Change 1 — Direct `validation_guard` detection in Python extractor
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3808 |
| **Category** | Feature |

Pydantic (`model_validate`, `BaseModel`), marshmallow (`Schema.load`/`loads`/`validate`),
Django forms/DRF serializers (`form.is_valid`, `serializer.validate`), and WTForms
(`validate_on_submit`) were invisible to `validation_guard` because they don't use `if`-blocks.
Added direct pattern matching for all five library families.

### Change 2 — Direct `validation_guard` detection in JS/TS extractor
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3920 |
| **Category** | Feature |

Zod (`z.parse`, `z.safeParse`, chained `.parse`/`.safeParse`/`.parseAsync`), Joi
(`joi.*.validate`), and Yup (`yup.*.validate`) schema calls were not detected without
an `if`-block. Added direct regex patterns for all three libraries.

### Change 3 — Axum `input_boundary` patterns in Rust extractor
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4008 |
| **Category** | Feature |

The Rust `input_boundary` block only covered Actix-web patterns. Axum extractor syntax
(`axum::extract::`, `extract::Json/Path/Query/Form/State/TypedHeader`, `axum::routing::`)
is now fully covered alongside the existing Actix-web patterns.

---

## Sprint 11 — Go & Rust validation_guard + Framework input_boundary Coverage (v3.41)

### Change 1 — Direct `validation_guard` detection in Go extractor
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3972 |
| **Category** | Feature |

`go-playground/validator` (`validate.Struct`, `validate.Var`) and `ozzo-validation`
(`validation.Validate`, `validation.ValidateStruct`) call validation functions directly —
no `if`-block — so they were invisible to `_guard_signal_for_window`. Added direct detection
for both libraries.

### Change 2 — Go `input_boundary` expanded to Gin, Echo, Fiber, Chi
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3951 |
| **Category** | Feature |

The existing Go `input_boundary` check only covered `net/http` handler signatures. Gin
(`*gin.Context`), Echo (`echo.Context`), Fiber (`*fiber.Ctx`), common accessor methods
(`c.Param`, `c.Query`, `c.Bind`, `c.ShouldBind`), and Chi (`chi.URLParam`) are now detected.

### Change 3 — Direct `validation_guard` detection in Rust extractor
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4042 |
| **Category** | Feature |

The Rust `validator` crate (`Validate::validate`, `validate.Struct`) and `garde` crate
(`.validate(&())`) were not detected without an `if`-block. Added direct pattern matching
for both library styles.

### Change 4 — Rust `output_boundary` expanded to cover Axum responses
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4026 |
| **Category** | Feature |

The Rust `output_boundary` block only covered Actix-web patterns. Sprint 10 added Axum
`input_boundary`; this sprint completes Axum coverage with `impl IntoResponse`,
`axum::response::*`, and `StatusCode::*` response patterns.

---

## Sprint 12 — config_access + NestJS + Java database_io Improvements (v3.42)

### Change 1 — Go `config_access` expansion
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3960 |
| **Category** | Feature |

Viper (`viper.Get*`), godotenv (`godotenv.Load/Overload/Read`), envconfig
(`envconfig.Process`), and `os.LookupEnv` added alongside the existing `os.Getenv` pattern.
Viper is the dominant Go config library and was entirely undetected.

### Change 2 — Rust `config_access` expansion
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4020 |
| **Category** | Feature |

`dotenv::dotenv`, `envy::from_env/prefixed`, `config::Config`, `figment::Figment`, and
`std::env::var_os` added alongside the existing `std::env::var` pattern.

### Change 3 — NestJS `input_boundary` decorators in JS/TS extractor
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3910 |
| **Category** | Feature |

NestJS route decorators (`@Get`, `@Post`, `@Put`, `@Delete`, `@Patch`) and parameter
decorators (`@Body`, `@Param`, `@Query`, `@Headers`, `@Req`, `@Res`, `@UploadedFile`) are
now detected as `input_boundary` signals.

### Change 4 — Java `database_io` annotation-based detection
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3872 |
| **Category** | Feature |

`@Transactional`, `@Query`, `@Modifying`, `@NamedQuery`, and `@NativeQuery` annotations
now trigger `database_io` directly, independent of the `member_types` resolution path.

### Change 5 — Java `config_access` expansion
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3848 |
| **Category** | Feature |

`@ConfigurationProperties` and Spring `env.getProperty(...)` added alongside the existing
`System.getenv`, `System.getProperty`, and `@Value` patterns.

## Sprint 13 — network_io Depth + Go output_boundary Framework Coverage (v3.43)

### Change 1 — Go `output_boundary`: Gin / Echo / Fiber response helpers
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4008 |
| **Category** | Feature |

Gin (`c.JSON`, `c.String`, `c.HTML`, `c.Redirect`, `c.AbortWithStatusJSON`, `c.IndentedJSON`,
`c.PureJSON`, `c.JSONP`, etc.), Echo, and Fiber response helpers added alongside the existing
bare `net/http` patterns. Sprint 11 added these frameworks to `input_boundary` but left
`output_boundary` unmatched.

### Change 2 — Go `network_io`: `http.NewRequest`, resty, gRPC
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3958 |
| **Category** | Feature |

`http.NewRequest`, `client.Get/Post/Head`, `resty.*`, and `grpc.Dial/NewClient` added
alongside the previous `http.Get/Post` + `client.Do` patterns.

### Change 3 — Python `network_io`: boto3, botocore, gRPC, Google Cloud SDK
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3756 |
| **Category** | Feature |

`boto3.client/resource/Session`, `botocore.*`, `grpc.insecure_channel/secure_channel`,
and `google.cloud.*` added. The majority of Python cloud services use these clients and
were entirely undetected.

### Change 4 — Rust `network_io`: hyper, surf, ureq, tonic
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4028 |
| **Category** | Feature |

`hyper::`, `surf::`, `ureq::`, and `tonic::` added alongside the existing `reqwest::`
and `client.execute` patterns.

---

## Sprint 14 — Final Pattern Coverage Pass (v3.44)

### Change 1 — Java `input_boundary`: `@RequestBody` + `@PathVariable`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3840 |
| **Category** | Feature |

`@RequestBody` and `@PathVariable` added alongside existing Spring MVC annotations.
Both are ubiquitous in REST controllers but were previously undetected.

### Change 2 — Java `network_io`: Apache HttpClient
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3848 |
| **Category** | Feature |

`CloseableHttpClient`, `HttpGet`, `HttpPost`, `HttpPut`, `HttpDelete`, `HttpPatch` added
to the existing RestTemplate/WebClient/Feign pattern. Apache HttpClient is dominant in
enterprise Java codebases.

### Change 3 — Java `auth_guard`: SecurityContextHolder + programmatic checks
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3842 |
| **Category** | Feature |

`SecurityContextHolder.getContext()`, `authenticationManager.authenticate()`, and
`jwtService.validate/verify/parseToken/extractUsername()` added alongside annotation
guards. Spring Security code-level patterns were entirely undetected.

### Change 4 — Go `database_io`: pgx / pgxpool
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3965 |
| **Category** | Feature |

`pgxpool.New`, `pgxpool.Connect`, `pgx.Connect`, and `pool/conn.QueryRow/Query/Exec/Begin/SendBatch`
added. pgx is the most-used PostgreSQL driver in Go and was entirely undetected.

### Change 5 — Go `filesystem_io`: `os.ReadFile` + bufio
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3967 |
| **Category** | Feature |

`os.ReadFile` (stdlib since Go 1.16) and `bufio.NewReader/NewWriter/NewScanner` added
to the existing os.Open/Create/WriteFile pattern.

### Change 6 — JS/TS `database_io`: Drizzle ORM
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3923 |
| **Category** | Feature |

`drizzle()` constructor and `db.select()/insert()/update()/delete()` builder calls added
alongside Prisma/Mongoose/TypeORM/Knex. Drizzle is one of the fastest-growing TypeScript
ORMs and was completely invisible.

### Change 7 — JS/TS `auth_guard`: bcrypt + argon2
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3931 |
| **Category** | Feature |

`bcrypt.hash/compare/hashSync/compareSync` and `argon2.hash/verify` added to the
existing jwt/passport/verifyToken patterns. Password hashing/verification calls are
a core auth signal.

### Change 8 — Rust `filesystem_io`: `tokio::fs` + `async_std::fs`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4037 |
| **Category** | Feature |

`tokio::fs::` and `async_std::fs::` added alongside `std::fs::`. Async Rust filesystem
operations were entirely undetected.

### Change 9 — Rust `database_io`: sea_orm + rusqlite
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4053 |
| **Category** | Feature |

`sea_orm::`, `rusqlite::`, and `EntityTrait::*()` added to the existing
diesel/sqlx/tokio_postgres pattern. sea_orm is the dominant async Rust ORM.

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

## Sprint 17 — Refactoring: _build_llm_context_pack + JS/TS + Go pattern additions (v3.47)

### Change 1 — `_build_llm_context_pack` decomposed
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | ~5025–5168 |
| **Category** | Refactoring |

Extracted `_build_llm_context_slices` (candidate processing: primary slice budget loop,
focus_symbols, support_pool building and filling) from the 144-line method.
Main method is now an ~70-line orchestrator. Behavior unchanged.

### Change 2 — JS/TS semantic signal additions
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Method** | `_extract_js_like_semantic_spans` |
| **Category** | Pattern coverage |

- `auth_guard`: added `@UseGuards(` (NestJS guard decorator) and `supabase.auth.*` calls
- `database_io`: added `new Redis(` / `new IORedis(` instantiation (ioredis)
- `validation_guard`: added class-validator decorators (`@IsEmail`, `@IsString`, etc.)

### Change 3 — Go semantic signal additions
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Method** | `_extract_go_semantic_spans` |
| **Category** | Pattern coverage |

- `database_io`: added `redis.NewClient(` (go-redis) and `mongo.Connect/NewClient(` (MongoDB Go driver)

## Sprint 18 — Pattern coverage: Java Spring + Python Celery + Rust gaps (v3.48)

### Change 1 — Java Spring annotation patterns
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Method** | `_extract_java_semantic_spans` |
| **Category** | Pattern coverage |

- `input_boundary`: `@KafkaListener`, `@RabbitListener`, `@SqsListener`, `@EventListener`, `@JmsListener`
- `process_io`: `@Async`
- `state_mutation`: `@Cacheable`, `@CacheEvict`, `@CachePut`, `@Caching`
- `time_or_randomness`: `@Scheduled`

### Change 2 — Python Celery task patterns
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Method** | `_extract_python_semantic_spans` |
| **Category** | Pattern coverage |

- `process_io`: `@app.task`, `@celery.task`, `@shared_task` decorators

### Change 3 — Rust missing patterns
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Method** | `_extract_rust_semantic_spans` |
| **Category** | Pattern coverage |

- `time_or_randomness`: `uuid::Uuid::new_v4/new_v7`
- `database_io`: `redis::Client/Connection/Commands/AsyncCommands`
- `input_boundary`: `lapin::` (AMQP/RabbitMQ), `rdkafka::consumer::` (Kafka)

## Sprint 19 — New language: C# + --diff CLI mode (v3.49)

### Change 1 — C# language support
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Category** | New language |

Added C# as the sixth supported language. Supports `.cs` files with namespace and
`using` directive parsing, multi-class/method symbol extraction (reuses Java brace-matching
helpers), and full semantic signal coverage: `input_boundary` (ASP.NET Core route attributes),
`auth_guard` ([Authorize], JWT validation), `validation_guard` ([Required] etc., ModelState),
`database_io` (Entity Framework, ADO.NET), `network_io` (HttpClient), `filesystem_io`
(File, Directory, Stream), `process_io` (Process.Start), `config_access` (IConfiguration,
Environment), `serialization/deserialization` (JsonSerializer, Newtonsoft), `time_or_randomness`
(DateTime.Now, Guid.NewGuid), `state_mutation` (this.field =), `error_handling` (try/catch/throw),
`output_boundary` (IActionResult return values).

### Change 2 — `--diff` CLI mode
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Category** | New feature |

`python god_mode_v3.py --diff old.json new.json` compares two SIA report JSON files and
prints a structured diff: new risks (appeared), resolved risks (disappeared), improved
(score dropped >=1.0), degraded (score rose >=1.0), unchanged count. No analysis is run.
Useful for validating sprint results and tracking risk evolution over time.

## Sprint 20 — New language: Kotlin + --exclude glob patterns (v3.50)

Worker A: Kotlin added as seventh language. `.kt` and `.kts` files are fully parsed:
`_parse_kotlin_file`, `_parse_kotlin_module`, `_extract_kotlin_symbol_payloads`,
`_extract_kotlin_semantic_spans`. Semantic signals cover coroutines (process_io), Ktor/
OkHttp/Retrofit (network_io), Room/JPA/Exposed (database_io), Spring Security (auth_guard),
Bean Validation (validation_guard), kotlinx.serialization/Gson/Jackson
(serialization/deserialization), clocks + UUID (time_or_randomness), @Cacheable
(state_mutation), Spring @Value/@ConfigurationProperties (config_access),
println/logger (output_boundary), try/runCatching (error_handling). Import resolution
matches Kotlin packages exactly.

Worker B: `--exclude PATTERN` CLI flag (repeatable, action=append) lets callers skip
directories or files by glob. Matched against directory names (pruning os.walk) and
relative file paths (fnmatch). `StructuralIntegrityAnalyzerV3.__init__` gains an
`exclude_globs` parameter forwarded from `main()`. Version 3.50, 22 passes.

## Sprint 21 — New language: PHP + Markdown report + --why explainer (v3.51)

Worker A: PHP added as eighth language. `.php` files fully parsed: `_parse_php_file`,
`_parse_php_module`, `_extract_php_symbol_payloads`, `_extract_php_semantic_spans`.
Signals: PDO/MySQLi/Eloquent (database_io); cURL/Guzzle/Http facade (network_io); file_*
/Storage (filesystem_io); exec/shell_exec (process_io); getenv/$_ENV/config() (config_access);
Auth::check/@Authorize (auth_guard); $request->validate() (validation_guard); Route::/
#[Route] (input_boundary); echo/response() (output_boundary); json_encode (serialization);
json_decode (deserialization); try/catch (error_handling); $_SESSION/Cache::put
(state_mutation); time()/rand()/Carbon::now() (time_or_randomness). Import resolution
matches PHP use directives after converting backslash namespace separators to dots.

Worker B: `--markdown PATH` writes a human-readable GitHub Markdown report (top risks table,
cycles, language distribution, module coupling) alongside the JSON output.
`--why SYMBOL REPORT` is a new standalone mode that loads an existing JSON report and prints
a structured explanation of a symbol's risk score: coupling metrics, semantic signals, callers,
callees, and any dependency cycles containing the symbol. Version 3.51, 23 passes.

## Sprint 22 — New language: Ruby + .siaignore + --filter-language (v3.52)

Worker A: Ruby added as ninth language. `.rb` files fully parsed: `_parse_ruby_file`,
`_parse_ruby_module`, `_ruby_find_end` (approximate end-keyword depth tracker for
`end`-delimited blocks), `_extract_ruby_symbol_payloads`. Top-level and class-member
`def` declarations extracted; class/module hierarchy captured. `_extract_ruby_semantic_spans`
covers Rails/Sinatra routing (input_boundary); Devise/CanCanCan auth (auth_guard);
ActiveRecord validations (validation_guard); ActiveRecord/Sequel queries (database_io);
Net::HTTP/Faraday/HTTParty (network_io); File/Dir/IO helpers (filesystem_io); backtick/
system/Open3 (process_io); ENV/$RAILS_ENV (config_access); to_json/JSON.parse
(serialization/deserialization); Time.now/SecureRandom (time_or_randomness); Rails.cache/
session (state_mutation); rescue/raise (error_handling); render/redirect_to/puts
(output_boundary).

Worker B: `.siaignore` file - if present in the project root, patterns (one per line, #
comments ignored) are merged with `--exclude` patterns before scanning. `--filter-language
LANGS` (comma-separated) restricts analysis to named languages only; wires into
wires into `StructuralIntegrityAnalyzerV3.__init__` via new `filter_languages` parameter. Version 3.52,
24 passes.

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

## Sprint 25 — Frappe Plugin: ORM Resolution + Semantic Enrichment (v3.55)

- New semantic signal `orm_dynamic_load` (weight 2.5) — fires on Python symbols using
  Frappe ORM calls (`frappe.get_doc`, `frappe.get_all`, `frappe.db.*`)
- `_resolve_frappe_orm_calls()`: adds `orm_load` edges from Python callers to DocType nodes
  (only when `--plugin frappe` active)
- `_extract_python_semantic_spans`: Frappe ORM patterns emit `orm_dynamic_load`
  unconditionally; `doc_events` → `input_boundary`, `scheduler_events` →
  `time_or_randomness`, `override_whitelisted_methods` → `auth_guard` when plugin active
- `"orm_load": (0.85, "high")` added to `RESOLUTION_CONFIDENCE`

## Sprint 26 — Frappe Plugin: Polish + JS Cross-Language + Documentation (v3.56)

- Fixture `sales_order.py`: added `frappe.get_all("Sales Order Item", ...)` → `orm_load`
  edge to `sales_order_item` DocType
- New JS fixture `sales_order_form.js`: `frappe.call({method: "..."})` strings resolve to
  Python methods via Sprint 23 `string_ref` mechanism (cross-language edges, no Frappe-
  specific JS code needed)
- Documentation: `CHANGES.md`, `WORKER_GUIDE.md`, `README.md` updated through Sprint 26

## Sprint 27 — New Semantic Signals: `concurrency` + `caching` (v3.57)

- New signal `concurrency` (weight 2.6) — fires on thread/goroutine/coroutine spawning,
  locks, channels, atomic ops, and executor submission across all 9 languages
- New signal `caching` (weight 1.8) — fires on Redis/Memcached clients, LRU caches,
  framework annotations (`@Cacheable`, `Rails.cache`, Laravel `Cache::`) across all 9 languages
- Both signals added to `SEMANTIC_CRITICAL_SIGNALS`; `concurrency` to
  `SEMANTIC_SIDE_EFFECT_SIGNALS`, `caching` to `SEMANTIC_EXTERNAL_IO_SIGNALS`
- Reclassifications: Java/Kotlin `@Cacheable` `state_mutation` → `caching`; Kotlin
  coroutine builders `process_io` → `concurrency`; PHP `Cache::` / Ruby `Rails.cache.`
  `state_mutation` → `caching`


