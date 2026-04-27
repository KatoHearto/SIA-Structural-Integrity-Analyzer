# Sprint 19 Briefing

Read `WORKER_GUIDE.md` first. Worker A adds C# as the sixth supported language (full parser,
symbol extraction, semantic spans, import resolution). Worker B adds a `--diff` CLI mode that
compares two SIA report JSON files and prints what changed, then bumps the version and updates
docs.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — C# language support

Add C# end-to-end: file detection, module + symbol parsing, semantic signal extraction, and
import outcome resolution. Follow the Java pattern throughout — C# has the same brace-delimited
structure and can reuse `_compute_js_like_brace_depths` and `_find_matching_brace`.

---

#### Step 1 — Register `.cs` extension

Find `LANGUAGE_BY_SUFFIX` (line ~55). Add one entry:

```python
".cs": "CSharp",
```

---

#### Step 2 — Wire `_parse_non_python_file`

Find `_parse_non_python_file` (line ~971). Add CSharp to the parser dict alongside Go and Rust:

```python
parser = {
    "Go": self._parse_go_module,
    "Rust": self._parse_rust_module,
    "CSharp": self._parse_csharp_module,
}.get(language)
```

Then add the file-level registration call (identical to the Go/Rust path) — it already exists:
`payload = parser(...)` and `self._register_non_python_node(...)` handle it.

Also add a `_parse_csharp_file` dispatch so multi-class files work.  The existing Go/Rust path
only registers one node per file. C# files usually contain multiple classes (like Java), so add:

```python
if language == "CSharp":
    self._parse_csharp_file(rel_path, content, language)
    return
```

**before** the `parser = {...}` dict (i.e. between the Java `if` and the dict).

---

#### Step 3 — Implement `_parse_csharp_file`

Insert directly after `_parse_java_file` (line ~1065):

```python
def _parse_csharp_file(self, rel_path: str, content: str, language: str) -> None:
    module_payload = self._parse_csharp_module(rel_path, content, language)
    module_name = str(module_payload.get("module") or source_group(rel_path, language))
    namespace = str(module_payload.get("package_name", ""))
    file_imports_symbols = dict(module_payload.get("imports_symbols", {}))
    self._register_non_python_node(rel_path, content, language, module_payload)
    for symbol_payload in self._extract_csharp_symbol_payloads(
        rel_path, content, module_name, namespace, file_imports_symbols,
    ):
        self._register_non_python_node(rel_path, content, language, symbol_payload)
```

---

#### Step 4 — Implement `_parse_csharp_module`

Insert after `_parse_java_module` (line ~1650ish). Returns the file-level module node payload.

```python
def _parse_csharp_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
    # Namespace: file-scoped (C# 10+) or block-scoped
    ns_match = re.search(r"(?m)^namespace\s+([\w.]+)\s*;", content)
    if not ns_match:
        ns_match = re.search(r"(?m)^namespace\s+([\w.]+)\s*\{", content)
    namespace = ns_match.group(1) if ns_match else ""

    # using directives → raw_imports
    raw_imports: Set[str] = set(
        re.findall(r"(?m)^\s*using\s+(?:static\s+)?(?:\w+\s*=\s*)?([\w.]+)\s*;", content)
    )

    # Top-level declared symbols (type names only)
    declared_symbols = re.findall(
        r"(?m)^\s*(?:(?:public|internal|private|protected|static|abstract|sealed|partial)\s+)*"
        r"(?:class|interface|enum|struct|record)\s+([A-Za-z_]\w*)\b",
        content,
    )[:20]

    raw_bases: Set[str] = set()
    for tail in re.findall(r"(?:class|struct)\s+\w+\s*:\s*([A-Za-z_][\w,\s<>?]*?)\s*(?:\{|where)", content):
        for part in re.split(r",\s*", tail):
            part = re.sub(r"<.*?>", "", part).strip()
            if part and re.match(r"[A-Za-z_]\w*", part):
                raw_bases.add(part)

    return {
        "module": source_group(rel_path, language, namespace),
        "qualname": source_qualname(rel_path),
        "kind": "module",
        "package_name": namespace,
        "imports_modules": {},
        "imports_symbols": {},
        "declared_symbols": declared_symbols,
        "raw_imports": raw_imports,
        "raw_bases": raw_bases,
    }
```

---

