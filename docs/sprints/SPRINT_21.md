# Sprint 21 Briefing

Read `WORKER_GUIDE.md` first. Worker A adds PHP as the eighth supported language (full parser,
symbol extraction, semantic spans, import resolution). Worker B adds two human-facing output
features: `--markdown PATH` (writes a readable `.md` report alongside the JSON) and
`--why SYMBOL REPORT` (standalone mode that explains a symbol's risk score from an existing
JSON report), then bumps the version and updates docs.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — PHP language support

Add PHP end-to-end: file detection, module + symbol parsing, semantic signal extraction, and
import outcome resolution. Follow the Java/CSharp/Kotlin pattern throughout — PHP uses the
same brace-delimited structure and can reuse `_compute_js_like_brace_depths` and
`_find_matching_brace`. PHP namespaces use backslash separators; store them with `.` internally
(replace `\\` with `.`).

---

#### Step 1 — Register `.php` extension

Find `LANGUAGE_BY_SUFFIX` (line ~55). Add one entry immediately after `.kts`:

```python
".php": "PHP",
```

---

#### Step 2 — Wire `_parse_non_python_file`

Find `_parse_non_python_file` (line ~972). Add a PHP dispatch block immediately after the
Kotlin block:

```python
        if language == "PHP":
            self._parse_php_file(rel_path, content, language)
            return
```

---

#### Step 3 — Implement `_parse_php_file`

Insert immediately after `_parse_kotlin_file` (line ~1113):

```python
    def _parse_php_file(self, rel_path: str, content: str, language: str) -> None:
        module_payload = self._parse_php_module(rel_path, content, language)
        module_name = str(module_payload.get("module") or source_group(rel_path, language))
        package_name = str(module_payload.get("package_name", ""))
        file_imports_symbols = dict(module_payload.get("imports_symbols", {}))
        self._register_non_python_node(rel_path, content, language, module_payload)
        for symbol_payload in self._extract_php_symbol_payloads(
            rel_path, content, module_name, package_name, file_imports_symbols,
        ):
            self._register_non_python_node(rel_path, content, language, symbol_payload)
```

---

#### Step 4 — Implement `_parse_php_module`

Insert immediately after `_parse_kotlin_module` (line ~1800, before `_extract_java_symbol_payloads`):

```python
    def _parse_php_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        ns_match = re.search(r"(?m)^\s*namespace\s+([\w\\]+)\s*[;{]", content)
        package_name = ns_match.group(1).replace("\\", ".") if ns_match else ""

        raw_imports: Set[str] = set(
            m.replace("\\", ".")
            for m in re.findall(
                r"(?m)^\s*use\s+(?:function\s+|const\s+)?([\w\\]+)(?:\s+as\s+\w+)?\s*;",
                content,
            )
        )

        declared_symbols = re.findall(
            r"(?m)^\s*(?:(?:abstract|final|readonly)\s+)*"
            r"(?:class|interface|trait|enum)\s+([A-Za-z_]\w*)\b",
            content,
        )[:20]

        raw_bases: Set[str] = set()
        for extend_m in re.findall(r"\bextends\s+([\w\\]+)", content):
            raw_bases.add(extend_m.replace("\\", ".").split(".")[-1])
        for impl_m in re.findall(r"\bimplements\s+([\w\\,\s]+?)(?:\{|$)", content):
            for part in re.split(r",\s*", impl_m.strip()):
                clean = part.strip().replace("\\", ".").split(".")[-1]
                if clean:
                    raw_bases.add(clean)

        return {
            "module": source_group(rel_path, language, package_name),
            "qualname": source_qualname(rel_path),
            "kind": "module",
            "package_name": package_name,
            "imports_modules": {},
            "imports_symbols": {},
            "declared_symbols": declared_symbols,
            "raw_imports": raw_imports,
            "raw_bases": raw_bases,
        }
```

---

#### Step 5 — Implement `_extract_php_symbol_payloads`

Insert immediately after `_extract_kotlin_symbol_payloads` ends (before `_extract_java_method_payloads`
at line ~2100). Reuses `_compute_js_like_brace_depths` and `_find_matching_brace`.

