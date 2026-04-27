# Sprint 20 Briefing

Read `WORKER_GUIDE.md` first. Worker A adds Kotlin as the seventh supported language (full parser,
symbol extraction, semantic spans, import resolution). Worker B adds an `--exclude PATTERN` CLI
flag for user-controlled file/directory exclusion, bumps the version, and updates docs. Worker B
will also make two small additions to `__init__` and `_scan_files` (both in Worker A's nominal
domain but small enough to own here to keep the feature self-contained in one worker).

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — Kotlin language support

Add Kotlin end-to-end: file detection, module + symbol parsing, semantic signal extraction, and
import outcome resolution. Follow the Java/CSharp pattern throughout — Kotlin shares Java's
brace-delimited structure and reuses `_compute_js_like_brace_depths` and `_find_matching_brace`.

---

#### Step 1 — Register `.kt` and `.kts` extensions

Find `LANGUAGE_BY_SUFFIX` (line ~55). Add two entries immediately after the `.cs` entry:

```python
".kt": "Kotlin",
".kts": "Kotlin",
```

---

#### Step 2 — Wire `_parse_non_python_file`

Find `_parse_non_python_file` (line ~972). Add a Kotlin dispatch block immediately after the
CSharp block (lines ~984-986):

```python
        if language == "Kotlin":
            self._parse_kotlin_file(rel_path, content, language)
            return
```

---

#### Step 3 — Implement `_parse_kotlin_file`

Insert this method immediately after `_parse_csharp_file` (line ~1082, before `_parse_js_like_module`):

```python
    def _parse_kotlin_file(self, rel_path: str, content: str, language: str) -> None:
        module_payload = self._parse_kotlin_module(rel_path, content, language)
        module_name = str(module_payload.get("module") or source_group(rel_path, language))
        package_name = str(module_payload.get("package_name", ""))
        file_imports_symbols = dict(module_payload.get("imports_symbols", {}))
        self._register_non_python_node(rel_path, content, language, module_payload)
        for symbol_payload in self._extract_kotlin_symbol_payloads(
            rel_path, content, module_name, package_name, file_imports_symbols,
        ):
            self._register_non_python_node(rel_path, content, language, symbol_payload)
```

---

#### Step 4 — Implement `_parse_kotlin_module`

Insert immediately after `_parse_csharp_module` (line ~1721, before `_extract_java_symbol_payloads`):

