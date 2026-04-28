# ── SIA src/09_parser_rust.py ── (god_mode_v3.py lines 3160–3219) ────────────────────
    def _parse_rust_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        funcs = re.findall(r"(?m)^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)\s*\(", content)
        types = re.findall(r"(?m)^\s*(?:pub\s+)?(?:struct|enum|trait|mod)\s+([A-Za-z_]\w*)\b", content)
        raw_imports: Set[str] = set()
        for spec in re.findall(r"(?m)^\s*use\s+([^;]+);", content):
            raw_imports.update(self._expand_rust_use_spec(spec))
        for child in re.findall(r"(?m)^\s*(?:pub\s+)?mod\s+([A-Za-z_]\w*)\s*;", content):
            raw_imports.add(f"mod::{child}")

        module_path = self._rust_module_path(rel_path)
        return {
            "module": source_group(rel_path, language),
            "qualname": source_qualname(rel_path),
            "kind": "module",
            "imports_modules": {},
            "imports_symbols": {},
            "package_name": module_path,
            "declared_symbols": self._dedupe(funcs + types)[:20],
            "raw_imports": raw_imports,
            "raw_bases": set(),
            "raw_string_refs": self._harvest_string_refs(content, exclude=raw_imports),
        }

    def _expand_rust_use_spec(self, spec: str) -> List[str]:
        compact = "".join(spec.strip().split())
        if "{" not in compact:
            return [compact]
        prefix, rest = compact.split("{", 1)
        inner = rest.rsplit("}", 1)[0]
        prefix = prefix.rstrip(":")
        out: List[str] = []
        for item in inner.split(","):
            if not item:
                continue
            if item == "self":
                out.append(prefix)
            else:
                out.append(f"{prefix}::{item}".strip(":"))
        return out

    def _rust_module_path(self, rel_path: str) -> str:
        normalized = Path(rel_path).as_posix()
        tail = normalized[4:] if normalized.startswith("src/") else normalized
        if tail in {"lib.rs", "main.rs"}:
            return "crate"
        if tail.endswith("/mod.rs"):
            tail = tail[:-7]
        elif tail.endswith(".rs"):
            tail = tail[:-3]
        parts = [part for part in tail.split("/") if part]
        if not parts:
            return "crate"
        return "crate::" + "::".join(parts)

    def _calls_from_body(self, statements: Iterable[ast.stmt]) -> Set[str]:
        collector = CallCollector()
        for stmt in statements:
            collector.visit(stmt)
        return collector.calls