#### Step 5 — Implement `_extract_csharp_symbol_payloads`

Insert after `_extract_java_symbol_payloads` (line ~1752). Returns one payload per type and
per method inside each type. Use `_compute_js_like_brace_depths` and `_find_matching_brace`
(already available) for brace matching — same technique as Java.

```python
def _extract_csharp_symbol_payloads(
    self,
    rel_path: str,
    content: str,
    module_name: str,
    namespace: str,
    imports_symbols: Dict[str, str],
) -> List[Dict[str, object]]:
    payloads: List[Dict[str, object]] = []
    depth_map = self._compute_js_like_brace_depths(content)
    type_pattern = re.compile(
        r"(?m)^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|readonly)\s+)*"
        r"(class|interface|enum|struct|record)\s+([A-Za-z_]\w*)\b([^{]*)\{"
    )
    method_pattern = re.compile(
        r"(?m)^\s*(?:(?:public|private|protected|internal|static|abstract|virtual|override|"
        r"async|sealed|new|extern|partial)\s+)*"
        r"(?:[\w<>\[\]?,.\s]+?)\s+([A-Za-z_]\w*)\s*(?:<[^>]*>)?\s*\([^)]*\)\s*"
        r"(?:where\s+[\w\s:,<>]+?)?\s*\{"
    )

    for type_match in type_pattern.finditer(content):
        if depth_map[type_match.start()] != 0:
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
        colon_match = re.search(r":\s*([\w,\s<>?]+?)(?:\{|where\b)", tail + " {")
        if colon_match:
            for part in re.split(r",\s*", colon_match.group(1)):
                part = re.sub(r"<.*?>", "", part).strip()
                if part and re.match(r"[A-Za-z_]\w*", part):
                    raw_bases.add(part)

        # Member field types
        body = content[open_brace + 1:close_brace]
        field_types: Dict[str, str] = {}
        for fm in re.finditer(
            r"(?m)^\s*(?:(?:private|public|protected|internal|static|readonly)\s+)+"
            r"([\w<>?,.\s]+?)\s+([A-Za-z_]\w*)\s*[;={]",
            body,
        ):
            ftype = re.sub(r"\s+", " ", fm.group(1)).strip()
            fname = fm.group(2).strip()
            if fname and ftype and ftype not in {"return", "var", "new"}:
                field_types[fname] = ftype

        annotation_block = self._extract_java_leading_annotation_block(content, type_match.start())
        annotations = [
            m.strip()
            for m in re.findall(r"\[([A-Za-z_]\w*(?:\([^)]*\))?)\]", annotation_block)
        ]

        payloads.append({
            "module": module_name,
            "qualname": type_name,
            "kind": "class" if type_kind in {"class", "struct", "record"} else type_kind,
            "class_context": type_name,
            "package_name": namespace,
            "imports_symbols": dict(imports_symbols),
            "member_types": field_types,
            "member_qualifiers": {},
            "declared_symbols": [],
            "annotations": annotations,
            "bean_name": "",
            "is_abstract": bool(re.search(r"\babstract\b", type_match.group(0))),
            "di_primary": False,
            "raw_calls": set(),
            "raw_bases": raw_bases,
            "lines": self._span_to_lines(content, type_match.start(), close_brace),
        })

        # Methods inside the type
        body_depth_map = self._compute_js_like_brace_depths(body)
        for method_match in method_pattern.finditer(body):
            method_name = method_match.group(1)
            if method_name in {"if", "for", "while", "foreach", "switch", "catch", "using", "lock",
                                "return", "await", "new", "throw", "var", "get", "set"}:
                continue
            if body_depth_map[method_match.start()] != 0:
                continue
            m_open = body.find("{", method_match.end() - 1)
            if m_open < 0:
                continue
            m_close = self._find_matching_brace(body, m_open)
            if m_close < 0:
                continue
            method_body = body[m_open + 1:m_close]
            raw_calls: Set[str] = set()
            for cm in re.finditer(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\(", method_body):
                name = cm.group(1)
                if not re.match(r"^(?:if|for|while|foreach|switch|catch|using|lock|return|await|new|throw|var|get|set)$", name):
                    raw_calls.add(name)
            m_annotation_block = self._extract_java_leading_annotation_block(body, method_match.start())
            m_annotations = [
                m.strip()
                for m in re.findall(r"\[([A-Za-z_]\w*(?:\([^)]*\))?)\]", m_annotation_block)
            ]
            abs_start = open_brace + 1 + method_match.start()
            abs_end = open_brace + 1 + m_close
            payloads.append({
                "module": module_name,
                "qualname": f"{type_name}.{method_name}",
                "kind": "function",
                "class_context": type_name,
                "package_name": namespace,
                "imports_symbols": dict(imports_symbols),
                "member_types": dict(field_types),
                "member_qualifiers": {},
                "declared_symbols": [],
                "annotations": m_annotations,
                "bean_name": "",
                "is_abstract": False,
                "di_primary": False,
                "raw_calls": raw_calls,
                "raw_bases": set(),
                "lines": self._span_to_lines(content, abs_start, abs_end),
            })

    return payloads
```

