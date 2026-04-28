# ── SIA src/14_analysis.py ── (god_mode_v3.py lines 9501–13575) ────────────────────
        requested_phrase: str,
        context_phrase: str,
        decisive_signals: List[str],
        ambiguity_item: Dict[str, object],
    ) -> Tuple[str, str]:
        if outcome_mode == "confirmed":
            if {"auth_guard", "database_io"} <= set(decisive_signals):
                claim = f"Auth is enforced in {symbol_label} before the repository read." if "repository read" in behavior_phrase else f"Auth is enforced in {symbol_label} before the database read."
                claim_short = f"Confirmed auth-before-read in {symbol_label}."
            elif {"state_mutation", "filesystem_io"} <= set(decisive_signals):
                claim = f"{symbol_label} performs state mutation and writes to disk."
                claim_short = f"{symbol_label} mutates state and writes to disk."
            else:
                claim = f"{symbol_label} directly evidences {behavior_phrase}."
                claim_short = f"Confirmed in {symbol_label}: {behavior_phrase}."
        elif outcome_mode == "partial":
            claim = f"The selected evidence shows {symbol_label} covering {behavior_phrase}, but not the full requested behavior."
            claim_short = f"Partial evidence in {symbol_label}."
        elif outcome_mode == "ambiguous":
            candidates = [
                self._node_brief_label(str(item))
                for item in ambiguity_item.get("candidates", [])
                if str(item) in self.nodes
            ]
            candidate_text = ", ".join(candidates[:3]) if candidates else "multiple candidates"
            raw_call = str(ambiguity_item.get("raw_call", "the selected call"))
            claim = f"The selected evidence keeps `{raw_call}` in {symbol_label} ambiguous between {candidate_text}."
            claim_short = f"Ambiguous in {symbol_label}: {raw_call}."
        else:
            claim = f"The selected context shows {symbol_label} reaching {context_phrase}, but no direct {requested_phrase} evidence."
            claim_short = f"No direct {requested_phrase} evidence for {symbol_label}."
        return claim, claim_short

    def _build_analysis_result_metadata(
        self,
        outcome_mode: str,
        missing_signals: List[str],
        primary_gap: Dict[str, object],
        ambiguity_item: Dict[str, object],
        flow_gap_refs: List[str],
        ambiguity_refs: List[str],
        primary_chain: Dict[str, object],
        primary_summary: Dict[str, object],
        decisive_signals: List[str],
        primary_target_id: str,
        supporting_slice_refs: List[str],
        supporting_flow_refs: List[str],
        supporting_path_refs: List[str],
        semantic_refs: List[Dict[str, object]],
    ) -> Tuple[List[Dict[str, object]], Dict[str, object], List[str], List[str]]:
        missing_evidence: List[Dict[str, object]] = []
        if outcome_mode in {"partial", "unproven"} and missing_signals:
            missing_evidence.append(
                {
                    "kind": "missing_signal",
                    "signals": list(missing_signals),
                    "reason": "No selected direct semantic span covers these query-matched signals.",
                }
            )
        if primary_gap:
            missing_evidence.append(
                {
                    "kind": str(primary_gap.get("gap_kind", "flow_gap")),
                    "gap_ref": flow_gap_refs[0],
                    "signals": list(primary_gap.get("missing_step_kinds", [])),
                    "reason": str(primary_gap.get("reason", "")),
                }
            )
        if ambiguity_item:
            missing_evidence.append(
                {
                    "kind": "ambiguity",
                    "ambiguity_ref": ambiguity_refs[0],
                    "candidates": list(ambiguity_item.get("candidates", [])),
                    "reason": str(ambiguity_item.get("resolution_reason", "")),
                }
            )

        if outcome_mode == "ambiguous":
            decisive_outcome_rule = "ambiguity_watchlist_blocks_unique_answer"
        elif primary_chain and str(primary_chain.get("completeness", "")) == "complete":
            decisive_outcome_rule = "complete_flow_chain_covers_all_query_signals"
        elif primary_summary and str(primary_summary.get("completeness", "")) == "complete":
            decisive_outcome_rule = "single_executable_flow_covers_all_query_signals"
        elif outcome_mode == "partial" and primary_gap:
            decisive_outcome_rule = "direct_evidence_exists_but_flow_gap_remains"
        elif supporting_path_refs or primary_gap:
            decisive_outcome_rule = "selected_context_lacks_direct_query_signal"
        else:
            decisive_outcome_rule = "selected_evidence_does_not_justify_broader_claim"

        minimal_basis = {
            "primary_symbol": primary_target_id,
            "decisive_slice_refs": list(supporting_slice_refs[:3]),
            "decisive_flow_refs": list(supporting_flow_refs[:2]),
            "decisive_path_refs": list(supporting_path_refs[:2]),
            "decisive_semantic_signals": list(decisive_signals[:6]),
            "decisive_outcome_rule": decisive_outcome_rule,
        }

        evidence_refs = list(
            dict.fromkeys(
                list(supporting_slice_refs)
                + list(supporting_flow_refs)
                + list(supporting_path_refs)
                + [item["ref_id"] for item in semantic_refs]
                + flow_gap_refs
                + ambiguity_refs
            )
        )
        result_reasoning_notes = [
            f"Outcome follows `analysis_plan.recommended_outcome_mode = {outcome_mode}`.",
            "Direct executable evidence outranks context-only structure.",
        ]
        if outcome_mode == "confirmed":
            result_reasoning_notes.append("A selected complete executable flow or chain covers the required query signals.")
        elif outcome_mode == "partial":
            result_reasoning_notes.append("At least one required signal is directly evidenced, but the requested behavior remains incomplete.")
        elif outcome_mode == "ambiguous":
            result_reasoning_notes.append("Competing candidates remain unresolved, so uniqueness is not allowed.")
        else:
            result_reasoning_notes.append("Selected paths stay structural or contextual while the requested direct signal remains absent.")

        return missing_evidence, minimal_basis, evidence_refs, result_reasoning_notes

    def _build_analysis_result(
        self,
        query: str,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        selected_slices: List[Dict[str, object]],
        selected_semantic_refs: List[Dict[str, object]],
        selected_flow_summaries: List[Dict[str, object]],
        selected_flow_chains: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
        flow_gaps: List[Dict[str, object]],
        ambiguity_watchlist: List[Dict[str, object]],
        deferred_requests: List[Dict[str, object]],
        analysis_plan: Dict[str, object],
    ) -> Dict[str, object]:
        outcome_mode = str(analysis_plan.get("recommended_outcome_mode", "unproven") or "unproven")
        primary_target = ranked_targets[0] if ranked_targets else {}
        primary_target_id = str(primary_target.get("node_id", "")) if primary_target else ""
        primary_chain = self._select_primary_flow_chain(primary_target_id, selected_flow_chains)
        primary_path = self._select_primary_evidence_path(primary_target_id, selected_paths)
        primary_gap = self._select_primary_flow_gap(primary_target_id, primary_chain, primary_path, flow_gaps)
        primary_summary = next(
            (item for item in selected_flow_summaries if str(item.get("node_id", "")) == primary_target_id),
            {},
        )
        ambiguity_item = next(
            (
                item
                for item in ambiguity_watchlist
                if str(item.get("source_node", "")) == primary_target_id
            ),
            ambiguity_watchlist[0] if ambiguity_watchlist else {},
        )
        matched_signals = {str(item) for item in analysis.get("matched_semantic_signals", [])}
        requested_signals = self._sort_semantic_signals(matched_signals)
        summary_signals = {
            str(item)
            for item in primary_summary.get("ordered_step_kinds", [])
            if str(item) in matched_signals
        }
        chain_signals = {
            str(item)
            for item in primary_chain.get("stitched_step_kinds", [])
            if str(item) in matched_signals
        }
        primary_related_nodes = {primary_target_id}
        primary_related_nodes.update(self._ordered_path_nodes(primary_path))
        primary_related_nodes.update(str(item) for item in primary_chain.get("nodes", []))
        semantic_refs = [
            self._semantic_ref_payload(item)
            for item in selected_semantic_refs
            if str(item.get("node_id", "")) in primary_related_nodes
            and (not matched_signals or str(item.get("signal", "")) in matched_signals)
        ]
        if not semantic_refs and primary_target_id in self.nodes:
            semantic_refs = [
                self._semantic_ref_payload(item)
                for item in self._query_relevant_semantic_refs(
                    list(self.nodes[primary_target_id].semantic_evidence_spans),
                    matched_signals,
                    limit=4,
                )
            ]
        semantic_refs = self._dedupe_object_list(semantic_refs)[:4]
        semantic_ref_signals = {
            str(item.get("signal", ""))
            for item in semantic_refs
            if str(item.get("signal", "")) in matched_signals
        }
        decisive_signals = self._sort_semantic_signals(summary_signals | chain_signals | semantic_ref_signals)
        missing_signals = self._sort_semantic_signals(matched_signals - set(decisive_signals))
        minimal_open_sequence = list(analysis_plan.get("minimal_open_sequence", []))
        primary_slice_refs = [
            str(item["slice_ref"])
            for item in minimal_open_sequence
            if str(item.get("symbol", "")) == primary_target_id
        ]
        if not primary_slice_refs and minimal_open_sequence:
            primary_slice_refs = [str(minimal_open_sequence[0]["slice_ref"])]
        supporting_slice_refs: List[str] = []
        for ref in primary_slice_refs:
            if ref and ref not in supporting_slice_refs:
                supporting_slice_refs.append(ref)
        for ref in primary_chain.get("supporting_slice_refs", []):
            ref = str(ref)
            if ref and ref not in supporting_slice_refs:
                supporting_slice_refs.append(ref)
        for ref in primary_gap.get("supporting_slice_refs", []):
            ref = str(ref)
            if ref and ref not in supporting_slice_refs:
                supporting_slice_refs.append(ref)
        supporting_slice_refs = supporting_slice_refs[:4]

        supporting_flow_refs: List[str] = []
        if primary_chain and primary_chain.get("chain_id"):
            supporting_flow_refs.append(str(primary_chain["chain_id"]))
        if primary_gap and primary_gap.get("chain_id") and str(primary_gap["chain_id"]) not in supporting_flow_refs:
            supporting_flow_refs.append(str(primary_gap["chain_id"]))

        supporting_path_refs: List[str] = []
        if primary_path and primary_path.get("path_id"):
            supporting_path_refs.append(str(primary_path["path_id"]))
        for ref in primary_chain.get("supporting_path_refs", []):
            ref = str(ref)
            if ref and ref not in supporting_path_refs:
                supporting_path_refs.append(ref)
        for ref in primary_gap.get("supporting_path_refs", []):
            ref = str(ref)
            if ref and ref not in supporting_path_refs:
                supporting_path_refs.append(ref)

        flow_gap_refs = [self._flow_gap_ref(primary_gap)] if primary_gap else []
        ambiguity_refs = [self._ambiguity_ref(ambiguity_item)] if ambiguity_item else []
        forbidden_overreach = self._analysis_result_forbidden_overreach(
            outcome_mode,
            analysis,
            primary_target_id,
            flow_gap_refs,
            ambiguity_refs,
        )
        next_best_request = self._select_next_best_request(
            outcome_mode,
            primary_target_id,
            primary_gap,
            ambiguity_item,
            deferred_requests,
        )
        symbol_label = self._node_brief_label(primary_target_id) if primary_target_id else "the selected symbol"
        behavior_phrase = self._analysis_result_behavior_phrase(decisive_signals, analysis, primary_path)
        requested_phrase = self._analysis_result_behavior_phrase(missing_signals or matched_signals, analysis, primary_path)
        context_phrase = self._analysis_result_context_phrase(primary_target_id, primary_path, primary_chain)

        claim, claim_short = self._build_analysis_result_claim(
            outcome_mode,
            symbol_label,
            behavior_phrase,
            requested_phrase,
            context_phrase,
            decisive_signals,
            ambiguity_item,
        )

        missing_evidence, minimal_basis, evidence_refs, result_reasoning_notes = (
            self._build_analysis_result_metadata(
                outcome_mode,
                missing_signals,
                primary_gap,
                ambiguity_item,
                flow_gap_refs,
                ambiguity_refs,
                primary_chain,
                primary_summary,
                decisive_signals,
                primary_target_id,
                supporting_slice_refs,
                supporting_flow_refs,
                supporting_path_refs,
                semantic_refs,
            )
        )

        return {
            "outcome_mode": outcome_mode,
            "claim": claim,
            "claim_short": claim_short,
            "confidence_posture": self._analysis_result_confidence_posture(outcome_mode, primary_summary, primary_chain),
            "requested_semantic_signals": requested_signals,
            "evidence_refs": evidence_refs[:12],
            "supporting_slice_refs": supporting_slice_refs,
            "supporting_flow_refs": supporting_flow_refs,
            "supporting_path_refs": supporting_path_refs,
            "supporting_semantic_refs": semantic_refs,
            "flow_gap_refs": flow_gap_refs,
            "ambiguity_refs": ambiguity_refs,
            "minimal_basis": minimal_basis,
            "missing_evidence": missing_evidence,
            "forbidden_overreach": forbidden_overreach,
            "next_best_request": next_best_request,
            "result_reasoning_notes": result_reasoning_notes,
            "outcome_explanation": {
                "one_sentence": claim_short,
                "evidence_sentence": (
                    f"Key evidence: {', '.join(evidence_refs[:3])}."
                    if evidence_refs
                    else "Key evidence: no decisive reference was selected."
                ),
                "limitation_sentence": forbidden_overreach["statements"][0] if forbidden_overreach["statements"] else "Do not go beyond the selected evidence.",
            },
        }

    def _outcome_mode_rank(self, outcome_mode: str) -> int:
        return OUTCOME_MODE_ORDER.get(outcome_mode, -1)

    def _outcome_upgrade_label(self, current_outcome: str, target_outcome: str) -> str:
        if not target_outcome or target_outcome == current_outcome:
            return "none"
        return f"{current_outcome} -> {target_outcome}"

    def _request_signature(self, request: Dict[str, object]) -> str:
        return json.dumps(request, sort_keys=True)

    def _escalation_target_symbols(self, request: Dict[str, object]) -> List[str]:
        symbols: List[str] = []
        primary_symbol = str(request.get("symbol", ""))
        if primary_symbol:
            symbols.append(primary_symbol)
        for candidate in request.get("candidates", []):
            candidate = str(candidate)
            if candidate and candidate not in symbols:
                symbols.append(candidate)
        for target in request.get("targets", []):
            anchor_symbol = str(target.get("anchor_symbol", ""))
            if anchor_symbol and anchor_symbol not in symbols:
                symbols.append(anchor_symbol)
        return symbols[:4]

    def _escalation_target_slice_candidates(self, request: Dict[str, object]) -> List[Dict[str, object]]:
        candidates: List[Dict[str, object]] = []
        seen: Set[Tuple[str, int, int, str, str]] = set()
        for target in request.get("targets", []):
            file_name = str(target.get("file", ""))
            lines = list(target.get("lines", []))
            if not file_name or not lines:
                continue
            start = int(lines[0])
            end = int(lines[1]) if len(lines) > 1 else start
            anchor_symbol = str(target.get("anchor_symbol", ""))
            signal = str(target.get("signal", ""))
            key = (file_name, start, end, anchor_symbol, signal)
            if key in seen:
                continue
            seen.add(key)
            payload: Dict[str, object] = {
                "file": file_name,
                "lines": [start, end],
            }
            if anchor_symbol:
                payload["anchor_symbol"] = anchor_symbol
            if signal:
                payload["signal"] = signal
            if target.get("why"):
                payload["why"] = str(target.get("why", ""))
            candidates.append(payload)
        return candidates[:3]

    def _escalation_cost_payload(self, target_slice_candidates: List[Dict[str, object]]) -> Dict[str, object]:
        unique_files = {str(item.get("file", "")) for item in target_slice_candidates if item.get("file")}
        additional_line_span = sum(
            max(1, int(item["lines"][1]) - int(item["lines"][0]) + 1)
            for item in target_slice_candidates
            if item.get("lines")
        )
        target_count = len(target_slice_candidates)
        if target_count <= 1 and additional_line_span <= 8 and len(unique_files) <= 1:
            label = "low"
        elif target_count <= 2 and additional_line_span <= 24 and len(unique_files) <= 2:
            label = "medium"
        else:
            label = "high"
        return {
            "label": label,
            "additional_target_count": target_count,
            "additional_file_count": len(unique_files),
            "additional_line_span": additional_line_span,
        }

    def _derive_synthetic_ambiguity_request(
        self,
        ambiguity_item: Dict[str, object],
        selected_slices: List[Dict[str, object]],
    ) -> Optional[Dict[str, object]]:
        if not ambiguity_item:
            return None
        next_target = ambiguity_item.get("recommended_next_evidence_target", {})
        raw_targets = list(next_target.get("targets", [])) if isinstance(next_target, dict) else []
        targets: List[Dict[str, object]] = []
        for target in raw_targets:
            file_name = str(target.get("file", ""))
            lines = list(target.get("lines", []))
            if not file_name or not lines:
                continue
            if self._slice_covers_lines(selected_slices, file_name, lines):
                continue
            targets.append(
                {
                    "file": file_name,
                    "lines": lines,
                    "why": str(target.get("why", "")),
                }
            )
        if not targets:
            return None
        return {
            "type": "ambiguity_followup",
            "symbol": str(ambiguity_item.get("source_node", "")),
            "raw_call": str(ambiguity_item.get("raw_call", "")),
            "candidates": list(ambiguity_item.get("candidates", [])),
            "request": (
                f"Open only the caller and smallest candidate slices for `{ambiguity_item.get('raw_call', '')}` "
                "to resolve the remaining ambiguity."
            ),
            "targets": targets[:3],
            "why": str(ambiguity_item.get("resolution_reason", "")),
        }

    def _derive_synthetic_semantic_gap_request(
        self,
        primary_target_id: str,
        primary_path: Dict[str, object],
        primary_chain: Dict[str, object],
        missing_signals: List[str],
        selected_slices: List[Dict[str, object]],
    ) -> Optional[Dict[str, object]]:
        if not primary_target_id or not missing_signals:
            return None
        ordered_nodes: List[str] = [primary_target_id]
        for node_id in self._ordered_path_nodes(primary_path):
            if node_id and node_id not in ordered_nodes:
                ordered_nodes.append(node_id)
        for node_id in primary_chain.get("nodes", []):
            node_id = str(node_id)
            if node_id and node_id not in ordered_nodes:
                ordered_nodes.append(node_id)
        candidate_refs: List[Tuple[int, int, str, str, str, Dict[str, object]]] = []
        missing_signal_set = set(str(item) for item in missing_signals)
        for index, node_id in enumerate(ordered_nodes):
            node = self.nodes.get(node_id)
            if node is None:
                continue
            for ref in node.semantic_evidence_spans:
                signal = str(ref.get("signal", ""))
                if signal not in missing_signal_set:
                    continue
                file_name = str(ref.get("file", ""))
                lines = list(ref.get("lines", []))
                if not file_name or not lines:
                    continue
                if self._slice_covers_lines(selected_slices, file_name, lines):
                    continue
                span = max(1, int(lines[1]) - int(lines[0]) + 1)
                candidate_refs.append((index, span, file_name, signal, node_id, ref))
        candidate_refs.sort(
            key=lambda item: (
                item[0],
                item[1],
                item[2],
                item[3],
                item[4],
            )
        )
        if not candidate_refs:
            return None
        _, _, _, signal, node_id, ref = candidate_refs[0]
        return {
            "type": "semantic_followup",
            "symbol": node_id,
            "signals": [signal],
            "request": (
                f"Open only `{ref['file']}:{ref['lines'][0]}-{ref['lines'][1]}` "
                f"to validate the missing `{signal}` evidence."
            ),
            "targets": [
                {
                    "file": str(ref["file"]),
                    "lines": list(ref["lines"]),
                    "anchor_symbol": node_id,
                    "signal": signal,
                    "why": str(ref.get("reason", "")),
                }
            ],
            "why": f"Potential direct evidence for the missing query signal `{signal}` on the primary evidence path.",
        }

    def _build_escalation_option(
        self,
        option_id: str,
        source: str,
        request_ref: str,
        request: Dict[str, object],
        current_outcome: str,
        analysis_result: Dict[str, object],
        primary_gap: Dict[str, object],
        ambiguity_item: Dict[str, object],
    ) -> Dict[str, object]:
        requested_signals = {str(item) for item in analysis_result.get("requested_semantic_signals", [])}
        missing_signals = {
            str(signal)
            for item in analysis_result.get("missing_evidence", [])
            if str(item.get("kind", "")) == "missing_signal"
            for signal in item.get("signals", [])
        }
        target_slice_candidates = self._escalation_target_slice_candidates(request)
        target_symbols = self._escalation_target_symbols(request)
        request_type = str(request.get("type", ""))
        signal_gain = {
            str(item)
            for item in request.get("signals", [])
            if str(item) in requested_signals
        }
        for target in target_slice_candidates:
            signal = str(target.get("signal", ""))
            if signal in requested_signals:
                signal_gain.add(signal)

        expected_evidence_gain: List[str] = []
        if signal_gain:
            expected_evidence_gain.append("direct_semantic_evidence")
        if request_type == "ambiguity_followup" or source == "ambiguity_watchlist":
            expected_evidence_gain.append("candidate_disambiguation")
        if primary_gap and set(str(item) for item in primary_gap.get("missing_step_kinds", [])) & signal_gain:
            expected_evidence_gain.append("close_flow_gap")
        elif request_type == "focused_symbol_followup":
            expected_evidence_gain.append("path_transition_validation")

        path_gain_refs = list(analysis_result.get("supporting_path_refs", []))[:2]
        flow_gap_refs = list(analysis_result.get("flow_gap_refs", []))[:2]
        if request_type == "ambiguity_followup" or source == "ambiguity_watchlist":
            path_gain_kind = "resolve_ambiguity"
        elif primary_gap and set(str(item) for item in primary_gap.get("missing_step_kinds", [])) & signal_gain:
            path_gain_kind = "close_primary_flow_gap"
        elif signal_gain:
            path_gain_kind = "direct_signal_confirmation"
        elif request_type == "focused_symbol_followup" and path_gain_refs:
            path_gain_kind = "validate_existing_path"
        else:
            path_gain_kind = "no_path_gain"
        expected_path_gain = {
            "gain_kind": path_gain_kind,
            "path_refs": path_gain_refs,
            "flow_gap_refs": flow_gap_refs if path_gain_kind == "close_primary_flow_gap" else [],
        }

        expected_target_outcome = ""
        covers_all_missing = bool(missing_signals) and missing_signals <= signal_gain
        if request_type == "ambiguity_followup" or source == "ambiguity_watchlist":
            if current_outcome == "ambiguous":
                expected_target_outcome = "confirmed" if not missing_signals and not analysis_result.get("flow_gap_refs", []) else "partial"
        elif signal_gain:
            if current_outcome == "partial":
                expected_target_outcome = "confirmed" if covers_all_missing else "partial"
            elif current_outcome == "unproven":
                expected_target_outcome = "confirmed" if covers_all_missing and not analysis_result.get("ambiguity_refs", []) else "partial"
        elif request_type == "focused_symbol_followup" and current_outcome == "partial" and not missing_signals:
            expected_target_outcome = "confirmed"

        cost = self._escalation_cost_payload(target_slice_candidates)
        blocked_by: List[str] = []
        if current_outcome == "confirmed":
            blocked_by.append("confirmed_result_already_sufficient")
        if not target_slice_candidates:
            blocked_by.append("no_target_slice_candidates")
        if current_outcome == "ambiguous" and request_type != "ambiguity_followup" and source != "ambiguity_watchlist":
            blocked_by.append("ambiguity_requires_disambiguation_only")
        if not expected_target_outcome or expected_target_outcome == current_outcome:
            blocked_by.append("no_expected_outcome_upgrade")
        if cost["label"] == "high" and expected_target_outcome != "confirmed":
            blocked_by.append("cost_exceeds_bounded_gain")
        allowed = not blocked_by

        if not allowed:
            confidence = "low"
        elif expected_target_outcome == "confirmed" and cost["label"] == "low" and signal_gain:
            confidence = "high"
        elif expected_target_outcome in {"confirmed", "partial"} and cost["label"] in {"low", "medium"}:
            confidence = "medium"
        else:
            confidence = "low"

        return {
            "option_id": option_id,
            "source": source,
            "request_ref": request_ref,
            "target_symbols": target_symbols,
            "target_slice_candidates": target_slice_candidates,
            "why": str(request.get("why", "")) or str(request.get("request", "")),
            "expected_evidence_gain": expected_evidence_gain,
            "expected_signal_gain": self._sort_semantic_signals(signal_gain),
            "expected_path_gain": expected_path_gain,
            "expected_target_outcome": expected_target_outcome,
            "expected_outcome_upgrade": self._outcome_upgrade_label(current_outcome, expected_target_outcome),
            "confidence": confidence,
            "cost": cost,
            "allowed": allowed,
            "blocked_by": blocked_by,
        }

    def _build_escalation_controller(
        self,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        selected_slices: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
        selected_flow_chains: List[Dict[str, object]],
        flow_gaps: List[Dict[str, object]],
        ambiguity_watchlist: List[Dict[str, object]],
        deferred_requests: List[Dict[str, object]],
        analysis_result: Dict[str, object],
    ) -> Dict[str, object]:
        current_outcome = str(analysis_result.get("outcome_mode", "unproven") or "unproven")
        primary_target_id = str(analysis_result.get("minimal_basis", {}).get("primary_symbol", "") or "")
        primary_chain = self._select_primary_flow_chain(primary_target_id, selected_flow_chains)
        primary_path = self._select_primary_evidence_path(primary_target_id, selected_paths)
        primary_gap = self._select_primary_flow_gap(primary_target_id, primary_chain, primary_path, flow_gaps)
        ambiguity_item = next(
            (
                item
                for item in ambiguity_watchlist
                if str(item.get("source_node", "")) == primary_target_id
            ),
            ambiguity_watchlist[0] if ambiguity_watchlist else {},
        )

        if current_outcome == "confirmed":
            return {
                "current_result_ref": "analysis_result",
                "current_outcome_mode": current_outcome,
                "escalation_needed": False,
                "escalation_allowed": False,
                "escalation_reason": "The current confirmed result already satisfies the query conservatively.",
                "stop_reason": "sufficient_confirmed_result",
                "current_sufficiency": "sufficient_confirmed_result",
                "next_step_mode": "stop",
                "escalation_options": [],
                "recommended_option": None,
                "maximum_reachable_outcome": "confirmed",
                "escalation_budget": {
                    "max_options_considered": 4,
                    "max_target_slices_per_option": 2,
                    "low_cost_line_span": 8,
                    "medium_cost_line_span": 24,
                },
                "next_ask_seed": None,
            }

        request_candidates: List[Tuple[str, str, Dict[str, object]]] = []
        seen_requests: Set[str] = set()
        next_best_request = analysis_result.get("next_best_request")
        if isinstance(next_best_request, dict) and next_best_request:
            signature = self._request_signature(next_best_request)
            seen_requests.add(signature)
            request_candidates.append(("next_best_request", "analysis_result.next_best_request", dict(next_best_request)))
        for index, request in enumerate(deferred_requests, start=1):
            signature = self._request_signature(request)
            if signature in seen_requests:
                continue
            seen_requests.add(signature)
            request_candidates.append(("deferred_request", f"ask_deferred_request_{index:02d}", dict(request)))

        synthetic_ambiguity = self._derive_synthetic_ambiguity_request(ambiguity_item, selected_slices)
        if synthetic_ambiguity is not None:
            signature = self._request_signature(synthetic_ambiguity)
            if signature not in seen_requests:
                seen_requests.add(signature)
                request_candidates.append(("ambiguity_watchlist", "synthetic_ambiguity", synthetic_ambiguity))

        synthetic_semantic_gap = self._derive_synthetic_semantic_gap_request(
            primary_target_id,
            primary_path,
            primary_chain,
            list(
                {
                    str(signal)
                    for item in analysis_result.get("missing_evidence", [])
                    if str(item.get("kind", "")) == "missing_signal"
                    for signal in item.get("signals", [])
                }
            ),
            selected_slices,
        )
        if synthetic_semantic_gap is not None:
            signature = self._request_signature(synthetic_semantic_gap)
            if signature not in seen_requests:
                seen_requests.add(signature)
                request_candidates.append(("semantic_gap", "synthetic_semantic_gap", synthetic_semantic_gap))

        options: List[Dict[str, object]] = []
        for index, (source, request_ref, request) in enumerate(request_candidates[:4], start=1):
            options.append(
                self._build_escalation_option(
                    option_id=f"option_{index:02d}",
                    source=source,
                    request_ref=request_ref,
                    request=request,
                    current_outcome=current_outcome,
                    analysis_result=analysis_result,
                    primary_gap=primary_gap,
                    ambiguity_item=ambiguity_item,
                )
            )

        cost_rank = {"low": 0, "medium": 1, "high": 2}
        confidence_rank = {"low": 0, "medium": 1, "high": 2}
        source_rank = {
            "next_best_request": 0,
            "semantic_gap": 1,
            "ambiguity_watchlist": 2,
            "deferred_request": 3,
            "path_completion": 4,
            "flow_gap": 5,
        }
        options.sort(
            key=lambda item: (
                0 if item.get("allowed") else 1,
                cost_rank.get(str(item.get("cost", {}).get("label", "")), 9),
                -self._outcome_mode_rank(str(item.get("expected_target_outcome", ""))),
                -confidence_rank.get(str(item.get("confidence", "")), -1),
                source_rank.get(str(item.get("source", "")), 9),
                str(item.get("option_id", "")),
            )
        )

        allowed_options = [item for item in options if item.get("allowed")]
        recommended_option = dict(allowed_options[0]) if allowed_options else None
        maximum_reachable_outcome = current_outcome
        for option in allowed_options:
            target_outcome = str(option.get("expected_target_outcome", ""))
            if self._outcome_mode_rank(target_outcome) > self._outcome_mode_rank(maximum_reachable_outcome):
                maximum_reachable_outcome = target_outcome

        escalation_allowed = recommended_option is not None
        escalation_needed = bool(escalation_allowed and current_outcome != "confirmed")
        if escalation_allowed:
            current_sufficiency = "bounded_result_with_escalation_option"
            escalation_reason = "A bounded next evidence step could improve the current result without widening the context excessively."
            stop_reason = None
            next_step_mode = "bounded_escalation"
        else:
            current_sufficiency = "bounded_result_without_safe_escalation"
            escalation_reason = "No bounded evidence request offers a conservative outcome upgrade from the current result."
            stop_reason = "no_bounded_evidence_gain"
            next_step_mode = "stop"

        next_ask_seed = None
        if recommended_option is not None:
            cost_label = str(recommended_option.get("cost", {}).get("label", "medium"))
            next_ask_seed = {
                "derived_query": str(recommended_option.get("why", "")) or str(recommended_option.get("request_ref", "")),
                "derived_focus_symbols": list(recommended_option.get("target_symbols", []))[:3],
                "derived_budget": 20 if cost_label == "low" else (35 if cost_label == "medium" else 60),
                "derived_goal": str(recommended_option.get("expected_outcome_upgrade", "")) or "gather_additional_evidence",
            }

        return {
            "current_result_ref": "analysis_result",
            "current_outcome_mode": current_outcome,
            "escalation_needed": escalation_needed,
            "escalation_allowed": escalation_allowed,
            "escalation_reason": escalation_reason,
            "stop_reason": stop_reason,
            "current_sufficiency": current_sufficiency,
            "next_step_mode": next_step_mode,
            "escalation_options": options,
            "recommended_option": recommended_option,
            "maximum_reachable_outcome": maximum_reachable_outcome,
            "escalation_budget": {
                "max_options_considered": 4,
                "max_target_slices_per_option": 2,
                "low_cost_line_span": 8,
                "medium_cost_line_span": 24,
            },
            "next_ask_seed": next_ask_seed,
        }

    def _build_escalation_prompt(self, ask_context_pack: Dict[str, object]) -> str:
        query = str(ask_context_pack.get("query", ""))
        analysis_result = ask_context_pack.get("analysis_result", {}) if isinstance(ask_context_pack.get("analysis_result"), dict) else {}
        controller = ask_context_pack.get("escalation_controller", {}) if isinstance(ask_context_pack.get("escalation_controller"), dict) else {}
        allowed = bool(controller.get("escalation_allowed"))
        maximum_reachable = str(controller.get("maximum_reachable_outcome", "") or analysis_result.get("outcome_mode", ""))
        return (
            f"Respect `analysis_result` first for `{query}`. Escalate only if `escalation_controller.recommended_option.allowed = true` "
            f"and only by opening its `target_slice_candidates`. Treat `{maximum_reachable}` as the maximum reachable outcome after one bounded "
            "escalation step, not as a granted upgrade. If `escalation_allowed = false`, stop immediately with the exported `stop_reason`. "
            "Do not claim an upgraded outcome until the new evidence is actually opened and the analysis is rerun."
            if allowed
            else (
                f"Respect `analysis_result` first for `{query}` and stop unless a future rerun produces a bounded `recommended_option`. "
                "The current `escalation_controller` does not allow a safe next step, so do not widen the context or invent a stronger outcome."
            )
        )

    def _followup_kind_for_option(self, option: Dict[str, object]) -> str:
        source = str(option.get("source", ""))
        request_gain = set(str(item) for item in option.get("expected_evidence_gain", []))
        path_gain = option.get("expected_path_gain", {}) if isinstance(option.get("expected_path_gain"), dict) else {}
        path_gain_kind = str(path_gain.get("gain_kind", ""))
        if "candidate_disambiguation" in request_gain or source == "ambiguity_watchlist":
            return "ambiguity_resolution"
        if path_gain_kind == "close_primary_flow_gap":
            return "flow_gap_check"
        if option.get("expected_signal_gain"):
            return "semantic_confirmation"
        if path_gain_kind in {"validate_existing_path", "close_primary_flow_gap"} or source in {"path_completion", "flow_gap"}:
            return "path_completion"
        return "focused_symbol_check"

    def _followup_budget(self, option: Dict[str, object]) -> Dict[str, object]:
        target_slice_candidates = list(option.get("target_slice_candidates", []))
        cost = option.get("cost", {}) if isinstance(option.get("cost"), dict) else {}
        cost_label = str(cost.get("label", "medium") or "medium")
        unique_files = {str(item.get("file", "")) for item in target_slice_candidates if item.get("file")}
        line_span = sum(
            max(1, int(item["lines"][1]) - int(item["lines"][0]) + 1)
            for item in target_slice_candidates
            if item.get("lines")
        )
        if cost_label == "low":
            line_budget = min(max(line_span + 2, 8), 12)
            slice_budget = 1
            file_budget = 1
        elif cost_label == "medium":
            line_budget = min(max(line_span + 4, 12), 24)
            slice_budget = min(2, max(1, len(target_slice_candidates)))
            file_budget = min(2, max(1, len(unique_files) or 1))
        else:
            line_budget = min(max(line_span + 6, 18), 40)
            slice_budget = min(3, max(1, len(target_slice_candidates)))
            file_budget = min(3, max(1, len(unique_files) or 1))
        return {
            "line_budget": line_budget,
            "slice_budget": slice_budget,
            "file_budget": file_budget,
            "cost_label": cost_label,
        }

    def _build_followup_guardrails(
        self,
        focus_symbols: List[str],
        option: Dict[str, object],
        analysis_result: Dict[str, object],
    ) -> Tuple[Dict[str, object], List[str]]:
        path_gain = option.get("expected_path_gain", {}) if isinstance(option.get("expected_path_gain"), dict) else {}
        do_not_expand_beyond = {
            "focus_symbols": list(focus_symbols[:3]),
            "slice_targets": list(option.get("target_slice_candidates", []))[:2],
            "path_refs": list(path_gain.get("path_refs", []))[:2],
            "flow_refs": list(analysis_result.get("supporting_flow_refs", []))[:2],
        }
        forbidden_scope_expansions = ["do_not_generalize_project_wide"]
        if str(analysis_result.get("outcome_mode", "")) != "confirmed":
            forbidden_scope_expansions.append("do_not_infer_missing_io")
        if str(option.get("source", "")) != "ambiguity_watchlist":
            forbidden_scope_expansions.append("do_not_open_unrelated_callers")
        if do_not_expand_beyond["path_refs"]:
            forbidden_scope_expansions.append("do_not_expand_to_sibling_modules")
        if any(str(item).startswith("java.") or str(item).startswith("typescript.") or str(item).startswith("pyapp.") for item in focus_symbols):
            forbidden_scope_expansions.append("do_not_leave_primary_focus_symbols")
        return do_not_expand_beyond, sorted(set(forbidden_scope_expansions))

    def _build_followup_ask(
        self,
        query: str,
        analysis: Dict[str, object],
        analysis_result: Dict[str, object],
        escalation_controller: Dict[str, object],
    ) -> Dict[str, object]:
        recommended_option = (
            escalation_controller.get("recommended_option", {})
            if isinstance(escalation_controller.get("recommended_option"), dict)
            else {}
        )
        if not bool(escalation_controller.get("escalation_allowed")) or not recommended_option:
            return {
                "enabled": False,
                "derived_from": "escalation_controller",
                "source_option_ref": None,
                "followup_kind": "none",
                "derived_query": "",
                "derived_goal": "",
                "derived_focus_symbols": [],
                "derived_slice_targets": [],
                "derived_path_refs": [],
                "derived_flow_refs": [],
                "derived_semantic_signals": [],
                "expected_outcome_upgrade": "none",
                "maximum_reachable_outcome": str(escalation_controller.get("maximum_reachable_outcome", analysis_result.get("outcome_mode", ""))),
                "budget": {
                    "line_budget": 0,
                    "slice_budget": 0,
                    "file_budget": 0,
                    "cost_label": "none",
                },
                "stop_if": str(escalation_controller.get("stop_reason", "followup_not_allowed")),
                "stop_reason": str(escalation_controller.get("stop_reason", "followup_not_allowed")),
                "do_not_expand_beyond": {
                    "focus_symbols": [],
                    "slice_targets": [],
                    "path_refs": [],
                    "flow_refs": [],
                },
                "forbidden_scope_expansions": ["do_not_generalize_project_wide"],
            }

        primary_symbol = str(analysis_result.get("minimal_basis", {}).get("primary_symbol", "") or "")
        primary_label = self._node_brief_label(primary_symbol) if primary_symbol else "the current primary symbol"
        focus_symbols = list(recommended_option.get("target_symbols", []))[:3] or ([primary_symbol] if primary_symbol else [])
        focus_label = self._node_brief_label(focus_symbols[0]) if focus_symbols else primary_label
        followup_kind = self._followup_kind_for_option(recommended_option)
        expected_signal_gain = [str(item) for item in recommended_option.get("expected_signal_gain", []) if item]
        signal_phrase = self._analysis_result_behavior_phrase(expected_signal_gain, analysis)
        expected_outcome_upgrade = str(recommended_option.get("expected_outcome_upgrade", "none") or "none")
        maximum_reachable_outcome = str(escalation_controller.get("maximum_reachable_outcome", analysis_result.get("outcome_mode", "")))
        budget = self._followup_budget(recommended_option)
        path_gain = recommended_option.get("expected_path_gain", {}) if isinstance(recommended_option.get("expected_path_gain"), dict) else {}
        derived_path_refs = list(path_gain.get("path_refs", []))[:2]
        derived_flow_refs = list(analysis_result.get("supporting_flow_refs", []))[:2]

        if followup_kind == "ambiguity_resolution":
            derived_query = f"Resolve the remaining ambiguity for {primary_label} using only the smallest candidate slices."
            derived_goal = f"Attempt `{expected_outcome_upgrade}` by disambiguating the bounded candidate set without widening scope."
            stop_if = "Stop if the candidate slices still leave multiple plausible answers; keep the current bounded result."
        elif followup_kind == "flow_gap_check":
            derived_query = f"Check whether the selected {primary_label} path has direct {signal_phrase} evidence in the smallest remaining candidate slice."
            derived_goal = f"Attempt `{expected_outcome_upgrade}` by closing the current flow gap with one bounded evidence check."
            stop_if = f"Stop if the bounded slice still does not show direct {signal_phrase} evidence; keep the current {analysis_result.get('outcome_mode', '')} result."
        elif followup_kind == "semantic_confirmation":
            derived_query = f"Check whether {focus_label} has direct {signal_phrase} evidence in the smallest remaining candidate slice."
            derived_goal = f"Attempt `{expected_outcome_upgrade}` by confirming only the missing direct semantic evidence."
            stop_if = f"Stop if the bounded slice still does not show direct {signal_phrase} evidence; do not broaden the claim."
        elif followup_kind == "path_completion":
            derived_query = f"Check whether the selected {primary_label} path transition is directly evidenced in the smallest remaining candidate slice."
            derived_goal = f"Attempt `{expected_outcome_upgrade}` by validating one bounded path transition."
            stop_if = "Stop if the bounded slice does not close the existing path transition; keep the current bounded result."
        else:
            derived_query = f"Check only {focus_label} in the smallest remaining slice needed by the current result."
            derived_goal = f"Attempt `{expected_outcome_upgrade}` with a bounded symbol-level evidence check."
            stop_if = "Stop if the bounded symbol slice does not improve the current result; do not expand to unrelated context."

        do_not_expand_beyond, forbidden_scope_expansions = self._build_followup_guardrails(
            focus_symbols,
            recommended_option,
            analysis_result,
        )
        return {
            "enabled": True,
            "derived_from": "escalation_controller.recommended_option",
            "source_option_ref": str(recommended_option.get("option_id", "")),
            "followup_kind": followup_kind,
            "derived_query": derived_query,
            "derived_goal": derived_goal,
            "derived_focus_symbols": focus_symbols,
            "derived_slice_targets": list(recommended_option.get("target_slice_candidates", []))[:2],
            "derived_path_refs": derived_path_refs,
            "derived_flow_refs": derived_flow_refs,
            "derived_semantic_signals": expected_signal_gain,
            "expected_outcome_upgrade": expected_outcome_upgrade,
            "maximum_reachable_outcome": maximum_reachable_outcome,
            "budget": budget,
            "stop_if": stop_if,
            "do_not_expand_beyond": do_not_expand_beyond,
            "forbidden_scope_expansions": forbidden_scope_expansions,
            "stop_reason": None,
        }

    def _build_followup_prompt(self, ask_context_pack: Dict[str, object]) -> str:
        query = str(ask_context_pack.get("query", ""))
        analysis_result = ask_context_pack.get("analysis_result", {}) if isinstance(ask_context_pack.get("analysis_result"), dict) else {}
        followup_ask = ask_context_pack.get("followup_ask", {}) if isinstance(ask_context_pack.get("followup_ask"), dict) else {}
        if not bool(followup_ask.get("enabled")):
            return (
                f"Respect `analysis_result` for `{query}` and do not create a bounded follow-up ask. "
                f"The exported stop reason is `{followup_ask.get('stop_reason', 'followup_not_allowed')}`, so do not widen scope or open extra context."
            )
        return (
            f"Respect the existing `analysis_result` for `{query}`. Run only the bounded follow-up described in `followup_ask`: "
            "inspect only `derived_slice_targets`, keep the scope inside `derived_focus_symbols`, and pursue only the exported "
            "`expected_outcome_upgrade`. If the targeted slices do not yield the expected direct evidence, stop and keep the "
            f"current `{analysis_result.get('outcome_mode', '')}` result. Do not expand beyond `do_not_expand_beyond` or violate "
            "`forbidden_scope_expansions`."
        )

    def _slice_ref_from_file_lines(self, file_name: str, lines: Iterable[int]) -> str:
        line_values = list(lines)
        if not file_name or not line_values:
            return ""
        start = int(line_values[0])
        end = int(line_values[1]) if len(line_values) > 1 else start
        return f"{file_name}:{start}-{end}"

    def _infer_worker_task_kind(
        self,
        analysis: Dict[str, object],
        analysis_result: Dict[str, object],
    ) -> str:
        intents = {str(item) for item in analysis.get("inferred_intents", [])}
        matched_signals = {str(item) for item in analysis_result.get("requested_semantic_signals", [])}
        if "refactor" in intents:
            return "refactor_probe"
        if bool(analysis.get("ambiguity_sensitive")) or analysis_result.get("outcome_mode") == "ambiguous":
            return "ambiguity_check"
        if {"auth_guard", "validation_guard"} & matched_signals and (
            matched_signals & {"database_io", "network_io", "filesystem_io", "process_io", "external_io"}
        ):
            return "verify_guard"
        if analysis.get("scope_preference") == "path" or "explain_flow" in intents:
            return "explain_path"
        if matched_signals & {"filesystem_io", "database_io", "network_io", "process_io", "external_io", "state_mutation"}:
            return "inspect_side_effect"
        if "architecture" in intents:
            return "impact_check"
        return "inspect_side_effect"

    def _choose_worker_mode(
        self,
        task_kind: str,
        analysis_result: Dict[str, object],
        ambiguity_watchlist: List[Dict[str, object]],
        followup_ask: Dict[str, object],
    ) -> str:
        outcome_mode = str(analysis_result.get("outcome_mode", "unproven") or "unproven")
        if task_kind == "refactor_probe":
            return "inspect_then_refactor_plan"
        if outcome_mode == "ambiguous" and (ambiguity_watchlist or bool(followup_ask.get("enabled"))):
            return "inspect_then_compare"
        if outcome_mode == "confirmed" and not bool(followup_ask.get("enabled")):
            return "answer_only"
        if task_kind == "ambiguity_check":
            return "ambiguity_resolution_only"
        return "inspect_then_answer"

    def _work_packet_target_payload(
        self,
        node_id: str,
        role: str,
        why: str,
        slice_refs: Optional[Iterable[str]] = None,
        flow_refs: Optional[Iterable[str]] = None,
        path_refs: Optional[Iterable[str]] = None,
    ) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "symbol": node_id,
            "label": self._node_brief_label(node_id) if node_id else node_id,
            "role": role,
            "why": why,
        }
        slice_values = [str(item) for item in (slice_refs or []) if str(item)]
        flow_values = [str(item) for item in (flow_refs or []) if str(item)]
        path_values = [str(item) for item in (path_refs or []) if str(item)]
        if slice_values:
            payload["slice_refs"] = list(dict.fromkeys(slice_values))[:3]
        if flow_values:
            payload["flow_refs"] = list(dict.fromkeys(flow_values))[:2]
        if path_values:
            payload["path_refs"] = list(dict.fromkeys(path_values))[:2]
        return payload

    def _work_packet_supporting_symbols(
        self,
        primary_target_id: str,
        primary_chain: Dict[str, object],
        primary_path: Dict[str, object],
    ) -> List[str]:
        supporting: List[str] = []
        for node_id in primary_chain.get("nodes", []):
            node_id = str(node_id)
            if node_id and node_id != primary_target_id and node_id in self.nodes and node_id not in supporting:
                supporting.append(node_id)
        for node_id in self._ordered_path_nodes(primary_path):
            node_id = str(node_id)
            if node_id and node_id != primary_target_id and node_id in self.nodes and node_id not in supporting:
                supporting.append(node_id)
        supporting.sort(
            key=lambda node_id: (
                0 if self.nodes[node_id].kind in SEMANTIC_EXECUTABLE_KINDS else 1,
                self._node_brief_label(node_id),
                node_id,
            )
        )
        return supporting[:4]

    def _slice_refs_for_work_target(
        self,
        node_id: str,
        selected_slices: List[Dict[str, object]],
        preferred_refs: Optional[Set[str]] = None,
    ) -> List[str]:
        slice_refs_by_symbol = self._slice_refs_by_symbol(selected_slices)
        refs: List[str] = []
        for ref in slice_refs_by_symbol.get(node_id, []):
            ref = str(ref)
            if preferred_refs and ref not in preferred_refs:
                continue
            if ref and ref not in refs:
                refs.append(ref)
        node = self.nodes.get(node_id)
        if node is not None:
            for spec in selected_slices:
                ref = self._slice_ref(spec)
                if preferred_refs and ref not in preferred_refs:
                    continue
                if str(spec.get("file", "")) == node.file and ref not in refs:
                    refs.append(ref)
        return refs[:3]

    def _primary_ambiguity_item(
        self,
        primary_target_id: str,
        ambiguity_watchlist: List[Dict[str, object]],
    ) -> Dict[str, object]:
        if primary_target_id:
            for item in ambiguity_watchlist:
                if str(item.get("source_node", "")) == primary_target_id:
                    return dict(item)
        return dict(ambiguity_watchlist[0]) if ambiguity_watchlist else {}

    def _build_ambiguity_candidate_targets(
        self,
        primary_target_id: str,
        ambiguity_item: Dict[str, object],
        selected_slices: List[Dict[str, object]],
        read_order_refs: Set[str],
    ) -> List[Dict[str, object]]:
        if not ambiguity_item:
            return []
        targets: List[Dict[str, object]] = []
        seen_symbols: Set[str] = set()
        recommended_targets = (
            ambiguity_item.get("recommended_next_evidence_target", {}).get("targets", [])
            if isinstance(ambiguity_item.get("recommended_next_evidence_target"), dict)
            else []
        )
        for candidate_id in [str(item) for item in ambiguity_item.get("candidates", []) if str(item)]:
            if candidate_id == primary_target_id or candidate_id in seen_symbols:
                continue
            slice_refs = self._slice_refs_for_work_target(candidate_id, selected_slices, read_order_refs)
            if not slice_refs:
                node = self.nodes.get(candidate_id)
                if node is not None:
                    for target in recommended_targets:
                        file_name = str(target.get("file", ""))
                        if file_name != node.file:
                            continue
                        ref = self._slice_ref_from_file_lines(file_name, target.get("lines", []))
                        if ref and ref not in slice_refs:
                            slice_refs.append(ref)
            targets.append(
                self._work_packet_target_payload(
                    candidate_id,
                    "candidate",
                    "Candidate implementation retained by the ambiguity watchlist for direct comparison.",
                    slice_refs=slice_refs,
                )
            )
            seen_symbols.add(candidate_id)
        if len(targets) >= 3:
            return targets[:3]
        for target in recommended_targets:
            file_name = str(target.get("file", ""))
            raw_lines = list(target.get("lines", []))
            if not file_name or not raw_lines:
                continue
            start = int(raw_lines[0])
            end = int(raw_lines[1]) if len(raw_lines) > 1 else start
            matching_nodes: List[str] = []
            for node_id, node in self.nodes.items():
                if node_id == primary_target_id or node.file != file_name or node_id in seen_symbols:
                    continue
                node_start, node_end = int(node.lines[0]), int(node.lines[1])
                if node_end < start or node_start > end:
                    continue
                matching_nodes.append(node_id)
            matching_nodes.sort(
                key=lambda node_id: (
                    0 if node_id in {str(item) for item in ambiguity_item.get("candidates", [])} else 1,
                    0 if self.nodes[node_id].kind in SEMANTIC_EXECUTABLE_KINDS else 1,
                    self._node_brief_label(node_id),
                    node_id,
                )
            )
            for node_id in matching_nodes:
                slice_refs = self._slice_refs_for_work_target(node_id, selected_slices, read_order_refs)
                if not slice_refs:
                    ref = self._slice_ref_from_file_lines(file_name, raw_lines)
                    if ref:
                        slice_refs.append(ref)
                targets.append(
                    self._work_packet_target_payload(
                        node_id,
                        "support",
                        "Secondary ambiguity context retained after the concrete candidate targets.",
                        slice_refs=slice_refs,
                    )
                )
                seen_symbols.add(node_id)
                if len(targets) >= 3:
                    return targets[:3]
        return targets[:3]

    def _build_work_packet_allowed_claims(
        self,
        analysis: Dict[str, object],
        analysis_result: Dict[str, object],
        primary_target_id: str,
        primary_path: Dict[str, object],
        primary_chain: Dict[str, object],
    ) -> List[str]:
        outcome_mode = str(analysis_result.get("outcome_mode", "unproven") or "unproven")
        symbol_label = self._node_brief_label(primary_target_id) if primary_target_id else "the selected symbol"
        decisive_signals = [str(item) for item in analysis_result.get("minimal_basis", {}).get("decisive_semantic_signals", []) if item]
        context_phrase = self._analysis_result_context_phrase(primary_target_id, primary_path, primary_chain)
        behavior_phrase = self._analysis_result_behavior_phrase(decisive_signals, analysis, primary_path)
        claims = [str(analysis_result.get("claim", ""))]
        if outcome_mode == "confirmed" and decisive_signals:
            claims.append(f"Direct selected evidence confirms {behavior_phrase} in {symbol_label}.")
        elif outcome_mode == "partial" and decisive_signals:
            claims.append(f"The selected evidence directly confirms {behavior_phrase} in {symbol_label}, but not the full requested behavior.")
        elif outcome_mode == "unproven" and context_phrase and context_phrase != "the selected structural context":
            claims.append(f"The selected context shows {symbol_label} reaching {context_phrase}.")
        elif outcome_mode == "ambiguous":
            ambiguity_refs = list(analysis_result.get("ambiguity_refs", []))
            if ambiguity_refs:
                claims.append(f"The current answer must stay ambiguous because `{ambiguity_refs[0]}` is unresolved.")
        return list(dict.fromkeys(item for item in claims if item))[:2]

    def _build_work_packet_disallowed_claims(
        self,
        analysis: Dict[str, object],
        analysis_result: Dict[str, object],
        primary_target_id: str,
        primary_path: Dict[str, object],
    ) -> List[str]:
        symbol_label = self._node_brief_label(primary_target_id) if primary_target_id else "the selected symbol"
        requested_signals = {str(item) for item in analysis_result.get("requested_semantic_signals", [])}
        forbidden = analysis_result.get("forbidden_overreach", {}) if isinstance(analysis_result.get("forbidden_overreach"), dict) else {}
        unsupported = {str(item) for item in forbidden.get("unsupported_claim_kinds", [])}
        statements = [str(item) for item in forbidden.get("statements", []) if item]
        disallowed: List[str] = []
        if "project_wide_claim" in unsupported:
            if {"auth_guard", "database_io"} <= requested_signals:
                disallowed.append("Do not claim that all project database reads are auth-guarded.")
            elif {"state_mutation", "filesystem_io"} <= requested_signals:
                disallowed.append("Do not claim that every project state write reaches disk.")
            elif "network_io" in requested_signals:
                disallowed.append(f"Do not claim project-wide network reachability from {symbol_label}.")
            else:
                disallowed.append(f"Do not generalize beyond {symbol_label}.")
        if "end_to_end_claim_without_direct_io" in unsupported:
            disallowed.append(f"Do not claim that {symbol_label} reaches direct network I/O.")
        if "complete_flow_claim" in unsupported:
            disallowed.append("Do not claim that this is the complete end-to-end path.")
        if "uniqueness_claim_without_disambiguation" in unsupported:
            disallowed.append("Do not claim a unique implementation or single resolved path while ambiguity remains.")
        if "root_cause_claim" in unsupported:
            disallowed.append("Do not infer root cause or hidden intent from the selected evidence.")
        requested_phrase = self._analysis_result_behavior_phrase(
            requested_signals,
            analysis,
            primary_path,
        )
        if analysis_result.get("outcome_mode") in {"partial", "unproven"} and requested_phrase != "the requested behavior":
            disallowed.append(f"Do not claim direct {requested_phrase} unless a selected direct evidence span proves it.")
        disallowed.extend(statements)
        return list(dict.fromkeys(item for item in disallowed if item))[:6]

    def _build_work_packet_read_order(
        self,
        worker_mode: str,
        analysis_result: Dict[str, object],
        analysis_plan: Dict[str, object],
        selected_slices: List[Dict[str, object]],
        followup_ask: Dict[str, object],
    ) -> List[Dict[str, object]]:
        slice_by_ref = {self._slice_ref(spec): spec for spec in selected_slices}
        minimal_open_sequence = list(analysis_plan.get("minimal_open_sequence", []))
        decisive_slice_refs = [
            str(item)
            for item in analysis_result.get("minimal_basis", {}).get("decisive_slice_refs", [])
            if str(item)
        ]
        if worker_mode == "answer_only":
            ordered_refs = decisive_slice_refs[:3]
        else:
            ordered_refs = [
                str(item.get("slice_ref", ""))
                for item in minimal_open_sequence
                if str(item.get("slice_ref", ""))
            ]
            if decisive_slice_refs:
                ordered_refs = list(dict.fromkeys(decisive_slice_refs + ordered_refs))
        if bool(followup_ask.get("enabled")):
            for target in followup_ask.get("derived_slice_targets", []):
                ref = self._slice_ref_from_file_lines(str(target.get("file", "")), target.get("lines", []))
                if ref:
                    ordered_refs.append(ref)
        out: List[Dict[str, object]] = []
        seen: Set[str] = set()
        by_sequence = {
            str(item.get("slice_ref", "")): item
            for item in minimal_open_sequence
            if str(item.get("slice_ref", ""))
        }
        for ref in ordered_refs:
            ref = str(ref)
            if not ref or ref in seen:
                continue
            seen.add(ref)
            sequence_item = by_sequence.get(ref, {})
            spec = slice_by_ref.get(ref)
            if spec is not None and not sequence_item:
                symbols = [str(symbol) for symbol in spec.get("symbols", []) if str(symbol)]
                symbol = symbols[0] if symbols else ""
                sequence_item = {
                    "slice_ref": ref,
                    "symbol": symbol,
                    "why": "Decisive selected evidence for the current bounded answer.",
                    "stop_if": "Stop when the current bounded outcome is already justified.",
                }
            if not sequence_item:
                continue
            out.append(
                {
                    "order": len(out) + 1,
                    "slice_ref": ref,
                    "symbol": str(sequence_item.get("symbol", "")),
                    "why": str(sequence_item.get("why", "")),
                    "stop_if": str(sequence_item.get("stop_if", "")),
                }
            )
            if len(out) >= (3 if worker_mode == "answer_only" else 4):
                break
        return out

    def _build_work_packet_targets(
        self,
        task_kind: str,
        worker_mode: str,
        analysis_result: Dict[str, object],
        primary_target_id: str,
        ambiguity_item: Dict[str, object],
        selected_slices: List[Dict[str, object]],
        read_order_refs: Set[str],
        supporting_symbols: List[str],
        analysis: Dict[str, object],
        primary_path: Dict[str, object],
        primary_chain: Dict[str, object],
    ) -> Tuple[
        List[Dict[str, object]],
        List[Dict[str, object]],
        List[Dict[str, object]],
        List[Dict[str, object]],
        List[Dict[str, object]],
        List[str],
        List[str],
    ]:
        primary_targets: List[Dict[str, object]] = []
        if primary_target_id:
            primary_targets.append(
                self._work_packet_target_payload(
                    primary_target_id,
                    "primary",
                    "Primary executable target chosen by the bounded analysis result.",
                    slice_refs=analysis_result.get("minimal_basis", {}).get("decisive_slice_refs", []),
                    flow_refs=analysis_result.get("minimal_basis", {}).get("decisive_flow_refs", []),
                    path_refs=analysis_result.get("minimal_basis", {}).get("decisive_path_refs", []),
                )
            )
        if task_kind == "ambiguity_check" or worker_mode == "inspect_then_compare":
            supporting_targets = self._build_ambiguity_candidate_targets(
                primary_target_id,
                ambiguity_item,
                selected_slices,
                read_order_refs,
            )
            if len(supporting_targets) < 3:
                candidate_symbols = {str(item.get("symbol", "")) for item in supporting_targets}
                for node_id in supporting_symbols:
                    if node_id in candidate_symbols or node_id == primary_target_id:
                        continue
                    supporting_targets.append(
                        self._work_packet_target_payload(
                            node_id,
                            "support",
                            "Secondary executable or path-adjacent context retained after ambiguity candidates.",
                            slice_refs=self._slice_refs_for_work_target(node_id, selected_slices, read_order_refs),
                            flow_refs=analysis_result.get("supporting_flow_refs", []),
                            path_refs=analysis_result.get("supporting_path_refs", []),
                        )
                    )
                    if len(supporting_targets) >= 3:
                        break
        else:
            supporting_targets = [
                self._work_packet_target_payload(
                    node_id,
                    "support",
                    "Supporting executable or path-adjacent evidence retained by the query-scoped planner.",
                    slice_refs=[
                        ref
                        for ref in analysis_result.get("supporting_slice_refs", [])
                        if str(ref) in read_order_refs
                    ],
                    flow_refs=analysis_result.get("supporting_flow_refs", []),
                    path_refs=analysis_result.get("supporting_path_refs", []),
                )
                for node_id in supporting_symbols
            ][:3]

        allowed_claims = self._build_work_packet_allowed_claims(
            analysis,
            analysis_result,
            primary_target_id,
            primary_path,
            primary_chain,
        )
        disallowed_claims = self._build_work_packet_disallowed_claims(
            analysis,
            analysis_result,
            primary_target_id,
            primary_path,
        )

        answer_targets = list(primary_targets)
        for item in supporting_targets:
            if item["symbol"] not in {target["symbol"] for target in answer_targets}:
                answer_targets.append(item)
            if len(answer_targets) >= 3:
                break

        patch_targets: List[Dict[str, object]] = []
        if (
            primary_target_id in self.nodes
            and self.nodes[primary_target_id].kind in SEMANTIC_EXECUTABLE_KINDS
            and str(analysis_result.get("outcome_mode", "")) in {"confirmed", "partial"}
        ):
            patch_targets.append(
                self._work_packet_target_payload(
                    primary_target_id,
                    "patch_candidate",
                    "Smallest direct executable locus if behavior around the proven evidence needs to change.",
                    slice_refs=analysis_result.get("minimal_basis", {}).get("decisive_slice_refs", []),
                    flow_refs=analysis_result.get("minimal_basis", {}).get("decisive_flow_refs", []),
                    path_refs=analysis_result.get("minimal_basis", {}).get("decisive_path_refs", []),
                )
            )

        refactor_targets: List[Dict[str, object]] = []
        if task_kind == "refactor_probe":
            for node_id in [primary_target_id] + supporting_symbols:
                if node_id and node_id in self.nodes:
                    refactor_targets.append(
                        self._work_packet_target_payload(
                            node_id,
                            "refactor_candidate",
                            "Refactor inquiry target retained from the bounded primary path.",
                            slice_refs=analysis_result.get("supporting_slice_refs", []),
                            flow_refs=analysis_result.get("supporting_flow_refs", []),
                            path_refs=analysis_result.get("supporting_path_refs", []),
                        )
                    )
                if len(refactor_targets) >= 3:
                    break

        return (
            primary_targets,
            supporting_targets,
            answer_targets,
            patch_targets,
            refactor_targets,
            allowed_claims,
            disallowed_claims,
        )

    def _build_work_packet_completion(
        self,
        outcome_mode: str,
        worker_mode: str,
        followup_ask: Dict[str, object],
        analysis: Dict[str, object],
        analysis_result: Dict[str, object],
        primary_path: Dict[str, object],
    ) -> Tuple[Dict[str, object], List[Dict[str, object]], List[str]]:
        if outcome_mode == "confirmed":
            when_answer_is_complete = "Stop once the allowed confirmed claim is directly supported by decisive_evidence."
            when_to_stop_without_upgrade = "Stop immediately after the decisive evidence is read; no stronger bounded result is needed."
        elif outcome_mode == "ambiguous":
            when_answer_is_complete = "Stop once the bounded ambiguous claim and candidate set are stated without collapsing the ambiguity."
            when_to_stop_without_upgrade = "Stop if the current candidate slices still leave multiple plausible answers."
        else:
            requested_phrase = self._analysis_result_behavior_phrase(
                analysis_result.get("requested_semantic_signals", []),
                analysis,
                primary_path,
            )
            when_answer_is_complete = "Stop once the bounded claim and its limitation are both stated from decisive_evidence."
            when_to_stop_without_upgrade = (
                f"Stop after the listed read_order if direct {requested_phrase} evidence is still absent."
                if requested_phrase != "the requested behavior"
                else "Stop after the listed read_order if the requested direct evidence is still absent."
            )

        followup_enabled = bool(followup_ask.get("enabled"))
        completion_criteria = {
            "when_answer_is_complete": when_answer_is_complete,
            "when_to_stop_without_upgrade": when_to_stop_without_upgrade,
            "when_to_request_followup": (
                "Only request the exported bounded follow-up after the current read_order is exhausted."
                if followup_enabled
                else "Do not request follow-up; the current escalation and follow-up gates are closed."
            ),
            "when_not_to_patch": "Do not patch unless the user explicitly asks for a change and the patch can stay inside `patch_targets`.",
        }
        stop_conditions = [
            {"kind": "answer_complete", "condition": completion_criteria["when_answer_is_complete"]},
            {"kind": "bounded_stop", "condition": completion_criteria["when_to_stop_without_upgrade"]},
            {"kind": "followup_gate", "condition": completion_criteria["when_to_request_followup"]},
        ]

        execution_notes = [
            "Read only the exported `read_order` first; do not widen to sibling modules or callers.",
            "State only `allowed_claims`; treat `disallowed_claims` as hard boundaries.",
        ]
        if worker_mode == "answer_only":
            execution_notes.append("Do not keep exploring after the decisive evidence is read; answer and stop.")
        else:
            execution_notes.append("Inspect the listed bounded context, then answer at the current outcome mode without inventing upgrades.")
        if followup_enabled:
            execution_notes.append("A single bounded follow-up exists, but it is only relevant after the current read_order is exhausted.")
        else:
            execution_notes.append("Do not create a new follow-up request; the current bounded result is the stopping point.")

        return completion_criteria, stop_conditions, execution_notes

    def _build_work_packet(
        self,
        query: str,
        analysis: Dict[str, object],
        analysis_plan: Dict[str, object],
        analysis_result: Dict[str, object],
        selected_slices: List[Dict[str, object]],
        selected_flow_chains: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
        flow_gaps: List[Dict[str, object]],
        ambiguity_watchlist: List[Dict[str, object]],
        escalation_controller: Dict[str, object],
        followup_ask: Dict[str, object],
    ) -> Dict[str, object]:
        primary_target_id = str(analysis_result.get("minimal_basis", {}).get("primary_symbol", "") or "")
        primary_chain = self._select_primary_flow_chain(primary_target_id, selected_flow_chains)
        primary_path = self._select_primary_evidence_path(primary_target_id, selected_paths)
        ambiguity_item = self._primary_ambiguity_item(primary_target_id, ambiguity_watchlist)
        task_kind = self._infer_worker_task_kind(analysis, analysis_result)
        worker_mode = self._choose_worker_mode(task_kind, analysis_result, ambiguity_watchlist, followup_ask)
        read_order = self._build_work_packet_read_order(
            worker_mode,
            analysis_result,
            analysis_plan,
            selected_slices,
            followup_ask,
        )
        supporting_symbols = self._work_packet_supporting_symbols(primary_target_id, primary_chain, primary_path)
        read_order_refs = {str(item.get("slice_ref", "")) for item in read_order if str(item.get("slice_ref", ""))}
        (
            primary_targets,
            supporting_targets,
            answer_targets,
            patch_targets,
            refactor_targets,
            allowed_claims,
            disallowed_claims,
        ) = self._build_work_packet_targets(
            task_kind,
            worker_mode,
            analysis_result,
            primary_target_id,
            ambiguity_item,
            selected_slices,
            read_order_refs,
            supporting_symbols,
            analysis,
            primary_path,
            primary_chain,
        )

        outcome_mode = str(analysis_result.get("outcome_mode", "unproven") or "unproven")
        completion_criteria, stop_conditions, execution_notes = self._build_work_packet_completion(
            outcome_mode,
            worker_mode,
            followup_ask,
            analysis,
            analysis_result,
            primary_path,
        )
        recommended_option_ref = str(followup_ask.get("source_option_ref", "") or analysis_result.get("recommended_escalation_option_ref", "") or "").strip()

        return {
            "task": query,
            "task_kind": task_kind,
            "worker_mode": worker_mode,
            "preferred_action": worker_mode,
            "current_outcome_mode": outcome_mode,
            "read_order": read_order,
            "primary_targets": primary_targets,
            "supporting_targets": supporting_targets,
            "decisive_evidence": {
                "evidence_refs": list(analysis_result.get("evidence_refs", []))[:8],
                "slice_refs": list(analysis_result.get("minimal_basis", {}).get("decisive_slice_refs", []))[:3],
                "flow_refs": list(analysis_result.get("minimal_basis", {}).get("decisive_flow_refs", []))[:2],
                "path_refs": list(analysis_result.get("minimal_basis", {}).get("decisive_path_refs", []))[:2],
                "semantic_refs": list(analysis_result.get("supporting_semantic_refs", []))[:3],
                "flow_gap_refs": list(analysis_result.get("flow_gap_refs", []))[:2],
                "ambiguity_refs": list(analysis_result.get("ambiguity_refs", []))[:2],
            },
            "allowed_claims": allowed_claims,
            "disallowed_claims": disallowed_claims,
            "stop_conditions": stop_conditions,
            "completion_criteria": completion_criteria,
            "patch_targets": patch_targets,
            "refactor_targets": refactor_targets,
            "answer_targets": answer_targets,
            "escalation_gate": {
                "escalation_allowed": bool(escalation_controller.get("escalation_allowed")),
                "followup_enabled": bool(followup_ask.get("enabled")),
                "recommended_option_ref": recommended_option_ref or None,
                "maximum_reachable_outcome": str(
                    escalation_controller.get(
                        "maximum_reachable_outcome",
                        analysis_result.get("maximum_reachable_outcome", outcome_mode),
                    )
                ),
                "stop_reason": str(
                    followup_ask.get("stop_reason")
                    or escalation_controller.get("stop_reason")
                    or analysis_result.get("stop_reason", "")
                ),
            },
            "execution_notes": execution_notes,
        }

    def _build_worker_prompt(self, ask_context_pack: Dict[str, object]) -> str:
        query = str(ask_context_pack.get("query", ""))
        work_packet = ask_context_pack.get("work_packet", {}) if isinstance(ask_context_pack.get("work_packet"), dict) else {}
        followup_ask = ask_context_pack.get("followup_ask", {}) if isinstance(ask_context_pack.get("followup_ask"), dict) else {}
        worker_mode = str(work_packet.get("worker_mode", "inspect_then_answer") or "inspect_then_answer")
        followup_note = (
            "Only consult `followup_ask` after the listed read_order is exhausted."
            if bool(followup_ask.get("enabled"))
            else "Do not open follow-up context; `followup_ask.enabled = false`."
        )
        return (
            f"Use `work_packet` as the operational contract for `{query}`. Read `read_order` strictly in order, keep the task inside "
            f"`primary_targets` and `supporting_targets`, and formulate only `allowed_claims`. Treat `disallowed_claims` as hard limits. "
            f"The current worker mode is `{worker_mode}`: if it is `answer_only`, stop after the decisive evidence and do not explore further; "
            "if it is `inspect_then_answer`, inspect only the listed targets before answering; if it is `inspect_then_compare`, compare only the "
            "listed candidates and stop without forcing uniqueness; if it is `inspect_then_refactor_plan`, limit yourself to focused refactor "
            f"targets without patching. {followup_note} Stop cleanly when `completion_criteria` says the bounded answer is complete."
        )

    def _build_worker_result_template(
        self,
        query: str,
        work_packet: Dict[str, object],
        analysis_result: Dict[str, object],
        followup_ask: Dict[str, object],
    ) -> Dict[str, object]:
        current_outcome = str(analysis_result.get("outcome_mode", "unproven") or "unproven")
        required_read_order_refs = [
            str(item.get("slice_ref", ""))
            for item in work_packet.get("read_order", [])
            if str(item.get("slice_ref", ""))
        ]
        required_primary_symbols = [
            str(item.get("symbol", ""))
            for item in work_packet.get("primary_targets", [])
            if str(item.get("symbol", ""))
        ]
        valid_stop_conditions = [
            str(item.get("kind", ""))
            for item in work_packet.get("stop_conditions", [])
            if str(item.get("kind", ""))
        ]
        return {
            "status": "ready_for_execution",
            "task": query,
            "worker_mode": str(work_packet.get("worker_mode", "")),
            "expected_outcome_ceiling": current_outcome,
            "minimum_honest_outcome": current_outcome,
            "default_completion_state": "ready_for_execution",
            "required_read_order_refs": required_read_order_refs,
            "required_primary_symbols": required_primary_symbols,
            "allowed_claims": list(work_packet.get("allowed_claims", [])),
            "disallowed_claims": list(work_packet.get("disallowed_claims", [])),
            "followup_allowed": bool(followup_ask.get("enabled")),
            "valid_stop_conditions": valid_stop_conditions,
            "supported_completion_states": list(WORKER_COMPLETION_STATES),
            "result_slots": {
                "inspected_slice_refs": [],
                "inspected_symbols": [],
                "used_claims": [],
                "final_outcome_mode": "",
                "final_claim": "",
                "supporting_refs": [],
                "stop_condition_hit": "",
                "completion_state": "ready_for_execution",
                "followup_used": False,
                "unresolved_points": [],
                "notes": [],
            },
        }

    def _build_worker_trace_template(
        self,
        worker_result_template: Dict[str, object],
    ) -> Dict[str, object]:
        return {
            "status": "ready_for_execution",
            "trace_slots": {
                "opened_slice_refs": [],
                "opened_symbols": [],
                "claim_attempts": [],
                "accepted_claims": [],
                "rejected_claims": [],
                "stop_condition_triggered": "",
                "completion_state": str(worker_result_template.get("default_completion_state", "ready_for_execution")),
                "followup_touched": False,
                "notes": [],
                "unresolved_points": [],
                "execution_time_hint": "",
            },
            "trace_expectations": {
                "required_read_order_refs": list(worker_result_template.get("required_read_order_refs", [])),
                "required_primary_symbols": list(worker_result_template.get("required_primary_symbols", [])),
                "maximum_allowed_outcome": str(worker_result_template.get("expected_outcome_ceiling", "")),
                "minimum_honest_outcome": str(worker_result_template.get("minimum_honest_outcome", "")),
                "allowed_claims": list(worker_result_template.get("allowed_claims", [])),
                "disallowed_claims": list(worker_result_template.get("disallowed_claims", [])),
                "followup_allowed": bool(worker_result_template.get("followup_allowed")),
            },
        }

    def _build_worker_validation_rules(
        self,
        work_packet: Dict[str, object],
        analysis_result: Dict[str, object],
        worker_result_template: Dict[str, object],
    ) -> List[Dict[str, object]]:
        forbidden = analysis_result.get("forbidden_overreach", {}) if isinstance(analysis_result.get("forbidden_overreach"), dict) else {}
        unsupported = {str(item) for item in forbidden.get("unsupported_claim_kinds", [])}
        rules: List[Dict[str, object]] = [
            {
                "rule_id": "must_respect_allowed_claims",
                "description": "Use only claim strings listed in `allowed_claims` for `result_slots.used_claims` and `result_slots.final_claim`.",
                "severity": "error",
                "applies_when": "always",
                "pass_condition": "Every emitted claim is copied from `allowed_claims`.",
                "fail_condition": "A claim appears that is not listed in `allowed_claims`.",
            },
            {
                "rule_id": "must_not_use_disallowed_claims",
                "description": "Never emit a claim string listed in `disallowed_claims`.",
                "severity": "error",
                "applies_when": "when `disallowed_claims` is non-empty",
                "pass_condition": "No emitted claim matches `disallowed_claims`.",
                "fail_condition": "A disallowed claim appears in `result_slots.used_claims` or `result_slots.final_claim`.",
            },
            {
                "rule_id": "must_not_exceed_outcome_ceiling",
                "description": "Do not raise `result_slots.final_outcome_mode` above `expected_outcome_ceiling`.",
                "severity": "error",
                "applies_when": "always",
                "pass_condition": "`final_outcome_mode` is less than or equal to `expected_outcome_ceiling`.",
                "fail_condition": "`final_outcome_mode` exceeds `expected_outcome_ceiling`.",
            },
            {
                "rule_id": "must_not_drop_below_minimum_honest_outcome",
                "description": "Do not return an outcome below the current bounded result.",
                "severity": "error",
                "applies_when": "always",
                "pass_condition": "`final_outcome_mode` is greater than or equal to `minimum_honest_outcome`.",
                "fail_condition": "`final_outcome_mode` drops below `minimum_honest_outcome`.",
            },
            {
                "rule_id": "must_set_final_outcome_for_terminal_result",
                "description": "Terminal worker results must set `result_slots.final_outcome_mode`.",
                "severity": "error",
                "applies_when": "when `completion_state` is terminal",
                "pass_condition": "`final_outcome_mode` is non-empty for any terminal worker result.",
                "fail_condition": "A terminal worker result omits `final_outcome_mode`.",
            },
            {
                "rule_id": "must_read_primary_slice_first",
                "description": "The first inspected slice must match the first `required_read_order_refs` entry.",
                "severity": "error",
                "applies_when": "when `required_read_order_refs` is non-empty and execution progressed beyond `ready_for_execution`",
                "pass_condition": "`inspected_slice_refs[0]` equals the first required read-order ref.",
                "fail_condition": "The worker skipped the first primary slice or inspected a different slice first.",
            },
            {
                "rule_id": "must_read_required_sequence_for_terminal_result",
                "description": "Terminal worker results must include the full `required_read_order_refs` sequence in order.",
                "severity": "error",
                "applies_when": "when `completion_state` is terminal and `required_read_order_refs` is non-empty",
                "pass_condition": "`required_read_order_refs` appears as an ordered subsequence inside `inspected_slice_refs`.",
                "fail_condition": "A required read-order ref is missing or appears out of order in a terminal worker result.",
            },
            {
                "rule_id": "must_cover_required_primary_symbols_for_terminal_result",
                "description": "Terminal worker results must record every `required_primary_symbols` entry in `result_slots.inspected_symbols`.",
                "severity": "error",
                "applies_when": "when `completion_state` is terminal and `required_primary_symbols` is non-empty",
                "pass_condition": "All required primary symbols appear in `inspected_symbols`.",
                "fail_condition": "A required primary symbol is missing from a terminal worker result.",
            },
            {
                "rule_id": "must_stop_when_completion_criteria_met",
                "description": "Completed or stopped results must cite one of the exported stop conditions.",
                "severity": "error",
                "applies_when": "when `completion_state` is a completed or stopped state",
                "pass_condition": "`stop_condition_hit` matches `valid_stop_conditions`.",
                "fail_condition": "The worker finished without referencing a valid stop condition.",
            },
        ]
        if not bool(worker_result_template.get("followup_allowed")):
            rules.append(
                {
                    "rule_id": "must_not_open_followup_when_disabled",
                    "description": "Follow-up use is forbidden when `followup_allowed = false`.",
                    "severity": "error",
                    "applies_when": "when `followup_allowed = false`",
                    "pass_condition": "`result_slots.followup_used = false`.",
                    "fail_condition": "The worker used follow-up evidence even though the gate was closed.",
                }
            )
        if str(analysis_result.get("outcome_mode", "")) == "ambiguous" or "uniqueness_claim_without_disambiguation" in unsupported:
            rules.append(
                {
                    "rule_id": "must_not_claim_uniqueness_while_ambiguous",
                    "description": "Ambiguous work packets may not collapse the result into a unique implementation or path.",
                    "severity": "error",
                    "applies_when": "when `expected_outcome_ceiling = ambiguous` or ambiguity refs are present",
                    "pass_condition": "`final_outcome_mode = ambiguous` and emitted claims stay inside the ambiguous allow-list.",
                    "fail_condition": "The worker returns a unique or stronger-than-ambiguous result without new evidence.",
                }
            )
        if "end_to_end_claim_without_direct_io" in unsupported:
            rules.append(
                {
                    "rule_id": "must_not_claim_direct_io_without_direct_evidence",
                    "description": "Direct I/O claims remain forbidden when the current bounded result lacks direct evidence.",
                    "severity": "error",
                    "applies_when": "when direct I/O is requested but `analysis_result` still marks it unsupported",
                    "pass_condition": "Claims stay inside `allowed_claims` and do not upgrade the current bounded result.",
                    "fail_condition": "The worker claims direct I/O even though no selected direct evidence span proves it.",
                }
            )
        return rules

    def _build_worker_result_prompt(self, ask_context_pack: Dict[str, object]) -> str:
        query = str(ask_context_pack.get("query", ""))
        work_packet = ask_context_pack.get("work_packet", {}) if isinstance(ask_context_pack.get("work_packet"), dict) else {}
        analysis_result = ask_context_pack.get("analysis_result", {}) if isinstance(ask_context_pack.get("analysis_result"), dict) else {}
        worker_result_template = (
            ask_context_pack.get("worker_result_template", {})
            if isinstance(ask_context_pack.get("worker_result_template"), dict)
            else {}
        )
        ceiling = str(worker_result_template.get("expected_outcome_ceiling", analysis_result.get("outcome_mode", "")) or "")
        return (
            f"Fill `worker_result_template` for `{query}` only after respecting `work_packet` and `analysis_result`. "
            "Keep `result_slots.used_claims` and `result_slots.final_claim` inside `allowed_claims`, never use "
            "`disallowed_claims`, and do not raise `result_slots.final_outcome_mode` above "
            f"`expected_outcome_ceiling = {ceiling}`. Record the exported read-order refs, required primary symbols, supporting refs, "
            "and a non-empty `result_slots.final_outcome_mode` before returning any terminal result. "
            "Set `followup_used = true` only if the gate is open, choose a `completion_state` from "
            "`supported_completion_states`, and do not mark a terminal result until the full `required_read_order_refs` "
            "sequence has been inspected in order and every `required_primary_symbols` entry has been recorded. If the current result is `unproven` or `ambiguous`, stop there "
            "cleanly instead of inventing a stronger claim."
        )

    def _build_worker_report_prompt(self, ask_context_pack: Dict[str, object]) -> str:
        query = str(ask_context_pack.get("query", ""))
        worker_result_template = (
            ask_context_pack.get("worker_result_template", {})
            if isinstance(ask_context_pack.get("worker_result_template"), dict)
            else {}
        )
        worker_trace_template = (
            ask_context_pack.get("worker_trace_template", {})
            if isinstance(ask_context_pack.get("worker_trace_template"), dict)
            else {}
        )
        ceiling = str(worker_result_template.get("expected_outcome_ceiling", "")) or "unproven"
        return (
            f"For `{query}`, keep `worker_trace_template` and `worker_result_template` separate. Record actual slice opens, symbol "
            "opens, and claim attempts in `worker_trace_template.trace_slots`, then fill `worker_result_template.result_slots` only "
            "inside the exported contract. Treat any invalidated claim attempt as rejected, do not hide violations, and do not treat "
            "a worker result as final until the validator has produced the derived `worker_result_report`. The current maximum bounded "
            f"outcome is `{ceiling}`; never let the final accepted result exceed that ceiling, and never rewrite rejected claims into "
            "an apparently valid summary."
        )

    def _build_result_prompt(self, ask_context_pack: Dict[str, object]) -> str:
        query = str(ask_context_pack.get("query", ""))
        analysis_result = ask_context_pack.get("analysis_result", {}) if isinstance(ask_context_pack.get("analysis_result"), dict) else {}
        outcome_mode = str(analysis_result.get("outcome_mode", "unproven") or "unproven")
        forbidden = analysis_result.get("forbidden_overreach", {}) if isinstance(analysis_result.get("forbidden_overreach"), dict) else {}
        unsupported = ", ".join(str(item) for item in forbidden.get("unsupported_claim_kinds", [])) or "none"
        controller = ask_context_pack.get("escalation_controller", {}) if isinstance(ask_context_pack.get("escalation_controller"), dict) else {}
        escalation_instruction = (
            "Only open `escalation_controller.recommended_option`"
            if bool(controller.get("escalation_allowed"))
            else "Do not open new escalation context"
        )
        return (
            f"Answer `{query}` by using `analysis_result` first. Treat `claim`, `minimal_basis`, and `evidence_refs` as the "
            f"maximum allowed answer surface for the current `{outcome_mode}` result. Do not exceed "
            f"`forbidden_overreach.unsupported_claim_kinds = [{unsupported}]`. {escalation_instruction}, "
            "`analysis_plan`, or broader deferred context if a wider answer is explicitly requested. If the result is "
            "`partial`, `unproven`, or `ambiguous`, stop at that bounded conclusion instead of inferring the missing behavior."
        )

    def _build_ask_prompt(self, ask_context_pack: Dict[str, object]) -> str:
        query = str(ask_context_pack.get("query", ""))
        return (
            f"Answer the question `{query}` by checking `work_packet` first for the strict worker contract, then `analysis_result`, "
            "then `escalation_controller`, then `followup_ask`, then `analysis_plan`, and only then using selected_flow_summaries, selected_flow_chains, "
            "selected_evidence_paths, selected_semantic_refs, and selected_slices in that order. Prefer direct semantic "
            "evidence over contained semantics, executable symbols over containers, and high-confidence paths over weaker "
            "hints. Treat any ambiguity_watchlist item as unresolved until a bounded escalation option is explicitly allowed."
        )

    def _build_analyst_prompt(self, ask_context_pack: Dict[str, object]) -> str:
        query = str(ask_context_pack.get("query", ""))
        analysis_plan = ask_context_pack.get("analysis_plan", {}) if isinstance(ask_context_pack.get("analysis_plan"), dict) else {}
        recommended_outcome_mode = str(analysis_plan.get("recommended_outcome_mode", "partial") or "partial")
        return (
            f"Work the analysis_plan for `{query}` in order. After each step, decide whether `confirmed`, `partial`, "
            f"`unproven`, or `ambiguous` is already justified; the recommended default is `{recommended_outcome_mode}`. "
            "Use selected_flow_summaries, selected_flow_chains, selected_evidence_paths, selected_semantic_refs, and "
            "selected_slices before opening any branch_requests or deferred_requests. Do not claim a flow, guard, side "
            "effect, or external interaction unless the current step has direct evidence for it. Compile `analysis_result` "
            "once the matching candidate_outcome is satisfied, then consult `escalation_controller` before opening any "
            "new evidence and stop early whenever escalation is not explicitly allowed."
        )

    def _rank_ask_candidates(
        self,
        analysis: Dict[str, object],
        inbound: Dict[str, List],
    ) -> Tuple[List[Dict[str, object]], Dict[str, float], Dict[str, Dict[str, object]], List[Dict[str, object]]]:
        mentioned_symbols = set(str(item) for item in analysis.get("mentioned_symbols", []))
        mentioned_files = set(str(item) for item in analysis.get("mentioned_files", []))

        def matches_query_focus_node(node_id: str) -> bool:
            return node_id in mentioned_symbols or (
                node_id in self.nodes and self.nodes[node_id].file in mentioned_files
            )

        def matches_query_focus_path(path: Dict[str, object]) -> bool:
            return any(matches_query_focus_node(node_id) for node_id in self._ordered_path_nodes(path))

        base_candidates = [
            self._build_query_target_candidate(node_id, analysis, inbound)
            for node_id in sorted(self.nodes)
        ]
        base_candidates = [
            item
            for item in base_candidates
            if (
                float(item["base_selection_score"]) > 0.0
                or item["direct_semantic_match"]
                or item["contained_semantic_match"]
                or item["ambiguity_relevance"]
            )
        ]
        base_candidates.sort(
            key=lambda item: (
                -float(item["base_selection_score"]),
                0 if self.nodes[item["node_id"]].kind in SEMANTIC_EXECUTABLE_KINDS else 1,
                str(item["node_id"]),
            )
        )
        query_paths = self._build_query_evidence_paths(base_candidates, inbound, analysis, limit=10)
        path_bonus_by_node: Dict[str, float] = defaultdict(float)
        best_path_by_node: Dict[str, Dict[str, object]] = {}
        for path in query_paths:
            risk_node = str(path.get("risk_node", ""))
            score = float(path.get("query_match_score", 0.0))
            if score > path_bonus_by_node.get(risk_node, 0.0):
                path_bonus_by_node[risk_node] = score
                best_path_by_node[risk_node] = path

        ranked_targets: List[Dict[str, object]] = []
        for item in base_candidates:
            node_id = str(item["node_id"])
            final_score = float(item["base_selection_score"]) + float(path_bonus_by_node.get(node_id, 0.0))
            payload = dict(item)
            payload["evidence_path_match"] = node_id in best_path_by_node
            payload["evidence_path_score"] = round(float(path_bonus_by_node.get(node_id, 0.0)), 2)
            payload["best_evidence_path_id"] = str(best_path_by_node[node_id]["path_id"]) if node_id in best_path_by_node else ""
            payload["selection_score"] = round(final_score, 2)
            payload["why_selected"] = list(payload["match_reasons"][:4]) or ["Selected because it best matches the query-scoped evidence heuristics."]
            ranked_targets.append(payload)

        ranked_targets.sort(
            key=lambda item: (
                -float(item["selection_score"]),
                0 if self.nodes[item["node_id"]].kind in SEMANTIC_EXECUTABLE_KINDS else 1,
                -float(self.nodes[item["node_id"]].risk_score),
                str(item["node_id"]),
            )
        )
        for rank, item in enumerate(ranked_targets, start=1):
            item["rank"] = rank

        return ranked_targets, path_bonus_by_node, best_path_by_node, query_paths

    def _select_ask_slices(
        self,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        query_paths: List[Dict[str, object]],
        best_path_by_node: Dict[str, Dict[str, object]],
        query_ambiguity_watchlist: List[Dict[str, object]],
        inbound: Dict[str, List],
        line_budget: int,
    ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], Dict[str, List], List[Dict[str, object]]]:
        mentioned_symbols = set(str(item) for item in analysis.get("mentioned_symbols", []))
        mentioned_files = set(str(item) for item in analysis.get("mentioned_files", []))

        def matches_query_focus_node(node_id: str) -> bool:
            return node_id in mentioned_symbols or (
                node_id in self.nodes and self.nodes[node_id].file in mentioned_files
            )

        def matches_query_focus_path(path: Dict[str, object]) -> bool:
            return any(matches_query_focus_node(node_id) for node_id in self._ordered_path_nodes(path))

        selected_paths = [
            path
            for path in query_paths
            if float(path.get("query_match_score", 0.0)) > 0.0
        ][:5]
        if mentioned_symbols or mentioned_files:
            focused_paths = [path for path in selected_paths if matches_query_focus_path(path)]
            if focused_paths:
                selected_paths = focused_paths
        if not selected_paths and ranked_targets[:1]:
            fallback = best_path_by_node.get(str(ranked_targets[0]["node_id"]))
            if fallback is not None:
                selected_paths = [fallback]

        path_refs_by_anchor = self._path_refs_by_anchor(selected_paths)
        selected_semantic_refs: List[Dict[str, object]] = []
        for item in ranked_targets[:8]:
            node_id = str(item["node_id"])
            direct_refs = self._query_relevant_semantic_refs(
                list(item.get("direct_semantic_refs", [])),
                set(str(signal) for signal in item.get("direct_semantic_match", [])),
                limit=3,
            )
            if direct_refs:
                for ref in direct_refs:
                    selected_semantic_refs.append({"node_id": node_id, "match_type": "direct", **ref})
                continue
            contained_refs = self._query_relevant_semantic_refs(
                list(item.get("contained_semantic_refs", [])),
                set(str(signal) for signal in item.get("contained_semantic_match", [])),
                limit=2,
            )
            for ref in contained_refs:
                selected_semantic_refs.append({"node_id": node_id, "match_type": "contained", **ref})
        selected_semantic_refs = self._dedupe_object_list(selected_semantic_refs)[:12]

        slice_specs: List[Dict[str, object]] = []
        used_lines = 0
        primary_budget = max(1, int(line_budget * 0.72))
        selected_target_ids: Set[str] = set()
        primary_targets = list(ranked_targets[:10])
        if mentioned_symbols or mentioned_files:
            focused_targets = [
                item
                for item in primary_targets
                if matches_query_focus_node(str(item["node_id"]))
            ]
            if focused_targets:
                primary_targets = focused_targets
        if len(set(str(item) for item in analysis.get("matched_semantic_signals", []))) > 1:
            focused_targets = [
                item
                for item in primary_targets
                if (
                    float(item.get("direct_semantic_coverage", 0.0)) >= 0.99
                    or float(item.get("contained_semantic_coverage", 0.0)) >= 0.99
                    or bool(item.get("evidence_path_match"))
                    or bool(item.get("ambiguity_relevance"))
                    or bool(item.get("has_strong_query_anchor"))
                )
            ]
            if focused_targets:
                primary_targets = focused_targets
        for item in primary_targets[:6]:
            node_id = str(item["node_id"])
            focus_refs = list(item.get("direct_semantic_refs", []))
            if not focus_refs and item.get("contained_semantic_match") and not item.get("direct_semantic_match"):
                focus_refs = list(item.get("contained_semantic_refs", []))[:2]
            spec = self._build_query_slice_spec(
                node_id=node_id,
                why=list(item["why_selected"]) + ["Query-scoped primary evidence slice."],
                selection_score=float(item["selection_score"]),
                selection_confidence_label=str(item.get("best_support_label", "") or "medium"),
                supporting_edges=self._support_edges_for_node(node_id, inbound, limit=2),
                ambiguity_flags=[],
                role="query_target",
                evidence_path_refs=[str(item.get("best_evidence_path_id", ""))] if item.get("best_evidence_path_id") else [],
                semantic_refs=focus_refs,
            )
            line_count = int(spec["end_line"]) - int(spec["start_line"]) + 1
            if used_lines + line_count > primary_budget and selected_target_ids:
                continue
            slice_specs.append(spec)
            used_lines += line_count
            selected_target_ids.add(node_id)

        for path in selected_paths:
            for item in path.get("recommended_slices", [])[1:]:
                node_id = str(item.get("anchor_symbol", ""))
                if node_id not in self.nodes or node_id in selected_target_ids:
                    continue
                path_match_refs = self._query_relevant_semantic_refs(
                    self._semantic_refs_for_node(node_id, limit=3),
                    set(str(signal) for signal in path.get("query_match_signals", [])),
                    limit=3,
                )
                spec = self._build_query_slice_spec(
                    node_id=node_id,
                    why=[
                        f"Support slice for query path `{path['path_id']}` ({path['path_kind']}).",
                        *list(path.get("query_match_reasons", []))[:2],
                    ],
                    selection_score=float(path.get("query_match_score", 0.0)),
                    selection_confidence_label=str(path.get("path_confidence_label", "") or "medium"),
                    supporting_edges=self._support_edges_for_node(node_id, inbound, limit=1),
                    ambiguity_flags=[],
                    role="support",
                    evidence_path_refs=[str(path["path_id"])],
                    semantic_refs=path_match_refs,
                )
                line_count = int(spec["end_line"]) - int(spec["start_line"]) + 1
                if used_lines + line_count > line_budget:
                    continue
                slice_specs.append(spec)
                used_lines += line_count
                selected_target_ids.add(node_id)

        if bool(analysis.get("ambiguity_sensitive")):
            for item in query_ambiguity_watchlist[:2]:
                source_node = str(item["source_node"])
                if source_node not in self.nodes or source_node in selected_target_ids:
                    continue
                spec = self._build_query_slice_spec(
                    node_id=source_node,
                    why=[
                        "Ambiguity-focused slice for the query.",
                        str(item.get("resolution_reason", "")),
                    ],
                    selection_score=float(item.get("query_match_score", 0.0)),
                    selection_confidence_label=str(item.get("confidence_label", "") or "ambiguous"),
                    supporting_edges=[],
                    ambiguity_flags=[item],
                    role="ambiguity_context",
                    evidence_path_refs=[],
                    semantic_refs=[],
                )
                line_count = int(spec["end_line"]) - int(spec["start_line"]) + 1
                if used_lines + line_count > line_budget:
                    continue
                slice_specs.append(spec)
                used_lines += line_count
                selected_target_ids.add(source_node)

        return slice_specs, selected_paths, path_refs_by_anchor, selected_semantic_refs

    def _build_ask_flow_data(
        self,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        merged_slices: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
    ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
        selected_flow_summaries = self._build_selected_flow_summaries(
            ranked_targets,
            merged_slices,
            selected_paths,
            analysis,
            limit=6,
        )
        selected_flow_chains = self._build_selected_flow_chains(
            analysis,
            ranked_targets,
            selected_paths,
            merged_slices,
            selected_flow_summaries,
            limit=4,
        )
        flow_gaps = self._build_flow_gaps(
            analysis,
            ranked_targets,
            selected_flow_summaries,
            selected_flow_chains,
            limit=4,
        )
        return selected_flow_summaries, selected_flow_chains, flow_gaps

    def _build_ask_context_pack(
        self,
        query: str,
        line_budget: int = 110,
    ) -> Dict[str, object]:
        inbound = self._inbound_adj()
        analysis = self._build_query_analysis(query)
        ranked_targets, path_bonus_by_node, best_path_by_node, query_paths = (
            self._rank_ask_candidates(analysis, inbound)
        )

        query_ambiguity_watchlist = self._build_query_ambiguity_watchlist(analysis, ranked_targets, limit=4)
        slice_specs, selected_paths, path_refs_by_anchor, selected_semantic_refs = self._select_ask_slices(
            analysis,
            ranked_targets,
            query_paths,
            best_path_by_node,
            query_ambiguity_watchlist,
            inbound,
            line_budget,
        )

        merged_slices = self._merge_slice_specs(slice_specs)
        merged_slices = [self._annotate_slice_path_refs(spec, path_refs_by_anchor) for spec in merged_slices]
        selected_symbols = {symbol for spec in merged_slices for symbol in spec.get("symbols", [])}
        selected_flow_summaries, selected_flow_chains, flow_gaps = self._build_ask_flow_data(
            analysis,
            ranked_targets,
            merged_slices,
            selected_paths,
        )

        deferred: List[Dict[str, object]] = []
        if bool(analysis.get("ambiguity_sensitive")):
            for item in query_ambiguity_watchlist[:2]:
                deferred.append(self._build_deferred_request_for_ambiguity(item))
        for item in ranked_targets[:4]:
            node_id = str(item["node_id"])
            if node_id not in selected_symbols:
                continue
            best_path = best_path_by_node.get(node_id)
            if best_path is not None:
                request = self._build_deferred_request_for_path(best_path, selected_symbols)
                if request is not None:
                    deferred.append(request)
        semantic_watchlist = self._build_semantic_watchlist(limit=8)
        selected_watchlist = [item for item in semantic_watchlist if item["symbol"] in selected_symbols]
        for item in selected_watchlist[:2]:
            request = self._build_deferred_request_for_semantic_item(item, merged_slices)
            if request is not None:
                deferred.append(request)
        deferred = self._dedupe_object_list(deferred)[:6]
        analysis_plan = self._build_analysis_plan(
            query,
            analysis,
            ranked_targets,
            merged_slices,
            selected_paths,
            selected_flow_summaries,
            selected_flow_chains,
            flow_gaps,
            query_ambiguity_watchlist,
            deferred,
        )
        analysis_result = self._build_analysis_result(
            query,
            analysis,
            ranked_targets,
            merged_slices,
            selected_semantic_refs,
            selected_flow_summaries,
            selected_flow_chains,
            selected_paths,
            flow_gaps,
            query_ambiguity_watchlist,
            deferred,
            analysis_plan,
        )
        escalation_controller = self._build_escalation_controller(
            analysis,
            ranked_targets,
            merged_slices,
            selected_paths,
            selected_flow_chains,
            flow_gaps,
            query_ambiguity_watchlist,
            deferred,
            analysis_result,
        )
        analysis_result["escalation_status"] = (
            "not_needed"
            if analysis_result.get("outcome_mode") == "confirmed"
            else ("allowed" if escalation_controller.get("escalation_allowed") else "stopped_no_bounded_gain")
        )
        analysis_result["stop_reason"] = escalation_controller.get("stop_reason")
        analysis_result["maximum_reachable_outcome"] = escalation_controller.get("maximum_reachable_outcome")
        analysis_result["recommended_escalation_option_ref"] = (
            escalation_controller["recommended_option"]["option_id"]
            if isinstance(escalation_controller.get("recommended_option"), dict)
            else None
        )
        followup_ask = self._build_followup_ask(
            query,
            analysis,
            analysis_result,
            escalation_controller,
        )
        analysis_result["followup_status"] = "enabled" if followup_ask.get("enabled") else "disabled"
        analysis_result["followup_ref"] = (
            str(followup_ask.get("source_option_ref", "")) if followup_ask.get("enabled") else None
        )
        work_packet = self._build_work_packet(
            query,
            analysis,
            analysis_plan,
            analysis_result,
            merged_slices,
            selected_flow_chains,
            selected_paths,
            flow_gaps,
            query_ambiguity_watchlist,
            escalation_controller,
            followup_ask,
        )
        worker_result_template = self._build_worker_result_template(
            query,
            work_packet,
            analysis_result,
            followup_ask,
        )
        worker_trace_template = self._build_worker_trace_template(worker_result_template)
        worker_validation_rules = self._build_worker_validation_rules(
            work_packet,
            analysis_result,
            worker_result_template,
        )

        ask_context_pack = {
            "query": query,
            "query_analysis": analysis,
            "ranked_targets": [
                {
                    "node_id": item["node_id"],
                    "rank": item["rank"],
                    "file": item["file"],
                    "lines": item["lines"],
                    "kind": item["kind"],
                    "why_selected": list(item["why_selected"]),
                    "match_reasons": list(item["match_reasons"]),
                    "direct_semantic_match": list(item["direct_semantic_match"]),
                    "contained_semantic_match": list(item["contained_semantic_match"]),
                    "evidence_path_match": bool(item["evidence_path_match"]),
                    "ambiguity_relevance": bool(item["ambiguity_relevance"]),
                    "selection_score": float(item["selection_score"]),
                }
                for item in ranked_targets[:10]
            ],
            "selected_slices": merged_slices,
            "selected_evidence_paths": selected_paths,
            "selected_semantic_refs": selected_semantic_refs,
            "selected_flow_summaries": selected_flow_summaries,
            "selected_flow_chains": selected_flow_chains,
            "flow_gaps": flow_gaps,
            "ambiguity_watchlist": query_ambiguity_watchlist,
            "deferred_requests": deferred,
            "analysis_plan": analysis_plan,
            "analysis_result": analysis_result,
            "escalation_controller": escalation_controller,
            "followup_ask": followup_ask,
            "work_packet": work_packet,
            "worker_result_template": worker_result_template,
            "worker_trace_template": worker_trace_template,
            "worker_validation_rules": worker_validation_rules,
            "selection_strategy": (
                "Rank executable nodes first by lexical query match, direct semantic matches, path evidence, "
                "confidence quality, and ambiguity relevance. Build compact behavioral flow summaries from direct "
                "semantic evidence, and only fall back to contained semantics or container nodes when direct executable "
                "evidence is weaker or absent."
            ),
            "budget": {
                "line_budget": max(20, line_budget),
                "selected_line_count": sum(int(spec["end_line"]) - int(spec["start_line"]) + 1 for spec in merged_slices),
                "selected_target_count": len(selected_symbols),
                "selected_path_count": len(selected_paths),
                "selected_flow_summary_count": len(selected_flow_summaries),
                "selected_flow_chain_count": len(selected_flow_chains),
                "deferred_request_count": len(deferred),
            },
        }
        ask_context_pack["ask_prompt"] = self._build_ask_prompt(ask_context_pack)
        ask_context_pack["analyst_prompt"] = self._build_analyst_prompt(ask_context_pack)
        ask_context_pack["result_prompt"] = self._build_result_prompt(ask_context_pack)
        ask_context_pack["escalation_prompt"] = self._build_escalation_prompt(ask_context_pack)
        ask_context_pack["followup_prompt"] = self._build_followup_prompt(ask_context_pack)
        ask_context_pack["worker_prompt"] = self._build_worker_prompt(ask_context_pack)
        ask_context_pack["worker_result_prompt"] = self._build_worker_result_prompt(ask_context_pack)
        ask_context_pack["worker_report_prompt"] = self._build_worker_report_prompt(ask_context_pack)
        return ask_context_pack

    def _language_for_file(self, rel_path: str) -> str:
        suffix = Path(rel_path).suffix.lower()
        return {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "jsx",
            ".ts": "typescript",
            ".tsx": "tsx",
            ".json": "json",
            ".toml": "toml",
            ".yml": "yaml",
            ".yaml": "yaml",
            ".xml": "xml",
            ".gradle": "groovy",
            ".md": "markdown",
            ".txt": "text",
            ".cfg": "ini",
            ".go": "go",
            ".java": "java",
            ".rs": "rust",
        }.get(suffix, "text")

    def _inbound_adj(self) -> Dict[str, Set[str]]:
        inbound: Dict[str, Set[str]] = defaultdict(set)
        for src, dsts in self.adj.items():
            for dst in dsts:
                inbound[dst].add(src)
        return inbound

    def _edge_outcome(self, source: str, target: str) -> ResolutionOutcome:
        if (source, target) in self.edge_resolution:
            return self.edge_resolution[(source, target)]
        return self._resolution(
            target=target,
            kind="heuristic",
            reason="Resolved internal edge without explicit provenance.",
        )

    def _dedupe_object_list(self, items: List[Dict[str, object]]) -> List[Dict[str, object]]:
        seen: Set[str] = set()
        out: List[Dict[str, object]] = []
        for item in items:
            key = json.dumps(item, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def _build_confidence_summary(self) -> Dict[str, object]:
        by_label: Dict[str, int] = defaultdict(int)
        by_kind: Dict[str, int] = defaultdict(int)
        ambiguity_count = 0
        unresolved_detail_count = 0

        for outcome in self.edge_resolution.values():
            if outcome.confidence_label:
                by_label[outcome.confidence_label] += 1
            if outcome.resolution_kind:
                by_kind[outcome.resolution_kind] += 1

        for node in self.nodes.values():
            unresolved_detail_count += len(node.unresolved_call_details)
            for detail in node.unresolved_call_details.values():
                if detail.get("resolution_kind") == "ambiguous_candidates":
                    ambiguity_count += 1

        return {
            "edge_count_by_confidence_label": {key: by_label[key] for key in sorted(by_label)},
            "edge_count_by_resolution_kind": {key: by_kind[key] for key in sorted(by_kind)},
            "ambiguity_count": ambiguity_count,
            "unresolved_call_detail_count": unresolved_detail_count,
        }

    def _semantic_bundle_bonus(self, node: SymbolNode) -> float:
        if not node.semantic_signals:
            return 0.0
        bonus = node.semantic_weight * 1.7
        if any(signal in SEMANTIC_BOUNDARY_SIGNALS for signal in node.semantic_signals):
            bonus += 4.0
        if any(signal in SEMANTIC_CRITICAL_SIGNALS for signal in node.semantic_signals):
            bonus += 2.0
        if node.unresolved_call_details and any(signal in SEMANTIC_CRITICAL_SIGNALS for signal in node.semantic_signals):
            bonus += 1.5
        if node.kind == "module":
            bonus -= 1.0
        return round(max(0.0, bonus), 2)

    def _semantic_refs_for_file(self, rel_path: str, limit: int = 4) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for node in self.nodes.values():
            if node.file != rel_path:
                continue
            if self._semantic_node_is_shadowed(node):
                continue
            refs.extend(list(node.semantic_evidence_spans))
        return self._dedupe_semantic_refs(refs, limit=limit)

    def _semantic_node_is_shadowed(self, node: SymbolNode) -> bool:
        if not node.semantic_signals:
            return False
        kind_rank = {
            "method": 0,
            "function": 0,
            "async_function": 0,
            "class": 1,
            "interface": 1,
            "enum": 1,
            "module": 2,
        }
        node_signals = set(node.semantic_signals)
        node_span = max(1, int(node.lines[1]) - int(node.lines[0]) + 1)
        for other in self.nodes.values():
            if other.node_id == node.node_id or other.file != node.file or not other.semantic_signals:
                continue
            other_signals = set(other.semantic_signals)
            other_span = max(1, int(other.lines[1]) - int(other.lines[0]) + 1)
            if other_signals >= node_signals and (
                kind_rank.get(other.kind, 9) < kind_rank.get(node.kind, 9)
                or (
                    kind_rank.get(other.kind, 9) == kind_rank.get(node.kind, 9)
                    and other_span < node_span
                )
            ):
                return True
        return False

    def _build_semantic_candidates(self, limit: int = 10) -> List[Dict[str, object]]:
        candidates: List[Dict[str, object]] = []
        for node_id, node in self.nodes.items():
            if not node.semantic_signals:
                continue
            if self._semantic_node_is_shadowed(node):
                continue
            reasons: List[str] = []
            if any(signal in SEMANTIC_BOUNDARY_SIGNALS for signal in node.semantic_signals):
                reasons.append("Boundary-facing symbol with explicit semantic evidence.")
            if any(signal in SEMANTIC_SIDE_EFFECT_SIGNALS for signal in node.semantic_signals):
                reasons.append("Contains state mutation or side-effectful behavior.")
            if any(signal in SEMANTIC_GUARD_SIGNALS for signal in node.semantic_signals):
                reasons.append("Contains validation, authorization, or error-handling logic.")
            if node.risk_score >= 45.0:
                reasons.append("Also appears structurally important enough to matter for triage.")
            if node.unresolved_call_details:
                reasons.append("Semantic interpretation may still depend on unresolved structural ambiguity.")
            priority = (
                (node.semantic_weight * 3.0)
                + min(node.risk_score / 12.0, 8.0)
                + (3.0 if any(signal in SEMANTIC_BOUNDARY_SIGNALS for signal in node.semantic_signals) else 0.0)
                + (2.0 if any(signal in SEMANTIC_EXTERNAL_IO_SIGNALS for signal in node.semantic_signals) else 0.0)
                - (1.0 if node.kind == "module" else 0.0)
            )
            candidates.append(
                {
                    "node_id": node_id,
                    "file": node.file,
                    "lines": node.lines,
                    "kind": node.kind,
                    "language": node.language,
                    "risk_score": node.risk_score,
                    "semantic_weight": node.semantic_weight,
                    "semantic_signals": list(node.semantic_signals),
                    "semantic_summary": dict(node.semantic_summary),
                    "semantic_evidence_spans": self._semantic_refs_for_node(node_id, limit=4),
                    "contained_semantic_signals": list(node.contained_semantic_signals),
                    "contained_semantic_summary": dict(node.contained_semantic_summary),
                    "contained_semantic_refs": self._contained_semantic_refs_for_node(node_id, limit=4),
                    "why_selected": reasons or ["Semantic evidence is present on this symbol."],
                    "ambiguity_count": len(node.unresolved_call_details),
                    "selection_score": round(priority, 2),
                }
            )
        candidates.sort(
            key=lambda item: (
                -float(item["selection_score"]),
                -float(item["semantic_weight"]),
                -float(item["risk_score"]),
                str(item["node_id"]),
            )
        )
        return candidates[:limit]

    def _build_semantic_watchlist(self, limit: int = 8) -> List[Dict[str, object]]:
        watchlist: List[Dict[str, object]] = []
        for node_id, node in self.nodes.items():
            if not node.semantic_signals:
                continue
            if self._semantic_node_is_shadowed(node):
                continue
            reasons: List[str] = []
            signals = set(node.semantic_signals)
            if node.unresolved_call_details and signals & SEMANTIC_CRITICAL_SIGNALS:
                reasons.append("Semantically important node still has unresolved structural ambiguity.")
            if "state_mutation" in signals and signals & SEMANTIC_EXTERNAL_IO_SIGNALS:
                reasons.append("Combines state mutation with external side effects.")
            if "auth_guard" in signals and (signals & SEMANTIC_EXTERNAL_IO_SIGNALS or "input_boundary" in signals):
                reasons.append("Authorization logic sits on a boundary or side-effect path.")
            if "error_handling" in signals and signals & SEMANTIC_EXTERNAL_IO_SIGNALS:
                reasons.append("Side-effectful code path relies on explicit error handling.")
            if "process_io" in signals:
                reasons.append("Process execution is operationally sensitive.")
            if not reasons:
                continue
            refs = self._semantic_refs_for_node(node_id, limit=3)
            target_ref = refs[0] if refs else {"file": node.file, "lines": node.lines, "signal": ""}
            watchlist.append(
                {
                    "symbol": node_id,
                    "file": node.file,
                    "lines": node.lines,
                    "semantic_signals": list(node.semantic_signals),
                    "semantic_summary": dict(node.semantic_summary),
                    "semantic_evidence_spans": refs,
                    "contained_semantic_signals": list(node.contained_semantic_signals),
                    "contained_semantic_summary": dict(node.contained_semantic_summary),
                    "ambiguity_count": len(node.unresolved_call_details),
                    "why": reasons,
                    "recommended_next_evidence_target": {
                        "file": target_ref["file"],
                        "lines": target_ref["lines"],
                        "signal": target_ref.get("signal", ""),
                        "why": target_ref.get("reason", ""),
                    },
                }
            )
        watchlist.sort(
            key=lambda item: (
                -float(self.nodes[item["symbol"]].semantic_weight),
                -float(self.nodes[item["symbol"]].risk_score),
                str(item["symbol"]),
            )
        )
        return watchlist[:limit]

    def _build_semantic_overview(self, limit: int = 8) -> Dict[str, object]:
        direct_by_signal: Dict[str, int] = defaultdict(int)
        contained_by_signal: Dict[str, int] = defaultdict(int)
        by_file: Dict[str, Dict[str, object]] = {}
        for node in self.nodes.values():
            shadowed = self._semantic_node_is_shadowed(node)
            if not shadowed:
                for signal in node.semantic_signals:
                    direct_by_signal[signal] += 1
            if (not node.semantic_signals or shadowed) and not node.semantic_evidence_spans:
                continue
            current = by_file.setdefault(
                node.file,
                {
                    "file": node.file,
                    "contained_refs": [],
                    "direct_semantic_weight": 0.0,
                    "contained_signals": set(),
                    "direct_signals": set(),
                    "symbol_count": 0,
                },
            )
            if node.semantic_signals and not shadowed:
                current["direct_semantic_weight"] += node.semantic_weight
                current["direct_signals"].update(node.semantic_signals)
                current["symbol_count"] += 1
            if not shadowed:
                current["contained_refs"].extend(list(node.semantic_evidence_spans))
        for item in by_file.values():
            contained_refs = self._dedupe_semantic_refs(list(item["contained_refs"]), limit=24)
            item["contained_refs"] = contained_refs
            item["contained_signals"] = set(str(ref.get("signal", "")) for ref in contained_refs if ref.get("signal"))
            item["contained_semantic_weight"] = round(
                sum(SEMANTIC_SIGNAL_WEIGHTS.get(signal, 0.0) for signal in item["contained_signals"]),
                2,
            )
            for signal in item["contained_signals"]:
                contained_by_signal[signal] += 1
        boundary_files = sorted(
            (
                {
                    "file": item["file"],
                    "contained_semantic_weight": round(float(item["contained_semantic_weight"]), 2),
                    "direct_semantic_weight": round(float(item["direct_semantic_weight"]), 2),
                    "contained_semantic_signals": self._sort_semantic_signals(item["contained_signals"]),
                    "direct_semantic_signals": self._sort_semantic_signals(item["direct_signals"]),
                    "contained_semantic_refs": self._dedupe_semantic_refs(list(item["contained_refs"]), limit=4),
                    "symbol_count": int(item["symbol_count"]),
                }
                for item in by_file.values()
                if item["contained_semantic_weight"] > 0.0 or item["direct_semantic_weight"] > 0.0
            ),
            key=lambda item: (-float(item["contained_semantic_weight"]), -float(item["direct_semantic_weight"]), -int(item["symbol_count"]), str(item["file"])),
        )
        return {
            "aggregation_scope": "contained_descendant_semantics_for_file_view",
            "direct_node_count_by_signal": {key: direct_by_signal[key] for key in sorted(direct_by_signal)},
            "contained_file_count_by_signal": {key: contained_by_signal[key] for key in sorted(contained_by_signal)},
            "files_by_contained_semantic_weight": boundary_files[:limit],
        }

    def _build_semantic_entrypoints(self, limit: int = 8) -> List[Dict[str, object]]:
        candidates: List[Dict[str, object]] = []
        for node_id, node in self.nodes.items():
            if not node.semantic_signals:
                continue
            if self._semantic_node_is_shadowed(node):
                continue
            if not (set(node.semantic_signals) & (SEMANTIC_BOUNDARY_SIGNALS | SEMANTIC_EXTERNAL_IO_SIGNALS | {"auth_guard", "validation_guard"})):
                continue
            candidates.append(
                {
                    "symbol": node_id,
                    "file": node.file,
                    "lines": node.lines,
                    "language": node.language,
                    "semantic_signals": list(node.semantic_signals),
                    "semantic_weight": node.semantic_weight,
                    "risk_score": node.risk_score,
                    "semantic_evidence_spans": self._semantic_refs_for_node(node_id, limit=3),
                    "contained_semantic_signals": list(node.contained_semantic_signals),
                    "contained_semantic_summary": dict(node.contained_semantic_summary),
                }
            )
        candidates.sort(
            key=lambda item: (
                -float(item["semantic_weight"]),
                -float(item["risk_score"]),
                str(item["symbol"]),
            )
        )
        return candidates[:limit]

    def _slice_covers_lines(
        self,
        slices: List[Dict[str, object]],
        file_name: str,
        lines: List[int],
    ) -> bool:
        if not lines:
            return False
        start_line = int(lines[0])
        end_line = int(lines[1]) if len(lines) > 1 else start_line
        return any(
            str(spec.get("file", "")) == file_name
            and int(spec.get("start_line", 0)) <= start_line
            and int(spec.get("end_line", 0)) >= end_line
            for spec in slices
        )

    def _build_deferred_request_for_semantic_item(
        self,
        item: Dict[str, object],
        context_slices: List[Dict[str, object]],
    ) -> Optional[Dict[str, object]]:
        refs = list(item.get("semantic_evidence_spans", []))
        if not refs:
            return None
        target_ref = next(
            (
                ref
                for ref in refs
                if not self._slice_covers_lines(
                    context_slices,
                    str(ref["file"]),
                    list(ref.get("lines", [])),
                )
            ),
            None,
        )
        if target_ref is None:
            return None
        signal = str(target_ref.get("signal", ""))
        return {
            "type": "semantic_followup",
            "symbol": item["symbol"],
            "signals": list(item.get("semantic_signals", []))[:4],
            "confidence_gate": "only_if_this_semantic_signal_changes_the_decision",
            "request": (
                f"Open only `{target_ref['file']}:{target_ref['lines'][0]}-{target_ref['lines'][1]}` "
                f"to validate the `{signal}` evidence."
            ),
            "targets": [
                {
                    "file": target_ref["file"],
                    "lines": target_ref["lines"],
                    "signal": signal,
                    "why": target_ref.get("reason", ""),
                }
            ],
            "why": "; ".join(str(reason) for reason in item.get("why", []) if reason),
        }

    def _support_edge_payload(self, source: str, target: str, direction: str, focus_node: str) -> Dict[str, object]:
        outcome = self._edge_outcome(source, target)
        other = target if source == focus_node else source
        other_node = self.nodes[other]
        return {
            "source": source,
            "target": target,
            "direction": direction,
            "other_node": other,
            "other_file": other_node.file,
            "other_lines": other_node.lines,
            "kinds": sorted(self.edge_kinds.get((source, target), set())),
            "confidence_score": outcome.confidence_score,
            "confidence_label": outcome.confidence_label,
            "resolution_kind": outcome.resolution_kind,
            "resolution_reason": outcome.resolution_reason,
        }

    def _support_edges_for_node(
        self,
        node_id: str,
        inbound: Dict[str, Set[str]],
        limit: int = 6,
    ) -> List[Dict[str, object]]:
        entries: List[Dict[str, object]] = []
        for source in sorted(inbound.get(node_id, set())):
            entries.append(self._support_edge_payload(source, node_id, "incoming", node_id))
        for target in sorted(self.adj.get(node_id, set())):
            entries.append(self._support_edge_payload(node_id, target, "outgoing", node_id))
        entries.sort(
            key=lambda item: (
                -float(item["confidence_score"]),
                0 if item["direction"] == "incoming" else 1,
                str(item["resolution_kind"]),
                str(item["other_node"]),
            )
        )
        return entries[:limit]

    def _confidence_breakdown(self, edges: List[Dict[str, object]]) -> Dict[str, object]:
        counts: Dict[str, int] = defaultdict(int)
        for edge in edges:
            label = str(edge.get("confidence_label", ""))
            if label:
                counts[label] += 1
        best = edges[0] if edges else None
        return {
            "best_label": best.get("confidence_label", "") if best else "",
            "best_score": round(float(best.get("confidence_score", 0.0)), 2) if best else 0.0,
            "edge_count_by_label": {key: counts[key] for key in sorted(counts)},
        }

    def _recommended_next_evidence_target(
        self,
        node: SymbolNode,
        raw_call: str,
        detail: Dict[str, object],
    ) -> Dict[str, object]:
        targets = [{"file": node.file, "lines": node.lines, "why": f"Caller evidence for `{raw_call}`."}]
        for candidate_id in sorted(str(item) for item in detail.get("candidates", [])):
            if candidate_id not in self.nodes:
                continue
            candidate_node = self.nodes[candidate_id]
            targets.append(
                {
                    "file": candidate_node.file,
                    "lines": candidate_node.lines,
                    "why": f"Candidate implementation `{candidate_node.qualname}`.",
                }
            )
        return {
            "targets": self._dedupe_object_list(targets),
            "why": "Open the caller and candidate implementation slices only if the ambiguous edge matters.",
        }

    def _build_ambiguity_watchlist(self, limit: int = 12) -> List[Dict[str, object]]:
        watchlist: List[Dict[str, object]] = []
        for node_id in sorted(self.nodes, key=lambda item: (-self.nodes[item].risk_score, item)):
            node = self.nodes[node_id]
            for raw_call in sorted(node.unresolved_call_details):
                detail = node.unresolved_call_details[raw_call]
                watchlist.append(
                    {
                        "source_node": node_id,
                        "file": node.file,
                        "lines": node.lines,
                        "raw_call": raw_call,
                        "candidates": list(detail.get("candidates", [])),
                        "resolution_kind": detail.get("resolution_kind", ""),
                        "resolution_reason": detail.get("resolution_reason", ""),
                        "confidence_label": detail.get("confidence_label", ""),
                        "recommended_next_evidence_target": self._recommended_next_evidence_target(node, raw_call, detail),
                    }
                )
        return watchlist[:limit]

    def _sort_confidence_labels(self, labels: Iterable[str]) -> List[str]:
        unique = {label for label in labels if label}
        return sorted(
            unique,
            key=lambda label: (-CONFIDENCE_LABEL_ORDER.get(label, -1), label),
        )

    def _make_evidence_group(
        self,
        anchor_symbol: str,
        role: str,
        why: List[str],
        supporting_edges: Optional[List[Dict[str, object]]] = None,
        selection_confidence_labels: Optional[List[str]] = None,
        ambiguity_flags: Optional[List[Dict[str, object]]] = None,
        selection_score: Optional[float] = None,
        evidence_path_refs: Optional[List[str]] = None,
        semantic_refs: Optional[List[Dict[str, object]]] = None,
    ) -> Dict[str, object]:
        group: Dict[str, object] = {
            "anchor_symbol": anchor_symbol,
            "role": role,
            "why": list(why),
            "supporting_edges": list(supporting_edges or []),
            "selection_confidence_labels": self._sort_confidence_labels(selection_confidence_labels or []),
            "ambiguity_flags": list(ambiguity_flags or []),
        }
        if selection_score is not None:
            group["selection_score"] = round(selection_score, 2)
        if evidence_path_refs:
            group["evidence_path_refs"] = sorted(set(str(item) for item in evidence_path_refs if item))
        if semantic_refs:
            group["semantic_refs"] = self._dedupe_semantic_refs(list(semantic_refs), limit=4)
        return group

    def _normalize_evidence_groups(self, groups: List[Dict[str, object]]) -> List[Dict[str, object]]:
        role_order = {
            "query_target": 0,
            "primary_risk": 1,
            "support": 2,
            "ambiguity_context": 3,
            "file_context": 4,
        }
        merged: Dict[Tuple[str, str], Dict[str, object]] = {}
        for group in groups:
            anchor_symbol = str(group.get("anchor_symbol", ""))
            role = str(group.get("role", "support"))
            key = (anchor_symbol, role)
            current = merged.get(key)
            if current is None:
                current = {
                    "anchor_symbol": anchor_symbol,
                    "role": role,
                    "why": [],
                    "supporting_edges": [],
                    "selection_confidence_labels": [],
                    "ambiguity_flags": [],
                    "selection_score": float(group.get("selection_score", 0.0)),
                    "evidence_path_refs": [],
                    "semantic_refs": [],
                }
                merged[key] = current
            current["why"].extend(str(item) for item in group.get("why", []) if item)
            current["supporting_edges"].extend(list(group.get("supporting_edges", [])))
            current["selection_confidence_labels"].extend(str(item) for item in group.get("selection_confidence_labels", []) if item)
            current["ambiguity_flags"].extend(list(group.get("ambiguity_flags", [])))
            current["selection_score"] = max(float(current.get("selection_score", 0.0)), float(group.get("selection_score", 0.0)))
            current["evidence_path_refs"].extend(str(item) for item in group.get("evidence_path_refs", []) if item)
            current["semantic_refs"].extend(list(group.get("semantic_refs", [])))

        normalized_groups: List[Dict[str, object]] = []
        for anchor_symbol, role in sorted(
            merged,
            key=lambda item: (
                role_order.get(item[1], 9),
                item[0],
            ),
        ):
            current = merged[(anchor_symbol, role)]
            payload: Dict[str, object] = {
                "anchor_symbol": anchor_symbol,
                "role": role,
                "why": sorted(set(str(item) for item in current["why"] if item)),
                "supporting_edges": self._dedupe_object_list(list(current["supporting_edges"])),
                "selection_confidence_labels": self._sort_confidence_labels(current["selection_confidence_labels"]),
                "ambiguity_flags": self._dedupe_object_list(list(current["ambiguity_flags"])),
            }
            if float(current.get("selection_score", 0.0)) > 0.0:
                payload["selection_score"] = round(float(current["selection_score"]), 2)
            if current.get("evidence_path_refs"):
                payload["evidence_path_refs"] = sorted(set(str(item) for item in current["evidence_path_refs"] if item))
            if current.get("semantic_refs"):
                payload["semantic_refs"] = self._dedupe_semantic_refs(list(current["semantic_refs"]), limit=4)
            normalized_groups.append(payload)
        return normalized_groups

    def _path_refs_by_anchor(self, evidence_paths: List[Dict[str, object]]) -> Dict[str, List[str]]:
        refs: Dict[str, Set[str]] = defaultdict(set)
        for path in evidence_paths:
            path_id = str(path.get("path_id", ""))
            if not path_id:
                continue
            for item in path.get("recommended_slices", []):
                anchor_symbol = str(item.get("anchor_symbol", ""))
                if anchor_symbol:
                    refs[anchor_symbol].add(path_id)
        return {
            anchor_symbol: sorted(path_ids)
            for anchor_symbol, path_ids in refs.items()
        }

    def _annotate_slice_path_refs(
        self,
        spec: Dict[str, object],
        path_refs_by_anchor: Dict[str, List[str]],
    ) -> Dict[str, object]:
        group_refs: Set[str] = set(str(item) for item in spec.get("evidence_path_refs", []) if item)
        for group in spec.get("evidence_groups", []):
            anchor_symbol = str(group.get("anchor_symbol", ""))
            if not anchor_symbol:
                continue
            refs = sorted(set(str(item) for item in group.get("evidence_path_refs", []) if item) | set(path_refs_by_anchor.get(anchor_symbol, [])))
            if refs:
                group["evidence_path_refs"] = refs
                group_refs.update(refs)
        if group_refs:
            spec["evidence_path_refs"] = sorted(group_refs)
        return spec

    def _build_slice_spec(
        self,
        node_id: str,
        why: List[str],
        selection_score: float,
        selection_confidence_label: str,
        supporting_edges: Optional[List[Dict[str, object]]] = None,
        ambiguity_flags: Optional[List[Dict[str, object]]] = None,
        role: str = "support",
        anchor_symbol: str = "",
        evidence_path_refs: Optional[List[str]] = None,
        semantic_refs: Optional[List[Dict[str, object]]] = None,
    ) -> Dict[str, object]:
        node = self.nodes[node_id]
        start_line = max(1, node.lines[0] - 3)
        end_line = node.lines[1] + 3
        labels = self._sort_confidence_labels([selection_confidence_label])
        anchor = anchor_symbol or node_id
        semantic_items = self._dedupe_semantic_refs(list(semantic_refs or self._semantic_refs_for_node(anchor)), limit=4)
        return {
            "file": node.file,
            "start_line": start_line,
            "end_line": end_line,
            "symbols": [node_id],
            "why": list(why),
            "selection_score": round(selection_score, 2),
            "selection_confidence_label": selection_confidence_label,
            "selection_confidence_labels": labels,
            "supporting_edges": list(supporting_edges or []),
            "ambiguity_flags": list(ambiguity_flags or []),
            "evidence_path_refs": sorted(set(str(item) for item in evidence_path_refs or [] if item)),
            "semantic_refs": semantic_items,
            "evidence_groups": [
                self._make_evidence_group(
                    anchor_symbol=anchor,
                    role=role,
                    why=why,
                    supporting_edges=supporting_edges,
                    selection_confidence_labels=labels,
                    ambiguity_flags=ambiguity_flags,
                    selection_score=selection_score,
                    evidence_path_refs=evidence_path_refs,
                    semantic_refs=semantic_items,
                )
            ],
        }

    def _build_support_chain(
        self,
        node_id: str,
        inbound: Dict[str, Set[str]],
        limit: int = 3,
    ) -> Dict[str, object]:
        edges = self._support_edges_for_node(node_id, inbound, limit=limit * 2)
        incoming = [edge for edge in edges if edge["direction"] == "incoming"][:limit]
        outgoing = [edge for edge in edges if edge["direction"] == "outgoing"][:limit]
        return {
            "risk_node": node_id,
            "incoming_support": incoming,
            "outgoing_support": outgoing,
        }

    def _path_hop_payload(self, source: str, target: str) -> Dict[str, object]:
        outcome = self._edge_outcome(source, target)
        return {
            "source": source,
            "target": target,
            "resolution_kind": outcome.resolution_kind,
            "confidence_label": outcome.confidence_label,
            "confidence_score": round(float(outcome.confidence_score), 2),
            "resolution_reason": outcome.resolution_reason,
        }

    def _is_trivial_path_kind(self, resolution_kind: str) -> bool:
        return resolution_kind in {"same_class_method", "same_module_symbol", "direct_symbol"}

    def _path_kind_for_hops(self, risk_node: str, hops: List[Dict[str, object]]) -> str:
        resolution_kinds = {str(hop.get("resolution_kind", "")) for hop in hops}
        if resolution_kinds & {"instance_dispatch", "super_dispatch", "java_di_primary", "java_di_qualifier", "java_di_unique_impl"}:
            return "dispatch_chain"
        if "inheritance_exact" in resolution_kinds:
            return "inheritance_chain"
        if resolution_kinds & {"import_exact", "alias_resolved", "barrel_reexport"}:
            return "import_to_symbol_chain"
        if hops and str(hops[0].get("target", "")) == risk_node:
            return "inbound_support_chain"
        return "outbound_support_chain"

    def _path_recommended_slices(
        self,
        risk_node: str,
        hops: List[Dict[str, object]],
    ) -> List[Dict[str, object]]:
        anchors = [risk_node]
        for hop in hops:
            for node_id in (str(hop["source"]), str(hop["target"])):
                if node_id not in self.nodes or node_id in anchors:
                    continue
                anchors.append(node_id)
        slices: List[Dict[str, object]] = []
        for index, node_id in enumerate(anchors):
            node = self.nodes[node_id]
            slices.append(
                {
                    "anchor_symbol": node_id,
                    "role": "primary_risk" if index == 0 else "support",
                    "file": node.file,
                    "lines": node.lines,
                }
            )
        return slices

    def _select_path_extension(
        self,
        risk_node: str,
        first_edge: Dict[str, object],
        inbound: Dict[str, Set[str]],
        ambiguity_count: int,
    ) -> Tuple[Optional[Dict[str, object]], str]:
        if ambiguity_count > 0:
            return None, "ambiguity_blocked_extension"
        if float(first_edge.get("confidence_score", 0.0)) < 0.78:
            return None, "no_high_confidence_extension"

        pivot = str(first_edge["other_node"])
        preferred_direction = "incoming" if str(first_edge["direction"]) == "incoming" else "outgoing"
        candidates = [
            edge
            for edge in self._support_edges_for_node(pivot, inbound, limit=8)
            if str(edge["direction"]) == preferred_direction
        ]
        interesting_candidates = [
            edge for edge in candidates if not self._is_trivial_path_kind(str(edge.get("resolution_kind", "")))
        ]
        if interesting_candidates:
            candidates = interesting_candidates
        viable: List[Dict[str, object]] = []
        for edge in candidates:
            source = str(edge["source"])
            target = str(edge["target"])
            if source == risk_node or target == risk_node:
                continue
            if source == target:
                continue
            if float(edge.get("confidence_score", 0.0)) < 0.78:
                continue
            viable.append(edge)

        if not viable:
            if candidates:
                return None, "no_high_confidence_extension"
            return None, "no_supported_extension"

        viable.sort(
            key=lambda edge: (
                -float(edge.get("confidence_score", 0.0)),
                str(edge.get("resolution_kind", "")),
                str(edge.get("source", "")),
                str(edge.get("target", "")),
            )
        )
        return viable[0], "max_hops_reached"

    def _build_path_record(
        self,
        risk_node: str,
        hops: List[Dict[str, object]],
        stop_reason: str,
        path_id: str,
    ) -> Dict[str, object]:
        path_confidence = min(float(hop.get("confidence_score", 0.0)) for hop in hops) if hops else 0.0
        path_labels = self._sort_confidence_labels(str(hop.get("confidence_label", "")) for hop in hops)
        semantic_signals = self._sort_semantic_signals(
            signal
            for node_id in {risk_node} | {str(hop.get("source", "")) for hop in hops} | {str(hop.get("target", "")) for hop in hops}
            if node_id in self.nodes
            for signal in self.nodes[node_id].semantic_signals
        )
        payload = {
            "risk_node": risk_node,
            "path_id": path_id,
            "hops": hops,
            "path_confidence": round(path_confidence, 2),
            "path_confidence_label": path_labels[-1] if path_labels else "",
            "path_kind": self._path_kind_for_hops(risk_node, hops),
            "recommended_slices": self._path_recommended_slices(risk_node, hops),
            "stop_reason": stop_reason,
        }
        if semantic_signals:
            payload["semantic_signals"] = semantic_signals[:6]
        return payload

    def _build_evidence_paths_for_candidate(
        self,
        candidate: Dict[str, object],
        inbound: Dict[str, Set[str]],
        limit: int = 3,
    ) -> List[Dict[str, object]]:
        risk_node = str(candidate["node_id"])
        ambiguity_count = len(candidate["ambiguity_flags"])
        edges = self._support_edges_for_node(risk_node, inbound, limit=6)
        interesting_edges = [
            edge for edge in edges if not self._is_trivial_path_kind(str(edge.get("resolution_kind", "")))
        ]
        if interesting_edges:
            edges = interesting_edges
        path_entries: List[Dict[str, object]] = []
        seen_signatures: Set[str] = set()

        for edge in edges:
            hops = [self._path_hop_payload(str(edge["source"]), str(edge["target"]))]
            second_edge, stop_reason = self._select_path_extension(risk_node, edge, inbound, ambiguity_count)
            if second_edge is not None:
                hops.append(self._path_hop_payload(str(second_edge["source"]), str(second_edge["target"])))
            path_signature = " | ".join(f"{hop['source']}->{hop['target']}" for hop in hops)
            if path_signature in seen_signatures:
                continue
            seen_signatures.add(path_signature)
            trivial_penalty = sum(1.5 for hop in hops if self._is_trivial_path_kind(str(hop.get("resolution_kind", ""))))
            path_entries.append(
                {
                    "hops": hops,
                    "stop_reason": stop_reason,
                    "path_score": (
                        float(candidate["bundle_priority"])
                        + (min(float(hop["confidence_score"]) for hop in hops) * 10.0)
                        + len(hops)
                        - trivial_penalty
                    ),
                }
            )

        path_entries.sort(
            key=lambda item: (
                -float(item["path_score"]),
                -min(float(hop["confidence_score"]) for hop in item["hops"]),
                -len(item["hops"]),
                " | ".join(f"{hop['source']}->{hop['target']}" for hop in item["hops"]),
            )
        )

        selected_paths: List[Dict[str, object]] = []
        for index, item in enumerate(path_entries[:limit], start=1):
            selected_paths.append(
                self._build_path_record(
                    risk_node=risk_node,
                    hops=item["hops"],
                    stop_reason=str(item["stop_reason"]),
                    path_id=f"{risk_node}::path::{index}",
                )
            )
        return selected_paths

    def _build_evidence_paths(
        self,
        candidates: List[Dict[str, object]],
        inbound: Dict[str, Set[str]],
        limit_per_node: int = 3,
        global_limit: int = 18,
    ) -> List[Dict[str, object]]:
        paths: List[Dict[str, object]] = []
        for candidate in candidates[:8]:
            paths.extend(self._build_evidence_paths_for_candidate(candidate, inbound, limit=limit_per_node))
        paths.sort(key=self._path_sort_key)
        return paths[:global_limit]

    def _path_sort_key(self, path: Dict[str, object]) -> Tuple[int, float, int, str, str]:
        return (
            -sum(1 for hop in path.get("hops", []) if not self._is_trivial_path_kind(str(hop.get("resolution_kind", "")))),
            -float(path.get("path_confidence", 0.0)),
            -len(path.get("hops", [])),
            str(path.get("path_kind", "")),
            str(path.get("path_id", "")),
        )

    def _best_paths_by_risk_node(self, paths: List[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
        grouped: Dict[str, List[Dict[str, object]]] = defaultdict(list)
        for path in paths:
            grouped[str(path.get("risk_node", ""))].append(path)
        return {
            risk_node: sorted(items, key=self._path_sort_key)[0]
            for risk_node, items in grouped.items()
            if risk_node and items
        }

    def _build_deferred_request_for_symbol(
        self,
        node_id: str,
        why: str,
        confidence_gate: str = "only_if_initial_evidence_is_insufficient",
        targets: Optional[List[Dict[str, object]]] = None,
        request: str = "",
    ) -> Dict[str, object]:
        node = self.nodes[node_id]
        requested_targets = list(targets or [{"file": node.file, "lines": node.lines}])
        return {
            "type": "focused_symbol_followup",
            "symbol": node_id,
            "confidence_gate": confidence_gate,
            "request": request or f"Open only `{node.file}:{node.lines[0]}-{node.lines[1]}` if the first-pass evidence is insufficient.",
            "targets": requested_targets,
            "why": why,
        }

    def _build_deferred_request_for_ambiguity(self, item: Dict[str, object]) -> Dict[str, object]:
        return {
            "type": "ambiguity_followup",
            "symbol": item["source_node"],
            "raw_call": item["raw_call"],
            "confidence_gate": "only_if_this_ambiguity_blocks_the_analysis",
            "request": (
                f"Open the caller and candidate implementations for `{item['raw_call']}` because the resolution is ambiguous."
            ),
            "targets": list(item["recommended_next_evidence_target"]["targets"]),
            "why": item["resolution_reason"],
        }

    def _build_deferred_request_for_path(
        self,
        path: Dict[str, object],
        selected_symbols: Set[str],
    ) -> Optional[Dict[str, object]]:
        risk_node = str(path["risk_node"])
        path_confidence = float(path.get("path_confidence", 0.0))
        if path_confidence >= 0.85:
            return None

        missing_targets: List[Dict[str, object]] = []
        for item in path.get("recommended_slices", []):
            anchor_symbol = str(item.get("anchor_symbol", ""))
            if anchor_symbol in selected_symbols:
                continue
            missing_targets.append(
                {
                    "file": item["file"],
                    "lines": item["lines"],
                    "anchor_symbol": anchor_symbol,
                }
            )

        if not missing_targets:
            return None

        missing_targets.sort(
            key=lambda item: (
                (int(item["lines"][1]) - int(item["lines"][0]) + 1) if item.get("lines") else 9999,
                str(item.get("file", "")),
                str(item.get("anchor_symbol", "")),
            )
        )
        first_target = missing_targets[0]
        hop_kinds = ", ".join(str(hop.get("resolution_kind", "")) for hop in path.get("hops", []))
        return self._build_deferred_request_for_symbol(
            risk_node,
            why=(
                f"Validate the best available `{path['path_kind']}` for `{risk_node}` because the best path is only "
                f"`{path.get('path_confidence_label', '')}` confidence."
            ),
            confidence_gate="only_if_this_medium_confidence_path_matters",
            targets=missing_targets[:1],
            request=(
                f"Open only `{first_target['file']}:{first_target['lines'][0]}-{first_target['lines'][1]}` "
                f"to validate the next evidence hop(s): {hop_kinds}."
            ),
        )

    def _build_evidence_candidate(
        self,
        rank: int,
        entry: Dict[str, object],
        inbound: Dict[str, Set[str]],
    ) -> Dict[str, object]:
        node_id = str(entry["symbol"])
        node = self.nodes[node_id]
        support_edges = self._support_edges_for_node(node_id, inbound)
        support_confidence = self._confidence_breakdown(support_edges)
        ambiguity_flags = [
            {
                "raw_call": raw_call,
                **node.unresolved_call_details[raw_call],
            }
            for raw_call in sorted(node.unresolved_call_details)
        ]
        adjacency_score = min(6.0, float(len(self.adj.get(node_id, set())) + len(inbound.get(node_id, set()))))
        best_support = float(support_confidence["best_score"])
        ambiguity_penalty = float(len(ambiguity_flags) * 4)
        semantic_bonus = self._semantic_bundle_bonus(node)
        bundle_priority = float(entry["risk_score"]) + (best_support * 10.0) + adjacency_score + semantic_bonus - ambiguity_penalty

        why_selected = list(node.reasons) or ["Selected because it appears in the prioritized structural-risk set."]
        if support_edges:
            why_selected.append(
                f"Best supporting edge uses `{support_edges[0]['resolution_kind']}` with `{support_edges[0]['confidence_label']}` confidence."
            )
        if node.semantic_signals:
            why_selected.append(
                f"Semantic signals: {', '.join(node.semantic_signals[:4])}."
            )
        if ambiguity_flags:
            why_selected.append(f"{len(ambiguity_flags)} ambiguous call(s) remain unresolved and are tracked separately.")

        primary_slice = self._build_slice_spec(
            node_id=node_id,
            why=why_selected + ["Primary risk evidence slice."],
            selection_score=bundle_priority + 12.0,
            selection_confidence_label=str(support_confidence["best_label"] or "medium"),
            supporting_edges=support_edges[:3],
            ambiguity_flags=ambiguity_flags[:2],
            role="primary_risk",
        )

        suggested_slices = [primary_slice]
        suggested_files = [node.file]
        for edge in support_edges:
            if float(edge["confidence_score"]) < 0.78:
                continue
            other_node = str(edge["other_node"])
            if other_node == node_id or self.nodes[other_node].file == node.file:
                continue
            suggested_files.append(self.nodes[other_node].file)
            suggested_slices.append(
                self._build_slice_spec(
                    node_id=other_node,
                    why=[
                        f"Support slice for `{node_id}` via `{edge['resolution_kind']}` ({edge['confidence_label']}).",
                        str(edge["resolution_reason"]),
                    ],
                    selection_score=(bundle_priority * 0.4) + (float(edge["confidence_score"]) * 20.0),
                    selection_confidence_label=str(edge["confidence_label"]),
                    supporting_edges=[edge],
                    ambiguity_flags=[],
                    role="support",
                )
            )
            if len(suggested_slices) >= 3:
                break

        deferred_if_needed: List[Dict[str, object]] = []
        if ambiguity_flags:
            for item in self._build_ambiguity_watchlist(limit=50):
                if item["source_node"] == node_id:
                    deferred_if_needed.append(self._build_deferred_request_for_ambiguity(item))

        return {
            "rank": rank,
            "node_id": node_id,
            "file": node.file,
            "lines": node.lines,
            "risk_score": entry["risk_score"],
            "bundle_priority": round(bundle_priority, 2),
            "why_selected": why_selected,
            "supporting_edges": support_edges,
            "supporting_edge_confidence": support_confidence,
            "semantic_signals": list(node.semantic_signals),
            "semantic_summary": dict(node.semantic_summary),
            "semantic_evidence_spans": self._semantic_refs_for_node(node_id, limit=4),
            "behavioral_flow_summary": dict(node.behavioral_flow_summary),
            "behavioral_flow_steps": list(node.behavioral_flow_steps[:8]),
            "contained_semantic_signals": list(node.contained_semantic_signals),
            "contained_semantic_summary": dict(node.contained_semantic_summary),
            "contained_semantic_refs": self._contained_semantic_refs_for_node(node_id, limit=4),
            "suggested_files": sorted(set(suggested_files)),
            "suggested_slices": suggested_slices,
            "ambiguity_flags": ambiguity_flags,
            "deferred_if_needed": self._dedupe_object_list(deferred_if_needed),
            "support_chain": self._build_support_chain(node_id, inbound),
        }

    def _build_evidence_candidates(
        self,
        top_risks: List[Dict[str, object]],
        inbound: Dict[str, Set[str]],
    ) -> List[Dict[str, object]]:
        candidates = [
            self._build_evidence_candidate(rank, entry, inbound)
            for rank, entry in enumerate(top_risks, start=1)
        ]
        candidates.sort(
            key=lambda item: (
                -float(item["bundle_priority"]),
                -float(item["risk_score"]),
                str(item["node_id"]),
            )
        )
        return candidates

    def _build_project_architecture_evidence(
        self,
        recommended_reads: List[Dict[str, str]],
        limit: int = 8,
    ) -> List[Dict[str, object]]:
        interesting_files = {item["file"] for item in recommended_reads}
        candidates: List[Dict[str, object]] = []
        for (source, target), outcome in self.edge_resolution.items():
            source_node = self.nodes[source]
            target_node = self.nodes[target]
            if outcome.resolution_kind in {"same_class_method", "same_module_symbol", "direct_symbol"}:
                continue
            if source_node.file not in interesting_files and target_node.file not in interesting_files:
                continue
            candidates.append(
                {
                    "source": source,
                    "target": target,
                    "source_file": source_node.file,
                    "target_file": target_node.file,
                    "confidence_score": outcome.confidence_score,
                    "confidence_label": outcome.confidence_label,
                    "resolution_kind": outcome.resolution_kind,
                    "resolution_reason": outcome.resolution_reason,
                }
            )
        candidates.sort(
            key=lambda item: (
                -float(item["confidence_score"]),
                str(item["resolution_kind"]),
                str(item["source"]),
                str(item["target"]),
            )
        )
        return candidates[:limit]

    def _build_project_architecture_paths(
        self,
        recommended_reads: List[Dict[str, str]],
        inbound: Dict[str, Set[str]],
        limit: int = 6,
    ) -> List[Dict[str, object]]:
        interesting_files = {item["file"] for item in recommended_reads}
        edge_candidates = self._build_project_architecture_evidence(recommended_reads, limit=max(limit * 2, 8))
        paths: List[Dict[str, object]] = []

        for index, edge in enumerate(edge_candidates, start=1):
            source = str(edge["source"])
            target = str(edge["target"])
            hops = [self._path_hop_payload(source, target)]
            extension: Optional[Dict[str, object]] = None

            outgoing = [
                candidate
                for candidate in self._support_edges_for_node(target, inbound, limit=6)
                if str(candidate["direction"]) == "outgoing"
                and str(candidate["target"]) != source
                and float(candidate.get("confidence_score", 0.0)) >= 0.78
            ]
            incoming = [
                candidate
                for candidate in self._support_edges_for_node(source, inbound, limit=6)
                if str(candidate["direction"]) == "incoming"
                and str(candidate["source"]) != target
                and float(candidate.get("confidence_score", 0.0)) >= 0.78
            ]
            candidates = outgoing + incoming
            if candidates:
                candidates.sort(
                    key=lambda item: (
                        -float(item.get("confidence_score", 0.0)),
                        str(item.get("resolution_kind", "")),
                        str(item.get("source", "")),
                        str(item.get("target", "")),
                    )
                )
                extension = candidates[0]
            if extension is not None:
                hops.append(self._path_hop_payload(str(extension["source"]), str(extension["target"])))

            recommended_slices = []
            seen_files: Set[str] = set()
            for node_id in {str(hop["source"]) for hop in hops} | {str(hop["target"]) for hop in hops}:
                if node_id not in self.nodes:
                    continue
                node = self.nodes[node_id]
                if node.file in seen_files and node.file not in interesting_files:
                    continue
                seen_files.add(node.file)
                recommended_slices.append(
                    {
                        "anchor_symbol": node_id,
                        "role": "file_context" if node.file in interesting_files else "support",
                        "file": node.file,
                        "lines": node.lines,
                    }
                )

            paths.append(
                {
                    "path_id": f"architecture::path::{index}",
                    "focus_edge": {"source": source, "target": target},
                    "hops": hops,
                    "path_confidence": round(min(float(hop["confidence_score"]) for hop in hops), 2) if hops else 0.0,
                    "path_kind": self._path_kind_for_hops(target, hops),
                    "recommended_slices": recommended_slices[:3],
                    "stop_reason": "max_hops_reached" if len(hops) > 1 else "no_supported_extension",
                }
            )

        paths.sort(
            key=lambda item: (
                -float(item["path_confidence"]),
                -len(item["hops"]),
                str(item["path_kind"]),
                str(item["path_id"]),
            )
        )
        return paths[:limit]

    def _rank_neighbors(self, neighbors: Iterable[str], limit: int = 3) -> List[Dict[str, object]]:
        ranked = sorted(
            neighbors,
            key=lambda node_id: (-self.nodes[node_id].risk_score, -self.nodes[node_id].ca, node_id),
        )
        out: List[Dict[str, object]] = []
        for node_id in ranked[:limit]:
            node = self.nodes[node_id]
            out.append(
                {
                    "symbol": node_id,
                    "risk_score": node.risk_score,
                    "file": node.file,
                    "lines": node.lines,
                }
            )
        return out

    def _merge_slice_specs(self, slice_specs: List[Dict[str, object]]) -> List[Dict[str, object]]:
        grouped: Dict[str, List[Dict[str, object]]] = defaultdict(list)
        for spec in slice_specs:
            grouped[spec["file"]].append(spec)

        merged: List[Dict[str, object]] = []
        for file_name in sorted(grouped):
            specs = sorted(grouped[file_name], key=lambda spec: (spec["start_line"], spec["end_line"]))
            current: Optional[Dict[str, object]] = None
            for spec in specs:
                if current is None:
                    current = {
                        "file": file_name,
                        "start_line": spec["start_line"],
                        "end_line": spec["end_line"],
                        "symbols": list(spec["symbols"]),
                        "why": list(spec["why"]),
                        "selection_score": float(spec.get("selection_score", 0.0)),
                        "selection_confidence_labels": list(spec.get("selection_confidence_labels", [])) or ([str(spec.get("selection_confidence_label", ""))] if spec.get("selection_confidence_label") else []),
                        "supporting_edges": list(spec.get("supporting_edges", [])),
                        "ambiguity_flags": list(spec.get("ambiguity_flags", [])),
                        "semantic_refs": list(spec.get("semantic_refs", [])),
                        "evidence_groups": list(spec.get("evidence_groups", [])),
                        "evidence_path_refs": list(spec.get("evidence_path_refs", [])),
                    }
                    continue

                if spec["start_line"] <= current["end_line"] + 2:
                    current["end_line"] = max(current["end_line"], spec["end_line"])
                    current["symbols"].extend(spec["symbols"])
                    current["why"].extend(spec["why"])
                    current["selection_score"] = max(float(current.get("selection_score", 0.0)), float(spec.get("selection_score", 0.0)))
                    current["selection_confidence_labels"].extend(list(spec.get("selection_confidence_labels", [])))
                    if spec.get("selection_confidence_label"):
                        current["selection_confidence_labels"].append(str(spec["selection_confidence_label"]))
                    current["supporting_edges"].extend(list(spec.get("supporting_edges", [])))
                    current["ambiguity_flags"].extend(list(spec.get("ambiguity_flags", [])))
                    current["semantic_refs"].extend(list(spec.get("semantic_refs", [])))
                    current["evidence_groups"].extend(list(spec.get("evidence_groups", [])))
                    current["evidence_path_refs"].extend(list(spec.get("evidence_path_refs", [])))
                else:
                    merged.append(self._normalize_slice(current))
                    current = {
                        "file": file_name,
                        "start_line": spec["start_line"],
                        "end_line": spec["end_line"],
                        "symbols": list(spec["symbols"]),
                        "why": list(spec["why"]),
                        "selection_score": float(spec.get("selection_score", 0.0)),
                        "selection_confidence_labels": list(spec.get("selection_confidence_labels", [])) or ([str(spec.get("selection_confidence_label", ""))] if spec.get("selection_confidence_label") else []),
                        "supporting_edges": list(spec.get("supporting_edges", [])),
                        "ambiguity_flags": list(spec.get("ambiguity_flags", [])),
                        "semantic_refs": list(spec.get("semantic_refs", [])),
                        "evidence_groups": list(spec.get("evidence_groups", [])),
                        "evidence_path_refs": list(spec.get("evidence_path_refs", [])),
                    }

            if current is not None:
                merged.append(self._normalize_slice(current))

        return merged

    def _normalize_slice(self, spec: Dict[str, object]) -> Dict[str, object]:
        evidence_groups = self._normalize_evidence_groups(list(spec.get("evidence_groups", [])))
        non_file_groups = [group for group in evidence_groups if str(group.get("role", "")) != "file_context"]
        normalized = {
            "file": spec["file"],
            "start_line": spec["start_line"],
            "end_line": spec["end_line"],
            "line_count": spec["end_line"] - spec["start_line"] + 1,
            "symbols": sorted(set(spec["symbols"])),
            "why": sorted(set(spec["why"])),
        }
        if len(non_file_groups) > 1:
            merge_reason = "Merged nearby evidence anchors in the same file to preserve budget without losing per-anchor provenance."
            normalized["why"] = sorted(set(list(normalized["why"]) + [merge_reason]))
            evidence_groups.append(
                self._make_evidence_group(
                    anchor_symbol=f"file::{spec['file']}",
                    role="file_context",
                    why=[merge_reason],
                    supporting_edges=[],
                    selection_confidence_labels=list(spec.get("selection_confidence_labels", [])),
                    ambiguity_flags=[],
                    selection_score=float(spec.get("selection_score", 0.0)),
                    evidence_path_refs=list(spec.get("evidence_path_refs", [])),
                    semantic_refs=list(spec.get("semantic_refs", [])),
                )
            )
            evidence_groups = self._normalize_evidence_groups(evidence_groups)
        if "selection_score" in spec:
            normalized["selection_score"] = round(float(spec.get("selection_score", 0.0)), 2)
        if spec.get("selection_confidence_labels"):
            normalized["selection_confidence_labels"] = self._sort_confidence_labels(spec["selection_confidence_labels"])
        if spec.get("supporting_edges"):
            normalized["supporting_edges"] = self._dedupe_object_list(list(spec["supporting_edges"]))
        if spec.get("ambiguity_flags"):
            normalized["ambiguity_flags"] = self._dedupe_object_list(list(spec["ambiguity_flags"]))
        if spec.get("semantic_refs"):
            normalized["semantic_refs"] = self._dedupe_semantic_refs(list(spec["semantic_refs"]), limit=6)
        if evidence_groups:
            normalized["evidence_groups"] = evidence_groups
        if spec.get("evidence_path_refs"):
            normalized["evidence_path_refs"] = sorted(set(str(item) for item in spec["evidence_path_refs"] if item))
        return normalized

    def _build_audit_prompt(self) -> str:
        return (
            "Analyze only the provided context_slices first. Use focus_symbols, evidence_groups, support_chains, "
            "evidence_paths, confidence_summary, semantic_candidates, and semantic_watchlist to explain the structural "
            "and behavioral cause of the risk. Treat ambiguity_watchlist items as unresolved until additional evidence "
            "is requested, and request the smallest useful item from deferred_requests instead of asking for whole files."
        )

    def _recursive_symbols(self) -> List[str]:
        return sorted(node_id for node_id, node in self.nodes.items() if node.recursive_self_call)

    def write_bundle(self, report: Dict[str, object], bundle_dir: str) -> str:
        bundle_path = Path(bundle_dir).resolve()
        bundle_path.mkdir(parents=True, exist_ok=True)
        ask_pack = report.get("ask_context_pack") if isinstance(report.get("ask_context_pack"), dict) else None

        report_path = bundle_path / "sia_report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        (bundle_path / "audit_prompt.txt").write_text(
            str(report["llm_context_pack"]["audit_prompt"]) + "\n",
            encoding="utf-8",
        )

        (bundle_path / "project_inventory.json").write_text(
            json.dumps(report["project_inventory"], indent=2),
            encoding="utf-8",
        )

        (bundle_path / "project_context_pack.json").write_text(
            json.dumps(report["project_context_pack"], indent=2),
            encoding="utf-8",
        )

        (bundle_path / "context_pack.json").write_text(
            json.dumps(report["llm_context_pack"], indent=2),
            encoding="utf-8",
        )

        slices_dir = bundle_path / "context_slices"
        slices_dir.mkdir(exist_ok=True)
        for index, spec in enumerate(report["llm_context_pack"]["context_slices"], start=1):
            snippet = self._render_slice_markdown(spec)
            slice_name = f"{index:02d}_{self._safe_slug(str(spec['file']))}_{spec['start_line']}_{spec['end_line']}.md"
            (slices_dir / slice_name).write_text(snippet, encoding="utf-8")

        project_slices_dir = bundle_path / "project_slices"
        project_slices_dir.mkdir(exist_ok=True)
        for index, spec in enumerate(report["project_context_pack"]["file_slices"], start=1):
            snippet = self._render_project_slice_markdown(spec)
            slice_name = f"{index:02d}_{self._safe_slug(str(spec['file']))}.md"
            (project_slices_dir / slice_name).write_text(snippet, encoding="utf-8")

        deferred_path = bundle_path / "deferred_requests.json"
        deferred_path.write_text(
            json.dumps(report["llm_context_pack"]["deferred_requests"], indent=2),
            encoding="utf-8",
        )

        if ask_pack:
            (bundle_path / "ask_context_pack.json").write_text(
                json.dumps(ask_pack, indent=2),
                encoding="utf-8",
            )
            (bundle_path / "work_packet.json").write_text(
                json.dumps(ask_pack.get("work_packet", {}), indent=2),
                encoding="utf-8",
            )
            (bundle_path / "worker_prompt.txt").write_text(
                str(ask_pack.get("worker_prompt", "")) + "\n",
                encoding="utf-8",
            )
            (bundle_path / "worker_trace_template.json").write_text(
                json.dumps(ask_pack.get("worker_trace_template", {}), indent=2),
                encoding="utf-8",
            )
            (bundle_path / "worker_result_template.json").write_text(
                json.dumps(ask_pack.get("worker_result_template", {}), indent=2),
                encoding="utf-8",
            )
            (bundle_path / "worker_validation_rules.json").write_text(
                json.dumps(ask_pack.get("worker_validation_rules", []), indent=2),
                encoding="utf-8",
            )
            (bundle_path / "worker_result_prompt.txt").write_text(
                str(ask_pack.get("worker_result_prompt", "")) + "\n",
                encoding="utf-8",
            )
            (bundle_path / "worker_report_prompt.txt").write_text(
                str(ask_pack.get("worker_report_prompt", "")) + "\n",
                encoding="utf-8",
            )
            (bundle_path / "analysis_result.json").write_text(
                json.dumps(ask_pack.get("analysis_result", {}), indent=2),
                encoding="utf-8",
            )
            (bundle_path / "result_prompt.txt").write_text(
                str(ask_pack.get("result_prompt", "")) + "\n",
                encoding="utf-8",
            )
            (bundle_path / "escalation_controller.json").write_text(
                json.dumps(ask_pack.get("escalation_controller", {}), indent=2),
                encoding="utf-8",
            )
            (bundle_path / "escalation_prompt.txt").write_text(
                str(ask_pack.get("escalation_prompt", "")) + "\n",
                encoding="utf-8",
            )
            (bundle_path / "followup_ask.json").write_text(
                json.dumps(ask_pack.get("followup_ask", {}), indent=2),
                encoding="utf-8",
            )
            (bundle_path / "followup_prompt.txt").write_text(
                str(ask_pack.get("followup_prompt", "")) + "\n",
                encoding="utf-8",
            )
            (bundle_path / "ask_prompt.txt").write_text(
                str(ask_pack.get("ask_prompt", "")) + "\n",
                encoding="utf-8",
            )
            (bundle_path / "analyst_prompt.txt").write_text(
                str(ask_pack.get("analyst_prompt", "")) + "\n",
                encoding="utf-8",
            )
            (bundle_path / "ask_deferred_requests.json").write_text(
                json.dumps(ask_pack.get("deferred_requests", []), indent=2),
                encoding="utf-8",
            )
            ask_slices_dir = bundle_path / "ask_slices"
            ask_slices_dir.mkdir(exist_ok=True)
            for index, spec in enumerate(ask_pack.get("selected_slices", []), start=1):
                snippet = self._render_slice_markdown(spec)
                slice_name = f"{index:02d}_{self._safe_slug(str(spec['file']))}_{spec['start_line']}_{spec['end_line']}.md"
                (ask_slices_dir / slice_name).write_text(snippet, encoding="utf-8")

        (bundle_path / "README_LLM.md").write_text(
            self._render_bundle_readme(report, bundle_path),
            encoding="utf-8",
        )
        return str(bundle_path)

    def _render_slice_markdown(self, spec: Dict[str, object]) -> str:
        file_path = os.path.join(self.root_dir, str(spec["file"]))
        lines: List[str] = []
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError:
            return f"# Missing Slice\n\nCould not read `{spec['file']}`.\n"

        start = int(spec["start_line"])
        end = int(spec["end_line"])
        excerpt_lines = []
        for lineno in range(start, min(end, len(lines)) + 1):
            excerpt_lines.append(f"{lineno:>4}: {lines[lineno - 1].rstrip()}")

        joined_symbols = ", ".join(str(item) for item in spec["symbols"])
        reasons = "\n".join(f"- {item}" for item in spec["why"])
        evidence_groups = []
        for group in spec.get("evidence_groups", []):
            group_header = f"- `{group['anchor_symbol']}` ({group['role']})"
            group_reasons = "".join(f"\n  - {item}" for item in group.get("why", []))
            group_semantics = "".join(
                f"\n  - semantic `{item['signal']}` at `{item['lines'][0]}-{item['lines'][1]}`: {item['reason']}"
                for item in group.get("semantic_refs", [])
            )
            evidence_groups.append(group_header + group_reasons + group_semantics)
        evidence_groups_text = "\n".join(evidence_groups) if evidence_groups else "- none"
        path_refs = ", ".join(str(item) for item in spec.get("evidence_path_refs", [])) or "none"
        semantic_refs = "\n".join(
            f"- `{item['signal']}` at `{item['lines'][0]}-{item['lines'][1]}`: {item['reason']}"
            for item in spec.get("semantic_refs", [])
        ) or "- none"
        return (
            f"# Context Slice\n\n"
            f"File: `{spec['file']}`\n"
            f"Lines: `{start}-{end}`\n"
            f"Symbols: `{joined_symbols}`\n\n"
            f"Why:\n{reasons}\n\n"
            f"Semantic Refs:\n{semantic_refs}\n\n"
            f"Evidence Groups:\n{evidence_groups_text}\n\n"
            f"Evidence Path Refs: `{path_refs}`\n\n"
            f"```{self._language_for_file(str(spec['file']))}\n" + "\n".join(excerpt_lines) + "\n```\n"
        )

    def _render_project_slice_markdown(self, spec: Dict[str, object]) -> str:
        evidence_groups = []
        for group in spec.get("evidence_groups", []):
            evidence_groups.append(f"- `{group['anchor_symbol']}` ({group['role']}): " + "; ".join(group.get("why", [])))
        evidence_groups_text = "\n".join(evidence_groups) if evidence_groups else "- none"
        semantic_refs = "\n".join(
            f"- `{item['signal']}` at `{item['lines'][0]}-{item['lines'][1]}`: {item['reason']}"
            for item in spec.get("semantic_refs", [])
        ) or "- none"
        return (
            "# Project Slice\n\n"
            f"File: `{spec['file']}`\n"
            f"Why: {spec['why']}\n\n"
            f"Semantic Refs:\n{semantic_refs}\n\n"
            f"Evidence Groups:\n{evidence_groups_text}\n\n"
            f"```{self._language_for_file(str(spec['file']))}\n{spec['excerpt']}\n```\n"
        )

    def _render_bundle_readme(self, report: Dict[str, object], bundle_path: Path) -> str:
        pack = report["llm_context_pack"]
        ask_pack = report.get("ask_context_pack") if isinstance(report.get("ask_context_pack"), dict) else None
        inventory = report["project_inventory"]
        technologies = ", ".join(inventory["likely_technologies"]) or "unknown"
        languages = ", ".join(
            f"{item['language']} ({item['file_count']})"
            for item in inventory["language_summary"][:6]
        ) or "unknown"
        read_first_lines = [
            "1. `project_context_pack.json`",
            "2. Check `confidence_summary`, direct `semantic_entrypoints`, contained `semantic_overview`, `architecture_evidence`, `architecture_evidence_paths`, and `ambiguity_watchlist`",
            "3. Files under `project_slices/`",
            "4. `sia_report.json`",
            "5. `context_pack.json` with `evidence_candidates`, `semantic_candidates`, `semantic_watchlist`, `evidence_paths`, `support_chains`, and `evidence_groups`",
            "6. Files under `context_slices/`",
            "7. `deferred_requests.json` only if the first slices are insufficient",
        ]
        ask_section = ""
        if ask_pack:
            analysis_result = ask_pack.get("analysis_result", {}) if isinstance(ask_pack.get("analysis_result"), dict) else {}
            escalation_controller = ask_pack.get("escalation_controller", {}) if isinstance(ask_pack.get("escalation_controller"), dict) else {}
            followup_ask = ask_pack.get("followup_ask", {}) if isinstance(ask_pack.get("followup_ask"), dict) else {}
            work_packet = ask_pack.get("work_packet", {}) if isinstance(ask_pack.get("work_packet"), dict) else {}
            read_first_lines = [
                "1. `ask_context_pack.json` for the query-scoped ranking, analysis_plan, work_packet, analysis_result, and smallest evidence-first slices",
                "2. `work_packet.json`",
                "3. `worker_prompt.txt`",
                "4. `worker_trace_template.json`",
                "5. `worker_result_template.json`",
                "6. `worker_validation_rules.json`",
                "7. `worker_result_prompt.txt`",
                "8. `worker_report_prompt.txt`",
                "9. `analysis_result.json`",
                "10. `escalation_controller.json`",
                "11. `followup_ask.json`",
                "12. `result_prompt.txt`",
                "13. `escalation_prompt.txt`",
                "14. `followup_prompt.txt`",
                "15. `analyst_prompt.txt`",
                "16. `ask_prompt.txt`",
                "17. Files under `ask_slices/`",
                "18. `ask_deferred_requests.json` only if the query remains under-evidenced",
                "19. `project_context_pack.json`",
                "20. Check `confidence_summary`, direct `semantic_entrypoints`, contained `semantic_overview`, `architecture_evidence`, `architecture_evidence_paths`, and `ambiguity_watchlist`",
                "21. Files under `project_slices/`",
                "22. `sia_report.json`",
                "23. `context_pack.json` with `evidence_candidates`, `semantic_candidates`, `semantic_watchlist`, `evidence_paths`, `support_chains`, and `evidence_groups`",
                "24. Files under `context_slices/`",
                "25. `deferred_requests.json` only if the broader bundle is still insufficient",
            ]
            ask_section = (
                "## Query-Scoped Ask Pack\n\n"
                f"- Query: `{ask_pack.get('query', '')}`\n"
                f"- Outcome: `{analysis_result.get('outcome_mode', '')}`\n"
                f"- Worker mode: `{work_packet.get('worker_mode', '')}`\n"
                f"- Escalation allowed: `{bool(escalation_controller.get('escalation_allowed'))}`\n"
                f"- Follow-up enabled: `{bool(followup_ask.get('enabled'))}`\n"
                f"- Selected slices: `{len(ask_pack.get('selected_slices', []))}`\n"
                f"- Selected evidence paths: `{len(ask_pack.get('selected_evidence_paths', []))}`\n"
                f"- Deferred requests: `{len(ask_pack.get('deferred_requests', []))}`\n\n"
                "Use the query-scoped pack first. It is intentionally smaller and prefers executable evidence with "
                "direct semantic matches before contained semantics or broader project context. `work_packet.json`, "
                "`worker_prompt.txt`, `worker_trace_template.json`, `worker_result_template.json`, "
                "`worker_validation_rules.json`, `worker_result_prompt.txt`, `worker_report_prompt.txt`, "
                "`analysis_result.json`, `result_prompt.txt`, `escalation_controller.json`, `escalation_prompt.txt`, "
                "`followup_ask.json`, and `followup_prompt.txt` are the narrowest answer, trace, and validation "
                "contract; only open deferred follow-ups if that bounded result is insufficient and escalation is "
                "explicitly allowed.\n\n"
            )
        return (
            "# SIA Context Bundle\n\n"
            "This bundle is designed as the smallest useful handoff to an LLM coding agent.\n\n"
            "## What To Read First\n\n"
            + "\n".join(read_first_lines)
            + "\n\n"
            + ask_section
            + "## Project Snapshot\n\n"
            + f"- Root: `{report['meta']['root_dir']}`\n"
            + f"- Graph nodes: `{inventory['graph_node_count']}`\n"
            + f"- Python symbols: `{inventory['python_symbol_count']}`\n"
            + f"- Total files seen: `{inventory['total_file_count']}`\n"
            + f"- Likely technologies: `{technologies}`\n"
            + f"- Language mix: `{languages}`\n"
            + f"- Git hotspot support active: `{report['meta']['git_hotspots_enabled']}`\n\n"
            + "## Project Prompt\n\n"
            + f"{report['project_context_pack']['project_prompt']}\n\n"
            + "## Audit Prompt\n\n"
            + f"{pack['audit_prompt']}\n\n"
            + "## Bundle Path\n\n"
            + f"`{bundle_path}`\n"
        )

    def _safe_slug(self, text: str) -> str:
        out = []
        for char in text.lower():
            if char.isalnum():
                out.append(char)
            else:
                out.append("_")
        return "".join(out).strip("_") or "slice"