```python
    def _extract_php_symbol_payloads(
        self,
        rel_path: str,
        content: str,
        module_name: str,
        package_name: str,
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        payloads: List[Dict[str, object]] = []
        depth_map = self._compute_js_like_brace_depths(content)

        type_pattern = re.compile(
            r"(?m)^\s*(?:(?:abstract|final|readonly)\s+)*"
            r"(class|interface|trait|enum)\s+([A-Za-z_]\w*)\b([^{]*)\{"
        )
        method_pattern = re.compile(
            r"(?m)^\s*(?:(?:public|protected|private|static|abstract|final)\s+)*"
            r"function\s+([A-Za-z_]\w*)\s*\([^)]*\)\s*(?::\s*[\w?\\|]+\s*)?\{"
        )

        for type_match in type_pattern.finditer(content):
            if depth_map[type_match.start()] > 1:
                continue
            type_kind = type_match.group(1)
            type_name = type_match.group(2)
            tail = type_match.group(3) or ""

            open_brace = content.find("{", type_match.end() - 1)
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(content, open_brace)
            if close_brace < 0:
                continue

            raw_bases: Set[str] = set()
            for m in re.findall(r"\bextends\s+([\w\\]+)", tail):
                raw_bases.add(m.replace("\\", ".").split(".")[-1])
            for m in re.findall(r"\bimplements\s+([\w\\,\s]+?)(?:\{|$)", tail + " {"):
                for part in re.split(r",\s*", m.strip()):
                    clean = part.strip().replace("\\", ".").split(".")[-1]
                    if clean:
                        raw_bases.add(clean)

            body = content[open_brace + 1:close_brace]
            payloads.append({
                "module": module_name,
                "qualname": type_name,
                "kind": "class" if type_kind in {"class", "trait"} else type_kind,
                "class_context": type_name,
                "package_name": package_name,
                "imports_symbols": dict(imports_symbols),
                "member_types": {},
                "member_qualifiers": {},
                "declared_symbols": [],
                "annotations": [],
                "bean_name": "",
                "is_abstract": bool(re.search(r"\babstract\b", type_match.group(0))),
                "di_primary": False,
                "raw_calls": set(),
                "raw_bases": raw_bases,
                "lines": self._span_to_lines(content, type_match.start(), close_brace),
            })

            body_depth_map = self._compute_js_like_brace_depths(body)
            body_offset = open_brace + 1
            for method_match in method_pattern.finditer(body):
                method_name = method_match.group(1)
                if method_name in {"if", "for", "foreach", "while", "switch", "catch",
                                   "match", "try", "return", "throw"}:
                    continue
                if body_depth_map[method_match.start()] > 1:
                    continue
                abs_start = body_offset + method_match.start()
                m_open = body.find("{", method_match.start())
                if m_open < 0:
                    m_close = method_match.end()
                else:
                    m_close = self._find_matching_brace(body, m_open)
                abs_end = body_offset + (m_close if m_close >= 0 else method_match.end())
                payloads.append({
                    "module": module_name,
                    "qualname": f"{type_name}.{method_name}",
                    "kind": "function",
                    "class_context": type_name,
                    "package_name": package_name,
                    "imports_symbols": dict(imports_symbols),
                    "member_types": {},
                    "member_qualifiers": {},
                    "declared_symbols": [],
                    "annotations": [],
                    "bean_name": "",
                    "is_abstract": False,
                    "di_primary": False,
                    "raw_calls": set(),
                    "raw_bases": set(),
                    "lines": self._span_to_lines(content, abs_start, abs_end),
                })

        return payloads
```

---

#### Step 6 — Wire semantic spans dispatch

Find the semantic spans dispatch (line ~4119) where Kotlin was added in Sprint 20:

```python
            elif node.language == "Kotlin":
                refs = self._extract_kotlin_semantic_spans(node, source_lines)
```

Add immediately after:

```python
            elif node.language == "PHP":
                refs = self._extract_php_semantic_spans(node, source_lines)
```

---

#### Step 7 — Implement `_extract_php_semantic_spans`

Insert immediately after `_extract_kotlin_semantic_spans` ends (line ~4800+, before
`_semantic_summary_for_node`):

