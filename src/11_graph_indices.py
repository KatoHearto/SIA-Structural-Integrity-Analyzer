# ── SIA src/11_graph_indices.py ── (god_mode_v3.py lines 3220–3559) ────────────────────
    def _build_indices(self) -> None:
        self.fq_to_id.clear()
        self.short_index.clear()
        self.file_module_node.clear()
        self.file_top_level_symbol_index.clear()
        self.go_dir_to_node.clear()
        self.java_type_to_node.clear()
        self.java_member_to_node.clear()
        self.java_concrete_type_targets.clear()
        self.rust_module_to_node.clear()
        self.frappe_doctype_name_to_node.clear()
        self.frappe_doctype_snake_to_node.clear()
        go_candidates: Dict[str, List[str]] = defaultdict(list)
        for node_id, node in self.nodes.items():
            fq = f"{node.module}.{node.qualname}"
            self.fq_to_id[fq] = node_id
            if node.kind == "doctype":
                dt_name = str(node.plugin_data.get("frappe_doctype_name", ""))
                dt_snake = str(node.plugin_data.get("frappe_snake", "")) or node.qualname
                if dt_name:
                    self.frappe_doctype_name_to_node[dt_name] = node_id
                if dt_snake:
                    self.frappe_doctype_snake_to_node[dt_snake] = node_id
            if node.language == "Python":
                short_names = [node.qualname.split(".")[-1]]
            else:
                short_names = [node.qualname.split(".")[-1], Path(node.qualname).stem] + list(node.declared_symbols)
                file_key = Path(node.file).as_posix()
                if node.kind == "module":
                    self.file_module_node[file_key] = node_id
                elif node.language in {"JavaScript", "TypeScript"} and "." not in node.qualname:
                    self.file_top_level_symbol_index[file_key][node.qualname].append(node_id)
                if node.language == "Go":
                    go_candidates[Path(node.file).parent.as_posix()].append(node_id)
                if node.language == "Java":
                    if node.kind in {"class", "interface", "enum"}:
                        fqcn = f"{node.package_name}.{node.qualname}" if node.package_name else node.qualname
                        self.java_type_to_node[fqcn] = node_id
                    elif node.kind == "method" and node.package_name:
                        self.java_member_to_node[f"{node.package_name}.{node.qualname}"] = node_id
                if node.language == "Rust":
                    module_path = node.package_name or self._rust_module_path(node.file)
                    self.rust_module_to_node[module_path] = node_id
            for short in short_names:
                if short:
                    self.short_index[short].append(node_id)

        for dt_name, node_id in self.frappe_doctype_name_to_node.items():
            snake = self._frappe_snake(dt_name)
            self.fq_to_id[snake] = node_id
            self.fq_to_id[dt_name] = node_id
            self.short_index[snake].append(node_id)

        for directory, candidates in go_candidates.items():
            selected = sorted(
                candidates,
                key=lambda candidate_id: (
                    0 if Path(self.nodes[candidate_id].file).name == "main.go" else 1,
                    0
                    if Path(self.nodes[candidate_id].file).stem == Path(directory).name and Path(directory).name
                    else 1,
                    self.nodes[candidate_id].file,
                ),
            )[0]
            self.go_dir_to_node[directory] = selected

    def _resolution(
        self,
        kind: str,
        reason: str,
        target: Optional[str] = None,
        candidates: Optional[List[str]] = None,
    ) -> ResolutionOutcome:
        score, label = RESOLUTION_CONFIDENCE.get(kind, RESOLUTION_CONFIDENCE["heuristic"])
        return ResolutionOutcome(
            target=target,
            resolution_kind=kind,
            confidence_score=score,
            confidence_label=label,
            resolution_reason=reason,
            candidates=list(candidates or []),
        )

    def _prefer_resolution(
        self,
        current: Optional[ResolutionOutcome],
        new: Optional[ResolutionOutcome],
    ) -> Optional[ResolutionOutcome]:
        if new is None:
            return current
        if current is None:
            return new
        current_key = (current.confidence_score, current.resolution_kind, current.resolution_reason)
        new_key = (new.confidence_score, new.resolution_kind, new.resolution_reason)
        return new if new_key > current_key else current

    def _record_unresolved_call_outcome(self, caller: SymbolNode, raw: str, outcome: ResolutionOutcome) -> None:
        if outcome.candidates:
            caller.heuristic_candidates[raw] = list(outcome.candidates)
        if outcome.resolution_kind:
            caller.unresolved_call_details[raw] = outcome.to_payload()

    def _add_edge(
        self,
        source: str,
        target: str,
        kind: str,
        resolution: Optional[ResolutionOutcome] = None,
    ) -> None:
        self.adj[source].add(target)
        self.edge_kinds[(source, target)].add(kind)
        if resolution and resolution.target == target:
            self.edge_resolution[(source, target)] = self._prefer_resolution(
                self.edge_resolution.get((source, target)),
                resolution,
            ) or resolution

    def _resolve_edges(self) -> None:
        for node_id in self.nodes:
            self.adj[node_id] = set()
        self.edge_kinds.clear()
        self.edge_resolution.clear()

        for node_id, node in self.nodes.items():
            node.resolved_calls.clear()
            node.resolved_bases.clear()
            node.resolved_imports.clear()
            node.external_calls.clear()
            node.external_bases.clear()
            node.external_imports.clear()
            node.unresolved_calls.clear()
            node.unresolved_call_details.clear()
            node.unresolved_bases.clear()
            node.unresolved_imports.clear()
            node.resolved_string_refs.clear()
            node.recursive_self_call = False
            node.heuristic_candidates.clear()

        for node_id, node in self.nodes.items():
            if node.kind != "class" and not node.raw_bases:
                continue
            for raw_base in sorted(node.raw_bases):
                outcome = self._resolve_base_outcome(node, raw_base)
                target = outcome.target
                if target is None:
                    base_kind = self._classify_unresolved_base(node, raw_base)
                    if base_kind == "external":
                        node.external_bases.add(raw_base)
                    elif base_kind == "unresolved":
                        node.unresolved_bases.add(raw_base)
                    continue
                if target == node_id:
                    continue
                node.resolved_bases.add(target)
                self._add_edge(node_id, target, "inheritance", outcome)

        self._build_java_concrete_type_targets()

        for node_id, node in self.nodes.items():
            for raw in sorted(node.raw_calls):
                outcome = self._resolve_call_outcome(node, raw)
                target = outcome.target
                if target is None:
                    if outcome.resolution_kind == "ambiguous_candidates":
                        self._record_unresolved_call_outcome(node, raw, outcome)
                    unresolved_kind = self._classify_unresolved_call(node, raw)
                    if unresolved_kind == "external":
                        node.external_calls.add(raw)
                    elif unresolved_kind == "unresolved":
                        node.unresolved_calls.add(raw)
                    continue
                self._add_edge(node_id, target, "call", outcome)
                if target == node_id:
                    node.recursive_self_call = True
                else:
                    node.resolved_calls.add(target)

        for node_id, node in self.nodes.items():
            for raw in sorted(node.raw_imports):
                outcome = self._resolve_import_outcome(node, raw)
                target = outcome.target
                if target is None:
                    import_kind = self._classify_unresolved_import(node, raw)
                    if import_kind == "external":
                        node.external_imports.add(raw)
                    elif import_kind == "unresolved":
                        node.unresolved_imports.add(raw)
                    continue
                if target == node_id:
                    continue
                node.resolved_imports.add(target)
                self._add_edge(node_id, target, "import", outcome)

        self._resolve_string_refs()
        self._resolve_frappe_doctype_edges()
        self._resolve_frappe_orm_calls()

        indegree: Dict[str, int] = {nid: 0 for nid in self.nodes}
        for src, dsts in self.adj.items():
            for dst in dsts:
                if src != dst:
                    indegree[dst] += 1

        for node_id, node in self.nodes.items():
            node.ca = indegree[node_id]
            node.ce_internal = len({target for target in self.adj[node_id] if target != node_id})
            node.ce_external = len(node.external_calls) + len(node.external_bases) + len(node.external_imports)
            node.ce_total = node.ce_internal + node.ce_external
            internal_total = node.ca + node.ce_internal
            total = node.ca + node.ce_total
            node.instability = round(node.ce_internal / internal_total, 4) if internal_total > 0 else 0.0
            node.instability_total = round(node.ce_total / total, 4) if total > 0 else 0.0

    def _resolve_string_refs(self) -> None:
        """Resolve dotted-path string literals to graph nodes and add string_ref edges."""
        for node_id, node in self.nodes.items():
            node.resolved_string_refs.clear()
            if not node.raw_string_refs:
                continue
            for raw in sorted(node.raw_string_refs):
                if raw in node.raw_imports or raw in node.raw_calls:
                    continue
                target = self._resolve_string_ref_target(raw, node)
                if target is None or target == node_id:
                    continue
                node.resolved_string_refs.add(target)
                outcome = self._resolution(
                    target=target,
                    kind="string_ref",
                    reason=f"Resolved string literal `\"{raw}\"` to symbol `{target}`.",
                )
                self._add_edge(node_id, target, "string_ref", outcome)

    def _lookup_node_for_dotted_ref(self, raw: str) -> Optional[str]:
        if raw in self.fq_to_id:
            return self.fq_to_id[raw]
        parts = raw.split(".")
        for length in range(len(parts) - 1, 1, -1):
            suffix = ".".join(parts[-length:])
            if suffix in self.fq_to_id:
                return self.fq_to_id[suffix]
        last = parts[-1]
        candidates = self.short_index.get(last, [])
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _resolve_string_ref_target(self, raw: str, caller: SymbolNode) -> Optional[str]:
        """Try to match a dotted string literal against known graph symbols."""
        return self._lookup_node_for_dotted_ref(raw)

    def _resolve_frappe_doctype_edges(self) -> None:
        """Add edges from DocType nodes to linked DocTypes and their controllers."""
        if "frappe" not in self.active_plugins:
            return
        for node_id, node in list(self.nodes.items()):
            if node.kind != "doctype":
                continue
            plugin_data = node.plugin_data

            for ref_name in plugin_data.get("frappe_link_refs", []):
                target = self.frappe_doctype_name_to_node.get(str(ref_name))
                if target and target != node_id:
                    outcome = self._resolution(
                        target=target,
                        kind="doctype_link",
                        reason=f"Link field references DocType `{ref_name}`.",
                    )
                    self._add_edge(node_id, target, "doctype_link", outcome)

            for ref_name in plugin_data.get("frappe_child_refs", []):
                target = self.frappe_doctype_name_to_node.get(str(ref_name))
                if target and target != node_id:
                    outcome = self._resolution(
                        target=target,
                        kind="doctype_child",
                        reason=f"Table field embeds child DocType `{ref_name}`.",
                    )
                    self._add_edge(node_id, target, "doctype_child", outcome)

            controller_path = str(plugin_data.get("frappe_controller_path", ""))
            if not controller_path:
                continue
            target = self.file_module_node.get(controller_path)
            if not target:
                target = self.file_module_node.get(controller_path.replace("/", os.sep))
            if not target:
                target = self._frappe_controller_symbol_for_path(controller_path)
            if target and target != node_id:
                outcome = self._resolution(
                    target=target,
                    kind="doctype_controller",
                    reason=f"Conventional Frappe controller path `{controller_path}`.",
                )
                self._add_edge(node_id, target, "doctype_controller", outcome)

    def _resolve_frappe_orm_calls(self) -> None:
        """Resolve Frappe ORM string-path references to DocType nodes."""
        if "frappe" not in self.active_plugins:
            return
        for node_id, node in self.nodes.items():
            source_path = os.path.join(self.root_dir, node.file)
            if not node.file.endswith(".py") or not os.path.exists(source_path):
                continue

            try:
                content = Path(source_path).read_text(encoding="utf-8")
                matches = _FRAPPE_ORM_LOAD_RE.findall(content) + _FRAPPE_DB_RE.findall(content)
                for dt_name in matches:
                    target = self.frappe_doctype_name_to_node.get(dt_name)
                    if not target:
                        target = self.frappe_doctype_name_to_node.get(self._frappe_snake(dt_name))

                    if target and target != node_id:
                        outcome = self._resolution(
                            kind="orm_load",
                            reason=f"Frappe ORM call references DocType `{dt_name}` via string argument.",
                            target=target,
                        )
                        self._add_edge(node_id, target, "orm_load", outcome)
            except Exception:
                continue

    def _frappe_controller_symbol_for_path(self, controller_path: str) -> Optional[str]:

        normalized = Path(controller_path).as_posix()
        candidates = [
            node_id for node_id, node in self.nodes.items()
            if Path(node.file).as_posix() == normalized and node.language == "Python"
        ]
        if not candidates:
            return None
        module_candidates = [node_id for node_id in candidates if self.nodes[node_id].kind == "module"]
        if module_candidates:
            return sorted(module_candidates)[0]
        class_candidates = [node_id for node_id in candidates if self.nodes[node_id].kind == "class"]
        if class_candidates:
            return sorted(class_candidates)[0]
        return sorted(candidates)[0]

