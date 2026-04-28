# ── SIA src/07_parser_go.py ── (god_mode_v3.py lines 2025–2058) ──────────────

    def _parse_go_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        funcs = re.findall(r"(?m)^\s*func\s+(?:\([^)]+\)\s*)?([A-Za-z_]\w*)\s*\(", content)
        types = re.findall(r"(?m)^\s*type\s+([A-Za-z_]\w*)\s+(?:struct|interface|map|chan|func|\[\])", content)
        declared_symbols = self._dedupe(funcs + types)[:20]

        raw_imports: Set[str] = set()
        imports_modules: Dict[str, str] = {}
        for spec in re.findall(r'"([^"]+)"', content):
            raw_imports.add(spec)
            local = spec.split("/")[-1]
            imports_modules[local] = spec

        module_name = source_group(rel_path, language)
        if self.go_root_module:
            rel_posix = Path(rel_path).parent.as_posix()
            if rel_posix in {"", "."}:
                module_name = self.go_root_module
            else:
                module_name = f"{self.go_root_module}/{rel_posix}"

        self.go_dir_to_node[str(Path(rel_path).parent)] = f"{module_name}:{source_qualname(rel_path)}"
        return {
            "module": module_name,
            "qualname": source_qualname(rel_path),
            "kind": "module",
            "imports_modules": imports_modules,
            "imports_symbols": {},
            "declared_symbols": declared_symbols,
            "raw_imports": raw_imports,
            "raw_calls": set(),
            "raw_bases": set(),
            "raw_string_refs": self._harvest_string_refs(content, exclude=raw_imports),
        }
