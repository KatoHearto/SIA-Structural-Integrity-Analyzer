# ── SIA src/15_worker_validation.py ── (god_mode_v3.py lines 13576–13969) ────────────────────

def _validation_outcome_rank(outcome_mode: str) -> int:
    return OUTCOME_MODE_ORDER.get(str(outcome_mode or ""), -1)


def _load_json_file(path: str) -> Dict[str, object]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _worker_result_claims(worker_result: Dict[str, object]) -> List[str]:
    result_slots = worker_result.get("result_slots", {}) if isinstance(worker_result.get("result_slots"), dict) else {}
    claims: List[str] = []
    for claim in result_slots.get("used_claims", []):
        claim = str(claim).strip()
        if claim and claim not in claims:
            claims.append(claim)
    final_claim = str(result_slots.get("final_claim", "")).strip()
    if final_claim and final_claim not in claims:
        claims.append(final_claim)
    return claims


def _ordered_subsequence_check(sequence: List[str], observed: List[str]) -> Tuple[bool, str]:
    if not sequence:
        return True, ""
    if not observed:
        return False, sequence[0]
    obs_index = 0
    for item in sequence:
        while obs_index < len(observed) and observed[obs_index] != item:
            obs_index += 1
        if obs_index >= len(observed):
            return False, item
        obs_index += 1
    return True, ""


def _build_read_order_coverage(
    required_refs: List[str],
    observed_refs: List[str],
) -> Dict[str, object]:
    required_refs = [str(item) for item in required_refs if str(item)]
    observed_refs = [str(item) for item in observed_refs if str(item)]
    if not required_refs:
        return {
            "required_count": 0,
            "observed_count": len(observed_refs),
            "matched_required_refs": [],
            "ordered_coverage_ratio": 1.0,
            "missing_required_refs": [],
            "first_divergence": None,
            "sequence_status": "no_requirements",
        }

    matched: List[str] = []
    missing_required_refs: List[str] = []
    first_divergence: Optional[Dict[str, object]] = None
    obs_index = 0
    for required_index, required_ref in enumerate(required_refs, start=1):
        found = False
        while obs_index < len(observed_refs):
            observed_ref = observed_refs[obs_index]
            if observed_ref == required_ref:
                matched.append(required_ref)
                obs_index += 1
                found = True
                break
            if first_divergence is None:
                first_divergence = {
                    "required_index": required_index,
                    "required_ref": required_ref,
                    "observed_index": obs_index + 1,
                    "observed_ref": observed_ref,
                }
            obs_index += 1
        if not found:
            missing_required_refs = required_refs[len(matched):]
            if first_divergence is None:
                first_divergence = {
                    "required_index": required_index,
                    "required_ref": required_ref,
                    "observed_index": (obs_index + 1) if obs_index < len(observed_refs) else None,
                    "observed_ref": observed_refs[obs_index] if obs_index < len(observed_refs) else "",
                }
            break

    if len(matched) == len(required_refs):
        sequence_status = "complete_in_order"
    elif not observed_refs:
        sequence_status = "not_started"
    elif first_divergence and not matched:
        sequence_status = "diverged_before_start"
    elif first_divergence:
        sequence_status = "partial_with_divergence"
    else:
        sequence_status = "partial_in_order"

    return {
        "required_count": len(required_refs),
        "observed_count": len(observed_refs),
        "matched_required_refs": matched,
        "ordered_coverage_ratio": round(len(matched) / max(1, len(required_refs)), 2),
        "missing_required_refs": missing_required_refs,
        "first_divergence": first_divergence if sequence_status != "complete_in_order" else None,
        "sequence_status": sequence_status,
    }