---

#### Step 6 — Implement `_extract_csharp_semantic_spans`

Insert after `_extract_rust_semantic_spans` (line ~4120):

```python
def _extract_csharp_semantic_spans(
    self,
    node: SymbolNode,
    source_lines: List[Tuple[int, str]],
) -> List[Dict[str, object]]:
    refs: List[Dict[str, object]] = []
    for index, (lineno, text) in enumerate(source_lines):
        lower = text.lower()
        if re.search(r"\[(?:HttpGet|HttpPost|HttpPut|HttpDelete|HttpPatch|Route|ApiController|FromBody|FromRoute|FromQuery|FromForm|FromHeader)\b", text):
            self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "ASP.NET Core route or parameter attribute marks an input boundary.")
        if (
            re.search(r"\[(?:Authorize|RequireAuthorization)\b", text)
            or re.search(r"\bjwtHandler\.ValidateToken\s*\(", text)
            or re.search(r"\bTokenValidationParameters\b", text)
            or re.search(r"\bClaimsPrincipal\b", text)
        ):
            self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "ASP.NET Core authorization attribute or JWT validation.")
        if (
            re.search(r"\[(?:Required|StringLength|Range|RegularExpression|EmailAddress|MinLength|MaxLength|Phone|Url|Compare)\b", text)
            or re.search(r"\bModelState\.IsValid\b", text)
            or re.search(r"\bValidationContext\b", text)
        ):
            self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Data-annotation attribute or ModelState validation.")
        if (
            re.search(r"\b_?[Cc]ontext\.[A-Za-z_]\w*\.(?:Add|Remove|Update|Find|FindAsync|FirstOrDefault|FirstOrDefaultAsync|ToList|ToListAsync|Where|Any|Count|Single|SingleOrDefault|SaveChanges|SaveChangesAsync)\s*\(", text)
            or re.search(r"\bDbContext\b", text)
            or re.search(r"\bIDbConnection\b", text)
            or re.search(r"\b\.ExecuteNonQuery\s*\(|\b\.ExecuteScalar\s*\(|\b\.ExecuteReader\s*\(", text)
        ):
            self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Entity Framework or ADO.NET database access.")
        if (
            re.search(r"\b_?[Hh]ttp[Cc]lient\.(?:GetAsync|PostAsync|SendAsync|PutAsync|DeleteAsync|PatchAsync)\s*\(", text)
            or re.search(r"\bnew HttpClient\s*\(", text)
        ):
            self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "HttpClient network call.")
        if (
            re.search(r"\bFile\.(?:ReadAllText|WriteAllText|ReadAllLines|WriteAllLines|ReadAllBytes|WriteAllBytes|AppendAllText|Open|Create|Delete|Exists|Copy|Move)\s*\(", text)
            or re.search(r"\bDirectory\.[A-Za-z_]\w*\s*\(", text)
            or re.search(r"\bnew (?:FileStream|StreamReader|StreamWriter|BinaryReader|BinaryWriter)\s*\(", text)
            or re.search(r"\bPath\.(?:Combine|GetFullPath|GetFileName|GetDirectoryName)\s*\(", text)
        ):
            self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno, "File system access in C# code.")
        if re.search(r"\bProcess\.Start\s*\(", text):
            self._record_semantic_ref(refs, node, "process_io", lineno, lineno, "Process.Start spawns an OS process.")
        if (
            re.search(r"\bEnvironment\.GetEnvironmentVariable\s*\(", text)
            or re.search(r"\bIConfiguration\b", text)
            or re.search(r"\bconfiguration\[", lower)
            or re.search(r"\.GetSection\s*\(|\.GetValue\s*\(", text)
        ):
            self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads configuration or environment state.")
        if re.search(r"\bJsonSerializer\.(?:Serialize|SerializeAsync)\s*\(|\bJsonConvert\.SerializeObject\s*\(", text):
            self._record_semantic_ref(refs, node, "serialization", lineno, lineno, "Serializes data to JSON.")
        if re.search(r"\bJsonSerializer\.(?:Deserialize|DeserializeAsync)\s*\(|\bJsonConvert\.DeserializeObject\s*\(", text):
            self._record_semantic_ref(refs, node, "deserialization", lineno, lineno, "Deserializes data from JSON.")
        if (
            re.search(r"\bDateTime\.(?:Now|UtcNow)\b", text)
            or re.search(r"\bGuid\.NewGuid\s*\(", text)
            or re.search(r"\bnew Random\s*\(|\bRandomNumberGenerator\b", text)
            or re.search(r"\bDateTimeOffset\.(?:Now|UtcNow)\b", text)
        ):
            self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno, "Uses time or randomness sources.")
        if (
            re.search(r"\bthis\.[A-Za-z_]\w*\s*=(?!=)", text)
            or re.search(r"\b_[A-Za-z_]\w*\s*=(?!=)", text)
        ):
            self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates instance state in C#.")
        if re.search(r"\b(?:try|catch|throw)\b", text):
            self._record_semantic_ref(refs, node, "error_handling", lineno, lineno, "Contains explicit C# error handling.")
        if (
            re.search(r"\breturn\s+(?:Ok|Created|BadRequest|NotFound|Unauthorized|Forbidden|NoContent|Conflict|StatusCode)\s*\(", text)
            or re.search(r"\bIActionResult\b|\bActionResult\b", text)
            or re.search(r"\bContentResult\b|\bJsonResult\b|\bObjectResult\b", text)
        ):
            self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "ASP.NET Core action returns a boundary-facing response.")
        guard = self._guard_signal_for_window(source_lines, index)
        if guard is not None:
            signal, end_line, reason = guard
            self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
    return refs
```

