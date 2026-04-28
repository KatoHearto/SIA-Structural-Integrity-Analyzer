# ── SIA src/06_parser_js.py ── (god_mode_v3.py lines 1456–2024) ──────────────

    def _parse_js_like_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        function_names = re.findall(r"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)\s*\(", content)
        class_names = re.findall(r"(?m)^\s*(?:export\s+)?class\s+([A-Za-z_]\w*)\b", content)
        arrow_names = re.findall(
            r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_]\w*)\s*=>",
            content,
        )
        type_names = re.findall(r"(?m)^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_]\w*)\b", content)
        declared_symbols = self._dedupe(function_names + class_names + arrow_names + type_names)[:20]

        raw_imports: Set[str] = set()
        imports_modules: Dict[str, str] = {}
        imports_symbols: Dict[str, str] = {}
        export_bindings: Dict[str, str] = {}
        export_star_specs: List[str] = []
        for lhs, spec in re.findall(r"(?m)^\s*import\s+(.+?)\s+from\s+['\"]([^'\"]+)['\"]", content):
            raw_imports.add(spec)
            self._parse_js_import_bindings(lhs, spec, imports_modules, imports_symbols)
        for spec in re.findall(r"(?m)^\s*import\s+['\"]([^'\"]+)['\"]", content):
            raw_imports.add(spec)
        for spec in re.findall(r"(?m)^\s*export\s+.+?\s+from\s+['\"]([^'\"]+)['\"]", content):
            raw_imports.add(spec)
        for alias, spec in re.findall(
            r"(?m)^\s*(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
            content,
        ):
            raw_imports.add(spec)
            imports_symbols[alias] = f"{spec}#default"
        for spec in re.findall(r"\brequire\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", content):
            raw_imports.add(spec)
        for spec in re.findall(r"\bimport\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", content):
            raw_imports.add(spec)
        for lhs, spec in re.findall(r"(?m)^\s*export\s+\{([^}]+)\}\s+from\s+['\"]([^'\"]+)['\"]", content):
            raw_imports.add(spec)
            for raw_item in lhs.split(","):
                item = raw_item.strip()
                if not item:
                    continue
                if " as " in item:
                    original, alias = [part.strip() for part in item.split(" as ", 1)]
                else:
                    original, alias = item, item
                export_bindings[alias] = f"{spec}#{original}"
        for alias, spec in re.findall(r"(?m)^\s*export\s+\*\s+as\s+([A-Za-z_$][\w$]*)\s+from\s+['\"]([^'\"]+)['\"]", content):
            raw_imports.add(spec)
            export_bindings[alias] = spec
        for spec in re.findall(r"(?m)^\s*export\s+\*\s+from\s+['\"]([^'\"]+)['\"]", content):
            raw_imports.add(spec)
            export_star_specs.append(spec)

        raw_bases: Set[str] = set(re.findall(r"\bclass\s+[A-Za-z_]\w*\s+extends\s+([A-Za-z_][\w$.]*)", content))
        return {
            "module": source_group(rel_path, language),
            "qualname": source_qualname(rel_path),
            "kind": "module",
            "imports_modules": imports_modules,
            "imports_symbols": imports_symbols,
            "declared_symbols": declared_symbols,
            "raw_imports": raw_imports,
            "raw_bases": raw_bases,
            "raw_string_refs": self._harvest_string_refs(content, exclude=raw_imports),
            "export_bindings": export_bindings,
            "export_star_specs": export_star_specs,
        }

    def _extract_js_like_symbol_payloads(
        self,
        rel_path: str,
        content: str,
        language: str,
        module_name: str,
        imports_modules: Dict[str, str],
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        depth_map = self._compute_js_like_brace_depths(content)
        payloads: List[Dict[str, object]] = []

        class_pattern = re.compile(r"(?m)^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)\b(?:\s+extends\s+([A-Za-z_$][\w$.]*))?")
        for match in class_pattern.finditer(content):
            if depth_map[match.start()] != 0:
                continue
            class_name = match.group(1)
            base_name = match.group(2)
            open_brace = content.find("{", match.end())
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(content, open_brace)
            if close_brace < 0:
                continue
            body = content[open_brace + 1:close_brace]
            member_types = self._extract_js_like_class_member_types(body)
            raw_calls = self._extract_js_like_top_level_calls(body)
            raw_imports = set(imports_modules.values()) | set(imports_symbols.values())
            payloads.append(
                {
                    "module": module_name,
                    "qualname": class_name,
                    "kind": "class",
                    "class_context": class_name,
                    "imports_modules": dict(imports_modules),
                    "imports_symbols": dict(imports_symbols),
                    "member_types": member_types,
                    "declared_symbols": [],
                    "raw_calls": raw_calls,
                    "raw_bases": {base_name} if base_name else set(),
                    "raw_string_refs": self._harvest_string_refs(body, exclude=raw_calls | raw_imports),
                    "lines": self._span_to_lines(content, match.start(), close_brace),
                }
            )
            payloads.extend(
                self._extract_js_like_method_payloads(
                    full_content=content,
                    class_body=body,
                    body_offset=open_brace + 1,
                    module_name=module_name,
                    class_name=class_name,
                    member_types=member_types,
                    imports_modules=imports_modules,
                    imports_symbols=imports_symbols,
                )
            )

        function_pattern = re.compile(
            r"(?m)^\s*(export\s+(?:default\s+)?)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)"
        )
        for match in function_pattern.finditer(content):
            if depth_map[match.start()] != 0:
                continue
            exported = bool(match.group(1))
            name = match.group(2)
            params = self._extract_js_callable_params(match.group(3))
            open_brace = content.find("{", match.end())
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(content, open_brace)
            if close_brace < 0:
                continue
            body = content[open_brace + 1:close_brace]
            raw_calls = self._extract_js_like_calls(body)
            raw_imports = set(imports_modules.values()) | set(imports_symbols.values())
            payloads.append(
                {
                    "module": module_name,
                    "qualname": name,
                    "kind": "function",
                    "imports_modules": dict(imports_modules),
                    "imports_symbols": dict(imports_symbols),
                    "declared_symbols": [],
                    "raw_calls": raw_calls,
                    "raw_bases": set(),
                    "raw_string_refs": self._harvest_string_refs(body, exclude=raw_calls | raw_imports),
                    "callable_params": params,
                    "exported": exported,
                    "lines": self._span_to_lines(content, match.start(), close_brace),
                }
            )

        arrow_pattern = re.compile(
            r"(?m)^\s*(export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\(([^)]*)\)|([A-Za-z_$][\w$]*))\s*=>"
        )
        for match in arrow_pattern.finditer(content):
            if depth_map[match.start()] != 0:
                continue
            exported = bool(match.group(1))
            name = match.group(2)
            params = self._extract_js_callable_params(match.group(3) or match.group(4) or "")
            idx = match.end()
            while idx < len(content) and content[idx].isspace():
                idx += 1
            if idx < len(content) and content[idx] == "{":
                close_brace = self._find_matching_brace(content, idx)
                if close_brace < 0:
                    continue
                body = content[idx + 1:close_brace]
                end_index = close_brace
            else:
                end_index = content.find("\n", idx)
                if end_index < 0:
                    end_index = len(content) - 1
                body = content[idx:end_index + 1]
            raw_calls = self._extract_js_like_calls(body)
            raw_imports = set(imports_modules.values()) | set(imports_symbols.values())
            payloads.append(
                {
                    "module": module_name,
                    "qualname": name,
                    "kind": "function",
                    "imports_modules": dict(imports_modules),
                    "imports_symbols": dict(imports_symbols),
                    "declared_symbols": [],
                    "raw_calls": raw_calls,
                    "raw_bases": set(),
                    "raw_string_refs": self._harvest_string_refs(body, exclude=raw_calls | raw_imports),
                    "callable_params": params,
                    "exported": exported,
                    "lines": self._span_to_lines(content, match.start(), end_index),
                }
            )

        return payloads

    def _extract_js_like_method_payloads(
        self,
        full_content: str,
        class_body: str,
        body_offset: int,
        module_name: str,
        class_name: str,
        member_types: Dict[str, str],
        imports_modules: Dict[str, str],
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        payloads: List[Dict[str, object]] = []
        depth_map = self._compute_js_like_brace_depths(class_body)
        seen: Set[Tuple[str, int, int]] = set()

        method_pattern = re.compile(
            r"(?m)^\s*(?:@[A-Za-z_$][\w$]*(?:\([^)]*\))?\s*)*"
            r"(?:(?:public|private|protected|static|async|abstract|readonly|override|get|set)\s+)*"
            r"([A-Za-z_$][\w$]*)\s*(?:<[^>{}]+>\s*)?\([^;{}=]*\)\s*(?::\s*[^({}=;]+)?\s*\{"
        )
        for match in method_pattern.finditer(class_body):
            if depth_map[match.start()] != 0:
                continue
            method_name = match.group(1)
            open_brace = class_body.find("{", match.end() - 1)
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(class_body, open_brace)
            if close_brace < 0:
                continue
            body = class_body[open_brace + 1:close_brace]
            start_index = body_offset + match.start()
            end_index = body_offset + close_brace
            marker = (method_name, start_index, end_index)
            if marker in seen:
                continue
            seen.add(marker)
            raw_calls = self._extract_js_like_calls(body)
            raw_imports = set(imports_modules.values()) | set(imports_symbols.values())
            payloads.append(
                {
                    "module": module_name,
                    "qualname": f"{class_name}.{method_name}",
                    "kind": "method",
                    "class_context": class_name,
                    "imports_modules": dict(imports_modules),
                    "imports_symbols": dict(imports_symbols),
                    "member_types": dict(member_types),
                    "declared_symbols": [],
                    "raw_calls": raw_calls,
                    "raw_bases": set(),
                    "raw_string_refs": self._harvest_string_refs(body, exclude=raw_calls | raw_imports),
                    "lines": self._span_to_lines(full_content, start_index, end_index),
                }
            )

        arrow_pattern = re.compile(
            r"(?m)^\s*(?:@[A-Za-z_$][\w$]*(?:\([^)]*\))?\s*)*"
            r"(?:(?:public|private|protected|static|readonly|override)\s+)*"
            r"([A-Za-z_$][\w$]*)\s*(?::\s*[^=;]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
        )
        for match in arrow_pattern.finditer(class_body):
            if depth_map[match.start()] != 0:
                continue
            method_name = match.group(1)
            idx = match.end()
            while idx < len(class_body) and class_body[idx].isspace():
                idx += 1
            if idx < len(class_body) and class_body[idx] == "{":
                close_brace = self._find_matching_brace(class_body, idx)
                if close_brace < 0:
                    continue
                body = class_body[idx + 1:close_brace]
                end_index = body_offset + close_brace
            else:
                close_delims = [pos for pos in (class_body.find("\n", idx), class_body.find(";", idx)) if pos >= 0]
                close_index = min(close_delims) if close_delims else len(class_body) - 1
                body = class_body[idx:close_index + 1]
                end_index = body_offset + close_index
            start_index = body_offset + match.start()
            marker = (method_name, start_index, end_index)
            if marker in seen:
                continue
            seen.add(marker)
            raw_calls = self._extract_js_like_calls(body)
            raw_imports = set(imports_modules.values()) | set(imports_symbols.values())
            payloads.append(
                {
                    "module": module_name,
                    "qualname": f"{class_name}.{method_name}",
                    "kind": "method",
                    "class_context": class_name,
                    "imports_modules": dict(imports_modules),
                    "imports_symbols": dict(imports_symbols),
                    "member_types": dict(member_types),
                    "declared_symbols": [],
                    "raw_calls": raw_calls,
                    "raw_bases": set(),
                    "raw_string_refs": self._harvest_string_refs(body, exclude=raw_calls | raw_imports),
                    "lines": self._span_to_lines(full_content, start_index, end_index),
                }
            )

        return payloads

    def _clean_js_like_type(self, raw_type: str, initializer: str = "") -> str:
        cleaned = raw_type.strip()
        if not cleaned:
            match = re.search(r"\bnew\s+([A-Za-z_$][\w$.]*)\s*\(", initializer)
            cleaned = match.group(1) if match else ""
        cleaned = re.sub(r"<.*?>", "", cleaned)
        cleaned = cleaned.replace("[]", " ")
        cleaned = cleaned.replace("readonly", " ")
        for splitter in ("|", "&"):
            if splitter in cleaned:
                cleaned = cleaned.split(splitter, 1)[0]
        tokens = re.findall(r"[A-Za-z_$][\w$]*", cleaned)
        if not tokens:
            return ""
        candidate = tokens[-1]
        if candidate in JS_NON_SYMBOL_TYPES:
            return ""
        return candidate

    def _extract_js_like_param_types(self, params_spec: str) -> Dict[str, str]:
        params: Dict[str, str] = {}
        for raw_param in params_spec.split(","):
            param = raw_param.strip()
            if not param:
                continue
            param = re.sub(r"^\.\.\.", "", param).strip()
            parts = re.match(
                r"(?:(?:public|private|protected|readonly)\s+)*([A-Za-z_$][\w$]*)\s*(?::\s*([^=]+))?",
                param,
            )
            if not parts:
                continue
            variable_name = parts.group(1)
            variable_type = self._clean_js_like_type(parts.group(2) or "")
            if variable_type:
                params[variable_name] = variable_type
        return params

    def _extract_js_like_class_member_types(self, class_body: str) -> Dict[str, str]:
        member_types: Dict[str, str] = {}
        depth_map = self._compute_js_like_brace_depths(class_body)

        field_pattern = re.compile(
            r"(?m)^\s*(?:(?:public|private|protected|readonly|static|declare|override)\s+)*"
            r"([A-Za-z_$][\w$]*)\s*(?::\s*([^=;]+))?\s*(?:=\s*([^;]+))?;"
        )
        for match in field_pattern.finditer(class_body):
            if depth_map[match.start()] != 0:
                continue
            member_name = match.group(1)
            member_type = self._clean_js_like_type(match.group(2) or "", match.group(3) or "")
            if member_type:
                member_types[member_name] = member_type

        ctor_pattern = re.compile(r"(?m)^\s*constructor\s*\(([^)]*)\)\s*\{")
        for match in ctor_pattern.finditer(class_body):
            if depth_map[match.start()] != 0:
                continue
            ctor_param_types = self._extract_js_like_param_types(match.group(1) or "")
            for raw_param in (match.group(1) or "").split(","):
                param = raw_param.strip()
                property_match = re.match(
                    r"(?:(?:public|private|protected|readonly)\s+)+([A-Za-z_$][\w$]*)\s*(?::\s*([^=]+))?",
                    param,
                )
                if not property_match:
                    continue
                property_type = self._clean_js_like_type(property_match.group(2) or "")
                if property_type:
                    member_types[property_match.group(1)] = property_type

            open_brace = class_body.find("{", match.end() - 1)
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(class_body, open_brace)
            if close_brace < 0:
                continue
            body = class_body[open_brace + 1:close_brace]
            for field_name, type_name in re.findall(r"\bthis\.([A-Za-z_$][\w$]*)\s*=\s*new\s+([A-Za-z_$][\w$.]*)\s*\(", body):
                cleaned = self._clean_js_like_type(type_name)
                if cleaned:
                    member_types[field_name] = cleaned
            for field_name, source_name in re.findall(r"\bthis\.([A-Za-z_$][\w$]*)\s*=\s*([A-Za-z_$][\w$]*)\s*;", body):
                if source_name in ctor_param_types:
                    member_types[field_name] = ctor_param_types[source_name]

        return member_types

    def _compute_js_like_brace_depths(self, text: str) -> List[int]:
        depths = [0] * (len(text) + 1)
        depth = 0
        quote: Optional[str] = None
        line_comment = False
        block_comment = False
        escaped = False
        index = 0
        while index < len(text):
            depths[index] = depth
            char = text[index]
            nxt = text[index + 1] if index + 1 < len(text) else ""

            if line_comment:
                if char == "\n":
                    line_comment = False
            elif block_comment:
                if char == "*" and nxt == "/":
                    block_comment = False
                    index += 1
            elif quote:
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
                elif char in {"'", '"', "`"}:
                    quote = char
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth = max(0, depth - 1)
            index += 1

        depths[len(text)] = depth
        return depths

    def _find_matching_brace(self, text: str, open_index: int) -> int:
        depth = 0
        quote: Optional[str] = None
        line_comment = False
        block_comment = False
        escaped = False
        index = open_index
        while index < len(text):
            char = text[index]
            nxt = text[index + 1] if index + 1 < len(text) else ""

            if line_comment:
                if char == "\n":
                    line_comment = False
            elif block_comment:
                if char == "*" and nxt == "/":
                    block_comment = False
                    index += 1
            elif quote:
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
                elif char in {"'", '"', "`"}:
                    quote = char
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return index
            index += 1
        return -1

    def _span_to_lines(self, text: str, start_index: int, end_index: int) -> List[int]:
        start_line = text.count("\n", 0, start_index) + 1
        end_line = text.count("\n", 0, end_index + 1) + 1
        return [start_line, end_line]

    def _extract_js_callable_params(self, raw_params: str) -> List[str]:
        params: List[str] = []
        for part in raw_params.split(","):
            token = part.strip()
            if not token:
                continue
            token = token.split("=", 1)[0].strip()
            if token.startswith("..."):
                token = token[3:].strip()
            token = token.split(":", 1)[0].strip().rstrip("?")
            if re.match(r"^[A-Za-z_$][\w$]*$", token):
                params.append(token)
        return self._dedupe(params)

    def _extract_js_like_top_level_calls(self, fragment: str) -> Set[str]:
        depth_map = self._compute_js_like_brace_depths(fragment)
        filtered = "".join(char if depth_map[index] == 0 else " " for index, char in enumerate(fragment))
        return self._extract_js_like_calls(filtered)

    def _extract_js_like_calls(self, fragment: str) -> Set[str]:
        cleaned = re.sub(r"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+[A-Za-z_$][\w$]*\s*\([^)]*\)\s*\{", "", fragment)
        cleaned = re.sub(r"(?m)^\s*(?:public|private|protected|static|async|get|set|\s)*[A-Za-z_$][\w$]*\s*\([^)]*\)\s*\{", "", cleaned)
        cleaned = re.sub(
            r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{?",
            "",
            cleaned,
        )

        calls: Set[str] = set()
        for match in re.finditer(r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*\(", cleaned):
            name = match.group(1)
            if name in JS_CALL_KEYWORDS:
                continue
            calls.add(name)
        for match in re.finditer(r"\bnew\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*\(", cleaned):
            calls.add(match.group(1))
        for match in re.finditer(r"<([A-Z][A-Za-z0-9_$]*)\b", cleaned):
            calls.add(match.group(1))
        return calls

    @staticmethod
    def _harvest_string_refs(body: str, exclude: Optional[Set[str]] = None) -> Set[str]:
        """Return dotted-path string literals from body that look like importable paths."""
        found: Set[str] = set()
        for match in re.finditer(r'["\']([A-Za-z_]\w*(?:\.[A-Za-z_]\w*){1,})["\']', body):
            candidate = match.group(1)
            if len(candidate.split(".")) > 8:
                continue
            found.add(candidate)
        if exclude:
            found -= exclude
        return found

    def _parse_js_import_bindings(
        self,
        lhs: str,
        spec: str,
        imports_modules: Dict[str, str],
        imports_symbols: Dict[str, str],
    ) -> None:
        lhs = lhs.strip()
        if not lhs:
            return
        default_match = re.match(r"^([A-Za-z_$][\w$]*)\s*(?:,|$)", lhs)
        if default_match and not lhs.startswith("{") and not lhs.startswith("*"):
            imports_symbols[default_match.group(1)] = f"{spec}#default"
        namespace_match = re.search(r"\*\s+as\s+([A-Za-z_$][\w$]*)", lhs)
        if namespace_match:
            imports_modules[namespace_match.group(1)] = spec
        named_match = re.search(r"\{([^}]+)\}", lhs)
        if not named_match:
            return
        for raw_item in named_match.group(1).split(","):
            item = raw_item.strip()
            if not item:
                continue
            if " as " in item:
                original, alias = [part.strip() for part in item.split(" as ", 1)]
                imports_symbols[alias] = f"{spec}#{original}"
            else:
                imports_symbols[item] = f"{spec}#{item}"
