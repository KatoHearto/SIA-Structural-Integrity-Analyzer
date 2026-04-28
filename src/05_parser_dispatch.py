# ── SIA src/05_parser_dispatch.py ── (god_mode_v3.py lines 1080–1395) ────────

    def _parse_file(self, rel_path: str) -> None:
        full_path = os.path.join(self.root_dir, rel_path)
        try:
            with open(full_path, "r", encoding="utf-8") as handle:
                source = handle.read()
            tree = ast.parse(source, filename=rel_path)
        except SyntaxError as exc:
            self.parse_errors.append({"file": rel_path, "error": f"SyntaxError: {exc.msg} (line {exc.lineno})"})
            return
        except (OSError, UnicodeDecodeError) as exc:
            self.parse_errors.append({"file": rel_path, "error": f"OSError: {exc}"})
            return

        module = path_to_module(rel_path)
        imports_modules, imports_symbols = self._extract_imports(tree, module)
        raw_imports_set = (
            set(imports_modules)
            | set(imports_modules.values())
            | set(imports_symbols)
            | set(imports_symbols.values())
        )
        module_string_refs = self._string_refs_from_statements(tree.body) - raw_imports_set
        if module_string_refs:
            self.nodes[f"{module}:{source_qualname(rel_path)}"] = SymbolNode(
                node_id=f"{module}:{source_qualname(rel_path)}",
                module=module,
                qualname=source_qualname(rel_path),
                kind="module",
                file=rel_path,
                lines=[1, max(1, len(source.splitlines()))],
                class_context=None,
                imports_modules=imports_modules,
                imports_symbols=imports_symbols,
                raw_string_refs=module_string_refs,
            )
        self._collect_definitions(
            module=module,
            rel_path=rel_path,
            statements=tree.body,
            imports_modules=imports_modules,
            imports_symbols=imports_symbols,
            qual_prefix="",
            class_context=None,
        )

    def _extract_imports(self, tree: ast.Module, module: str) -> Tuple[Dict[str, str], Dict[str, str]]:
        imports_modules: Dict[str, str] = {}
        imports_symbols: Dict[str, str] = {}
        for stmt in tree.body:
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    local = alias.asname if alias.asname else alias.name.split(".")[0]
                    imports_modules[local] = alias.name
            elif isinstance(stmt, ast.ImportFrom):
                resolved_mod = resolve_relative_module(module, stmt.level, stmt.module)
                for alias in stmt.names:
                    if alias.name == "*":
                        continue
                    local = alias.asname if alias.asname else alias.name
                    if resolved_mod:
                        imports_symbols[local] = f"{resolved_mod}.{alias.name}"
                    else:
                        imports_symbols[local] = alias.name
        return imports_modules, imports_symbols

    def _string_refs_from_statements(self, statements: Iterable[ast.stmt]) -> Set[str]:
        collector = StringRefCollector()
        for stmt in statements:
            collector.visit(stmt)
        return set(collector.refs)

    def _extract_local_imports(
        self,
        module: str,
        statements: Iterable[ast.stmt],
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        collector = ImportCollector(module)
        for stmt in statements:
            collector.visit(stmt)
        return collector.imports_modules, collector.imports_symbols

    def _merged_imports(
        self,
        base_modules: Dict[str, str],
        base_symbols: Dict[str, str],
        local_modules: Dict[str, str],
        local_symbols: Dict[str, str],
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        merged_modules = dict(base_modules)
        merged_modules.update(local_modules)
        merged_symbols = dict(base_symbols)
        merged_symbols.update(local_symbols)
        return merged_modules, merged_symbols

    @staticmethod
    def _python_decorator_names(decorators: Iterable[ast.expr]) -> List[str]:
        names: List[str] = []
        seen: Set[str] = set()
        for decorator in decorators:
            name = ref_name(decorator.func) if isinstance(decorator, ast.Call) else ref_name(decorator)
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names

    @staticmethod
    def _python_param_names(args: ast.arguments) -> List[str]:
        names: List[str] = []
        for arg in getattr(args, "posonlyargs", []):
            names.append(arg.arg)
        for arg in args.args:
            names.append(arg.arg)
        if args.vararg is not None:
            names.append(args.vararg.arg)
        for arg in args.kwonlyargs:
            names.append(arg.arg)
        if args.kwarg is not None:
            names.append(args.kwarg.arg)
        return names

    def _collect_definitions(
        self,
        module: str,
        rel_path: str,
        statements: Iterable[ast.stmt],
        imports_modules: Dict[str, str],
        imports_symbols: Dict[str, str],
        qual_prefix: str,
        class_context: Optional[str],
    ) -> None:
        for stmt in statements:
            if isinstance(stmt, ast.ClassDef):
                class_qual = f"{qual_prefix}.{stmt.name}" if qual_prefix else stmt.name
                class_id = f"{module}:{class_qual}"
                local_modules, local_symbols = self._extract_local_imports(module, stmt.body)
                class_imports_modules, class_imports_symbols = self._merged_imports(
                    imports_modules,
                    imports_symbols,
                    local_modules,
                    local_symbols,
                )
                class_calls = self._calls_from_body(stmt.body)
                class_raw_imports_set = (
                    set(class_imports_modules)
                    | set(class_imports_modules.values())
                    | set(class_imports_symbols)
                    | set(class_imports_symbols.values())
                )
                class_string_refs = self._string_refs_from_statements(stmt.body) - class_calls - class_raw_imports_set
                class_bases = {name for name in (ref_name(base) for base in stmt.bases) if name}
                self.nodes[class_id] = SymbolNode(
                    node_id=class_id,
                    module=module,
                    qualname=class_qual,
                    kind="class",
                    file=rel_path,
                    lines=[stmt.lineno, getattr(stmt, "end_lineno", stmt.lineno)],
                    class_context=class_qual,
                    imports_modules=class_imports_modules,
                    imports_symbols=class_imports_symbols,
                    raw_calls=class_calls,
                    raw_bases=class_bases,
                    raw_string_refs=class_string_refs,
                )
                self._collect_definitions(
                    module=module,
                    rel_path=rel_path,
                    statements=stmt.body,
                    imports_modules=imports_modules,
                    imports_symbols=imports_symbols,
                    qual_prefix=class_qual,
                    class_context=class_qual,
                )
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_qual = f"{qual_prefix}.{stmt.name}" if qual_prefix else stmt.name
                fn_id = f"{module}:{fn_qual}"
                local_modules, local_symbols = self._extract_local_imports(module, stmt.body)
                fn_imports_modules, fn_imports_symbols = self._merged_imports(
                    imports_modules,
                    imports_symbols,
                    local_modules,
                    local_symbols,
                )
                fn_calls = self._calls_from_body(stmt.body)
                fn_raw_imports_set = (
                    set(fn_imports_modules)
                    | set(fn_imports_modules.values())
                    | set(fn_imports_symbols)
                    | set(fn_imports_symbols.values())
                )
                fn_string_refs = self._string_refs_from_statements(stmt.body) - fn_calls - fn_raw_imports_set
                kind = "async_function" if isinstance(stmt, ast.AsyncFunctionDef) else "function"
                self.nodes[fn_id] = SymbolNode(
                    node_id=fn_id,
                    module=module,
                    qualname=fn_qual,
                    kind=kind,
                    file=rel_path,
                    lines=[stmt.lineno, getattr(stmt, "end_lineno", stmt.lineno)],
                    class_context=class_context,
                    imports_modules=fn_imports_modules,
                    imports_symbols=fn_imports_symbols,
                    raw_calls=fn_calls,
                    raw_string_refs=fn_string_refs,
                    callable_params=self._python_param_names(stmt.args),
                    callable_decorators=self._python_decorator_names(stmt.decorator_list),
                )
                if self.taint_enabled:
                    self._collect_definitions(
                        module=module,
                        rel_path=rel_path,
                        statements=stmt.body,
                        imports_modules=fn_imports_modules,
                        imports_symbols=fn_imports_symbols,
                        qual_prefix=fn_qual,
                        class_context=class_context,
                    )

    def _parse_non_python_file(self, rel_path: str, language: str) -> None:
        content = self._read_project_text(rel_path)
        if content is None:
            self.parse_errors.append({"file": rel_path, "error": "OSError: Could not read source file"})
            return

        if language in {"JavaScript", "TypeScript"}:
            self._parse_js_like_file(rel_path, content, language)
            return
        if language == "Java":
            self._parse_java_file(rel_path, content, language)
            return
        if language == "CSharp":
            self._parse_csharp_file(rel_path, content, language)
            return
        if language == "Kotlin":
            self._parse_kotlin_file(rel_path, content, language)
            return
        if language == "PHP":
            self._parse_php_file(rel_path, content, language)
            return
        if language == "Ruby":
            self._parse_ruby_file(rel_path, content, language)
            return

        parser = {
            "Go": self._parse_go_module,
            "Rust": self._parse_rust_module,
            "CSharp": self._parse_csharp_module,
        }.get(language)
        if parser is None:
            return

        payload = parser(rel_path, content, language)
        self._register_non_python_node(rel_path, content, language, payload)

    def _register_non_python_node(
        self,
        rel_path: str,
        content: str,
        language: str,
        payload: Dict[str, object],
    ) -> str:
        module = payload.get("module") or source_group(rel_path, language)
        qualname = payload.get("qualname") or source_qualname(rel_path)
        node_id = f"{module}:{qualname}"
        line_count = max(1, len(content.splitlines()))
        lines = payload.get("lines")
        self.nodes[node_id] = SymbolNode(
            node_id=node_id,
            module=module,
            qualname=qualname,
            kind=str(payload.get("kind", "module")),
            file=rel_path,
            lines=list(lines) if isinstance(lines, list) and len(lines) == 2 else [1, line_count],
            class_context=str(payload.get("class_context")) if payload.get("class_context") else None,
            imports_modules=dict(payload.get("imports_modules", {})),
            imports_symbols=dict(payload.get("imports_symbols", {})),
            member_types=dict(payload.get("member_types", {})),
            member_qualifiers=dict(payload.get("member_qualifiers", {})),
            language=language,
            package_name=str(payload.get("package_name", "")),
            declared_symbols=list(payload.get("declared_symbols", [])),
            annotations=list(payload.get("annotations", [])),
            bean_name=str(payload.get("bean_name", "")),
            is_abstract=bool(payload.get("is_abstract", False)),
            di_primary=bool(payload.get("di_primary", False)),
            raw_imports=set(payload.get("raw_imports", set())),
            raw_calls=set(payload.get("raw_calls", set())),
            raw_bases=set(payload.get("raw_bases", set())),
            raw_string_refs=set(payload.get("raw_string_refs", set())),
            callable_params=list(payload.get("callable_params", [])),
            callable_decorators=list(payload.get("callable_decorators", [])),
            exported=bool(payload.get("exported", False)),
        )
        return node_id

    def _parse_js_like_file(self, rel_path: str, content: str, language: str) -> None:
        module_payload = self._parse_js_like_module(rel_path, content, language)
        module_name = str(module_payload.get("module") or source_group(rel_path, language))
        file_imports_modules = dict(module_payload.get("imports_modules", {}))
        file_imports_symbols = dict(module_payload.get("imports_symbols", {}))
        file_key = Path(rel_path).as_posix()
        self.js_barrel_bindings[file_key] = dict(module_payload.get("export_bindings", {}))
        self.js_barrel_star_specs[file_key] = list(module_payload.get("export_star_specs", []))
        self._register_non_python_node(rel_path, content, language, module_payload)

        for symbol_payload in self._extract_js_like_symbol_payloads(
            rel_path,
            content,
            language,
            module_name,
            file_imports_modules,
            file_imports_symbols,
        ):
            self._register_non_python_node(rel_path, content, language, symbol_payload)