def _build_primary_target_coverage(
    required_symbols: List[str],
    observed_symbols: List[str],
) -> Dict[str, object]:
    required_symbols = [str(item) for item in required_symbols if str(item)]
    observed_symbols = [str(item) for item in observed_symbols if str(item)]
    if not required_symbols:
        return {
            "required_count": 0,
            "observed_count": len(observed_symbols),
            "matched_primary_symbols": [],
            "missing_required_symbols": [],
            "coverage_ratio": 1.0,
            "status": "no_requirements",
        }
    observed_set = set(observed_symbols)
    matched = [symbol for symbol in required_symbols if symbol in observed_set]
    missing = [symbol for symbol in required_symbols if symbol not in observed_set]
    if not matched:
        status = "not_started"
    elif not missing:
        status = "complete"
    else:
        status = "partial"
    return {
        "required_count": len(required_symbols),
        "observed_count": len(observed_symbols),
        "matched_primary_symbols": matched,
        "missing_required_symbols": missing,
        "coverage_ratio": round(len(matched) / max(1, len(required_symbols)), 2),
        "status": status,
    }


def _load_worker_contract(
    against_ask_bundle: str,
    against_report: str,
) -> Dict[str, object]:
    if bool(against_ask_bundle) == bool(against_report):
        raise ValueError("Provide exactly one of --against-ask-bundle or --against-report.")
    if against_ask_bundle:
        ask_context_path = os.path.join(os.path.abspath(against_ask_bundle), "ask_context_pack.json")
        ask_pack = _load_json_file(ask_context_path)
        return {
            "contract_source": os.path.abspath(against_ask_bundle),
            "ask_context_pack": ask_pack,
            "worker_trace_template": ask_pack.get("worker_trace_template", {}),
            "worker_result_template": ask_pack.get("worker_result_template", {}),
            "worker_validation_rules": ask_pack.get("worker_validation_rules", []),
        }
    report = _load_json_file(os.path.abspath(against_report))
    ask_pack = report.get("ask_context_pack", {})
    if not isinstance(ask_pack, dict) or not ask_pack:
        raise ValueError("The report does not contain an ask_context_pack.")
    return {
        "contract_source": os.path.abspath(against_report),
        "ask_context_pack": ask_pack,
        "worker_trace_template": ask_pack.get("worker_trace_template", {}),
        "worker_result_template": ask_pack.get("worker_result_template", {}),
        "worker_validation_rules": ask_pack.get("worker_validation_rules", []),
    }


