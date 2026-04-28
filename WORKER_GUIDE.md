# Worker Guide — Project Magnetic Entanglement

## What this project is

**Structural Integrity Analyzer v3 (SIA v3)** — a deterministic static analysis tool for polyglot codebases.
Single-file Python tool: `god_mode_v3.py` (currently ~14,200 lines).

Supported languages: Python, JavaScript/TypeScript, Go, Java, Rust, C#, Kotlin, PHP, Ruby.
Optional plugin: --plugin frappe (DocType JSON, ORM resolution, hooks.py enrichment).

Produces: symbol graphs, coupling metrics (Ca/Ce/instability), Tarjan SCC cycle detection, PageRank, betweenness
centrality, layered architecture diagrams, taint-flow paths, exploitability scores, absence warnings,
pattern libraries, fix suggestions, and LLM context bundles for downstream AI workers.

---

## Autonomy

**You have full autonomy to edit `god_mode_v3.py` directly. Do not ask for permission before making any change to
this file or any file in this project directory. Implement, verify, write your result, and stop.**

---

## Das Build-Modell

`god_mode_v3.py` ist ein **Build-Artefakt** — nie direkt bearbeiten.

Der Source-Code liegt in `src/` (20 Module). Nach jeder Änderung:
```bash
python build.py        # baut god_mode_v3.py aus src/
python -m py_compile god_mode_v3.py   # Syntax-Check
```

### Modul-Übersicht

| Datei | Inhalt | god_mode_v3.py Zeilen |
|-------|--------|-----------------------|
| `src/00_header.py` | Imports, Konstanten, Regex, _TAINT_SOURCE_KINDS | 1–401 |
| `src/01_core_classes.py` | SymbolNode, ResolutionOutcome, Collector-Klassen | 402–691 |
| `src/02_analyzer_init.py` | class StructuralIntegrityAnalyzerV3 + `__init__` | 692–730 |
| `src/03_run_scan.py` | `run()`, `_scan_files()` | 731–950 |
| `src/04_frappe_scanner.py` | Frappe/JSON-Scanner | 951–1079 |
| `src/05_parser_dispatch.py` | `_parse_file`, `_parse_non_python_file` | 1080–1395 |
| `src/10_parser_other.py` | C#, Kotlin, PHP, Ruby | 1396–1455 |
| `src/06_parser_js.py` | JS/TS-Parser | 1456–2024 |
| `src/07_parser_go.py` | Go-Parser | 2025–2058 |
| `src/08_parser_java.py` | Java-Parser + Symbol-Extraktoren | 2059–3159 |
| `src/09_parser_rust.py` | Rust-Parser | 3160–3219 |
| `src/11_graph_indices.py` | `_build_indices()` | 3220–3559 |
| `src/12_taint.py` | `_compute_taint_metadata()`, Hook-Paths | 3560–3913 |
| `src/13_graph_metrics.py` | Graph-Aufbau, PageRank, Betweenness, Layers, Signale | 3914–9500 |
| `src/14_analysis.py` | Semantik, Behavioral Flow, LLM-Context-Pack | 9501–13575 |
| `src/15_worker_validation.py` | Top-Level-Validierungs-Funktionen | 13576–13969 |
| `src/16_report_builders.py` | `build_worker_result_report()` | 13970–14188 |
| `src/17_markdown_report.py` | `_build_markdown_report()` | 14189–14332 |
| `src/18_sia_commands.py` | `_run_sia_why()`, `_run_sia_diff()` | 14333–14592 |
| `src/19_cli.py` | `main()` + CLI | 14593–14809 |

**Build-Reihenfolge** ist in `build.py` festgelegt (nicht alphabetisch — `10_parser_other.py` kommt zwischen `05` und `06`).

### Domain split (Worker A vs Worker B)

| Worker | Line range | Domain |
|--------|-----------|--------|
| **A** | 1 – 9500 | Parsers, graph construction, Tarjan SCC, PageRank, betweenness centrality, coupling metrics, behavioral flow analysis, semantic signals, taint source classification, taint propagation, absence detection (symmetry + spec alignment), pattern library extraction, analysis outcome logic |
| **B** | 9500 – 14200 | Worker result validation, LLM bundle generation, ask context packs, escalation controller, report builders, CLI entry point (`sia brief`, `sia verify`, `sia patterns`), exploitability scoring output, fix suggestion rendering |

This split is a guidance boundary, not a hard fence. If a fix in your range touches a line just outside it, edit it.

### When is only one worker needed?

Not every sprint requires both workers. Use this table:

| Sprint | Workers needed | Reason |
|--------|---------------|--------|
| 32 | **A only** | Taint source classification is purely graph construction |
| 33 | **A + B** | A: propagation logic; B: exploitability score output + report section |
| 34 | **B only** | `sia brief` is CLI + report rendering, no graph changes |
| 35 | **B only** | `sia verify` is CLI + diff logic, no graph changes |
| 36 | **A + B** | A: symmetry rule engine + sibling detection; B: absence_warnings report section |
| 37 | **A + B** | A: spec parser + matcher; B: spec_gap warning output + coverage metric |
| 38 | **A + B** | A: pattern extraction pass; B: `sia patterns` CLI + library output |
| 39 | **A + B** | A: suggestion engine + adaptation logic; B: suggestion block in all warning outputs |

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