---

#### Step 7 — Wire semantic spans dispatch

Find the `elif node.language == "Rust":` line in the semantic spans loop (line ~3697).
Add immediately after it:

```python
elif node.language == "CSharp":
    refs = self._extract_csharp_semantic_spans(node, source_lines)
```

---

#### Step 8 — Wire import resolution

Find `_resolve_import_outcome` (line ~2527). Add a CSharp branch **before** the final
`return ResolutionOutcome(target=None)`:

```python
if caller.language == "CSharp":
    # Match using directive to any C# node whose namespace equals the raw import
    candidates = [
        nid for nid, nd in self.nodes.items()
        if nd.language == "CSharp" and nd.package_name == raw and nd.kind != "module"
    ]
    if len(candidates) == 1:
        return self._resolution(
            target=candidates[0],
            kind="import_exact",
            reason=f"Resolved C# using `{raw}` exactly.",
        )
    return ResolutionOutcome(target=None)
```

---

### Verification for Worker A

```bash
python -m py_compile god_mode_v3.py
python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only
rg -n "CSharp\|_parse_csharp\|_extract_csharp" god_mode_v3.py | head -20
```

Expected: `parse_errors=0`, `nodes=74, edges=58` (fixture has no `.cs` files, counts unchanged).
The `rg` output must show all new C# methods and the `LANGUAGE_BY_SUFFIX` entry.

**Do not bump the version** — Worker B handles that.

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–end, plus docs.

### Task B1 — Add `--diff` CLI mode

Add a new CLI mode that compares two SIA report JSON files and prints what changed.
When `--diff` is passed the tool does **no** analysis — it exits after printing the diff.

---

#### B1a — Add module-level function `_run_sia_diff`

Insert near the bottom of the file, just before `def main()` (line ~11902):