```python
    def _extract_php_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            # input_boundary — Laravel routing attributes and Route facade
            if (
                re.search(r"\bRoute::(?:get|post|put|delete|patch|any)\s*\(", text)
                or re.search(r"#\[(?:Route|Get|Post|Put|Delete|Patch)\b", text)
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno,
                                          "Laravel route definition or HTTP attribute marks an input boundary.")
            # auth_guard — Auth facade, auth() helper, middleware guard
            if (
                re.search(r"\bAuth::(?:check|user|guard|id)\s*\(", text)
                or re.search(r"\bauth\s*\(\s*\)->(?:user|check|id)\s*\(", text)
                or re.search(r"\$request->user\s*\(", text)
                or re.search(r"#\[Authorize\b", text)
                or re.search(r"->middleware\s*\(\s*['\"]auth", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno,
                                          "Laravel Auth guard or authorization middleware.")
            # validation_guard — FormRequest, Validator facade, inline validate()
            if (
                re.search(r"\$request->validate\s*\(", text)
                or re.search(r"\bValidator::make\s*\(", text)
                or re.search(r"#\[Rule\b", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno,
                                          "Laravel/Symfony validation enforces input constraints.")
            # database_io — PDO, MySQLi, Eloquent/Query Builder, Doctrine
            if (
                re.search(r"\bnew\s+PDO\s*\(", text)
                or re.search(r"\$(?:pdo|db)->(?:query|prepare|exec|execute|fetchAll|fetch)\s*\(", text)
                or re.search(r"\bmysqli_\w+\s*\(|\$mysqli->(?:query|prepare|execute)\s*\(", text)
                or re.search(r"\bDB::(?:select|insert|update|delete|table|statement)\s*\(", text)
                or re.search(r"::(?:find|findOrFail|where|create|update|delete|first|all|save)\s*\(", text)
                or re.search(r"->(?:where|select|from|join|orderBy|groupBy|having|get|first|count|save)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno,
                                          "Database access via PDO/MySQLi/Eloquent/Doctrine.")
            # network_io — cURL, Guzzle, Laravel Http facade, file_get_contents(URL)
            if (
                re.search(r"\bcurl_(?:init|exec|setopt)\s*\(", text)
                or re.search(r"\$(?:http)?[Cc]lient->(?:get|post|put|delete|request|send)\s*\(", text)
                or re.search(r"\bHttp::(?:get|post|put|delete|withHeaders|withToken)\s*\(", text)
                or re.search(r"\bfile_get_contents\s*\(\s*['\"]https?://", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno,
                                          "HTTP client or remote file fetch.")
            # filesystem_io — file functions (not URL-based)
            if (
                re.search(r"\bfile_(?:get_contents|put_contents|exists|delete)\s*\(", text)
                or re.search(r"\b(?:fopen|fclose|fwrite|fread|fgets|fputs)\s*\(", text)
                or re.search(r"\b(?:unlink|mkdir|rmdir|glob|scandir|opendir|readdir)\s*\(", text)
                or re.search(r"\bStorage::(?:put|get|delete|disk|exists|download)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno,
                                          "File system access in PHP code.")
            # process_io — shell execution functions
            if re.search(r"\b(?:exec|shell_exec|system|passthru|proc_open|popen)\s*\(", text):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno,
                                          "PHP shell-execution function spawns an OS process.")
            # config_access — getenv, $_ENV, $_SERVER, Laravel config/env helpers
            if (
                re.search(r"\bgetenv\s*\(", text)
                or re.search(r"\$_(?:ENV|SERVER)\b", text)
                or re.search(r"\bconfig\s*\(\s*['\"]", text)
                or re.search(r"\benv\s*\(\s*['\"]", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno,
                                          "Reads configuration or environment variable.")
            # serialization — json_encode, serialize
            if re.search(r"\bjson_encode\s*\(|\bserialize\s*\(", text):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno,
                                          "Serializes data to JSON or PHP format.")
            # deserialization — json_decode, unserialize
            if re.search(r"\bjson_decode\s*\(|\bunserialize\s*\(", text):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno,
                                          "Deserializes data from JSON or PHP format.")
            # time_or_randomness — time/date/random functions
            if (
                re.search(r"\btime\s*\(\s*\)|\bmicrotime\s*\(|\bdate\s*\(|\bstrtotime\s*\(", text)
                or re.search(r"\brand\s*\(|\bmt_rand\s*\(|\brandom_int\s*\(|\brandom_bytes\s*\(", text)
                or re.search(r"\bStr::(?:uuid|random|orderedUuid)\s*\(", text)
                or re.search(r"\bCarbon::(?:now|today|parse)\s*\(", text)
                or re.search(r"\bnew\s+\\\?DateTime\s*\(|\bnew\s+DateTimeImmutable\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno,
                                          "Uses time or randomness sources.")
            # state_mutation — session + Laravel cache
            if (
                re.search(r"\$_SESSION\b", text)
                or re.search(r"\bCache::(?:put|forget|forever|remember)\s*\(", text)
                or re.search(r"\bcache\s*\(\s*\)->(?:put|forget|remember)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno,
                                          "Mutates session or cache state.")
            # error_handling — try/catch/throw
            if re.search(r"\b(?:try|catch|throw)\b", text):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno,
                                          "Contains explicit PHP error handling.")
            # output_boundary — echo/print/response
            if (
                re.search(r"\becho\b|\bprint\b", text)
                or re.search(r"\bresponse\s*\(\s*\)->json\s*\(", text)
                or re.search(r"\breturn\s+response\s*\(", text)
                or re.search(r"\breturn\s+(?:new\s+)?JsonResponse\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno,
                                          "Produces observable output (echo, response).")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs
```

