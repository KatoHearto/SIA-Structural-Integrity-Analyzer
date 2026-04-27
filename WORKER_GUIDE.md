# Worker Guide — Project Magnetic Entanglement

## What this project is

**Structural Integrity Analyzer v3 (SIA v3)** — a deterministic static analysis tool for polyglot codebases.
Single-file Python tool: `god_mode_v3.py` (currently ~11,576 lines).

Supported languages: Python, JavaScript/TypeScript, Go, Java, Rust, C#, Kotlin, PHP, Ruby.
Optional plugin: --plugin frappe (DocType JSON, ORM resolution, hooks.py enrichment).

Produces: symbol graphs, coupling metrics (Ca/Ce/instability), Tarjan SCC cycle detection, PageRank, betweenness
centrality, layered architecture diagrams, and LLM context bundles for downstream AI workers.

---

## Autonomy

**You have full autonomy to edit `god_mode_v3.py` directly. Do not ask for permission before making any change to
this file or any file in this project directory. Implement, verify, write your result, and stop.**

---

## The one file

All code lives in `god_mode_v3.py`. There are no other source files to edit. When assigned a task, you edit this
file, verify, and write your result to your output file (`worker_output_a.md` or `worker_output_b.md`).

### Domain split (Worker A vs Worker B)

| Worker | Line range | Domain |
|--------|-----------|--------|
| **A** | 1 – 8730 | Parsers, graph construction, Tarjan SCC, PageRank, betweenness centrality, coupling metrics, behavioral flow analysis, semantic signals, analysis outcome logic |
| **B** | 8730 – 11576 | Worker result validation, LLM bundle generation, ask context packs, escalation controller, report builders, CLI entry point |

This split is a guidance boundary, not a hard fence. If a fix in your range touches a line just outside it, edit it.

---

## Sprint workflow

1. **Brain (Claude Code / Orchestrator)** reads the current state of the file, identifies tasks, writes a sprint
   briefing, and assigns tasks to Worker A and Worker B.
2. **You (Worker A or B)** receive your task briefing in the chat. Read it, implement the changes, verify, and
   write your result to your output file.
3. **Output files** are the handoff mechanism. Brain reads them directly — no copy-paste needed.
4. **Brain** reads both output files, integrates the results, and plans the next sprint.

---

## Output file format

Write your results to:
- Worker A → `worker_output_a.md` (overwrite entirely each sprint)
- Worker B → `worker_output_b.md` (overwrite entirely each sprint)

Use this structure:

```markdown
# Worker [A/B] Output

## Edits made

1. Brief description of what changed and where (file:line).
   ```python
   # new code
   ```

## Verification

1. `python -m py_compile god_mode_v3.py` — no output means pass.
2. Any `rg` spot-checks relevant to your changes (show command + result).

## Issues

None. (or describe any problems)
```

---

## Version bump

Every sprint that changes `god_mode_v3.py` must bump the version. The version lives at approximately line 670:

```python
                "version": "3.37",
```

Indentation is exactly 16 spaces (inside nested dict literals). Increment the minor version by 1 (e.g., 3.37 → 3.38).
Only one worker bumps the version per sprint — coordinate with your counterpart. If in doubt, Worker B bumps.

---

## Verification protocol

After every edit, run these two checks before writing your output:

```bash
python -m py_compile god_mode_v3.py
```
No output = pass.

```bash
rg -n "your_changed_pattern" god_mode_v3.py
```
Confirm the change is present (or absent if you removed something).

Use `rg` (ripgrep) for all searches. `grep` may not be available.

---

## CLI reference

```bash
# Full analysis + bundle
python god_mode_v3.py <project_root> --out report.json --bundle-dir <bundle_dir>

# Ask a query (generates a query-scoped context pack)
python god_mode_v3.py <project_root> --out report.json --ask "Where is auth enforced?" --bundle-dir <bundle_dir>

# Validate a worker result
python god_mode_v3.py --validate-worker-result result.json --against-ask-bundle <bundle_dir>

# Summary only (faster, omits full nodes+edges)
python god_mode_v3.py <project_root> --out report.json --summary-only
```

