# ── SIA src/12_taint.py ── (god_mode_v3.py lines 3560–3913) ────────────────────
    def _compute_taint_metadata(self) -> Dict[str, object]:
        hook_entry_nodes = self._resolve_frappe_hook_entry_nodes()
        source_breakdown: Dict[str, int] = defaultdict(int)
        entry_points = 0
        tainted_param_count = 0

        for node in self.nodes.values():
            node.taint_entry = False
            node.taint_sources = []
            node.tainted_params = {}

        for node_id in sorted(self.nodes):
            node = self.nodes[node_id]
            if node.kind not in SEMANTIC_EXECUTABLE_KINDS:
                continue
            sources = self._classify_taint_sources_for_node(node, hook_entry_nodes)
            if not sources:
                continue
            node.taint_entry = True
            node.taint_sources = sources
            node.tainted_params = self._tainted_params_for_node(node, sources)
            entry_points += 1
            tainted_param_count += len(node.tainted_params)
            for kind in node.tainted_params.values():
                source_breakdown[kind] += 1

        return {
            "entry_points": entry_points,
            "tainted_params": tainted_param_count,
            "source_breakdown": {
                kind: source_breakdown[kind]
                for kind in _TAINT_SOURCE_KINDS
                if source_breakdown.get(kind)
            },
        }

    def _classify_taint_sources_for_node(self, node: SymbolNode, hook_entry_nodes: Set[str]) -> List[str]:
        text = self._node_source_text(node, direct_semantics=True)
        if not text:
            return []

        sources: List[str] = []
        param_names = {param.lower() for param in node.callable_params}

        if node.language == "Python":
            if self._python_node_has_decorator(node, "frappe.whitelist"):
                sources.append("http_param")
            if self._python_node_has_decorator(node, "click.command"):
                sources.append("cli_arg")
            if node.class_context is None and node.qualname.split(".")[-1] == "main" and "sys.argv" in text:
                sources.append("cli_arg")
            if self._node_has_taint_indicator(text, _TAINT_SOURCE_KINDS["http_param"]):
                sources.append("http_param")
            if (
                node.node_id in hook_entry_nodes
                or (
                    self._node_has_taint_indicator(text, _TAINT_SOURCE_KINDS["event_hook"])
                    and bool(param_names & {"doc", "event", "ctx", "context"})
                )
            ):
                sources.append("event_hook")
        elif node.language in {"JavaScript", "TypeScript"} and node.exported:
            if param_names & {"req", "request"}:
                sources.append("http_param")
            if param_names & {"event", "ctx", "context"}:
                sources.append("event_hook")

        if self._node_has_taint_indicator(text, _TAINT_SOURCE_KINDS["cli_arg"]):
            sources.append("cli_arg")
        if self._node_has_taint_indicator(text, _TAINT_SOURCE_KINDS["file_read"]):
            sources.append("file_read")
        if self._node_has_taint_indicator(text, _TAINT_SOURCE_KINDS["env_var"]):
            sources.append("env_var")
        if self._node_has_taint_indicator(text, _TAINT_SOURCE_KINDS["external_api"]):
            sources.append("external_api")
        return self._sort_taint_sources(sources)

    def _tainted_params_for_node(self, node: SymbolNode, sources: List[str]) -> Dict[str, str]:
        params = [param for param in node.callable_params if param not in {"self", "cls"}]
        if not params or not sources:
            return {}

        if node.language in {"JavaScript", "TypeScript"} and node.exported:
            mapped: Dict[str, str] = {}
            for param in params:
                lower = param.lower()
                if lower in {"req", "request"}:
                    mapped[param] = "http_param"
                elif lower in {"event", "ctx", "context"}:
                    mapped[param] = "event_hook"
            if mapped:
                return mapped

        preferred = sources[0]
        return {param: preferred for param in params}

    def _python_node_has_decorator(self, node: SymbolNode, decorator_name: str) -> bool:
        resolved: Set[str] = set(node.callable_decorators)
        for decorator in node.callable_decorators:
            if decorator in node.imports_symbols:
                resolved.add(node.imports_symbols[decorator])
            root, dot, tail = decorator.partition(".")
            if dot and root in node.imports_modules:
                resolved.add(f"{node.imports_modules[root]}.{tail}")
        return decorator_name in resolved

    @staticmethod
    def _node_has_taint_indicator(text: str, indicators: List[str]) -> bool:
        return any(indicator in text for indicator in indicators)

    def _sort_taint_sources(self, sources: Iterable[str]) -> List[str]:
        unique = self._dedupe([source for source in sources if source in _TAINT_SOURCE_ORDER])
        return sorted(unique, key=lambda source: (_TAINT_SOURCE_ORDER[source], source))

    def _resolve_frappe_hook_entry_nodes(self) -> Set[str]:
        hook_files = sorted({
            node.file
            for node in self.nodes.values()
            if node.language == "Python" and Path(node.file).name == "hooks.py"
        })
        targets: Set[str] = set()
        for rel_path in hook_files:
            for dotted_path in self._extract_frappe_hook_paths(rel_path):
                target = self._lookup_node_for_dotted_ref(dotted_path)
                if target:
                    targets.add(target)
        return targets

    def _extract_frappe_hook_paths(self, rel_path: str) -> List[str]:
        content = self._read_project_text(rel_path)
        if content is None:
            return []
        try:
            tree = ast.parse(content, filename=rel_path)
        except SyntaxError:
            return []

        targets: List[str] = []
        for stmt in tree.body:
            if not isinstance(stmt, ast.Assign):
                continue
            names = [target.id for target in stmt.targets if isinstance(target, ast.Name)]
            if not names:
                continue
            if not any(name in {"doc_events", "scheduler_events", "on_submit"} for name in names):
                continue
            targets.extend(self._extract_frappe_hook_paths_from_value(stmt.value))
        return self._dedupe(targets)

    def _extract_frappe_hook_paths_from_value(self, value: ast.AST) -> List[str]:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            candidate = value.value.strip()
            return [candidate] if _STRING_REF_RE.match(candidate) else []
        if isinstance(value, ast.Dict):
            out: List[str] = []
            for nested in value.values:
                if nested is not None:
                    out.extend(self._extract_frappe_hook_paths_from_value(nested))
            return out
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            out: List[str] = []
            for nested in value.elts:
                out.extend(self._extract_frappe_hook_paths_from_value(nested))
            return out
        return []

    def _incoming_string_ref_sources(self, target_id: str) -> List[str]:
        return sorted(
            node_id
            for node_id, node in self.nodes.items()
            if target_id in node.resolved_string_refs
        )

    def _classify_unresolved_call(self, caller: SymbolNode, raw: str) -> str:
        if caller.language in {"JavaScript", "TypeScript"}:
            return self._classify_js_like_call(caller, raw)
        if caller.language == "Java":
            return self._classify_java_call(caller, raw)
        root = raw.split(".", 1)[0]
        if raw == "super()" or root in BUILTIN_NAMES:
            return "ignore"
        if raw.startswith(("self.", "cls.", "super().")):
            return "unresolved"
        if root in caller.imports_modules or root in caller.imports_symbols:
            return "external"
        if raw in caller.imports_symbols:
            return "external"
        return "unresolved"

    def _classify_unresolved_base(self, caller: SymbolNode, raw: str) -> str:
        if caller.language != "Python":
            return self._classify_non_python_base(caller, raw)
        root = raw.split(".", 1)[0]
        if root in BUILTIN_NAMES or raw == "object":
            return "ignore"
        if root in caller.imports_modules or root in caller.imports_symbols:
            return "external"
        if raw in caller.imports_symbols:
            return "external"
        return "unresolved"

    def _resolve_base_outcome(self, caller: SymbolNode, raw: str) -> ResolutionOutcome:
        if caller.language != "Python":
            target = self._resolve_non_python_base(caller, raw)
            if target:
                return self._resolution(target=target, kind="inheritance_exact", reason=f"Resolved base `{raw}` as an internal inherited type.")
            return ResolutionOutcome(target=None)
        module = caller.module
        candidate = f"{module}:{raw}"
        if candidate in self.nodes and self.nodes[candidate].kind == "class":
            return self._resolution(target=candidate, kind="inheritance_exact", reason=f"Resolved base `{raw}` in the same module.")

        if "." in raw:
            head, tail = raw.split(".", 1)
            if head in caller.imports_modules:
                fq = f"{caller.imports_modules[head]}.{tail}"
                target = self.fq_to_id.get(fq)
                if target and self.nodes[target].kind == "class":
                    return self._resolution(target=target, kind="inheritance_exact", reason=f"Resolved base `{raw}` through imported module `{head}`.")
            if head in caller.imports_symbols:
                fq = f"{caller.imports_symbols[head]}.{tail}"
                target = self.fq_to_id.get(fq)
                if target and self.nodes[target].kind == "class":
                    return self._resolution(target=target, kind="inheritance_exact", reason=f"Resolved base `{raw}` through imported symbol `{head}`.")
            direct = self.fq_to_id.get(raw)
            if direct and self.nodes[direct].kind == "class":
                return self._resolution(target=direct, kind="inheritance_exact", reason=f"Resolved base `{raw}` by exact qualified name.")

        if raw in caller.imports_symbols:
            target = self.fq_to_id.get(caller.imports_symbols[raw])
            if target and self.nodes[target].kind == "class":
                return self._resolution(target=target, kind="inheritance_exact", reason=f"Resolved base `{raw}` through exact import.")

        candidates = [node_id for node_id in self.short_index.get(raw, []) if self.nodes[node_id].kind == "class"]
        if len(candidates) == 1:
            return self._resolution(target=candidates[0], kind="heuristic", reason=f"Resolved base `{raw}` via unique short-name class match.")
        return ResolutionOutcome(target=None)

    def _resolve_base(self, caller: SymbolNode, raw: str) -> Optional[str]:
        return self._resolve_base_outcome(caller, raw).target

    def _resolve_call_outcome(self, caller: SymbolNode, raw: str) -> ResolutionOutcome:
        if caller.language in {"JavaScript", "TypeScript"}:
            return self._resolve_js_like_call_outcome(caller, raw)
        if caller.language == "Java":
            return self._resolve_java_call_outcome(caller, raw)
        module = caller.module
        class_ctx = caller.class_context

        # Direct same-module qualified symbol, e.g. Class.method
        candidate = f"{module}:{raw}"
        if candidate in self.nodes:
            return self._resolution(target=candidate, kind="direct_symbol", reason=f"Resolved `{raw}` by exact symbol name in the same module.")

        # self.method / cls.method
        if raw.startswith("self.") or raw.startswith("cls."):
            if class_ctx:
                method = raw.split(".", 1)[1]
                candidate = f"{module}:{class_ctx}.{method}"
                if candidate in self.nodes:
                    return self._resolution(target=candidate, kind="same_class_method", reason=f"Resolved `{raw}` to method `{method}` on the current class.")
            return ResolutionOutcome(target=None)

        # super().method: keep external unless base method exists in same module uniquely
        if raw.startswith("super()."):
            method = raw.split(".", 1)[1]
            target = self._resolve_super_method(module, class_ctx, method)
            if target:
                return self._resolution(target=target, kind="super_dispatch", reason=f"Resolved `{raw}` through base-class dispatch.")
            matches = [nid for nid in self.short_index.get(method, []) if self.nodes[nid].module == module]
            if len(matches) == 1:
                return self._resolution(target=matches[0], kind="heuristic", reason=f"Resolved `{raw}` via unique same-module fallback after super dispatch.")
            return ResolutionOutcome(target=None)

        # Dotted call: alias.module_or_symbol.something
        if "." in raw:
            head, tail = raw.split(".", 1)
            if head in caller.imports_modules:
                fq = f"{caller.imports_modules[head]}.{tail}"
                target = self.fq_to_id.get(fq)
                if target:
                    return self._resolution(target=target, kind="import_exact", reason=f"Resolved `{raw}` through imported module `{head}`.")
            if head in caller.imports_symbols:
                fq = f"{caller.imports_symbols[head]}.{tail}"
                target = self.fq_to_id.get(fq)
                if target:
                    return self._resolution(target=target, kind="import_exact", reason=f"Resolved `{raw}` through imported symbol `{head}`.")
            direct = self.fq_to_id.get(raw)
            if direct:
                return self._resolution(target=direct, kind="direct_symbol", reason=f"Resolved `{raw}` by exact qualified symbol name.")

        # Bare imported symbol
        if raw in caller.imports_symbols:
            fq = caller.imports_symbols[raw]
            target = self.fq_to_id.get(fq)
            if target:
                return self._resolution(target=target, kind="import_exact", reason=f"Resolved `{raw}` through exact import.")

        # Bare same-class method inside class context
        if class_ctx:
            candidate = f"{module}:{class_ctx}.{raw}"
            if candidate in self.nodes:
                return self._resolution(target=candidate, kind="same_class_method", reason=f"Resolved `{raw}` as a method on the current class.")

        # Bare same-module function/class
        candidate = f"{module}:{raw}"
        if candidate in self.nodes:
            return self._resolution(target=candidate, kind="same_module_symbol", reason=f"Resolved `{raw}` as a same-module symbol.")

        # Global unique short name fallback
        candidates = [candidate for candidate in self.short_index.get(raw, []) if self.nodes[candidate].language == "Python"]
        if len(candidates) == 1:
            return self._resolution(target=candidates[0], kind="heuristic", reason=f"Resolved `{raw}` via unique short-name fallback.")

        return ResolutionOutcome(target=None)

    def _resolve_call(self, caller: SymbolNode, raw: str) -> Optional[str]:
        return self._resolve_call_outcome(caller, raw).target

    def _resolve_non_python_base(self, caller: SymbolNode, raw: str) -> Optional[str]:
        root = raw.split(".", 1)[0].split("::", 1)[0]
        if caller.language in {"JavaScript", "TypeScript"}:
            if root in caller.declared_symbols:
                target = self._resolve_js_like_file_symbol(caller.file, root)
                if target and target != caller.node_id:
                    return target
                return caller.node_id
            spec = caller.imports_symbols.get(root) or caller.imports_modules.get(root)
            if spec:
                return self._resolve_import(caller, spec)
            return self._resolve_js_like_file_symbol(caller.file, root)

        if caller.language == "Java":
            cleaned = re.sub(r"<.*?>", "", raw).strip()
            simple = cleaned.rsplit(".", 1)[-1]
            if simple in caller.declared_symbols:
                return caller.node_id
            if cleaned in self.java_type_to_node:
                return self.java_type_to_node[cleaned]
            imported = caller.imports_symbols.get(simple)
            if imported and imported in self.java_type_to_node:
                return self.java_type_to_node[imported]
            if caller.package_name:
                local_fqcn = f"{caller.package_name}.{simple}"
                if local_fqcn in self.java_type_to_node:
                    return self.java_type_to_node[local_fqcn]
            candidates = [node_id for fqcn, node_id in self.java_type_to_node.items() if fqcn.endswith(f".{simple}")]
            return candidates[0] if len(candidates) == 1 else None

        return None

    def _is_java_concrete_type(self, node: SymbolNode) -> bool:
        return node.language == "Java" and node.kind in {"class", "enum"} and not node.is_abstract

