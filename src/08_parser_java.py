# ── SIA src/08_parser_java.py ── (god_mode_v3.py lines 2059–3159) ────────────
# Contains: Java, C#, Kotlin, PHP, Ruby module parsers + symbol extractors

    def _parse_java_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        package_match = re.search(r"(?m)^\s*package\s+([A-Za-z0-9_.]+)\s*;", content)
        package_name = package_match.group(1) if package_match else ""
        types = re.findall(r"(?m)^\s*(?:public\s+)?(?:class|interface|enum|record)\s+([A-Za-z_]\w*)\b", content)
        methods = [
            name
            for name in re.findall(
                r"(?m)^\s*(?:public|protected|private)?\s*(?:static\s+)?[A-Za-z0-9_<>\[\], ?]+\s+([A-Za-z_]\w*)\s*\(",
                content,
            )
            if name not in {"if", "for", "while", "switch", "catch", "return", "new"}
        ]
        raw_imports: Set[str] = set()
        imports_symbols: Dict[str, str] = {}
        for spec in re.findall(r"(?m)^\s*import\s+(?:static\s+)?([A-Za-z0-9_.*]+)\s*;", content):
            raw_imports.add(spec)
            if not spec.endswith(".*"):
                imports_symbols[spec.rsplit(".", 1)[-1]] = spec

        raw_bases: Set[str] = set()
        for base in re.findall(
            r"\b(?:class|record)\s+[A-Za-z_]\w*(?:\s*<[^>{}]+>)?\s+extends\s+([A-Za-z0-9_$.<>]+)",
            content,
        ):
            raw_bases.add(re.sub(r"<.*?>", "", base).strip())
        for match in re.findall(
            r"\b(?:class|record)\s+[A-Za-z_]\w*(?:\s*<[^>{}]+>)?\s+implements\s+([A-Za-z0-9_$.<>,\s]+)",
            content,
        ):
            for raw_item in self._split_java_csv(match):
                item = re.sub(r"<.*?>", "", raw_item).strip()
                if item:
                    raw_bases.add(item)
        for match in re.findall(
            r"\binterface\s+[A-Za-z_]\w*(?:\s*<[^>{}]+>)?\s+extends\s+([A-Za-z0-9_$.<>,\s]+)",
            content,
        ):
            for raw_item in self._split_java_csv(match):
                item = re.sub(r"<.*?>", "", raw_item).strip()
                if item:
                    raw_bases.add(item)

        return {
            "module": source_group(rel_path, language, package_name),
            "qualname": source_qualname(rel_path),
            "kind": "module",
            "imports_modules": {},
            "imports_symbols": imports_symbols,
            "package_name": package_name,
            "declared_symbols": self._dedupe(types + methods)[:20],
            "raw_calls": set(),
            "raw_imports": raw_imports,
            "raw_bases": raw_bases,
            "raw_string_refs": self._harvest_string_refs(content, exclude=raw_imports),
        }

    def _parse_csharp_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        ns_match = re.search(r"(?m)^namespace\s+([\w.]+)\s*;", content)
        if not ns_match:
            ns_match = re.search(r"(?m)^namespace\s+([\w.]+)\s*\{", content)
        namespace = ns_match.group(1) if ns_match else ""

        raw_imports: Set[str] = set(
            re.findall(r"(?m)^\s*using\s+(?:static\s+)?(?:\w+\s*=\s*)?([\w.]+)\s*;", content)
        )

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
            "raw_string_refs": self._harvest_string_refs(content, exclude=raw_imports),
        }

    def _parse_kotlin_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        pkg_match = re.search(r"(?m)^\s*package\s+([\w.]+)", content)
        package_name = pkg_match.group(1).strip() if pkg_match else ""

        raw_imports: Set[str] = set(
            re.findall(r"(?m)^\s*import\s+([\w.*]+)", content)
        )

        declared_symbols = re.findall(
            r"(?m)^\s*(?:(?:public|private|protected|internal|open|abstract|sealed|data|"
            r"value|inline|companion|inner|override|suspend)\s+)*"
            r"(?:class|interface|object|enum\s+class|fun)\s+([A-Za-z_]\w*)\b",
            content,
        )[:20]

        raw_bases: Set[str] = set()
        for tail in re.findall(
            r"(?:class|object)\s+\w+(?:\s*<[^>]*>)?(?:\s*\([^)]*\))?\s*:\s*([A-Za-z_][\w(),\s<>?]*?)\s*(?:\{|$)",
            content,
        ):
            for part in re.split(r",\s*", tail):
                part = re.sub(r"<.*?>|\(.*?\)", "", part).strip()
                if part and re.match(r"[A-Za-z_]\w*", part):
                    raw_bases.add(part)

        return {
            "module": source_group(rel_path, language, package_name),
            "qualname": source_qualname(rel_path),
            "kind": "module",
            "package_name": package_name,
            "imports_modules": {},
            "imports_symbols": {},
            "declared_symbols": declared_symbols,
            "raw_imports": raw_imports,
            "raw_bases": raw_bases,
            "raw_string_refs": self._harvest_string_refs(content, exclude=raw_imports),
        }

    def _parse_php_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        ns_match = re.search(r"(?m)^\s*namespace\s+([\w\\]+)\s*[;{]", content)
        package_name = ns_match.group(1).replace("\\", ".") if ns_match else ""

        raw_imports: Set[str] = set(
            m.replace("\\", ".")
            for m in re.findall(
                r"(?m)^\s*use\s+(?:function\s+|const\s+)?([\w\\]+)(?:\s+as\s+\w+)?\s*;",
                content,
            )
        )

        declared_symbols = re.findall(
            r"(?m)^\s*(?:(?:abstract|final|readonly)\s+)*"
            r"(?:class|interface|trait|enum)\s+([A-Za-z_]\w*)\b",
            content,
        )[:20]

        raw_bases: Set[str] = set()
        for extend_m in re.findall(r"\bextends\s+([\w\\]+)", content):
            raw_bases.add(extend_m.replace("\\", ".").split(".")[-1])
        for impl_m in re.findall(r"\bimplements\s+([\w\\,\s]+?)(?:\{|$)", content):
            for part in re.split(r",\s*", impl_m.strip()):
                clean = part.strip().replace("\\", ".").split(".")[-1]
                if clean:
                    raw_bases.add(clean)

        return {
            "module": source_group(rel_path, language, package_name),
            "qualname": source_qualname(rel_path),
            "kind": "module",
            "package_name": package_name,
            "imports_modules": {},
            "imports_symbols": {},
            "declared_symbols": declared_symbols,
            "raw_imports": raw_imports,
            "raw_bases": raw_bases,
            "raw_string_refs": self._harvest_string_refs(content, exclude=raw_imports),
        }

    def _parse_ruby_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        raw_imports: Set[str] = set()
        for m in re.findall(
            r"(?m)^\s*require(?:_relative)?\s+['\"]([^'\"]+)['\"]", content
        ):
            raw_imports.add(m.rsplit("/", 1)[-1].replace("-", "_"))

        declared_symbols = re.findall(
            r"(?m)^\s*(?:class|module)\s+([A-Z]\w*(?:::[A-Z]\w*)*)", content
        )[:20]

        raw_bases: Set[str] = set()
        for base in re.findall(r"\bclass\s+\w+\s*<\s*([A-Z]\w*(?:::[A-Z]\w*)*)", content):
            raw_bases.add(base.split("::")[-1])

        pkg_match = re.search(r"(?m)^\s*module\s+([A-Z]\w*(?:::[A-Z]\w*)*)", content)
        package_name = pkg_match.group(1).replace("::", ".") if pkg_match else ""

        return {
            "module": source_group(rel_path, language, package_name),
            "qualname": source_qualname(rel_path),
            "kind": "module",
            "package_name": package_name,
            "imports_modules": {},
            "imports_symbols": {},
            "declared_symbols": declared_symbols,
            "raw_imports": raw_imports,
            "raw_bases": raw_bases,
            "raw_string_refs": self._harvest_string_refs(content, exclude=raw_imports),
        }

    def _extract_java_symbol_payloads(
        self,
        rel_path: str,
        content: str,
        module_name: str,
        package_name: str,
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        payloads: List[Dict[str, object]] = []
        depth_map = self._compute_js_like_brace_depths(content)
        type_pattern = re.compile(
            r"(?m)^\s*(?:public|protected|private|abstract|final|static\s+)*\s*(class|interface|enum|record)\s+([A-Za-z_]\w*)\b([^{]*)\{"
        )

        for match in type_pattern.finditer(content):
            if depth_map[match.start()] != 0:
                continue
            type_kind = match.group(1)
            type_name = match.group(2)
            tail = match.group(3) or ""
            open_brace = content.find("{", match.end() - 1)
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(content, open_brace)
            if close_brace < 0:
                continue

            raw_bases: Set[str] = set()
            extends_match = re.search(r"\bextends\s+([A-Za-z0-9_$.<>]+)", tail)
            if extends_match:
                raw_bases.add(re.sub(r"<.*?>", "", extends_match.group(1)).strip())
            implements_match = re.search(r"\bimplements\s+([A-Za-z0-9_$.<>,\s]+)", tail)
            if implements_match:
                for raw_item in self._split_java_csv(implements_match.group(1)):
                    item = re.sub(r"<.*?>", "", raw_item).strip()
                    if item:
                        raw_bases.add(item)

            body = content[open_brace + 1:close_brace]
            field_types, field_qualifiers = self._extract_java_declared_members(body, top_level_only=True)
            constructor_field_qualifiers = self._extract_java_constructor_field_qualifiers(body, type_name, field_types)
            for field_name, qualifier in constructor_field_qualifiers.items():
                field_qualifiers.setdefault(field_name, qualifier)
            annotation_block = self._extract_java_leading_annotation_block(content, match.start())
            annotations, bean_name, di_primary = self._extract_java_component_metadata(type_name, annotation_block)
            raw_calls = self._extract_java_top_level_calls(body)
            raw_imports = set(imports_symbols.values())
            payloads.append(
                {
                    "module": module_name,
                    "qualname": type_name,
                    "kind": "class" if type_kind in {"class", "record"} else type_kind,
                    "class_context": type_name,
                    "imports_modules": {},
                    "imports_symbols": dict(imports_symbols),
                    "member_types": field_types,
                    "member_qualifiers": field_qualifiers,
                    "package_name": package_name,
                    "declared_symbols": [],
                    "annotations": annotations,
                    "bean_name": bean_name,
                    "is_abstract": type_kind == "class" and bool(re.search(r"\babstract\b", match.group(0))),
                    "di_primary": di_primary,
                    "raw_calls": raw_calls,
                    "raw_bases": raw_bases,
                    "raw_string_refs": self._harvest_string_refs(body, exclude=raw_calls | raw_imports),
                    "lines": self._span_to_lines(content, match.start(), close_brace),
                }
            )

            for method_payload in self._extract_java_method_payloads(
                content,
                body,
                body_offset=open_brace + 1,
                module_name=module_name,
                package_name=package_name,
                class_name=type_name,
                field_types=field_types,
                field_qualifiers=field_qualifiers,
                imports_symbols=imports_symbols,
            ):
                payloads.append(method_payload)

        return payloads

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
            if depth_map[type_match.start()] > 1:
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
                item.strip()
                for item in re.findall(r"\[([A-Za-z_]\w*(?:\([^)]*\))?)\]", annotation_block)
            ]

            payloads.append(
                {
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
                    "raw_string_refs": self._harvest_string_refs(body, exclude=set(imports_symbols.values())),
                    "lines": self._span_to_lines(content, type_match.start(), close_brace),
                }
            )

            body_depth_map = self._compute_js_like_brace_depths(body)
            for method_match in method_pattern.finditer(body):
                method_name = method_match.group(1)
                if method_name in {"if", "for", "while", "foreach", "switch", "catch", "using", "lock", "return", "await", "new", "throw", "var", "get", "set"}:
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
                    item.strip()
                    for item in re.findall(r"\[([A-Za-z_]\w*(?:\([^)]*\))?)\]", m_annotation_block)
                ]
                abs_start = open_brace + 1 + method_match.start()
                abs_end = open_brace + 1 + m_close
                payloads.append(
                    {
                        "module": module_name,
                        "qualname": f"{type_name}.{method_name}",
                        "kind": "method",
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
                        "raw_string_refs": self._harvest_string_refs(method_body, exclude=raw_calls | set(imports_symbols.values())),
                        "lines": self._span_to_lines(content, abs_start, abs_end),
                    }
                )

        return payloads

    def _extract_kotlin_symbol_payloads(
        self,
        rel_path: str,
        content: str,
        module_name: str,
        package_name: str,
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        payloads: List[Dict[str, object]] = []
        type_ranges: List[Tuple[int, int]] = []
        depth_map = self._compute_js_like_brace_depths(content)

        type_pattern = re.compile(
            r"(?m)^\s*(?:(?:public|private|protected|internal|open|abstract|sealed|data|"
            r"value|inline|companion|inner|annotation)\s+)*"
            r"(class|interface|object|enum\s+class)\s+([A-Za-z_]\w*)\b([^{]*)\{"
        )
        method_pattern = re.compile(
            r"(?m)^\s*(?:(?:public|private|protected|internal|open|override|abstract|"
            r"suspend|inline|operator|infix|tailrec|external|actual|expect)\s+)*"
            r"fun\s+(?:<[^>]*>\s*)?(?:[\w.]+\s*\.\s*)?([A-Za-z_]\w*)\s*\([^)]*\)"
            r"(?:\s*:\s*[\w<>?,.\s]+)?\s*(?:=\s*[^\n]+|(?:where\s+[\w\s:,<>]+\s*)?\{)"
        )

        for type_match in type_pattern.finditer(content):
            if depth_map[type_match.start()] > 1:
                continue
            type_kind_raw = type_match.group(1)
            type_name = type_match.group(2)
            tail = type_match.group(3) or ""

            open_brace = content.find("{", type_match.end() - 1)
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(content, open_brace)
            if close_brace < 0:
                continue
            type_ranges.append((type_match.start(), close_brace))

            raw_bases: Set[str] = set()
            colon_match = re.search(r":\s*([\w(),\s<>?]+?)(?:\{|where\b)", tail + " {")
            if colon_match:
                for part in re.split(r",\s*", colon_match.group(1)):
                    part = re.sub(r"<.*?>|\(.*?\)", "", part).strip()
                    if part and re.match(r"[A-Za-z_]\w*", part):
                        raw_bases.add(part)

            body = content[open_brace + 1:close_brace]
            type_kind = "class" if "class" in type_kind_raw else type_kind_raw

            payloads.append(
                {
                    "module": module_name,
                    "qualname": type_name,
                    "kind": type_kind,
                    "class_context": type_name,
                    "package_name": package_name,
                    "imports_symbols": dict(imports_symbols),
                    "member_types": {},
                    "member_qualifiers": {},
                    "declared_symbols": [],
                    "annotations": [],
                    "bean_name": "",
                    "is_abstract": bool(re.search(r"\babstract\b", type_match.group(0))),
                    "di_primary": False,
                    "raw_calls": set(),
                    "raw_bases": raw_bases,
                    "raw_string_refs": self._harvest_string_refs(body, exclude=set(imports_symbols.values())),
                    "lines": self._span_to_lines(content, type_match.start(), close_brace),
                }
            )

            body_depth_map = self._compute_js_like_brace_depths(body)
            body_offset = open_brace + 1
            for method_match in method_pattern.finditer(body):
                method_name = method_match.group(1)
                if method_name in {"if", "for", "while", "when", "catch", "try", "return", "throw", "object", "companion", "init"}:
                    continue
                if body_depth_map[method_match.start()] > 1:
                    continue
                abs_start = body_offset + method_match.start()
                method_open = body.find("{", method_match.start())
                if method_open < 0:
                    method_close = method_match.end()
                else:
                    method_close = self._find_matching_brace(body, method_open)
                abs_end = body_offset + (method_close if method_close >= 0 else method_match.end())
                method_body = (
                    body[method_open + 1:method_close]
                    if method_open >= 0 and method_close >= 0
                    else body[method_match.start():method_match.end()]
                )
                payloads.append(
                    {
                        "module": module_name,
                        "qualname": f"{type_name}.{method_name}",
                        "kind": "function",
                        "class_context": type_name,
                        "package_name": package_name,
                        "imports_symbols": dict(imports_symbols),
                        "member_types": {},
                        "member_qualifiers": {},
                        "declared_symbols": [],
                        "annotations": [],
                        "bean_name": "",
                        "is_abstract": False,
                        "di_primary": False,
                        "raw_calls": set(),
                        "raw_bases": set(),
                        "raw_string_refs": self._harvest_string_refs(method_body, exclude=set(imports_symbols.values())),
                        "lines": self._span_to_lines(content, abs_start, abs_end),
                    }
                )

        for fun_match in method_pattern.finditer(content):
            if depth_map[fun_match.start()] > 1:
                continue
            if any(start <= fun_match.start() <= end for start, end in type_ranges):
                continue
            fun_name = fun_match.group(1)
            if fun_name in {"if", "for", "while", "when", "catch", "try", "return", "throw", "object", "companion", "init"}:
                continue
            fun_open = content.find("{", fun_match.start())
            if fun_open < 0:
                fun_end = fun_match.end()
                fun_body = content[fun_match.start():fun_match.end()]
            else:
                fun_end = self._find_matching_brace(content, fun_open)
                fun_body = content[fun_open + 1:fun_end] if fun_end >= 0 else content[fun_match.start():fun_match.end()]
            payloads.append(
                {
                    "module": module_name,
                    "qualname": fun_name,
                    "kind": "function",
                    "class_context": "",
                    "package_name": package_name,
                    "imports_symbols": dict(imports_symbols),
                    "member_types": {},
                    "member_qualifiers": {},
                    "declared_symbols": [],
                    "annotations": [],
                    "bean_name": "",
                    "is_abstract": False,
                    "di_primary": False,
                    "raw_calls": set(),
                    "raw_bases": set(),
                    "raw_string_refs": self._harvest_string_refs(fun_body, exclude=set(imports_symbols.values())),
                    "lines": self._span_to_lines(content, fun_match.start(), fun_end if fun_end >= 0 else fun_match.end()),
                }
            )

        return payloads

    def _extract_php_symbol_payloads(
        self,
        rel_path: str,
        content: str,
        module_name: str,
        package_name: str,
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        payloads: List[Dict[str, object]] = []
        depth_map = self._compute_js_like_brace_depths(content)

        type_pattern = re.compile(
            r"(?m)^\s*(?:(?:abstract|final|readonly)\s+)*"
            r"(class|interface|trait|enum)\s+([A-Za-z_]\w*)\b([^{]*)\{"
        )
        method_pattern = re.compile(
            r"(?m)^\s*(?:(?:public|protected|private|static|abstract|final)\s+)*"
            r"function\s+([A-Za-z_]\w*)\s*\([^)]*\)\s*(?::\s*[\w?\\|]+\s*)?\{"
        )

        for type_match in type_pattern.finditer(content):
            if depth_map[type_match.start()] > 1:
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
            for m in re.findall(r"\bextends\s+([\w\\]+)", tail):
                raw_bases.add(m.replace("\\", ".").split(".")[-1])
            for m in re.findall(r"\bimplements\s+([\w\\,\s]+?)(?:\{|$)", tail + " {"):
                for part in re.split(r",\s*", m.strip()):
                    clean = part.strip().replace("\\", ".").split(".")[-1]
                    if clean:
                        raw_bases.add(clean)

            body = content[open_brace + 1:close_brace]
            payloads.append({
                "module": module_name,
                "qualname": type_name,
                "kind": "class" if type_kind in {"class", "trait"} else type_kind,
                "class_context": type_name,
                "package_name": package_name,
                "imports_symbols": dict(imports_symbols),
                "member_types": {},
                "member_qualifiers": {},
                "declared_symbols": [],
                "annotations": [],
                "bean_name": "",
                "is_abstract": bool(re.search(r"\babstract\b", type_match.group(0))),
                "di_primary": False,
                "raw_calls": set(),
                "raw_bases": raw_bases,
                "raw_string_refs": self._harvest_string_refs(body, exclude=set(imports_symbols.values())),
                "lines": self._span_to_lines(content, type_match.start(), close_brace),
            })

            body_depth_map = self._compute_js_like_brace_depths(body)
            body_offset = open_brace + 1
            for method_match in method_pattern.finditer(body):
                method_name = method_match.group(1)
                if method_name in {"if", "for", "foreach", "while", "switch", "catch",
                                   "match", "try", "return", "throw"}:
                    continue
                if body_depth_map[method_match.start()] > 1:
                    continue
                abs_start = body_offset + method_match.start()
                m_open = body.find("{", method_match.start())
                if m_open < 0:
                    m_close = method_match.end()
                else:
                    m_close = self._find_matching_brace(body, m_open)
                abs_end = body_offset + (m_close if m_close >= 0 else method_match.end())
                method_body = (
                    body[m_open + 1:m_close]
                    if m_open >= 0 and m_close >= 0
                    else body[method_match.start():method_match.end()]
                )
                payloads.append({
                    "module": module_name,
                    "qualname": f"{type_name}.{method_name}",
                    "kind": "function",
                    "class_context": type_name,
                    "package_name": package_name,
                    "imports_symbols": dict(imports_symbols),
                    "member_types": {},
                    "member_qualifiers": {},
                    "declared_symbols": [],
                    "annotations": [],
                    "bean_name": "",
                    "is_abstract": False,
                    "di_primary": False,
                    "raw_calls": set(),
                    "raw_bases": set(),
                    "raw_string_refs": self._harvest_string_refs(method_body, exclude=set(imports_symbols.values())),
                    "lines": self._span_to_lines(content, abs_start, abs_end),
                })

        return payloads

    def _ruby_find_end(self, content: str, start_index: int) -> int:
        """Return the character index just after the closing Ruby 'end'."""
        _OPEN = re.compile(
            r"\b(?:class|module|def|do|begin|if|unless|case|while|until|for)\b"
        )
        _CLOSE = re.compile(r"\bend\b")
        depth = 1
        pos = start_index + 1
        while pos < len(content):
            om = _OPEN.search(content, pos)
            em = _CLOSE.search(content, pos)
            if om is None and em is None:
                break
            if em is None or (om is not None and om.start() < em.start()):
                depth += 1
                pos = om.end()
            else:
                depth -= 1
                if depth == 0:
                    return em.end()
                pos = em.end()
        return len(content)

    def _extract_ruby_symbol_payloads(
        self,
        rel_path: str,
        content: str,
        module_name: str,
        package_name: str,
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        payloads: List[Dict[str, object]] = []

        type_pattern = re.compile(
            r"(?m)^(\s*)(?:class|module)\s+([A-Z]\w*(?:::[A-Z]\w*)*)\b([^\n]*)"
        )
        method_pattern = re.compile(
            r"(?m)^(\s*)def\s+(self\.)?([a-z_]\w*[?!]?)\s*(?:\([^)]*\))?"
        )

        for type_match in type_pattern.finditer(content):
            indent = len(type_match.group(1))
            if indent > 0:
                continue
            type_name = type_match.group(2).split("::")[-1]
            tail = type_match.group(3) or ""
            raw_bases: Set[str] = set()
            base_m = re.search(r"<\s*([A-Z]\w*(?:::[A-Z]\w*)*)", tail)
            if base_m:
                raw_bases.add(base_m.group(1).split("::")[-1])

            block_end = self._ruby_find_end(content, type_match.start())
            body = content[type_match.end():block_end]
            nested_type_ranges = [
                (nested_match.start(), self._ruby_find_end(body, nested_match.start()))
                for nested_match in type_pattern.finditer(body)
            ]

            payloads.append({
                "module": module_name,
                "qualname": type_name,
                "kind": "class",
                "class_context": type_name,
                "package_name": package_name,
                "imports_symbols": dict(imports_symbols),
                "member_types": {},
                "member_qualifiers": {},
                "declared_symbols": [],
                "annotations": [],
                "bean_name": "",
                "is_abstract": False,
                "di_primary": False,
                "raw_calls": set(),
                "raw_bases": raw_bases,
                "raw_string_refs": self._harvest_string_refs(body, exclude=set(imports_symbols.values())),
                "lines": self._span_to_lines(content, type_match.start(), block_end),
            })

            for method_match in method_pattern.finditer(body):
                if any(start <= method_match.start() < end for start, end in nested_type_ranges):
                    continue
                method_indent = len(method_match.group(1))
                if method_indent > 4:
                    continue
                is_class_method = bool(method_match.group(2))
                method_name = method_match.group(3)
                if method_name in {"initialize"}:
                    qualname = f"{type_name}.initialize"
                elif is_class_method:
                    qualname = f"{type_name}.{method_name}"
                else:
                    qualname = f"{type_name}#{method_name}"
                abs_start = type_match.end() + method_match.start()
                mend = self._ruby_find_end(body, method_match.start())
                abs_end = type_match.end() + mend
                method_body = body[method_match.end():mend]
                payloads.append({
                    "module": module_name,
                    "qualname": qualname,
                    "kind": "function",
                    "class_context": type_name,
                    "package_name": package_name,
                    "imports_symbols": dict(imports_symbols),
                    "member_types": {},
                    "member_qualifiers": {},
                    "declared_symbols": [],
                    "annotations": [],
                    "bean_name": "",
                    "is_abstract": False,
                    "di_primary": False,
                    "raw_calls": set(),
                    "raw_bases": set(),
                    "raw_string_refs": self._harvest_string_refs(method_body, exclude=set(imports_symbols.values())),
                    "lines": self._span_to_lines(content, abs_start, abs_end),
                })

        for method_match in method_pattern.finditer(content):
            if len(method_match.group(1)) > 0:
                continue
            method_name = method_match.group(3)
            mend = self._ruby_find_end(content, method_match.start())
            method_body = content[method_match.end():mend]
            payloads.append({
                "module": module_name,
                "qualname": method_name,
                "kind": "function",
                "class_context": "",
                "package_name": package_name,
                "imports_symbols": dict(imports_symbols),
                "member_types": {},
                "member_qualifiers": {},
                "declared_symbols": [],
                "annotations": [],
                "bean_name": "",
                "is_abstract": False,
                "di_primary": False,
                "raw_calls": set(),
                "raw_bases": set(),
                "raw_string_refs": self._harvest_string_refs(method_body, exclude=set(imports_symbols.values())),
                "lines": self._span_to_lines(content, method_match.start(), mend),
            })

        return payloads

    def _extract_java_method_payloads(
        self,
        full_content: str,
        class_body: str,
        body_offset: int,
        module_name: str,
        package_name: str,
        class_name: str,
        field_types: Dict[str, str],
        field_qualifiers: Dict[str, str],
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        payloads: List[Dict[str, object]] = []
        depth_map = self._compute_js_like_brace_depths(class_body)
        method_pattern = re.compile(
            r"(?m)^\s*(?:@[A-Za-z_][A-Za-z0-9_$.]*(?:\([^\n]*\))?\s*)*"
            r"(?:(?:public|protected|private|static|final|abstract|synchronized|native|default|strictfp)\s+)*"
            r"(?:<[A-Za-z0-9_<>, ?]+\>\s*)?"
            r"(?:(?:[A-Za-z0-9_<>\[\], ?]+)\s+)?"
            r"([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*(?:throws\s+[A-Za-z0-9_.,\s]+)?\{"
        )

        for match in method_pattern.finditer(class_body):
            if depth_map[match.start()] != 0:
                continue
            method_name = match.group(1)
            param_types, param_qualifiers = self._extract_java_param_details(match.group(2) or "")
            open_brace = class_body.find("{", match.end() - 1)
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(class_body, open_brace)
            if close_brace < 0:
                continue
            body = class_body[open_brace + 1:close_brace]
            local_types = self._extract_java_declared_types(body)
            member_types = dict(field_types)
            member_types.update(param_types)
            member_types.update(local_types)
            member_qualifiers = dict(field_qualifiers)
            member_qualifiers.update(param_qualifiers)
            start_index = body_offset + match.start()
            end_index = body_offset + close_brace
            qualname = f"{class_name}.{method_name}"
            raw_calls = self._extract_java_calls(body)
            raw_imports = set(imports_symbols.values())
            payloads.append(
                {
                    "module": module_name,
                    "qualname": qualname,
                    "kind": "method",
                    "class_context": class_name,
                    "imports_modules": {},
                    "imports_symbols": dict(imports_symbols),
                    "member_types": member_types,
                    "member_qualifiers": member_qualifiers,
                    "package_name": package_name,
                    "declared_symbols": [],
                    "raw_calls": raw_calls,
                    "raw_bases": set(),
                    "raw_string_refs": self._harvest_string_refs(body, exclude=raw_calls | raw_imports),
                    "lines": self._span_to_lines(full_content, start_index, end_index),
                }
            )
        return payloads

    def _extract_java_top_level_calls(self, class_body: str) -> Set[str]:
        depth_map = self._compute_js_like_brace_depths(class_body)
        filtered = "".join(char if depth_map[index] == 0 else " " for index, char in enumerate(class_body))
        return self._extract_java_calls(filtered)

    def _extract_java_calls(self, fragment: str) -> Set[str]:
        calls: Set[str] = set()
        for match in re.finditer(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\(", fragment):
            name = match.group(1)
            if name in {"if", "for", "while", "switch", "catch", "return", "new", "super", "this"}:
                continue
            calls.add(name)
        for match in re.finditer(r"\bnew\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\(", fragment):
            calls.add(match.group(1))
        return calls

    def _split_java_csv(self, spec: str) -> List[str]:
        items: List[str] = []
        current: List[str] = []
        angle_depth = 0
        paren_depth = 0
        bracket_depth = 0
        brace_depth = 0
        for char in spec:
            if char == "<":
                angle_depth += 1
            elif char == ">" and angle_depth > 0:
                angle_depth -= 1
            elif char == "(":
                paren_depth += 1
            elif char == ")" and paren_depth > 0:
                paren_depth -= 1
            elif char == "[":
                bracket_depth += 1
            elif char == "]" and bracket_depth > 0:
                bracket_depth -= 1
            elif char == "{":
                brace_depth += 1
            elif char == "}" and brace_depth > 0:
                brace_depth -= 1
            elif char == "," and angle_depth == 0 and paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
                item = "".join(current).strip()
                if item:
                    items.append(item)
                current = []
                continue
            current.append(char)
        item = "".join(current).strip()
        if item:
            items.append(item)
        return items

    def _extract_java_annotation_entries(self, fragment: str) -> List[Tuple[str, str]]:
        entries: List[Tuple[str, str]] = []
        for match in re.finditer(r"@([A-Za-z_][A-Za-z0-9_$.]*)(?:\(([^()]*)\))?", fragment):
            entries.append((match.group(1).rsplit(".", 1)[-1], match.group(2) or ""))
        return entries

    def _extract_java_annotation_value(self, args: str) -> str:
        match = re.search(r'"([^"]+)"', args)
        return match.group(1).strip() if match else ""

    def _extract_java_qualifier(self, fragment: str) -> str:
        for name, args in self._extract_java_annotation_entries(fragment):
            if name in JAVA_QUALIFIER_ANNOTATIONS:
                qualifier = self._extract_java_annotation_value(args)
                if qualifier:
                    return qualifier
        return ""

    def _extract_java_leading_annotation_block(self, content: str, start_index: int) -> str:
        lines = content[:start_index].splitlines()
        collected: List[str] = []
        while lines:
            line = lines.pop().strip()
            if not line:
                if collected:
                    break
                continue
            if line.startswith("@"):
                collected.append(line)
                continue
            break
        return "\n".join(reversed(collected))

    def _extract_java_component_metadata(self, type_name: str, annotation_block: str) -> Tuple[List[str], str, bool]:
        entries = self._extract_java_annotation_entries(annotation_block)
        annotations = [name for name, _ in entries]
        bean_name = ""
        for name, args in entries:
            if name in JAVA_COMPONENT_ANNOTATIONS:
                bean_name = self._extract_java_annotation_value(args)
                if bean_name:
                    break
        if not bean_name and type_name and any(name in JAVA_COMPONENT_ANNOTATIONS for name in annotations):
            bean_name = type_name[:1].lower() + type_name[1:]
        return annotations, bean_name, any(name in JAVA_PRIMARY_ANNOTATIONS for name in annotations)

    def _clean_java_type(self, raw_type: str, initializer: str = "") -> str:
        cleaned = re.sub(r"@\w+(?:\([^)]*\))?\s*", " ", raw_type)
        cleaned = cleaned.replace("...", " ")
        cleaned = cleaned.replace("[]", " ")
        cleaned = re.sub(r"<.*?>", "", cleaned)
        cleaned = re.sub(
            r"\b(?:public|protected|private|static|final|transient|volatile|synchronized|native|strictfp)\b",
            " ",
            cleaned,
        )
        cleaned = re.sub(r"\b(?:extends|super)\b", " ", cleaned)
        parts = [part for part in cleaned.split() if part]
        if not parts:
            return ""
        candidate = parts[-1].strip()
        if candidate == "var":
            match = re.search(r"\bnew\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\(", initializer)
            candidate = match.group(1) if match else ""
        if not candidate or candidate in JAVA_NON_SYMBOL_TYPES:
            return ""
        return candidate

    def _extract_java_declared_members(
        self,
        fragment: str,
        top_level_only: bool = False,
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        declared: Dict[str, str] = {}
        qualifiers: Dict[str, str] = {}
        depth_map = self._compute_js_like_brace_depths(fragment) if top_level_only else None
        declaration_pattern = re.compile(
            r"(?m)^\s*((?:@[A-Za-z_][A-Za-z0-9_$.]*(?:\([^)]*\))?\s*)*)"
            r"(?:(?:public|protected|private|static|final|transient|volatile)\s+)*"
            r"([A-Za-z0-9_$.<>\[\], ?]+)\s+([A-Za-z_]\w*)\s*(?:=\s*([^;]+))?;"
        )
        for match in declaration_pattern.finditer(fragment):
            if depth_map is not None and depth_map[match.start()] != 0:
                continue
            variable_name = match.group(3)
            variable_type = self._clean_java_type(match.group(2), match.group(4) or "")
            if variable_type:
                declared[variable_name] = variable_type
                qualifier = self._extract_java_qualifier(match.group(1) or "")
                if qualifier:
                    qualifiers[variable_name] = qualifier
        return declared, qualifiers

    def _extract_java_declared_types(self, fragment: str, top_level_only: bool = False) -> Dict[str, str]:
        declared, _ = self._extract_java_declared_members(fragment, top_level_only=top_level_only)
        return declared

    def _extract_java_constructor_field_qualifiers(
        self,
        class_body: str,
        class_name: str,
        field_types: Dict[str, str],
    ) -> Dict[str, str]:
        field_qualifiers: Dict[str, str] = {}
        depth_map = self._compute_js_like_brace_depths(class_body)
        method_pattern = re.compile(
            r"(?m)^\s*(?:@[A-Za-z_][A-Za-z0-9_$.]*(?:\([^\n]*\))?\s*)*"
            r"(?:(?:public|protected|private|static|final|abstract|synchronized|native|default|strictfp)\s+)*"
            r"(?:<[A-Za-z0-9_<>, ?]+\>\s*)?"
            r"(?:(?:[A-Za-z0-9_<>\[\], ?]+)\s+)?"
            r"([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*(?:throws\s+[A-Za-z0-9_.,\s]+)?\{"
        )
        assignment_pattern = re.compile(r"(?m)(?:this\.)?([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s*;")

        for match in method_pattern.finditer(class_body):
            if depth_map[match.start()] != 0 or match.group(1) != class_name:
                continue
            param_types, param_qualifiers = self._extract_java_param_details(match.group(2) or "")
            if not param_qualifiers:
                continue
            open_brace = class_body.find("{", match.end() - 1)
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(class_body, open_brace)
            if close_brace < 0:
                continue
            body = class_body[open_brace + 1:close_brace]
            for assignment in assignment_pattern.finditer(body):
                field_name = assignment.group(1)
                param_name = assignment.group(2)
                if param_name not in param_qualifiers or field_name not in field_types:
                    continue
                if param_name in param_types and field_types[field_name] == param_types[param_name]:
                    field_qualifiers.setdefault(field_name, param_qualifiers[param_name])
        return field_qualifiers

    def _extract_java_param_details(self, params_spec: str) -> Tuple[Dict[str, str], Dict[str, str]]:
        params: Dict[str, str] = {}
        qualifiers: Dict[str, str] = {}
        param_pattern = re.compile(
            r"^\s*((?:@[A-Za-z_][A-Za-z0-9_$.]*(?:\([^)]*\))?\s*)*)"
            r"(?:(?:final)\s+)*(.+?)\s+([A-Za-z_]\w*)\s*$"
        )
        for raw_param in self._split_java_csv(params_spec):
            match = param_pattern.match(raw_param)
            if not match:
                continue
            variable_name = match.group(3)
            variable_type = self._clean_java_type(match.group(2))
            if not variable_type:
                continue
            params[variable_name] = variable_type
            qualifier = self._extract_java_qualifier(match.group(1) or "")
            if qualifier:
                qualifiers[variable_name] = qualifier
        return params, qualifiers

    def _extract_java_param_types(self, params_spec: str) -> Dict[str, str]:
        params, _ = self._extract_java_param_details(params_spec)
        return params
