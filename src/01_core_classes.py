# ── SIA src/01_core_classes.py ── (god_mode_v3.py lines 402–691) ─────────────

@dataclass
class SymbolNode:
    node_id: str
    module: str
    qualname: str
    kind: str
    file: str
    lines: List[int]
    class_context: Optional[str]
    imports_modules: Dict[str, str]
    imports_symbols: Dict[str, str]
    member_types: Dict[str, str] = field(default_factory=dict)
    member_qualifiers: Dict[str, str] = field(default_factory=dict)
    language: str = "Python"
    package_name: str = ""
    declared_symbols: List[str] = field(default_factory=list)
    annotations: List[str] = field(default_factory=list)
    bean_name: str = ""
    is_abstract: bool = False
    di_primary: bool = False
    raw_imports: Set[str] = field(default_factory=set)
    resolved_imports: Set[str] = field(default_factory=set)
    external_imports: Set[str] = field(default_factory=set)
    unresolved_imports: Set[str] = field(default_factory=set)
    raw_calls: Set[str] = field(default_factory=set)
    raw_bases: Set[str] = field(default_factory=set)
    resolved_calls: Set[str] = field(default_factory=set)
    resolved_bases: Set[str] = field(default_factory=set)
    external_calls: Set[str] = field(default_factory=set)
    external_bases: Set[str] = field(default_factory=set)
    unresolved_calls: Set[str] = field(default_factory=set)
    unresolved_call_details: Dict[str, Dict[str, object]] = field(default_factory=dict)
    unresolved_bases: Set[str] = field(default_factory=set)
    recursive_self_call: bool = False
    ca: int = 0
    ce_internal: int = 0
    ce_external: int = 0
    ce_total: int = 0
    instability: float = 0.0
    instability_total: float = 0.0
    layer: int = 0
    scc_id: int = -1
    scc_size: int = 1
    pagerank: float = 0.0
    betweenness: float = 0.0
    git_commit_count: int = 0
    git_churn: int = 0
    git_hotness: float = 0.0
    coord: List[float] = field(default_factory=list)
    risk_score: float = 0.0
    reasons: List[str] = field(default_factory=list)
    heuristic_candidates: Dict[str, List[str]] = field(default_factory=dict)
    semantic_signals: List[str] = field(default_factory=list)
    semantic_evidence_spans: List[Dict[str, object]] = field(default_factory=list)
    semantic_summary: Dict[str, object] = field(default_factory=dict)
    semantic_weight: float = 0.0
    contained_semantic_signals: List[str] = field(default_factory=list)
    contained_semantic_refs: List[Dict[str, object]] = field(default_factory=list)
    contained_semantic_summary: Dict[str, object] = field(default_factory=dict)
    contained_semantic_weight: float = 0.0
    behavioral_flow_steps: List[Dict[str, object]] = field(default_factory=list)
    behavioral_flow_summary: Dict[str, object] = field(default_factory=dict)
    raw_string_refs: Set[str] = field(default_factory=set)
    resolved_string_refs: Set[str] = field(default_factory=set)
    callable_params: List[str] = field(default_factory=list)
    callable_decorators: List[str] = field(default_factory=list)
    exported: bool = False
    plugin_data: Dict[str, object] = field(default_factory=dict)
    reachable_guards: Set[str] = field(default_factory=set)
    architectural_warnings: List[Dict[str, object]] = field(default_factory=list)
    taint_entry: bool = False
    taint_sources: List[str] = field(default_factory=list)
    tainted_params: Dict[str, str] = field(default_factory=dict)


@dataclass
class ResolutionOutcome:
    target: Optional[str]
    resolution_kind: str = ""
    confidence_score: float = 0.0
    confidence_label: str = ""
    resolution_reason: str = ""
    candidates: List[str] = field(default_factory=list)

    def to_payload(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "confidence_score": self.confidence_score,
            "confidence_label": self.confidence_label,
            "resolution_kind": self.resolution_kind,
            "resolution_reason": self.resolution_reason,
        }
        if self.candidates:
            payload["candidates"] = list(self.candidates)
        return payload