def validate_worker_result_payload(
    worker_result: Dict[str, object],
    contract: Dict[str, object],
) -> Dict[str, object]:
    template = contract.get("worker_result_template", {}) if isinstance(contract.get("worker_result_template"), dict) else {}
    rules = contract.get("worker_validation_rules", []) if isinstance(contract.get("worker_validation_rules"), list) else []
    ask_pack = contract.get("ask_context_pack", {}) if isinstance(contract.get("ask_context_pack"), dict) else {}
    rule_index = {
        str(rule.get("rule_id", "")): rule
        for rule in rules
        if isinstance(rule, dict) and str(rule.get("rule_id", ""))
    }

    result_slots = worker_result.get("result_slots", {}) if isinstance(worker_result.get("result_slots"), dict) else {}
    claims = _worker_result_claims(worker_result)
    allowed_claims = {str(item) for item in template.get("allowed_claims", [])}
    disallowed_claims = {str(item) for item in template.get("disallowed_claims", [])}
    expected_ceiling = str(template.get("expected_outcome_ceiling", "")) or str(
        ask_pack.get("analysis_result", {}).get("outcome_mode", "")
    )
    minimum_honest = str(template.get("minimum_honest_outcome", "")) or expected_ceiling
    inspected_slice_refs = [str(item) for item in result_slots.get("inspected_slice_refs", []) if str(item)]
    inspected_symbols = [str(item) for item in result_slots.get("inspected_symbols", []) if str(item)]
    final_outcome_mode = str(result_slots.get("final_outcome_mode", "")).strip()
    completion_state = str(
        result_slots.get("completion_state", "") or template.get("default_completion_state", "ready_for_execution")
    ).strip()
    followup_used = bool(result_slots.get("followup_used"))
    stop_condition_hit = str(result_slots.get("stop_condition_hit", "")).strip()
    required_read_order_refs = [str(item) for item in template.get("required_read_order_refs", []) if str(item)]
    required_primary_symbols = [str(item) for item in template.get("required_primary_symbols", []) if str(item)]
    valid_stop_conditions = {str(item) for item in template.get("valid_stop_conditions", []) if str(item)}
    supported_completion_states = {str(item) for item in template.get("supported_completion_states", []) if str(item)}
    terminal_states = WORKER_TERMINAL_STATES

    violations: List[Dict[str, object]] = []
    warnings: List[Dict[str, object]] = []
    recommended_fixes: List[str] = []
    accepted_claims = [claim for claim in claims if claim in allowed_claims and claim not in disallowed_claims]
    rejected_claims = [claim for claim in claims if claim not in allowed_claims or claim in disallowed_claims]

    def add_issue(
        bucket: List[Dict[str, object]],
        rule_id: str,
        message: str,
        default_severity: str = "error",
    ) -> None:
        rule = rule_index.get(rule_id, {})
        severity = str(rule.get("severity", default_severity) or default_severity)
        bucket.append(
            {
                "rule_id": rule_id,
                "severity": severity,
                "message": message,
            }
        )

    if rejected_claims:
        add_issue(
            violations,
            "must_respect_allowed_claims",
            f"Claims outside the bounded allow-list were used: {', '.join(rejected_claims[:4])}.",
        )
        recommended_fixes.append("Use only claim strings from `allowed_claims`.")

    disallowed_hits = [claim for claim in claims if claim in disallowed_claims]
    if disallowed_hits:
        add_issue(
            violations,
            "must_not_use_disallowed_claims",
            f"Disallowed claim strings were emitted: {', '.join(disallowed_hits[:4])}.",
        )
        recommended_fixes.append("Remove any claim that appears in `disallowed_claims`.")

    if final_outcome_mode:
        if _validation_outcome_rank(final_outcome_mode) > _validation_outcome_rank(expected_ceiling):
            add_issue(
                violations,
                "must_not_exceed_outcome_ceiling",
                f"`final_outcome_mode = {final_outcome_mode}` exceeds `expected_outcome_ceiling = {expected_ceiling}`.",
            )
            recommended_fixes.append(f"Cap `final_outcome_mode` at `{expected_ceiling}`.")
        if _validation_outcome_rank(final_outcome_mode) < _validation_outcome_rank(minimum_honest):
            add_issue(
                violations,
                "must_not_drop_below_minimum_honest_outcome",
                f"`final_outcome_mode = {final_outcome_mode}` drops below `minimum_honest_outcome = {minimum_honest}`.",
            )
            recommended_fixes.append(f"Keep `final_outcome_mode` at or above `{minimum_honest}`.")
    elif completion_state in terminal_states:
        add_issue(
            violations,
            "must_set_final_outcome_for_terminal_result",
            "Terminal worker results must set `result_slots.final_outcome_mode`.",
        )
        recommended_fixes.append("Set `result_slots.final_outcome_mode` before returning a terminal worker result.")
    elif completion_state not in {"ready_for_execution", "in_progress"}:
        add_issue(
            warnings,
            "must_not_exceed_outcome_ceiling",
            "A non-ready worker result omitted `final_outcome_mode`.",
            default_severity="warning",
        )

    if required_read_order_refs:
        if inspected_slice_refs:
            if inspected_slice_refs[0] != required_read_order_refs[0]:
                add_issue(
                    violations,
                    "must_read_primary_slice_first",
                    f"The first inspected slice `{inspected_slice_refs[0]}` does not match the required primary slice `{required_read_order_refs[0]}`.",
                )
                recommended_fixes.append("Inspect the first required read-order slice before any other slice.")
        elif completion_state not in {"ready_for_execution", "in_progress"}:
            add_issue(
                violations,
                "must_read_primary_slice_first",
                "The worker result reached a terminal state without recording any inspected slice refs.",
            )
            recommended_fixes.append("Record inspected slice refs and start with the first required read-order slice.")
        if completion_state in terminal_states:
            is_complete_sequence, missing_ref = _ordered_subsequence_check(required_read_order_refs, inspected_slice_refs)
            if not is_complete_sequence:
                add_issue(
                    violations,
                    "must_read_required_sequence_for_terminal_result",
                    f"Terminal worker results must include the full required read-order sequence; missing or out-of-order ref `{missing_ref}`.",
                )
                recommended_fixes.append(
                    "For terminal worker results, include every `required_read_order_refs` entry in `inspected_slice_refs` in the exported order."
                )

    if required_primary_symbols:
        missing_primary = [symbol for symbol in required_primary_symbols if symbol not in inspected_symbols]
        if missing_primary and completion_state in terminal_states:
            add_issue(
                violations,
                "must_cover_required_primary_symbols_for_terminal_result",
                f"Terminal worker results must record every required primary symbol; missing `{', '.join(missing_primary[:3])}`.",
            )
            recommended_fixes.append(
                "Record every `required_primary_symbols` entry in `result_slots.inspected_symbols` before returning a terminal worker result."
            )
        elif missing_primary and inspected_symbols:
            add_issue(
                warnings,
                "must_cover_required_primary_symbols_for_terminal_result",
                f"Primary symbols were not all recorded in `inspected_symbols`: {', '.join(missing_primary[:3])}.",
                default_severity="warning",
            )

    if completion_state and completion_state not in supported_completion_states:
        add_issue(
            violations,
            "must_stop_when_completion_criteria_met",
            f"`completion_state = {completion_state}` is not listed in `supported_completion_states`.",
        )
        recommended_fixes.append("Use a completion state from `supported_completion_states`.")
    elif completion_state in terminal_states and stop_condition_hit not in valid_stop_conditions:
        add_issue(
            violations,
            "must_stop_when_completion_criteria_met",
            f"Terminal completion state `{completion_state}` requires a `stop_condition_hit` from `valid_stop_conditions`.",
        )
        recommended_fixes.append("Record a valid `stop_condition_hit` when the worker result is completed or stopped.")

    if not bool(template.get("followup_allowed")) and followup_used:
        add_issue(
            violations,
            "must_not_open_followup_when_disabled",
            "The worker marked `followup_used = true` even though the follow-up gate is closed.",
        )
        recommended_fixes.append("Keep `followup_used = false` while the follow-up gate is closed.")

    if "must_not_claim_uniqueness_while_ambiguous" in rule_index and final_outcome_mode and final_outcome_mode != "ambiguous":
        add_issue(
            violations,
            "must_not_claim_uniqueness_while_ambiguous",
            f"Ambiguous contract requires `final_outcome_mode = ambiguous`, but the worker returned `{final_outcome_mode}`.",
        )
        recommended_fixes.append("Keep ambiguous work packets at `final_outcome_mode = ambiguous` unless new evidence is added and the analysis is rerun.")

    if "must_not_claim_direct_io_without_direct_evidence" in rule_index:
        forbidden_io_claims = [
            claim
            for claim in claims
            if "direct network i/o" in claim.lower() and claim not in allowed_claims
        ]
        if forbidden_io_claims:
            add_issue(
                violations,
                "must_not_claim_direct_io_without_direct_evidence",
                f"Direct I/O claims appeared without direct evidence: {', '.join(forbidden_io_claims[:3])}.",
            )
            recommended_fixes.append("Do not claim direct I/O unless the claim is explicitly allowed by the current bounded result.")

    capped_outcome_mode = expected_ceiling
    if final_outcome_mode:
        if _validation_outcome_rank(final_outcome_mode) <= _validation_outcome_rank(expected_ceiling):
            capped_outcome_mode = final_outcome_mode

    return {
        "valid": not violations,
        "attempted_claims": claims,
        "violations": violations,
        "warnings": warnings,
        "capped_outcome_mode": capped_outcome_mode,
        "accepted_claims": accepted_claims,
        "rejected_claims": rejected_claims,
        "recommended_fix": (
            " ".join(dict.fromkeys(recommended_fixes))
            if recommended_fixes
            else "None; the worker result stays within the bounded contract."
        ),
        "contract_source": str(contract.get("contract_source", "")),
        "expected_outcome_ceiling": expected_ceiling,
        "minimum_honest_outcome": minimum_honest,
    }
