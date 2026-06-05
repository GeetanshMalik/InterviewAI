from __future__ import annotations

from typing import Any

from agents.state import AgentWorkflowState, agent_event, append_event
from services.security_gateway import security_gateway


async def security_gatekeeper_node(state: AgentWorkflowState) -> dict[str, Any]:
    interview = dict(state["interview"])
    sanitized = security_gateway.sanitize_all(
        {
            "resume_text": interview.get("resume_text", ""),
            "job_description": interview.get("job_description", ""),
        },
        source="interview",
        limits={"resume_text": 12000, "job_description": 8000},
    )
    resume_result = sanitized["resume_text"]
    jd_result = sanitized["job_description"]
    interview["resume_text"] = resume_result.clean_text
    interview["job_description"] = jd_result.clean_text

    security_state = security_gateway.metadata_for([resume_result, jd_result], source="interview_generation")
    classifier_state = await security_gateway.classify_all(sanitized, source="interview_generation")
    security_state["llm_classifier"] = classifier_state
    security_state["classifier_mode"] = (
        "deterministic_regex_plus_llm" if classifier_state.get("enabled") else "deterministic_regex"
    )
    if classifier_state.get("enabled") and classifier_state.get("risk_level") in {"high", "critical"}:
        security_state["risk_level"] = classifier_state["risk_level"]
        security_state["reasons"] = [*security_state.get("reasons", []), *classifier_state.get("reasons", [])]
    fail_closed = security_gateway.should_fail_closed(sanitized) or bool(classifier_state.get("should_fail_closed"))

    event_type = "error" if fail_closed else ("warning" if security_state["quarantined_count"] else "success")
    message = (
        "Security Gatekeeper blocked high-confidence prompt-injection instructions."
        if fail_closed
        else (
            "Security Gatekeeper sanitized suspicious user-supplied text before agent prompts."
            if security_state["quarantined_count"]
            else "Security Gatekeeper cleared user-supplied text for agent planning."
        )
    )

    update: dict[str, Any] = {
        "interview": interview,
        "security_state": security_state,
        "logs": append_event(
            state,
            agent_event(
                "Security Gatekeeper Agent",
                message,
                "form",
                event_type,
                {
                    "risk_level": security_state["risk_level"],
                    "quarantined_count": security_state["quarantined_count"],
                    "reasons": security_state["reasons"],
                    "classifier_mode": security_state["classifier_mode"],
                    "classifier_risk": classifier_state.get("risk_level"),
                },
            ),
        ),
    }
    if fail_closed:
        update["validation_errors"] = ["Security Gatekeeper blocked high-confidence prompt-injection instructions."]
        update["error"] = update["validation_errors"][0]
        update["status"] = "failed"
    return update


def route_after_security(state: AgentWorkflowState) -> str:
    return "fail" if (state.get("security_state") or {}).get("failed_closed") else "continue"
