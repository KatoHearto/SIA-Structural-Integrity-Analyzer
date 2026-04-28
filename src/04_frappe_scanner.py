# ── SIA src/04_frappe_scanner.py ── (god_mode_v3.py lines 951–1079) ──────────

    def _scan_frappe_json_files(self) -> None:
        """Walk the project and register all Frappe DocType JSON files as graph nodes."""
        import fnmatch as _fnmatch
        norm_excludes = [p.rstrip("/\\") for p in self.exclude_globs]
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if not should_ignore_dir(d)]
            if norm_excludes:
                dirs[:] = [d for d in dirs if not any(_fnmatch.fnmatch(d, pattern) for pattern in norm_excludes)]
            for file_name in files:
                if not file_name.endswith(".json"):
                    continue
                full_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(full_path, self.root_dir)
                try:
                    with open(full_path, encoding="utf-8") as handle:
                        data = json.load(handle)
                    if not isinstance(data, dict):
                        raise ValueError("not a JSON object")
                except (OSError, json.JSONDecodeError, ValueError):
                    continue
                if data.get("doctype") != "DocType":
                    continue
                self._parse_frappe_doctype_file(rel_path, data)

    @staticmethod
    def _frappe_snake(name: str) -> str:
        return name.lower().replace(" ", "_").replace("-", "_")

    def _parse_frappe_doctype_file(self, rel_path: str, data: Dict[str, object]) -> None:
        """Register a Frappe DocType JSON as a graph node."""
        dt_name = str(data.get("name", ""))
        if not dt_name:
            return
        dt_snake = self._frappe_snake(dt_name)
        dt_module = str(data.get("module", ""))

        controller_path = str(Path(rel_path).with_suffix(".py").as_posix())
        if Path(rel_path).stem != dt_snake:
            controller_path = str((Path(rel_path).parent / f"{dt_snake}.py").as_posix())

        link_refs: List[str] = []
        child_refs: List[str] = []
        for field_def in data.get("fields", []):
            if not isinstance(field_def, dict):
                continue
            field_type = str(field_def.get("fieldtype", ""))
            options = str(field_def.get("options", "")).strip()
            if not options:
                continue
            if field_type == "Link":
                link_refs.append(options)
            elif field_type in ("Table", "Table MultiSelect"):
                child_refs.append(options)

        node_id = f"frappe.doctype.{dt_snake}:{dt_snake}"
        node = SymbolNode(
            node_id=node_id,
            module=f"frappe.doctype.{dt_snake}",
            qualname=dt_snake,
            kind="doctype",
            file=rel_path,
            lines=[1, 1],
            class_context=None,
            imports_modules={},
            imports_symbols={},
            language="FrappeDocType",
            plugin_data={
                "frappe_doctype_name": dt_name,
                "frappe_module": dt_module,
                "frappe_snake": dt_snake,
                "frappe_link_refs": link_refs,
                "frappe_child_refs": child_refs,
                "frappe_controller_path": controller_path,
                "frappe_is_single": bool(data.get("issingle")),
                "frappe_is_virtual": bool(data.get("is_virtual")),
            },
        )
        self.nodes[node_id] = node
        self.frappe_doctype_name_to_node[dt_name] = node_id
        self.frappe_doctype_snake_to_node[dt_snake] = node_id

    def _load_js_compiler_options(self, config_path: str, visited: Set[str]) -> Dict[str, object]:
        normalized = os.path.normpath(os.path.abspath(config_path))
        if normalized in visited or not os.path.exists(normalized):
            return {}
        visited.add(normalized)

        try:
            data = load_relaxed_json(normalized)
        except (OSError, json.JSONDecodeError):
            return {}

        merged: Dict[str, object] = {}
        extends_value = data.get("extends")
        if isinstance(extends_value, str):
            base_path = self._resolve_extended_js_config_path(normalized, extends_value)
            if base_path:
                merged.update(self._load_js_compiler_options(base_path, visited))

        current_options = data.get("compilerOptions", {})
        if isinstance(current_options, dict):
            if "baseUrl" in current_options:
                merged["baseUrl"] = current_options["baseUrl"]
            existing_paths = merged.get("paths", {})
            merged_paths = dict(existing_paths) if isinstance(existing_paths, dict) else {}
            raw_paths = current_options.get("paths", {})
            if isinstance(raw_paths, dict):
                for alias_pattern, targets in raw_paths.items():
                    merged_paths[alias_pattern] = targets
            if merged_paths:
                merged["paths"] = merged_paths

        return merged

    def _resolve_extended_js_config_path(self, config_path: str, extends_value: str) -> str:
        if not extends_value or not extends_value.startswith((".", "..")):
            return ""
        candidate = os.path.normpath(os.path.join(os.path.dirname(config_path), extends_value.replace("/", os.sep)))
        suffix = Path(candidate).suffix.lower()
        if suffix != ".json":
            candidate_json = candidate + ".json"
            if os.path.exists(candidate_json):
                return candidate_json
        if os.path.isdir(candidate):
            nested = os.path.join(candidate, "tsconfig.json")
            if os.path.exists(nested):
                return nested
        return candidate if os.path.exists(candidate) else ""