```python
    def _parse_kotlin_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        pkg_match = re.search(r"(?m)^\s*package\s+([\w.]+)", content)
        package_name = pkg_match.group(1).strip() if pkg_match else ""

        raw_imports: Set[str] = set(
            re.findall(r"(?m)^\s*import\s+([\w.*]+)", content)
        )

        declared_symbols = re.findall(
            r"(?m)^\s*(?:(?:public|private|protected|internal|open|abstract|sealed|data|"
            r"value|inline|companion|inner|override|suspend)\s+)*"
            r"(?:class|interface|object|enum\s+class|fun)\s+([A-Za-z_]\w*)\b",
            content,
        )[:20]

        raw_bases: Set[str] = set()
        for tail in re.findall(
            r"(?:class|object)\s+\w+(?:\s*<[^>]*>)?(?:\s*\([^)]*\))?\s*:\s*([A-Za-z_][\w(),\s<>?]*?)\s*(?:\{|$)",
            content,
        ):
            for part in re.split(r",\s*", tail):
                part = re.sub(r"<.*?>|\(.*?\)", "", part).strip()
                if part and re.match(r"[A-Za-z_]\w*", part):
                    raw_bases.add(part)

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

#### Step 5 — Implement `_extract_kotlin_symbol_payloads`

Insert immediately after `_extract_csharp_symbol_payloads` ends (before `_extract_java_method_payloads`
at line ~1935). Use `_compute_js_like_brace_depths` and `_find_matching_brace` to locate class
bodies, then `_extract_kotlin_method_payloads` for methods within each class plus a pass for
top-level `fun` declarations.

```python
    def _extract_kotlin_symbol_payloads(
        self,
        rel_path: str,
        content: str,
        module_name: str,
        package_name: str,
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        payloads: List[Dict[str, object]] = []
        depth_map = self._compute_js_like_brace_depths(content)

        # Top-level type declarations
        type_pattern = re.compile(
            r"(?m)^\s*(?:(?:public|private|protected|internal|open|abstract|sealed|data|"
            r"value|inline|companion|inner|annotation)\s+)*"
            r"(class|interface|object|enum\s+class)\s+([A-Za-z_]\w*)\b([^{]*)\{"
        )
        method_pattern = re.compile(
            r"(?m)^\s*(?:(?:public|private|protected|internal|open|override|abstract|"
            r"suspend|inline|operator|infix|tailrec|external|actual|expect)\s+)*"
            r"fun\s+(?:<[^>]*>\s*)?(?:[\w.]+\s*\.\s*)?([A-Za-z_]\w*)\s*\([^)]*\)"
            r"(?:\s*:\s*[\w<>?,.\s]+)?\s*(?:=\s*[^\n]+|(?:where\s+[\w\s:,<>]+\s*)?\{)"
        )

        for type_match in type_pattern.finditer(content):
            if depth_map[type_match.start()] > 1:
                continue
            type_kind_raw = type_match.group(1)
            type_name = type_match.group(2)
            tail = type_match.group(3) or ""

            open_brace = content.find("{", type_match.end() - 1)
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(content, open_brace)
            if close_brace < 0:
                continue

            raw_bases: Set[str] = set()
            colon_match = re.search(r":\s*([\w(),\s<>?]+?)(?:\{|where\b)", tail + " {")
            if colon_match:
                for part in re.split(r",\s*", colon_match.group(1)):
                    part = re.sub(r"<.*?>|\(.*?\)", "", part).strip()
                    if part and re.match(r"[A-Za-z_]\w*", part):
                        raw_bases.add(part)

            body = content[open_brace + 1:close_brace]
            type_kind = "class" if "class" in type_kind_raw else type_kind_raw

            payloads.append({
                "module": module_name,
                "qualname": type_name,
                "kind": type_kind,
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
                if method_name in {"if", "for", "while", "when", "catch", "try", "return",
                                   "throw", "object", "companion", "init"}:
                    continue
                if body_depth_map[method_match.start()] > 1:
                    continue
                abs_start = body_offset + method_match.start()
                method_open = body.find("{", method_match.start())
                if method_open < 0:
                    method_close = method_match.end()
                else:
                    method_close = self._find_matching_brace(body, method_open)
                abs_end = body_offset + (method_close if method_close >= 0 else method_match.end())
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

        # Top-level functions (not inside any class/object)
        for fun_match in method_pattern.finditer(content):
            if depth_map[fun_match.start()] > 1:
                continue
            # Skip if this position is covered by a type body already parsed
            fun_name = fun_match.group(1)
            if fun_name in {"if", "for", "while", "when", "catch", "try", "return",
                            "throw", "object", "companion", "init"}:
                continue
            fun_open = content.find("{", fun_match.start())
            if fun_open < 0:
                fun_end = fun_match.end()
            else:
                fun_end = self._find_matching_brace(content, fun_open)
            payloads.append({
                "module": module_name,
                "qualname": fun_name,
                "kind": "function",
                "class_context": "",
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
                "lines": self._span_to_lines(content, fun_match.start(), fun_end if fun_end >= 0 else fun_match.end()),
            })

        return payloads
```

---

#### Step 6 — Wire semantic spans dispatch

Find the semantic spans dispatch block (line ~3891) where CSharp was added in Sprint 19:

```python
            elif node.language == "CSharp":
                refs = self._extract_csharp_semantic_spans(node, source_lines)
```

Add immediately after:

```python
            elif node.language == "Kotlin":
                refs = self._extract_kotlin_semantic_spans(node, source_lines)
```

---

#### Step 7 — Implement `_extract_kotlin_semantic_spans`

Insert immediately after `_extract_csharp_semantic_spans` ends (line ~4437, before
`_semantic_summary_for_node`):

```python
    def _extract_kotlin_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            # input_boundary — HTTP + message listener annotations (Spring/Ktor)
            if re.search(
                r"@(?:GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|"
                r"RequestMapping|RestController|Controller|KafkaListener|"
                r"RabbitListener|SqsListener|EventListener|JmsListener)\b",
                text,
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno,
                                          "HTTP route or message-listener annotation marks an input boundary.")
            # auth_guard — Spring Security + JWT
            if re.search(
                r"@(?:Secured|PreAuthorize|PostAuthorize|RolesAllowed)\b"
                r"|SecurityContextHolder\b"
                r"|\bAuthentication\b",
                text,
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno,
                                          "Spring Security annotation or context access.")
            # validation_guard — Bean Validation + Spring @Validated
            if re.search(
                r"@(?:Valid|Validated|NotNull|NotEmpty|NotBlank|Size|Min|Max|Email|Pattern|"
                r"Positive|Negative|DecimalMin|DecimalMax|AssertTrue|AssertFalse)\b",
                text,
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno,
                                          "Bean Validation annotation enforces input constraints.")
            # database_io — Room (Android), JPA/Hibernate, exposed, R2DBC
            if re.search(
                r"@(?:Query|Insert|Update|Delete|Dao|Entity|Repository)\b"
                r"|\bRoom\.databaseBuilder\s*\("
                r"|\bJdbcTemplate\b"
                r"|\btransaction\s*\{"
                r"|\bDatabase\.connect\s*\(",
                text,
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno,
                                          "Database access via Room/JPA/Exposed.")
            # network_io — HttpClient (Ktor, OkHttp, Retrofit, Spring)
            if (
                re.search(r"\bHttpClient\s*\(|\bnew HttpClient\b", text)
                or re.search(r"\bOkHttpClient\s*\(", text)
                or re.search(r"\bRetrofit\.Builder\s*\(", text)
                or re.search(r"\b(?:WebClient|RestTemplate)\b", text)
                or re.search(r"client\.(?:get|post|put|delete|patch)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno,
                                          "HTTP client network call.")
            # filesystem_io — kotlin.io + java.io file helpers
            if (
                re.search(r"\bFile\s*\(", text)
                or re.search(r"\.readText\s*\(|\.writeText\s*\(|\.readLines\s*\(|\.appendText\s*\(", text)
                or re.search(r"\bPaths\.get\s*\(|\bFiles\.\w+\s*\(", text)
                or re.search(r"\bnew FileInputStream\b|\bnew FileOutputStream\b", text)
            ):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno,
                                          "File system access in Kotlin code.")
            # process_io — coroutines (launch/async/runBlocking are async execution boundaries)
            if re.search(
                r"\b(?:launch|async|runBlocking|withContext|GlobalScope\.launch|"
                r"CoroutineScope|supervisorScope|coroutineScope)\s*[{\(]",
                text,
            ):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno,
                                          "Coroutine builder creates a concurrent execution context.")
            # config_access — @Value, @ConfigurationProperties, System.getenv, environment
            if (
                re.search(r"@(?:Value|ConfigurationProperties)\b", text)
                or re.search(r"\bSystem\.getenv\s*\(", text)
                or re.search(r"\benvironment\.getProperty\s*\(|\benvironment\.getRequiredProperty\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno,
                                          "Reads configuration or environment variable.")
            # serialization — kotlinx.serialization, Gson, Jackson
            if (
                re.search(r"\bJson\.encodeToString\s*\(", text)
                or re.search(r"\bjacksonObjectMapper\s*\(\)|\.writeValueAsString\s*\(", text)
                or re.search(r"\bGson\s*\(\)\.toJson\s*\(", text)
                or re.search(r"@Serializable\b", text)
            ):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno,
                                          "Serializes object to JSON.")
            # deserialization — kotlinx.serialization, Gson, Jackson
            if (
                re.search(r"\bJson\.decodeFromString\s*\(", text)
                or re.search(r"\.readValue\s*\(", text)
                or re.search(r"\bGson\s*\(\)\.fromJson\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno,
                                          "Deserializes object from JSON.")
            # time_or_randomness — clocks, UUIDs, Random, @Scheduled
            if (
                re.search(r"\bSystem\.currentTimeMillis\s*\(|\bSystem\.nanoTime\s*\(", text)
                or re.search(r"\bLocalDateTime\.now\s*\(|\bInstant\.now\s*\(|\bClock\.systemUTC\s*\(", text)
                or re.search(r"\bUUID\.randomUUID\s*\(", text)
                or re.search(r"\bRandom\.nextInt\b|\bRandom\.nextLong\b|\bkotlin\.random\.Random\b", text)
                or re.search(r"@Scheduled\b", text)
            ):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno,
                                          "Uses time or randomness sources.")
            # state_mutation — cache annotations
            if re.search(r"@(?:Cacheable|CacheEvict|CachePut|Caching)\b", text):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno,
                                          "Spring cache annotation mutates a shared cache store.")
            # error_handling — try/catch/runCatching/.onFailure
            if (
                re.search(r"\b(?:try|catch|throw)\b", text)
                or re.search(r"\brun[Cc]atching\s*\{", text)
                or re.search(r"\.onFailure\s*\{|\.getOrThrow\s*\(|\.getOrElse\s*\{", text)
            ):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno,
                                          "Contains explicit Kotlin error handling.")
            # output_boundary — logging + response bodies
            if (
                re.search(r"\b(?:println|print)\s*\(", text)
                or re.search(r"\blog(?:ger)?\.(?:info|warn|error|debug|trace)\s*\(", text)
                or re.search(r"\bResponseEntity\b|\bcall\.respond\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno,
                                          "Produces observable output (log, response).")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs
```

---

#### Step 8 — Wire import resolution

Find `_resolve_import_outcome` and the CSharp branch (line ~2727). Add a Kotlin branch
immediately after the CSharp `return ResolutionOutcome(target=None)` line:

```python
        if caller.language == "Kotlin":
            # Exact match on package_name (Kotlin package == Java package semantics)
            candidates = [
                nid for nid, nd in self.nodes.items()
                if nd.language == "Kotlin" and nd.package_name
                and (nd.package_name == raw or nd.package_name.startswith(raw + "."))
                and nd.kind != "module"
            ]
            if len(candidates) == 1:
                return self._resolution(
                    target=candidates[0],
                    kind="import_exact",
                    reason=f"Resolved Kotlin import `{raw}` exactly.",
                )
            return ResolutionOutcome(target=None)
```

---

#### Verification (Worker A)

1. `python -m py_compile god_mode_v3.py` — must pass with no output.
2. `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only` — must print
   `nodes=74, edges=58, cycles=0, parse_errors=0` (fixture has no .kt files, count unchanged).
3. `rg -n '"Kotlin"\|_parse_kotlin\|_extract_kotlin' god_mode_v3.py` — confirm all 8
   integration points appear at their expected lines.
4. Inline smoke-test (run once, do not leave in the file):
   ```python
   import re, tempfile, os
   kt = '''package com.example\nimport com.example.Repo\nclass UserService(val repo: Repo) {\n    suspend fun getUser(id: Int): User {\n        val r = runBlocking { repo.find(id) }\n        return r ?: throw NotFoundException("not found")\n    }\n}\n'''
   assert re.search(r"(?m)^\s*package\s+([\w.]+)", kt).group(1) == "com.example"
   assert re.search(r"\brun[Bb]locking\s*\{", kt) or re.search(r"\brunBlocking\s*\{", kt)
   print("Kotlin smoke OK")
   ```

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–end; also small additions to lines 613–636 and 720–732
(cross-domain, documented here for cohesion).

### Task B1 — `exclude_globs` in `__init__` and `_scan_files`

#### Step 1 — Add `exclude_globs` parameter to `__init__`

Find `def __init__(self, root_dir: str) -> None:` at line ~613. Change the signature and add
the attribute as the last line before the `go_root_module` discovery:

Old signature:
```python
    def __init__(self, root_dir: str) -> None:
```

New signature:
```python
    def __init__(self, root_dir: str, exclude_globs: Optional[List[str]] = None) -> None:
```

Add this line immediately before `self.go_root_module = ...` (the last two lines of `__init__`):

```python
        self.exclude_globs: List[str] = list(exclude_globs or [])
```

#### Step 2 — Check exclusions in `_scan_files`

Find `_scan_files` at line ~720. The current body is:

```python
    def _scan_files(self) -> None:
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if not should_ignore_dir(d)]
            for file_name in files:
                if file_name.endswith(".d.ts"):
                    continue
                suffix = Path(file_name).suffix.lower()
                full_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(full_path, self.root_dir)
                if suffix == ".py":
                    self._parse_file(rel_path)
                elif suffix in LANGUAGE_BY_SUFFIX:
                    self._parse_non_python_file(rel_path, LANGUAGE_BY_SUFFIX[suffix])