Every sprint that changes `god_mode_v3.py` must bump the version.
The version lives in **`src/00_header.py`** (ca. Zeile 773 im Original):

```python
                "version": "3.62",
```

Indentation is exactly 16 spaces. Increment the minor version by 1 (e.g., 3.62 → 3.63).
Only one worker bumps the version per sprint — coordinate with your counterpart. If in doubt, Worker B bumps.
After bumping: run `python build.py` before verifying.

---

## Verification protocol

After every edit to a `src/` file:

```bash
python build.py                         # rebuild god_mode_v3.py
python -m py_compile god_mode_v3.py    # syntax check — no output = pass
```

Then confirm the change is present in the built file:
```bash
rg -n "your_changed_pattern" god_mode_v3.py
```

Use `rg` (ripgrep) for all searches. `grep` may not be available.

**Note on parse_errors when scanning this project:** `src/` files are Python
fragments (class methods without class header) — SIA's own parser reports
parse_errors when analyzing them. This is expected and not a regression.
Use `tests/fixtures/polyglot` for functional regression checks:
```bash
python god_mode_v3.py tests/fixtures/polyglot --no-git-hotspots --summary-only
# Expected baseline: nodes=75  edges=61  cycles=0  parse_errors=0
```

---

## CLI reference

```bash
# Full analysis + bundle
python god_mode_v3.py <project_root> --out report.json --bundle-dir <bundle_dir>

# Full analysis with taint-flow (Sprint 32+)
python god_mode_v3.py <project_root> --out report.json --taint

# Full analysis with spec alignment (Sprint 37+)
python god_mode_v3.py <project_root> --out report.json --taint --spec docs/API.md

# Ask a query (generates a query-scoped context pack)
python god_mode_v3.py <project_root> --out report.json --ask "Where is auth enforced?" --bundle-dir <bundle_dir>

# Validate a worker result
python god_mode_v3.py --validate-worker-result result.json --against-ask-bundle <bundle_dir>

# Summary only (faster, omits full nodes+edges)
python god_mode_v3.py <project_root> --out report.json --summary-only

# Generate chirurgisches worker brief for a specific node (Sprint 34+)
python god_mode_v3.py sia brief <node_id> --task fix|extend|verify --output markdown|json

# Verify a fix after a worker run (Sprint 35+)
python god_mode_v3.py sia verify <before.json> <after.json> --node <node_id> --strict

# List patterns from the codebase pattern library (Sprint 38+)
python god_mode_v3.py sia patterns --type regex_validation --lang python --domain <hint>
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
| `--taint` | Enable taint-flow analysis (Sprint 32+) |
| `--spec <path>` | Spec document for alignment analysis (Sprint 37+) |
| `--no-absence` | Skip absence detection (Sprint 36+) |
| `--no-suggestions` | Skip fix suggestion generation (Sprint 39+) |
| `--no-patterns` | Skip pattern library extraction (Sprint 38+) |

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

Fixtures live in `tests/fixtures/`:

| Directory | Purpose | Baseline |
|-----------|---------|---------|
| `tests/fixtures/minimal/` | Minimal Python fixture (base.py, service.py, util.py) | — |
| `tests/fixtures/multilang/` | Multi-language fixture | — |
| `tests/fixtures/polyglot/` | Polyglot (Go, Java, Node, Python, Rust, TS) | nodes=75, edges=61, cycles=0 |
| `tests/fixtures/frappe/` | Frappe DocType fixture | nodes=13, edges=20, cycles=2 |

Run SIA against a fixture to test changes:

```bash
python god_mode_v3.py tests/fixtures/polyglot --out test_report.json --no-git-hotspots --summary-only
python god_mode_v3.py tests/fixtures/frappe --plugin frappe --out test_frappe.json --no-git-hotspots --summary-only
```

---

## Current state

- Version: **3.62**
- Status: **active development** — Sprint 32 (Taint) complete; Sprint R1 (Restrukturierung) complete; Sprints 33–39 folgen
- Sprint history: 36 passes (Runs 1–3 autonomous, Sprints 1–31, Sprint 32, Sprint R1)
- **Next sprint: 33 (Taint Propagation + Exploitability Score — Worker A + B)**
- **Build-Modell aktiv:** `src/` editieren, `python build.py` ausführen, nie `god_mode_v3.py` direkt bearbeiten

### Sprint roadmap (32–39)

| Sprint | Version | Title | Workers |
|--------|---------|-------|---------|
| 32 | 3.61 → 3.62 | Taint Source Classification | A |
| 33 | 3.62 → 3.63 | Taint Propagation + Exploitability Score | A + B |
| 34 | 3.63 → 3.64 | `sia brief` — Chirurgisches Worker Briefing | B |
| 35 | 3.64 → 3.65 | `sia verify` — Verifikations-Loop | B |
| 36 | 3.65 → 3.66 | Absence Detection: Graph Symmetry | A + B |
| 37 | 3.66 → 3.67 | Absence Detection: Spec Alignment (`--spec`) | A + B |
| 38 | 3.67 → 3.68 | Pattern Library Extraction (`sia patterns`) | A + B |
| 39 | 3.68 → 3.69 | Fix Suggestions (Prescriptive Output) | A + B |

Full sprint specs in `docs/sprints/SPRINT_32.md` through `SPRINT_39.md`.

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
