# ── SIA src/16_report_builders.py ── (god_mode_v3.py lines 13970–14188) ────────────────────

def build_worker_result_report(
    worker_result: Dict[str, object],
    contract: Dict[str, object],
    validation_report: Dict[str, object],
) -> Dict[str, object]:
    template = contract.get("worker_result_template", {}) if isinstance(contract.get("worker_result_template"), dict) else {}
    ask_pack = contract.get("ask_context_pack", {}) if isinstance(contract.get("ask_context_pack"), dict) else {}
    trace_template = contract.get("worker_trace_template", {}) if isinstance(contract.get("worker_trace_template"), dict) else {}
    result_slots = worker_result.get("result_slots", {}) if isinstance(worker_result.get("result_slots"), dict) else {}
    trace_slots = worker_result.get("trace_slots", {}) if isinstance(worker_result.get("trace_slots"), dict) else {}

    terminal_states = WORKER_TERMINAL_STATES
    expected_ceiling = str(validation_report.get("expected_outcome_ceiling", "")) or str(template.get("expected_outcome_ceiling", ""))
    followup_allowed = bool(template.get("followup_allowed"))
    allowed_claims = [str(item) for item in template.get("allowed_claims", []) if str(item)]
    disallowed_claims = [str(item) for item in template.get("disallowed_claims", []) if str(item)]
    required_read_order_refs = [str(item) for item in template.get("required_read_order_refs", []) if str(item)]
    required_primary_symbols = [str(item) for item in template.get("required_primary_symbols", []) if str(item)]
    valid_stop_conditions = {str(item) for item in template.get("valid_stop_conditions", []) if str(item)}

    observed_slice_refs = [
        str(item)
        for item in (trace_slots.get("opened_slice_refs", []) or result_slots.get("inspected_slice_refs", []))
        if str(item)
    ]
    observed_symbols = [
        str(item)
        for item in (trace_slots.get("opened_symbols", []) or result_slots.get("inspected_symbols", []))
        if str(item)
    ]
    attempted_claims = [
        str(item)
        for item in (trace_slots.get("claim_attempts", []) or validation_report.get("attempted_claims", []))
        if str(item)
    ]
    accepted_claims = [str(item) for item in validation_report.get("accepted_claims", []) if str(item)]
    rejected_claims = [str(item) for item in validation_report.get("rejected_claims", []) if str(item)]
    final_outcome_mode = str(result_slots.get("final_outcome_mode", "")).strip()
    final_claim = str(result_slots.get("final_claim", "")).strip()
    completion_state = str(
        trace_slots.get("completion_state", "")
        or result_slots.get("completion_state", "")
        or template.get("default_completion_state", "ready_for_execution")
    ).strip()
    stop_condition_hit = str(
        trace_slots.get("stop_condition_triggered", "")
        or result_slots.get("stop_condition_hit", "")
    ).strip()
    followup_touched = bool(
        trace_slots.get("followup_touched")
        if "followup_touched" in trace_slots
        else result_slots.get("followup_used")
    )
    supporting_refs = [str(item) for item in result_slots.get("supporting_refs", []) if str(item)]

    read_order_coverage = _build_read_order_coverage(required_read_order_refs, observed_slice_refs)
    primary_target_coverage = _build_primary_target_coverage(required_primary_symbols, observed_symbols)

    if not attempted_claims:
        claim_surface_status = "no_claims_attempted"
    elif rejected_claims:
        claim_surface_status = "contains_rejected_claims"
    elif accepted_claims:
        claim_surface_status = "bounded_claim_surface"
    else:
        claim_surface_status = "no_accepted_claims"

    if completion_state in terminal_states:
        stop_status = (
            "terminal_stop_recorded"
            if stop_condition_hit in valid_stop_conditions
            else "terminal_stop_missing_or_invalid"
        )
    elif completion_state in {"ready_for_execution", "in_progress"}:
        stop_status = "non_terminal"
    else:
        stop_status = "unsupported_completion_state"

    if followup_allowed and followup_touched:
        followup_status = "used_allowed_followup"
    elif followup_allowed:
        followup_status = "open_not_used"
    elif followup_touched:
        followup_status = "violated_closed_gate"
    else:
        followup_status = "closed_and_respected"

    is_non_terminal = completion_state in {"ready_for_execution", "in_progress"}

    if validation_report.get("valid"):
        if is_non_terminal:
            contract_status = "within_bounds_but_non_terminal"
            boundedness_status = "pending_execution" if completion_state == "ready_for_execution" else "execution_in_progress"
        else:
            contract_status = "warnings_only" if validation_report.get("warnings") else "within_bounds"
            boundedness_status = "within_bounds"
    else:
        contract_status = "violations_present"
        boundedness_status = "violated_contract"

    if not validation_report.get("valid"):
        accepted_outcome_mode = "rejected_pending_fix"
        official_result = {
            "accepted_outcome_mode": "rejected_pending_fix",
            "accepted_claim": "",
            "supporting_refs": [],
            "stop_condition": stop_condition_hit,
            "boundedness_status": "rejected_pending_fix",
            "provisional_capped_outcome_mode": str(validation_report.get("capped_outcome_mode", "")),
        }
    elif is_non_terminal:
        accepted_outcome_mode = "pending_execution" if completion_state == "ready_for_execution" else "in_progress"
        official_result = {
            "accepted_outcome_mode": accepted_outcome_mode,
            "accepted_claim": "",
            "supporting_refs": [],
            "stop_condition": "",
            "boundedness_status": "pending_execution" if completion_state == "ready_for_execution" else "execution_in_progress",
            "provisional_capped_outcome_mode": str(validation_report.get("capped_outcome_mode", "")),
        }
    else:
        accepted_outcome_mode = final_outcome_mode or str(validation_report.get("capped_outcome_mode", "")) or expected_ceiling
        accepted_claim = (
            final_claim
            if final_claim and final_claim in accepted_claims
            else (accepted_claims[0] if accepted_claims else "")
        )
        official_result = {
            "accepted_outcome_mode": accepted_outcome_mode,
            "accepted_claim": accepted_claim,
            "supporting_refs": supporting_refs,
            "stop_condition": stop_condition_hit,
            "boundedness_status": "accepted_within_bounds",
        }

    if not validation_report.get("valid"):
        next_action = "fix_worker_result"
    elif completion_state == "ready_for_execution":
        next_action = "execute_worker"
    elif completion_state == "in_progress":
        next_action = "continue_execution"
    elif followup_allowed and accepted_outcome_mode in {"partial", "unproven", "ambiguous"}:
        next_action = "rerun_with_followup"
    elif accepted_outcome_mode in {"partial", "unproven", "ambiguous"}:
        next_action = "stop_on_current_bounds"
    else:
        next_action = "accept_result"

    if not validation_report.get("valid"):
        validation_message = "Worker result violates the bounded contract and must be fixed before acceptance."
    elif is_non_terminal:
        validation_message = "Worker result is still non-terminal; it stays within the contract so far but is not yet an accepted bounded result."
    else:
        validation_message = "Worker result stays within the bounded contract."

    return {
        "valid": bool(validation_report.get("valid")),
        "accepted_result_mode": accepted_outcome_mode,
        "capped_outcome_mode": str(validation_report.get("capped_outcome_mode", "")),
        "attempted_claims": attempted_claims,
        "accepted_claims": accepted_claims,
        "rejected_claims": rejected_claims,
        "claim_surface_status": claim_surface_status,
        "read_order_coverage": read_order_coverage,
        "primary_target_coverage": primary_target_coverage,
        "contract_adherence": {
            "status": contract_status,
            "rules_checked": len(contract.get("worker_validation_rules", [])) if isinstance(contract.get("worker_validation_rules"), list) else 0,
            "violations_count": len(validation_report.get("violations", [])),
            "warnings_count": len(validation_report.get("warnings", [])),
            "used_only_allowed_claims": not rejected_claims,
            "required_sequence_status": str(read_order_coverage.get("sequence_status", "")),
        },
        "stop_analysis": {
            "completion_state": completion_state,
            "stop_condition_hit": stop_condition_hit,
            "status": stop_status,
            "valid_stop_conditions": sorted(valid_stop_conditions),
        },
        "followup_gate_status": {
            "allowed": followup_allowed,
            "used": followup_touched,
            "status": followup_status,
        },
        "boundedness_status": boundedness_status,
        "validation_summary": {
            "status": (
                "invalid"
                if not validation_report.get("valid")
                else ("pending_execution" if is_non_terminal else "valid")
            ),
            "violation_count": len(validation_report.get("violations", [])),
            "warning_count": len(validation_report.get("warnings", [])),
            "message": validation_message,
        },
        "violations": list(validation_report.get("violations", [])),
        "warnings": list(validation_report.get("warnings", [])),
        "recommended_fix": str(validation_report.get("recommended_fix", "")),
        "official_result": official_result,
        "next_action": next_action,
        "trace_expectations": trace_template.get("trace_expectations", {}) if isinstance(trace_template.get("trace_expectations"), dict) else {},
        "trace_observed": {
            "opened_slice_refs": observed_slice_refs,
            "opened_symbols": observed_symbols,
            "claim_attempts": attempted_claims,
            "accepted_claims": accepted_claims,
            "rejected_claims": rejected_claims,
            "followup_touched": followup_touched,
        },
        "worker_mode": str(worker_result.get("worker_mode", "") or template.get("worker_mode", "")),
        "task": str(worker_result.get("task", "") or ask_pack.get("query", "")),
        "expected_outcome_ceiling": expected_ceiling,
        "minimum_honest_outcome": str(validation_report.get("minimum_honest_outcome", "")),
        "allowed_claims": allowed_claims,
        "disallowed_claims": disallowed_claims,
        "contract_source": str(validation_report.get("contract_source", contract.get("contract_source", ""))),
    }
