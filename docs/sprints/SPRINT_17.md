# Sprint 17 Briefing

Read `WORKER_GUIDE.md` first. Worker A refactors `_build_llm_context_pack` (144 lines) by
extracting the candidate-processing loop. Worker B adds missing semantic signal patterns for
JS/TS and Go, then bumps the version and updates docs.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — Refactor `_build_llm_context_pack` into 1 helper

**Where:** `_build_llm_context_pack` lives at lines 5025–5168 (144 lines).

Extract exactly one private helper method. Insert it **directly before**
`_build_llm_context_pack` (i.e. before line 5025). The main method becomes an ~70-line
orchestrator.

---

#### Helper — `_build_llm_context_slices`

Extract lines 5041–5120 (the candidate processing + support-pool block) into:

```python
def _build_llm_context_slices(
    self,
    evidence_candidates: List[Dict[str, object]],
    inbound: Dict[str, List],
    path_refs_by_anchor: Dict[str, List],
    path_bonus_by_anchor: Dict[str, float],
    ambiguity_watchlist: List[Dict[str, object]],
    line_budget: int,
    primary_budget: int,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]], Set[str]]:
```

This block:
- Iterates over `evidence_candidates`, builds `slice_specs`, `deferred`, `focus_symbols`,
  `selected_nodes` (the primary loop, lines 5041–5091)
- Builds and sorts `support_pool` from the selected candidates (lines 5093–5112)
- Fills remaining budget from `support_pool` (lines 5114–5120)

Returns `(slice_specs, deferred, focus_symbols, selected_nodes)`.

`primary_budget` is computed at line 5045 (`max(1, int(line_budget * 0.72))`) in the
**original** method — keep that one line in the main method before the call and pass it
as an argument.

---

#### Resulting `_build_llm_context_pack` skeleton

```python
def _build_llm_context_pack(self, top_risks, line_budget):
    inbound = self._inbound_adj()
    confidence_summary = self._build_confidence_summary()
    ambiguity_watchlist = self._build_ambiguity_watchlist()
    evidence_candidates = self._build_evidence_candidates(top_risks, inbound)
    semantic_candidates = self._build_semantic_candidates(limit=10)
    semantic_watchlist = self._build_semantic_watchlist(limit=6)
    evidence_paths = self._build_evidence_paths(evidence_candidates, inbound)[:12]
    path_refs_by_anchor = self._path_refs_by_anchor(evidence_paths)
    path_bonus_by_anchor: Dict[str, float] = defaultdict(float)
    for path in evidence_paths:
        bonus = ...
        for item in path.get("recommended_slices", [])[1:]:
            ...
    primary_budget = max(1, int(line_budget * 0.72))

    slice_specs, deferred, focus_symbols, selected_nodes = self._build_llm_context_slices(
        evidence_candidates, inbound, path_refs_by_anchor, path_bonus_by_anchor,
        ambiguity_watchlist, line_budget, primary_budget,
    )

    merged_slices = self._merge_slice_specs(slice_specs)
    merged_slices = [self._annotate_slice_path_refs(spec, path_refs_by_anchor) for spec in merged_slices]
    selected_symbols = {symbol for spec in merged_slices for symbol in spec["symbols"]}
    # ... deferred finalization + support_chains + return (lines 5127–5168, unchanged) ...
```

**Important:** `selected_nodes` (returned by the helper) is used in lines 5127–5143 of the
original to filter `support_chains` and build path-deferred requests. Check carefully:
lines 5127–5143 use `selected_symbols` (computed from `merged_slices`), not `selected_nodes`.
`selected_nodes` is only needed inside the helper to build `support_pool`. Do **not** include
it in the return tuple if it isn't used after the helper call — verify before deciding.

---

### Verification for Worker A

```bash
python -m py_compile god_mode_v3.py
rg -n "def _build_llm_context_slices" god_mode_v3.py
python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only
```

Expected: `parse_errors=0`, `nodes=74, edges=58`.

**Do not bump the version** — Worker B handles that.

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–end, plus extractors and docs.
Note: the extractors live at lines ~3747–4120 (Worker A territory by line number, but these
pattern additions are small and isolated — edit them as part of this task).

### Task B1 — Add JS/TS semantic signal patterns

**Where:** `_extract_js_like_semantic_spans` — the `auth_guard` block and `database_io` block
and `validation_guard` block.

#### 1a. auth_guard — add `@UseGuards` and Supabase auth

Find the existing `auth_guard` block in `_extract_js_like_semantic_spans` (currently
detects `jwt.verify`, `passport.authenticate`, `bcrypt`, `argon2`).
Add two conditions **inside the same `if` block** (as additional `or` clauses):

```python
or re.search(r"@UseGuards\s*\(", text)
or re.search(r"\bsupabase\.auth\.[A-Za-z_]\w*\s*\(", text)
```

These cover NestJS's `@UseGuards(AuthGuard('jwt'))` and Supabase auth calls
(`supabase.auth.signIn`, `supabase.auth.getUser`, etc.).

#### 1b. database_io — add `ioredis` / `node-redis` instantiation

Find the existing `database_io` block in `_extract_js_like_semantic_spans`.
Add one condition as an additional `or` clause:

```python
or re.search(r"\bnew (?:Redis|IORedis)\s*\(", text)
```

This detects `new Redis({...})` (ioredis) and `new IORedis({...})` (ioredis v4 alias).

#### 1c. validation_guard — add `class-validator` decorators

Find the existing `validation_guard` block in `_extract_js_like_semantic_spans`
(currently detects Zod, Joi, Yup). Add one condition as an additional `or` clause:

```python
or re.search(
    r"@(?:IsEmail|IsString|IsNumber|IsInt|IsBoolean|IsDate|IsOptional|IsNotEmpty|"
    r"IsArray|IsUUID|Length|MinLength|MaxLength|IsEnum|Matches|IsNotEmptyObject)\s*\(",
    text,
)
```

This detects `class-validator` decorator usage, which is ubiquitous in NestJS DTOs.

---

### Task B2 — Add Go semantic signal patterns

**Where:** `_extract_go_semantic_spans` — the `database_io` block.

Find the existing `database_io` block in `_extract_go_semantic_spans` (currently detects
`db.Query/Exec`, `sql.Open`, GORM, pgx/pgxpool, pool.QueryRow).
Add two conditions as additional `or` clauses:

```python
or re.search(r"\bredis\.NewClient\s*\(", text)
or re.search(r"\bmongo\.(?:Connect|NewClient)\s*\(", text)
```

These cover the official Go Redis client (`go-redis/redis` → `redis.NewClient(...)`) and
the official MongoDB Go driver (`mongo.Connect(...)`, `mongo.NewClient(...)`).

---

### Task B3 — Version bump and docs

**Version:** Bump `god_mode_v3.py` line 672 from `"3.46"` to `"3.47"`.

**CHANGES.md:** Append:

```markdown
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
```

**WORKER_GUIDE.md:** Update Current state:
- Version: `**3.47**`
- Sprint history: `19 passes (Runs 1–3 autonomous, Sprints 1–17)`

---

### Verification for Worker B

```bash
python -m py_compile god_mode_v3.py
python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only
rg -n '"version"' god_mode_v3.py
rg -n "UseGuards\|supabase\.auth\|new.*Redis\|IORedis\|IsEmail\|redis\.NewClient\|mongo\.Connect" god_mode_v3.py
```

Expected: `parse_errors=0`, `nodes=74, edges=58`. The `rg` output must show all new patterns
inside the extractor methods.

---

## Handoff

- Worker A → `worker_output_a.md`
- Worker B → `worker_output_b.md`
