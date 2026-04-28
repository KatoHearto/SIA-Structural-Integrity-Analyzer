# ── SIA src/10_parser_other.py ── (god_mode_v3.py lines 1396–1455) ───────────
# Java, C#, Kotlin, PHP, Ruby file-level dispatch stubs

    def _parse_java_file(self, rel_path: str, content: str, language: str) -> None:
        module_payload = self._parse_java_module(rel_path, content, language)
        module_name = str(module_payload.get("module") or source_group(rel_path, language))
        package_name = str(module_payload.get("package_name", ""))
        file_imports_symbols = dict(module_payload.get("imports_symbols", {}))
        self._register_non_python_node(rel_path, content, language, module_payload)

        for symbol_payload in self._extract_java_symbol_payloads(
            rel_path,
            content,
            module_name,
            package_name,
            file_imports_symbols,
        ):
            self._register_non_python_node(rel_path, content, language, symbol_payload)

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

    def _parse_php_file(self, rel_path: str, content: str, language: str) -> None:
        module_payload = self._parse_php_module(rel_path, content, language)
        module_name = str(module_payload.get("module") or source_group(rel_path, language))
        package_name = str(module_payload.get("package_name", ""))
        file_imports_symbols = dict(module_payload.get("imports_symbols", {}))
        self._register_non_python_node(rel_path, content, language, module_payload)
        for symbol_payload in self._extract_php_symbol_payloads(
            rel_path, content, module_name, package_name, file_imports_symbols,
        ):
            self._register_non_python_node(rel_path, content, language, symbol_payload)

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