```python
def _run_sia_diff(old_path: str, new_path: str) -> None:
    import sys as _sys

    def _load(path: str) -> Dict[str, object]:
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:
            print(f"Error loading {path}: {exc}", file=_sys.stderr)
            raise SystemExit(1)

    old_data = _load(old_path)
    new_data = _load(new_path)

    old_risks = {str(r["symbol"]): float(r["risk_score"]) for r in old_data.get("top_risks", [])}
    new_risks = {str(r["symbol"]): float(r["risk_score"]) for r in new_data.get("top_risks", [])}

    appeared = sorted((s, sc) for s, sc in new_risks.items() if s not in old_risks)
    resolved = sorted((s, sc) for s, sc in old_risks.items() if s not in new_risks)
    improved = sorted(
        (s, old_risks[s], new_risks[s])
        for s in old_risks if s in new_risks and old_risks[s] - new_risks[s] >= 1.0
    )
    degraded = sorted(
        (s, old_risks[s], new_risks[s])
        for s in old_risks if s in new_risks and new_risks[s] - old_risks[s] >= 1.0
    )
    unchanged_count = sum(
        1 for s in old_risks if s in new_risks and abs(new_risks[s] - old_risks[s]) < 1.0
    )

    old_ver = old_data.get("meta", {}).get("version", "?")
    new_ver = new_data.get("meta", {}).get("version", "?")
    old_nodes = old_data.get("meta", {}).get("node_count", "?")
    new_nodes = new_data.get("meta", {}).get("node_count", "?")

    sep = "=" * 56
    print(f"\nSIA Diff  {old_path}  →  {new_path}")
    print(sep)
    print(f"Version : {old_ver} → {new_ver}")
    if old_nodes != "?" and new_nodes != "?":
        delta_n = int(new_nodes) - int(old_nodes)
        print(f"Nodes   : {old_nodes} → {new_nodes}  ({'+' if delta_n >= 0 else ''}{delta_n})")
    print()

    if appeared:
        print(f"NEW RISKS ({len(appeared)} appeared):")
        for sym, sc in appeared:
            print(f"  +  {sym:<60}  score={sc}")
        print()
    if resolved:
        print(f"RESOLVED ({len(resolved)} no longer in top risks):")
        for sym, sc in resolved:
            print(f"  -  {sym:<60}  score={sc}")
        print()
    if improved:
        print(f"IMPROVED (score ↓≥1.0):")
        for sym, old_sc, new_sc in improved:
            print(f"  ~  {sym:<60}  {old_sc} → {new_sc}  ({new_sc - old_sc:+.1f})")
        print()
    if degraded:
        print(f"DEGRADED (score ↑≥1.0):")
        for sym, old_sc, new_sc in degraded:
            print(f"  !  {sym:<60}  {old_sc} → {new_sc}  ({new_sc - old_sc:+.1f})")
        print()
    print(f"UNCHANGED: {unchanged_count} risks within ±1.0")
    print(sep)
```

---

#### B1b — Wire `--diff` into `main()`

Find `def main()` (line ~11902). Add the argument **before** `args = parser.parse_args()`:

```python
parser.add_argument(
    "--diff",
    nargs=2,
    metavar=("OLD", "NEW"),
    default=None,
    help="Compare two SIA report JSON files and print the diff. No analysis is run.",
)
```

After `args = parser.parse_args()` add an early-exit block **before** any existing
`if args.validate_worker_result:` check:

```python
if args.diff:
    _run_sia_diff(args.diff[0], args.diff[1])
    return
```

---

### Task B2 — Version bump and docs

**Version:** Bump `god_mode_v3.py` line 672 from `"3.48"` to `"3.49"`.

**CHANGES.md:** Append:

```markdown
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
(score dropped ≥1.0), degraded (score rose ≥1.0), unchanged count. No analysis is run.
Useful for validating sprint results and tracking risk evolution over time.
```

**WORKER_GUIDE.md:** Update Current state:
- Version: `**3.49**`
- Sprint history: `21 passes (Runs 1–3 autonomous, Sprints 1–19)`
- Add C# to the supported languages list in the "What this project is" section.

---

### Verification for Worker B

```bash
python -m py_compile god_mode_v3.py
python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only
python god_mode_v3.py --diff sia_self_v347.json sia_self_v348.json
rg -n '"version"' god_mode_v3.py
rg -n "_run_sia_diff\|--diff" god_mode_v3.py
```

The `--diff` command must print a readable diff without crashing.
Expected: `parse_errors=0`, `nodes=74, edges=58`.

---

## Handoff

- Worker A → `worker_output_a.md`
- Worker B → `worker_output_b.md`
