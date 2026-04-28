# ── SIA src/02_analyzer_init.py ── (god_mode_v3.py lines 692–730) ────────────

class StructuralIntegrityAnalyzerV3:
    def __init__(
        self,
        root_dir: str,
        exclude_globs: Optional[List[str]] = None,
        filter_languages: Optional[List[str]] = None,
        plugins: Optional[List[str]] = None,
    ) -> None:
        self.root_dir = os.path.abspath(root_dir)
        self.nodes: Dict[str, SymbolNode] = {}
        self.adj: Dict[str, Set[str]] = defaultdict(set)
        self.edge_kinds: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
        self.parse_errors: List[Dict[str, str]] = []
        self.fq_to_id: Dict[str, str] = {}
        self.short_index: Dict[str, List[str]] = defaultdict(list)
        self.file_module_node: Dict[str, str] = {}
        self.file_top_level_symbol_index: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
        self.js_barrel_bindings: Dict[str, Dict[str, str]] = defaultdict(dict)
        self.js_barrel_star_specs: Dict[str, List[str]] = defaultdict(list)
        self.go_dir_to_node: Dict[str, str] = {}
        self.java_type_to_node: Dict[str, str] = {}
        self.java_member_to_node: Dict[str, str] = {}
        self.java_concrete_type_targets: Dict[str, List[str]] = defaultdict(list)
        self.rust_module_to_node: Dict[str, str] = {}
        self.edge_resolution: Dict[Tuple[str, str], ResolutionOutcome] = {}
        self.project_text_cache: Dict[str, Optional[str]] = {}
        self.project_lines_cache: Dict[str, List[str]] = {}
        self.git_hotspot_enabled: bool = False
        self.git_tracked_file_count: int = 0
        self.exclude_globs: List[str] = list(exclude_globs or [])
        self.filter_languages: Optional[Set[str]] = set(filter_languages) if filter_languages else None
        self.active_plugins: Set[str] = set(plugin.lower() for plugin in (plugins or []))
        self.frappe_doctype_name_to_node: Dict[str, str] = {}
        self.frappe_doctype_snake_to_node: Dict[str, str] = {}
        self.go_root_module: str = self._discover_go_root_module()
        self.js_resolver_configs: List[Dict[str, object]] = self._discover_js_resolver_configs()
        self.taint_enabled: bool = False
        self.taint_summary: Dict[str, object] = {}
