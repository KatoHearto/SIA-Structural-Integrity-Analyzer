# Structural Integrity Analyzer v3 — Project Document

**Version:** 3.52 &nbsp;|&nbsp; **Status:** Active Development &nbsp;|&nbsp; **Build:** Passing &nbsp;|&nbsp; **Passes:** 24 &nbsp;|&nbsp; **Languages:** 9

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Project Background & Motivation](#2-project-background--motivation)
3. [Technical Architecture](#3-technical-architecture)
4. [Analysis Pipeline — Step by Step](#4-analysis-pipeline--step-by-step)
5. [Language Support Matrix](#5-language-support-matrix)
6. [Semantic Signal Catalog](#6-semantic-signal-catalog)
7. [CLI Reference](#7-cli-reference)
8. [The Worker Protocol (LLM Integration)](#8-the-worker-protocol-llm-integration)
9. [Self-Analysis — SIA Examining Itself](#9-self-analysis--sia-examining-itself)
10. [Honest Assessment — What Works, What Doesn't](#10-honest-assessment--what-works-what-doesnt)
11. [Development Effort Analysis](#11-development-effort-analysis)
12. [Sprint History](#12-sprint-history)
13. [Known Limitations & Open Issues](#13-known-limitations--open-issues)
14. [Conclusion](#14-conclusion)

---

## 1. Executive Summary

**Structural Integrity Analyzer v3 (SIA)** is a deterministic, static-analysis command-line tool written in Python. Its purpose is to parse a polyglot codebase, construct a directed dependency graph, compute coupling and centrality metrics for every symbol in the graph, and identify the highest-risk code — i.e., the symbols whose failure or incorrect modification would have the widest blast radius.

The entire tool is a **single Python file** (`god_mode_v3.py`) of **13,609 lines**. It supports **nine programming languages** (Python, JavaScript/TypeScript, Go, Java, Rust, C#, Kotlin, PHP, Ruby), detects **15 semantic signal types** across every language, and outputs a structured JSON report alongside an optional human-readable Markdown document.

A key secondary purpose is **LLM-context generation**: SIA can package the most relevant slices of a codebase into JSON bundles sized to fit inside a large-language model's context window, so that an LLM coding assistant receives precisely the code it needs rather than a raw file dump.

This document reflects the complete state of the project as of version 3.52 and provides a thorough, honest account of what SIA can and cannot do.

---

## 2. Project Background & Motivation

### 2.1 The Problem

When an LLM coding assistant is asked to refactor or extend a large codebase, it typically receives one of two things:

- **Too little context**: a handful of files with no visibility into how they connect to the rest of the system.
- **Too much context**: the entire repository pasted into the prompt, most of which is irrelevant and crowds out the signal.

Neither approach is reliable. The assistant may propose a change that looks correct locally but breaks a distant dependency. Without a structural view of the codebase, it cannot know which files are safe to touch and which are load-bearing.

### 2.2 The Hypothesis

SIA was built on a specific hypothesis:

> *If you can deterministically compute the coupling structure of a codebase and rank every symbol by how dangerous a change to it would be, you can build context packages that give an LLM exactly what it needs — and no more.*

### 2.3 What "Risk" Means in SIA

SIA's risk score is not a code-quality score. It does not measure whether code is well-written, whether it has tests, or whether it follows best practices. It measures **structural fragility**: how many other things depend on this symbol, how many things it depends on, how central it is in the dependency graph, and how many behavioral boundaries it crosses.

A symbol with a high risk score is not necessarily bad code. It is code where **a mistake has the widest consequences**.

---

## 3. Technical Architecture

### 3.1 Single-File Design

SIA is deliberately implemented as a single Python module with no runtime dependencies beyond the Python standard library. This is a conscious constraint, not an oversight.

**Why a single file?**

- Zero installation complexity — copy the file, run it.
- Trivially deployable in CI pipelines, Docker containers, or air-gapped environments.
- The tool can analyze codebases that use package managers it does not understand.
- The LLM workers that implement SIA can be given the entire tool in one context window.

The cost of this design is that the file is large and dense. At 13,609 lines it requires discipline to navigate. The sprint refactoring series (Sprints 15–17) deliberately decomposed its most complex methods to keep individual functions manageable.

### 3.2 Core Data Structures

```
SymbolNode
  ├── node_id          : str   — unique identifier (file:ClassName.methodName)
  ├── language         : str   — "Python", "Java", "TypeScript", etc.
  ├── kind             : str   — "function", "class", "module"
  ├── package_name     : str   — namespace / package / module path
  ├── risk_score       : float — computed after full graph analysis
  ├── ca               : int   — afferent coupling (how many depend on this)
  ├── ce_internal      : int   — efferent coupling to internal symbols
  ├── ce_external      : int   — efferent coupling to external / unresolved symbols
  ├── ce_total         : int   — ce_internal + ce_external
  ├── instability      : float — Ce / (Ca + Ce)  [Martin 1994]
  ├── pagerank         : float — recursive importance in the dependency graph
  ├── betweenness      : float — fraction of shortest paths that pass through this node
  ├── semantic_refs    : List  — detected behavioral signals with line numbers
  └── resolved_bases   : Set   — inheritance / interface targets resolved to node IDs
```

The graph itself is an adjacency dict `adj: Dict[str, Set[str]]` where each entry maps a source node ID to the set of nodes it depends on. Edge metadata (resolution kind, confidence, provenance) is stored in a parallel `edge_resolution` dict.

### 3.3 High-Level Module Map

```
god_mode_v3.py
│
├── Constants & helpers          lines 1    – 560
│   ├── LANGUAGE_BY_SUFFIX       (9 language dispatch table)
│   ├── IGNORE_DIRS              (standard exclusion list)
│   ├── SEMANTIC_SIGNAL_NAMES    (14 directly-emitted signals)
│   └── Module-level utilities   (source_group, source_qualname, stable_jitter, …)
│
├── AST visitors                 lines 561  – 612
│   └── CallCollector, ImportCollector (Python-only AST walkers)
│
├── StructuralIntegrityAnalyzerV3  lines 613 – 8730+  (the main class)
│   ├── __init__                 (graph state, exclude/filter config)
│   ├── run()                    (top-level pipeline orchestrator)
│   ├── _scan_files()            (directory walker with .siaignore support)
│   │
│   ├── Language parsers
│   │   ├── Python               (_parse_file, _collect_definitions, …)
│   │   ├── JavaScript/TypeScript (_parse_js_like_file, barrel resolution, …)
│   │   ├── Go                   (_parse_go_module, …)
│   │   ├── Java                 (_parse_java_file, _extract_java_symbol_payloads, …)
│   │   ├── Rust                 (_parse_rust_module, …)
│   │   ├── C#                   (_parse_csharp_file, …)
│   │   ├── Kotlin               (_parse_kotlin_file, …)
│   │   ├── PHP                  (_parse_php_file, …)
│   │   └── Ruby                 (_parse_ruby_file, _ruby_find_end, …)
│   │
│   ├── Graph analysis
│   │   ├── _resolve_edges()         (import + call resolution)
│   │   ├── _compute_betweenness()   (Brandes algorithm, approximate)
│   │   ├── _compute_page_rank()     (iterative PageRank)
│   │   ├── _compute_git_hotspots()  (git log integration, optional)
│   │   └── _compute_risk_scores()   (composite score)
│   │
│   ├── Semantic signal extraction
│   │   └── _extract_semantic_signals() → per-language _extract_*_semantic_spans()
│   │
│   └── Output builders
│       ├── _build_analysis_result()
│       ├── _build_llm_context_pack()
│       ├── _build_ask_context_pack()
│       ├── _build_project_inventory()
│       └── _build_project_context_pack()
│
├── Worker-result validation     lines 11896 – 12508
│   ├── validate_worker_result_payload()
│   └── build_worker_result_report()
│
├── CLI standalone functions     lines 12509 – 12700
│   ├── _build_markdown_report()
│   ├── _run_sia_why()
│   └── _run_sia_diff()
│
└── main()                       lines ~12700 – 13609
```

---

## 4. Analysis Pipeline — Step by Step

When `analyzer.run()` is called, the following stages execute in sequence:

### Stage 1 — File Discovery (`_scan_files`)

The tool walks the project root with `os.walk`, pruning:
- Directories in the hardcoded `IGNORE_DIRS` set (`.git`, `node_modules`, `__pycache__`, `.venv`, etc.)
- Directories matching user-supplied `--exclude` glob patterns
- Patterns listed in a `.siaignore` file at the project root
- Files whose language is not in the `--filter-language` whitelist (if provided)

Each discovered file is dispatched to its language parser. Python files use Python's built-in `ast` module for a full parse tree. All other languages use regex-based extraction.

### Stage 2 — Symbol Registration

Each parser emits **payloads** — dicts describing one symbol (a class, function, or module node). The `_register_non_python_node` method converts each payload into a `SymbolNode` and adds it to the graph. For Python, the AST walk directly populates nodes.

Every node receives a deterministic `node_id` of the form `file_stem:ClassName.method_name`.

### Stage 3 — Edge Resolution (`_resolve_edges`)

This is the most complex stage. For each node, SIA examines its raw imports, raw calls, and inheritance bases, and attempts to resolve them to concrete node IDs in the graph.

Resolution strategies (applied in order, stopping at first success):

| Strategy | Description |
|----------|-------------|
| `import_exact` | Import string matches a known package name or module path exactly |
| `import_heuristic` | Short name matches a unique node across the graph |
| `call_exact` | Call target name matches a known declared symbol uniquely |
| `call_heuristic` | Fuzzy name match with confidence scoring |
| `inheritance_exact` | Base class name resolves to a known class node |
| `barrel` | JS/TS re-export barrel files are traversed (depth-guarded at 8 hops) |

Unresolved edges contribute to `ce_external` (efferent coupling to external / unknown symbols) and still affect the instability score.

### Stage 4 — Graph Metrics

After edge resolution, three computations run on the fully-wired graph:

**Afferent coupling (Ca):** Count of edges pointing *into* this node (how many depend on it).

**Instability (Martin's metric):**
```
instability = Ce / (Ca + Ce)
```
Where Ce = ce_internal + ce_external. A symbol with instability = 1.0 depends on everything and nothing depends on it — it is a leaf and can be changed freely. A symbol with instability = 0.0 is depended on by many and depends on nothing — it is a stable foundation.

**PageRank** and **betweenness centrality** are computed using standard iterative algorithms. Betweenness uses an approximate Brandes-style algorithm truncated to avoid O(V·E) cost on large graphs.

### Stage 5 — Semantic Signal Extraction

For every node, SIA retrieves the source lines that belong to that node's body and scans them line-by-line against a battery of regex patterns. Each pattern match emits a **semantic reference** tagged with one of 14 signal types:

```
network_io       database_io      filesystem_io    process_io
config_access    input_boundary   output_boundary  validation_guard
auth_guard       error_handling   serialization    deserialization
state_mutation   time_or_randomness
```

A 15th signal, `external_io`, is **synthetically derived**: any symbol that has at least one `network_io`, `database_io`, `filesystem_io`, or `process_io` reference is tagged as an `external_io` caller.

The number and type of signals affect the risk score: a symbol that crosses four external boundaries is structurally more dangerous than one that crosses none.

### Stage 6 — Risk Score Computation

The composite risk score is calculated per node:

```
risk_score = (
    instability_component           # scaled by Ce weight
  + ca_component                    # logarithmic; high Ca = high blast radius
  + semantic_signal_component       # number of distinct external signal types
  + centrality_component            # PageRank + betweenness, normalized
  + git_hotspot_component           # change frequency (optional)
  + stable_jitter                   # deterministic tie-breaking
)
```

Scores are not bounded — they are relative to the codebase. A score of 50 in a 50-node codebase means something very different than a score of 50 in a 5,000-node codebase.

### Stage 7 — Output Generation

The pipeline closes by assembling the output report:

- **`top_risks`**: Top N symbols sorted by risk score descending.
- **`module_report`**: Per-module coupling aggregation.
- **`cycles`**: All dependency cycles detected by Tarjan's SCC algorithm, sorted by size descending.
- **`nodes` / `edges`**: Full graph (omitted with `--summary-only`).
- **`llm_context_pack`**: Curated source snippets for the top-risk symbols, budget-capped at `--context-lines` lines.
- **`ask_context_pack`**: Query-scoped context slice (when `--ask` is provided).
- **`project_inventory`**: All files, languages, line counts, and dependency metadata.

---

## 5. Language Support Matrix

| Language | Extension(s) | Parser Type | Symbol Extraction | Import Resolution | Semantic Signals |
|----------|-------------|-------------|-------------------|-------------------|-----------------|
| **Python** | `.py` | Full AST (`ast` module) | Classes, functions, methods, lambdas | Full static resolution | All 14 signals |
| **JavaScript** | `.js`, `.jsx`, `.mjs`, `.cjs` | Regex + brace-depth | Classes, functions, arrow fns, exports | Barrel traversal, tsconfig paths | All 14 signals |
| **TypeScript** | `.ts`, `.tsx` | Regex + brace-depth | Same as JS + interfaces, type aliases | Same as JS | All 14 signals |
| **Go** | `.go` | Regex (single module node per file) | Package-level functions, structs | Package path resolution | All 14 signals |
| **Java** | `.java` | Regex + brace-depth | Classes, interfaces, enums, methods | FQN + short-name resolution | All 14 signals |
| **Rust** | `.rs` | Regex + brace-depth | Structs, impls, functions, traits | Crate path resolution | All 14 signals |
| **C#** | `.cs` | Regex + brace-depth | Classes, interfaces, enums, methods | Namespace resolution | All 14 signals |
| **Kotlin** | `.kt`, `.kts` | Regex + brace-depth | Classes, objects, data classes, fns | Package resolution | All 14 signals |
| **PHP** | `.php` | Regex + brace-depth | Classes, traits, interfaces, methods | `use` + namespace resolution | All 14 signals |
| **Ruby** | `.rb` | Regex + `end`-depth | Classes, modules, instance/class methods | `require` path matching | All 14 signals |

> **Parser type note:** "Regex + brace-depth" means SIA uses a custom character-level scanner (`_compute_js_like_brace_depths`) to track nesting depth in `{}`-delimited languages. "End-depth" is an equivalent scanner for Ruby's `end`-keyword-delimited blocks. Neither approach is a full parser — see Section 10 for the implications.

---

## 6. Semantic Signal Catalog

Each signal is detected by pattern-matching source lines. Signals are language-specific but map to the same 14 categories across all languages.

| Signal | What it means | Example patterns |
|--------|--------------|-----------------|
| `network_io` | Outbound network call | `requests.get()`, `HttpClient`, `Net::HTTP`, `curl_exec` |
| `database_io` | Database read or write | `session.query()`, `DB::select()`, `ActiveRecord` |
| `filesystem_io` | File system access | `open()`, `File.read`, `fopen()`, `Storage::put()` |
| `process_io` | OS process execution | `subprocess`, `exec()`, `system()`, backtick in Ruby |
| `config_access` | Reads configuration or environment | `os.getenv()`, `ENV[]`, `config()`, `@ConfigurationProperties` |
| `input_boundary` | Entry point for external data | `@GetMapping`, `Route::get()`, `resources :posts` |
| `output_boundary` | Produces externally visible output | `render json:`, `response().json()`, `println!()` |
| `auth_guard` | Authentication or authorization check | `@Secured`, `Auth::check()`, `authenticate_user!` |
| `validation_guard` | Input validation enforcement | `$request->validate()`, `validates :title`, `@NotNull` |
| `error_handling` | Explicit exception handling | `try/catch`, `rescue`, `Result::Err`, `.onFailure` |
| `serialization` | Converts object to transmittable form | `json.dumps()`, `JSON.generate`, `JsonSerializer.Serialize` |
| `deserialization` | Reconstructs object from transmitted form | `json.loads()`, `JSON.parse`, `Marshal.load` |
| `state_mutation` | Mutates shared mutable state | `Cache::put()`, `$_SESSION`, `@Cacheable` |
| `time_or_randomness` | Non-deterministic inputs | `time.time()`, `SecureRandom.uuid`, `rand()`, `@Scheduled` |
| `external_io` *(synthetic)* | Has any of: network, database, filesystem, process | Derived — not directly emitted |

---

## 7. CLI Reference

SIA is invoked as:

```bash
python god_mode_v3.py [ROOT] [OPTIONS]
```

`ROOT` defaults to the current directory.

### Analysis flags

| Flag | Default | Description |
|------|---------|-------------|
| `--out PATH` | `sia_report.json` | Output JSON file path |
| `--top N` | `20` | Number of top-risk symbols in the report |
| `--context-lines N` | `220` | Line budget for the LLM context pack |
| `--ask-lines N` | `110` | Line budget for a query-scoped context slice |
| `--no-git-hotspots` | off | Disable git history analysis |
| `--summary-only` | off | Omit full `nodes` and `edges` arrays from JSON |
| `--ask QUERY` | — | Generate a query-scoped ask context pack |
| `--question-file PATH` | — | Read ask query from a UTF-8 text file |
| `--bundle-dir DIR` | — | Write a full LLM bundle to a directory |

### Filtering flags

| Flag | Description |
|------|-------------|
| `--exclude PATTERN` | Glob exclusion (repeatable); matches directory names and relative file paths |
| `--filter-language LANGS` | Comma-separated language whitelist (e.g. `Python,Java`) |

`.siaignore` in the project root is also read automatically; one pattern per line, `#` for comments.

### Output flags

| Flag | Description |
|------|-------------|
| `--markdown PATH` | Write a human-readable Markdown report alongside the JSON |

### Standalone modes (no analysis run)

| Flag | Description |
|------|-------------|
| `--diff OLD NEW` | Compare two SIA JSON reports; print what changed |
| `--why SYMBOL REPORT` | Explain why a specific symbol has a high risk score |

### Worker validation mode

| Flag | Description |
|------|-------------|
| `--validate-worker-result FILE` | Validate a filled worker result template |
| `--against-ask-bundle DIR` | Validate against an ask bundle directory |
| `--against-report FILE` | Validate against a full report JSON |

### Example: full run with Markdown output

```bash
python god_mode_v3.py ./my-project \
  --out reports/sia_report.json \
  --markdown reports/sia_report.md \
  --top 30 \
  --no-git-hotspots \
  --exclude vendor \
  --exclude build
```

### Example: explain a high-risk symbol

```bash
python god_mode_v3.py --why "UserService.processPayment" sia_report.json
```

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
  …

Dependency cycles: none
============================================================
```

---

## 8. The Worker Protocol (LLM Integration)

SIA includes a complete protocol for delegating implementation work to LLM "workers". This is the feature that makes SIA not just an analysis tool but an **LLM-native development workflow**.

### 8.1 The Three Roles

```
BRAIN (orchestrator — Claude)
  │
  ├── writes SPRINT_N.md (detailed briefing for two workers)
  │
  ├── Worker A (lines 1–8730 domain)
  │   └── implements parsers, graph logic, analysis methods
  │
  └── Worker B (lines 8730–end domain)
      └── implements output builders, CLI, standalone functions
```

The Brain writes a sprint briefing that specifies exact line anchors, full method bodies, and the expected verification steps. Workers have no context beyond what the briefing provides — they must be fully self-contained.

### 8.2 Ask Bundles

When SIA is run with `--ask "refactor the payment flow"`, it generates an **ask bundle** in an `llm_bundle_ask_*/` directory containing:

```
llm_bundle_ask_001/
  ├── work_packet.json          — the symbols SIA selected as relevant
  ├── worker_result_template.json   — the template the worker must fill
  ├── worker_validation_rules.json  — what counts as a valid result
  └── ask_context_pack.json     — curated source lines, max --ask-lines
```

The worker fills `worker_result_template.json` with its analysis and proposed changes. SIA can then validate the result with `--validate-worker-result`.

### 8.3 Validation

The `validate_worker_result_payload` function checks worker output against a formal bounded contract:

- Did the worker address all primary targets?
- Are all claims supported by evidence references?
- Does the completion state match the stop conditions?
- Are the claimed outcomes within the allowed outcome modes?

The validation report includes `valid`, `violations`, `warnings`, `next_action`, and `accepted_result_mode` — enough for an orchestrating LLM to decide whether to accept the result, request a fix, or continue with a follow-up.

---

## 9. Self-Analysis — SIA Examining Itself

One of the strongest tests of a static analysis tool is whether it can analyze its own source code and produce meaningful results. SIA was run on itself (`python god_mode_v3.py .`) with the following outcome:

### 9.1 Self-Analysis Statistics

| Metric | Value |
|--------|-------|
| Node count | 360 |
| Edge count | 616 |
| Dependency cycles | **1** |
| Parse errors | 0 |
| File analyzed | `god_mode_v3.py` (13,609 lines) |

### 9.2 Top 15 Highest-Risk Methods (self-reported)

| Rank | Method | Score | Ca | Ce | Instability |
|------|--------|-------|----|----|-------------|
| 1 | `_build_ask_context_pack` | 48.5 | 1 | 29 | 0.97 |
| 2 | `_resolve_import_outcome` | 39.0 | 2 | 11 | 0.75 |
| 3 | `_parse_non_python_file` | 36.0 | 1 | 8 | 0.89 |
| 4 | `_build_llm_context_pack` | 35.8 | 1 | 17 | 0.94 |
| 5 | `run` | 35.6 | 0 | 22 | 1.00 |
| 6 | `_build_analysis_result` | 34.9 | 1 | 18 | 0.95 |
| 7 | `_extract_semantic_signals` | 34.0 | 1 | 14 | 0.93 |
| 8 | `_extract_java_symbol_payloads` | 33.7 | 1 | 14 | 0.91 |
| 9 | `_resolve_js_like_import_outcome` | 33.6 | 3 | 5 | 0.62 |
| 10 | `_resolve_edges` | 33.1 | 1 | 9 | 0.90 |
| 11 | `_resolve_java_type_ref_outcome` | 32.2 | 2 | 6 | 0.75 |
| 12 | `_resolve_java_call_outcome` | 31.2 | 2 | 7 | 0.78 |
| 13 | `_resolve_js_like_call_outcome` | 31.1 | 2 | 7 | 0.78 |
| 14 | `_build_evidence_candidates` | 30.9 | 1 | 10 | 0.91 |
| 15 | `_build_project_context_pack` | 30.7 | 1 | 9 | 0.90 |

### 9.3 The Cycle

SIA detected one dependency cycle in itself:

```
_resolve_js_like_binding_reference_with_barrel
    ↔
_resolve_js_like_binding_target_with_barrel
```

This is **intentional mutual recursion** — barrel file resolution requires alternating between resolving a reference and resolving its binding target. The depth guard (introduced in Sprint 15, max depth = 8) prevents infinite loops. SIA correctly detects and reports this cycle.

### 9.4 Interpretation

The self-analysis results are coherent and expected:

- `run()` scoring high (instability = 1.00) is correct — it is the top-level orchestrator that calls everything and is called by nothing inside the class.
- `_build_ask_context_pack` scoring highest (Ce = 29) correctly identifies the most complex output builder, which was specifically targeted for decomposition in Sprint 15.
- The import resolution methods (`_resolve_import_outcome`, `_resolve_js_like_import_outcome`) scoring high correctly reflects their central, switch-like role — they dispatch to every language's resolution branch.
- The Java symbol extractor (`_extract_java_symbol_payloads`) appearing in the top 10 is expected — it is the most complex parser, handling annotations, DI, generics, and nested types.

**The self-analysis passes a key sanity check:** every method in the top 15 is one that a developer looking at the codebase would independently identify as important, complex, or load-bearing. The tool is not producing noise.

---

## 10. Honest Assessment — What Works, What Doesn't

This section is written with deliberate honesty. SIA is a real tool with real value, but also with real limitations that a user must understand before trusting its output.

### 10.1 What Works Well

#### Python Analysis — High Confidence

Python is analyzed using Python's own `ast` module. Import resolution, call graph construction, and class hierarchy detection are accurate to the degree that static analysis can be (no runtime behavior, no dynamic imports). For a Python-only codebase, SIA's coupling metrics are **reliable and production-ready**.

#### Dependency Cycle Detection — High Confidence

Tarjan's SCC algorithm is a well-established graph algorithm. If SIA's edge resolution constructs the graph correctly (which it does reasonably well), cycle detection is mathematically exact. Finding a cycle in SIA's output is a real finding.

#### Risk Ranking as a Relative Tool — Medium-High Confidence

The risk score is a heuristic, but it is a *calibrated* heuristic. In testing against SIA's own codebase, the top-ranked methods are consistently the ones a senior developer would identify as the most architecturally significant. The **relative order** of symbols by risk score is more meaningful than any individual score's absolute value.

#### LLM Context Generation — Medium Confidence

The context packs SIA generates are structurally sound — they contain the source lines for the highest-risk symbols, their imports, and their callers. Whether this produces better LLM behavior than alternative approaches has not been formally measured. Anecdotally, targeted context performs better than raw file dumps for complex refactoring tasks.

#### JavaScript/TypeScript, Java — Medium Confidence

JS/TS and Java parsers have been the most thoroughly developed. The barrel resolution system for JS/TS handles common patterns (index.ts re-exports, named exports, star exports). The Java parser handles annotations, Spring DI, generics stubs, and nested types. Both are regex-based and will fail on unusual patterns, but they cover the majority of common codebases.

### 10.2 What Doesn't Work Well

#### Non-Python Parsers Are Approximate

Every language parser except Python is built on regular expressions and a character-level brace/end counter. This is fundamentally an approximation. Specific failure modes:

- **Macros and metaprogramming** (Rust macros, Ruby `method_missing`, PHP magic methods) are invisible to regex.
- **Deeply nested or unusual formatting** can confuse the brace-depth counter.
- **String literals containing code patterns** can produce false positive semantic signals (e.g., a Python docstring that says "call `json.dumps()`" would trigger `serialization`).
- **Template literals, heredocs, multi-line strings** in various languages are not stripped before pattern matching.

#### Import Resolution Has Gaps

Import resolution in polyglot codebases is hard. SIA's resolution strategies work well within a single language but do not understand cross-language calls (e.g., a TypeScript frontend calling a Java backend via REST — these are separate graphs). Unresolved imports become `ce_external` edges, which still affects the instability score but adds noise.

#### The Risk Score Is Not Validated Against Ground Truth

SIA has never been evaluated against a dataset of production incidents to verify that "high risk score" correlates with "high probability of introducing a bug." It is plausible that it does — the underlying metrics (instability, coupling, centrality) have theoretical backing in software engineering literature — but this has not been empirically verified for SIA specifically.

#### The Polyglot Fixture Is Small

SIA's automated smoke test uses a fixture with 74 nodes. This is sufficient to verify that the tool doesn't crash, but it is too small to validate the quality of analysis on real-world polyglot codebases.

#### No Automated Test Suite

SIA has no unit tests, integration tests, or property-based tests beyond the fixture smoke test. The correctness guarantee is: `python -m py_compile god_mode_v3.py` passes, and the fixture produces the expected node/edge count. Regressions in analysis quality would not be caught automatically.

### 10.3 Summary Table

| Capability | Confidence | Notes |
|-----------|-----------|-------|
| Python coupling analysis | ★★★★★ | Full AST, accurate |
| JS/TS coupling analysis | ★★★★☆ | Good; barrel resolution is solid |
| Java coupling analysis | ★★★★☆ | Good; Spring patterns well-covered |
| Go/Rust/C#/Kotlin/PHP | ★★★☆☆ | Adequate; regex approximation |
| Ruby analysis | ★★★☆☆ | Adequate; `end`-depth approximation |
| Dependency cycle detection | ★★★★★ | Tarjan SCC, mathematically exact |
| Risk ranking (relative) | ★★★★☆ | Reliable for prioritization |
| Risk score (absolute) | ★★★☆☆ | Heuristic, not ground-truth |
| Semantic signal detection | ★★★☆☆ | Regex; false positives possible |
| LLM context quality | ★★★★☆ | Structurally sound; unvalidated empirically |
| Cross-language edges | ★★☆☆☆ | Not supported; treated as external |

---

## 11. Development Effort Analysis

### 11.1 What Was Built

| Category | Items |
|----------|-------|
| Language parsers | 9 languages × full parse chain (module + symbol + semantic + resolution) |
| Graph algorithms | Tarjan SCC, PageRank, betweenness centrality, coupling metrics |
| Semantic signals | 14 signal types × 9 languages = 126 pattern groups |
| Output formats | JSON, Markdown, diff, why-explainer |
| CLI flags | 16 flags |
| LLM integration | Ask bundles, worker protocol, validation engine |
| File infrastructure | `.siaignore`, `--exclude`, `--filter-language` |
| Total source lines | **13,609** |

### 11.2 Estimated Solo-Developer Timeline

The following estimates assume a **senior Python developer** who is familiar with compiler/parser concepts and reasonably comfortable reading all nine target languages. Times are full-time working days.

| Phase | Description | Estimated Days |
|-------|-------------|---------------|
| Architecture & design | Graph data structures, module organization, language dispatch | 10 |
| Python parser | Full AST integration, import resolution, call graph | 10 |
| JS/TypeScript parser | Brace-depth scanner, barrel resolution, tsconfig | 15 |
| Go parser | Package resolution, module discovery | 8 |
| Java parser | Class/method extraction, annotations, DI patterns, generics | 15 |
| Rust parser | Module system, impl blocks, traits | 8 |
| C# parser | Namespace/using, ASP.NET Core patterns, brace scanner | 8 |
| Kotlin parser | Coroutines, Spring Boot Kotlin, data classes | 8 |
| PHP parser | Namespace backslash normalization, Laravel patterns | 6 |
| Ruby parser | `end`-depth scanner, Rails patterns | 6 |
| Graph algorithms | Tarjan SCC, PageRank, betweenness, risk score | 15 |
| Semantic signals | 14 categories × 9 languages (research + implementation) | 20 |
| LLM bundle system | Context packs, ask bundles, project inventory | 12 |
| Worker validation | Contract system, outcome modes, validation report | 10 |
| CLI | 16 flags, all output modes, diff, why, markdown | 8 |
| Refactoring sprints | Method decomposition (Sprints 15–17 equivalent) | 8 |
| Testing & fixtures | Smoke test, polyglot fixture, edge cases | 10 |
| Bug fixing & iteration | Regression fixes, edge cases discovered in use | 15 |
| Documentation | WORKER_GUIDE.md, CHANGES.md, this document | 5 |
| **Total** | | **~181 working days** |

**181 working days ≈ 36 weeks ≈ 9 months of full-time work.**

> For a developer who is not already expert in several of the nine target languages, add 50–100% to the language parser phases. For a developer without prior experience in graph algorithms, add 50% to that phase. A realistic estimate for a skilled-but-not-expert developer: **12–16 months**.

### 11.3 Actual Development Velocity

SIA was developed in **24 passes** across 3 autonomous runs and 22 directed sprints. The sprints covered:

| Sprint group | Focus |
|-------------|-------|
| Runs 1–3 (autonomous) | Initial architecture, Python parser, core graph |
| Sprints 1–14 | Feature additions, language support 2–5, analysis pipeline |
| Sprints 15–17 | Major refactoring: method decomposition |
| Sprint 18 | Pattern coverage expansion (Java Spring, Python Celery, Rust) |
| Sprint 19 | C# (6th language) + `--diff` mode |
| Sprint 20 | Kotlin (7th language) + `--exclude` |
| Sprint 21 | PHP (8th language) + `--markdown` + `--why` |
| Sprint 22 | Ruby (9th language) + `.siaignore` + `--filter-language` |

---

## 12. Sprint History

| Pass | Version | Key Deliverable |
|------|---------|-----------------|
| Run 1 | 3.00 | Initial architecture: Python parser, graph, coupling metrics |
| Run 2 | 3.10 | JS/TS parser, barrel resolution |
| Run 3 | 3.20 | Go + Java + Rust parsers, Tarjan SCC |
| Sprint 1–5 | 3.21–3.30 | Semantic signals, PageRank, betweenness, LLM bundles |
| Sprint 6–10 | 3.31–3.38 | Ask context packs, project inventory, worker validation |
| Sprint 11–14 | 3.39–3.44 | Git hotspot integration, resolution improvements |
| Sprint 15 | 3.45 | Barrel resolver depth guard; `_build_ask_context_pack` decomposition |
| Sprint 16 | 3.46 | `_build_analysis_result` + `_build_work_packet` decomposition |
| Sprint 17 | 3.47 | `_build_llm_context_pack` refactor; JS/TS + Go pattern coverage |
| Sprint 18 | 3.48 | Java Spring (@KafkaListener, @Async, @Cacheable, @Scheduled); Python Celery; Rust (UUID, Redis, lapin) |
| Sprint 19 | 3.49 | C# as 6th language; `--diff OLD NEW` CLI mode |
| Sprint 20 | 3.50 | Kotlin as 7th language; `--exclude` glob patterns |
| Sprint 21 | 3.51 | PHP as 8th language; `--markdown`; `--why SYMBOL REPORT` |
| Sprint 22 | 3.52 | Ruby as 9th language; `.siaignore`; `--filter-language` |

---

## 13. Known Limitations & Open Issues

### Technical Debt

- **No automated test suite.** The only correctness check is a fixture smoke test (74-node polyglot project) and `py_compile`. Correctness of analysis is verified manually.
- **Single-file constraint.** At 13,609 lines, the file is approaching the practical upper bound for single-file maintenance. Further growth should be accompanied by additional method decomposition.
- **One intentional dead code path.** `if sigma[vertex] == 0: continue` in `_compute_betweenness` (~line 3310) is defensive dead code that is intentionally left in place.

### Known Parser Gaps

| Language | Known Gap |
|----------|-----------|
| Ruby | Metaprogramming (`define_method`, `method_missing`) is invisible |
| PHP | PHP 8 named arguments and intersection types not parsed |
| Rust | `macro_rules!` bodies are not analyzed |
| Go | Interface satisfaction is not checked; only explicit method calls resolved |
| JS/TS | Dynamic `require()` and computed import paths not resolved |
| All non-Python | String literals are not stripped before semantic signal scanning |

### Pending Features (Natural Next Steps)

- **`--watch` mode**: Auto-rerun on file changes for live feedback during development.
- **`--output-format {json,jsonl,compact}`**: Multiple JSON output formats for pipeline integration.
- **Cross-language edge support**: REST endpoint matching between frontend and backend.
- **Automated fixture expansion**: Adding Kotlin, PHP, C#, and Ruby files to the polyglot fixture for better regression coverage.
- **Formal benchmarking**: Validate the risk score against a curated dataset of production incidents.

---

## 14. Conclusion

The Structural Integrity Analyzer v3 is a **functional, production-capable tool** for structural analysis of polyglot codebases with a specific and well-defined use case: identifying the highest-risk symbols in a codebase and packaging them as context for LLM coding assistants.

Its Python analysis is accurate and reliable. Its polyglot support is broad but approximate — adequate for architectural insight and risk prioritization, not a substitute for language-specific linters or type checkers. Its risk ranking is a calibrated heuristic that agrees with expert developer judgment in the self-analysis case.

The tool's most distinctive property is its **LLM-native design**: the worker protocol, ask bundles, and validation engine treat LLMs as first-class actors in the development workflow rather than afterthoughts. This positions SIA not as a static analysis tool that outputs a report, but as an **infrastructure layer for AI-assisted development** — one that provides the structural understanding that makes LLM code changes reliable rather than lucky.

At an estimated 9+ months of solo developer effort to build from scratch, the tool represents a substantial investment of engineering time. The sprint-driven AI-assisted development approach used here achieved this scope considerably faster — but the correctness and robustness of the resulting system must be validated with real-world usage before trusting it on critical production codebases.

---

*Document generated: 2026-04-27 · SIA v3.52 · 13,609 lines · 9 languages · 24 development passes*