---

#### Step 8 — Wire import resolution

Find `_resolve_import_outcome` and the Kotlin branch (line ~2949). Add a PHP branch
immediately after the Kotlin `return ResolutionOutcome(target=None)` line:

```python
        if caller.language == "PHP":
            # `use` directives store package_name with "." separators
            candidates = [
                nid for nid, nd in self.nodes.items()
                if nd.language == "PHP" and nd.package_name
                and (nd.package_name == raw or nd.package_name.endswith("." + raw))
                and nd.kind != "module"
            ]
            if len(candidates) == 1:
                return self._resolution(
                    target=candidates[0],
                    kind="import_exact",
                    reason=f"Resolved PHP use `{raw}` exactly.",
                )
            return ResolutionOutcome(target=None)
```

---

#### Verification (Worker A)

1. `python -m py_compile god_mode_v3.py` — must pass with no output.
2. `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only` — must print
   `nodes=74, edges=58, cycles=0, parse_errors=0` (fixture has no .php files, count unchanged).
3. `rg -n '"PHP"|_parse_php|_extract_php' god_mode_v3.py` — confirm all integration points.
4. Inline smoke-test (run once, do not leave in file):
   ```python
   import re
   php = '<?php\nnamespace App\\Services;\nuse App\\Models\\User;\nclass UserService {\n    public function getUser(int $id): User {\n        try {\n            $user = User::find($id);\n        } catch (\\Exception $e) {\n            throw $e;\n        }\n        return $user;\n    }\n}'
   ns = re.search(r"(?m)^\s*namespace\s+([\w\\]+)\s*[;{]", php)
   assert ns and ns.group(1).replace("\\\\", ".") == "App.Services"
   assert re.search(r"::find\s*\(", php)
   assert re.search(r"\btry\b", php)
   print("PHP smoke OK")
   ```

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–end (module-level functions and `main()`).

### Task B1 — `_build_markdown_report` function

Add a module-level function `_build_markdown_report` immediately before `_run_sia_diff`
(currently at line ~12509). It takes the full report dict and returns a Markdown string.