```

Replace it with:

```python
    def _scan_files(self) -> None:
        import fnmatch as _fnmatch
        norm_excludes = [p.rstrip("/\\") for p in self.exclude_globs]
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if not should_ignore_dir(d)]
            if norm_excludes:
                dirs[:] = [
                    d for d in dirs
                    if not any(_fnmatch.fnmatch(d, pat) for pat in norm_excludes)
                ]
            for file_name in files:
                if file_name.endswith(".d.ts"):
                    continue
                suffix = Path(file_name).suffix.lower()
                full_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(full_path, self.root_dir)
                if norm_excludes and any(
                    _fnmatch.fnmatch(rel_path.replace(os.sep, "/"), pat)
                    or _fnmatch.fnmatch(file_name, pat)
                    for pat in norm_excludes
                ):
                    continue
                if suffix == ".py":
                    self._parse_file(rel_path)
                elif suffix in LANGUAGE_BY_SUFFIX:
                    self._parse_non_python_file(rel_path, LANGUAGE_BY_SUFFIX[suffix])
```

---

### Task B2 — `--exclude` CLI argument

Find `main()` (line ~12248). Add this argument after the existing `--diff` block:

```python
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "Glob pattern to exclude files or directories (repeatable). "
            "Examples: --exclude 'vendor' --exclude '*.generated.kt' "
            "--exclude 'build'. Matched against directory names and "
            "relative file paths."
        ),
    )