Key flags:

| Flag | Purpose |
|------|---------|
| `--out` | Output JSON report path |
| `--bundle-dir` | Directory to write the full LLM context bundle |
| `--ask` | Query string — generates a query-scoped ask context pack |
| `--question-file` | Same as `--ask` but reads the query from a file |
| `--validate-worker-result` | Validate a filled worker result JSON |
| `--against-ask-bundle` | Bundle dir to validate against |
| `--against-report` | Report JSON to validate against |
| `--top` | Number of top risks in the summary (default: 10) |
| `--context-lines` | Line budget for the context pack |
| `--ask-lines` | Line budget for the query-scoped ask pack |
| `--no-git-hotspots` | Disable Git history hotspot analysis |
| `--summary-only` | Write only summary sections, skip full graph |

---

## LLM bundle system

When you run SIA with `--bundle-dir`, it generates a directory containing:

| File | Contents |
|------|---------|
| `work_packet.json` | Operational contract: task, targets, read_order, allowed/disallowed claims |
| `worker_result_template.json` | Template the Codex worker must fill in |
| `worker_validation_rules.json` | Validation rules SIA uses to check the filled result |
| `worker_prompt.txt` | Instructions for the Codex worker |
| `worker_result_template.json` | Result structure to fill |
| `ask_context_pack.json` | Query-scoped evidence pack (smallest, read first) |
| `analysis_result.json` | SIA's own analysis result |
| `escalation_controller.json` | Whether escalation is allowed |
| `README_LLM.md` | Reading order for the bundle |

Codex workers fill `worker_result_template.json` using the evidence in the bundle. SIA validates the filled result:

```bash
python god_mode_v3.py --validate-worker-result filled_result.json --against-ask-bundle <bundle_dir>
```

**Worker terminal states** (defined as `WORKER_TERMINAL_STATES` in `god_mode_v3.py`):
`completed_within_bounds`, `stopped_on_guardrail`, `stopped_on_ambiguity`,
`stopped_on_insufficient_evidence`, `invalid_result`

---

## Fixtures

Three fixture directories exist in the project root for testing:

| Directory | Purpose |
|-----------|---------|
| `.sia_fixture/` | Minimal Python fixture (base.py, service.py, util.py) |
| `.multilang_fixture/` | Multi-language fixture |
| `.polyglot_graph_fixture/` | Polyglot fixture (Go, Java, Node, Python, Rust, TS) — used for all `llm_bundle_ask_*/` examples |

Run SIA against a fixture to test changes:

```bash
python god_mode_v3.py .polyglot_graph_fixture --out test_report.json --bundle-dir test_bundle
```

---

## Current state

- Version: **3.58**
- Status: **complete** — all 18 semantic signals covered in all 9 language extractors; all known pattern gaps closed
- Sprint history: 31 passes (Runs 1–3 autonomous, Sprints 1–28)
- **Next step: real-project testing**

---

## Key constants (quick reference)

```python
SEMANTIC_SIDE_EFFECT_SIGNALS      # superset: includes external_io, network_io, database_io, filesystem_io, process_io, state_mutation
SEMANTIC_EXTERNAL_IO_SIGNALS      # strict subset of SEMANTIC_SIDE_EFFECT_SIGNALS
WORKER_TERMINAL_STATES            # set of 5 terminal state strings (~line 193)
OUTCOME_MODE_ORDER                # ["unproven", "ambiguous", "partial", "confirmed"]
BEHAVIORAL_FLOW_STEP_ORDER        # step ordering for behavioral flow analysis
```

---

## Environment notes

- Python 3.x required (no third-party dependencies beyond stdlib + `gitpython` for hotspots)
- Use `rg` (ripgrep) for all search/verification — `grep` may not be installed
- On Windows: PowerShell available as fallback if bash commands fail
- `py_compile` is the canonical syntax check: `python -m py_compile god_mode_v3.py`
