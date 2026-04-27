# SIA — Structural Integrity Analyzer

> Deterministic static analysis for polyglot codebases. Identifies your highest-risk code and packages it as context for LLM coding assistants.

[![GitHub](https://img.shields.io/badge/GitHub-KatoHearto%2FSIA--Structural--Integrity--Analyzer-181717?logo=github)](https://github.com/KatoHearto/SIA-Structural-Integrity-Analyzer)
![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python&logoColor=white)
![Languages](https://img.shields.io/badge/Languages-9-green)
![Version](https://img.shields.io/badge/Version-3.58-orange)
![License](https://img.shields.io/badge/License-MIT-lightgrey)
![Lines](https://img.shields.io/badge/Source-14%2C150%20lines-informational)

---

## What is SIA?

SIA walks a multi-language project, builds a directed dependency graph of every class and function, computes coupling metrics and centrality scores for every node, and ranks all symbols by **structural risk** — how wide the blast radius would be if that symbol were changed incorrectly.

It then packages the top-risk symbols as curated context slices for use by LLM coding assistants, so the model receives precisely the code it needs rather than a raw file dump.

**One file. No dependencies beyond the Python standard library.**

---

## Quick Start

```bash
# Analyze the current directory
python god_mode_v3.py .

# Specify output and top-N
python god_mode_v3.py ./my-project --out report.json --top 30

# Also write a human-readable Markdown report
python god_mode_v3.py ./my-project --out report.json --markdown report.md

# Explain why a specific symbol is high-risk
python god_mode_v3.py --why "UserService.processPayment" report.json

# Compare two reports (e.g. before and after a refactor)
python god_mode_v3.py --diff report_before.json report_after.json

# Only analyze specific languages
python god_mode_v3.py ./my-project --filter-language Python,Java

# Exclude directories
python god_mode_v3.py ./my-project --exclude vendor --exclude build
```

---

## Supported Languages

| Language | Extensions | Parser |
|----------|-----------|--------|
| Python | `.py` | Full AST (`ast` module) |
| JavaScript | `.js` `.jsx` `.mjs` `.cjs` | Regex + brace-depth + barrel resolution |
| TypeScript | `.ts` `.tsx` | Regex + brace-depth + barrel resolution |
| Go | `.go` | Regex |
| Java | `.java` | Regex + brace-depth |
| Rust | `.rs` | Regex + brace-depth |
| C# | `.cs` | Regex + brace-depth |
| Kotlin | `.kt` `.kts` | Regex + brace-depth |
| PHP | `.php` | Regex + brace-depth |
| Ruby | `.rb` | Regex + end-depth |

---

## What SIA Measures

### Coupling Metrics (Robert C. Martin, 1994)

| Metric | Formula | Meaning |
|--------|---------|---------|
| **Ca** (Afferent) | count of inbound edges | How many symbols depend on this one |
| **Ce** (Efferent) | count of outbound edges | How many symbols this one depends on |
| **Instability** | Ce / (Ca + Ce) | 0 = stable foundation, 1 = freely changeable leaf |

### Additional Signals

- **PageRank** — recursive importance in the dependency graph
- **Betweenness centrality** — how often this node sits on the shortest path between others
- **Git hotspot score** — change frequency from `git log` (optional, `--no-git-hotspots` to disable)
- **Semantic signals** — 18 behavioral categories detected per symbol (see below)

### Semantic Signals

```
network_io       database_io      filesystem_io    process_io
config_access    input_boundary   output_boundary  validation_guard
auth_guard       error_handling   serialization    deserialization
state_mutation   time_or_randomness  dynamic_dispatch  orm_dynamic_load
concurrency      caching
```

Each signal is detected by language-specific pattern matching across all 9 languages.

---

## Output

### JSON Report (`--out`)

```json
{
  "meta": { "version": "3.54", "node_count": 360, "edge_count": 616 },
  "top_risks": [
    {
      "symbol": "UserService.processPayment",
      "language": "Java",
      "risk_score": 71.4,
      "single_point_of_failure": true,
      "metrics": { "ca": 6, "ce_total": 12, "instability": 0.67 },
      "semantic_signals": ["database_io", "network_io", "auth_guard"]
    }
  ],
  "cycles": [["A.foo", "B.bar", "A.foo"]],
  "module_report": [...],
  "llm_context_pack": { ... }
}
```

### Markdown Report (`--markdown`)

Generates a GitHub-flavored Markdown file with a top-risks table, dependency cycles, language distribution, and module coupling overview.

### `--why` Explainer

```
============================================================
Symbol: UserService.processPayment
Language: Java  Kind: function  Risk score: 71.4  SPOF: yes

Coupling
  Afferent  Ca = 6   (symbols that depend on this one)
  Efferent  Ce = 12  (symbols this one depends on)
  Instability    = 0.67

Semantic signals: database_io, network_io, auth_guard, error_handling

Incoming edges (6):
  ← OrderController.checkout
  ← SubscriptionService.renew
============================================================
```

---

## LLM Integration — The Worker Protocol

SIA includes a structured workflow for delegating analysis and implementation to LLM workers:

```bash
# Generate a query-scoped context bundle
python god_mode_v3.py ./my-project --ask "refactor the payment service" --bundle-dir ./bundle

# Validate a worker's filled result template
python god_mode_v3.py --validate-worker-result worker_result.json --against-report sia_report.json
```

See [`WORKER_GUIDE.md`](WORKER_GUIDE.md) for the full worker protocol.

---

## Project Exclusions

### `.siaignore`

Place a `.siaignore` file in your project root — one glob pattern per line, `#` for comments:

```
# .siaignore
vendor
build
dist
*.generated.ts
```

Patterns are merged with any `--exclude` flags you pass on the CLI.

---

## Plugin: Frappe

Activate with `--plugin frappe` to parse Frappe DocType JSON definitions:

```bash
python god_mode_v3.py ./my-frappe-app --plugin frappe
```

SIA will:
- Create `kind="doctype"` graph nodes for every DocType JSON found
- Add `doctype_link` edges for Link fields and `doctype_child` edges for Table fields
- Resolve each DocType to its Python controller via the Frappe path convention
- Detect `hooks.py` string references and ORM event triggers automatically
- Resolve Frappe ORM string-path references (e.g. `frappe.get_doc("Customer")`) to DocType nodes

If SIA detects a Frappe project without the flag, it prints an advisory to stderr.

---

## CLI Reference

| Flag | Default | Description |
|------|---------|-------------|
| `--out PATH` | `sia_report.json` | Output JSON path |
| `--top N` | `20` | Number of top-risk symbols |
| `--markdown PATH` | — | Write Markdown report |
| `--summary-only` | off | Omit full nodes/edges from JSON |
| `--no-git-hotspots` | off | Disable git history analysis |
| `--context-lines N` | `220` | LLM context line budget |
| `--ask QUERY` | — | Generate query-scoped ask bundle |
| `--bundle-dir DIR` | — | Write full LLM bundle to directory |
| `--exclude PATTERN` | — | Glob exclusion (repeatable) |
| `--filter-language LANGS` | — | Comma-separated language whitelist |
| `--plugin NAMES` | — | Activate optional plugins (currently: `frappe`) |
| `--diff OLD NEW` | — | Compare two SIA JSON reports |
| `--why SYMBOL REPORT` | — | Explain a symbol's risk score |
| `--validate-worker-result` | — | Validate a filled worker result |

---

## Self-Analysis

SIA can analyze its own source. Running it on `god_mode_v3.py`:

```
nodes=379  edges=657  cycles=1  parse_errors=0
```

The one detected cycle is an intentional mutual recursion in the JS/TS barrel resolver, guarded by a depth limit of 8 hops.

Top-ranked method: `_build_ask_context_pack` (score=48.5, Ce=29, instability=0.97) — correctly identified as the most complex orchestrator in the codebase.

---

## Development History

SIA was developed in **31 passes** (3 autonomous runs + 28 directed sprints) using an AI-assisted workflow where Claude acted as both architect and implementation worker.

| Sprints | Deliverable |
|---------|-------------|
| Runs 1–3 | Initial architecture: Python parser, graph, coupling metrics |
| Sprints 1–14 | JS/TS/Go/Java/Rust parsers, semantic signals, LLM bundles, worker protocol |
| Sprints 15–17 | Method decomposition, JS/TS + Go pattern coverage |
| Sprint 18 | Java Spring, Python Celery, Rust pattern gaps |
| Sprint 19 | C# (6th language), `--diff` mode |
| Sprint 20 | Kotlin (7th language), `--exclude` |
| Sprint 21 | PHP (8th language), `--markdown`, `--why` |
| Sprint 22 | Ruby (9th language), `.siaignore`, `--filter-language` |
| Sprint 23–24 | Frappe Plugin: DocTypes, Link/Child fields, Controllers |
| Sprint 25 | Frappe Plugin: ORM resolution + Semantic enrichment |
| Sprint 26 | Frappe Plugin: JS cross-language, polish, documentation |
| Sprint 27 | New semantic signals: `concurrency` + `caching` (all 9 languages) |
| Sprint 28 | Guard propagation: `reachable_guards` from callers (depth ≤ 2) |

Full changelog: [`CHANGES.md`](CHANGES.md)  
Sprint briefings: [`docs/sprints/`](docs/sprints/)

---

## Requirements

- Python 3.9+
- No third-party packages
- Optional: `git` in PATH for `--git-hotspots` analysis

---

## License

MIT — see [`LICENSE`](LICENSE)