```python
def _build_markdown_report(report: Dict[str, object]) -> str:
    import datetime as _dt
    meta = report.get("meta", {})
    version = meta.get("version", "?")
    node_count = meta.get("node_count", 0)
    edge_count = meta.get("edge_count", 0)
    cycle_count = meta.get("cycle_count", 0)
    lang_dist: Dict[str, int] = meta.get("language_distribution", {})
    generated = meta.get("generated_at") or _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines: List[str] = []

    lines.append("# SIA Report\n")
    lines.append(f"> Generated {generated} · SIA v{version} · {node_count} nodes · {edge_count} edges · {cycle_count} cycles\n")
    lines.append("")

    # --- Top Risks ---
    top_risks: List[Dict[str, object]] = report.get("top_risks", [])
    if top_risks:
        lines.append("## Top Risks\n")
        lines.append("| # | Symbol | Lang | Kind | Score | Ca | Ce | Instability | SPOF |")
        lines.append("|---|--------|------|------|-------|----|----|-------------|------|")
        for rank, entry in enumerate(top_risks, start=1):
            sym = str(entry.get("symbol", ""))
            lang = str(entry.get("language", ""))
            kind = str(entry.get("kind", ""))
            score = float(entry.get("risk_score", 0.0))
            metrics = entry.get("metrics", {})
            ca = metrics.get("ca", 0)
            ce = metrics.get("ce_total", 0)
            inst = metrics.get("instability", 0.0)
            spof = "✓" if entry.get("single_point_of_failure") else ""
            signals = entry.get("semantic_signals", [])
            sig_str = (
                f"<br>*{', '.join(str(s) for s in signals[:3])}{'…' if len(signals) > 3 else ''}*"
                if signals else ""
            )
            lines.append(
                f"| {rank} | `{sym}`{sig_str} | {lang} | {kind} | {score:.1f} | {ca} | {ce} | {inst:.2f} | {spof} |"
            )
        lines.append("")

    # --- Dependency Cycles ---
    cycles: List[List[str]] = report.get("cycles", [])
    if cycles:
        lines.append(f"## Dependency Cycles\n")
        lines.append(f"**{len(cycles)} cycle{'s' if len(cycles) != 1 else ''} detected.**\n")
        for i, cycle in enumerate(cycles[:20], start=1):
            chain = " → ".join(f"`{s}`" for s in cycle) + f" → `{cycle[0]}`"
            lines.append(f"{i}. {chain}")
        if len(cycles) > 20:
            lines.append(f"\n*…and {len(cycles) - 20} more.*")
        lines.append("")

    # --- Language Distribution ---
    if lang_dist:
        lines.append("## Language Distribution\n")
        lines.append("| Language | Nodes |")
        lines.append("|----------|-------|")
        for lang, count in sorted(lang_dist.items(), key=lambda x: -x[1]):
            lines.append(f"| {lang} | {count} |")
        lines.append("")

    # --- Module Coupling ---
    module_report: List[Dict[str, object]] = report.get("module_report", [])
    if module_report:
        lines.append("## Module Coupling\n")
        lines.append("| Module | Lang | Ca | Ce | Instability | Parse Errors |")
        lines.append("|--------|------|----|----|-------------|--------------|")
        for mod in module_report[:40]:
            mname = str(mod.get("module", ""))
            mlang = str(mod.get("language", ""))
            mca = mod.get("ca", 0)
            mce = mod.get("ce", 0)
            minst = float(mod.get("instability", 0.0))
            merr = mod.get("parse_errors", 0)
            lines.append(f"| `{mname}` | {mlang} | {mca} | {mce} | {minst:.2f} | {merr} |")
        if len(module_report) > 40:
            lines.append(f"\n*…and {len(module_report) - 40} more modules.*")
        lines.append("")

    return "\n".join(lines)
```

---

### Task B2 — `_run_sia_why` function

Add a module-level function `_run_sia_why` immediately after `_build_markdown_report` and
before `_run_sia_diff`:

