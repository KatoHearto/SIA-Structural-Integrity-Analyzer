# Sprint 22 Briefing

Read `WORKER_GUIDE.md` first. Worker A adds Ruby as the ninth supported language (full parser,
symbol extraction, semantic spans, import resolution). Worker B adds two quality-of-life
features: `.siaignore` file support (project-level exclusion list) and `--filter-language`
(restrict analysis to named languages), then bumps the version and updates docs. Worker B will
also make small additions to `__init__` and `_scan_files` (Worker A's nominal domain) to keep
the feature self-contained.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — Ruby language support

Ruby uses `end`-delimited blocks (not braces). Provide a `_ruby_find_end` helper for
approximate block matching, then build the parser chain on top of it.

---

#### Step 1 — Register `.rb` extension

Find `LANGUAGE_BY_SUFFIX` (line ~55). Add one entry immediately after `.php`:

```python
".rb": "Ruby",
```

---

#### Step 2 — Wire `_parse_non_python_file`

Find `_parse_non_python_file` (line ~972). Add a Ruby dispatch block immediately after the
PHP block:

```python
        if language == "Ruby":
            self._parse_ruby_file(rel_path, content, language)
            return
```

---

#### Step 3 — Implement `_parse_ruby_file`

Insert immediately after `_parse_php_file` (line ~1117, before `_parse_js_like_module`
at line ~1128):

```python
    def _parse_ruby_file(self, rel_path: str, content: str, language: str) -> None:
        module_payload = self._parse_ruby_module(rel_path, content, language)
        module_name = str(module_payload.get("module") or source_group(rel_path, language))
        package_name = str(module_payload.get("package_name", ""))
        file_imports_symbols = dict(module_payload.get("imports_symbols", {}))
        self._register_non_python_node(rel_path, content, language, module_payload)
        for symbol_payload in self._extract_ruby_symbol_payloads(
            rel_path, content, module_name, package_name, file_imports_symbols,
        ):
            self._register_non_python_node(rel_path, content, language, symbol_payload)
```

---

#### Step 4 — Implement `_parse_ruby_module`

Insert immediately after `_parse_php_module` ends (line ~1842, before
`_extract_java_symbol_payloads` at line ~1843):

```python
    def _parse_ruby_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        raw_imports: Set[str] = set()
        for m in re.findall(
            r"(?m)^\s*require(?:_relative)?\s+['\"]([^'\"]+)['\"]", content
        ):
            raw_imports.add(m.rsplit("/", 1)[-1].replace("-", "_"))

        declared_symbols = re.findall(
            r"(?m)^\s*(?:class|module)\s+([A-Z]\w*(?:::[A-Z]\w*)*)", content
        )[:20]

        raw_bases: Set[str] = set()
        for base in re.findall(r"\bclass\s+\w+\s*<\s*([A-Z]\w*(?:::[A-Z]\w*)*)", content):
            raw_bases.add(base.split("::")[-1])

        # Ruby has no package system; use the first module/class name as a grouping hint
        pkg_match = re.search(r"(?m)^\s*module\s+([A-Z]\w*(?:::[A-Z]\w*)*)", content)
        package_name = pkg_match.group(1).replace("::", ".") if pkg_match else ""

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

#### Step 5 — Implement `_ruby_find_end` helper and `_extract_ruby_symbol_payloads`

Insert immediately after `_extract_php_symbol_payloads` ends (line ~2298, before
`_extract_java_method_payloads` at line ~2299).

First the helper:

```python
    def _ruby_find_end(self, content: str, start_index: int) -> int:
        """Return the character index just after the 'end' that closes the Ruby block
        whose opening keyword appears at start_index. depth starts at 1.
        Uses word-boundary regex; approximate (does not skip string literals)."""
        _OPEN = re.compile(
            r"\b(?:class|module|def|do|begin|if|unless|case|while|until|for)\b"
        )
        _CLOSE = re.compile(r"\bend\b")
        depth = 1
        pos = start_index + 1
        while pos < len(content):
            om = _OPEN.search(content, pos)
            em = _CLOSE.search(content, pos)
            if om is None and em is None:
                break
            if em is None or (om is not None and om.start() < em.start()):
                depth += 1
                pos = om.end()
            else:
                depth -= 1
                if depth == 0:
                    return em.end()
                pos = em.end()
        return len(content)
```

Then the symbol extractor:

```python
    def _extract_ruby_symbol_payloads(
        self,
        rel_path: str,
        content: str,
        module_name: str,
        package_name: str,
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        payloads: List[Dict[str, object]] = []

        type_pattern = re.compile(
            r"(?m)^(\s*)(?:class|module)\s+([A-Z]\w*(?:::[A-Z]\w*)*)\b([^\n]*)"
        )
        method_pattern = re.compile(
            r"(?m)^(\s*)def\s+(self\.)?([a-z_]\w*[?!]?)\s*(?:\([^)]*\))?"
        )

        for type_match in type_pattern.finditer(content):
            indent = len(type_match.group(1))
            if indent > 0:
                continue  # only top-level classes/modules
            type_name = type_match.group(2).split("::")[-1]
            tail = type_match.group(3) or ""
            raw_bases: Set[str] = set()
            base_m = re.search(r"<\s*([A-Z]\w*(?:::[A-Z]\w*)*)", tail)
            if base_m:
                raw_bases.add(base_m.group(1).split("::")[-1])

            block_end = self._ruby_find_end(content, type_match.start())
            body = content[type_match.end():block_end]

            payloads.append({
                "module": module_name,
                "qualname": type_name,
                "kind": "class",
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
                "raw_bases": raw_bases,
                "lines": self._span_to_lines(content, type_match.start(), block_end),
            })

            for method_match in method_pattern.finditer(body):
                method_indent = len(method_match.group(1))
                if method_indent > 4:
                    continue  # skip deeply nested defs
                is_class_method = bool(method_match.group(2))
                method_name = method_match.group(3)
                if method_name in {"initialize"}:
                    qualname = f"{type_name}.initialize"
                elif is_class_method:
                    qualname = f"{type_name}.{method_name}"
                else:
                    qualname = f"{type_name}#{method_name}"
                abs_start = type_match.end() + method_match.start()
                mend = self._ruby_find_end(body, method_match.start())
                abs_end = type_match.end() + mend
                payloads.append({
                    "module": module_name,
                    "qualname": qualname,
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

        # Top-level def (not inside any class/module)
        for method_match in method_pattern.finditer(content):
            if len(method_match.group(1)) > 0:
                continue  # not top-level
            method_name = method_match.group(3)
            mend = self._ruby_find_end(content, method_match.start())
            payloads.append({
                "module": module_name,
                "qualname": method_name,
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
                "lines": self._span_to_lines(content, method_match.start(), mend),
            })

        return payloads
```

---

#### Step 6 — Wire semantic spans dispatch

Find the semantic spans dispatch block (line ~4302) where PHP was added in Sprint 21:

```python
            elif node.language == "PHP":
                refs = self._extract_php_semantic_spans(node, source_lines)
```

Add immediately after:

```python
            elif node.language == "Ruby":
                refs = self._extract_ruby_semantic_spans(node, source_lines)
```

---

#### Step 7 — Implement `_extract_ruby_semantic_spans`

Insert immediately after `_extract_php_semantic_spans` ends (before `_semantic_summary_for_node`
at line ~5056):

```python
    def _extract_ruby_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            # input_boundary — Rails/Sinatra routing
            if (
                re.search(r"\b(?:get|post|put|delete|patch|resources?|namespace)\s+['\"/]", text)
                or re.search(r"\bRoutes\.draw\b", text)
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno,
                                          "Rails/Sinatra route definition marks an input boundary.")
            # auth_guard — Devise, CanCanCan, before_action auth
            if (
                re.search(r"\bbefore_action\s+:authenticate_user[!?]?", text)
                or re.search(r"\bauthenticate_user[!?]\s*\(", text)
                or re.search(r"\bauthorize[!?]?\s*\(", text)
                or re.search(r"\bcurrent_user\b", text)
                or re.search(r"\buser_signed_in\?\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno,
                                          "Devise/CanCanCan authentication or authorization check.")
            # validation_guard — ActiveRecord validations
            if (
                re.search(r"\bvalidates\s+:", text)
                or re.search(r"\bvalidate\s+:", text)
                or re.search(r"\bvalid\?\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno,
                                          "ActiveRecord validation enforces data constraints.")
            # database_io — ActiveRecord, sequel
            if (
                re.search(r"\b(?:ActiveRecord::Base|ApplicationRecord)\b", text)
                or re.search(r"\.(?:where|find|find_by|create|save[!?]?|update[!?]?|destroy[!?]?|first|last|all|count|exists\?)\s*[(\{]", text)
                or re.search(r"\bconnection\.execute\s*\(", text)
                or re.search(r"\bDB\[|Sequel\.connect\b", text)
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno,
                                          "ActiveRecord or Sequel database access.")
            # network_io — Net::HTTP, Faraday, HTTParty, open-uri
            if (
                re.search(r"\bNet::HTTP\b", text)
                or re.search(r"\bFaraday\.new\b|\bfaraday\b", text)
                or re.search(r"\bHTTParty\.(?:get|post|put|delete)\b", text)
                or re.search(r"\bRestClient\.(?:get|post|put|delete)\b", text)
                or re.search(r"\bopen\s*\(\s*['\"]https?://", text)
                or re.search(r"\bURI\.open\b|\bURI\.parse\b", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno,
                                          "HTTP client or remote URI access.")
            # filesystem_io — File, Dir, FileUtils, IO
            if (
                re.search(r"\bFile\.(?:read|write|open|exist[s]?|delete|rename|expand_path|join)\s*\(", text)
                or re.search(r"\bDir\.(?:glob|mkdir|entries|foreach)\s*\(", text)
                or re.search(r"\bFileUtils\.\w+\s*\(", text)
                or re.search(r"\bIO\.(?:read|write|popen)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno,
                                          "File system access in Ruby code.")
            # process_io — backtick, system, exec, spawn, Open3
            if (
                re.search(r"`[^`]+`", text)
                or re.search(r"\b(?:system|exec|spawn)\s*\(", text)
                or re.search(r"\bOpen3\.(?:popen\d?|capture\d|pipeline)\b", text)
                or re.search(r"\bProcess\.spawn\b", text)
            ):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno,
                                          "Shell command execution in Ruby.")
            # config_access — ENV, Rails.application.config, Figaro
            if (
                re.search(r"\bENV\s*\[", text)
                or re.search(r"\bRails\.application\.config\b", text)
                or re.search(r"\bRails\.env\b", text)
                or re.search(r"\bRails\.configuration\b", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno,
                                          "Reads configuration or environment variable.")
            # serialization — to_json, JSON.generate, Marshal.dump
            if (
                re.search(r"\.to_json\b", text)
                or re.search(r"\bJSON\.(?:generate|dump)\s*\(", text)
                or re.search(r"\bMarshal\.dump\s*\(", text)
                or re.search(r"\.to_xml\b|\bActiveSupport::JSON\.encode\b", text)
            ):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno,
                                          "Serializes data to JSON/XML.")
            # deserialization — JSON.parse, Marshal.load
            if (
                re.search(r"\bJSON\.parse\s*\(", text)
                or re.search(r"\bMarshal\.load\s*\(", text)
                or re.search(r"\bActiveSupport::JSON\.decode\b", text)
            ):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno,
                                          "Deserializes data from JSON.")
            # time_or_randomness — Time, Date, SecureRandom, rand
            if (
                re.search(r"\bTime\.(?:now|current|zone\.now)\b", text)
                or re.search(r"\bDateTime\.(?:now|current)\b", text)
                or re.search(r"\bDate\.today\b", text)
                or re.search(r"\bSecureRandom\.(?:uuid|hex|random_bytes)\s*\(", text)
                or re.search(r"\brand\s*\(|\bRandom\.rand\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno,
                                          "Uses time or randomness sources.")
            # state_mutation — Rails.cache, session
            if (
                re.search(r"\bRails\.cache\.(?:write|fetch|delete)\s*\(", text)
                or re.search(r"\bsession\s*\[", text)
            ):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno,
                                          "Mutates Rails cache or session state.")
            # error_handling — rescue, raise
            if re.search(r"\brescue\b|\braise\b", text):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno,
                                          "Contains explicit Ruby error handling.")
            # output_boundary — render, redirect_to, puts, p, logger
            if (
                re.search(r"\brender\s+(?:json:|template:|partial:|html:|nothing:)", text)
                or re.search(r"\bredirect_to\s*\(", text)
                or re.search(r"\bputs\s*\(|\bp\s+\w", text)
                or re.search(r"\bRails\.logger\.\w+\s*\(|\blogger\.\w+\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno,
                                          "Produces observable output (render, log, puts).")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs
```

---

#### Step 8 — Wire import resolution

Find `_resolve_import_outcome` and the PHP branch (line ~3117). Add a Ruby branch
immediately after the PHP `return ResolutionOutcome(target=None)` line:

```python
        if caller.language == "Ruby":
            # Match by last path component of the require string
            candidates = [
                nid for nid, nd in self.nodes.items()
                if nd.language == "Ruby"
                and nd.kind != "module"
                and (nd.package_name == raw or nd.package_name.endswith("." + raw))
            ]
            if len(candidates) == 1:
                return self._resolution(
                    target=candidates[0],
                    kind="import_exact",
                    reason=f"Resolved Ruby require `{raw}` exactly.",
                )
            return ResolutionOutcome(target=None)
```

---

#### Verification (Worker A)

1. `python -m py_compile god_mode_v3.py` — must pass with no output.
2. `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only` — nodes=74,
   edges=58, cycles=0, parse_errors=0.
3. `rg -n '"Ruby"|_parse_ruby|_extract_ruby|_ruby_find_end' god_mode_v3.py` — confirm all
   integration points.
4. Inline smoke-test (run once, do not leave in file):
   ```python
   import re
   rb = "module Blog\nclass Post < ApplicationRecord\n  validates :title, presence: true\n  def publish!\n    update!(published_at: Time.current)\n  rescue ActiveRecord::RecordInvalid => e\n    Rails.logger.error e.message\n  end\nend\nend\n"
   assert re.search(r"(?m)^\s*module\s+([A-Z]\w*)", rb).group(1) == "Blog"
   assert re.search(r"\bupdate[!?]?\s*\(", rb)
   assert re.search(r"\brescue\b", rb)
   print("Ruby smoke OK")
   ```

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–end; also small modifications to `__init__` (line ~615)
and `_scan_files` (line ~723) — cross-domain, documented here for cohesion.

### Task B1 — `.siaignore` file support

Modify `_scan_files` (line ~723) to load patterns from `.siaignore` if it exists in the
project root, merging them with `self.exclude_globs` before scanning. No change to `__init__`
is needed.

Find the start of `_scan_files`:

```python
    def _scan_files(self) -> None:
        import fnmatch as _fnmatch
        norm_excludes = [p.rstrip("/\\") for p in self.exclude_globs]
        for root, dirs, files in os.walk(self.root_dir):
```

Replace the first three lines of the method body with:

```python
    def _scan_files(self) -> None:
        import fnmatch as _fnmatch
        norm_excludes = [p.rstrip("/\\") for p in self.exclude_globs]
        _siaignore = os.path.join(self.root_dir, ".siaignore")
        if os.path.isfile(_siaignore):
            try:
                with open(_siaignore, encoding="utf-8") as _fh:
                    for _raw in _fh:
                        _pat = _raw.strip()
                        if _pat and not _pat.startswith("#"):
                            norm_excludes.append(_pat.rstrip("/\\"))
            except OSError:
                pass
        for root, dirs, files in os.walk(self.root_dir):
```

---

### Task B2 — `filter_languages` in `__init__` and `_scan_files`

#### Step 1 — Add `filter_languages` parameter to `__init__`

Find `def __init__(self, root_dir: str, exclude_globs: Optional[List[str]] = None)` at
line ~615. Change the signature to:

```python
    def __init__(
        self,
        root_dir: str,
        exclude_globs: Optional[List[str]] = None,
        filter_languages: Optional[List[str]] = None,
    ) -> None:
```

Add this line immediately after the `self.exclude_globs` line:

```python
        self.filter_languages: Optional[Set[str]] = set(filter_languages) if filter_languages else None
```

#### Step 2 — Apply filter in `_scan_files`

In `_scan_files`, find the file-dispatch block at the end of the loop:

```python
                if suffix == ".py":
                    self._parse_file(rel_path)
                elif suffix in LANGUAGE_BY_SUFFIX:
                    self._parse_non_python_file(rel_path, LANGUAGE_BY_SUFFIX[suffix])
```

Replace with:

```python
                if suffix == ".py":
                    if self.filter_languages is None or "Python" in self.filter_languages:
                        self._parse_file(rel_path)
                elif suffix in LANGUAGE_BY_SUFFIX:
                    _lang = LANGUAGE_BY_SUFFIX[suffix]
                    if self.filter_languages is None or _lang in self.filter_languages:
                        self._parse_non_python_file(rel_path, _lang)
```

---

### Task B3 — `--filter-language` CLI argument

Find `main()` (line ~12966). Add this argument after `--exclude`:

```python
    parser.add_argument(
        "--filter-language",
        default="",
        metavar="LANGS",
        help=(
            "Comma-separated list of languages to analyze (e.g. 'Python,Java'). "
            "All other languages are skipped. Case-sensitive."
        ),
    )
```

Then find where the analyzer is constructed:

```python
    analyzer = StructuralIntegrityAnalyzerV3(args.root, exclude_globs=args.exclude or [])
```

Change to:

```python
    _filter_langs = [l.strip() for l in args.filter_language.split(",") if l.strip()] if args.filter_language else None
    analyzer = StructuralIntegrityAnalyzerV3(
        args.root,
        exclude_globs=args.exclude or [],
        filter_languages=_filter_langs,
    )
```

---

### Task B4 — Version bump + docs

1. Bump `"version"` at line ~676 from `"3.51"` to `"3.52"`.
2. Update `WORKER_GUIDE.md` lines ~193 and ~195 to `**3.52**` and
   `24 passes (Runs 1–3 autonomous, Sprints 1–22)`. Add Ruby to supported-languages line.
3. Append to `CHANGES.md`:

```
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

Worker B: `.siaignore` file — if present in the project root, patterns (one per line, #
comments ignored) are merged with `--exclude` patterns before scanning. `--filter-language
LANGS` (comma-separated) restricts analysis to named languages only; wires into
`StructuralIntegrityAnalyzerV3.__init__` via new `filter_languages` parameter. Version 3.52,
24 passes.
```

---

### Verification (Worker B)

1. `python -m py_compile god_mode_v3.py` — must pass with no output.
2. `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only` — nodes=74,
   edges=58, cycles=0, parse_errors=0.
3. `python god_mode_v3.py .polyglot_graph_fixture --filter-language TypeScript --out NUL --summary-only`
   — nodes should be **less than 74** (only TypeScript files parsed).
4. Create a temporary `.siaignore` in `.polyglot_graph_fixture` containing `*.ts` on one line,
   run `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only`, confirm node
   count drops, then remove the `.siaignore` file.
5. `rg -n '"version"|filter_languages|_siaignore|--filter-language' god_mode_v3.py` — confirm
   all wiring points appear.
6. `rg -n 'Version: \*\*3\.52\*\*|24 passes|Sprint 22|Ruby' WORKER_GUIDE.md CHANGES.md`
   — confirm docs updated.