```

Then find where the analyzer is constructed (line ~12369):

```python
    analyzer = StructuralIntegrityAnalyzerV3(args.root)
```

Change to:

```python
    analyzer = StructuralIntegrityAnalyzerV3(args.root, exclude_globs=args.exclude or [])
```

---

### Task B3 — Version bump + docs

1. Bump `"version"` at line ~673 from `"3.49"` to `"3.50"`.
2. Update `WORKER_GUIDE.md` lines ~193 and ~195 to `**3.50**` and `22 passes (Runs 1–3
   autonomous, Sprints 1–20)`. Also update the supported-languages line (~8) to add Kotlin.
3. Append to `CHANGES.md`:

```
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
```

---

### Verification (Worker B)

1. `python -m py_compile god_mode_v3.py` — must pass with no output.
2. `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only` — nodes=74,
   edges=58, cycles=0, parse_errors=0.
3. `python god_mode_v3.py .polyglot_graph_fixture --exclude '*.py' --out NUL --summary-only`
   — nodes should be **less than 74** (Python files excluded).
4. `rg -n '"version"' god_mode_v3.py` → `"3.50"` at ~line 673.
5. `rg -n 'exclude_globs\|--exclude\|norm_excludes' god_mode_v3.py` — confirm all three
   wiring points appear.
6. `rg -n 'Version: \*\*3\.50\*\*|22 passes|Sprint 20|Kotlin' WORKER_GUIDE.md CHANGES.md`
   — confirm docs updated.