def path_to_module(rel_path: str) -> str:
    stem = rel_path[:-3] if rel_path.endswith(".py") else rel_path
    parts = stem.split(os.sep)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else stem


def language_slug(language: str) -> str:
    return language.lower().replace(" ", "_")


def source_group(rel_path: str, language: str, package_name: str = "") -> str:
    if package_name:
        return f"{language_slug(language)}.{package_name}"
    parent = Path(rel_path).parent.as_posix()
    if parent in {"", "."}:
        return language_slug(language)
    return f"{language_slug(language)}.{parent.replace('/', '.')}"


def source_qualname(rel_path: str) -> str:
    return Path(rel_path).name


def should_ignore_dir(name: str) -> bool:
    return name in IGNORE_DIRS or name.startswith(".") or name.startswith("llm_bundle") or name.startswith("ask_bundle")


def strip_json_comments(text: str) -> str:
    out: List[str] = []
    quote: Optional[str] = None
    escaped = False
    line_comment = False
    block_comment = False
    index = 0
    while index < len(text):
        char = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
                out.append(char)
        elif block_comment:
            if char == "*" and nxt == "/":
                block_comment = False
                index += 1
        elif quote:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        else:
            if char == "/" and nxt == "/":
                line_comment = True
                index += 1
            elif char == "/" and nxt == "*":
                block_comment = True
                index += 1
            else:
                out.append(char)
                if char in {'"', "'"}:
                    quote = char
        index += 1
    return "".join(out)


def load_relaxed_json(path: str) -> Dict[str, object]:
    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read()
    stripped = strip_json_comments(content)
    stripped = re.sub(r",(\s*[}\]])", r"\1", stripped)
    data = json.loads(stripped)
    return data if isinstance(data, dict) else {}


def resolve_relative_module(current_module: str, level: int, module: Optional[str]) -> Optional[str]:
    if level <= 0:
        return module
    base_parts = current_module.split(".")
    if len(base_parts) < level:
        return module
    prefix = ".".join(base_parts[:-level])
    if module:
        return f"{prefix}.{module}" if prefix else module
    return prefix or None


def stable_jitter(text: str, salt: str) -> float:
    digest = hashlib.sha1(f"{salt}:{text}".encode("utf-8")).hexdigest()
    value = int(digest[:8], 16) / 0xFFFFFFFF
    return (value - 0.5) * 3.0


def ref_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = ref_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Subscript):
        return ref_name(node.value)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "super":
            return "super()"
        return ref_name(node.func)
    return None


def call_name(func_node: ast.AST) -> Optional[str]:
    return ref_name(func_node)


class CallCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: Set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        name = call_name(node.func)
        if name:
            self.calls.add(name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


class ImportCollector(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.imports_modules: Dict[str, str] = {}
        self.imports_symbols: Dict[str, str] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname if alias.asname else alias.name.split(".")[0]
            self.imports_modules[local] = alias.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        resolved_mod = resolve_relative_module(self.module, node.level, node.module)
        for alias in node.names:
            if alias.name == "*":
                continue
            local = alias.asname if alias.asname else alias.name
            self.imports_symbols[local] = f"{resolved_mod}.{alias.name}" if resolved_mod else alias.name

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


_STRING_REF_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*){1,}$")


class StringRefCollector(ast.NodeVisitor):
    """Collects string literals that look like dotted importable paths."""

    def __init__(self) -> None:
        self.refs: Set[str] = set()

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and _STRING_REF_RE.match(node.value):
            self.refs.add(node.value)
        self.generic_visit(node)

    def visit_Str(self, node: ast.Str) -> None:  # type: ignore[attr-defined]
        if _STRING_REF_RE.match(node.s):
            self.refs.add(node.s)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

