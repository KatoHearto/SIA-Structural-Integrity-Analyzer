# ── SIA src/03_run_scan.py ── (god_mode_v3.py lines 731–950) ─────────────────

    def run(
        self,
        top_n: int = 20,
        include_graph: bool = True,
        context_line_budget: int = 220,
        include_git_hotspots: bool = True,
        ask_query: str = "",
        ask_line_budget: int = 110,
        enable_taint: bool = False,
    ) -> Dict[str, object]:
        self.taint_enabled = enable_taint
        self.taint_summary = {}
        self._scan_files()
        self._build_indices()
        self._resolve_edges()
        sccs, node_to_scc = self._tarjan_scc()
        self._apply_scc(node_to_scc, sccs)
        self._compute_layers(node_to_scc, sccs)
        self._compute_pagerank()
        self._compute_betweenness()
        self._compute_git_hotspots(enabled=include_git_hotspots)
        self._compute_coords()
        self._extract_semantic_signals()
        self._propagate_guard_signals()
        self._compute_architectural_warnings()
        self._compute_risk_scores()
        self._extract_behavioral_flows()
        if enable_taint:
            self.taint_summary = self._compute_taint_metadata()

        top_risks = self._top_risks(top_n)
        modules = self._module_report()
        cycles = [sorted(comp) for comp in sccs if len(comp) > 1]
        cycles = sorted(cycles, key=lambda c: (-len(c), c))
        recursive_symbols = self._recursive_symbols()
        llm_context_pack = self._build_llm_context_pack(top_risks, line_budget=context_line_budget)
        project_inventory = self._build_project_inventory()
        project_context_pack = self._build_project_context_pack(project_inventory)
        ask_context_pack = self._build_ask_context_pack(ask_query.strip(), line_budget=max(20, ask_line_budget)) if ask_query.strip() else None

        report: Dict[str, object] = {
            "meta": {
                "version": "3.62",
                "root_dir": self.root_dir,
                "node_count": len(self.nodes),
                "edge_count": sum(len(v) for v in self.adj.values()),
                "cycle_count": len(cycles),
                "recursive_symbol_count": len(recursive_symbols),
                "git_hotspots_enabled": self.git_hotspot_enabled,
                "git_tracked_file_count": self.git_tracked_file_count,
                "parse_error_count": len(self.parse_errors),
                "architectural_warning_count": sum(
                    len(n.architectural_warnings) for n in self.nodes.values()
                ),
                "ask_query_present": bool(ask_context_pack),
                **({"taint_summary": dict(self.taint_summary)} if enable_taint else {}),
            },
            "top_risks": top_risks,
            "module_report": modules,
            "project_inventory": project_inventory,
            "project_context_pack": project_context_pack,
            "cycles": cycles,
            "recursive_symbols": recursive_symbols,
            "llm_context_pack": llm_context_pack,
            "parse_errors": self.parse_errors,
            "architectural_warnings": [
                {
                    "node_id": node.node_id,
                    "language": node.language,
                    "kind": node.kind,
                    "file": node.file,
                    "warnings": list(node.architectural_warnings),
                }
                for node in sorted(self.nodes.values(), key=lambda n: n.node_id)
                if node.architectural_warnings
            ],
        }
        if ask_context_pack is not None:
            report["ask_context_pack"] = ask_context_pack

        if include_graph:
            report["nodes"] = [self._node_payload(self.nodes[nid]) for nid in sorted(self.nodes)]
            report["edges"] = [
                [src, dst]
                for src in sorted(self.adj)
                for dst in sorted(self.adj[src])
            ]
            report["edge_details"] = [
                {
                    "source": src,
                    "target": dst,
                    "kinds": sorted(self.edge_kinds[(src, dst)]),
                    **(
                        self.edge_resolution[(src, dst)].to_payload()
                        if (src, dst) in self.edge_resolution
                        else self._resolution("heuristic", "Resolved edge without explicit provenance.", target=dst).to_payload()
                    ),
                }
                for src in sorted(self.adj)
                for dst in sorted(self.adj[src])
            ]

        return report

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
                    if self.filter_languages is None or "Python" in self.filter_languages:
                        self._parse_file(rel_path)
                elif suffix in LANGUAGE_BY_SUFFIX:
                    _lang = LANGUAGE_BY_SUFFIX[suffix]
                    if self.filter_languages is None or _lang in self.filter_languages:
                        self._parse_non_python_file(rel_path, _lang)
        if "frappe" in self.active_plugins:
            self._scan_frappe_json_files()
        elif self._detect_frappe_project():
            print(
                "[SIA] Frappe project detected. Re-run with --plugin frappe for DocType analysis.",
                file=sys.stderr,
            )

    def _discover_go_root_module(self) -> str:
        go_mod_path = os.path.join(self.root_dir, "go.mod")
        if not os.path.exists(go_mod_path):
            return ""
        try:
            with open(go_mod_path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except OSError:
            return ""
        match = re.search(r"(?m)^\s*module\s+(.+?)\s*$", content)
        return match.group(1).strip() if match else ""

    def _discover_js_resolver_configs(self) -> List[Dict[str, object]]:
        configs: List[Dict[str, object]] = []
        config_paths: List[str] = []
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if not should_ignore_dir(d)]
            for file_name in files:
                lower_name = file_name.lower()
                if lower_name == "jsconfig.json" or (lower_name.startswith("tsconfig") and lower_name.endswith(".json")):
                    config_paths.append(os.path.join(root, file_name))

        for config_path in sorted(config_paths):
            compiler_options = self._load_js_compiler_options(config_path, visited=set())
            config_dir = os.path.dirname(config_path)
            base_url = str(compiler_options.get("baseUrl", "."))
            base_dir = os.path.normpath(os.path.join(config_dir, base_url))
            raw_paths = compiler_options.get("paths", {})
            normalized_paths: Dict[str, List[str]] = {}
            if isinstance(raw_paths, dict):
                for alias_pattern, targets in raw_paths.items():
                    if not isinstance(alias_pattern, str):
                        continue
                    target_list = targets if isinstance(targets, list) else [targets]
                    resolved_targets: List[str] = []
                    for raw_target in target_list:
                        if not isinstance(raw_target, str):
                            continue
                        resolved_targets.append(os.path.normpath(os.path.join(base_dir, raw_target.replace("/", os.sep))))
                    if resolved_targets:
                        normalized_paths[alias_pattern] = resolved_targets
            configs.append(
                {
                    "config_file": Path(os.path.relpath(config_path, self.root_dir)).as_posix(),
                    "config_dir": config_dir,
                    "base_dir": base_dir,
                    "paths": normalized_paths,
                }
            )

        return sorted(configs, key=lambda item: len(str(item["config_dir"])), reverse=True)

    def _detect_frappe_project(self) -> bool:
        """Return True if root looks like a Frappe bench or app."""
        for name in ("apps.txt", "sites/apps.txt"):
            if os.path.isfile(os.path.join(self.root_dir, name)):
                return True
        for name in ("pyproject.toml", "requirements.txt", "setup.py"):
            path = os.path.join(self.root_dir, name)
            if os.path.isfile(path):
                try:
                    with open(path, encoding="utf-8") as handle:
                        content = handle.read()
                    if "frappe" in content.lower():
                        return True
                except OSError:
                    pass
        return False
