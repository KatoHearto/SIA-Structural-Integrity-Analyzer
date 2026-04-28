# ── SIA src/13_graph_metrics.py ── (god_mode_v3.py lines 3914–9500) ────────────────────
    def _build_java_concrete_type_targets(self) -> None:
        self.java_concrete_type_targets.clear()
        java_types = sorted(
            node_id
            for node_id, node in self.nodes.items()
            if node.language == "Java" and node.kind in {"class", "enum", "interface"}
        )
        children: Dict[str, Set[str]] = defaultdict(set)
        for node_id in java_types:
            node = self.nodes[node_id]
            for base_id in node.resolved_bases:
                if base_id in self.nodes and self.nodes[base_id].language == "Java":
                    children[base_id].add(node_id)

        for type_id in java_types:
            concrete_targets: List[str] = []
            if self._is_java_concrete_type(self.nodes[type_id]):
                concrete_targets.append(type_id)
            visited: Set[str] = set()
            queue = deque(sorted(children.get(type_id, set())))
            while queue:
                child_id = queue.popleft()
                if child_id in visited:
                    continue
                visited.add(child_id)
                child_node = self.nodes[child_id]
                if self._is_java_concrete_type(child_node):
                    concrete_targets.append(child_id)
                for nested_id in sorted(children.get(child_id, set())):
                    queue.append(nested_id)
            if concrete_targets:
                self.java_concrete_type_targets[type_id] = sorted(set(concrete_targets))

    def _java_candidate_names(self, candidate_id: str) -> Set[str]:
        if candidate_id not in self.nodes:
            return set()
        node = self.nodes[candidate_id]
        simple_name = node.qualname.split(".")[-1]
        names = {simple_name, simple_name[:1].lower() + simple_name[1:] if simple_name else ""}
        if node.bean_name:
            names.add(node.bean_name)
        return {name for name in names if name}

    def _java_candidate_matches_qualifier(self, candidate_id: str, qualifier: str) -> bool:
        normalized = qualifier.strip().lower()
        if not normalized:
            return False
        return any(name.lower() == normalized for name in self._java_candidate_names(candidate_id))

    def _select_java_di_candidates(
        self,
        caller: SymbolNode,
        declared_target: str,
        member_name: str,
    ) -> List[str]:
        candidates = list(self.java_concrete_type_targets.get(declared_target, []))
        if not candidates:
            return []
        qualifier = caller.member_qualifiers.get(member_name, "")
        if qualifier:
            return sorted(candidate for candidate in candidates if self._java_candidate_matches_qualifier(candidate, qualifier))
        primary_candidates = sorted(candidate for candidate in candidates if self.nodes[candidate].di_primary)
        if primary_candidates:
            return primary_candidates
        return sorted(candidates)

    def _resolve_import_outcome(self, caller: SymbolNode, raw: str) -> ResolutionOutcome:
        if caller.language in {"JavaScript", "TypeScript"}:
            return self._resolve_js_like_import_outcome(caller, raw)
        if caller.language == "Go":
            target = self._resolve_go_import(raw)
            if target:
                return self._resolution(target=target, kind="import_exact", reason=f"Resolved Go import `{raw}` exactly.")
            return ResolutionOutcome(target=None)
        if caller.language == "Java":
            target = self._resolve_java_import(raw)
            if target:
                return self._resolution(target=target, kind="import_exact", reason=f"Resolved Java import `{raw}` exactly.")
            return ResolutionOutcome(target=None)
        if caller.language == "Rust":
            target = self._resolve_rust_import(caller, raw)
            if target:
                return self._resolution(target=target, kind="import_exact", reason=f"Resolved Rust import `{raw}` exactly.")
            return ResolutionOutcome(target=None)
        if caller.language == "CSharp":
            candidates = [
                nid for nid, nd in self.nodes.items()
                if nd.language == "CSharp" and nd.package_name == raw and nd.kind != "module"
            ]
            if len(candidates) == 1:
                return self._resolution(
                    target=candidates[0],
                    kind="import_exact",
                    reason=f"Resolved C# using `{raw}` exactly.",
                )
            return ResolutionOutcome(target=None)
        if caller.language == "Kotlin":
            candidates = [
                nid for nid, nd in self.nodes.items()
                if nd.language == "Kotlin" and nd.package_name
                and (nd.package_name == raw or nd.package_name.startswith(raw + "."))
                and nd.kind != "module"
            ]
            if len(candidates) == 1:
                return self._resolution(
                    target=candidates[0],
                    kind="import_exact",
                    reason=f"Resolved Kotlin import `{raw}` exactly.",
                )
            return ResolutionOutcome(target=None)
        if caller.language == "PHP":
            direct_candidates = [
                nid for nid, nd in self.nodes.items()
                if nd.language == "PHP" and nd.package_name
                and "." not in nd.qualname
                and f"{nd.package_name}.{nd.qualname}" == raw
                and nd.kind != "module"
            ]
            if len(direct_candidates) == 1:
                return self._resolution(
                    target=direct_candidates[0],
                    kind="import_exact",
                    reason=f"Resolved PHP use `{raw}` exactly.",
                )
            candidates = [
                nid for nid, nd in self.nodes.items()
                if nd.language == "PHP" and nd.package_name
                and (nd.package_name == raw or nd.package_name.endswith("." + raw))
                and nd.kind != "module"
            ]
            if len(candidates) == 1:
                return self._resolution(
                    target=candidates[0],
                    kind="import_exact",
                    reason=f"Resolved PHP use `{raw}` exactly.",
                )
            return ResolutionOutcome(target=None)
        if caller.language == "Ruby":
            raw_norm = raw.replace("-", "_").lower()
            direct_candidates = [
                nid for nid, nd in self.nodes.items()
                if nd.language == "Ruby"
                and nd.kind == "class"
                and (
                    Path(nd.file).stem.replace("-", "_").lower() == raw_norm
                    or re.sub(
                        r"(?<!^)(?=[A-Z])",
                        "_",
                        nd.qualname.split("#", 1)[0].split(".", 1)[0].split("::")[-1],
                    ).lower() == raw_norm
                )
            ]
            if len(direct_candidates) == 1:
                return self._resolution(
                    target=direct_candidates[0],
                    kind="import_exact",
                    reason=f"Resolved Ruby require `{raw}` exactly.",
                )
            candidates = [
                nid for nid, nd in self.nodes.items()
                if nd.language == "Ruby"
                and nd.kind != "module"
                and (nd.package_name == raw or nd.package_name.endswith("." + raw))
            ]
            if len(candidates) == 1:
                return self._resolution(
                    target=candidates[0],
                    kind="import_exact",
                    reason=f"Resolved Ruby require `{raw}` exactly.",
                )
            return ResolutionOutcome(target=None)
        return ResolutionOutcome(target=None)

    def _resolve_import(self, caller: SymbolNode, raw: str) -> Optional[str]:
        return self._resolve_import_outcome(caller, raw).target

    def _js_like_import_resolution_kind(self, rel_path: str, spec: str) -> str:
        if not spec or spec.startswith((".", "..")):
            return "import_exact"
        for config in self._js_resolver_configs_for_file(rel_path):
            for alias_pattern in dict(config.get("paths", {})):
                if "*" in alias_pattern:
                    prefix, suffix = alias_pattern.split("*", 1)
                    if spec.startswith(prefix) and (not suffix or spec.endswith(suffix)):
                        return "alias_resolved"
                elif spec == alias_pattern:
                    return "alias_resolved"
        return "import_exact"

    def _resolve_js_like_import_outcome(self, caller: SymbolNode, spec: str) -> ResolutionOutcome:
        if not spec:
            return ResolutionOutcome(target=None)
        binding_name = ""
        if "#" in spec:
            spec, binding_name = spec.split("#", 1)
        path_kind = self._js_like_import_resolution_kind(caller.file, spec)
        resolved: List[Tuple[str, str]] = []
        for target_file in self._resolve_js_like_import_targets(caller.file, spec):
            if binding_name:
                target, used_barrel = self._resolve_js_like_binding_target_with_barrel(target_file, binding_name, visited=set())
            else:
                target, used_barrel = self.file_module_node.get(target_file), False
            if target:
                resolved.append((target, "barrel_reexport" if used_barrel else path_kind))
        unique_targets = sorted({target for target, _ in resolved})
        if len(unique_targets) != 1:
            return ResolutionOutcome(target=None)
        target = unique_targets[0]
        target_kinds = [kind for candidate, kind in resolved if candidate == target]
        resolution_kind = "barrel_reexport" if "barrel_reexport" in target_kinds else target_kinds[0]
        if resolution_kind == "barrel_reexport":
            reason = f"Resolved `{spec}` via barrel re-export."
        elif resolution_kind == "alias_resolved":
            reason = f"Resolved `{spec}` through configured path alias."
        else:
            reason = f"Resolved `{spec}` through exact internal import target."
        return self._resolution(target=target, kind=resolution_kind, reason=reason)

    def _resolve_js_like_import(self, caller: SymbolNode, spec: str) -> Optional[str]:
        return self._resolve_js_like_import_outcome(caller, spec).target

    def _resolve_js_like_import_targets(self, rel_path: str, spec: str) -> List[str]:
        candidates: List[str] = []
        if not spec:
            return candidates
        abs_source = os.path.abspath(os.path.join(self.root_dir, rel_path))
        if spec.startswith((".", "..")):
            base_path = os.path.normpath(os.path.join(os.path.dirname(abs_source), spec.replace("/", os.sep)))
            candidates.extend(self._js_like_candidate_file_keys(base_path))
            return self._dedupe(candidates)

        configs = self._js_resolver_configs_for_file(rel_path)
        for config in configs:
            matched_alias = False
            for alias_pattern, target_patterns in dict(config.get("paths", {})).items():
                wildcard_value: Optional[str] = None
                if "*" in alias_pattern:
                    prefix, suffix = alias_pattern.split("*", 1)
                    if spec.startswith(prefix) and (not suffix or spec.endswith(suffix)):
                        end_index = len(spec) - len(suffix) if suffix else len(spec)
                        wildcard_value = spec[len(prefix):end_index]
                elif spec == alias_pattern:
                    wildcard_value = ""
                if wildcard_value is None:
                    continue
                matched_alias = True
                for target_pattern in target_patterns:
                    resolved_target = target_pattern.replace("*", wildcard_value) if "*" in target_pattern else target_pattern
                    candidates.extend(self._js_like_candidate_file_keys(resolved_target))
            if matched_alias:
                continue
            base_dir = str(config.get("base_dir", ""))
            if base_dir:
                candidates.extend(self._js_like_candidate_file_keys(os.path.normpath(os.path.join(base_dir, spec.replace("/", os.sep)))))
        return self._dedupe(candidates)

    def _js_like_candidate_file_keys(self, base_path: str) -> List[str]:
        out: List[str] = []
        if not base_path:
            return out
        candidate_paths: List[str] = []
        if Path(base_path).suffix.lower() in JS_LIKE_SUFFIXES:
            candidate_paths.append(base_path)
        else:
            for suffix in sorted(JS_LIKE_SUFFIXES):
                candidate_paths.append(base_path + suffix)
            for suffix in sorted(JS_LIKE_SUFFIXES):
                candidate_paths.append(os.path.join(base_path, f"index{suffix}"))

        for candidate in candidate_paths:
            abs_candidate = os.path.abspath(candidate)
            try:
                rel_candidate = os.path.relpath(abs_candidate, self.root_dir)
            except ValueError:
                continue
            if rel_candidate.startswith(".."):
                continue
            normalized = Path(os.path.normpath(rel_candidate)).as_posix()
            if normalized in self.file_module_node:
                out.append(normalized)
        return out

    def _js_resolver_configs_for_file(self, rel_path: str) -> List[Dict[str, object]]:
        abs_file = os.path.abspath(os.path.join(self.root_dir, rel_path))
        applicable = [
            config
            for config in self.js_resolver_configs
            if abs_file == str(config["config_dir"]) or abs_file.startswith(str(config["config_dir"]) + os.sep)
        ]
        return applicable if applicable else self.js_resolver_configs

    def _looks_like_internal_js_spec(self, rel_path: str, spec: str) -> bool:
        if not spec:
            return False
        if spec.startswith((".", "..")):
            return True
        if self._resolve_js_like_import_targets(rel_path, spec):
            return True
        for config in self._js_resolver_configs_for_file(rel_path):
            for alias_pattern in dict(config.get("paths", {})):
                if "*" in alias_pattern:
                    prefix, suffix = alias_pattern.split("*", 1)
                    if spec.startswith(prefix) and (not suffix or spec.endswith(suffix)):
                        return True
                elif spec == alias_pattern:
                    return True
        return False

    def _resolve_js_like_type_ref(self, caller: SymbolNode, raw_type: str) -> Optional[str]:
        cleaned = self._clean_js_like_type(raw_type)
        if not cleaned:
            return None
        if caller.class_context and cleaned == caller.class_context:
            candidate = f"{caller.module}:{caller.class_context}"
            if candidate in self.nodes and self.nodes[candidate].kind == "class":
                return candidate
        target = self._resolve_non_python_base(caller, cleaned)
        if target and self.nodes[target].kind == "class":
            return target
        return None

    def _resolve_js_like_member_target(self, class_target: Optional[str], member_name: str) -> Optional[str]:
        if not class_target or class_target not in self.nodes:
            return None
        if self.nodes[class_target].kind != "class" or "." in member_name:
            return None
        candidate = f"{self.nodes[class_target].module}:{self.nodes[class_target].qualname}.{member_name}"
        return candidate if candidate in self.nodes else None

    def _resolve_js_like_call_outcome(self, caller: SymbolNode, raw: str) -> ResolutionOutcome:
        class_ctx = caller.class_context
        normalized = raw[len("this."):] if raw.startswith("this.") else raw
        if normalized.startswith("super."):
            target = self._resolve_super_method(caller.module, class_ctx, normalized.split(".", 1)[1])
            if target:
                return self._resolution(target=target, kind="super_dispatch", reason=f"Resolved `{raw}` through base-class dispatch.")
            return ResolutionOutcome(target=None)
        if "." in normalized:
            head, tail = normalized.split(".", 1)
            if head in caller.member_types:
                class_target = self._resolve_js_like_type_ref(caller, caller.member_types[head])
                member_target = self._resolve_js_like_member_target(class_target, tail)
                if member_target:
                    return self._resolution(target=member_target, kind="instance_dispatch", reason=f"Resolved `{raw}` through instance member `{head}`.")
            if head in caller.imports_modules:
                outcome = self._resolve_js_like_import_outcome(caller, f"{caller.imports_modules[head]}#{tail}")
                if outcome.target:
                    return outcome
        if normalized in caller.imports_symbols:
            binding = caller.imports_symbols[normalized]
            outcome = self._resolve_js_like_import_outcome(caller, binding)
            if outcome.target:
                return outcome
        if class_ctx:
            candidate = f"{caller.module}:{class_ctx}.{normalized}"
            if candidate in self.nodes:
                return self._resolution(target=candidate, kind="same_class_method", reason=f"Resolved `{raw}` on the current class.")
        target = self._resolve_js_like_file_symbol(caller.file, normalized)
        if target:
            return self._resolution(target=target, kind="same_module_symbol", reason=f"Resolved `{raw}` as a same-file symbol.")
        candidates = [
            candidate
            for candidate in self.short_index.get(normalized, [])
            if self.nodes[candidate].language in {"JavaScript", "TypeScript"}
        ]
        if len(candidates) == 1:
            return self._resolution(target=candidates[0], kind="heuristic", reason=f"Resolved `{raw}` via unique short-name fallback.")
        return ResolutionOutcome(target=None)

    def _resolve_js_like_call(self, caller: SymbolNode, raw: str) -> Optional[str]:
        return self._resolve_js_like_call_outcome(caller, raw).target

    def _resolve_js_like_file_symbol(self, rel_path: str, symbol_name: str) -> Optional[str]:
        file_key = Path(rel_path).as_posix()
        candidates = self.file_top_level_symbol_index.get(file_key, {}).get(symbol_name, [])
        return candidates[0] if len(candidates) == 1 else None

    def _resolve_js_like_binding_reference_with_barrel(
        self,
        file_key: str,
        binding_spec: str,
        visited: Set[Tuple[str, str]],
        _depth: int = 0,
    ) -> Tuple[Optional[str], bool]:
        if _depth > 8:
            return None, False
        spec = binding_spec
        binding_name = ""
        if "#" in binding_spec:
            spec, binding_name = binding_spec.split("#", 1)
        resolved: List[Tuple[str, bool]] = []
        for target_file in self._resolve_js_like_import_targets(file_key, spec):
            if binding_name:
                target, used_barrel = self._resolve_js_like_binding_target_with_barrel(target_file, binding_name, visited=visited, _depth=_depth + 1)
            else:
                target, used_barrel = self.file_module_node.get(target_file), False
            if target:
                resolved.append((target, used_barrel))
        unique_targets = sorted({target for target, _ in resolved})
        if len(unique_targets) != 1:
            return None, False
        target = unique_targets[0]
        return target, any(used_barrel for candidate, used_barrel in resolved if candidate == target)

    def _resolve_js_like_binding_reference(
        self,
        file_key: str,
        binding_spec: str,
        visited: Set[Tuple[str, str]],
    ) -> Optional[str]:
        target, _ = self._resolve_js_like_binding_reference_with_barrel(file_key, binding_spec, visited)
        return target

    def _resolve_js_like_binding_target_with_barrel(
        self,
        file_key: str,
        binding_name: str,
        visited: Optional[Set[Tuple[str, str]]] = None,
        _depth: int = 0,
    ) -> Tuple[Optional[str], bool]:
        if _depth > 8:
            return None, False
        visited = visited or set()
        visit_key = (file_key, binding_name)
        if visit_key in visited:
            return None, False
        visited.add(visit_key)
        symbols = self.file_top_level_symbol_index.get(file_key, {})
        if not binding_name:
            return None, False
        if binding_name not in {"", "default"}:
            candidates = symbols.get(binding_name, [])
            if len(candidates) == 1:
                return candidates[0], False
            barrel_binding = self.js_barrel_bindings.get(file_key, {}).get(binding_name)
            if barrel_binding:
                target, _ = self._resolve_js_like_binding_reference_with_barrel(file_key, barrel_binding, visited, _depth=_depth + 1)
                return (target, True) if target else (None, False)
            star_hits = []
            for spec in self.js_barrel_star_specs.get(file_key, []):
                target, _ = self._resolve_js_like_binding_reference_with_barrel(file_key, f"{spec}#{binding_name}", visited, _depth=_depth + 1)
                if target:
                    star_hits.append(target)
            unique_star_hits = sorted(set(star_hits))
            return (unique_star_hits[0], True) if len(unique_star_hits) == 1 else (None, False)
        stem = Path(file_key).stem
        if stem in symbols and len(symbols[stem]) == 1:
            return symbols[stem][0], False
        default_binding = self.js_barrel_bindings.get(file_key, {}).get("default")
        if default_binding:
            target, _ = self._resolve_js_like_binding_reference_with_barrel(file_key, default_binding, visited, _depth=_depth + 1)
            return (target, True) if target else (None, False)
        top_level_nodes = [candidate for candidates in symbols.values() for candidate in candidates]
        unique_nodes = sorted(set(top_level_nodes))
        return (unique_nodes[0], False) if len(unique_nodes) == 1 else (None, False)

    def _resolve_js_like_binding_target(
        self,
        file_key: str,
        binding_name: str,
        visited: Optional[Set[Tuple[str, str]]] = None,
    ) -> Optional[str]:
        target, _ = self._resolve_js_like_binding_target_with_barrel(file_key, binding_name, visited)
        return target

    def _classify_js_like_call(self, caller: SymbolNode, raw: str) -> str:
        normalized = raw[len("this."):] if raw.startswith("this.") else raw
        root = normalized.split(".", 1)[0]
        if root in JS_GLOBAL_NAMES:
            return "external"
        if raw.startswith(("this.", "super.")):
            return "unresolved"
        if root in caller.member_types:
            return "unresolved"
        if root in caller.imports_modules:
            spec = caller.imports_modules[root]
            return "unresolved" if self._looks_like_internal_js_spec(caller.file, spec) else "external"
        if root in caller.imports_symbols:
            binding = caller.imports_symbols[root]
            spec = binding.split("#", 1)[0]
            return "unresolved" if self._looks_like_internal_js_spec(caller.file, spec) else "external"
        return "unresolved"

    def _resolve_go_import(self, spec: str) -> Optional[str]:
        if not self.go_root_module or not spec.startswith(self.go_root_module):
            return None
        rel_dir = spec[len(self.go_root_module):].lstrip("/") or "."
        rel_dir = Path(rel_dir).as_posix()
        return self.go_dir_to_node.get(rel_dir)

    def _resolve_java_import(self, spec: str) -> Optional[str]:
        if spec.endswith(".*"):
            return None
        return self.java_type_to_node.get(spec) or self.java_member_to_node.get(spec)

    def _resolve_java_type_ref_outcome(
        self,
        caller: SymbolNode,
        raw_type: str,
        member_name: str = "",
        allow_di: bool = False,
        raw_call: str = "",
    ) -> ResolutionOutcome:
        cleaned = self._clean_java_type(raw_type)
        if not cleaned:
            return ResolutionOutcome(target=None)
        if caller.class_context and cleaned == caller.class_context:
            candidate = f"{caller.module}:{caller.class_context}"
            if candidate in self.nodes and self.nodes[candidate].kind in {"class", "enum", "interface"}:
                return self._resolution(target=candidate, kind="instance_dispatch", reason=f"Dispatched `{raw_call or member_name or cleaned}` to the current Java type.")
        target = self._resolve_non_python_base(caller, cleaned)
        if not target or target not in self.nodes or self.nodes[target].language != "Java":
            return ResolutionOutcome(target=None)
        if not allow_di or self._is_java_concrete_type(self.nodes[target]):
            return self._resolution(target=target, kind="instance_dispatch", reason=f"Resolved `{member_name or cleaned}` to concrete Java type `{self.nodes[target].qualname}`.")

        all_candidates = list(self.java_concrete_type_targets.get(target, []))
        qualifier = caller.member_qualifiers.get(member_name, "")
        if qualifier:
            qualifier_candidates = sorted(
                candidate for candidate in all_candidates if self._java_candidate_matches_qualifier(candidate, qualifier)
            )
            if len(qualifier_candidates) == 1:
                selected = qualifier_candidates[0]
                return self._resolution(
                    target=selected,
                    kind="java_di_qualifier",
                    reason=f"Qualifier `{qualifier}` selected Java implementation `{self.nodes[selected].qualname}`.",
                )
            if len(qualifier_candidates) > 1:
                return self._resolution(
                    target=None,
                    kind="ambiguous_candidates",
                    reason=f"Qualifier `{qualifier}` matched multiple Java implementations for `{member_name}`.",
                    candidates=qualifier_candidates,
                )
            return self._resolution(target=target, kind="instance_dispatch", reason=f"Kept declared Java type `{self.nodes[target].qualname}` after qualifier lookup.")

        primary_candidates = sorted(candidate for candidate in all_candidates if self.nodes[candidate].di_primary)
        if len(primary_candidates) == 1:
            selected = primary_candidates[0]
            return self._resolution(
                target=selected,
                kind="java_di_primary",
                reason=f"`@Primary` selected Java implementation `{self.nodes[selected].qualname}`.",
            )
        if len(primary_candidates) > 1:
            return self._resolution(
                target=None,
                kind="ambiguous_candidates",
                reason=f"Multiple `@Primary` Java implementations matched `{member_name}`.",
                candidates=primary_candidates,
            )

        if len(all_candidates) == 1:
            selected = all_candidates[0]
            return self._resolution(
                target=selected,
                kind="java_di_unique_impl",
                reason=f"Unique Java implementation `{self.nodes[selected].qualname}` matched declared type `{cleaned}`.",
            )
        if len(all_candidates) > 1:
            return self._resolution(
                target=None,
                kind="ambiguous_candidates",
                reason=f"Multiple Java implementations matched declared type `{cleaned}`.",
                candidates=all_candidates,
            )
        return self._resolution(target=target, kind="instance_dispatch", reason=f"Kept declared Java type `{self.nodes[target].qualname}` for dispatch.")

    def _resolve_java_type_ref(
        self,
        caller: SymbolNode,
        raw_type: str,
        member_name: str = "",
        allow_di: bool = False,
        raw_call: str = "",
    ) -> Optional[str]:
        return self._resolve_java_type_ref_outcome(
            caller,
            raw_type,
            member_name=member_name,
            allow_di=allow_di,
            raw_call=raw_call,
        ).target

    def _resolve_java_member_target(self, class_target: Optional[str], member_name: str) -> Optional[str]:
        if not class_target or class_target not in self.nodes or "." in member_name:
            return None
        visited: Set[str] = set()
        queue = deque([class_target])
        while queue:
            current_id = queue.popleft()
            if current_id in visited:
                continue
            visited.add(current_id)
            current = self.nodes[current_id]
            if current.language != "Java" or current.kind not in {"class", "enum", "interface"}:
                continue
            candidate = f"{current.module}:{current.qualname}.{member_name}"
            if candidate in self.nodes:
                return candidate
            for base_id in sorted(current.resolved_bases):
                queue.append(base_id)
        return None

    def _resolve_java_call_outcome(self, caller: SymbolNode, raw: str) -> ResolutionOutcome:
        class_ctx = caller.class_context
        normalized = raw[len("this."):] if raw.startswith("this.") else raw
        if normalized.startswith("super."):
            target = self._resolve_super_method(caller.module, class_ctx, normalized.split(".", 1)[1])
            if target:
                return self._resolution(target=target, kind="super_dispatch", reason=f"Resolved `{raw}` through Java super dispatch.")
            return ResolutionOutcome(target=None)
        if normalized in self.java_member_to_node:
            target = self.java_member_to_node[normalized]
            return self._resolution(target=target, kind="direct_symbol", reason=f"Resolved `{raw}` by exact Java member name.")
        if "." in normalized:
            head, tail = normalized.split(".", 1)
            if head in caller.member_types:
                type_outcome = self._resolve_java_type_ref_outcome(
                    caller,
                    caller.member_types[head],
                    member_name=head,
                    allow_di=True,
                    raw_call=normalized,
                )
                member_target = self._resolve_java_member_target(type_outcome.target, tail)
                if member_target:
                    if type_outcome.resolution_kind in {"java_di_primary", "java_di_qualifier", "java_di_unique_impl"}:
                        return self._resolution(
                            target=member_target,
                            kind=type_outcome.resolution_kind,
                            reason=type_outcome.resolution_reason,
                        )
                    return self._resolution(
                        target=member_target,
                        kind="instance_dispatch",
                        reason=f"Resolved `{raw}` through Java instance member `{head}`.",
                    )
                if type_outcome.resolution_kind == "ambiguous_candidates":
                    return type_outcome
            if head in caller.imports_symbols:
                imported = caller.imports_symbols[head]
                target = self._resolve_java_import(imported)
                member_target = self._resolve_java_member_target(target, tail)
                if member_target:
                    return self._resolution(target=member_target, kind="import_exact", reason=f"Resolved `{raw}` through exact Java import `{imported}`.")
                if target:
                    return self._resolution(target=target, kind="import_exact", reason=f"Resolved `{raw}` through exact Java import `{imported}`.")
            class_target = self._resolve_java_type_ref(caller, head)
            member_target = self._resolve_java_member_target(class_target, tail)
            if member_target:
                return self._resolution(target=member_target, kind="direct_symbol", reason=f"Resolved `{raw}` by exact Java type/member reference.")
            return ResolutionOutcome(target=None)
        if normalized in caller.imports_symbols:
            imported = caller.imports_symbols[normalized]
            target = self._resolve_java_import(imported)
            if target:
                return self._resolution(target=target, kind="import_exact", reason=f"Resolved `{raw}` through exact Java import `{imported}`.")
        if class_ctx:
            candidate = f"{caller.module}:{class_ctx}.{normalized}"
            if candidate in self.nodes:
                return self._resolution(target=candidate, kind="same_class_method", reason=f"Resolved `{raw}` on the current Java class.")
        candidates = [
            candidate for candidate in self.short_index.get(normalized, []) if self.nodes[candidate].language == "Java"
        ]
        if len(candidates) == 1:
            return self._resolution(target=candidates[0], kind="heuristic", reason=f"Resolved `{raw}` via unique Java short-name fallback.")
        return ResolutionOutcome(target=None)

    def _resolve_java_call(self, caller: SymbolNode, raw: str) -> Optional[str]:
        return self._resolve_java_call_outcome(caller, raw).target

    def _classify_java_call(self, caller: SymbolNode, raw: str) -> str:
        normalized = raw[len("this."):] if raw.startswith("this.") else raw
        root = normalized.split(".", 1)[0]
        if root in {"System", "Objects", "Collections", "List", "Map", "Set", "Optional", "String", "Math"}:
            return "external"
        if raw.startswith(("this.", "super.")):
            return "unresolved"
        if root in caller.member_types:
            return "unresolved"
        if root in caller.imports_symbols:
            imported = caller.imports_symbols[root]
            return "unresolved" if (imported in self.java_type_to_node or imported in self.java_member_to_node) else "external"
        return "unresolved"

    def _resolve_rust_import(self, caller: SymbolNode, raw: str) -> Optional[str]:
        current_module = caller.package_name or self._rust_module_path(caller.file)
        target = raw
        if raw.startswith("mod::"):
            child = raw.split("::", 1)[1]
            target = f"{current_module}::{child}" if current_module != "crate" else f"crate::{child}"
        elif raw.startswith("self::"):
            suffix = raw[len("self::"):]
            target = f"{current_module}::{suffix}" if current_module != "crate" else f"crate::{suffix}"
        elif raw.startswith("super::"):
            parent = current_module.rsplit("::", 1)[0] if "::" in current_module else "crate"
            suffix = raw[len("super::"):]
            target = f"{parent}::{suffix}" if parent != "crate" else f"crate::{suffix}"
        elif not raw.startswith("crate::"):
            target = f"crate::{raw}"

        parts = target.split("::")
        for size in range(len(parts), 0, -1):
            candidate = "::".join(parts[:size])
            if candidate in self.rust_module_to_node:
                return self.rust_module_to_node[candidate]
        return None

    def _classify_unresolved_import(self, caller: SymbolNode, raw: str) -> str:
        if caller.language in {"JavaScript", "TypeScript"}:
            return "unresolved" if self._looks_like_internal_js_spec(caller.file, raw) else "external"
        if caller.language == "Go":
            if self.go_root_module and raw.startswith(self.go_root_module):
                return "unresolved"
            return "external"
        if caller.language == "Java":
            if raw.endswith(".*"):
                package = raw[:-2]
                if any(fqcn.startswith(f"{package}.") for fqcn in self.java_type_to_node):
                    return "unresolved"
                return "external"
            if raw in self.java_type_to_node:
                return "unresolved"
            simple = raw.rsplit(".", 1)[-1]
            if any(fqcn.endswith(f".{simple}") for fqcn in self.java_type_to_node):
                return "unresolved"
            return "external"
        if caller.language == "Rust":
            if raw.startswith(("crate::", "self::", "super::", "mod::")):
                return "unresolved"
            return "external"
        return "unresolved"

    def _classify_non_python_base(self, caller: SymbolNode, raw: str) -> str:
        root = raw.split(".", 1)[0].split("::", 1)[0]
        if caller.language in {"JavaScript", "TypeScript"}:
            if root in caller.declared_symbols:
                return "ignore"
            spec = caller.imports_symbols.get(root) or caller.imports_modules.get(root)
            if not spec:
                return "unresolved"
            return "unresolved" if self._looks_like_internal_js_spec(caller.file, spec.split("#", 1)[0]) else "external"
        if caller.language == "Java":
            cleaned = re.sub(r"<.*?>", "", raw).strip()
            simple = cleaned.rsplit(".", 1)[-1]
            if simple in caller.declared_symbols:
                return "ignore"
            imported = caller.imports_symbols.get(simple)
            if imported:
                return "unresolved" if imported in self.java_type_to_node else "external"
            if caller.package_name and any(fqcn == f"{caller.package_name}.{simple}" for fqcn in self.java_type_to_node):
                return "unresolved"
            return "external" if "." in cleaned else "unresolved"
        return "unresolved"

    def _resolve_super_method(self, module: str, class_ctx: Optional[str], method: str) -> Optional[str]:
        if not class_ctx:
            return None
        class_id = f"{module}:{class_ctx}"
        if class_id not in self.nodes:
            return None

        visited: Set[str] = set()
        queue = deque(sorted(self.nodes[class_id].resolved_bases))
        while queue:
            base_id = queue.popleft()
            if base_id in visited:
                continue
            visited.add(base_id)
            base_node = self.nodes[base_id]
            candidate = f"{base_node.module}:{base_node.qualname}.{method}"
            if candidate in self.nodes:
                return candidate
            for parent in sorted(base_node.resolved_bases):
                if parent not in visited:
                    queue.append(parent)
        return None

    def _tarjan_scc(self) -> Tuple[List[List[str]], Dict[str, int]]:
        index = 0
        indices: Dict[str, int] = {}
        lowlink: Dict[str, int] = {}
        stack: List[str] = []
        on_stack: Set[str] = set()
        components: List[List[str]] = []

        for node_id in sorted(self.nodes):
            if node_id in indices:
                continue

            indices[node_id] = index
            lowlink[node_id] = index
            index += 1
            stack.append(node_id)
            on_stack.add(node_id)

            call_stack = [(node_id, iter(sorted(self.adj[node_id])), None)]
            while call_stack:
                v, neighbors, child = call_stack[-1]

                if child is not None:
                    lowlink[v] = min(lowlink[v], lowlink[child])
                    call_stack[-1] = (v, neighbors, None)
                    continue

                try:
                    w = next(neighbors)
                except StopIteration:
                    call_stack.pop()
                    if lowlink[v] == indices[v]:
                        comp: List[str] = []
                        while stack:
                            w = stack.pop()
                            on_stack.remove(w)
                            comp.append(w)
                            if w == v:
                                break
                        components.append(sorted(comp))
                    continue

                if w not in indices:
                    indices[w] = index
                    lowlink[w] = index
                    index += 1
                    stack.append(w)
                    on_stack.add(w)
                    call_stack[-1] = (v, neighbors, w)
                    call_stack.append((w, iter(sorted(self.adj[w])), None))
                elif w in on_stack:
                    lowlink[v] = min(lowlink[v], indices[w])

        node_to_scc: Dict[str, int] = {}
        for comp_id, comp in enumerate(components):
            for node_id in comp:
                node_to_scc[node_id] = comp_id
        return components, node_to_scc

    def _apply_scc(self, node_to_scc: Dict[str, int], sccs: List[List[str]]) -> None:
        for node_id, node in self.nodes.items():
            cid = node_to_scc[node_id]
            node.scc_id = cid
            node.scc_size = len(sccs[cid])

    def _compute_layers(self, node_to_scc: Dict[str, int], sccs: List[List[str]]) -> None:
        comp_edges: Dict[int, Set[int]] = defaultdict(set)
        indegree: Dict[int, int] = {i: 0 for i in range(len(sccs))}

        for src, dsts in self.adj.items():
            c_src = node_to_scc[src]
            for dst in dsts:
                c_dst = node_to_scc[dst]
                if c_src == c_dst:
                    continue
                if c_dst not in comp_edges[c_src]:
                    comp_edges[c_src].add(c_dst)
                    indegree[c_dst] += 1

        queue = deque(sorted(cid for cid, deg in indegree.items() if deg == 0))
        depth: Dict[int, int] = {cid: 0 for cid in indegree}
        topo: List[int] = []

        while queue:
            cid = queue.popleft()
            topo.append(cid)
            for nxt in sorted(comp_edges[cid]):
                if depth[nxt] < depth[cid] + 1:
                    depth[nxt] = depth[cid] + 1
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)

        # If graph was disconnected from Kahn roots due to malformed indegrees, keep deterministic fallback.
        if len(topo) < len(sccs):
            for cid in sorted(set(range(len(sccs))) - set(topo)):
                depth.setdefault(cid, 0)

        for node_id, node in self.nodes.items():
            node.layer = depth.get(node_to_scc[node_id], 0)

    def _compute_pagerank(self, damping: float = 0.85, iterations: int = 30) -> None:
        node_ids = sorted(self.nodes)
        n = len(node_ids)
        if n == 0:
            return

        pr: Dict[str, float] = {nid: 1.0 / n for nid in node_ids}
        inbound: Dict[str, Set[str]] = defaultdict(set)
        outdeg: Dict[str, int] = {}

        for nid in node_ids:
            targets = self.adj[nid]
            outdeg[nid] = len(targets)
            for target in targets:
                inbound[target].add(nid)

        base = (1.0 - damping) / n
        for _ in range(iterations):
            sink_total = sum(pr[nid] for nid in node_ids if outdeg[nid] == 0)
            nxt: Dict[str, float] = {}
            for nid in node_ids:
                score = base + damping * sink_total / n
                for src in inbound[nid]:
                    score += damping * pr[src] / outdeg[src]
                nxt[nid] = score
            pr = nxt

        for nid in node_ids:
            self.nodes[nid].pagerank = round(pr[nid], 8)

    def _compute_betweenness(self) -> None:
        node_ids = sorted(self.nodes)
        n = len(node_ids)
        if n < 3:
            for node in self.nodes.values():
                node.betweenness = 0.0
            return

        centrality: Dict[str, float] = {nid: 0.0 for nid in node_ids}
        for source in node_ids:
            stack: List[str] = []
            predecessors: Dict[str, List[str]] = {nid: [] for nid in node_ids}
            sigma: Dict[str, float] = {nid: 0.0 for nid in node_ids}
            sigma[source] = 1.0
            distance: Dict[str, int] = {nid: -1 for nid in node_ids}
            distance[source] = 0
            queue = deque([source])

            while queue:
                vertex = queue.popleft()
                stack.append(vertex)
                for neighbor in sorted(self.adj[vertex]):
                    if distance[neighbor] < 0:
                        queue.append(neighbor)
                        distance[neighbor] = distance[vertex] + 1
                    if distance[neighbor] == distance[vertex] + 1:
                        sigma[neighbor] += sigma[vertex]
                        predecessors[neighbor].append(vertex)

            dependency: Dict[str, float] = {nid: 0.0 for nid in node_ids}
            while stack:
                vertex = stack.pop()
                if sigma[vertex] == 0:
                    continue
                for predecessor in predecessors[vertex]:
                    dependency[predecessor] += (sigma[predecessor] / sigma[vertex]) * (1.0 + dependency[vertex])
                if vertex != source:
                    centrality[vertex] += dependency[vertex]

        scale = 1.0 / ((n - 1) * (n - 2))
        for node_id in node_ids:
            self.nodes[node_id].betweenness = round(centrality[node_id] * scale, 8)

    def _compute_git_hotspots(self, enabled: bool) -> None:
        self.git_hotspot_enabled = False
        self.git_tracked_file_count = 0
        for node in self.nodes.values():
            node.git_commit_count = 0
            node.git_churn = 0
            node.git_hotness = 0.0

        if not enabled:
            return

        try:
            probe = subprocess.run(
                ["git", "-C", self.root_dir, "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return

        if probe.returncode != 0 or probe.stdout.strip() != "true":
            return

        log_result = subprocess.run(
            [
                "git",
                "-C",
                self.root_dir,
                "log",
                "--numstat",
                "--no-renames",
                "--format=tformat:",
                "--relative=.",
                "--",
                ".",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if log_result.returncode != 0:
            return

        file_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"commits": 0, "churn": 0})
        for raw_line in log_result.stdout.splitlines():
            parts = raw_line.split("\t")
            if len(parts) != 3:
                continue
            added, deleted, path = parts
            if added == "-" or deleted == "-":
                continue
            norm_path = os.path.normpath(path)
            if norm_path.startswith("..") or Path(norm_path).suffix.lower() not in LANGUAGE_BY_SUFFIX:
                continue
            try:
                churn = int(added) + int(deleted)
            except ValueError:
                continue
            file_stats[norm_path]["commits"] += 1
            file_stats[norm_path]["churn"] += churn

        if not file_stats:
            return

        raw_scores: Dict[str, float] = {}
        for file_name, stats in file_stats.items():
            raw_scores[file_name] = (math.log1p(stats["churn"]) * 0.7) + (math.log1p(stats["commits"]) * 0.3)

        max_score = max(raw_scores.values()) or 1.0
        self.git_hotspot_enabled = True
        self.git_tracked_file_count = len(file_stats)
        for node in self.nodes.values():
            stats = file_stats.get(os.path.normpath(node.file))
            if not stats:
                continue
            node.git_commit_count = stats["commits"]
            node.git_churn = stats["churn"]
            node.git_hotness = round(raw_scores[os.path.normpath(node.file)] / max_score, 8)

    def _compute_coords(self) -> None:
        modules = sorted({n.module for n in self.nodes.values()})
        if not modules:
            return
        grid = int(math.ceil(math.sqrt(len(modules))))
        base_xy: Dict[str, Tuple[float, float]] = {}
        for idx, mod in enumerate(modules):
            row, col = divmod(idx, grid)
            base_xy[mod] = (col * 20.0, row * 20.0)

        for node_id, node in self.nodes.items():
            bx, by = base_xy[node.module]
            x = round(bx + stable_jitter(node_id, "x"), 3)
            y = round(by + stable_jitter(node_id, "y"), 3)
            z = round(-float(node.layer), 3)
            node.coord = [x, y, z]

    def _compute_risk_scores(self) -> None:
        if not self.nodes:
            return
        max_ca = max((node.ca for node in self.nodes.values()), default=1) or 1
        max_ce_internal = max((node.ce_internal for node in self.nodes.values()), default=1) or 1
        max_ce_external = max((node.ce_external for node in self.nodes.values()), default=1) or 1
        max_pr = max((node.pagerank for node in self.nodes.values()), default=1.0) or 1.0
        max_bridge = max((node.betweenness for node in self.nodes.values()), default=1.0) or 1.0
        max_git_hotness = max((node.git_hotness for node in self.nodes.values()), default=1.0) or 1.0

        for node in self.nodes.values():
            norm_ca = node.ca / max_ca
            norm_ce_internal = node.ce_internal / max_ce_internal
            norm_ce_external = node.ce_external / max_ce_external
            norm_pr = node.pagerank / max_pr
            norm_bridge = node.betweenness / max_bridge
            norm_git_hotness = node.git_hotness / max_git_hotness
            cycle_flag = 1.0 if node.scc_size > 1 else 0.0
            recursion_flag = 1.0 if (node.recursive_self_call and node.ca >= 2) else 0.0
            upper_layer_pressure = 1.0 if (node.layer <= 1 and node.ce_internal >= 2) else 0.0

            risk = (
                0.24 * node.instability
                + 0.20 * norm_ca
                + 0.14 * norm_bridge
                + 0.12 * norm_ce_internal
                + 0.10 * norm_pr
                + 0.08 * norm_git_hotness
                + 0.06 * cycle_flag
                + 0.03 * recursion_flag
                + 0.02 * upper_layer_pressure
                + 0.01 * norm_ce_external
            )
            node.risk_score = round(risk * 100.0, 2)
            node.reasons = self._reasons_for(
                node,
                max_ca=max_ca,
                max_ce_internal=max_ce_internal,
                max_bridge=max_bridge,
            )

    def _reasons_for(self, node: SymbolNode, max_ca: int, max_ce_internal: int, max_bridge: float) -> List[str]:
        reasons: List[str] = []
        if node.instability >= 0.8 and node.ce_internal >= 2:
            reasons.append("High internal instability: many outgoing project dependencies relative to incoming.")
        if node.ca >= max(3, int(math.ceil(max_ca * 0.6))):
            reasons.append("High afferent coupling (Ca): many dependents, high blast radius.")
        if node.ce_internal >= max(3, int(math.ceil(max_ce_internal * 0.6))):
            reasons.append("High internal efferent coupling (Ce): broad dependency surface inside the project.")
        if node.scc_size > 1:
            reasons.append(f"Part of dependency cycle (SCC size {node.scc_size}).")
        if node.betweenness >= max(0.05, max_bridge * 0.6):
            reasons.append("High bridge centrality: change here can disrupt many shortest dependency paths.")
        if node.recursive_self_call and node.ca >= 2:
            reasons.append("Self-recursive and widely depended upon: verify termination and API stability.")
        if node.layer <= 1 and node.ce_internal >= 2:
            reasons.append("High fan-out near upper architectural layers.")
        if node.resolved_bases:
            reasons.append("Inheritance-linked node: verify whether coupling belongs in inheritance or composition.")
        if node.ce_external >= 5 and node.ce_internal >= 1:
            reasons.append("Large external API surface: consider wrapping vendor/library touchpoints.")
        if self.git_hotspot_enabled and node.git_hotness >= 0.7 and (node.ca >= 1 or node.ce_internal >= 2):
            reasons.append("Git hotspot: this file changes often, so structural issues here are more likely to hurt.")
        if not reasons and node.risk_score >= 55.0:
            reasons.append("Combined coupling pressure from multiple metrics.")
        if node.semantic_signals:
            critical = [s for s in node.semantic_signals if s in SEMANTIC_CRITICAL_SIGNALS]
            if critical and (node.instability >= 0.7 or node.ca >= 3 or node.ce_internal >= 3):
                reasons.append(
                    f"Carries critical semantic signals ({', '.join(sorted(critical))}) under structural pressure — verify change safety."
                )
        return reasons

    def _sort_semantic_signals(self, signals: Iterable[str]) -> List[str]:
        unique = {signal for signal in signals if signal}
        return sorted(
            unique,
            key=lambda signal: (-SEMANTIC_SIGNAL_WEIGHTS.get(signal, 0.0), signal),
        )

    def _semantic_ref_sort_key(self, ref: Dict[str, object]) -> Tuple[float, int, int, str, str]:
        lines = ref.get("lines", [0, 0])
        start = int(lines[0]) if isinstance(lines, list) and lines else 0
        end = int(lines[1]) if isinstance(lines, list) and len(lines) > 1 else start
        signal = str(ref.get("signal", ""))
        return (
            -SEMANTIC_SIGNAL_WEIGHTS.get(signal, 0.0),
            start,
            end,
            signal,
            str(ref.get("reason", "")),
        )

    def _dedupe_semantic_refs(self, refs: List[Dict[str, object]], limit: int = 12) -> List[Dict[str, object]]:
        seen: Set[str] = set()
        out: List[Dict[str, object]] = []
        for ref in sorted(refs, key=self._semantic_ref_sort_key):
            key = json.dumps(ref, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            out.append(ref)
            if len(out) >= limit:
                break
        return out

    def _semantic_refs_for_node(self, node_id: str, limit: int = 3) -> List[Dict[str, object]]:
        node = self.nodes.get(node_id)
        if node is None or not node.semantic_evidence_spans:
            return []
        return self._dedupe_semantic_refs(list(node.semantic_evidence_spans), limit=limit)

    def _contained_semantic_refs_for_node(self, node_id: str, limit: int = 4) -> List[Dict[str, object]]:
        node = self.nodes.get(node_id)
        if node is None or not node.contained_semantic_refs:
            return []
        return self._dedupe_semantic_refs(list(node.contained_semantic_refs), limit=limit)

    def _semantic_child_nodes(self, node: SymbolNode) -> List[SymbolNode]:
        children: List[SymbolNode] = []
        start_line = int(node.lines[0])
        end_line = int(node.lines[1])
        for candidate in self.nodes.values():
            if candidate.node_id == node.node_id or candidate.file != node.file:
                continue
            candidate_start = int(candidate.lines[0])
            candidate_end = int(candidate.lines[1])
            if candidate_start < start_line or candidate_end > end_line:
                continue
            if node.kind == "module":
                if candidate.kind == "module":
                    continue
                children.append(candidate)
                continue
            if node.kind not in SEMANTIC_CONTAINER_KINDS:
                continue
            if candidate.kind == "module":
                continue
            if candidate.class_context == node.qualname or candidate.qualname.startswith(f"{node.qualname}."):
                children.append(candidate)
        children.sort(
            key=lambda child: (
                int(child.lines[0]),
                int(child.lines[1]),
                child.kind,
                child.node_id,
            )
        )
        return children

    def _node_source_lines(self, node: SymbolNode, direct_semantics: bool = False) -> List[Tuple[int, str]]:
        lines = self._read_project_lines(node.file)
        if not lines:
            return []
        start = max(1, min(int(node.lines[0]), len(lines)))
        end = max(start, min(int(node.lines[1]), len(lines)))
        if not direct_semantics or node.kind in SEMANTIC_EXECUTABLE_KINDS:
            return [(lineno, lines[lineno - 1]) for lineno in range(start, end + 1)]
        excluded_lines: Set[int] = set()
        for child in self._semantic_child_nodes(node):
            child_start = max(start, int(child.lines[0]))
            child_end = min(end, int(child.lines[1]))
            excluded_lines.update(range(child_start, child_end + 1))
        return [
            (lineno, lines[lineno - 1])
            for lineno in range(start, end + 1)
            if lineno not in excluded_lines
        ]

    def _node_source_text(self, node: SymbolNode, direct_semantics: bool = False) -> str:
        return "\n".join(text for _, text in self._node_source_lines(node, direct_semantics=direct_semantics))

    def _looks_like_validation_guard(self, text: str) -> bool:
        lower = f" {text.lower()} "
        if any(hint in lower for hint in SEMANTIC_VALIDATION_HINTS):
            return True
        return bool(
            re.search(r"\bif\s*\(\s*!", text)
            or " is none" in lower
            or " is not none" in lower
            or re.search(r'(?:==|!=)\s*(?:None|null|undefined|""|\'\'|0\b|False\b|True\b)', text)
            or "<=" in text
            or ">=" in text
        )

    def _guard_signal_for_window(
        self,
        source_lines: List[Tuple[int, str]],
        index: int,
        lookahead: int = 2,
    ) -> Optional[Tuple[str, int, str]]:
        _, text = source_lines[index]
        if not re.search(r"\bif\b", text):
            return None
        window = source_lines[index:min(len(source_lines), index + lookahead + 1)]
        combined = " ".join(line for _, line in window)
        combined_lower = combined.lower()
        action_lineno = 0
        for lineno, candidate in window:
            candidate_lower = candidate.lower()
            if any(pattern in candidate_lower for pattern in SEMANTIC_GUARD_ACTION_PATTERNS):
                action_lineno = lineno
                break
        if not action_lineno:
            return None
        if any(keyword in combined_lower for keyword in SEMANTIC_AUTH_KEYWORDS):
            return ("auth_guard", action_lineno, "Guard checks authorization or permissions before continuing.")
        if self._looks_like_validation_guard(combined):
            return ("validation_guard", action_lineno, "Guard rejects invalid or missing input before continuing.")
        return None

    def _record_semantic_ref(
        self,
        refs: List[Dict[str, object]],
        node: SymbolNode,
        signal: str,
        start_line: int,
        end_line: int,
        reason: str,
    ) -> None:
        refs.append(
            {
                "signal": signal,
                "file": node.file,
                "lines": [start_line, max(start_line, end_line)],
                "reason": reason,
            }
        )

    def _has_direct_js_like_network_call(self, text: str) -> bool:
        stripped = text.strip()
        if re.match(
            r"^(?:export\s+)?(?:default\s+)?(?:public\s+|private\s+|protected\s+|static\s+|readonly\s+|override\s+)*"
            r"(?:async\s+)?fetch\s*\([^)]*\)\s*\{",
            stripped,
        ):
            return False
        if re.match(
            r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+fetch\s*\(",
            stripped,
        ):
            return False
        if re.search(r"(?<![\w$.])fetch\s*\(", text):
            return True
        if re.search(r"\baxios(?:\.[A-Za-z_]\w*)?\s*\(", text):
            return True
        if re.search(r"\bhttps?\.request\s*\(", text):
            return True
        return False

    def _extract_semantic_signals(self) -> None:
        for node in self.nodes.values():
            node.semantic_signals.clear()
            node.semantic_evidence_spans.clear()
            node.semantic_summary = {}
            node.semantic_weight = 0.0
            node.contained_semantic_signals.clear()
            node.contained_semantic_refs.clear()
            node.contained_semantic_summary = {}
            node.contained_semantic_weight = 0.0

            source_lines = self._node_source_lines(node, direct_semantics=True)

            refs: List[Dict[str, object]] = []
            if source_lines:
                if node.language == "Python":
                    refs = self._extract_python_semantic_spans(node, source_lines)
                elif node.language == "Java":
                    refs = self._extract_java_semantic_spans(node, source_lines)
                elif node.language in {"JavaScript", "TypeScript"}:
                    refs = self._extract_js_like_semantic_spans(node, source_lines)
                elif node.language == "Go":
                    refs = self._extract_go_semantic_spans(node, source_lines)
                elif node.language == "Rust":
                    refs = self._extract_rust_semantic_spans(node, source_lines)
                elif node.language == "CSharp":
                    refs = self._extract_csharp_semantic_spans(node, source_lines)
                elif node.language == "Kotlin":
                    refs = self._extract_kotlin_semantic_spans(node, source_lines)
                elif node.language == "PHP":
                    refs = self._extract_php_semantic_spans(node, source_lines)
                elif node.language == "Ruby":
                    refs = self._extract_ruby_semantic_spans(node, source_lines)

            string_ref_sources = self._incoming_string_ref_sources(node.node_id)
            if string_ref_sources:
                refs.append({
                    "signal": "dynamic_dispatch",
                    "file": node.file,
                    "lines": [node.lines[0], node.lines[0]] if node.lines else [0, 0],
                    "reason": (
                        f"Invoked via {len(string_ref_sources)} dynamic string "
                        f"reference(s) - renaming this symbol silently breaks callers."
                    ),
                })

            refs = self._dedupe_semantic_refs(refs, limit=12)
            io_refs = [ref for ref in refs if str(ref.get("signal", "")) in SEMANTIC_EXTERNAL_IO_SIGNALS]
            if io_refs and not any(str(ref.get("signal", "")) == "external_io" for ref in refs):
                primary_ref = sorted(io_refs, key=self._semantic_ref_sort_key)[0]
                refs.append(
                    {
                        "signal": "external_io",
                        "file": node.file,
                        "lines": list(primary_ref["lines"]),
                        "reason": f"Touches an external boundary via `{primary_ref['signal']}`.",
                    }
                )
                refs = self._dedupe_semantic_refs(refs, limit=12)

            signals = self._sort_semantic_signals(str(ref.get("signal", "")) for ref in refs)
            node.semantic_signals = signals
            node.semantic_evidence_spans = refs
            node.semantic_weight = round(sum(SEMANTIC_SIGNAL_WEIGHTS.get(signal, 0.0) for signal in signals), 2)
            if signals:
                node.semantic_summary = self._semantic_summary_for_node(node, signals, refs)
        self._populate_contained_semantics()

    def _populate_contained_semantics(self) -> None:
        for node in self.nodes.values():
            if node.kind not in SEMANTIC_CONTAINER_KINDS:
                continue
            refs: List[Dict[str, object]] = []
            descendant_nodes = [
                child
                for child in self._semantic_child_nodes(node)
                if child.semantic_signals
            ]
            for child in descendant_nodes:
                refs.extend(list(child.semantic_evidence_spans))
            refs = self._dedupe_semantic_refs(refs, limit=12)
            signals = self._sort_semantic_signals(str(ref.get("signal", "")) for ref in refs)
            node.contained_semantic_signals = signals
            node.contained_semantic_refs = refs
            node.contained_semantic_weight = round(
                sum(SEMANTIC_SIGNAL_WEIGHTS.get(signal, 0.0) for signal in signals),
                2,
            )
            if signals:
                node.contained_semantic_summary = {
                    "signal_count": len(signals),
                    "evidence_count": len(refs),
                    "descendant_node_count": len(descendant_nodes),
                    "top_signal": signals[0],
                    "boundary_signals": [signal for signal in signals if signal in SEMANTIC_BOUNDARY_SIGNALS],
                    "side_effect_signals": [signal for signal in signals if signal in SEMANTIC_SIDE_EFFECT_SIGNALS],
                    "guard_signals": [signal for signal in signals if signal in SEMANTIC_GUARD_SIGNALS],
                }

    def _propagate_guard_signals(self) -> None:
        """Populate reachable_guards on each node: guard signals from callers at depth <= 2."""
        rev_adj: Dict[str, Set[str]] = defaultdict(set)
        for src, dsts in self.adj.items():
            for dst in dsts:
                if src != dst:
                    rev_adj[dst].add(src)

        for node_id, node in self.nodes.items():
            node.reachable_guards = set()
            depth1: Set[str] = rev_adj.get(node_id, set())
            for caller_id in depth1:
                caller = self.nodes.get(caller_id)
                if caller:
                    node.reachable_guards.update(
                        s for s in caller.semantic_signals
                        if s in SEMANTIC_GUARD_SIGNALS
                    )
            for caller_id in depth1:
                for caller2_id in rev_adj.get(caller_id, set()):
                    caller2 = self.nodes.get(caller2_id)
                    if caller2:
                        node.reachable_guards.update(
                            s for s in caller2.semantic_signals
                            if s in SEMANTIC_GUARD_SIGNALS
                        )

    def _evaluate_arch_rules(self, node: "SymbolNode") -> List[Dict[str, object]]:
        """Return architectural-warning dicts for every anti-pattern rule that fires."""
        if not node.semantic_signals:
            return []
        warnings: List[Dict[str, object]] = []
        own: Set[str] = set(node.semantic_signals)
        reach: Set[str] = node.reachable_guards
        all_guards: Set[str] = own | reach

        if "input_boundary" in own:
            if "auth_guard" not in all_guards and "validation_guard" not in all_guards:
                warnings.append({
                    "rule": "unguarded_entry",
                    "severity": "critical",
                    "message": (
                        "Accepts external input without authentication or validation guard "
                        "anywhere in the 2-level call chain."
                    ),
                })

        if "deserialization" in own and "validation_guard" not in all_guards:
            warnings.append({
                "rule": "untrusted_deserialization",
                "severity": "critical",
                "message": (
                    "Deserializes external data without a validation guard - "
                    "classic injection or RCE risk."
                ),
            })

        if "concurrency" in own and "state_mutation" in own and "error_handling" not in own:
            warnings.append({
                "rule": "concurrent_mutation",
                "severity": "high",
                "message": (
                    "Concurrent execution combined with mutable state and no error handling - "
                    "race condition or deadlock risk."
                ),
            })

        if "caching" in own and "state_mutation" in own and "concurrency" in own:
            warnings.append({
                "rule": "cache_coherence_risk",
                "severity": "high",
                "message": (
                    "Cache writes combined with concurrent state mutation - "
                    "stale reads or write-after-write conflicts possible."
                ),
            })

        if "network_io" in own and "error_handling" not in own and "error_handling" not in reach:
            warnings.append({
                "rule": "open_network_call",
                "severity": "high",
                "message": (
                    "Outbound network call with no error handling in this symbol or its callers - "
                    "failures propagate silently."
                ),
            })

        if "database_io" in own and "state_mutation" in own and "auth_guard" not in all_guards:
            warnings.append({
                "rule": "unguarded_db_write",
                "severity": "high",
                "message": (
                    "Writes to the database without an authentication guard "
                    "in this symbol or its callers."
                ),
            })

        if "orm_dynamic_load" in own and "dynamic_dispatch" in own:
            warnings.append({
                "rule": "double_indirection",
                "severity": "medium",
                "message": (
                    "Dynamic ORM load combined with string-based dispatch - "
                    "two layers of runtime indirection make this symbol hard to trace statically."
                ),
            })

        if "input_boundary" in own and "state_mutation" in own and "validation_guard" not in own:
            warnings.append({
                "rule": "stateful_input_boundary",
                "severity": "medium",
                "message": (
                    "Mutates state from an external input boundary without first validating "
                    "the input - save-before-validate pattern."
                ),
            })

        return warnings

    def _compute_architectural_warnings(self) -> None:
        """Populate architectural_warnings on every node by evaluating all anti-pattern rules."""
        for node in self.nodes.values():
            node.architectural_warnings = self._evaluate_arch_rules(node)

    def _extract_python_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            lower = text.lower()
            stripped = lower.strip()
            if (
                re.search(r"\b(?:requests|httpx|urllib(?:\.request)?|aiohttp\.ClientSession)\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bboto3\.(?:client|resource|Session)\s*\(", text)
                or re.search(r"\bbotocore\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bgrpc\.(?:insecure_channel|secure_channel)\s*\(", text)
                or re.search(r"\bgoogle\.cloud\.", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "Calls a Python HTTP or cloud client.")
            if (
                re.search(r"\bopen\s*\(", text)
                or re.search(r"\bPath\s*\(", text)
                or re.search(r"\.(?:read_text|write_text|read_bytes|write_bytes)\s*\(", text)
                or re.search(r"\bos\.(?:remove|unlink|rename|replace|makedirs)\s*\(", text)
                or re.search(r"\bshutil\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\baiofiles\.open\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno, "Touches the filesystem from Python code.")
            if (
                re.search(r"\b(?:subprocess\.[A-Za-z_]\w*|os\.(?:system|popen|spawnv|execv)|asyncio\.create_subprocess_(?:exec|shell))\s*\(", text)
                or re.search(r"@(?:\w+\.)?(?:task|shared_task)\s*(?:\(|$)", text)
            ):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno, "Starts or controls a process from Python code.")
            if (
                re.search(r"\b(?:sqlite3|aiosqlite)\.connect\s*\(", text)
                or re.search(r"\b(?:cursor|session|db|conn|connection)\.(?:execute|query|commit|rollback|add|delete|merge|get)\s*\(", text)
                or re.search(r"\.objects\.(?:filter|get|create|update|delete|all|exclude|annotate|aggregate|bulk_create)\s*\(", text)
                or re.search(r"\bself\.[A-Za-z_]\w*\.(?:save|delete)\s*\(\s*\)", text)
                or re.search(r"\b(?:conn|connection)\.(?:fetch|fetchrow|fetchval|execute)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Touches a database or session API.")
            frappe_db_match = _FRAPPE_DB_RE.search(text)
            if _FRAPPE_ORM_LOAD_RE.search(text) or frappe_db_match:
                self._record_semantic_ref(refs, node, "orm_dynamic_load", lineno, lineno, "Invokes Frappe ORM dynamic load.")
            if frappe_db_match:
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Touches a Frappe database API.")
            if re.search(r"\bfrappe\.db\.(?:set_value|delete)\s*\(", text):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates database state via Frappe DB API.")
            if re.search(r"\bos\.(?:environ|getenv)\b", text) or re.search(r"\b(?:configparser|dotenv)\b", text) or re.search(r"\btomllib\.(?:load|loads)\s*\(", text):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads configuration or environment state.")
            if re.search(r"\b(?:json|pickle|yaml)\.(?:dump|dumps|safe_dump)\s*\(", text):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno, "Serializes structured data.")
            if re.search(r"\b(?:json|pickle|yaml)\.(?:load|loads|safe_load)\s*\(", text):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno, "Deserializes structured data.")
            if re.search(r"\b(?:datetime\.(?:now|utcnow)|time\.[A-Za-z_]\w*|random\.[A-Za-z_]\w*|uuid\.[A-Za-z_]\w*|secrets\.[A-Za-z_]\w*)\s*\(", text):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno, "Uses time or randomness sources.")
            if (
                re.search(r"\bself\.[A-Za-z_]\w*\s*=", text)
                or re.search(r"\bself\.[A-Za-z_]\w*\[", text)
                or re.search(r"\bself\.[A-Za-z_]\w*\.(?:append|extend|insert|update|setdefault|pop|remove|clear|add|discard)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates object state via `self`.")
            if (
                re.search(r"\binput\s*\(", text)
                or re.search(r"@\w*(?:route|get|post|put|delete|patch)\b", lower)
                or re.search(r"\brequest\.(?:GET|POST|data|body|json|form|files|args)\b", text)
                or re.search(r"\b(?:Body|Query|Form|Header|Cookie|Depends)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "Reads data at an input boundary.")
            if re.search(
                r"\b(?:jsonify|Response|JSONResponse|HTMLResponse|StreamingResponse|FileResponse|"
                r"ORJSONResponse|RedirectResponse|PlainTextResponse|UJSONResponse|"
                r"HttpResponse|JsonResponse|HttpResponseRedirect|StreamingHttpResponse)\s*\(",
                text,
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Produces boundary-facing output.")
            if re.search(r"@(?:login_required|permission_required|jwt_required|token_required|requires_auth|authenticated|auth_required|requires_permission)\b", text):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "Auth/permission decorator guards this callable.")
            if (
                re.search(r"\bmodel_validate(?:_json)?\s*\(", text)
                or re.search(r"\bBaseModel\s*\(", text)
                or re.search(r"\b(?:schema|Schema)\.(?:load|loads|validate)\s*\(", text)
                or re.search(r"\b(?:form|serializer)\.(?:is_valid|validate)\s*\(", text)
                or re.search(r"\.validate_on_submit\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Invokes schema or form validation.")
            if stripped.startswith("try:") or stripped.startswith("except") or re.search(r"\braise\b", lower):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno, "Contains explicit Python error handling.")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
            if (
                re.search(r"\bthreading\.(?:Thread|Lock|RLock|Event|Semaphore|Condition|Barrier)\b", text)
                or re.search(r"\bconcurrent\.futures\.(?:ThreadPoolExecutor|ProcessPoolExecutor|as_completed|wait)\b", text)
                or re.search(r"\bmultiprocessing\.(?:Process|Pool|Queue|Pipe|Lock|Manager)\b", text)
                or re.search(r"\basyncio\.(?:create_task|gather|wait|wait_for|Lock|Semaphore|Queue|Event|Barrier|TaskGroup)\s*[\(\[]", text)
                or re.search(r"\bqueue\.(?:Queue|SimpleQueue|LifoQueue|PriorityQueue)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                          "Spawns threads, coroutines, or uses Python concurrency primitives.")
            if (
                re.search(r"@(?:functools\.)?(?:lru_cache|cache)\b", text)
                or re.search(r"\bfunctools\.lru_cache\s*\(", text)
                or re.search(r"\bredis(?:\.asyncio)?\.(?:Redis|StrictRedis)\s*\(", text)
                or re.search(r"\bcachetools\.(?:cached|LRUCache|TTLCache|LFUCache|MRUCache|RRCache)\b", text)
                or re.search(r"\bdiskcache\.Cache\s*\(", text)
                or re.search(r"\bcache\.(?:get|set|delete|add|incr|decr|get_many|set_many)\s*\(", text)
                or re.search(r"\bdjango\.core\.cache\b", text)
            ):
                self._record_semantic_ref(refs, node, "caching", lineno, lineno,
                                          "Uses an in-memory or distributed cache.")

        if "frappe" in self.active_plugins and node.file.endswith("hooks.py"):
            for index, (lineno, text) in enumerate(source_lines):
                if re.search(r'\bdoc_events\s*=\s*\{', text):
                    self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno,
                                             "Frappe doc_events hook — registers document event handlers.")
                if re.search(r'\bscheduler_events\s*=\s*\{', text):
                    self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno,
                                             "Frappe scheduler_events — registers time-driven tasks.")
                if re.search(r'\boverride_whitelisted_methods\s*=\s*\{', text):
                    self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno,
                                             "Frappe override_whitelisted_methods — alters API access control.")
        return refs

    def _extract_java_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            lower = text.lower()
            stripped = lower.strip()
            if stripped.startswith("import ") or stripped.startswith("package "):
                continue
            if re.search(r"@(?:RestController|Controller|RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestParam|RequestBody|PathVariable)\b", text):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "Framework annotation marks a request boundary.")
            if (
                re.search(r"@(?:PreAuthorize|RolesAllowed|Secured)\b", text)
                or re.search(r"\bSecurityContextHolder\.getContext\(\)", text)
                or re.search(r"\bauthenticationManager\.authenticate\s*\(", text)
                or re.search(r"\bjwtService\.(?:validate|verify|parseToken|extractUsername)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "Security annotation guards the execution path.")
            if re.search(r"@(?:Valid|Validated|NotNull|NotBlank|NotEmpty|Size|Min|Max|Pattern)\b", text) or "objects.requirenonnull" in lower:
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Validation annotation or guard constrains inputs.")
            if "responseentity" in lower or "@responsebody" in lower or re.search(r"\breturn\s+ResponseEntity\.", text):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Returns a boundary-facing response object.")
            if re.search(r"\b(?:RestTemplate|WebClient|HttpClient|OkHttpClient|Feign|CloseableHttpClient|HttpGet|HttpPost|HttpPut|HttpDelete|HttpPatch)\b", text):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "Calls a Java HTTP client.")
            if re.search(r"\b(?:Files|Paths|FileInputStream|FileOutputStream|BufferedWriter|BufferedReader)\b", text):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno, "Touches the filesystem from Java code.")
            if re.search(r"\b(?:ProcessBuilder|Runtime\.getRuntime\(\)\.exec)\b", text):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno, "Starts or controls a process from Java code.")
            if (
                re.search(r"\b(?:System\.getenv|System\.getProperty)\s*\(", text)
                or re.search(r"@(?:Value|ConfigurationProperties)\b", text)
                or re.search(r"\benv\.getProperty\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads configuration or environment state.")
            if re.search(r"\b(?:ObjectMapper|Gson)\.(?:writeValue|writeValueAsString|toJson)\s*\(", text):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno, "Serializes structured data.")
            if re.search(r"\b(?:ObjectMapper|Gson)\.(?:readValue|fromJson)\s*\(", text):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno, "Deserializes structured data.")
            if re.search(r"\b(?:Instant\.now|LocalDate(?:Time)?\.now|System\.currentTimeMillis|Random|ThreadLocalRandom|UUID\.randomUUID)\b", text):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno, "Uses time or randomness sources.")
            if re.search(r"\bthis\.[A-Za-z_]\w*\s*=", text):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates object state via `this`.")
            if re.search(r"\b(?:try|catch)\b", text) or re.search(r"\bthrow\b", text):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno, "Contains explicit Java error handling.")
            if re.search(r"\b(?:jdbcTemplate|entityManager)\.[A-Za-z_]\w*\s*\(", text) or re.search(r"\.(?:findById|save|delete|createQuery|queryForObject|query)\s*\(", text):
                repository_match = any(
                    member_type.endswith("Repository")
                    and re.search(rf"\b(?:this\.)?{re.escape(member_name)}\.[A-Za-z_]\w*\s*\(", text)
                    for member_name, member_type in node.member_types.items()
                )
                if repository_match or "jdbctemplate" in lower or "entitymanager" in lower:
                    self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Calls a repository or database-oriented dependency.")
            if re.search(r"@(?:Transactional|Query|Modifying|NamedQuery|NativeQuery)\b", text):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Calls a repository or database-oriented dependency.")
            if re.search(
                r"@(?:KafkaListener|RabbitListener|SqsListener|EventListener|JmsListener)\b",
                text,
            ):
                self._record_semantic_ref(
                    refs, node, "input_boundary", lineno, lineno,
                    "Message-listener annotation marks this method as a queue/event consumer.",
                )
            if re.search(r"@Async\b", text):
                self._record_semantic_ref(
                    refs, node, "process_io", lineno, lineno,
                    "@Async marks a method that runs in a separate thread pool.",
                )
            if re.search(r"@(?:Cacheable|CacheEvict|CachePut|Caching)\b", text):
                self._record_semantic_ref(
                    refs, node, "caching", lineno, lineno,
                    "Spring cache annotation reads or writes a shared cache store.",
                )
            if re.search(r"@Scheduled\b", text):
                self._record_semantic_ref(
                    refs, node, "time_or_randomness", lineno, lineno,
                    "@Scheduled drives execution by a time-based trigger.",
                )
            if (
                re.search(r"\bnew Thread\s*\(", text)
                or re.search(r"\bExecutors?\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bCompletableFuture\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bForkJoinPool\b", text)
                or re.search(r"\bCountDownLatch\b|\bCyclicBarrier\b|\bPhaser\b", text)
                or re.search(r"\bReentrantLock\b|\bReentrantReadWriteLock\b|\bStampedLock\b", text)
                or re.search(r"\bsynchronized\s*\(", text)
                or re.search(r"\bAtomicInteger\b|\bAtomicLong\b|\bAtomicReference\b|\bAtomicBoolean\b", text)
                or re.search(r"\bBlockingQueue\b|\bLinkedBlockingQueue\b|\bArrayBlockingQueue\b", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                          "Uses Java threading or concurrency primitives.")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs

    def _extract_js_like_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            lower = text.lower()
            if self._has_direct_js_like_network_call(text):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "Calls a JavaScript/TypeScript network client.")
            if re.search(r"\b(?:fs|fs/promises)\b", lower) or re.search(r"\b(?:readFile|writeFile|appendFile|mkdir|unlink|rm)\s*\(", text):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno, "Touches the filesystem from JS/TS code.")
            if re.search(r"\b(?:child_process|exec|execSync|spawn|spawnSync|fork)\s*\(", text):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno, "Starts or controls a process from JS/TS code.")
            if "process.env" in lower or "import.meta.env" in lower:
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads runtime configuration or environment variables.")
            if re.search(r"\bJSON\.stringify\s*\(", text):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno, "Serializes data to JSON.")
            if re.search(r"\bJSON\.parse\s*\(", text) or re.search(r"\bresponse\.json\s*\(", lower):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno, "Deserializes data from JSON.")
            if re.search(r"\b(?:Date\.now|new Date|Math\.random|crypto\.randomUUID)\b", text):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno, "Uses time or randomness sources.")
            if re.search(r"\bthis\.[A-Za-z_$][\w$]*\s*=", text):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates object state via `this`.")
            if re.search(r"\b(?:try|catch)\b", text) or re.search(r"\bthrow\b", text):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno, "Contains explicit JS/TS error handling.")
            if re.search(r"\b(?:function|async function)\b", text) and re.search(r"\((?:[^)]*\b(?:req|request|res|response)\b[^)]*)\)", text):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "Handler signature accepts request/response boundary objects.")
            if re.search(r"\b(?:req|request)\.(?:body|query|params|headers)\b", lower) or re.search(r"\brequest\.(?:json|formData)\s*\(", text):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "Reads request-boundary input data.")
            if (
                re.search(r"@(?:Get|Post|Put|Delete|Patch|Options|Head)\s*\(", text)
                or re.search(r"@(?:Body|Param|Query|Headers|Req|Res|UploadedFile)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "NestJS route or parameter decorator marks an input boundary.")
            if re.search(r"\b(?:res\.(?:json|send|status|render|sendFile|download|redirect)|NextResponse|Response\.json|new Response)\b", text):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Produces boundary-facing output.")
            if (
                re.search(r"\bprisma\.[A-Za-z_]\w*\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\b(?:mongoose|Model)\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\b(?:getRepository|getConnection|createQueryBuilder)\s*\(", text)
                or re.search(r"\bknex\s*\(", text)
                or re.search(r"\b(?:pool|client|db)\.(?:query|execute|connect)\s*\(", text)
                or re.search(r"\bdrizzle\s*\(", text)
                or re.search(r"\bdb\.(?:select|insert|update|delete)\s*\(\s*\)", text)
                or re.search(r"\bnew (?:Redis|IORedis)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Calls a JS/TS database client.")
            if (
                re.search(r"\bjwt\.(?:verify|decode|sign)\s*\(", text)
                or re.search(r"\bpassport\.(?:authenticate|authorize)\s*\(", text)
                or re.search(r"\b(?:verifyToken|checkAuth|requireAuth|isAuthenticated|ensureLoggedIn)\s*\(", text)
                or re.search(r"\bbcrypt\.(?:hash|compare|hashSync|compareSync)\s*\(", text)
                or re.search(r"\bargon2\.(?:hash|verify)\s*\(", text)
                or re.search(r"@UseGuards\s*\(", text)
                or re.search(r"\bsupabase\.auth\.[A-Za-z_]\w*\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "Enforces authentication or token verification.")
            if (
                re.search(r"\bz\.[a-z]\w*\(\s*\)\.(?:parse|safeParse|parseAsync)\s*\(", text)
                or re.search(r"\bz\.(?:parse|safeParse)\s*\(", text)
                or re.search(r"\b(?:schema|Schema)\.(?:parse|validate|validateSync|validateAsync)\s*\(", text)
                or re.search(r"\bjoi\.[a-z]\w*\(\s*\)\.validate\s*\(", text)
                or re.search(r"\b(?:yup\.|Yup\.)\w+\(\s*\)\.validate\s*\(", text)
                or re.search(
                    r"@(?:IsEmail|IsString|IsNumber|IsInt|IsBoolean|IsDate|IsOptional|IsNotEmpty|"
                    r"IsArray|IsUUID|Length|MinLength|MaxLength|IsEnum|Matches|IsNotEmptyObject)\s*\(",
                    text,
                )
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Invokes schema validation (Zod/Joi/Yup).")
            if (
                re.search(r"\bnew Worker\s*\(", text)
                or re.search(r"\bSharedArrayBuffer\b", text)
                or re.search(r"\bAtomics\.", text)
                or re.search(r"\bPromise\.(?:all|race|allSettled|any)\s*\(", text)
                or re.search(r"\bworker_threads\b", text)
                or re.search(r"\bcluster\.fork\s*\(", text)
                or re.search(r"\bnew (?:MessageChannel|BroadcastChannel)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                          "Uses workers, parallel Promise composition, or shared-memory primitives.")
            if (
                re.search(r"\blru[-_]cache\b|\bLRUCache\s*\(|\bnew LRU\s*\(", text, re.IGNORECASE)
                or re.search(r"\bnew NodeCache\s*\(", text)
                or re.search(r"\bunstable_cache\s*\(", text)
                or re.search(r"\buseMemo\s*\(|\buseCallback\s*\(|\bReact\.memo\s*\(", text)
                or re.search(r"\bredis\.(?:get|set|setex|getset|mget|mset|del|expire|exists)\s*\(", lower)
            ):
                self._record_semantic_ref(refs, node, "caching", lineno, lineno,
                                          "Uses a cache (LRU, Redis client, React memo, or Next.js unstable_cache).")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs

    def _extract_go_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            if (
                re.search(r"\bhttp\.(?:Get|Post|Head|PostForm|NewRequest)\s*\(", text)
                or re.search(r"\bclient\.(?:Do|Get|Post|Head)\s*\(", text)
                or re.search(r"\bresty\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bgrpc\.(?:Dial|NewClient)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "Calls a Go HTTP or gRPC client.")
            if (
                re.search(r"\b(?:db\.(?:Query|Exec)|sql\.Open)\s*\(", text)
                or re.search(r"\bdb\.(?:Where|Find|First|Last|Create|Save|Delete|Update|Updates|Preload|Joins)\s*\(", text)
                or re.search(r"\b(?:pgxpool|pgx)\.(?:New|Connect)\s*\(", text)
                or re.search(r"\b(?:pool|conn)\.(?:QueryRow|Query|Exec|Begin|SendBatch)\s*\(", text)
                or re.search(r"\bredis\.NewClient\s*\(", text)
                or re.search(r"\bmongo\.(?:Connect|NewClient)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Touches a Go database handle.")
            if re.search(r"\b(?:os\.Open|os\.Create|os\.WriteFile|os\.ReadFile|ioutil\.ReadFile|bufio\.New(?:Reader|Writer|Scanner))\s*\(", text):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno, "Touches the filesystem from Go code.")
            if re.search(r"\bexec\.Command\s*\(", text):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno, "Starts a process from Go code.")
            if (
                re.search(r"\bos\.(?:Getenv|LookupEnv)\s*\(", text)
                or re.search(r"\bviper\.(?:Get|GetString|GetInt(?:Slice)?|GetBool|GetFloat64|GetDuration|GetStringSlice|GetStringMap|GetStringMapString)\s*\(", text)
                or re.search(r"\bgodotenv\.(?:Load|Overload|Read)\s*\(", text)
                or re.search(r"\benvconfig\.Process\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads environment or configuration state.")
            if (
                re.search(r"\bhttp\.(?:HandleFunc|ListenAndServe)\b", text)
                or re.search(r"func\s*\(\s*\w+\s+http\.ResponseWriter\s*,\s*\w+\s+\*http\.Request", text)
                or re.search(r"\*gin\.Context\b", text)
                or re.search(r"\becho\.Context\b", text)
                or re.search(r"\*fiber\.Ctx\b", text)
                or re.search(r"\bc\.(?:Param|Query|FormValue|Bind|ShouldBind(?:JSON|Query)?|BodyParser|QueryParam)\s*\(", text)
                or re.search(r"\bchi\.URLParam\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "Declares an HTTP boundary in Go code.")
            if "if err != nil" in text:
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno, "Contains explicit Go error handling.")
            if re.search(r"\b(?:time\.Now|rand\.)\b", text):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno, "Uses time or randomness sources.")
            if (
                re.search(r"\br\.Header\.Get\s*\(\s*[\"']Authorization", text)
                or re.search(r"\bjwt\.(?:Parse|ParseWithClaims|Valid)\b", text)
                or re.search(r"\b(?:Middleware|middleware)\.(?:Auth|JWT|Token|Bearer)\b", text)
                or re.search(r"\bctx\.Value\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "Enforces authentication in Go code.")
            if (
                re.search(r"\bvalidate\.(?:Struct|Var|StructPartial|StructExcept|VarWithValue)\s*\(", text)
                or re.search(r"\bvalidation\.(?:Validate|ValidateStruct|ValidateMap)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Invokes Go struct/field validation (go-playground/validator or ozzo-validation).")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
            if (
                re.search(r"\b(?:w\.Write|w\.WriteHeader|json\.NewEncoder\s*\(\s*w\s*\)\.Encode|http\.(?:Error|Redirect|ServeFile|ServeContent))\s*\(", text)
                or re.search(r"\bc\.(?:JSON|String|HTML|XML|File|Redirect|Status|Send|SendString|SendStatus|NoContent|Render|Blob|Attachment|AbortWithStatus(?:JSON)?|IndentedJSON|PureJSON|JSONP)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Writes an HTTP response from Go code.")
            if re.search(r"\bjson\.Marshal(?:Indent)?\s*\(", text):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno, "Serializes structured data in Go.")
            if re.search(r"\bjson\.(?:Unmarshal|NewDecoder)\s*\(", text):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno, "Deserializes structured data in Go.")
            if re.search(r"\b[a-z]\w*\.[A-Za-z_]\w*\s*=(?!=)", text):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates a struct field in Go.")
            if (
                re.search(r"\bgo\s+[A-Za-z_]", text)
                or re.search(r"\bmake\s*\(\s*chan\b", text)
                or re.search(r"\bsync\.(?:Mutex|RWMutex|WaitGroup|Once|Map|Cond)\b", text)
                or re.search(r"\batomic\.(?:Add|Load|Store|Swap|CompareAndSwap)\b", text)
                or re.search(r"\bsync/atomic\b", text)
                or re.search(r"\bselect\s*\{", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                          "Spawns a goroutine or uses Go concurrency primitives.")
            if (
                re.search(r"\bbigcache\.New(?:BigCache)?\s*\(", text)
                or re.search(r"\bfreecache\.NewCache\s*\(", text)
                or re.search(r"\bristretto\.NewCache\s*\(", text)
                or re.search(r"\bgocache\.New\s*\(", text)
                or re.search(r"\bgroupcache\.NewGroup\s*\(", text)
                or re.search(r"\bsync\.Pool\s*\{", text)
            ):
                self._record_semantic_ref(refs, node, "caching", lineno, lineno,
                                          "Uses a Go in-process or distributed cache.")
        return refs

    def _extract_rust_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            if (
                re.search(r"\breqwest::\b", text)
                or re.search(r"\bclient\.(?:execute|get|post|put|delete|head|request)\s*\(", text)
                or re.search(r"\bhyper::\b", text)
                or re.search(r"\bsurf::\b", text)
                or re.search(r"\bureq::\b", text)
                or re.search(r"\btonic::\b", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "Calls a Rust HTTP or gRPC client.")
            if re.search(r"\b(?:std::fs::|tokio::fs::|async_std::fs::|File::(?:open|create))\b", text):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno, "Touches the filesystem from Rust code.")
            if re.search(r"\bCommand::new\s*\(", text):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno, "Starts a process from Rust code.")
            if (
                re.search(r"\bstd::env::(?:var|var_os)\s*\(", text)
                or re.search(r"\bdotenv::dotenv\s*\(", text)
                or re.search(r"\benvy::(?:from_env|prefixed)\s*\(", text)
                or re.search(r"\bconfig::Config\b", text)
                or re.search(r"\bfigment::Figment\b", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads environment or configuration state.")
            if re.search(r"\b(?:SystemTime::now|rand::)\b", text) or re.search(r"\buuid::Uuid::new_v\d\b", text):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno, "Uses time or randomness sources.")
            if re.search(r"\.(?:unwrap|expect)\s*\(", text) or re.search(r"\?\s*(?:;|$)", text.rstrip()) or re.search(r"\bErr\s*\(", text):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno, "Contains explicit Rust error handling.")
            if (
                re.search(r"\b(?:diesel::|sqlx::|tokio_postgres::|sea_orm::|rusqlite::)\b", text)
                or re.search(r"\.(?:execute|query|query_as|fetch_one|fetch_all|fetch_optional)\s*\(", text)
                or re.search(r"\bEntityTrait::[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bredis::(?:Client|Connection|Commands|AsyncCommands)\b", text)
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Touches a Rust database client.")
            if re.search(r"\bserde_json::(?:to_string|to_vec|to_writer)\s*\(", text):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno, "Serializes structured data in Rust.")
            if re.search(r"\bserde_json::(?:from_str|from_reader|from_slice|from_value)\s*\(", text):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno, "Deserializes structured data in Rust.")
            if re.search(r"\bself\.[A-Za-z_]\w*\s*=(?!=)", text):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates self state in Rust.")
            if (
                re.search(r"#\[(?:get|post|put|delete|patch|head|options)\s*\(", text)
                or re.search(r"\b(?:web::Path|web::Json|web::Query|web::Form|HttpRequest)\b", text)
                or re.search(r"\baxum::extract::\b", text)
                or re.search(r"\bextract::(?:Json|Path|Query|Form|State|TypedHeader)\b", text)
                or re.search(r"\baxum::routing::\b", text)
                or re.search(r"\blapin::\b", text)
                or re.search(r"\brdkafka::consumer::\b", text)
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "Declares a Rust HTTP input boundary.")
            if (
                re.search(r"\bHttpResponse::(?:Ok|Created|BadRequest|Unauthorized|Forbidden|NotFound|InternalServerError)\s*\(", text)
                or re.search(r"\bweb::Json\s*\(", text)
                or re.search(r"\bimpl\s+Responder\b", text)
                or re.search(r"\bimpl\s+IntoResponse\b", text)
                or re.search(r"\baxum::response::", text)
                or re.search(r"\bStatusCode::[A-Z_]{2,}\b", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Produces a Rust HTTP response.")
            if (
                re.search(r"\bbearer_token\b", text)
                or re.search(r"\bjwt::decode\s*::<", text)
                or re.search(r"Authorization.*Bearer\b", text)
                or re.search(r"\bIdentity::(?:identity|remember|forget)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "Enforces authentication in Rust code.")
            if (
                re.search(r"\bValidate::validate\s*\(", text)
                or re.search(r"\bvalidate\.(?:Struct|Var|StructPartial)\s*\(", text)
                or re.search(r"\.validate\s*\(\s*&\s*\(\s*\)\s*\)", text)
                or re.search(r"\bvalidator::validate_\w+\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Invokes Rust struct/field validation (validator/garde crate).")
            if (
                re.search(r"\bthread::spawn\s*\(", text)
                or re.search(r"\bArc::new\s*\(", text)
                or re.search(r"\bMutex::new\s*\(|\bRwLock::new\s*\(", text)
                or re.search(r"\bmpsc::(?:channel|sync_channel)\s*\(", text)
                or re.search(r"\btokio::spawn\s*\(", text)
                or re.search(r"\bsmol::spawn\s*\(|\basync_std::task::spawn\s*\(", text)
                or re.search(r"\brayon::(?:spawn|scope|join)\s*\(", text)
                or re.search(r"\bcrossbeam(?:_channel)?::\b", text)
                or re.search(r"\bAtomicUsize\b|\bAtomicBool\b|\bAtomicI32\b|\bAtomicU64\b", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                          "Spawns threads or uses Rust concurrency primitives.")
            if (
                re.search(r"\bmoka::(?:Cache|future::Cache)\b", text)
                or re.search(r"#\[cached\]", text)
                or re.search(r"\bonce_cell::sync::", text)
                or re.search(r"\blazy_static!\b", text)
                or re.search(r"\bstd::sync::(?:OnceLock|LazyLock)\b", text)
                or re.search(r"\blru::LruCache\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "caching", lineno, lineno,
                                          "Uses a Rust cache crate or lazy-initialised global.")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs

    def _extract_csharp_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            lower = text.lower()
            if re.search(r"\[(?:HttpGet|HttpPost|HttpPut|HttpDelete|HttpPatch|Route|ApiController|FromBody|FromRoute|FromQuery|FromForm|FromHeader)\b", text):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "ASP.NET Core route or parameter attribute marks an input boundary.")
            if (
                re.search(r"\[(?:Authorize|RequireAuthorization)\b", text)
                or re.search(r"\bjwtHandler\.ValidateToken\s*\(", text)
                or re.search(r"\bTokenValidationParameters\b", text)
                or re.search(r"\bClaimsPrincipal\b", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "ASP.NET Core authorization attribute or JWT validation.")
            if (
                re.search(r"\[(?:Required|StringLength|Range|RegularExpression|EmailAddress|MinLength|MaxLength|Phone|Url|Compare)\b", text)
                or re.search(r"\bModelState\.IsValid\b", text)
                or re.search(r"\bValidationContext\b", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Data-annotation attribute or ModelState validation.")
            if (
                re.search(r"\b_?[Cc]ontext\.[A-Za-z_]\w*\.(?:Add|Remove|Update|Find|FindAsync|FirstOrDefault|FirstOrDefaultAsync|ToList|ToListAsync|Where|Any|Count|Single|SingleOrDefault|SaveChanges|SaveChangesAsync)\s*\(", text)
                or re.search(r"\bDbContext\b", text)
                or re.search(r"\bIDbConnection\b", text)
                or re.search(r"\b\.ExecuteNonQuery\s*\(|\b\.ExecuteScalar\s*\(|\b\.ExecuteReader\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Entity Framework or ADO.NET database access.")
            if (
                re.search(r"\b_?[Hh]ttp[Cc]lient\.(?:GetAsync|PostAsync|SendAsync|PutAsync|DeleteAsync|PatchAsync)\s*\(", text)
                or re.search(r"\bnew HttpClient\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "HttpClient network call.")
            if (
                re.search(r"\bFile\.(?:ReadAllText|WriteAllText|ReadAllLines|WriteAllLines|ReadAllBytes|WriteAllBytes|AppendAllText|Open|Create|Delete|Exists|Copy|Move)\s*\(", text)
                or re.search(r"\bDirectory\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bnew (?:FileStream|StreamReader|StreamWriter|BinaryReader|BinaryWriter)\s*\(", text)
                or re.search(r"\bPath\.(?:Combine|GetFullPath|GetFileName|GetDirectoryName)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno, "File system access in C# code.")
            if re.search(r"\bProcess\.Start\s*\(", text):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno, "Process.Start spawns an OS process.")
            if (
                re.search(r"\bEnvironment\.GetEnvironmentVariable\s*\(", text)
                or re.search(r"\bIConfiguration\b", text)
                or re.search(r"\bconfiguration\[", lower)
                or re.search(r"\.GetSection\s*\(|\.GetValue\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads configuration or environment state.")
            if re.search(r"\bJsonSerializer\.(?:Serialize|SerializeAsync)\s*\(|\bJsonConvert\.SerializeObject\s*\(", text):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno, "Serializes data to JSON.")
            if re.search(r"\bJsonSerializer\.(?:Deserialize|DeserializeAsync)\s*\(|\bJsonConvert\.DeserializeObject\s*\(", text):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno, "Deserializes data from JSON.")
            if (
                re.search(r"\bDateTime\.(?:Now|UtcNow)\b", text)
                or re.search(r"\bGuid\.NewGuid\s*\(", text)
                or re.search(r"\bnew Random\s*\(|\bRandomNumberGenerator\b", text)
                or re.search(r"\bDateTimeOffset\.(?:Now|UtcNow)\b", text)
            ):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno, "Uses time or randomness sources.")
            if (
                re.search(r"\bthis\.[A-Za-z_]\w*\s*=(?!=)", text)
                or re.search(r"\b_[A-Za-z_]\w*\s*=(?!=)", text)
            ):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates instance state in C#.")
            if re.search(r"\b(?:try|catch|throw)\b", text):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno, "Contains explicit C# error handling.")
            if (
                re.search(r"\breturn\s+(?:Ok|Created|BadRequest|NotFound|Unauthorized|Forbidden|NoContent|Conflict|StatusCode)\s*\(", text)
                or re.search(r"\bIActionResult\b|\bActionResult\b", text)
                or re.search(r"\bContentResult\b|\bJsonResult\b|\bObjectResult\b", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "ASP.NET Core action returns a boundary-facing response.")
            if (
                re.search(r"\bnew Thread\s*\(", text)
                or re.search(r"\bTask\.(?:Run|Factory\.StartNew|WhenAll|WhenAny|Delay)\s*\(", text)
                or re.search(r"\bParallel\.(?:For|ForEach|Invoke)\s*\(", text)
                or re.search(r"\bCancellationToken(?:Source)?\b", text)
                or re.search(r"\bSemaphoreSlim\b|\bMutex\b", text)
                or re.search(r"\bMonitor\.(?:Enter|Exit|Wait|Pulse)\b", text)
                or re.search(r"\bChannel\.Create(?:Unbounded|Bounded)\s*\(", text)
                or re.search(r"\bThreadPool\.QueueUserWorkItem\s*\(", text)
                or re.search(r"\bInterlocked\.(?:Add|Increment|Decrement|Exchange|CompareExchange)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                          "Uses C# threading or async concurrency primitives.")
            if (
                re.search(r"\bIMemoryCache\b|\bIDistributedCache\b", text)
                or re.search(r"\bcache\.(?:Get|Set|TryGetValue|GetOrCreate|GetOrCreateAsync|Remove)\s*\(", text)
                or re.search(r"\bMemoryCache\b|\bDistributedCache\b", text)
                or re.search(r"\[ResponseCache\b", text)
                or re.search(r"\bOutputCache(?:Attribute)?\b", text)
            ):
                self._record_semantic_ref(refs, node, "caching", lineno, lineno,
                                          "Uses ASP.NET Core memory or distributed caching.")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs

    def _extract_kotlin_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            if re.search(
                r"@(?:GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|"
                r"RequestMapping|RestController|Controller|KafkaListener|"
                r"RabbitListener|SqsListener|EventListener|JmsListener)\b",
                text,
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "HTTP route or message-listener annotation marks an input boundary.")
            if re.search(
                r"@(?:Secured|PreAuthorize|PostAuthorize|RolesAllowed)\b"
                r"|SecurityContextHolder\b"
                r"|\bAuthentication\b",
                text,
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "Spring Security annotation or context access.")
            if re.search(
                r"@(?:Valid|Validated|NotNull|NotEmpty|NotBlank|Size|Min|Max|Email|Pattern|"
                r"Positive|Negative|DecimalMin|DecimalMax|AssertTrue|AssertFalse)\b",
                text,
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Bean Validation annotation enforces input constraints.")
            if re.search(
                r"@(?:Query|Insert|Update|Delete|Dao|Entity|Repository)\b"
                r"|\bRoom\.databaseBuilder\s*\("
                r"|\bJdbcTemplate\b"
                r"|\btransaction\s*\{"
                r"|\bDatabase\.connect\s*\(",
                text,
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Database access via Room/JPA/Exposed.")
            if (
                re.search(r"\bHttpClient\s*\(|\bnew HttpClient\b", text)
                or re.search(r"\bOkHttpClient\s*\(", text)
                or re.search(r"\bRetrofit\.Builder\s*\(", text)
                or re.search(r"\b(?:WebClient|RestTemplate)\b", text)
                or re.search(r"client\.(?:get|post|put|delete|patch)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "HTTP client network call.")
            if (
                re.search(r"\bFile\s*\(", text)
                or re.search(r"\.readText\s*\(|\.writeText\s*\(|\.readLines\s*\(|\.appendText\s*\(", text)
                or re.search(r"\bPaths\.get\s*\(|\bFiles\.\w+\s*\(", text)
                or re.search(r"\bnew FileInputStream\b|\bnew FileOutputStream\b", text)
            ):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno, "File system access in Kotlin code.")
            if (
                re.search(
                    r"\b(?:launch|async|runBlocking|withContext|GlobalScope\.launch|"
                    r"CoroutineScope|supervisorScope|coroutineScope)\s*[{\(]",
                    text,
                )
                or re.search(r"\bMutex\(\)|\bSemaphore\(\)", text)
                or re.search(r"\bChannel<", text)
                or re.search(r"\bnew Thread\s*\(|\bExecutors?\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bStateFlow\b|\bSharedFlow\b|\bMutableStateFlow\b", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                          "Coroutine builder or concurrency primitive creates a concurrent execution context.")
            if (
                re.search(r"@(?:Value|ConfigurationProperties)\b", text)
                or re.search(r"\bSystem\.getenv\s*\(", text)
                or re.search(r"\benvironment\.getProperty\s*\(|\benvironment\.getRequiredProperty\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads configuration or environment variable.")
            if (
                re.search(r"\bJson\.encodeToString\s*\(", text)
                or re.search(r"\bjacksonObjectMapper\s*\(\)|\.writeValueAsString\s*\(", text)
                or re.search(r"\bGson\s*\(\)\.toJson\s*\(", text)
                or re.search(r"@Serializable\b", text)
            ):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno, "Serializes object to JSON.")
            if (
                re.search(r"\bJson\.decodeFromString\s*\(", text)
                or re.search(r"\.readValue\s*\(", text)
                or re.search(r"\bGson\s*\(\)\.fromJson\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno, "Deserializes object from JSON.")
            if (
                re.search(r"\bSystem\.currentTimeMillis\s*\(|\bSystem\.nanoTime\s*\(", text)
                or re.search(r"\bLocalDateTime\.now\s*\(|\bInstant\.now\s*\(|\bClock\.systemUTC\s*\(", text)
                or re.search(r"\bUUID\.randomUUID\s*\(", text)
                or re.search(r"\bRandom\.nextInt\b|\bRandom\.nextLong\b|\bkotlin\.random\.Random\b", text)
                or re.search(r"@Scheduled\b", text)
            ):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno, "Uses time or randomness sources.")
            if (
                re.search(r"@(?:Cacheable|CacheEvict|CachePut|Caching)\b", text)
                or re.search(r"\bCaffeineCache\b|\bEhcache\b", text)
                or re.search(r"\bcache\.(?:get|put|evict|putIfAbsent)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "caching", lineno, lineno,
                                          "Spring cache annotation or cache API reads or writes a shared cache store.")
            if (
                re.search(r"\b(?:try|catch|throw)\b", text)
                or re.search(r"\brun[Cc]atching\s*\{", text)
                or re.search(r"\.onFailure\s*\{|\.getOrThrow\s*\(|\.getOrElse\s*\{", text)
            ):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno, "Contains explicit Kotlin error handling.")
            if (
                re.search(r"\b(?:println|print)\s*\(", text)
                or re.search(r"\blog(?:ger)?\.(?:info|warn|error|debug|trace)\s*\(", text)
                or re.search(r"\bResponseEntity\b|\bcall\.respond\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Produces observable output (log, response).")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs

    def _extract_php_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            if (
                re.search(r"\bRoute::(?:get|post|put|delete|patch|any)\s*\(", text)
                or re.search(r"#\[(?:Route|Get|Post|Put|Delete|Patch)\b", text)
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno,
                                          "Laravel route definition or HTTP attribute marks an input boundary.")
            if (
                re.search(r"\bAuth::(?:check|user|guard|id)\s*\(", text)
                or re.search(r"\bauth\s*\(\s*\)->(?:user|check|id)\s*\(", text)
                or re.search(r"\$request->user\s*\(", text)
                or re.search(r"#\[Authorize\b", text)
                or re.search(r"->middleware\s*\(\s*['\"]auth", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno,
                                          "Laravel Auth guard or authorization middleware.")
            if (
                re.search(r"\$request->validate\s*\(", text)
                or re.search(r"\bValidator::make\s*\(", text)
                or re.search(r"#\[Rule\b", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno,
                                          "Laravel/Symfony validation enforces input constraints.")
            if (
                re.search(r"\bnew\s+PDO\s*\(", text)
                or re.search(r"\$(?:pdo|db)->(?:query|prepare|exec|execute|fetchAll|fetch)\s*\(", text)
                or re.search(r"\bmysqli_\w+\s*\(|\$mysqli->(?:query|prepare|execute)\s*\(", text)
                or re.search(r"\bDB::(?:select|insert|update|delete|table|statement)\s*\(", text)
                or re.search(r"::(?:find|findOrFail|where|create|update|delete|first|all|save)\s*\(", text)
                or re.search(r"->(?:where|select|from|join|orderBy|groupBy|having|get|first|count|save)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno,
                                          "Database access via PDO/MySQLi/Eloquent/Doctrine.")
            if (
                re.search(r"\bcurl_(?:init|exec|setopt)\s*\(", text)
                or re.search(r"\$(?:http)?[Cc]lient->(?:get|post|put|delete|request|send)\s*\(", text)
                or re.search(r"\bHttp::(?:get|post|put|delete|withHeaders|withToken)\s*\(", text)
                or re.search(r"\bfile_get_contents\s*\(\s*['\"]https?://", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno,
                                          "HTTP client or remote file fetch.")
            if (
                re.search(r"\bfile_(?:get_contents|put_contents|exists|delete)\s*\(", text)
                or re.search(r"\b(?:fopen|fclose|fwrite|fread|fgets|fputs)\s*\(", text)
                or re.search(r"\b(?:unlink|mkdir|rmdir|glob|scandir|opendir|readdir)\s*\(", text)
                or re.search(r"\bStorage::(?:put|get|delete|disk|exists|download)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno,
                                          "File system access in PHP code.")
            if re.search(r"\b(?:exec|shell_exec|system|passthru|proc_open|popen)\s*\(", text):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno,
                                          "PHP shell-execution function spawns an OS process.")
            if (
                re.search(r"\bgetenv\s*\(", text)
                or re.search(r"\$_(?:ENV|SERVER)\b", text)
                or re.search(r"\bconfig\s*\(\s*['\"]", text)
                or re.search(r"\benv\s*\(\s*['\"]", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno,
                                          "Reads configuration or environment variable.")
            if re.search(r"\bjson_encode\s*\(|\bserialize\s*\(", text):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno,
                                          "Serializes data to JSON or PHP format.")
            if re.search(r"\bjson_decode\s*\(|\bunserialize\s*\(", text):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno,
                                          "Deserializes data from JSON or PHP format.")
            if (
                re.search(r"\btime\s*\(\s*\)|\bmicrotime\s*\(|\bdate\s*\(|\bstrtotime\s*\(", text)
                or re.search(r"\brand\s*\(|\bmt_rand\s*\(|\brandom_int\s*\(|\brandom_bytes\s*\(", text)
                or re.search(r"\bStr::(?:uuid|random|orderedUuid)\s*\(", text)
                or re.search(r"\bCarbon::(?:now|today|parse)\s*\(", text)
                or re.search(r"\bnew\s+\\\?DateTime\s*\(|\bnew\s+DateTimeImmutable\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno,
                                          "Uses time or randomness sources.")
            if re.search(r"\$_SESSION\b", text):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno,
                                          "Mutates PHP session state.")
            if (
                re.search(r"\bCache::(?:get|put|forget|forever|remember|has|pull|flush|tags)\s*\(", text)
                or re.search(r"\bcache\s*\(\s*\)->(?:get|put|forget|remember)\s*\(", text)
                or re.search(r"\bRedis::(?:get|set|setex|expire|del)\s*\(", text)
                or re.search(r"\bnew Memcached\s*\(|\$memcache->(?:get|set|delete)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "caching", lineno, lineno,
                                          "Reads or writes a Laravel/Redis/Memcached cache.")
            if re.search(r"\b(?:try|catch|throw)\b", text):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno,
                                          "Contains explicit PHP error handling.")
            if (
                re.search(r"\becho\b|\bprint\b", text)
                or re.search(r"\bresponse\s*\(\s*\)->json\s*\(", text)
                or re.search(r"\breturn\s+response\s*\(", text)
                or re.search(r"\breturn\s+(?:new\s+)?JsonResponse\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno,
                                          "Produces observable output (echo, response).")
            if (
                re.search(r"\\parallel\\(?:Runtime|Channel|Future)\b", text)
                or re.search(r"\bpcntl_fork\s*\(", text)
                or re.search(r"\bQueue::(?:push|bulk|later)\s*\(", text)
                or re.search(r"\bdispatch(?:Now)?\s*\(\s*new\s+", text)
                or re.search(r"\bReact\\EventLoop\b", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                          "Dispatches async jobs or uses PHP concurrency extension.")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs

    def _extract_ruby_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            if (
                re.search(r"\b(?:get|post|put|delete|patch|resources?|namespace)\s+['\"/]", text)
                or re.search(r"\bRoutes\.draw\b", text)
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno,
                                          "Rails/Sinatra route definition marks an input boundary.")
            if (
                re.search(r"\bbefore_action\s+:authenticate_user[!?]?", text)
                or re.search(r"\bauthenticate_user[!?]\s*\(", text)
                or re.search(r"\bauthorize[!?]?\s*\(", text)
                or re.search(r"\bcurrent_user\b", text)
                or re.search(r"\buser_signed_in\?\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno,
                                          "Devise/CanCanCan authentication or authorization check.")
            if (
                re.search(r"\bvalidates\s+:", text)
                or re.search(r"\bvalidate\s+:", text)
                or re.search(r"\bvalid\?\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno,
                                          "ActiveRecord validation enforces data constraints.")
            if (
                re.search(r"\b(?:ActiveRecord::Base|ApplicationRecord)\b", text)
                or re.search(r"\.(?:where|find|find_by|create|save[!?]?|update[!?]?|destroy[!?]?|first|last|all|count|exists\?)\s*[(\{]", text)
                or re.search(r"\b(?:where|find|find_by|create|save[!?]?|update[!?]?|destroy[!?]?|exists\?)\s*[(\{]", text)
                or re.search(r"\bconnection\.execute\s*\(", text)
                or re.search(r"\bDB\[|Sequel\.connect\b", text)
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno,
                                          "ActiveRecord or Sequel database access.")
            if (
                re.search(r"\bNet::HTTP\b", text)
                or re.search(r"\bFaraday\.new\b|\bfaraday\b", text)
                or re.search(r"\bHTTParty\.(?:get|post|put|delete)\b", text)
                or re.search(r"\bRestClient\.(?:get|post|put|delete)\b", text)
                or re.search(r"\bopen\s*\(\s*['\"]https?://", text)
                or re.search(r"\bURI\.open\b|\bURI\.parse\b", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno,
                                          "HTTP client or remote URI access.")
            if (
                re.search(r"\bFile\.(?:read|write|open|exist[s]?|delete|rename|expand_path|join)\s*\(", text)
                or re.search(r"\bDir\.(?:glob|mkdir|entries|foreach)\s*\(", text)
                or re.search(r"\bFileUtils\.\w+\s*\(", text)
                or re.search(r"\bIO\.(?:read|write|popen)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno,
                                          "File system access in Ruby code.")
            if (
                re.search(r"`[^`]+`", text)
                or re.search(r"\b(?:system|exec|spawn)\s*\(", text)
                or re.search(r"\bOpen3\.(?:popen\d?|capture\d|pipeline)\b", text)
                or re.search(r"\bProcess\.spawn\b", text)
            ):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno,
                                          "Shell command execution in Ruby.")
            if (
                re.search(r"\bENV\s*\[", text)
                or re.search(r"\bRails\.application\.config\b", text)
                or re.search(r"\bRails\.env\b", text)
                or re.search(r"\bRails\.configuration\b", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno,
                                          "Reads configuration or environment variable.")
            if (
                re.search(r"\.to_json\b", text)
                or re.search(r"\bJSON\.(?:generate|dump)\s*\(", text)
                or re.search(r"\bMarshal\.dump\s*\(", text)
                or re.search(r"\.to_xml\b|\bActiveSupport::JSON\.encode\b", text)
            ):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno,
                                          "Serializes data to JSON/XML.")
            if (
                re.search(r"\bJSON\.parse\s*\(", text)
                or re.search(r"\bMarshal\.load\s*\(", text)
                or re.search(r"\bActiveSupport::JSON\.decode\b", text)
            ):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno,
                                          "Deserializes data from JSON.")
            if (
                re.search(r"\bTime\.(?:now|current|zone\.now)\b", text)
                or re.search(r"\bDateTime\.(?:now|current)\b", text)
                or re.search(r"\bDate\.today\b", text)
                or re.search(r"\bSecureRandom\.(?:uuid|hex|random_bytes)\s*\(", text)
                or re.search(r"\brand\s*\(|\bRandom\.rand\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno,
                                          "Uses time or randomness sources.")
            if re.search(r"\bsession\s*\[", text):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno,
                                          "Mutates Rails session state.")
            if (
                re.search(r"\bRails\.cache\.(?:write|fetch|delete|read|exist\?|clear)\s*\(", text)
                or re.search(r"\bRedis\.new\b|\bRedis::Client\b", text)
                or re.search(r"\bDalli::Client\b", text)
                or re.search(r"\bmemoize\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "caching", lineno, lineno,
                                          "Reads or writes a Rails/Redis/Memcached cache.")
            if re.search(r"\brescue\b|\braise\b", text):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno,
                                          "Contains explicit Ruby error handling.")
            if (
                re.search(r"\brender\s+(?:json:|template:|partial:|html:|nothing:)", text)
                or re.search(r"\bredirect_to\s*\(", text)
                or re.search(r"\bputs\s*\(|\bp\s+\w", text)
                or re.search(r"\bRails\.logger\.\w+\b|\blogger\.\w+\b", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno,
                                          "Produces observable output (render, log, puts).")
            if (
                re.search(r"\bThread\.(?:new|start)\s*[\{\(]", text)
                or re.search(r"\bMutex\.new\b|\.synchronize\s*\{", text)
                or re.search(r"\bQueue\.new\b", text)
                or re.search(r"\bConcurrent::(?:Future|Promise|IVar|Actor|ThreadPoolExecutor)\b", text)
                or re.search(r"\bperform_async\s*\(|\bperform_later\s*\(", text)
                or re.search(r"\bSidekiq::Worker\b|\bResque::Job\b", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                          "Spawns threads or delegates work to a background-job framework.")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs

    def _semantic_summary_for_node(
        self,
        node: SymbolNode,
        signals: List[str],
        refs: List[Dict[str, object]],
    ) -> Dict[str, object]:
        return {
            "signal_count": len(signals),
            "evidence_count": len(refs),
            "top_signal": signals[0] if signals else "",
            "boundary_signals": [signal for signal in signals if signal in SEMANTIC_BOUNDARY_SIGNALS],
            "side_effect_signals": [signal for signal in signals if signal in SEMANTIC_SIDE_EFFECT_SIGNALS],
            "guard_signals": [signal for signal in signals if signal in SEMANTIC_GUARD_SIGNALS],
            "ambiguity_count": len(node.unresolved_call_details),
        }

    def _behavioral_step_sort_key(self, step: Dict[str, object]) -> Tuple[int, int, int, str, str]:
        lines = step.get("lines", [0, 0])
        start = int(lines[0]) if isinstance(lines, list) and lines else 0
        end = int(lines[1]) if isinstance(lines, list) and len(lines) > 1 else start
        step_kind = str(step.get("step_kind", ""))
        return (
            start,
            end,
            BEHAVIORAL_FLOW_STEP_ORDER.get(step_kind, 999),
            step_kind,
            str(step.get("reason", "")),
        )

    def _dedupe_behavioral_flow_steps(
        self,
        steps: List[Dict[str, object]],
        limit: int = 12,
    ) -> List[Dict[str, object]]:
        seen: Set[str] = set()
        out: List[Dict[str, object]] = []
        for step in sorted(steps, key=self._behavioral_step_sort_key):
            key = json.dumps(
                {
                    "step_kind": step.get("step_kind", ""),
                    "file": step.get("file", ""),
                    "lines": step.get("lines", []),
                    "semantic_signal": step.get("semantic_signal", ""),
                    "anchor_symbol": step.get("anchor_symbol", ""),
                },
                sort_keys=True,
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(step)
            if len(out) >= limit:
                break
        return out

    def _compact_behavioral_step_kinds(self, step_kinds: Iterable[str]) -> List[str]:
        ordered: List[str] = []
        for step_kind in step_kinds:
            if not step_kind:
                continue
            if not ordered or ordered[-1] != step_kind:
                ordered.append(step_kind)
        return ordered

    def _build_behavioral_flow_steps(self, node: SymbolNode) -> List[Dict[str, object]]:
        if node.kind not in SEMANTIC_EXECUTABLE_KINDS or not node.semantic_evidence_spans:
            return []
        raw_steps: List[Dict[str, object]] = []
        for ref in node.semantic_evidence_spans:
            signal = str(ref.get("signal", ""))
            if signal not in BEHAVIORAL_FLOW_STEP_SIGNALS:
                continue
            lines = list(ref.get("lines", [node.lines[0], node.lines[0]]))
            start_line = int(lines[0])
            end_line = int(lines[1]) if len(lines) > 1 else start_line
            reason = str(ref.get("reason", ""))
            if (
                signal == "output_boundary"
                and start_line <= int(node.lines[0])
                and "response object" in reason.lower()
            ):
                continue
            raw_steps.append(
                {
                    "step_kind": signal,
                    "file": node.file,
                    "lines": [start_line, end_line],
                    "reason": reason,
                    "semantic_signal": signal,
                    "anchor_symbol": node.node_id,
                    "provenance_kind": "semantic_evidence",
                }
            )
        steps = self._dedupe_behavioral_flow_steps(raw_steps, limit=12)
        earliest_side_effect_line = min(
            (
                int(step["lines"][0])
                for step in steps
                if str(step.get("step_kind", "")) in SEMANTIC_SIDE_EFFECT_SIGNALS
            ),
            default=0,
        )
        if earliest_side_effect_line:
            steps = [
                step
                for step in steps
                if not (
                    str(step.get("step_kind", "")) == "output_boundary"
                    and int(step["lines"][0]) < earliest_side_effect_line
                    and any(
                        other is not step
                        and list(other.get("lines", [])) == list(step.get("lines", []))
                        and str(other.get("step_kind", "")) != "output_boundary"
                        for other in steps
                    )
                )
            ]
        for index, step in enumerate(steps, start=1):
            start_line = int(step["lines"][0])
            end_line = int(step["lines"][1])
            step["order_index"] = index
            step["step_id"] = f"{node.node_id}::flow_step::{index:02d}:{step['step_kind']}:{start_line}-{end_line}"
        return steps

    def _behavioral_flow_summary_for_node(
        self,
        node: SymbolNode,
        steps: List[Dict[str, object]],
    ) -> Dict[str, object]:
        ordered_step_kinds = self._compact_behavioral_step_kinds(str(step.get("step_kind", "")) for step in steps)
        side_effect_steps = [step for step in steps if str(step.get("step_kind", "")) in SEMANTIC_SIDE_EFFECT_SIGNALS]
        guard_steps = [step for step in steps if str(step.get("step_kind", "")) in {"validation_guard", "auth_guard"}]
        boundary_steps = [step for step in steps if str(step.get("step_kind", "")) in SEMANTIC_BOUNDARY_SIGNALS]
        first_boundary = boundary_steps[0] if boundary_steps else None
        first_side_effect = side_effect_steps[0] if side_effect_steps else None
        output_indexes = [index for index, step_kind in enumerate(ordered_step_kinds) if step_kind == "output_boundary"]
        side_effect_indexes = [
            index
            for index, step_kind in enumerate(ordered_step_kinds)
            if step_kind in SEMANTIC_SIDE_EFFECT_SIGNALS
        ]
        has_terminal_output = bool(output_indexes and (not side_effect_indexes or output_indexes[-1] > side_effect_indexes[-1]))
        return {
            "step_count": len(steps),
            "ordered_step_kinds": ordered_step_kinds,
            "boundary_to_side_effect": bool(first_boundary and first_side_effect and int(first_boundary["order_index"]) < int(first_side_effect["order_index"])),
            "first_boundary_step_kind": str(first_boundary.get("step_kind", "")) if first_boundary else "",
            "first_side_effect_step_kind": str(first_side_effect.get("step_kind", "")) if first_side_effect else "",
            "guard_count": len(guard_steps),
            "side_effect_count": len(side_effect_steps),
            "has_terminal_output": has_terminal_output,
            "has_error_path": "error_handling" in ordered_step_kinds,
            "flow_compact_string": " -> ".join(ordered_step_kinds),
        }

    def _extract_behavioral_flows(self) -> None:
        for node in self.nodes.values():
            node.behavioral_flow_steps = []
            node.behavioral_flow_summary = {}
            if node.kind not in SEMANTIC_EXECUTABLE_KINDS:
                continue
            steps = self._build_behavioral_flow_steps(node)
            if not steps:
                continue
            node.behavioral_flow_steps = steps
            node.behavioral_flow_summary = self._behavioral_flow_summary_for_node(node, steps)

    def _node_payload(self, node: SymbolNode) -> Dict[str, object]:
        return {
            "id": node.node_id,
            "language": node.language,
            "kind": node.kind,
            "module": node.module,
            "qualname": node.qualname,
            "file": node.file,
            "lines": node.lines,
            "class_context": node.class_context,
            "package_name": node.package_name,
            "declared_symbols": node.declared_symbols,
            "member_types": {key: node.member_types[key] for key in sorted(node.member_types)},
            "member_qualifiers": {key: node.member_qualifiers[key] for key in sorted(node.member_qualifiers)},
            "annotations": node.annotations,
            "bean_name": node.bean_name,
            "is_abstract": node.is_abstract,
            "di_primary": node.di_primary,
            "coord": node.coord,
            "metrics": {
                "ca": node.ca,
                "ce_internal": node.ce_internal,
                "ce_external": node.ce_external,
                "ce_total": node.ce_total,
                "inheritance_internal": len(node.resolved_bases),
                "inheritance_external": len(node.external_bases),
                "instability": round(node.instability, 4),
                "instability_total": round(node.instability_total, 4),
                "layer": node.layer,
                "pagerank": node.pagerank,
                "betweenness": node.betweenness,
                "git_commit_count": node.git_commit_count,
                "git_churn": node.git_churn,
                "git_hotness": node.git_hotness,
                "scc_id": node.scc_id,
                "scc_size": node.scc_size,
                "recursive_self_call": node.recursive_self_call,
                "resolved_import_count": len(node.resolved_imports),
                "external_import_count": len(node.external_imports),
                "unresolved_import_count": len(node.unresolved_imports),
                "unresolved_call_count": len(node.unresolved_calls),
                "unresolved_base_count": len(node.unresolved_bases),
                "heuristic_candidate_count": len(node.heuristic_candidates),
                "string_ref_count": len(node.resolved_string_refs),
                "semantic_signal_count": len(node.semantic_signals),
                "contained_semantic_signal_count": len(node.contained_semantic_signals),
                "behavioral_flow_step_count": len(node.behavioral_flow_steps),
            },
            "risk_score": node.risk_score,
            "reasons": node.reasons,
            "semantic_signals": list(node.semantic_signals),
            **(
                {
                    "taint_entry": node.taint_entry,
                    "taint_sources": list(node.taint_sources),
                    "tainted_params": dict(node.tainted_params),
                }
                if self.taint_enabled else {}
            ),
            **({"reachable_guards": sorted(node.reachable_guards)} if node.reachable_guards else {}),
            **({"architectural_warnings": list(node.architectural_warnings)} if node.architectural_warnings else {}),
            "resolved_string_refs": sorted(node.resolved_string_refs),
            **({"plugin_data": dict(node.plugin_data)} if node.plugin_data else {}),
            "semantic_evidence_spans": list(node.semantic_evidence_spans),
            "semantic_summary": dict(node.semantic_summary),
            "semantic_weight": node.semantic_weight,
            "contained_semantic_signals": list(node.contained_semantic_signals),
            "contained_semantic_refs": list(node.contained_semantic_refs),
            "contained_semantic_summary": dict(node.contained_semantic_summary),
            "contained_semantic_weight": node.contained_semantic_weight,
            "behavioral_flow_steps": list(node.behavioral_flow_steps),
            "behavioral_flow_summary": dict(node.behavioral_flow_summary),
            "resolved_imports": sorted(node.resolved_imports),
            "resolved_calls": sorted(node.resolved_calls),
            "resolved_bases": sorted(node.resolved_bases),
            "external_imports": sorted(node.external_imports),
            "external_calls": sorted(node.external_calls),
            "external_bases": sorted(node.external_bases),
            "unresolved_imports": sorted(node.unresolved_imports),
            "unresolved_calls": sorted(node.unresolved_calls),
            "unresolved_call_details": {key: node.unresolved_call_details[key] for key in sorted(node.unresolved_call_details)},
            "unresolved_bases": sorted(node.unresolved_bases),
            "heuristic_candidates": {key: node.heuristic_candidates[key] for key in sorted(node.heuristic_candidates)},
        }

    def _top_risks(self, top_n: int) -> List[Dict[str, object]]:
        ranked = sorted(
            self.nodes.values(),
            key=lambda n: (-n.risk_score, -n.ca, -n.ce_total, n.node_id),
        )
        top: List[Dict[str, object]] = []
        for node in ranked[:top_n]:
            top.append(
                {
                    "symbol": node.node_id,
                    "language": node.language,
                    "kind": node.kind,
                    "risk_score": node.risk_score,
                    "single_point_of_failure": bool(node.ca >= 3 and node.risk_score >= 60.0),
                    "metrics": {
                        "ca": node.ca,
                        "ce_internal": node.ce_internal,
                        "ce_external": node.ce_external,
                        "ce_total": node.ce_total,
                        "inheritance_internal": len(node.resolved_bases),
                        "inheritance_external": len(node.external_bases),
                        "instability": round(node.instability, 4),
                        "instability_total": round(node.instability_total, 4),
                        "layer": node.layer,
                        "pagerank": node.pagerank,
                        "betweenness": node.betweenness,
                        "git_hotness": node.git_hotness,
                        "scc_size": node.scc_size,
                    },
                    "location": {
                        "file": node.file,
                        "lines": node.lines,
                    },
                    "coord": node.coord,
                    "reasons": node.reasons,
                    "semantic_signals": list(node.semantic_signals),
                    **({"reachable_guards": sorted(node.reachable_guards)} if node.reachable_guards else {}),
                    **({"architectural_warnings": list(node.architectural_warnings)} if node.architectural_warnings else {}),
                    "semantic_summary": dict(node.semantic_summary),
                    "semantic_weight": node.semantic_weight,
                    "contained_semantic_signals": list(node.contained_semantic_signals),
                    "contained_semantic_summary": dict(node.contained_semantic_summary),
                    "contained_semantic_weight": node.contained_semantic_weight,
                    "behavioral_flow_summary": dict(node.behavioral_flow_summary),
                    "behavioral_flow_steps": list(node.behavioral_flow_steps[:6]),
                }
            )
        return top

    def _module_report(self) -> List[Dict[str, object]]:
        modules = sorted({n.module for n in self.nodes.values()})
        outgoing: Dict[str, Set[str]] = {m: set() for m in modules}
        incoming: Dict[str, Set[str]] = {m: set() for m in modules}

        for src, dsts in self.adj.items():
            src_mod = self.nodes[src].module
            for dst in dsts:
                dst_mod = self.nodes[dst].module
                if src_mod == dst_mod:
                    continue
                outgoing[src_mod].add(dst_mod)
                incoming[dst_mod].add(src_mod)

        out: List[Dict[str, object]] = []
        max_ca = max((len(incoming[m]) for m in modules), default=1) or 1
        for mod in modules:
            ca = len(incoming[mod])
            ce = len(outgoing[mod])
            total = ca + ce
            instability = round(ce / total, 4) if total else 0.0
            risk = round((0.6 * instability + 0.4 * (ca / max_ca)) * 100.0, 2)
            out.append(
                {
                    "module": mod,
                    "metrics": {"ca": ca, "ce": ce, "instability": instability},
                    "risk_score": risk,
                }
            )
        return sorted(out, key=lambda x: (-x["risk_score"], x["module"]))

    def _build_project_inventory(self) -> Dict[str, object]:
        extension_counts: Dict[str, int] = defaultdict(int)
        candidate_files: List[str] = []
        key_files = {
            "pyproject.toml",
            "requirements.txt",
            "requirements-dev.txt",
            "setup.py",
            "setup.cfg",
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "yarn.lock",
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            ".env",
            ".env.example",
            "README.md",
            "Makefile",
            "go.mod",
            "Cargo.toml",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
        }
        total_file_count = 0
        project_files = self._iter_project_files()

        for rel_path in project_files:
            file_name = os.path.basename(rel_path)
            total_file_count += 1
            suffix = Path(file_name).suffix.lower() or "<no_ext>"
            extension_counts[suffix] += 1
            if file_name in key_files and rel_path not in candidate_files:
                candidate_files.append(rel_path)

        top_extensions = sorted(
            (
                {"extension": ext, "count": count}
                for ext, count in extension_counts.items()
            ),
            key=lambda item: (-item["count"], item["extension"]),
        )[:12]

        top_modules = sorted(
            (
                {"module": item["module"], "risk_score": item["risk_score"]}
                for item in self._module_report()[:8]
            ),
            key=lambda item: (-item["risk_score"], item["module"]),
        )
        language_summary, source_file_insights = self._build_source_file_insights(project_files)
        top_source_files = source_file_insights[:12]

        technologies, manifest_summary = self._detect_project_technologies(project_files, sorted(candidate_files))
        entrypoints = self._detect_project_entrypoints(project_files)
        docs = self._detect_documentation_files(project_files)

        return {
            "total_file_count": total_file_count,
            "graph_node_count": len(self.nodes),
            "python_symbol_count": sum(1 for node in self.nodes.values() if node.language == "Python"),
            "top_extensions": top_extensions,
            "key_files": sorted(candidate_files),
            "likely_technologies": technologies,
            "language_summary": language_summary,
            "entrypoints": entrypoints,
            "documentation_files": docs,
            "manifest_summary": manifest_summary,
            "source_file_insights": source_file_insights,
            "top_source_files": top_source_files,
            "top_modules": top_modules,
        }

    def _detect_project_technologies(
        self,
        project_files: List[str],
        key_files: List[str],
    ) -> Tuple[List[str], Dict[str, object]]:
        technologies: Set[str] = set()
        manifest_summary: Dict[str, object] = {}

        if any(node.language == "Python" for node in self.nodes.values()):
            technologies.add("Python")

        package_json_path = os.path.join(self.root_dir, "package.json")
        if os.path.exists(package_json_path):
            try:
                with open(package_json_path, "r", encoding="utf-8") as handle:
                    package_data = json.load(handle)
                deps = {}
                deps.update(package_data.get("dependencies", {}))
                deps.update(package_data.get("devDependencies", {}))
                dep_names = sorted(deps)
                technologies.add("Node.js")
                if "react" in deps:
                    technologies.add("React")
                if "next" in deps:
                    technologies.add("Next.js")
                if "vite" in deps:
                    technologies.add("Vite")
                if "express" in deps:
                    technologies.add("Express")
                if "@nestjs/core" in deps:
                    technologies.add("NestJS")
                if "vue" in deps:
                    technologies.add("Vue")
                if "nuxt" in deps:
                    technologies.add("Nuxt")
                if "svelte" in deps:
                    technologies.add("Svelte")
                manifest_summary["package_json"] = {
                    "name": package_data.get("name", ""),
                    "scripts": sorted(package_data.get("scripts", {}).keys())[:10],
                    "dependencies": dep_names[:20],
                }
            except (OSError, json.JSONDecodeError):
                manifest_summary["package_json"] = {"error": "Could not parse package.json"}

        if self.js_resolver_configs:
            manifest_summary["js_resolver_configs"] = [
                {
                    "file": str(config.get("config_file", "")),
                    "base_dir": Path(
                        os.path.relpath(str(config.get("base_dir", self.root_dir)), self.root_dir)
                    ).as_posix(),
                    "aliases": sorted(dict(config.get("paths", {})).keys()),
                }
                for config in self.js_resolver_configs[:10]
            ]

        pyproject_path = os.path.join(self.root_dir, "pyproject.toml")
        if tomllib is not None and os.path.exists(pyproject_path):
            try:
                with open(pyproject_path, "rb") as handle:
                    pyproject_data = tomllib.load(handle)
                project_section = pyproject_data.get("project", {})
                poetry_section = pyproject_data.get("tool", {}).get("poetry", {})
                deps = project_section.get("dependencies", [])
                poetry_deps = sorted(k for k in poetry_section.get("dependencies", {}).keys() if k != "python")
                flattened_deps = [str(item) for item in deps] + poetry_deps
                dep_blob = " ".join(flattened_deps).lower()
                if "fastapi" in dep_blob:
                    technologies.add("FastAPI")
                if "flask" in dep_blob:
                    technologies.add("Flask")
                if "django" in dep_blob:
                    technologies.add("Django")
                if "pytest" in dep_blob:
                    technologies.add("pytest")
                manifest_summary["pyproject"] = {
                    "name": project_section.get("name") or poetry_section.get("name", ""),
                    "dependencies": flattened_deps[:20],
                }
            except (OSError, ValueError, TypeError):
                manifest_summary["pyproject"] = {"error": "Could not parse pyproject.toml"}

        requirements_files = [
            rel_path
            for rel_path in key_files
            if os.path.basename(rel_path) in {"requirements.txt", "requirements-dev.txt"}
        ]
        if requirements_files:
            reqs: List[str] = []
            for rel_path in requirements_files:
                try:
                    with open(os.path.join(self.root_dir, rel_path), "r", encoding="utf-8") as handle:
                        for raw_line in handle:
                            line = raw_line.strip()
                            if not line or line.startswith("#"):
                                continue
                            reqs.append(re.split(r"[<>=!~]", line, maxsplit=1)[0].strip())
                except OSError:
                    continue
            req_blob = " ".join(reqs).lower()
            if "fastapi" in req_blob:
                technologies.add("FastAPI")
            if "flask" in req_blob:
                technologies.add("Flask")
            if "django" in req_blob:
                technologies.add("Django")
            if "pytest" in req_blob:
                technologies.add("pytest")
            manifest_summary["requirements"] = sorted(set(reqs))[:20]

        if os.path.exists(os.path.join(self.root_dir, "Dockerfile")):
            technologies.add("Docker")

        go_mod_path = os.path.join(self.root_dir, "go.mod")
        if os.path.exists(go_mod_path):
            technologies.add("Go")
            try:
                with open(go_mod_path, "r", encoding="utf-8") as handle:
                    content = handle.read()
                module_match = re.search(r"(?m)^\s*module\s+(.+?)\s*$", content)
                deps = []
                for line in content.splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith("//"):
                        continue
                    stripped = re.sub(r"^require\s+", "", stripped)
                    stripped = stripped.strip("() ").strip()
                    match = re.match(r"^([A-Za-z0-9./_-]+)\s+v[0-9][^\s]*$", stripped)
                    if match:
                        deps.append(match.group(1))
                dep_blob = " ".join(deps).lower()
                if "gin-gonic" in dep_blob:
                    technologies.add("Gin")
                if "spf13/cobra" in dep_blob:
                    technologies.add("Cobra")
                manifest_summary["go_mod"] = {
                    "module": module_match.group(1).strip() if module_match else "",
                    "dependencies": deps[:20],
                }
            except OSError:
                manifest_summary["go_mod"] = {"error": "Could not parse go.mod"}

        cargo_path = os.path.join(self.root_dir, "Cargo.toml")
        if tomllib is not None and os.path.exists(cargo_path):
            technologies.add("Rust")
            try:
                with open(cargo_path, "rb") as handle:
                    cargo_data = tomllib.load(handle)
                deps = sorted(cargo_data.get("dependencies", {}).keys())
                dep_blob = " ".join(deps).lower()
                if "tokio" in dep_blob:
                    technologies.add("Tokio")
                if "actix-web" in dep_blob:
                    technologies.add("Actix Web")
                if "axum" in dep_blob:
                    technologies.add("Axum")
                manifest_summary["cargo_toml"] = {
                    "package": cargo_data.get("package", {}).get("name", ""),
                    "dependencies": deps[:20],
                }
            except (OSError, ValueError, TypeError):
                manifest_summary["cargo_toml"] = {"error": "Could not parse Cargo.toml"}

        pom_path = os.path.join(self.root_dir, "pom.xml")
        if os.path.exists(pom_path):
            technologies.add("Java")
            try:
                tree = ElementTree.parse(pom_path)
                root = tree.getroot()
                artifact = self._xml_find_text(root, "artifactId")
                deps = self._xml_find_all_text(root, "artifactId")
                dep_blob = " ".join(deps).lower()
                if "spring-boot" in dep_blob:
                    technologies.add("Spring Boot")
                if "junit" in dep_blob:
                    technologies.add("JUnit")
                manifest_summary["pom_xml"] = {
                    "artifact_id": artifact,
                    "artifacts": deps[:20],
                }
            except (OSError, ElementTree.ParseError):
                manifest_summary["pom_xml"] = {"error": "Could not parse pom.xml"}

        for rel_path in project_files:
            suffix = Path(rel_path).suffix.lower()
            if suffix in {".ts", ".tsx"}:
                technologies.add("TypeScript")
            if suffix in {".js", ".jsx"}:
                technologies.add("JavaScript")
            if suffix == ".tsx":
                technologies.add("React")
            if suffix == ".go":
                technologies.add("Go")
            if suffix == ".java":
                technologies.add("Java")
            if suffix == ".rs":
                technologies.add("Rust")

        return sorted(technologies), manifest_summary

    def _detect_project_entrypoints(self, project_files: List[str]) -> List[Dict[str, str]]:
        candidates = {
            "main.py": "Common Python entrypoint",
            "app.py": "Common Python application bootstrap",
            "manage.py": "Typical Django entrypoint",
            "wsgi.py": "WSGI application entrypoint",
            "asgi.py": "ASGI application entrypoint",
            "cli.py": "CLI-style Python entrypoint",
            "__main__.py": "Python package entrypoint",
            "package.json": "Node.js manifest with runnable scripts",
            "src/main.ts": "Common frontend bootstrap",
            "src/main.tsx": "Common React bootstrap",
            "src/index.ts": "Common TypeScript bootstrap",
            "src/index.tsx": "Common React bootstrap",
            "src/index.js": "Common JavaScript bootstrap",
            "server.js": "Common Node server entrypoint",
            "server.ts": "Common TypeScript server entrypoint",
            "main.go": "Common Go entrypoint",
            "src/main.rs": "Common Rust binary entrypoint",
            "src/lib.rs": "Common Rust library root",
            "go.mod": "Go module manifest",
            "Cargo.toml": "Rust package manifest",
            "pom.xml": "Java/Maven project manifest",
        }
        out: List[Dict[str, str]] = []
        seen = set()
        for rel_path in project_files:
            normalized = rel_path.replace("\\", "/")
            for candidate, reason in candidates.items():
                if normalized == candidate and normalized not in seen:
                    out.append({"file": rel_path, "reason": reason})
                    seen.add(normalized)
            if re.fullmatch(r"cmd/[^/]+/main\.go", normalized) and normalized not in seen:
                out.append({"file": rel_path, "reason": "Go command entrypoint under cmd/."})
                seen.add(normalized)
            if normalized.endswith("Application.java") and normalized not in seen:
                out.append({"file": rel_path, "reason": "Likely Java application bootstrap."})
                seen.add(normalized)
        return sorted(out, key=lambda item: item["file"])

    def _detect_documentation_files(self, project_files: List[str]) -> List[str]:
        docs: List[str] = []
        for rel_path in project_files:
            normalized = rel_path.replace("\\", "/").lower()
            if normalized in {"readme.md", "readme.txt"}:
                docs.append(rel_path)
            elif normalized.startswith("docs/") and normalized.endswith((".md", ".txt", ".rst")):
                docs.append(rel_path)
        return sorted(docs)[:12]

    def _build_source_file_insights(
        self,
        project_files: List[str],
    ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
        python_nodes_by_file: Dict[str, List[SymbolNode]] = defaultdict(list)
        for node in self.nodes.values():
            python_nodes_by_file[node.file].append(node)

        insights: List[Dict[str, object]] = []
        lang_agg: Dict[str, Dict[str, float]] = defaultdict(lambda: {"file_count": 0, "symbol_count": 0, "entrypoints": 0})
        for rel_path in project_files:
            language = LANGUAGE_BY_SUFFIX.get(Path(rel_path).suffix.lower())
            if not language:
                continue
            insight = self._analyze_source_file(rel_path, language, python_nodes_by_file.get(rel_path, []))
            if not insight:
                continue
            insights.append(insight)
            lang_agg[language]["file_count"] += 1
            lang_agg[language]["symbol_count"] += int(insight["symbol_count"])
            if insight["entrypoint_reason"]:
                lang_agg[language]["entrypoints"] += 1

        insights.sort(
            key=lambda item: (
                -int(bool(item["entrypoint_reason"])),
                -float(item["semantic_score"]),
                item["file"],
            )
        )
        language_summary = [
            {
                "language": language,
                "file_count": int(data["file_count"]),
                "symbol_count": int(data["symbol_count"]),
                "entrypoint_count": int(data["entrypoints"]),
            }
            for language, data in sorted(lang_agg.items(), key=lambda item: (-item[1]["file_count"], item[0]))
        ]
        return language_summary, insights[:20]

    def _analyze_source_file(
        self,
        rel_path: str,
        language: str,
        python_nodes: List[SymbolNode],
    ) -> Optional[Dict[str, object]]:
        content = self._read_project_text(rel_path)
        if content is None:
            return None

        if language == "Python":
            return self._analyze_python_source(rel_path, content, python_nodes)
        if language in {"JavaScript", "TypeScript"}:
            return self._analyze_js_like_source(rel_path, content, language)
        if language == "Go":
            return self._analyze_go_source(rel_path, content)
        if language == "Java":
            return self._analyze_java_source(rel_path, content)
        if language == "Rust":
            return self._analyze_rust_source(rel_path, content)
        return None

    def _analyze_python_source(
        self,
        rel_path: str,
        content: str,
        python_nodes: List[SymbolNode],
    ) -> Dict[str, object]:
        classes = sum(1 for node in python_nodes if node.kind == "class")
        functions = sum(1 for node in python_nodes if node.kind != "class")
        symbols = sorted(node.qualname for node in python_nodes)[:8]
        import_count = len(re.findall(r"(?m)^\s*(?:from|import)\s+", content))
        entrypoint_reason = ""
        if "__name__" in content and "__main__" in content:
            entrypoint_reason = "Contains a Python main guard."
        elif os.path.basename(rel_path) in {"main.py", "app.py", "manage.py"}:
            entrypoint_reason = "Filename suggests a Python entrypoint."
        summary = f"{len(python_nodes)} symbols, {classes} classes, {functions} functions."
        semantic_score = float(len(python_nodes) + import_count + (4 if entrypoint_reason else 0))
        return self._source_insight(
            rel_path,
            "Python",
            len(python_nodes),
            import_count,
            0,
            entrypoint_reason,
            semantic_score,
            symbols,
            summary,
        )

    def _analyze_js_like_source(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        function_names = re.findall(r"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)\s*\(", content)
        class_names = re.findall(r"(?m)^\s*(?:export\s+)?class\s+([A-Za-z_]\w*)\b", content)
        arrow_names = re.findall(
            r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_]\w*)\s*=>",
            content,
        )
        type_names = re.findall(r"(?m)^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_]\w*)\b", content)
        imports = len(re.findall(r"(?m)^\s*import\s+", content)) + len(re.findall(r"\brequire\s*\(", content))
        exports = len(re.findall(r"(?m)^\s*export\s+", content)) + len(re.findall(r"\bmodule\.exports\b", content))
        symbols = self._dedupe(function_names + class_names + arrow_names + type_names)[:10]

        entrypoint_reason = ""
        normalized = rel_path.replace("\\", "/")
        if normalized in {"src/main.ts", "src/main.tsx", "src/index.ts", "src/index.tsx", "src/index.js", "server.js", "server.ts"}:
            entrypoint_reason = "Common frontend or server bootstrap file."
        elif re.search(r"\b(app|server)\.listen\s*\(", content):
            entrypoint_reason = "Starts an HTTP listener."
        elif re.search(r"\bcreateRoot\s*\(", content) or "ReactDOM.render" in content:
            entrypoint_reason = "Bootstraps a React application."

        tags: List[str] = []
        if language == "TypeScript":
            tags.append("typed")
        if Path(rel_path).suffix.lower() in {".jsx", ".tsx"}:
            tags.append("react-ish")
        summary = f"{len(symbols)} named symbols, {imports} imports, {exports} exports."
        semantic_score = float(len(symbols) + imports + exports + (4 if entrypoint_reason else 0))
        return self._source_insight(
            rel_path,
            language,
            len(symbols),
            imports,
            exports,
            entrypoint_reason,
            semantic_score,
            symbols,
            summary,
            tags,
        )

    def _analyze_go_source(self, rel_path: str, content: str) -> Dict[str, object]:
        funcs = re.findall(r"(?m)^\s*func\s+(?:\([^)]+\)\s*)?([A-Za-z_]\w*)\s*\(", content)
        types = re.findall(r"(?m)^\s*type\s+([A-Za-z_]\w*)\s+(?:struct|interface|map|chan|func|\[\])", content)
        imports = len(re.findall(r"(?m)^\s*import\s+", content))
        symbols = self._dedupe(funcs + types)[:10]
        entrypoint_reason = ""
        if os.path.basename(rel_path) == "main.go" and re.search(r"(?m)^\s*package\s+main\s*$", content):
            entrypoint_reason = "Go main package entrypoint."
        elif re.search(r"(?m)^\s*func\s+main\s*\(", content):
            entrypoint_reason = "Contains func main()."
        summary = f"{len(symbols)} named declarations, {imports} import sections."
        semantic_score = float(len(symbols) + imports + (4 if entrypoint_reason else 0))
        return self._source_insight(rel_path, "Go", len(symbols), imports, 0, entrypoint_reason, semantic_score, symbols, summary)

    def _analyze_java_source(self, rel_path: str, content: str) -> Dict[str, object]:
        types = re.findall(r"(?m)^\s*(?:public\s+)?(?:class|interface|enum|record)\s+([A-Za-z_]\w*)\b", content)
        methods = [
            name
            for name in re.findall(
                r"(?m)^\s*(?:public|protected|private)?\s*(?:static\s+)?[A-Za-z0-9_<>\[\], ?]+\s+([A-Za-z_]\w*)\s*\(",
                content,
            )
            if name not in {"if", "for", "while", "switch", "catch", "return", "new"}
        ]
        imports = len(re.findall(r"(?m)^\s*import\s+", content))
        symbols = self._dedupe(types + methods)[:10]
        entrypoint_reason = ""
        if "public static void main" in content:
            entrypoint_reason = "Contains a Java main method."
        elif "@SpringBootApplication" in content:
            entrypoint_reason = "Likely Spring Boot application bootstrap."
        summary = f"{len(symbols)} named declarations, {imports} imports."
        semantic_score = float(len(symbols) + imports + (4 if entrypoint_reason else 0))
        tags = ["spring"] if "@SpringBootApplication" in content or "@RestController" in content else []
        return self._source_insight(rel_path, "Java", len(symbols), imports, 0, entrypoint_reason, semantic_score, symbols, summary, tags)

    def _analyze_rust_source(self, rel_path: str, content: str) -> Dict[str, object]:
        funcs = re.findall(r"(?m)^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)\s*\(", content)
        types = re.findall(r"(?m)^\s*(?:pub\s+)?(?:struct|enum|trait|mod)\s+([A-Za-z_]\w*)\b", content)
        imports = len(re.findall(r"(?m)^\s*use\s+", content))
        symbols = self._dedupe(funcs + types)[:10]
        entrypoint_reason = ""
        if re.search(r"(?m)^\s*fn\s+main\s*\(", content):
            entrypoint_reason = "Rust binary entrypoint."
        elif rel_path.replace("\\", "/") == "src/lib.rs":
            entrypoint_reason = "Rust library root."
        summary = f"{len(symbols)} named declarations, {imports} use statements."
        semantic_score = float(len(symbols) + imports + (4 if entrypoint_reason else 0))
        return self._source_insight(rel_path, "Rust", len(symbols), imports, 0, entrypoint_reason, semantic_score, symbols, summary)

    def _source_insight(
        self,
        rel_path: str,
        language: str,
        symbol_count: int,
        import_count: int,
        export_count: int,
        entrypoint_reason: str,
        semantic_score: float,
        symbols: List[str],
        summary: str,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, object]:
        line_count = len((self._read_project_text(rel_path) or "").splitlines())
        return {
            "file": rel_path,
            "language": language,
            "symbol_count": symbol_count,
            "import_count": import_count,
            "export_count": export_count,
            "line_count": line_count,
            "entrypoint_reason": entrypoint_reason,
            "semantic_score": round(semantic_score, 2),
            "top_symbols": symbols,
            "summary": summary,
            "tags": tags or [],
        }

    def _read_project_text(self, rel_path: str) -> Optional[str]:
        if rel_path in self.project_text_cache:
            return self.project_text_cache[rel_path]
        full_path = os.path.join(self.root_dir, rel_path)
        try:
            with open(full_path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except (OSError, UnicodeDecodeError):
            content = None
        self.project_text_cache[rel_path] = content
        return content

    def _read_project_lines(self, rel_path: str) -> List[str]:
        if rel_path not in self.project_lines_cache:
            content = self._read_project_text(rel_path)
            self.project_lines_cache[rel_path] = content.splitlines() if content is not None else []
        return self.project_lines_cache[rel_path]

    def _xml_find_text(self, root: ElementTree.Element, local_name: str) -> str:
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] == local_name and element.text:
                return element.text.strip()
        return ""

    def _xml_find_all_text(self, root: ElementTree.Element, local_name: str) -> List[str]:
        out: List[str] = []
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] == local_name and element.text:
                out.append(element.text.strip())
        return out

    def _dedupe(self, values: List[str]) -> List[str]:
        seen: Set[str] = set()
        out: List[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out

    def _iter_project_files(self) -> List[str]:
        files: List[str] = []
        for root, dirs, file_names in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if not should_ignore_dir(d)]
            for file_name in file_names:
                files.append(os.path.relpath(os.path.join(root, file_name), self.root_dir))
        return sorted(files)

    def _build_llm_context_slices(
        self,
        evidence_candidates: List[Dict[str, object]],
        inbound: Dict[str, List],
        path_refs_by_anchor: Dict[str, List],
        path_bonus_by_anchor: Dict[str, float],
        ambiguity_watchlist: List[Dict[str, object]],
        line_budget: int,
        primary_budget: int,
    ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
        slice_specs: List[Dict[str, object]] = []
        deferred: List[Dict[str, object]] = []
        focus_symbols: List[Dict[str, object]] = []
        used_lines = 0
        selected_nodes: Set[str] = set()

        for candidate in evidence_candidates:
            node_id = str(candidate["node_id"])
            node = self.nodes[node_id]
            primary_slice = self._annotate_slice_path_refs(dict(candidate["suggested_slices"][0]), path_refs_by_anchor)
            line_count = int(primary_slice["end_line"]) - int(primary_slice["start_line"]) + 1
            must_include = len(selected_nodes) < min(3, len(evidence_candidates))

            selected_for_context = False
            if must_include or used_lines + line_count <= primary_budget:
                slice_specs.append(primary_slice)
                used_lines += line_count
                selected_nodes.add(node_id)
                selected_for_context = True
            else:
                deferred.append(
                    self._build_deferred_request_for_symbol(
                        node_id,
                        "This risk node was deferred because the initial slice budget was exhausted.",
                    )
                )

            focus_symbols.append(
                {
                    "rank": candidate["rank"],
                    "symbol": node_id,
                    "risk_score": candidate["risk_score"],
                    "bundle_priority": candidate["bundle_priority"],
                    "file": node.file,
                    "lines": node.lines,
                    "why": list(candidate["why_selected"]),
                    "dependencies": self._rank_neighbors(self.adj.get(node_id, set())),
                    "dependents": self._rank_neighbors(inbound.get(node_id, set())),
                    "supporting_edge_confidence": candidate["supporting_edge_confidence"],
                    "ambiguity_count": len(candidate["ambiguity_flags"]),
                    "semantic_signals": list(node.semantic_signals),
                    "semantic_summary": dict(node.semantic_summary),
                    "semantic_weight": node.semantic_weight,
                    "contained_semantic_signals": list(node.contained_semantic_signals),
                    "contained_semantic_summary": dict(node.contained_semantic_summary),
                    "contained_semantic_weight": node.contained_semantic_weight,
                    "selected_for_context": selected_for_context,
                }
            )
            deferred.extend(list(candidate["deferred_if_needed"]))

        support_pool: List[Dict[str, object]] = []
        for candidate in evidence_candidates:
            if str(candidate["node_id"]) not in selected_nodes:
                continue
            support_pool.extend(
                self._annotate_slice_path_refs(dict(spec), path_refs_by_anchor)
                for spec in candidate["suggested_slices"][1:]
            )

        for item in ambiguity_watchlist[:4]:
            deferred.append(self._build_deferred_request_for_ambiguity(item))

        support_pool.sort(
            key=lambda spec: (
                -(float(spec.get("selection_score", 0.0)) + max(path_bonus_by_anchor.get(str(symbol), 0.0) for symbol in spec.get("symbols", []) or [""])),
                str(spec.get("selection_confidence_label", "")),
                str(spec.get("file", "")),
                int(spec.get("start_line", 0)),
            )
        )

        for spec in support_pool:
            line_count = int(spec["end_line"]) - int(spec["start_line"]) + 1
            if used_lines + line_count > line_budget:
                continue
            slice_specs.append(spec)
            used_lines += line_count

        return slice_specs, deferred, focus_symbols

    def _build_llm_context_pack(self, top_risks: List[Dict[str, object]], line_budget: int) -> Dict[str, object]:
        inbound = self._inbound_adj()
        confidence_summary = self._build_confidence_summary()
        ambiguity_watchlist = self._build_ambiguity_watchlist()
        evidence_candidates = self._build_evidence_candidates(top_risks, inbound)
        semantic_candidates = self._build_semantic_candidates(limit=10)
        semantic_watchlist = self._build_semantic_watchlist(limit=6)
        evidence_paths = self._build_evidence_paths(evidence_candidates, inbound)[:12]
        path_refs_by_anchor = self._path_refs_by_anchor(evidence_paths)
        path_bonus_by_anchor: Dict[str, float] = defaultdict(float)
        for path in evidence_paths:
            bonus = (float(path.get("path_confidence", 0.0)) * 10.0) + float(len(path.get("hops", [])))
            for item in path.get("recommended_slices", [])[1:]:
                anchor_symbol = str(item.get("anchor_symbol", ""))
                if anchor_symbol:
                    path_bonus_by_anchor[anchor_symbol] = max(path_bonus_by_anchor[anchor_symbol], bonus)
        primary_budget = max(1, int(line_budget * 0.72))
        slice_specs, deferred, focus_symbols = self._build_llm_context_slices(
            evidence_candidates,
            inbound,
            path_refs_by_anchor,
            path_bonus_by_anchor,
            ambiguity_watchlist,
            line_budget,
            primary_budget,
        )

        merged_slices = self._merge_slice_specs(slice_specs)
        merged_slices = [
            self._annotate_slice_path_refs(spec, path_refs_by_anchor)
            for spec in merged_slices
        ]
        selected_symbols = {symbol for spec in merged_slices for symbol in spec["symbols"]}
        best_paths_by_risk_node = self._best_paths_by_risk_node(evidence_paths)
        for risk_node in sorted(best_paths_by_risk_node):
            if risk_node not in selected_symbols:
                continue
            path = best_paths_by_risk_node[risk_node]
            request = self._build_deferred_request_for_path(path, selected_symbols)
            if request is not None:
                deferred.append(request)
        for item in semantic_watchlist[:3]:
            request = self._build_deferred_request_for_semantic_item(item, merged_slices)
            if request is not None:
                deferred.append(request)
        support_chains = [
            candidate["support_chain"]
            for candidate in evidence_candidates
            if str(candidate["node_id"]) in selected_symbols
        ][:8]
        deferred = self._dedupe_object_list(deferred)
        return {
            "strategy": (
                "Read the selected slices first, prefer high-confidence support chains, keep ambiguity compact, "
                "then use short evidence_paths plus semantic signals to justify claims. Request only the smallest "
                "missing structural or semantic follow-up slice when the current evidence is insufficient."
            ),
            "budget": {
                "line_budget": max(1, line_budget),
                "selected_line_count": sum(spec["end_line"] - spec["start_line"] + 1 for spec in merged_slices),
                "selected_symbol_count": len(selected_symbols),
                "deferred_symbol_count": len(deferred),
            },
            "confidence_summary": confidence_summary,
            "focus_symbols": focus_symbols,
            "evidence_candidates": evidence_candidates[:10],
            "semantic_candidates": semantic_candidates,
            "support_chains": support_chains,
            "evidence_paths": evidence_paths,
            "ambiguity_watchlist": ambiguity_watchlist,
            "semantic_watchlist": semantic_watchlist,
            "context_slices": merged_slices,
            "deferred_requests": deferred,
            "audit_prompt": self._build_audit_prompt(),
        }

    def _build_project_context_pack(self, inventory: Dict[str, object]) -> Dict[str, object]:
        recommended_reads: List[Dict[str, str]] = []
        for item in inventory["entrypoints"][:6]:
            recommended_reads.append({"file": item["file"], "why": item["reason"]})
        for rel_path in inventory["documentation_files"][:4]:
            if all(entry["file"] != rel_path for entry in recommended_reads):
                recommended_reads.append({"file": rel_path, "why": "Project documentation or onboarding context."})
        for rel_path in inventory["key_files"][:6]:
            if all(entry["file"] != rel_path for entry in recommended_reads):
                recommended_reads.append({"file": rel_path, "why": "Key manifest or configuration file."})
        for item in inventory["top_source_files"][:4]:
            if all(entry["file"] != item["file"] for entry in recommended_reads):
                recommended_reads.append(
                    {
                        "file": item["file"],
                        "why": (
                            f"Representative {item['language']} source file with {item['symbol_count']} discovered "
                            f"symbols. {item['summary']}"
                        ),
                    }
                )
        for item in self._build_semantic_entrypoints(limit=4):
            if all(entry["file"] != item["file"] for entry in recommended_reads):
                recommended_reads.append(
                    {
                        "file": item["file"],
                        "why": (
                            f"Semantic entrypoint with {', '.join(item['semantic_signals'][:3])} evidence."
                        ),
                    }
                )

        inbound = self._inbound_adj()
        confidence_summary = self._build_confidence_summary()
        ambiguity_watchlist = self._build_ambiguity_watchlist(limit=6)
        semantic_overview = self._build_semantic_overview(limit=8)
        semantic_entrypoints = self._build_semantic_entrypoints(limit=8)
        architecture_evidence = self._build_project_architecture_evidence(recommended_reads, limit=8)
        architecture_evidence_paths = self._build_project_architecture_paths(recommended_reads, inbound, limit=6)
        project_file_slices = self._build_project_file_slices(recommended_reads, architecture_evidence_paths)
        return {
            "strategy": (
                "Understand the project shell first: read stack clues, entrypoints, and key manifests before "
                "descending into implementation details. Use the architecture_evidence, architecture_evidence_paths, "
                "ambiguity_watchlist, direct semantic_entrypoints, and the contained file-level semantic_overview to "
                "decide where confidence is high enough to trust the summary versus where targeted evidence is still needed."
            ),
            "likely_technologies": inventory["likely_technologies"],
            "confidence_summary": confidence_summary,
            "semantic_overview": semantic_overview,
            "semantic_entrypoints": semantic_entrypoints,
            "recommended_reads": recommended_reads[:10],
            "architecture_evidence": architecture_evidence,
            "architecture_evidence_paths": architecture_evidence_paths,
            "ambiguity_watchlist": ambiguity_watchlist,
            "file_slices": project_file_slices,
            "project_prompt": self._build_project_prompt(inventory, recommended_reads[:10]),
        }

    def _build_project_file_slices(
        self,
        reads: List[Dict[str, str]],
        architecture_evidence_paths: Optional[List[Dict[str, object]]] = None,
        max_chars: int = 2200,
    ) -> List[Dict[str, object]]:
        path_refs_by_file: Dict[str, Set[str]] = defaultdict(set)
        for path in architecture_evidence_paths or []:
            path_id = str(path.get("path_id", ""))
            for item in path.get("recommended_slices", []):
                file_name = str(item.get("file", ""))
                if file_name and path_id:
                    path_refs_by_file[file_name].add(path_id)
        slices: List[Dict[str, object]] = []
        for item in reads[:10]:
            rel_path = item["file"]
            full_path = os.path.join(self.root_dir, rel_path)
            try:
                with open(full_path, "r", encoding="utf-8") as handle:
                    content = handle.read()
            except OSError:
                continue

            excerpt = content[:max_chars].strip()
            if len(content) > max_chars:
                excerpt += "\n..."
            line_count = min(len(content.splitlines()), 80)
            semantic_refs = self._semantic_refs_for_file(rel_path, limit=4)
            slices.append(
                {
                    "file": rel_path,
                    "why": item["why"],
                    "excerpt": excerpt,
                    "line_hint": line_count,
                    "language": self._language_for_file(rel_path),
                    "semantic_refs": semantic_refs,
                    "evidence_groups": [
                        self._make_evidence_group(
                            anchor_symbol=f"file::{rel_path}",
                            role="file_context",
                            why=[item["why"]],
                            evidence_path_refs=sorted(path_refs_by_file.get(rel_path, set())),
                            semantic_refs=semantic_refs,
                        )
                    ],
                    "evidence_path_refs": sorted(path_refs_by_file.get(rel_path, set())),
                }
            )
        return slices

    def _build_project_prompt(self, inventory: Dict[str, object], reads: List[Dict[str, str]]) -> str:
        tech = ", ".join(inventory["likely_technologies"]) if inventory["likely_technologies"] else "unknown stack"
        languages = ", ".join(item["language"] for item in inventory["language_summary"][:4]) or "unknown languages"
        files = ", ".join(item["file"] for item in reads[:6]) if reads else "no obvious entry files"
        return (
            "Start with the project shell. Infer the architecture, runtime shape, and likely developer workflow from "
            f"the manifests and entrypoints first. Stack guess: {tech}. Languages seen: {languages}. "
            f"Recommended first files: {files}. "
            "Then use the confidence-aware evidence, semantic entrypoints, and ambiguity signals before requesting additional files."
        )

    def _compact_text(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", text.lower())

    def _split_identifier_tokens(self, text: str) -> List[str]:
        tokens: List[str] = []
        for part in re.split(r"[^A-Za-z0-9]+", text):
            if not part:
                continue
            lowered = part.lower()
            tokens.append(lowered)
            matches = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|\d+", part)
            if matches:
                tokens.extend(match.lower() for match in matches)
        return self._dedupe([token for token in tokens if token])

    def _query_tokens(self, text: str) -> List[str]:
        raw_tokens = re.findall(r"[A-Za-z0-9]+", text.lower())
        tokens = self._dedupe(raw_tokens + self._split_identifier_tokens(text))
        return [
            token
            for token in tokens
            if token and (len(token) > 2 or token == "di") and token not in QUERY_STOPWORDS
        ]

    def _strict_query_tokens(self, text: str) -> Set[str]:
        return {
            token
            for token in re.findall(r"[A-Za-z0-9]+", text.lower())
            if token and (len(token) > 2 or token == "di") and token not in QUERY_STOPWORDS
        }

    def _query_contains_keyword(self, normalized_query: str, token_set: Set[str], keyword: str) -> bool:
        normalized_keyword = re.sub(r"[^a-z0-9]+", " ", keyword.lower()).strip()
        if not normalized_keyword:
            return False
        if " " in normalized_keyword:
            return normalized_keyword in normalized_query
        return normalized_keyword in token_set

    def _query_mentioned_symbols(self, normalized_query: str, tokens: Set[str], limit: int = 8) -> List[str]:
        matches: List[Tuple[float, str]] = []
        for node in self.nodes.values():
            candidates = [
                node.qualname,
                node.qualname.split(".")[-1],
                node.node_id,
                Path(node.file).stem,
            ]
            best_score = 0.0
            for index, value in enumerate(candidates):
                if not value:
                    continue
                normalized_value = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
                candidate_tokens = [token for token in normalized_value.split() if token]
                compact = self._compact_text(value)
                if normalized_value and " " in normalized_value and normalized_value in normalized_query:
                    best_score = max(best_score, 14.0 - index)
                elif (
                    len(candidate_tokens) == 1
                    and candidate_tokens[0] in tokens
                    and candidate_tokens[0] not in QUERY_GENERIC_MENTION_TOKENS
                    and len(candidate_tokens[0]) >= 5
                ):
                    best_score = max(best_score, 9.0 - index)
                elif compact and len(compact) >= 5 and compact == self._compact_text(normalized_query):
                    best_score = max(best_score, 11.0 - index)
            if not best_score:
                overlap = sorted(
                    token
                    for token in (tokens & set(self._split_identifier_tokens(node.qualname)))
                    if token not in QUERY_GENERIC_MENTION_TOKENS
                )
                if len(overlap) >= 2:
                    best_score = min(6.0, float(len(overlap)) * 1.5)
                elif overlap and len(overlap[0]) >= 8:
                    best_score = 3.5
            if best_score > 0.0:
                matches.append(
                    (
                        -best_score,
                        0 if node.kind in SEMANTIC_EXECUTABLE_KINDS else 1,
                        node.lines[1] - node.lines[0],
                        node.node_id,
                    )
                )
        ordered = sorted(matches)
        out: List[str] = []
        for _, _, _, node_id in ordered:
            if node_id not in out:
                out.append(node_id)
            if len(out) >= limit:
                break
        return out

    def _query_mentioned_files(self, normalized_query: str, tokens: Set[str], limit: int = 6) -> List[str]:
        matches: List[Tuple[float, str]] = []
        for rel_path in sorted({node.file for node in self.nodes.values()}):
            basename = Path(rel_path).name.lower()
            stem = Path(rel_path).stem.lower()
            normalized_basename = re.sub(r"[^a-z0-9]+", " ", basename).strip()
            normalized_stem = re.sub(r"[^a-z0-9]+", " ", stem).strip()
            score = 0.0
            if normalized_basename and " " in normalized_basename and normalized_basename in normalized_query:
                score = max(score, 12.0)
            if normalized_stem and normalized_stem in tokens:
                score = max(score, 10.0)
            compact_stem = self._compact_text(stem)
            if compact_stem and len(compact_stem) >= 5 and compact_stem == self._compact_text(normalized_query):
                score = max(score, 8.0)
            if score > 0.0:
                matches.append((-score, rel_path))
        return [rel_path for _, rel_path in sorted(matches)[:limit]]

    def _infer_query_scope_preference(
        self,
        normalized_query: str,
        inferred_intents: List[str],
        matched_signals: List[str],
        ambiguity_sensitive: bool,
    ) -> str:
        if ambiguity_sensitive or "smallest slice" in normalized_query:
            return "symbol"
        if any(keyword in normalized_query for keyword in ("how", "path", "flow", "reach", "before", "after")):
            return "path"
        if {"auth", "validation"} & set(inferred_intents) or set(matched_signals) & (SEMANTIC_BOUNDARY_SIGNALS | {"auth_guard", "validation_guard"}):
            return "boundary"
        if "architecture" in inferred_intents:
            return "risk"
        if matched_signals:
            return "semantic"
        return "symbol"

    def _build_query_analysis(self, query: str) -> Dict[str, object]:
        normalized_query = re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()
        query_tokens = self._query_tokens(query)
        strict_query_tokens = self._strict_query_tokens(query)
        token_set = set(query_tokens)
        matched_keywords: Set[str] = set()
        inferred_intents: List[str] = []
        for intent, keywords in QUERY_INTENT_KEYWORDS.items():
            hits = [keyword for keyword in keywords if self._query_contains_keyword(normalized_query, token_set, keyword)]
            if hits:
                inferred_intents.append(intent)
                matched_keywords.update(hits)
        matched_signals = [
            signal
            for signal, keywords in QUERY_SIGNAL_KEYWORDS.items()
            if any(self._query_contains_keyword(normalized_query, token_set, keyword) for keyword in keywords)
        ]
        ambiguity_sensitive = bool(
            "ambiguity_resolution" in inferred_intents
            or any(
                self._query_contains_keyword(normalized_query, token_set, keyword)
                for keyword in ("ambiguous", "unresolved", "candidate", "di")
            )
        )
        mentioned_symbols = self._query_mentioned_symbols(normalized_query, strict_query_tokens)
        mentioned_files = self._query_mentioned_files(normalized_query, strict_query_tokens)
        return {
            "raw_query": query,
            "normalized_query": normalized_query,
            "query_tokens": query_tokens,
            "strict_query_tokens": sorted(strict_query_tokens),
            "inferred_intents": inferred_intents,
            "mentioned_symbols": mentioned_symbols,
            "mentioned_files": mentioned_files,
            "matched_semantic_signals": self._sort_semantic_signals(matched_signals),
            "matched_keywords": sorted(matched_keywords),
            "ambiguity_sensitive": ambiguity_sensitive,
            "scope_preference": self._infer_query_scope_preference(
                normalized_query,
                inferred_intents,
                matched_signals,
                ambiguity_sensitive,
            ),
        }

    def _node_query_terms(self, node: SymbolNode) -> Set[str]:
        values = [
            node.node_id,
            node.module,
            node.qualname,
            node.qualname.split(".")[-1],
            node.file,
            Path(node.file).name,
            Path(node.file).stem,
        ]
        out: Set[str] = set()
        for value in values:
            out.update(self._split_identifier_tokens(value))
        return out

    def _query_lexical_match_details(
        self,
        node: SymbolNode,
        analysis: Dict[str, object],
    ) -> Tuple[float, List[str], List[str]]:
        query_tokens = set(str(token) for token in analysis.get("query_tokens", []))
        informative_query_tokens = {token for token in query_tokens if token not in QUERY_GENERIC_MENTION_TOKENS}
        mentioned_symbols = set(str(item) for item in analysis.get("mentioned_symbols", []))
        mentioned_files = set(str(item) for item in analysis.get("mentioned_files", []))
        compact_query = self._compact_text(str(analysis.get("normalized_query", "")))
        score = 0.0
        reasons: List[str] = []
        overlap = sorted(informative_query_tokens & self._node_query_terms(node))
        if node.node_id in mentioned_symbols:
            score += 16.0
            reasons.append("Exact symbol mention in the query.")
        elif self._compact_text(node.qualname.split(".")[-1]) and self._compact_text(node.qualname.split(".")[-1]) in compact_query:
            score += 9.0
            reasons.append("Query mentions the target symbol name.")
        if node.file in mentioned_files:
            score += 9.0
            reasons.append("Query mentions the target file.")
        elif self._compact_text(Path(node.file).stem) and self._compact_text(Path(node.file).stem) in compact_query:
            score += 4.0
            reasons.append("Query mentions the file stem.")
        if overlap:
            score += min(6.0, float(len(overlap)) * 1.5)
            reasons.append(f"Lexical overlap with query tokens: {', '.join(overlap[:4])}.")
        return score, reasons, overlap

    def _query_relevant_semantic_refs(
        self,
        refs: List[Dict[str, object]],
        matched_signals: Set[str],
        limit: int = 4,
    ) -> List[Dict[str, object]]:
        if matched_signals:
            filtered = [ref for ref in refs if str(ref.get("signal", "")) in matched_signals]
            if filtered:
                return self._dedupe_semantic_refs(filtered, limit=limit)
        return self._dedupe_semantic_refs(list(refs), limit=limit)

    def _best_support_edge_for_node(
        self,
        node_id: str,
        inbound: Dict[str, Set[str]],
    ) -> Optional[Dict[str, object]]:
        edges = self._support_edges_for_node(node_id, inbound, limit=4)
        return edges[0] if edges else None

    def _build_query_target_candidate(
        self,
        node_id: str,
        analysis: Dict[str, object],
        inbound: Dict[str, Set[str]],
    ) -> Dict[str, object]:
        node = self.nodes[node_id]
        mentioned_symbols = set(str(item) for item in analysis.get("mentioned_symbols", []))
        mentioned_files = set(str(item) for item in analysis.get("mentioned_files", []))
        matched_signals = set(str(item) for item in analysis.get("matched_semantic_signals", []))
        matched_signal_count = max(1, len(matched_signals))
        direct_match = self._sort_semantic_signals(signal for signal in node.semantic_signals if signal in matched_signals)
        contained_match = self._sort_semantic_signals(signal for signal in node.contained_semantic_signals if signal in matched_signals)
        direct_coverage = float(len(direct_match)) / float(matched_signal_count) if matched_signals else 0.0
        contained_coverage = float(len(contained_match)) / float(matched_signal_count) if matched_signals else 0.0
        direct_refs = self._query_relevant_semantic_refs(list(node.semantic_evidence_spans), matched_signals, limit=4)
        contained_refs = self._query_relevant_semantic_refs(list(node.contained_semantic_refs), matched_signals, limit=4)
        lexical_score, lexical_reasons, lexical_overlap = self._query_lexical_match_details(node, analysis)
        has_strong_query_anchor = bool(
            node_id in mentioned_symbols
            or node.file in mentioned_files
            or len(lexical_overlap) >= 2
            or any(len(token) >= 8 for token in lexical_overlap)
        )
        best_support = self._best_support_edge_for_node(node_id, inbound)
        support_score = float(best_support.get("confidence_score", 0.0)) if best_support else 0.0
        support_label = str(best_support.get("confidence_label", "")) if best_support else ""
        match_reasons = list(lexical_reasons)
        if direct_match:
            match_reasons.append(f"Direct semantic match: {', '.join(direct_match[:4])}.")
        if contained_match and not direct_match:
            match_reasons.append(f"Contained semantic match only: {', '.join(contained_match[:4])}.")
        if best_support is not None:
            match_reasons.append(
                f"Best supporting edge is `{best_support['resolution_kind']}` with `{best_support['confidence_label']}` confidence."
            )
        ambiguity_relevance = bool(
            node.unresolved_call_details
            and (
                bool(analysis.get("ambiguity_sensitive"))
                or node_id in set(str(item) for item in analysis.get("mentioned_symbols", []))
            )
        )
        if ambiguity_relevance:
            match_reasons.append("Relevant unresolved ambiguity is attached to this node.")
        executable_bonus = 3.5 if node.kind in SEMANTIC_EXECUTABLE_KINDS else (0.5 if node.kind in {"class", "interface", "enum", "record"} else -2.0)
        scope_preference = str(analysis.get("scope_preference", "symbol"))
        selection_score = (
            lexical_score
            + (float(len(direct_match)) * 8.0)
            + (float(len(contained_match)) * 3.0)
            + min(node.risk_score / 18.0, 5.0)
            + (support_score * 2.5)
            + (direct_coverage * 4.0)
            + (contained_coverage * 1.5)
            + executable_bonus
            + (5.0 if ambiguity_relevance else 0.0)
        )
        if not direct_match and contained_match:
            selection_score -= 2.0
        if len(matched_signals) > 1:
            if direct_coverage >= 0.99:
                selection_score += 10.0
                match_reasons.append("Direct semantic coverage matches all requested query signals.")
            elif direct_match:
                selection_score -= (1.0 - direct_coverage) * 8.0
                if scope_preference == "path" and not has_strong_query_anchor:
                    selection_score -= 10.0
                    match_reasons.append("Only partial semantic coverage and no strong lexical/path anchor for this multi-signal query.")
                else:
                    match_reasons.append("Only partial direct semantic coverage for the multi-signal query.")
            elif contained_coverage >= 0.99:
                selection_score += 1.5
                if scope_preference == "path":
                    selection_score -= 3.0
                match_reasons.append("Contained semantics cover all requested signals, but only indirectly.")
            elif contained_match:
                selection_score -= (1.0 - contained_coverage) * 6.0 + 4.0
                if scope_preference == "path" and not has_strong_query_anchor:
                    selection_score -= 6.0
                match_reasons.append("Only partial contained semantic coverage for the multi-signal query.")
            elif scope_preference == "path" and not has_strong_query_anchor:
                selection_score -= 3.0
        if scope_preference == "path" and node.kind in SEMANTIC_EXECUTABLE_KINDS and self.adj.get(node_id):
            selection_score += 1.5
        if scope_preference == "boundary" and set(direct_match) & (SEMANTIC_BOUNDARY_SIGNALS | {"auth_guard", "validation_guard"}):
            selection_score += 2.0
        if scope_preference == "semantic" and direct_match:
            selection_score += 2.0
        if scope_preference == "symbol" and node_id in set(str(item) for item in analysis.get("mentioned_symbols", [])):
            selection_score += 2.0
        return {
            "node_id": node_id,
            "file": node.file,
            "lines": node.lines,
            "kind": node.kind,
            "language": node.language,
            "risk_score": node.risk_score,
            "lexical_overlap": lexical_overlap,
            "match_reasons": match_reasons,
            "direct_semantic_match": direct_match,
            "contained_semantic_match": contained_match,
            "direct_semantic_refs": direct_refs,
            "contained_semantic_refs": contained_refs,
            "semantic_signals": list(node.semantic_signals),
            "contained_semantic_signals": list(node.contained_semantic_signals),
            "direct_semantic_coverage": round(direct_coverage, 2),
            "contained_semantic_coverage": round(contained_coverage, 2),
            "has_strong_query_anchor": has_strong_query_anchor,
            "best_support_label": support_label,
            "best_support_score": round(support_score, 2),
            "ambiguity_relevance": ambiguity_relevance,
            "base_selection_score": round(selection_score, 2),
        }

    def _build_query_evidence_paths(
        self,
        candidates: List[Dict[str, object]],
        inbound: Dict[str, Set[str]],
        analysis: Dict[str, object],
        limit: int = 8,
    ) -> List[Dict[str, object]]:
        paths: List[Dict[str, object]] = []
        mentioned_symbols = set(str(item) for item in analysis.get("mentioned_symbols", []))
        mentioned_files = set(str(item) for item in analysis.get("mentioned_files", []))
        query_tokens = set(str(item) for item in analysis.get("query_tokens", []))
        matched_signals = set(str(item) for item in analysis.get("matched_semantic_signals", []))
        matched_signal_keywords = {
            keyword
            for signal in matched_signals
            for keyword in QUERY_SIGNAL_KEYWORDS.get(signal, ())
        }
        matched_signal_count = max(1, len(matched_signals))
        full_coverage_present = any(
            float(candidate.get("direct_semantic_coverage", 0.0)) >= 0.99
            or float(candidate.get("contained_semantic_coverage", 0.0)) >= 0.99
            for candidate in candidates
        )
        for candidate in candidates[:8]:
            candidate_coverage = max(
                float(candidate.get("direct_semantic_coverage", 0.0)),
                float(candidate.get("contained_semantic_coverage", 0.0)) * 0.7,
            )
            candidate_has_strong_anchor = bool(candidate.get("has_strong_query_anchor"))
            if (
                len(matched_signals) > 1
                and full_coverage_present
                and candidate_coverage < 0.99
                and not candidate_has_strong_anchor
            ):
                continue
            faux_candidate = {
                "node_id": candidate["node_id"],
                "bundle_priority": candidate["base_selection_score"],
                "ambiguity_flags": [{}] if candidate["ambiguity_relevance"] else [],
            }
            for path in self._build_evidence_paths_for_candidate(faux_candidate, inbound, limit=2):
                path_signals = set(str(item) for item in path.get("semantic_signals", []))
                signal_matches = self._sort_semantic_signals(path_signals & matched_signals)
                path_nodes = {str(path.get("risk_node", ""))}
                for hop in path.get("hops", []):
                    path_nodes.add(str(hop.get("source", "")))
                    path_nodes.add(str(hop.get("target", "")))
                lexical_hits = [node_id for node_id in sorted(path_nodes) if node_id in mentioned_symbols]
                file_hits = [
                    self.nodes[node_id].file
                    for node_id in sorted(path_nodes)
                    if node_id in self.nodes and self.nodes[node_id].file in mentioned_files
                ]
                path_term_overlap = sorted(
                    token
                    for node_id in path_nodes
                    if node_id in self.nodes
                    for token in (query_tokens & self._node_query_terms(self.nodes[node_id]))
                )
                signal_keyword_hits = sorted(
                    token
                    for node_id in path_nodes
                    if node_id in self.nodes
                    for token in (matched_signal_keywords & self._node_query_terms(self.nodes[node_id]))
                )
                has_query_anchor = bool(signal_matches or lexical_hits or file_hits or path_term_overlap or signal_keyword_hits)
                if not has_query_anchor:
                    continue
                signal_coverage = float(len(signal_matches)) / float(matched_signal_count) if matched_signals else 0.0
                score = (
                    (float(len(signal_matches)) * 5.0)
                    + (float(len(lexical_hits)) * 3.0)
                    + min(4.0, float(len(set(file_hits))) * 2.0)
                    + min(4.0, float(len(set(path_term_overlap))) * 1.0)
                    + min(4.0, float(len(set(signal_keyword_hits))) * 1.5)
                    + (float(path.get("path_confidence", 0.0)) * 4.0)
                    + (signal_coverage * 6.0)
                    + (2.0 if str(analysis.get("scope_preference", "")) == "path" else 0.0)
                    + (1.5 if len(path.get("hops", [])) > 1 else 0.0)
                )
                if len(matched_signals) > 1:
                    if signal_coverage >= 0.99:
                        score += 6.0
                    elif signal_matches:
                        score -= (1.0 - signal_coverage) * 7.0
                        if str(analysis.get("scope_preference", "")) == "path" and not (lexical_hits or file_hits):
                            score -= 5.0
                    elif signal_keyword_hits:
                        if str(analysis.get("scope_preference", "")) == "path" and not (lexical_hits or file_hits):
                            score -= 2.0
                    elif full_coverage_present:
                        score -= 8.0
                    elif str(analysis.get("scope_preference", "")) == "path":
                        score -= 6.0
                elif matched_signals and not signal_matches and not signal_keyword_hits and str(analysis.get("scope_preference", "")) == "path":
                    score -= 4.0
                reasons: List[str] = []
                if signal_matches:
                    reasons.append(f"Path semantic match: {', '.join(signal_matches[:4])}.")
                if lexical_hits:
                    reasons.append("Path includes a lexically mentioned symbol.")
                if file_hits:
                    reasons.append("Path includes a mentioned file.")
                if path_term_overlap:
                    reasons.append(f"Path overlaps query tokens: {', '.join(sorted(set(path_term_overlap))[:4])}.")
                if signal_keyword_hits:
                    reasons.append(f"Path overlaps semantic hint terms: {', '.join(sorted(set(signal_keyword_hits))[:4])}.")
                enriched = dict(path)
                enriched["query_match_score"] = round(score, 2)
                enriched["query_match_reasons"] = reasons
                enriched["query_match_signals"] = signal_matches
                paths.append(enriched)
        paths.sort(
            key=lambda item: (
                -float(item.get("query_match_score", 0.0)),
                -float(item.get("path_confidence", 0.0)),
                -len(item.get("hops", [])),
                str(item.get("path_id", "")),
            )
        )
        return paths[:limit]

    def _build_query_ambiguity_watchlist(
        self,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        limit: int = 4,
    ) -> List[Dict[str, object]]:
        mentioned_symbols = set(str(item) for item in analysis.get("mentioned_symbols", [])) | {
            str(item["node_id"]) for item in ranked_targets[:6]
        }
        mentioned_files = set(str(item) for item in analysis.get("mentioned_files", []))
        query_tokens = set(str(item) for item in analysis.get("query_tokens", []))
        items: List[Dict[str, object]] = []
        for item in self._build_ambiguity_watchlist(limit=50):
            score = 0.0
            reasons: List[str] = []
            if bool(analysis.get("ambiguity_sensitive")):
                score += 8.0
                reasons.append("Query explicitly asks for ambiguity handling.")
            if str(item["source_node"]) in mentioned_symbols:
                score += 6.0
                reasons.append("Ambiguous source node is directly relevant to the query.")
            if str(item["file"]) in mentioned_files:
                score += 3.0
                reasons.append("Ambiguous file is mentioned in the query.")
            raw_blob = " ".join(
                [str(item.get("source_node", "")), str(item.get("raw_call", ""))]
                + [str(candidate) for candidate in item.get("candidates", [])]
            ).lower()
            if any(token in raw_blob for token in query_tokens):
                score += 2.0
                reasons.append("Ambiguity details overlap the query terms.")
            if score <= 0.0 and not (bool(analysis.get("ambiguity_sensitive")) and len(self._build_ambiguity_watchlist(limit=50)) == 1):
                continue
            enriched = dict(item)
            enriched["query_match_score"] = round(score, 2)
            enriched["query_match_reasons"] = reasons
            items.append(enriched)
        items.sort(
            key=lambda item: (
                -float(item.get("query_match_score", 0.0)),
                -float(self.nodes[item["source_node"]].risk_score),
                str(item["source_node"]),
            )
        )
        return items[:limit]

    def _build_query_slice_spec(
        self,
        node_id: str,
        why: List[str],
        selection_score: float,
        selection_confidence_label: str,
        supporting_edges: Optional[List[Dict[str, object]]] = None,
        ambiguity_flags: Optional[List[Dict[str, object]]] = None,
        role: str = "query_target",
        evidence_path_refs: Optional[List[str]] = None,
        semantic_refs: Optional[List[Dict[str, object]]] = None,
    ) -> Dict[str, object]:
        node = self.nodes[node_id]
        file_lines = self._read_project_lines(node.file)
        file_end = len(file_lines) if file_lines else int(node.lines[1])
        focus_refs = self._dedupe_semantic_refs(list(semantic_refs or []), limit=4)
        if focus_refs:
            start_line = max(1, min(int(ref["lines"][0]) for ref in focus_refs) - 1)
            end_line = min(file_end, max(int(ref["lines"][1]) for ref in focus_refs) + 1)
        else:
            start_line = max(1, int(node.lines[0]) - 1)
            end_line = min(file_end, int(node.lines[1]) + 1)
        labels = self._sort_confidence_labels([selection_confidence_label or "medium"])
        return {
            "file": node.file,
            "start_line": start_line,
            "end_line": max(start_line, end_line),
            "symbols": [node_id],
            "why": list(why),
            "selection_score": round(selection_score, 2),
            "selection_confidence_label": selection_confidence_label or "medium",
            "selection_confidence_labels": labels,
            "supporting_edges": list(supporting_edges or []),
            "ambiguity_flags": list(ambiguity_flags or []),
            "semantic_refs": focus_refs,
            "evidence_path_refs": sorted(set(str(item) for item in evidence_path_refs or [] if item)),
            "evidence_groups": [
                self._make_evidence_group(
                    anchor_symbol=node_id,
                    role=role,
                    why=why,
                    supporting_edges=supporting_edges,
                    selection_confidence_labels=labels,
                    ambiguity_flags=ambiguity_flags,
                    selection_score=selection_score,
                    evidence_path_refs=evidence_path_refs,
                    semantic_refs=focus_refs,
                )
            ],
        }

    def _slice_ref(self, spec: Dict[str, object]) -> str:
        return f"{spec['file']}:{spec['start_line']}-{spec['end_line']}"

    def _flow_node_label(self, node_id: str) -> str:
        node = self.nodes.get(node_id)
        if node is None:
            return node_id
        if node.kind == "module":
            return Path(node.file).name
        tail = node.qualname.split(".")[-1] if node.qualname else ""
        return tail or Path(node.file).stem or node.node_id

    def _slice_refs_by_symbol(self, slices: List[Dict[str, object]]) -> Dict[str, List[str]]:
        mapping: Dict[str, List[str]] = defaultdict(list)
        for spec in slices:
            slice_ref = self._slice_ref(spec)
            for symbol in spec.get("symbols", []):
                mapping[str(symbol)].append(slice_ref)
        return {
            symbol: sorted(set(refs))
            for symbol, refs in mapping.items()
        }

    def _flow_completeness_label(
        self,
        step_kinds: List[str],
        matched_signals: Set[str],
    ) -> str:
        if not step_kinds:
            return "missing"
        if not matched_signals:
            return "context_only"
        covered = set(step_kinds) & matched_signals
        if covered >= matched_signals:
            return "complete"
        if covered:
            return "partial"
        return "context_only"

    def _ordered_path_nodes(self, path: Dict[str, object]) -> List[str]:
        hop_pairs = [
            (str(hop.get("source", "")), str(hop.get("target", "")))
            for hop in path.get("hops", [])
            if str(hop.get("source", "")) in self.nodes and str(hop.get("target", "")) in self.nodes
        ]
        nodes = {str(path.get("risk_node", ""))} | {source for source, _ in hop_pairs} | {target for _, target in hop_pairs}
        nodes = {node_id for node_id in nodes if node_id in self.nodes}
        if not nodes:
            return []

        outgoing: Dict[str, List[str]] = defaultdict(list)
        indegree: Dict[str, int] = {node_id: 0 for node_id in nodes}
        for source, target in hop_pairs:
            outgoing[source].append(target)
            indegree[target] = indegree.get(target, 0) + 1
            indegree.setdefault(source, 0)

        for source in outgoing:
            outgoing[source] = sorted(set(outgoing[source]), key=lambda node_id: (self._flow_node_label(node_id), node_id))

        starts = sorted(
            [node_id for node_id, degree in indegree.items() if degree == 0],
            key=lambda node_id: (0 if self.nodes[node_id].kind in SEMANTIC_EXECUTABLE_KINDS else 1, self._flow_node_label(node_id), node_id),
        )
        if not starts:
            ordered = sorted(nodes, key=lambda node_id: (self._flow_node_label(node_id), node_id))
            risk_node = str(path.get("risk_node", ""))
            if risk_node in ordered:
                ordered.remove(risk_node)
                ordered.insert(0, risk_node)
            return ordered

        ordered: List[str] = []
        visited: Set[str] = set()
        current = starts[0]
        while current and current not in visited:
            ordered.append(current)
            visited.add(current)
            next_nodes = [node_id for node_id in outgoing.get(current, []) if node_id not in visited]
            current = next_nodes[0] if next_nodes else ""

        for node_id in sorted(nodes - set(ordered), key=lambda item: (self._flow_node_label(item), item)):
            ordered.append(node_id)
        return ordered

    def _build_flow_chain_compact_string(
        self,
        ordered_nodes: List[str],
        stitched_step_kinds: List[str],
        matched_signals: Set[str],
    ) -> str:
        if len(ordered_nodes) <= 1 and stitched_step_kinds:
            return " -> ".join(stitched_step_kinds)
        if matched_signals and set(stitched_step_kinds) >= matched_signals and len(stitched_step_kinds) >= max(2, len(matched_signals)):
            return " -> ".join(stitched_step_kinds)
        node_labels = [self._flow_node_label(node_id) for node_id in ordered_nodes]
        if stitched_step_kinds:
            return " -> ".join(node_labels + stitched_step_kinds)
        return " -> ".join(node_labels)

    def _build_selected_flow_summaries(
        self,
        ranked_targets: List[Dict[str, object]],
        merged_slices: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
        analysis: Dict[str, object],
        limit: int = 6,
    ) -> List[Dict[str, object]]:
        selected_symbols = {str(symbol) for spec in merged_slices for symbol in spec.get("symbols", [])}
        slice_refs_by_symbol = self._slice_refs_by_symbol(merged_slices)
        path_refs_by_symbol: Dict[str, List[str]] = defaultdict(list)
        path_map = {
            str(path.get("path_id", "")): path
            for path in selected_paths
            if path.get("path_id")
        }
        for path in selected_paths:
            path_id = str(path.get("path_id", ""))
            for node_id in self._ordered_path_nodes(path):
                path_refs_by_symbol[node_id].append(path_id)

        out: List[Dict[str, object]] = []
        seen: Set[str] = set()
        matched_signals = set(str(item) for item in analysis.get("matched_semantic_signals", []))
        ordered_candidates = [str(item["node_id"]) for item in ranked_targets] + sorted(selected_symbols)
        for node_id in ordered_candidates:
            if node_id in seen or node_id not in selected_symbols or node_id not in self.nodes:
                continue
            node = self.nodes[node_id]
            if node.kind not in SEMANTIC_EXECUTABLE_KINDS or not node.behavioral_flow_summary:
                continue
            ordered_step_kinds = list(node.behavioral_flow_summary.get("ordered_step_kinds", []))
            matched_step_kinds = self._sort_semantic_signals(set(ordered_step_kinds) & matched_signals)
            completeness = self._flow_completeness_label(ordered_step_kinds, matched_signals)
            supporting_path_refs = sorted(set(path_refs_by_symbol.get(node_id, [])))
            if matched_signals and completeness == "context_only" and not supporting_path_refs:
                continue
            if (
                matched_signals
                and completeness == "context_only"
                and supporting_path_refs
                and not any(
                    path_map.get(path_id, {}).get("query_match_signals", [])
                    for path_id in supporting_path_refs
                )
            ):
                continue
            out.append(
                {
                    "node_id": node_id,
                    "file": node.file,
                    "lines": list(node.lines),
                    "ordered_step_kinds": ordered_step_kinds,
                    "matched_step_kinds": matched_step_kinds,
                    "flow_compact_string": str(node.behavioral_flow_summary.get("flow_compact_string", "")),
                    "guard_count": int(node.behavioral_flow_summary.get("guard_count", 0)),
                    "side_effect_count": int(node.behavioral_flow_summary.get("side_effect_count", 0)),
                    "has_terminal_output": bool(node.behavioral_flow_summary.get("has_terminal_output", False)),
                    "has_error_path": bool(node.behavioral_flow_summary.get("has_error_path", False)),
                    "completeness": completeness,
                    "supporting_slice_refs": slice_refs_by_symbol.get(node_id, []),
                    "supporting_path_refs": supporting_path_refs,
                    "behavioral_flow_steps": list(node.behavioral_flow_steps[:8]),
                }
            )
            seen.add(node_id)
            if len(out) >= limit:
                break
        return out

    def _build_selected_flow_chains(
        self,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
        merged_slices: List[Dict[str, object]],
        selected_flow_summaries: List[Dict[str, object]],
        limit: int = 4,
    ) -> List[Dict[str, object]]:
        slice_refs_by_symbol = self._slice_refs_by_symbol(merged_slices)
        selected_summary_map = {str(item["node_id"]): item for item in selected_flow_summaries}
        matched_signals = set(str(item) for item in analysis.get("matched_semantic_signals", []))
        mentioned_symbols = set(str(item) for item in analysis.get("mentioned_symbols", []))
        mentioned_files = set(str(item) for item in analysis.get("mentioned_files", []))
        rank_by_node = {
            str(item["node_id"]): index
            for index, item in enumerate(ranked_targets, start=1)
        }
        matched_signal_keywords = {
            keyword
            for signal in matched_signals
            for keyword in QUERY_SIGNAL_KEYWORDS.get(signal, ())
        }
        chains: List[Dict[str, object]] = []
        seen: Set[str] = set()

        def append_chain(
            chain_id: str,
            query_anchor: str,
            ordered_nodes: List[str],
            stitched_step_kinds: List[str],
            supporting_path_refs: List[str],
            stop_reason: str,
        ) -> None:
            if not ordered_nodes or (not stitched_step_kinds and len(ordered_nodes) < 2):
                return
            completeness = self._flow_completeness_label(stitched_step_kinds, matched_signals)
            if completeness == "context_only" and matched_signals and not supporting_path_refs:
                return
            supporting_slice_refs: List[str] = []
            seen_slice_refs: Set[str] = set()
            for node_id in ordered_nodes:
                for ref in slice_refs_by_symbol.get(node_id, []):
                    ref = str(ref)
                    if ref in seen_slice_refs:
                        continue
                    seen_slice_refs.add(ref)
                    supporting_slice_refs.append(ref)
            signature = json.dumps(
                {
                    "query_anchor": query_anchor,
                    "nodes": ordered_nodes,
                    "steps": stitched_step_kinds,
                },
                sort_keys=True,
            )
            if signature in seen:
                return
            seen.add(signature)
            mentioned_match_count = sum(
                1
                for node_id in ordered_nodes
                if node_id in mentioned_symbols
                or (node_id in self.nodes and self.nodes[node_id].file in mentioned_files)
            )
            matched_step_count = len(set(str(item) for item in stitched_step_kinds) & matched_signals)
            chains.append(
                {
                    "chain_id": chain_id,
                    "query_anchor": query_anchor,
                    "nodes": ordered_nodes,
                    "stitched_step_kinds": stitched_step_kinds,
                    "flow_compact_string": self._build_flow_chain_compact_string(ordered_nodes, stitched_step_kinds, matched_signals),
                    "supporting_path_refs": supporting_path_refs,
                    "supporting_slice_refs": supporting_slice_refs,
                    "completeness": completeness,
                    "stop_reason": stop_reason,
                    "_query_anchor_rank": int(rank_by_node.get(query_anchor, 999)),
                    "_mentioned_match_count": mentioned_match_count,
                    "_matched_step_count": matched_step_count,
                    "_node_count": len(ordered_nodes),
                }
            )

        for index, path in enumerate(selected_paths, start=1):
            raw_ordered_nodes = self._ordered_path_nodes(path)
            if (
                (mentioned_symbols or mentioned_files)
                and not any(
                    node_id in mentioned_symbols
                    or (node_id in self.nodes and self.nodes[node_id].file in mentioned_files)
                    for node_id in raw_ordered_nodes
                )
                and int(rank_by_node.get(str(path.get("risk_node", "")), 999)) > 3
            ):
                continue
            ordered_nodes = [
                node_id
                for node_id in raw_ordered_nodes
                if node_id in self.nodes and self.nodes[node_id].kind in SEMANTIC_EXECUTABLE_KINDS
            ]
            flow_nodes = [node_id for node_id in ordered_nodes if node_id in selected_summary_map]
            if not flow_nodes:
                continue
            first_flow = selected_summary_map[flow_nodes[0]]
            if matched_signals and len(ordered_nodes) > 1:
                flow_start_index = ordered_nodes.index(flow_nodes[0])
                downstream_nodes = ordered_nodes[flow_start_index + 1 :]
                downstream_relevance = any(
                    node_id in self.nodes
                    and (
                        bool(set(str(item) for item in self.nodes[node_id].semantic_signals) & matched_signals)
                        or bool(set(self._node_query_terms(self.nodes[node_id])) & matched_signal_keywords)
                        or node_id in mentioned_symbols
                        or self.nodes[node_id].file in mentioned_files
                    )
                    for node_id in downstream_nodes
                )
                if not downstream_relevance:
                    if flow_start_index == 0:
                        continue
                    ordered_nodes = ordered_nodes[: flow_start_index + 1]
                    flow_nodes = [node_id for node_id in ordered_nodes if node_id in selected_summary_map]
                    if not flow_nodes:
                        continue
                    first_flow = selected_summary_map[flow_nodes[0]]
            if len(ordered_nodes) == 1:
                stitched_step_kinds = list(first_flow.get("ordered_step_kinds", []))
            elif (
                matched_signals
                and set(str(item) for item in first_flow.get("ordered_step_kinds", [])) >= matched_signals
                and len(first_flow.get("ordered_step_kinds", [])) >= max(2, len(matched_signals))
            ):
                stitched_step_kinds = list(first_flow.get("ordered_step_kinds", []))
            else:
                stitched_step_kinds = self._compact_behavioral_step_kinds(
                    step_kind
                    for node_position, node_id in enumerate(flow_nodes)
                    for step_kind in (
                        [
                            kind
                            for kind in selected_summary_map[node_id].get("ordered_step_kinds", [])
                            if not (
                                node_position < len(flow_nodes) - 1
                                and kind == "output_boundary"
                            )
                        ]
                    )
                )
            append_chain(
                chain_id=f"{path.get('path_id', f'flow_chain_{index}')}",
                query_anchor=str(path.get("risk_node", "")),
                ordered_nodes=ordered_nodes,
                stitched_step_kinds=stitched_step_kinds,
                supporting_path_refs=[str(path.get("path_id", ""))] if path.get("path_id") else [],
                stop_reason=str(path.get("stop_reason", "")) or "path_selected",
            )

        if not chains and matched_signals:
            for index, path in enumerate(selected_paths, start=1):
                ordered_nodes = [
                    node_id
                    for node_id in self._ordered_path_nodes(path)
                    if node_id in self.nodes and self.nodes[node_id].kind in SEMANTIC_EXECUTABLE_KINDS
                ]
                if len(ordered_nodes) < 2:
                    continue
                query_anchor = str(path.get("risk_node", ""))
                if (
                    (mentioned_symbols or mentioned_files)
                    and not any(
                        node_id in mentioned_symbols
                        or (node_id in self.nodes and self.nodes[node_id].file in mentioned_files)
                        for node_id in ordered_nodes
                    )
                    and int(rank_by_node.get(query_anchor, 999)) > 3
                ):
                    continue
                append_chain(
                    chain_id=f"{path.get('path_id', f'flow_chain_{index}')}::context",
                    query_anchor=query_anchor,
                    ordered_nodes=ordered_nodes,
                    stitched_step_kinds=[],
                    supporting_path_refs=[str(path.get("path_id", ""))] if path.get("path_id") else [],
                    stop_reason="path_without_direct_semantic_evidence",
                )
                if len(chains) >= limit:
                    break

        if len(chains) < limit:
            for index, item in enumerate(selected_flow_summaries, start=1):
                node_id = str(item["node_id"])
                append_chain(
                    chain_id=f"{node_id}::single_flow::{index}",
                    query_anchor=node_id,
                    ordered_nodes=[node_id],
                    stitched_step_kinds=list(item.get("ordered_step_kinds", [])),
                    supporting_path_refs=list(item.get("supporting_path_refs", [])),
                    stop_reason="single_node_flow",
                )
                if len(chains) >= limit:
                    break

        chains.sort(
            key=lambda item: (
                -FLOW_COMPLETENESS_ORDER.get(str(item.get("completeness", "")), 0),
                -int(item.get("_mentioned_match_count", 0)),
                -int(item.get("_matched_step_count", 0)),
                int(item.get("_query_anchor_rank", 999)),
                -len(item.get("supporting_path_refs", [])),
                -int(item.get("_node_count", 0)),
                -len(item.get("stitched_step_kinds", [])),
                str(item.get("chain_id", "")),
            )
        )
        deduped: List[Dict[str, object]] = []
        dedupe_seen: Set[str] = set()
        for item in chains:
            dedupe_key = json.dumps(
                {
                    "query_anchor": str(item.get("query_anchor", "")),
                    "stitched_step_kinds": list(item.get("stitched_step_kinds", [])),
                },
                sort_keys=True,
            )
            if dedupe_key in dedupe_seen:
                continue
            dedupe_seen.add(dedupe_key)
            payload = dict(item)
            for key in ("_query_anchor_rank", "_mentioned_match_count", "_matched_step_count", "_node_count"):
                payload.pop(key, None)
            deduped.append(payload)
            if len(deduped) >= limit:
                break
        return deduped

    def _build_flow_gaps(
        self,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        selected_flow_summaries: List[Dict[str, object]],
        selected_flow_chains: List[Dict[str, object]],
        limit: int = 4,
    ) -> List[Dict[str, object]]:
        matched_signals = set(str(item) for item in analysis.get("matched_semantic_signals", []))
        summary_map = {str(item["node_id"]): item for item in selected_flow_summaries}
        items: List[Dict[str, object]] = []
        for target in ranked_targets[:6]:
            node_id = str(target["node_id"])
            node = self.nodes.get(node_id)
            if node is None or node.kind not in SEMANTIC_EXECUTABLE_KINDS:
                continue
            summary = summary_map.get(node_id)
            if summary is None:
                continue
            missing_step_kinds = sorted(matched_signals - set(str(item) for item in summary.get("ordered_step_kinds", [])))
            if not missing_step_kinds:
                continue
            items.append(
                {
                    "gap_kind": "partial_node_flow",
                    "node_id": node_id,
                    "missing_step_kinds": missing_step_kinds,
                    "reason": "Selected executable flow covers only part of the query-matched semantic signals.",
                    "supporting_slice_refs": list(summary.get("supporting_slice_refs", [])),
                    "supporting_path_refs": list(summary.get("supporting_path_refs", [])),
                }
            )
        for chain in selected_flow_chains:
            if str(chain.get("completeness", "")) == "complete":
                continue
            items.append(
                {
                    "gap_kind": "incomplete_flow_chain",
                    "chain_id": str(chain.get("chain_id", "")),
                    "missing_step_kinds": sorted(matched_signals - set(str(item) for item in chain.get("stitched_step_kinds", []))),
                    "reason": "The stitched behavioral flow chain remains partial for the query signals.",
                    "supporting_slice_refs": list(chain.get("supporting_slice_refs", [])),
                    "supporting_path_refs": list(chain.get("supporting_path_refs", [])),
                }
            )
        return self._dedupe_object_list(items)[:limit]

    def _analysis_overall_goal(self, query: str, analysis: Dict[str, object]) -> str:
        matched_signals = list(analysis.get("matched_semantic_signals", []))
        if matched_signals:
            return (
                "Determine whether the selected evidence proves "
                f"`{', '.join(str(item) for item in matched_signals[:4])}` for `{query}`."
            )
        intents = list(analysis.get("inferred_intents", []))
        if intents:
            return (
                "Determine the smallest evidenced answer to "
                f"`{query}` with emphasis on `{', '.join(str(item) for item in intents[:3])}`."
            )
        return f"Determine the smallest evidenced answer to `{query}`."

    def _recommended_analysis_outcome_mode(
        self,
        analysis: Dict[str, object],
        selected_flow_summaries: List[Dict[str, object]],
        selected_flow_chains: List[Dict[str, object]],
        flow_gaps: List[Dict[str, object]],
        ambiguity_watchlist: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
    ) -> str:
        matched_signals = set(str(item) for item in analysis.get("matched_semantic_signals", []))
        if ambiguity_watchlist:
            return "ambiguous"
        if any(str(item.get("completeness", "")) == "complete" for item in selected_flow_chains):
            return "confirmed"
        if any(str(item.get("completeness", "")) == "complete" for item in selected_flow_summaries):
            return "confirmed"
        covered_signals = {
            signal
            for item in selected_flow_summaries
            for signal in item.get("ordered_step_kinds", [])
            if signal in matched_signals
        } | {
            signal
            for item in selected_flow_chains
            for signal in item.get("stitched_step_kinds", [])
            if signal in matched_signals
        }
        if matched_signals:
            if covered_signals:
                return "partial" if flow_gaps else "confirmed"
            return "unproven"
        if selected_flow_chains or selected_flow_summaries or selected_paths:
            return "partial"
        return "unproven"

    def _build_analysis_candidate_outcomes(
        self,
        query: str,
        analysis: Dict[str, object],
        recommended_outcome_mode: str,
    ) -> List[Dict[str, object]]:
        matched_signals = [str(item) for item in analysis.get("matched_semantic_signals", [])]
        signal_text = ", ".join(matched_signals[:4]) if matched_signals else "the requested behavior"
        templates = {
            "confirmed": {
                "claim_template": f"Confirmed: `{query}` is directly supported by the selected evidence for {signal_text}.",
                "evidence_requirements": [
                    "A selected slice or complete flow chain covers all query-matched signals.",
                    "No unresolved ambiguity remains on the answering path.",
                ],
                "when_to_choose": "Choose this once the selected slices and flow/path evidence answer the query without missing signals.",
                "forbidden_overreach": "Do not claim extra transitions or side effects that are not directly evidenced.",
            },
            "partial": {
                "claim_template": f"Partial: `{query}` is only partly supported; one or more transitions or signals remain open.",
                "evidence_requirements": [
                    "At least one relevant slice or flow chain is directly evidenced.",
                    "A flow gap, missing transition, or weakly supported step remains.",
                ],
                "when_to_choose": "Choose this when the main path is visible but the full requested claim is not yet closed.",
                "forbidden_overreach": "Do not upgrade a partial chain into a complete claim.",
            },
            "unproven": {
                "claim_template": f"Unproven: `{query}` cannot be proven from the selected evidence.",
                "evidence_requirements": [
                    "Primary slices and selected paths were inspected.",
                    "No direct evidence proves the missing signal(s).",
                ],
                "when_to_choose": "Choose this when the available slices stay structural or contextual and the key signal never appears directly.",
                "forbidden_overreach": "Do not infer the missing behavior from naming, wrappers, or adjacency alone.",
            },
            "ambiguous": {
                "claim_template": f"Ambiguous: `{query}` still has multiple plausible interpretations or unresolved candidates.",
                "evidence_requirements": [
                    "An ambiguity_watchlist item or competing candidate set remains unresolved.",
                    "The selected slices do not remove that ambiguity decisively.",
                ],
                "when_to_choose": "Choose this when the best available evidence still branches into multiple plausible answers.",
                "forbidden_overreach": "Do not collapse multiple candidates into a single confirmed answer.",
            },
        }
        order = [recommended_outcome_mode] + [
            item for item in ("confirmed", "partial", "unproven", "ambiguous")
            if item != recommended_outcome_mode
        ]
        return [
            {"outcome_mode": outcome_mode, **templates[outcome_mode]}
            for outcome_mode in order
        ]

    def _build_minimal_open_sequence(
        self,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        selected_slices: List[Dict[str, object]],
        selected_flow_summaries: List[Dict[str, object]],
        selected_flow_chains: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
        flow_gaps: List[Dict[str, object]],
        recommended_outcome_mode: str,
        primary_target_id: str = "",
        primary_chain: Optional[Dict[str, object]] = None,
        primary_path: Optional[Dict[str, object]] = None,
        primary_gap: Optional[Dict[str, object]] = None,
        limit: int = 4,
    ) -> List[Dict[str, object]]:
        matched_signals = set(str(item) for item in analysis.get("matched_semantic_signals", []))
        slice_by_ref = {self._slice_ref(spec): spec for spec in selected_slices}
        slice_refs_by_symbol = self._slice_refs_by_symbol(selected_slices)
        rank_by_node = {
            str(item["node_id"]): index
            for index, item in enumerate(ranked_targets, start=1)
        }
        chain_support_refs = {
            str(ref)
            for item in selected_flow_chains
            for ref in item.get("supporting_slice_refs", [])
        }
        summary_support_refs = {
            str(ref)
            for item in selected_flow_summaries
            for ref in item.get("supporting_slice_refs", [])
        }
        gap_support_refs = {
            str(ref)
            for item in flow_gaps
            for ref in item.get("supporting_slice_refs", [])
        }

        ordered_refs: List[str] = []

        def append_refs(refs: Iterable[str]) -> None:
            ordered_refs.extend(str(ref) for ref in refs if str(ref))

        def append_path_refs() -> None:
            for path in selected_paths:
                for item in path.get("recommended_slices", []):
                    node_id = str(item.get("anchor_symbol", ""))
                    append_refs(slice_refs_by_symbol.get(node_id, []))

        def append_chain_refs() -> None:
            for item in selected_flow_chains:
                append_refs(item.get("supporting_slice_refs", []))

        def append_summary_refs() -> None:
            for item in selected_flow_summaries:
                append_refs(item.get("supporting_slice_refs", []))

        if primary_target_id:
            append_refs(slice_refs_by_symbol.get(primary_target_id, []))
        if primary_chain:
            append_refs(primary_chain.get("supporting_slice_refs", []))
        if primary_path:
            for item in primary_path.get("recommended_slices", []):
                node_id = str(item.get("anchor_symbol", ""))
                append_refs(slice_refs_by_symbol.get(node_id, []))
        if primary_gap:
            append_refs(primary_gap.get("supporting_slice_refs", []))

        if recommended_outcome_mode in {"partial", "unproven"}:
            append_path_refs()
            append_chain_refs()
            append_summary_refs()
        else:
            append_chain_refs()
            append_summary_refs()
            append_path_refs()
        ordered_refs.extend(self._slice_ref(spec) for spec in selected_slices)

        out: List[Dict[str, object]] = []
        seen: Set[str] = set()
        for ref in ordered_refs:
            ref = str(ref)
            if ref in seen or ref not in slice_by_ref:
                continue
            seen.add(ref)
            spec = slice_by_ref[ref]
            candidate_symbols = [
                str(symbol)
                for symbol in spec.get("symbols", [])
                if str(symbol) in self.nodes
            ]
            candidate_symbols.sort(
                key=lambda node_id: (
                    int(rank_by_node.get(node_id, 999)),
                    0 if self.nodes[node_id].kind in SEMANTIC_EXECUTABLE_KINDS else 1,
                    node_id,
                )
            )
            symbol = candidate_symbols[0] if candidate_symbols else (str(spec.get("symbols", [""])[0]) if spec.get("symbols") else "")
            if ref in gap_support_refs:
                why = "Inspect this slice only to decide whether the remaining flow gap can be closed."
                stop_if = (
                    f"Stop after this slice if `{', '.join(sorted(matched_signals))}` is still not directly evidenced."
                    if matched_signals
                    else "Stop after this slice if the gap remains unresolved."
                )
            elif ref in chain_support_refs:
                why = "Primary graph-guided evidence for the leading flow or path check."
                stop_if = "Stop if this slice, together with the current flow/path, already settles the claim."
            elif ref in summary_support_refs:
                why = "Primary executable slice for the highest-ranked query target."
                stop_if = "Stop if this slice alone answers the query."
            else:
                why = "Lowest-cost supporting context retained by the query-scoped ranking."
                stop_if = "Stop if the current outcome mode can already be chosen without opening lower-priority context."
            out.append(
                {
                    "order": len(out) + 1,
                    "slice_ref": ref,
                    "symbol": symbol,
                    "why": why,
                    "stop_if": stop_if,
                }
            )
            if len(out) >= limit:
                break
        return out

    def _select_primary_flow_chain(
        self,
        primary_target_id: str,
        selected_flow_chains: List[Dict[str, object]],
    ) -> Dict[str, object]:
        if not primary_target_id or not selected_flow_chains:
            return selected_flow_chains[0] if selected_flow_chains else {}

        ranked = sorted(
            enumerate(selected_flow_chains),
            key=lambda item: (
                0 if str(item[1].get("query_anchor", "")) == primary_target_id else (1 if primary_target_id in [str(node_id) for node_id in item[1].get("nodes", [])] else 2),
                ([str(node_id) for node_id in item[1].get("nodes", [])].index(primary_target_id) if primary_target_id in [str(node_id) for node_id in item[1].get("nodes", [])] else 999),
                -FLOW_COMPLETENESS_ORDER.get(str(item[1].get("completeness", "")), 0),
                0 if ([str(node_id) for node_id in item[1].get("nodes", [])][:1] == [primary_target_id]) else (1 if primary_target_id in [str(node_id) for node_id in item[1].get("nodes", [])][:2] else 2),
                item[0],
            ),
        )
        return dict(ranked[0][1]) if ranked else {}

    def _select_primary_evidence_path(
        self,
        primary_target_id: str,
        selected_paths: List[Dict[str, object]],
    ) -> Dict[str, object]:
        if not primary_target_id or not selected_paths:
            return selected_paths[0] if selected_paths else {}

        ranked = sorted(
            enumerate(selected_paths),
            key=lambda item: (
                0 if str(item[1].get("risk_node", "")) == primary_target_id else (1 if primary_target_id in self._ordered_path_nodes(item[1]) else 2),
                (self._ordered_path_nodes(item[1]).index(primary_target_id) if primary_target_id in self._ordered_path_nodes(item[1]) else 999),
                -len(item[1].get("query_match_signals", [])),
                -float(item[1].get("path_confidence", 0.0)),
                -float(item[1].get("query_match_score", 0.0)),
                item[0],
            ),
        )
        return dict(ranked[0][1]) if ranked else {}

    def _select_primary_flow_gap(
        self,
        primary_target_id: str,
        primary_chain: Dict[str, object],
        primary_path: Dict[str, object],
        flow_gaps: List[Dict[str, object]],
    ) -> Dict[str, object]:
        if not flow_gaps:
            return {}

        primary_chain_id = str(primary_chain.get("chain_id", "")) if primary_chain else ""
        primary_path_id = str(primary_path.get("path_id", "")) if primary_path else ""
        ranked = sorted(
            enumerate(flow_gaps),
            key=lambda item: (
                0 if primary_chain_id and str(item[1].get("chain_id", "")) == primary_chain_id else (
                    1 if primary_target_id and str(item[1].get("node_id", "")) == primary_target_id else (
                        2 if primary_path_id and primary_path_id in [str(ref) for ref in item[1].get("supporting_path_refs", [])] else 3
                    )
                ),
                len(item[1].get("missing_step_kinds", [])),
                item[0],
            ),
        )
        return dict(ranked[0][1]) if ranked else {}

    def _build_analysis_plan(
        self,
        query: str,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        selected_slices: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
        selected_flow_summaries: List[Dict[str, object]],
        selected_flow_chains: List[Dict[str, object]],
        flow_gaps: List[Dict[str, object]],
        ambiguity_watchlist: List[Dict[str, object]],
        deferred_requests: List[Dict[str, object]],
    ) -> Dict[str, object]:
        matched_signals = [str(item) for item in analysis.get("matched_semantic_signals", [])]
        recommended_outcome_mode = self._recommended_analysis_outcome_mode(
            analysis,
            selected_flow_summaries,
            selected_flow_chains,
            flow_gaps,
            ambiguity_watchlist,
            selected_paths,
        )
        candidate_outcomes = self._build_analysis_candidate_outcomes(
            query,
            analysis,
            recommended_outcome_mode,
        )
        primary_target = ranked_targets[0] if ranked_targets else {}
        primary_target_id = str(primary_target.get("node_id", "")) if primary_target else ""
        primary_chain = self._select_primary_flow_chain(primary_target_id, selected_flow_chains)
        primary_path = self._select_primary_evidence_path(primary_target_id, selected_paths)
        primary_gap = self._select_primary_flow_gap(primary_target_id, primary_chain, primary_path, flow_gaps)
        minimal_open_sequence = self._build_minimal_open_sequence(
            analysis,
            ranked_targets,
            selected_slices,
            selected_flow_summaries,
            selected_flow_chains,
            selected_paths,
            flow_gaps,
            recommended_outcome_mode,
            primary_target_id=primary_target_id,
            primary_chain=primary_chain,
            primary_path=primary_path,
            primary_gap=primary_gap,
            limit=4,
        )
        ambiguity_item = ambiguity_watchlist[0] if ambiguity_watchlist else {}
        branch_requests = [
            {
                "branch_id": f"branch_{index:02d}",
                "when": "Only open this branch if the current selected slices do not satisfy the active step.",
                "deferred_request_ref": f"ask_deferred_request_{index:02d}",
                "request_kind": str(item.get("request_kind", "")),
                "why": str(item.get("why", "")),
                "targets": list(item.get("targets", []))[:3],
            }
            for index, item in enumerate(deferred_requests[:3], start=1)
        ]

        steps: List[Dict[str, object]] = []

        def add_step(
            step_kind: str,
            question: str,
            target_symbols: List[str],
            target_slice_refs: List[str],
            target_flow_refs: List[str],
            target_path_refs: List[str],
            why_this_step: str,
            expected_evidence: str,
            success_condition: str,
            if_success_next: str,
            if_failure_next: str,
            if_ambiguous_next: str,
            stop_if_answered: bool,
        ) -> str:
            step_id = f"step_{len(steps) + 1:02d}"
            steps.append(
                {
                    "step_id": step_id,
                    "step_kind": step_kind,
                    "question": question,
                    "target_symbols": target_symbols,
                    "target_slice_refs": target_slice_refs,
                    "target_flow_refs": target_flow_refs,
                    "target_path_refs": target_path_refs,
                    "why_this_step": why_this_step,
                    "expected_evidence": expected_evidence,
                    "success_condition": success_condition,
                    "if_success_next": if_success_next,
                    "if_failure_next": if_failure_next,
                    "if_ambiguous_next": if_ambiguous_next,
                    "stop_if_answered": stop_if_answered,
                }
            )
            return step_id

        final_step_kind = f"synthesize_{recommended_outcome_mode}"
        final_step_id = "step_final"

        primary_target_slice_refs = [
            str(item["slice_ref"])
            for item in minimal_open_sequence
            if str(item.get("symbol", "")) == primary_target_id
        ]
        primary_slice_ref = primary_target_slice_refs[0] if primary_target_slice_refs else (minimal_open_sequence[0]["slice_ref"] if minimal_open_sequence else "")
        primary_path_refs: List[str] = []
        if primary_path and primary_path.get("path_id"):
            primary_path_refs.append(str(primary_path["path_id"]))
        primary_path_refs.extend(
            str(item)
            for item in primary_chain.get("supporting_path_refs", [])
            if str(item) not in primary_path_refs
        )

        single_slice_confirmable = bool(
            recommended_outcome_mode == "confirmed"
            and primary_chain
            and str(primary_chain.get("completeness", "")) == "complete"
            and len(primary_chain.get("supporting_slice_refs", [])) <= 1
        )

        followup_step_id = "step_02"
        gap_step_needed = bool(primary_gap)
        ambiguity_step_needed = bool(ambiguity_item)
        if primary_chain and primary_gap:
            followup_step_id = "step_02"
        elif primary_chain or primary_gap or ambiguity_item:
            followup_step_id = "step_02"
        else:
            followup_step_id = final_step_id

        add_step(
            step_kind="inspect_primary_slice",
            question=f"What is the smallest direct evidence inside `{primary_target.get('node_id', '') or query}` for `{query}`?",
            target_symbols=[str(primary_target["node_id"])] if primary_target else [],
            target_slice_refs=[primary_slice_ref] if primary_slice_ref else [],
            target_flow_refs=[],
            target_path_refs=primary_path_refs,
            why_this_step="Start with the highest-ranked executable or query-focused slice before opening support context.",
            expected_evidence=(
                f"Direct evidence for `{', '.join(matched_signals[:4])}`."
                if matched_signals
                else "The main executable step that answers the query."
            ),
            success_condition=(
                "The primary slice already answers the query with direct evidence."
                if single_slice_confirmable
                else "The primary slice reveals the leading control step or the strongest direct evidence."
            ),
            if_success_next=final_step_id if single_slice_confirmable else followup_step_id,
            if_failure_next=followup_step_id,
            if_ambiguous_next="step_03" if ambiguity_step_needed and (primary_chain or primary_gap) else (followup_step_id if ambiguity_step_needed else followup_step_id),
            stop_if_answered=True,
        )

        if primary_chain:
            chain_kind = "confirm_flow_chain"
            if matched_signals and {"auth_guard"} & set(matched_signals) and (set(matched_signals) & (SEMANTIC_EXTERNAL_IO_SIGNALS | {"database_io"})):
                chain_kind = "confirm_guard_before_side_effect"
            elif not primary_chain.get("stitched_step_kinds"):
                chain_kind = "inspect_path_transition"
            elif str(primary_chain.get("completeness", "")) != "complete":
                chain_kind = "inspect_flow_gap"
            chain_success_next = (
                final_step_id
                if str(primary_chain.get("completeness", "")) == "complete" and recommended_outcome_mode == "confirmed"
                else ("step_03" if primary_gap else final_step_id)
            )
            add_step(
                step_kind=chain_kind,
                question=(
                    f"Does `{primary_chain.get('chain_id', '')}` provide the ordered evidence needed for `{query}`?"
                ),
                target_symbols=[str(item) for item in primary_chain.get("nodes", [])[:4]],
                target_slice_refs=[str(item) for item in primary_chain.get("supporting_slice_refs", [])[:4]],
                target_flow_refs=[str(primary_chain.get("chain_id", ""))],
                target_path_refs=primary_path_refs[:2],
                why_this_step="Use the strongest selected flow/path after the primary slice to confirm ordering or expose the remaining gap.",
                expected_evidence=(
                    f"An ordered chain covering `{', '.join(matched_signals[:4])}`."
                    if matched_signals
                    else "An ordered structural chain that resolves the query."
                ),
                success_condition=(
                    "The selected chain covers every query-matched signal in order."
                    if str(primary_chain.get("completeness", "")) == "complete"
                    else "The chain clarifies the last supported transition and exposes what is still missing."
                ),
                if_success_next=chain_success_next,
                if_failure_next="step_03" if primary_gap else final_step_id,
                if_ambiguous_next="step_03" if ambiguity_step_needed or primary_gap else final_step_id,
                stop_if_answered=True,
            )

        if primary_gap:
            gap_slice_refs = [str(item) for item in primary_gap.get("supporting_slice_refs", [])[:4]]
            gap_path_refs = [str(item) for item in primary_gap.get("supporting_path_refs", [])[:2]]
            add_step(
                step_kind="inspect_flow_gap",
                question="What direct evidence is still missing after the currently selected structural path?",
                target_symbols=[str(primary_target["node_id"])] if primary_target else [],
                target_slice_refs=gap_slice_refs,
                target_flow_refs=[str(primary_gap.get("chain_id", ""))] if primary_gap.get("chain_id") else [],
                target_path_refs=gap_path_refs,
                why_this_step="Inspect the smallest unresolved gap before requesting more code.",
                expected_evidence=(
                    f"Either a direct `{', '.join(str(item) for item in primary_gap.get('missing_step_kinds', [])[:4])}` span or confirmation that it is absent."
                ),
                success_condition="The missing signal is either directly evidenced or remains absent after the referenced slices are checked.",
                if_success_next=final_step_id,
                if_failure_next=(branch_requests[0]["branch_id"] if branch_requests else final_step_id),
                if_ambiguous_next="step_04" if ambiguity_step_needed and primary_chain else final_step_id,
                stop_if_answered=True,
            )

        if ambiguity_item:
            add_step(
                step_kind="resolve_ambiguity",
                question=f"Does the current evidence resolve the ambiguity around `{ambiguity_item.get('source_node', '')}`?",
                target_symbols=[str(ambiguity_item.get("source_node", ""))],
                target_slice_refs=[str(item) for item in ambiguity_item.get("supporting_slice_refs", [])[:3]],
                target_flow_refs=[],
                target_path_refs=[],
                why_this_step="Ambiguity must be resolved explicitly before a confirmed answer is allowed.",
                expected_evidence="A single supported candidate or a clear reason to keep the result ambiguous.",
                success_condition="Either one candidate clearly wins or the ambiguity remains explicit.",
                if_success_next=final_step_id,
                if_failure_next=(branch_requests[0]["branch_id"] if branch_requests else final_step_id),
                if_ambiguous_next=final_step_id,
                stop_if_answered=True,
            )

        final_target_slice_refs = [str(item["slice_ref"]) for item in minimal_open_sequence[:3]]
        final_target_flow_refs: List[str] = []
        if primary_chain and primary_chain.get("chain_id"):
            final_target_flow_refs.append(str(primary_chain["chain_id"]))
        if primary_gap and primary_gap.get("chain_id") and str(primary_gap["chain_id"]) not in final_target_flow_refs:
            final_target_flow_refs.append(str(primary_gap["chain_id"]))
        final_target_path_refs: List[str] = []
        if primary_path and primary_path.get("path_id"):
            final_target_path_refs.append(str(primary_path["path_id"]))
        for ref in primary_chain.get("supporting_path_refs", []):
            ref = str(ref)
            if ref and ref not in final_target_path_refs:
                final_target_path_refs.append(ref)
        for ref in primary_gap.get("supporting_path_refs", []):
            ref = str(ref)
            if ref and ref not in final_target_path_refs:
                final_target_path_refs.append(ref)
        steps.append(
            {
                "step_id": final_step_id,
                "step_kind": final_step_kind,
                "question": f"Which conservative outcome mode is justified for `{query}` now?",
                "target_symbols": [str(primary_target["node_id"])] if primary_target else [],
                "target_slice_refs": final_target_slice_refs,
                "target_flow_refs": final_target_flow_refs,
                "target_path_refs": final_target_path_refs,
                "why_this_step": "Finish with the smallest allowed claim and stop early once it is justified.",
                "expected_evidence": f"Only the evidence required by `{recommended_outcome_mode}`.",
                "success_condition": f"The evidence satisfies the `{recommended_outcome_mode}` candidate_outcome without overreach.",
                "if_success_next": "stop",
                "if_failure_next": "stop",
                "if_ambiguous_next": "stop",
                "stop_if_answered": True,
            }
        )

        decision_points: List[Dict[str, object]] = []
        for step in steps[:-1]:
            if step.get("if_success_next") and step["if_success_next"] != "stop":
                decision_points.append(
                    {
                        "decision_id": f"decision_{len(decision_points) + 1:02d}",
                        "based_on_step": str(step["step_id"]),
                        "condition": str(step["success_condition"]),
                        "next_step": str(step["if_success_next"]),
                    }
                )
            if step.get("if_failure_next") and str(step["if_failure_next"]).startswith("branch_"):
                branch = next((item for item in branch_requests if item["branch_id"] == step["if_failure_next"]), None)
                decision_points.append(
                    {
                        "decision_id": f"decision_{len(decision_points) + 1:02d}",
                        "based_on_step": str(step["step_id"]),
                        "condition": "The selected slices still do not satisfy the step success_condition.",
                        "next_step": str(final_step_id),
                        "deferred_request_ref": str(branch.get("deferred_request_ref", "")) if branch else "",
                    }
                )
            elif step.get("if_failure_next") and step["if_failure_next"] != "stop":
                decision_points.append(
                    {
                        "decision_id": f"decision_{len(decision_points) + 1:02d}",
                        "based_on_step": str(step["step_id"]),
                        "condition": "The current slice or chain does not yet answer the query fully.",
                        "next_step": str(step["if_failure_next"]),
                    }
                )

        stop_conditions = [
            {
                "outcome_mode": "confirmed",
                "condition": "Stop when a selected slice or complete flow chain covers all query-matched signals directly.",
            },
            {
                "outcome_mode": "partial",
                "condition": "Stop when part of the claim is directly evidenced but a flow gap or missing transition remains.",
            },
            {
                "outcome_mode": "unproven",
                "condition": "Stop when the selected slices and paths stay under-evidenced and the missing signal never appears directly.",
            },
            {
                "outcome_mode": "ambiguous",
                "condition": "Stop when competing candidates remain unresolved and the evidence cannot break the tie conservatively.",
            },
        ]

        return {
            "task": query,
            "overall_goal": self._analysis_overall_goal(query, analysis),
            "recommended_outcome_mode": recommended_outcome_mode,
            "steps": steps,
            "decision_points": decision_points,
            "stop_conditions": stop_conditions,
            "minimal_open_sequence": minimal_open_sequence,
            "candidate_outcomes": candidate_outcomes,
            "branch_requests": branch_requests,
        }

    def _node_brief_label(self, node_id: str) -> str:
        node = self.nodes.get(node_id)
        if node is None:
            return node_id
        if node.qualname:
            return node.qualname
        return self._flow_node_label(node_id)

    def _semantic_ref_id(self, ref: Dict[str, object]) -> str:
        lines = list(ref.get("lines", []))
        start = int(lines[0]) if lines else 0
        end = int(lines[1]) if len(lines) > 1 else start
        return f"{ref.get('file', '')}:{start}-{end}:{ref.get('signal', '')}"

    def _semantic_ref_payload(self, ref: Dict[str, object]) -> Dict[str, object]:
        lines = list(ref.get("lines", []))
        start = int(lines[0]) if lines else 0
        end = int(lines[1]) if len(lines) > 1 else start
        return {
            "ref_id": self._semantic_ref_id(ref),
            "file": str(ref.get("file", "")),
            "lines": [start, end],
            "signal": str(ref.get("signal", "")),
            "reason": str(ref.get("reason", "")),
        }

    def _flow_gap_ref(self, gap: Dict[str, object]) -> str:
        missing = ",".join(sorted(str(item) for item in gap.get("missing_step_kinds", []) if item))
        if gap.get("chain_id"):
            base = f"chain::{gap['chain_id']}"
        elif gap.get("node_id"):
            base = f"node::{gap['node_id']}"
        else:
            base = "gap::unknown"
        return f"{base}::{missing}" if missing else base

    def _ambiguity_ref(self, item: Dict[str, object]) -> str:
        return f"{item.get('source_node', '')}:{item.get('raw_call', '')}"

    def _analysis_result_behavior_phrase(
        self,
        signals: Iterable[str],
        analysis: Dict[str, object],
        primary_path: Optional[Dict[str, object]] = None,
    ) -> str:
        ordered_signals = self._sort_semantic_signals(str(item) for item in signals if item)
        signal_set = set(ordered_signals)
        query_tokens = {str(item).lower() for item in analysis.get("query_tokens", [])}
        path_labels = [
            self._node_brief_label(node_id).lower()
            for node_id in self._ordered_path_nodes(primary_path or {})
            if node_id in self.nodes
        ]
        if {"auth_guard", "database_io"} <= signal_set:
            if any("repository" in label for label in path_labels):
                db_phrase = "the repository read"
            elif "read" in query_tokens:
                db_phrase = "the database read"
            else:
                db_phrase = "database access"
            return f"auth enforced before {db_phrase}"
        if {"state_mutation", "filesystem_io"} <= signal_set:
            if {"write", "disk", "file"} & query_tokens:
                return "state mutation and a disk write"
            return "state mutation and filesystem I/O"
        phrase_map = {
            "auth_guard": "auth enforcement",
            "validation_guard": "validation",
            "state_mutation": "state mutation",
            "config_access": "config access",
            "deserialization": "deserialization",
            "serialization": "serialization",
            "database_io": "database I/O",
            "network_io": "network I/O",
            "filesystem_io": "filesystem I/O",
            "process_io": "process I/O",
            "input_boundary": "input handling",
            "output_boundary": "output handling",
            "error_handling": "error handling",
            "time_or_randomness": "time or randomness",
            "external_io": "external I/O",
        }
        phrases = [phrase_map.get(signal, signal.replace("_", " ")) for signal in ordered_signals]
        if not phrases:
            return "the requested behavior"
        if len(phrases) == 1:
            return phrases[0]
        if len(phrases) == 2:
            return f"{phrases[0]} and {phrases[1]}"
        return ", ".join(phrases[:-1]) + f", and {phrases[-1]}"

    def _analysis_result_context_phrase(
        self,
        primary_target_id: str,
        primary_path: Dict[str, object],
        primary_chain: Dict[str, object],
    ) -> str:
        node_ids: List[str] = []
        if primary_path:
            node_ids = [node_id for node_id in self._ordered_path_nodes(primary_path) if node_id != primary_target_id]
        elif primary_chain:
            node_ids = [
                str(node_id)
                for node_id in primary_chain.get("nodes", [])
                if str(node_id) and str(node_id) != primary_target_id
            ]
        labels = [self._flow_node_label(node_id) for node_id in node_ids if node_id in self.nodes]
        fetch_like = [label for label in labels if "fetch" in label.lower()]
        if fetch_like:
            return "internal fetch-related calls"
        if not labels:
            return "the selected structural context"
        unique_labels: List[str] = []
        for label in labels:
            if label not in unique_labels:
                unique_labels.append(label)
        if len(unique_labels) == 1:
            return f"internal `{unique_labels[0]}` calls"
        joined = " -> ".join(unique_labels[:3])
        return joined if len(unique_labels) <= 3 else f"{joined} context"

    def _analysis_result_confidence_posture(
        self,
        outcome_mode: str,
        primary_summary: Dict[str, object],
        primary_chain: Dict[str, object],
    ) -> str:
        if outcome_mode == "confirmed":
            if primary_chain and str(primary_chain.get("completeness", "")) == "complete":
                return "complete_flow_evidence"
            if primary_summary and str(primary_summary.get("completeness", "")) == "complete":
                return "direct_executable_evidence"
            return "bounded_confirmed_evidence"
        if outcome_mode == "partial":
            return "bounded_partial_evidence"
        if outcome_mode == "ambiguous":
            return "ambiguity_blocks_unique_answer"
        return "no_direct_evidence_for_requested_behavior"

    def _analysis_result_forbidden_overreach(
        self,
        outcome_mode: str,
        analysis: Dict[str, object],
        primary_target_id: str,
        flow_gap_refs: List[str],
        ambiguity_refs: List[str],
    ) -> Dict[str, object]:
        symbol_label = self._node_brief_label(primary_target_id) if primary_target_id else "the selected symbol"
        unsupported: List[str] = ["project_wide_claim", "root_cause_claim"]
        statements = [
            f"Do not widen `{symbol_label}` into a project-wide claim.",
            "Do not infer root cause or hidden intent from structural evidence alone.",
        ]
        matched_signals = {str(item) for item in analysis.get("matched_semantic_signals", [])}
        if outcome_mode != "confirmed" or flow_gap_refs:
            unsupported.append("complete_flow_claim")
            statements.append("Do not upgrade a partial or missing chain into a complete flow claim.")
        if "network_io" in matched_signals and outcome_mode != "confirmed":
            unsupported.append("end_to_end_claim_without_direct_io")
            statements.append("Do not claim end-to-end network I/O without a direct network evidence span.")
        if ambiguity_refs:
            unsupported.append("uniqueness_claim_without_disambiguation")
            statements.append("Do not claim a unique implementation or path while ambiguity remains unresolved.")
        return {
            "unsupported_claim_kinds": sorted(set(unsupported)),
            "statements": list(dict.fromkeys(statements)),
        }

    def _select_next_best_request(
        self,
        outcome_mode: str,
        primary_target_id: str,
        primary_gap: Dict[str, object],
        ambiguity_item: Dict[str, object],
        deferred_requests: List[Dict[str, object]],
    ) -> Optional[Dict[str, object]]:
        if outcome_mode == "confirmed" or not deferred_requests:
            return None
        primary_gap_refs = {str(item) for item in primary_gap.get("supporting_path_refs", [])}
        ranked = sorted(
            deferred_requests,
            key=lambda item: (
                -(
                    (12 if ambiguity_item and str(item.get("type", "")) == "ambiguity_followup" and str(item.get("symbol", "")) == str(ambiguity_item.get("source_node", "")) else 0)
                    + (10 if primary_target_id and str(item.get("symbol", "")) == primary_target_id else 0)
                    + (4 if primary_gap_refs and any(str(target.get("anchor_symbol", "")) == primary_target_id for target in item.get("targets", [])) else 0)
                ),
                str(item.get("type", "")),
                str(item.get("symbol", "")),
                str(item.get("request", "")),
            ),
        )
        return dict(ranked[0]) if ranked else None

    def _build_analysis_result_claim(
        self,
        outcome_mode: str,
        symbol_label: str,
        behavior_phrase: str,