```python
def _run_sia_why(symbol: str, report_path: str) -> None:
    import sys as _sys
    try:
        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)
    except Exception as exc:
        print(f"Error loading {report_path}: {exc}", file=_sys.stderr)
        raise SystemExit(1)

    # Find in top_risks
    risk_entry: Optional[Dict[str, object]] = None
    for entry in report.get("top_risks", []):
        if str(entry.get("symbol", "")) == symbol:
            risk_entry = entry
            break

    # Find in nodes (full report only)
    node_entry: Optional[Dict[str, object]] = None
    for nd in report.get("nodes", []):
        if str(nd.get("node_id", "")) == symbol:
            node_entry = nd
            break

    if risk_entry is None and node_entry is None:
        print(f"Symbol '{symbol}' not found in {report_path}.", file=_sys.stderr)
        print("Tip: run without --summary-only so 'nodes' is included, or check the symbol name.", file=_sys.stderr)
        raise SystemExit(1)

    sep = "=" * 60
    print(f"\n{sep}")
    print(f"Symbol: {symbol}")
    if risk_entry:
        lang = risk_entry.get("language", "?")
        kind = risk_entry.get("kind", "?")
        score = float(risk_entry.get("risk_score", 0.0))
        spof = risk_entry.get("single_point_of_failure", False)
        metrics = risk_entry.get("metrics", {})
        ca = metrics.get("ca", "?")
        ce = metrics.get("ce_total", "?")
        inst = metrics.get("instability", "?")
        git_h = metrics.get("git_hotspot_score", 0)
        signals: List[str] = [str(s) for s in risk_entry.get("semantic_signals", [])]
        print(f"Language: {lang}  Kind: {kind}  Risk score: {score:.1f}  SPOF: {'yes' if spof else 'no'}")
        print()
        print("Coupling")
        print(f"  Afferent  Ca = {ca}   (symbols that depend on this one)")
        print(f"  Efferent  Ce = {ce}   (symbols this one depends on)")
        print(f"  Instability    = {inst if isinstance(inst, str) else f'{inst:.2f}'}")
        if git_h:
            print(f"  Git hotspot    = {git_h:.2f}")
        if signals:
            print()
            print(f"Semantic signals: {', '.join(signals)}")
    elif node_entry:
        print(f"(Not in top risks — node found with risk_score={node_entry.get('risk_score', '?')})")

    # Edges from the full graph
    callers: List[str] = []
    callees: List[str] = []
    for edge in report.get("edges", []):
        src = str(edge.get("source", ""))
        dst = str(edge.get("target", ""))
        if dst == symbol:
            callers.append(src)
        if src == symbol:
            callees.append(dst)
    if callers or callees:
        print()
        if callers:
            print(f"Incoming edges ({len(callers)}):")
            for c in sorted(callers)[:10]:
                print(f"  ← {c}")
            if len(callers) > 10:
                print(f"  … and {len(callers) - 10} more")
        if callees:
            print(f"Outgoing edges ({len(callees)}):")
            for c in sorted(callees)[:10]:
                print(f"  → {c}")
            if len(callees) > 10:
                print(f"  … and {len(callees) - 10} more")

    # Cycles involving this symbol
    cycles_with: List[List[str]] = [
        c for c in report.get("cycles", []) if symbol in c
    ]
    if cycles_with:
        print()
        print(f"Dependency cycles containing this symbol ({len(cycles_with)}):")
        for cycle in cycles_with[:5]:
            print(f"  {' → '.join(cycle)} → {cycle[0]}")
    else:
        print()
        print("Dependency cycles: none")

    print(sep)
```

---

### Task B3 — Wire `--markdown` and `--why` into `main()`

#### Step 1 — Add CLI arguments

After the `--exclude` block (line ~12654) and before `args = parser.parse_args()`, add:

```python
    parser.add_argument(
        "--markdown",
        default="",
        metavar="PATH",
        help="Write a human-readable Markdown report to PATH alongside the JSON output.",
    )
    parser.add_argument(
        "--why",
        nargs=2,
        metavar=("SYMBOL", "REPORT"),
        default=None,
        help="Explain why SYMBOL scores high in REPORT JSON file. No analysis is run.",
    )
```

#### Step 2 — Early exit for `--why`

After the `if args.diff:` block (line ~12657), add:

```python
    if args.why:
        _run_sia_why(args.why[0], args.why[1])
        return
```

#### Step 3 — Write Markdown after JSON

After the line `print(f"Top risks written to: {out_path}")` (line ~12735), add:

```python
    if args.markdown:
        md_path = os.path.abspath(args.markdown)
        md_text = _build_markdown_report(report)
        with open(md_path, "w", encoding="utf-8") as handle:
            handle.write(md_text)
        print(f"Markdown report written to: {md_path}")
```

---

### Task B4 — Version bump + docs

1. Bump `"version"` at line ~676 from `"3.50"` to `"3.51"`.
2. Update `WORKER_GUIDE.md` lines ~193 and ~195 to `**3.51**` and
   `23 passes (Runs 1–3 autonomous, Sprints 1–21)`. Add PHP to the supported-languages line.
3. Append to `CHANGES.md`:

```
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
```

---

### Verification (Worker B)

1. `python -m py_compile god_mode_v3.py` — must pass with no output.
2. `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only` — nodes=74,
   edges=58, cycles=0, parse_errors=0.
3. `python god_mode_v3.py .polyglot_graph_fixture --out sia_test.json --markdown sia_test.md`
   — both files created; check `sia_test.md` starts with `# SIA Report`.
4. `python god_mode_v3.py --why "<some_high_risk_symbol_from_sia_test.json>" sia_test.json`
   — prints structured output without error. Pick any symbol that appears in `top_risks`.
5. `rg -n '"version"|_build_markdown_report|_run_sia_why|--markdown|--why' god_mode_v3.py`
   — confirm all wiring points.
6. `rg -n 'Version: \*\*3\.51\*\*|23 passes|Sprint 21|PHP' WORKER_GUIDE.md CHANGES.md`
   — confirm docs updated.
7. Clean up `sia_test.json` and `sia_test.md` after verification.
