from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
try:
    from langgraph.checkpoint.memory import MemorySaver
except Exception:  # pragma: no cover - optional by installed LangGraph version
    MemorySaver = None

from agents.memory_curator_agent import curate_lifecycle_memory_items
from agents.report_agent import build_report
from agents.reviewer_agent import review_lifecycle_artifact_quality
from agents.roadmap_agent import build_roadmap
from agents.state import AgentEvent, CandidateProfile, MemoryState, agent_event, build_candidate_profile_from_interview
from agents.tools.autonomous import execute_autonomous_tool_selection
from agents.tools.decision import ToolDecision, ToolExecutionRecord, execute_tool_decision, tool_decision
from config import settings
from services.security_gateway import security_gateway
from services.store import iso_now, store
from services.workflow import append_workflow_event, ensure_workflow_job, update_workflow_job


class LifecycleState(TypedDict, total=False):
    user_id: str
    interview: dict[str, Any]
    candidate_profile: CandidateProfile
    memory_state: MemoryState
    dsa_submissions: list[dict[str, Any]]
    aptitude_result: dict[str, Any] | None
    technical_answers: list[dict[str, Any]]
    hr_answers: list[dict[str, Any]]
    round_performance: dict[str, Any]
    evaluation_summary: dict[str, Any]
    weakness_profile: dict[str, Any]
    report: dict[str, Any]
    roadmap: dict[str, Any]
    memory_writes: list[dict[str, Any]]
    skipped_memory_writes: list[dict[str, Any]]
    tool_decisions: list[ToolDecision]
    tool_results: list[ToolExecutionRecord]
    report_attempt: int
    roadmap_attempt: int
    max_lifecycle_review_attempts: int
    report_reflection_feedback: list[dict[str, Any]]
    roadmap_reflection_feedback: list[dict[str, Any]]
    lifecycle_reviewer_critiques: list[dict[str, Any]]
    memory_curation_decisions: list[dict[str, Any]]
    report_review_errors: list[str]
    roadmap_review_errors: list[str]
    lifecycle_security_state: dict[str, Any]
    checkpoint_metadata: dict[str, Any]
    logs: list[AgentEvent]
    status: Literal["running", "succeeded", "failed"]
    error: str


def _logs_with(
    state: LifecycleState,
    agent: str,
    message: str,
    step: str = "completed",
    event_type: Literal["info", "success", "warning", "error"] = "info",
    metadata: dict[str, Any] | None = None,
) -> list[AgentEvent]:
    event = agent_event(agent, message, step, event_type, metadata)
    if _can_record_workflow(state.get("interview")):
        try:
            append_workflow_event(
                state["interview"],
                event_type,
                message,
                step,
                metadata,
                agent=agent,
            )
        except Exception:
            # Lifecycle graph state must remain usable even if observability storage is unavailable.
            pass
    return [*state.get("logs", []), event]


def _can_record_workflow(interview: dict[str, Any] | None) -> bool:
    interview_id = str((interview or {}).get("id") or "")
    return bool(interview_id and (interview_id in store.interviews or interview_id in store.workflow_jobs))


def _graph_limit(value: Any, fallback: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return fallback


def _graph_timeout(value: Any, fallback: float, *, minimum: float = 1.0) -> float:
    try:
        return max(minimum, float(value))
    except (TypeError, ValueError):
        return fallback


def _with_lifecycle_node(node_name: str, agent: str, node_func):
    async def wrapped(state: LifecycleState) -> dict[str, Any]:
        interview = state.get("interview")
        timeout_seconds = _graph_timeout(settings.workflow_graph_node_timeout_seconds, 120.0)
        started = time.perf_counter()
        if _can_record_workflow(interview):
            append_workflow_event(
                interview,
                "info",
                f"{agent} started lifecycle node {node_name}.",
                "completed",
                {"node": node_name, "phase": "start", "timeout_seconds": timeout_seconds},
                agent=agent,
            )
            update_workflow_job(interview, status="running", current_node=node_name)

        async def call_node():
            result = node_func(state)
            if inspect.isawaitable(result):
                return await result
            return result

        try:
            result = await asyncio.wait_for(call_node(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            if _can_record_workflow(interview):
                append_workflow_event(
                    interview,
                    "error",
                    f"{agent} lifecycle node {node_name} timed out.",
                    "completed",
                    {"node": node_name, "timeout_seconds": timeout_seconds},
                    agent=agent,
                )
                update_workflow_job(
                    interview,
                    status="running",
                    current_node=node_name,
                    error=f"Lifecycle node {node_name} exceeded {timeout_seconds} seconds.",
                )
            raise TimeoutError(f"Lifecycle node {node_name} exceeded {timeout_seconds} seconds.") from exc
        except Exception as exc:
            if _can_record_workflow(interview):
                append_workflow_event(
                    interview,
                    "error",
                    f"{agent} lifecycle node {node_name} failed.",
                    "completed",
                    {"node": node_name, "error": f"{type(exc).__name__}: {exc}"[:600]},
                    agent=agent,
                )
                update_workflow_job(interview, status="running", current_node=node_name)
            raise

        if _can_record_workflow(interview):
            append_workflow_event(
                interview,
                "success",
                f"{agent} completed lifecycle node {node_name}.",
                "completed",
                {
                    "node": node_name,
                    "phase": "end",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
                agent=agent,
            )
            update_workflow_job(interview, status="running", current_node=node_name)
        return result

    return wrapped


def _average(values: list[float], fallback: float = 0) -> float:
    return round(sum(values) / len(values), 2) if values else fallback


def _round_score(values: list[dict[str, Any]], fallback: float = 0) -> float:
    return _average([float(item.get("score") or 0) for item in values], fallback)


def _round_performance(state: LifecycleState) -> dict[str, Any]:
    dsa_submissions = state.get("dsa_submissions", [])
    aptitude_result = state.get("aptitude_result")
    technical_answers = state.get("technical_answers", [])
    hr_answers = state.get("hr_answers", [])
    return {
        "dsa": {
            "score": _round_score(dsa_submissions),
            "submitted": len(dsa_submissions),
            "evidenceCount": sum(len(item.get("testResults", [])) for item in dsa_submissions),
        },
        "aptitude": {
            "score": float((aptitude_result or {}).get("score") or 0),
            "submitted": 1 if aptitude_result else 0,
            "evidenceCount": len((aptitude_result or {}).get("per_question_results", [])),
        },
        "technical": {
            "score": _round_score(technical_answers),
            "submitted": len(technical_answers),
            "evidenceCount": sum(len(item.get("evidence", [])) for item in technical_answers),
        },
        "hr": {
            "score": _round_score(hr_answers),
            "submitted": len(hr_answers),
            "evidenceCount": sum(len(item.get("evidence", [])) for item in hr_answers),
        },
    }


async def collect_round_performance_node(state: LifecycleState) -> dict[str, Any]:
    interview = state["interview"]
    core_security = security_gateway.sanitize_all(
        {
            "resume_text": interview.get("resume_text", ""),
            "job_description": interview.get("job_description", ""),
        },
        source="lifecycle",
        limits={"resume_text": 12000, "job_description": 8000},
    )
    security_results = [core_security["resume_text"], core_security["job_description"]]
    interview["resume_text"] = core_security["resume_text"].clean_text
    interview["job_description"] = core_security["job_description"].clean_text

    technical_answers = []
    for index, answer in enumerate(state.get("technical_answers", [])):
        item = dict(answer)
        result = security_gateway.sanitize_text(
            item.get("answer") or item.get("text", ""),
            source=f"lifecycle.technical_answer.{index}",
            limit=5000,
        )
        if "answer" in item:
            item["answer"] = result.clean_text
        if "text" in item:
            item["text"] = result.clean_text
        security_results.append(result)
        technical_answers.append(item)

    hr_answers = []
    for index, answer in enumerate(state.get("hr_answers", [])):
        item = dict(answer)
        result = security_gateway.sanitize_text(
            item.get("answer") or item.get("text", ""),
            source=f"lifecycle.hr_answer.{index}",
            limit=5000,
        )
        if "answer" in item:
            item["answer"] = result.clean_text
        if "text" in item:
            item["text"] = result.clean_text
        security_results.append(result)
        hr_answers.append(item)

    profile = build_candidate_profile_from_interview(interview)
    performance = _round_performance(state)
    security_state = security_gateway.metadata_for(security_results, source="lifecycle")
    return {
        "interview": interview,
        "technical_answers": technical_answers,
        "hr_answers": hr_answers,
        "lifecycle_security_state": security_state,
        "candidate_profile": profile,
        "round_performance": performance,
        "logs": _logs_with(
            state,
            "Workflow Orchestrator Agent",
            "Collected round performance into shared lifecycle state.",
            metadata={
                "rounds": list(performance.keys()),
                "security_risk_level": security_state.get("risk_level"),
                "quarantined_count": security_state.get("quarantined_count"),
            },
        ),
    }


async def retrieve_lifecycle_memory_node(state: LifecycleState) -> dict[str, Any]:
    profile = state.get("candidate_profile") or {}
    query = " ".join(
        str(part)
        for part in [
            profile.get("target_role", ""),
            profile.get("inferred_domain", ""),
            " ".join(profile.get("skills", [])),
            state["interview"].get("difficulty", ""),
            "interview report roadmap weakness transcript",
        ]
        if part
    )
    decisions = [
        tool_decision(
            "Memory Agent",
            "retrieve_memory_context",
            "Retrieve semantic memories before final evaluation and roadmap planning.",
            {
                "user_id": state["user_id"],
                "query": query or "interview lifecycle memory",
                "limit": 8,
            },
            required=False,
        ),
        tool_decision(
            "Report Agent",
            "retrieve_reports",
            "Inspect previous reports so the final report can account for historical evidence.",
            {"user_id": state["user_id"], "limit": 3},
            required=False,
        ),
        tool_decision(
            "Roadmap Agent",
            "retrieve_roadmap",
            "Inspect the active roadmap before generating a new adaptive roadmap.",
            {"user_id": state["user_id"], "active_only": True, "limit": 1},
            required=False,
        ),
    ]
    selector_specs = [
        (
            "memory",
            ["retrieve_memory_context"],
            [decisions[0]],
            "Choose semantic memory retrieval only if historical user memory can improve lifecycle evaluation.",
        ),
        (
            "report",
            ["retrieve_reports"],
            [decisions[1]],
            "Choose report retrieval only if prior reports can improve evidence coverage or trend comparison.",
        ),
        (
            "roadmap",
            ["retrieve_roadmap"],
            [decisions[2]],
            "Choose roadmap retrieval only if an active roadmap can improve next-plan continuity.",
        ),
    ]
    tool_runs = [
        await execute_autonomous_tool_selection(
            agent=agent,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are the InterviewOS {agent.title()} Agent deciding backend tool use. {instruction} "
                        "Use no tool when the lifecycle state already has enough evidence."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"User id: {state['user_id']}\nQuery: {query or 'interview lifecycle memory'}\n"
                        f"Round performance: {state.get('round_performance', {})}\n"
                        f"Candidate profile: {profile}"
                    ),
                },
            ],
            available_tools=tools,
            fallback_decisions=fallback,
        )
        for agent, tools, fallback, instruction in selector_specs
    ]
    records = [record for run in tool_runs for record in run.tool_results]
    selected_decisions = [decision for run in tool_runs for decision in run.tool_decisions]
    memory_record = next(
        (record for record in records if record["decision"]["tool"] == "retrieve_memory_context"),
        None,
    )
    memories = memory_record.get("data", {}).get("memories", []) if memory_record and memory_record.get("ok") else []
    report_count = next(
        (record.get("data", {}).get("count", 0) for record in records if record["decision"]["tool"] == "retrieve_reports"),
        0,
    )
    roadmap_count = next(
        (record.get("data", {}).get("count", 0) for record in records if record["decision"]["tool"] == "retrieve_roadmap"),
        0,
    )
    memory_state: MemoryState = {
        "retrieved": memories,
        "query": query,
        "memory_types": sorted({str(item.get("metadata", {}).get("memory_type", "unknown")) for item in memories}),
        "notes": [
            f"Retrieved {len(memories)} semantic memory item(s), {report_count} prior report(s), and {roadmap_count} active roadmap item(s)."
        ],
    }
    return {
        "memory_state": memory_state,
        "tool_decisions": [*state.get("tool_decisions", []), *selected_decisions],
        "tool_results": [*state.get("tool_results", []), *records],
        "logs": _logs_with(
            state,
            "Memory Agent",
            f"Executed {len(selected_decisions)} lifecycle retrieval tool decision(s).",
            metadata={
                "tools": [decision["tool"] for decision in selected_decisions],
                "semantic_memory_count": len(memories),
                "tool_selection": [run.provider_metadata for run in tool_runs],
            },
        ),
    }


async def final_evaluation_node(state: LifecycleState) -> dict[str, Any]:
    performance = state.get("round_performance") or {}
    scored_rounds = [
        {"round": name, "score": float(item.get("score") or 0), "evidenceCount": int(item.get("evidenceCount") or 0)}
        for name, item in performance.items()
    ]
    overall = _average([item["score"] for item in scored_rounds])
    weak = [item for item in scored_rounds if item["score"] < 75]
    if not weak and scored_rounds:
        weak = [min(scored_rounds, key=lambda item: item["score"])]
    strong = [item for item in scored_rounds if item["score"] >= 75]
    memory_state = state.get("memory_state") or {}
    evaluation_summary = {
        "agent": "Evaluation Agent",
        "overallScore": overall,
        "rounds": scored_rounds,
        "strengths": [item["round"] for item in strong],
        "weaknesses": [item["round"] for item in weak],
        "historicalMemoryCount": len(memory_state.get("retrieved", [])),
        "generatedAt": iso_now(),
    }
    weakness_profile = {
        "agent": "Evaluation Agent",
        "currentWeaknesses": [
            {
                "round": item["round"],
                "score": item["score"],
                "priority": "high" if item["score"] < 60 else "medium",
            }
            for item in weak
        ],
        "memoryTypesUsed": memory_state.get("memory_types", []),
    }
    return {
        "evaluation_summary": evaluation_summary,
        "weakness_profile": weakness_profile,
        "logs": _logs_with(
            state,
            "Evaluation Agent",
            "Final evaluation summary and weakness profile produced.",
            metadata={"overallScore": overall, "weaknesses": evaluation_summary["weaknesses"]},
        ),
    }


async def report_node(state: LifecycleState) -> dict[str, Any]:
    attempt = int(state.get("report_attempt") or 0) + 1
    interview = dict(state["interview"])
    if state.get("report_reflection_feedback"):
        interview["_agentic_report_reflection_feedback"] = state.get("report_reflection_feedback", [])
        interview["_agentic_report_repair_attempt"] = attempt

    report = await build_report(
        state["user_id"],
        interview,
        state.get("dsa_submissions", []),
        state.get("aptitude_result"),
        state.get("technical_answers", []),
        state.get("hr_answers", []),
        include_agent_evidence=True,
    )
    report_tool_decisions = report.pop("_agentic_tool_decisions", [])
    report_tool_results = report.pop("_agentic_tool_results", [])
    report["evaluationSummary"] = state.get("evaluation_summary", {})
    report["weaknessProfile"] = state.get("weakness_profile", {})
    report["memoryContext"] = {
        "retrievedCount": len((state.get("memory_state") or {}).get("retrieved", [])),
        "memoryTypes": (state.get("memory_state") or {}).get("memory_types", []),
    }
    return {
        "report_attempt": attempt,
        "report": report,
        "tool_decisions": [*state.get("tool_decisions", []), *report_tool_decisions],
        "tool_results": [*state.get("tool_results", []), *report_tool_results],
        "logs": _logs_with(
            state,
            "Report Agent",
            f"Report artifact created from lifecycle graph evidence on attempt {attempt}.",
            metadata={
                "report_id": report["id"],
                "overallScore": report["overallScore"],
                "attempt": attempt,
                "repair": bool(state.get("report_reflection_feedback")),
                "tool_decisions": len(report_tool_decisions),
            },
            event_type="success",
        ),
    }


def _section_lookup(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(section.get("name", "")).strip().lower(): section for section in report.get("sections", [])}


def _round_label(round_name: str) -> str:
    mapping = {
        "dsa": "DSA",
        "aptitude": "Aptitude",
        "technical": "Technical",
        "hr": "HR",
    }
    return mapping.get(round_name.lower(), round_name)


def _text_blob(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_text_blob(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_text_blob(item) for item in value)
    return str(value or "")


def _report_review_errors(state: LifecycleState) -> list[str]:
    report = state.get("report") or {}
    performance = state.get("round_performance") or {}
    evaluation = state.get("evaluation_summary") or {}
    weakness_profile = state.get("weakness_profile") or {}
    errors: list[str] = []

    if not str(report.get("executiveSummary") or report.get("aiFeedback") or "").strip():
        errors.append("Report Agent must provide an executive summary or AI feedback.")

    try:
        report_score = float(report.get("overallScore"))
        expected_score = float(evaluation.get("overallScore"))
        if abs(report_score - expected_score) > 5:
            errors.append("Report Agent overall score must stay aligned with Evaluation Agent evidence.")
    except (TypeError, ValueError):
        errors.append("Report Agent must provide a numeric overall score.")

    sections = _section_lookup(report)
    for round_name, round_data in performance.items():
        section = sections.get(_round_label(round_name).lower())
        if not section:
            errors.append(f"Report Agent must include a {_round_label(round_name)} section.")
            continue
        evidence_text = _text_blob(section.get("details", {})) + " " + str(section.get("feedback", ""))
        if int(round_data.get("submitted") or 0) > 0 and not evidence_text.strip():
            errors.append(f"Report Agent must include evidence for {_round_label(round_name)} performance.")

    weak_rounds = [
        _round_label(str(item.get("round", ""))).lower()
        for item in weakness_profile.get("currentWeaknesses", [])
        if item.get("round")
    ]
    report_weakness_text = _text_blob(
        {
            "weaknesses": report.get("weaknesses", []),
            "whatWentWrong": report.get("whatWentWrong", []),
            "nextTimeSuggestions": report.get("nextTimeSuggestions", []),
            "aiFeedback": report.get("aiFeedback", ""),
        }
    ).lower()
    for weak_round in weak_rounds:
        if weak_round and weak_round not in report_weakness_text:
            errors.append(f"Report Agent must explicitly address the {weak_round.upper()} weakness.")

    return errors


async def review_report_node(state: LifecycleState) -> dict[str, Any]:
    errors = _report_review_errors(state)
    qualitative_review = await review_lifecycle_artifact_quality(
        artifact="report",
        lifecycle_state=state,
        deterministic_errors=errors,
    )
    quality_errors = [
        f"Qualitative Reviewer: {error}"
        for error in qualitative_review.get("qualityErrors", [])
        if str(error).strip()
    ]
    if not qualitative_review.get("accepted", not quality_errors) and not quality_errors and not errors:
        quality_errors.append("Qualitative Reviewer rejected the report without a specific error.")
    if not qualitative_review.get("accepted", not quality_errors):
        errors = [*errors, *quality_errors]
    event_type: Literal["success", "warning"] = "success" if not errors else "warning"
    message = (
        "Report reviewer accepted evidence coverage and weakness alignment."
        if not errors
        else "Report reviewer found evidence/alignment gaps."
    )
    return {
        "report_review_errors": errors,
        "lifecycle_reviewer_critiques": [*state.get("lifecycle_reviewer_critiques", []), qualitative_review],
        "logs": _logs_with(
            state,
            "Reviewer Agent",
            message,
            metadata={
                "errors": errors,
                "attempt": state.get("report_attempt", 0),
                "reviewer_provider": qualitative_review.get("provider"),
                "reviewer_fallback": qualitative_review.get("fallbackUsed"),
            },
            event_type=event_type,
        ),
    }


def route_after_report_review(state: LifecycleState) -> str:
    if not state.get("report_review_errors"):
        return "accepted"
    attempt = int(state.get("report_attempt") or 0)
    max_attempts = int(state.get("max_lifecycle_review_attempts") or 2)
    return "repair" if attempt < max_attempts else "accepted_with_warnings"


async def repair_report_node(state: LifecycleState) -> dict[str, Any]:
    errors = state.get("report_review_errors", [])
    attempt = int(state.get("report_attempt") or 0)
    latest_review = (state.get("lifecycle_reviewer_critiques") or [{}])[-1]
    qualitative_instructions = [
        str(item)
        for item in latest_review.get("repairInstructions", [])
        if str(item).strip()
    ]
    critique = {
        "agent": "Reviewer Agent",
        "artifact": "report",
        "attempt": attempt,
        "validationErrors": errors,
        "qualitativeReview": latest_review,
        "requiredCorrections": [
            {
                "issue": error,
                "instruction": (
                    "Regenerate the report with explicit round evidence, score alignment, and weakness-specific "
                    "guidance grounded in the lifecycle state."
                ),
            }
            for error in errors
        ]
        + [
            {
                "issue": "Qualitative review repair instruction",
                "instruction": instruction,
            }
            for instruction in qualitative_instructions
        ],
        "decision": "repair_report",
    }
    return {
        "report_reflection_feedback": [*state.get("report_reflection_feedback", []), critique],
        "lifecycle_reviewer_critiques": [*state.get("lifecycle_reviewer_critiques", []), critique],
        "logs": _logs_with(
            state,
            "Reviewer Agent",
            "Reviewer requested report regeneration with critique feedback.",
            metadata={
                "attempt": attempt,
                "next_attempt": attempt + 1,
                "validation_errors": errors,
                "decision": "repair_report",
            },
            event_type="warning",
        ),
    }


async def roadmap_node(state: LifecycleState) -> dict[str, Any]:
    attempt = int(state.get("roadmap_attempt") or 0) + 1
    report = dict(state["report"])
    if state.get("roadmap_reflection_feedback"):
        report["_agentic_roadmap_reflection_feedback"] = state.get("roadmap_reflection_feedback", [])
        report["lifecycleReviewerFeedback"] = state.get("roadmap_reflection_feedback", [])

    roadmap = await build_roadmap(
        state["user_id"],
        report,
        state["interview"].get("target_role"),
        include_agent_evidence=True,
    )
    roadmap_tool_decisions = roadmap.pop("_agentic_tool_decisions", [])
    roadmap_tool_results = roadmap.pop("_agentic_tool_results", [])
    roadmap["weaknessProfile"] = state.get("weakness_profile", {})
    return {
        "roadmap_attempt": attempt,
        "roadmap": roadmap,
        "tool_decisions": [*state.get("tool_decisions", []), *roadmap_tool_decisions],
        "tool_results": [*state.get("tool_results", []), *roadmap_tool_results],
        "logs": _logs_with(
            state,
            "Roadmap Agent",
            f"Roadmap artifact created from report and weakness profile on attempt {attempt}.",
            metadata={
                "roadmap_id": roadmap["id"],
                "source_report_id": report["id"],
                "attempt": attempt,
                "repair": bool(state.get("roadmap_reflection_feedback")),
                "tool_decisions": len(roadmap_tool_decisions),
            },
            event_type="success",
        ),
    }


def _roadmap_review_errors(state: LifecycleState) -> list[str]:
    report = state.get("report") or {}
    roadmap = state.get("roadmap") or {}
    weakness_profile = state.get("weakness_profile") or {}
    errors: list[str] = []

    if roadmap.get("sourceReportId") != report.get("id"):
        errors.append("Roadmap Agent must link the roadmap to the lifecycle report.")
    if not roadmap.get("skills"):
        errors.append("Roadmap Agent must include prioritized skills.")
    milestones = roadmap.get("milestones", [])
    if len(milestones) < 4:
        errors.append("Roadmap Agent must include at least four weekly milestones.")
    for index, milestone in enumerate(milestones, start=1):
        if len(milestone.get("tasks", [])) < 4:
            errors.append(f"Roadmap Agent milestone {index} must include at least four practice tasks.")

    weak_rounds = [
        _round_label(str(item.get("round", ""))).lower()
        for item in weakness_profile.get("currentWeaknesses", [])
        if item.get("round")
    ]
    roadmap_text = _text_blob(
        {
            "title": roadmap.get("title", ""),
            "description": roadmap.get("description", ""),
            "skills": roadmap.get("skills", []),
            "milestones": roadmap.get("milestones", []),
        }
    ).lower()
    for weak_round in weak_rounds:
        if weak_round and weak_round not in roadmap_text:
            errors.append(f"Roadmap Agent must align tasks with the {weak_round.upper()} weakness.")

    return errors


async def review_roadmap_node(state: LifecycleState) -> dict[str, Any]:
    errors = _roadmap_review_errors(state)
    qualitative_review = await review_lifecycle_artifact_quality(
        artifact="roadmap",
        lifecycle_state=state,
        deterministic_errors=errors,
    )
    quality_errors = [
        f"Qualitative Reviewer: {error}"
        for error in qualitative_review.get("qualityErrors", [])
        if str(error).strip()
    ]
    if not qualitative_review.get("accepted", not quality_errors) and not quality_errors and not errors:
        quality_errors.append("Qualitative Reviewer rejected the roadmap without a specific error.")
    if not qualitative_review.get("accepted", not quality_errors):
        errors = [*errors, *quality_errors]
    event_type: Literal["success", "warning"] = "success" if not errors else "warning"
    message = (
        "Roadmap reviewer accepted weakness alignment and task coverage."
        if not errors
        else "Roadmap reviewer found weakness/task alignment gaps."
    )
    return {
        "roadmap_review_errors": errors,
        "lifecycle_reviewer_critiques": [*state.get("lifecycle_reviewer_critiques", []), qualitative_review],
        "logs": _logs_with(
            state,
            "Reviewer Agent",
            message,
            metadata={
                "errors": errors,
                "attempt": state.get("roadmap_attempt", 0),
                "reviewer_provider": qualitative_review.get("provider"),
                "reviewer_fallback": qualitative_review.get("fallbackUsed"),
            },
            event_type=event_type,
        ),
    }


def route_after_roadmap_review(state: LifecycleState) -> str:
    if not state.get("roadmap_review_errors"):
        return "accepted"
    attempt = int(state.get("roadmap_attempt") or 0)
    max_attempts = int(state.get("max_lifecycle_review_attempts") or 2)
    return "repair" if attempt < max_attempts else "accepted_with_warnings"


async def repair_roadmap_node(state: LifecycleState) -> dict[str, Any]:
    errors = state.get("roadmap_review_errors", [])
    attempt = int(state.get("roadmap_attempt") or 0)
    latest_review = (state.get("lifecycle_reviewer_critiques") or [{}])[-1]
    qualitative_instructions = [
        str(item)
        for item in latest_review.get("repairInstructions", [])
        if str(item).strip()
    ]
    critique = {
        "agent": "Reviewer Agent",
        "artifact": "roadmap",
        "attempt": attempt,
        "validationErrors": errors,
        "qualitativeReview": latest_review,
        "requiredCorrections": [
            {
                "issue": error,
                "instruction": (
                    "Regenerate the roadmap with concrete weekly tasks that explicitly target the weakness profile "
                    "and preserve the lifecycle report link."
                ),
            }
            for error in errors
        ]
        + [
            {
                "issue": "Qualitative review repair instruction",
                "instruction": instruction,
            }
            for instruction in qualitative_instructions
        ],
        "decision": "repair_roadmap",
    }
    return {
        "roadmap_reflection_feedback": [*state.get("roadmap_reflection_feedback", []), critique],
        "lifecycle_reviewer_critiques": [*state.get("lifecycle_reviewer_critiques", []), critique],
        "logs": _logs_with(
            state,
            "Reviewer Agent",
            "Reviewer requested roadmap regeneration with critique feedback.",
            metadata={
                "attempt": attempt,
                "next_attempt": attempt + 1,
                "validation_errors": errors,
                "decision": "repair_roadmap",
            },
            event_type="warning",
        ),
    }


def _memory_text_for_report(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            str(report.get("executiveSummary") or ""),
            str(report.get("aiFeedback") or ""),
            "Strengths: " + ", ".join(str(item) for item in report.get("strengths", [])),
            "Weaknesses: " + ", ".join(str(item) for item in report.get("weaknesses", [])),
            "Next suggestions: " + ", ".join(str(item) for item in report.get("nextTimeSuggestions", [])),
        ]
    )


def _memory_input(
    user_id: str,
    memory_type: str,
    source_id: str,
    text: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    final_metadata = {
        "privacy_scope": "user",
        "importance": "high",
        **metadata,
        "type": memory_type,
    }
    return {
        "user_id": user_id,
        "memory_type": memory_type,
        "source_id": source_id,
        "text": text,
        "metadata": final_metadata,
        "defer_indexing": True,
    }


def _useful_memory_item(item: dict[str, Any]) -> tuple[bool, str]:
    text = str(item.get("text", "")).strip()
    memory_type = str(item.get("memory_type", ""))
    if len(text) < 30:
        return False, "text_too_short"
    if memory_type in {"weakness", "evaluation", "report", "roadmap"}:
        return True, "high_value_lifecycle_memory"
    if memory_type == "transcript" and len(text) >= 120:
        return True, "substantive_transcript"
    return False, "not_marked_useful_by_memory_policy"


async def write_memory_node(state: LifecycleState) -> dict[str, Any]:
    user_id = state["user_id"]
    report = state["report"]
    roadmap = state["roadmap"]
    pending: list[dict[str, Any]] = []

    report_text = _memory_text_for_report(report)
    if report_text.strip():
        pending.append(
            _memory_input(
                user_id,
                "report",
                report["id"],
                report_text,
                {"interview_id": report.get("interviewId"), "overall_score": report.get("overallScore")},
            )
        )

    weakness_text = "\n".join(str(item) for item in report.get("weaknesses", []))
    if weakness_text.strip():
        pending.append(
            _memory_input(
                user_id,
                "weakness",
                f"{report['id']}:weaknesses",
                weakness_text,
                {"report_id": report["id"], "weakness_profile": state.get("weakness_profile", {})},
            )
        )

    evaluation_text = str(state.get("evaluation_summary", {}))
    pending.append(
        _memory_input(
            user_id,
            "evaluation",
            f"{report['id']}:evaluation",
            evaluation_text,
            {"report_id": report["id"], "interview_id": report.get("interviewId")},
        )
    )

    transcript_text = "\n".join(
        str(item.get("text", ""))
        for item in report.get("transcript", [])
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    )
    if transcript_text.strip():
        pending.append(
            _memory_input(
                user_id,
                "transcript",
                f"{report['id']}:transcript",
                transcript_text,
                {"report_id": report["id"], "interview_id": report.get("interviewId")},
            )
        )

    roadmap_text = "\n".join(
        [
            str(roadmap.get("title") or ""),
            str(roadmap.get("description") or ""),
            "\n".join(str(milestone.get("title", "")) for milestone in roadmap.get("milestones", [])),
        ]
    )
    if roadmap_text.strip():
        pending.append(
            _memory_input(
                user_id,
                "roadmap",
                roadmap["id"],
                roadmap_text,
                {"report_id": report["id"], "progress": roadmap.get("progress", 0)},
            )
        )

    curation = await curate_lifecycle_memory_items(user_id, pending)
    curation_by_source = {str(item.get("source_id")): item for item in curation.decisions}
    useful_pending: list[dict[str, Any]] = []
    seen_memory_keys: set[tuple[str, str, str]] = set()
    skipped = []
    for item in pending:
        memory_key = (str(item.get("user_id")), str(item.get("memory_type")), str(item.get("source_id")))
        if memory_key in seen_memory_keys:
            skipped.append(
                {
                    "memoryType": item.get("memory_type"),
                    "sourceId": item.get("source_id"),
                    "reason": "duplicate_lifecycle_memory_write",
                    "decisionSource": "batch_dedupe",
                    "textLength": len(str(item.get("text", ""))),
                }
            )
            continue
        seen_memory_keys.add(memory_key)
        decision = curation_by_source.get(str(item.get("source_id"))) or {
            "decision": "write" if _useful_memory_item(item)[0] else "skip",
            "reason": _useful_memory_item(item)[1],
            "importance": item.get("metadata", {}).get("importance", "medium"),
            "decision_source": "deterministic_safety_fallback",
        }
        if decision.get("decision") == "write":
            item["metadata"]["memory_policy_reason"] = decision.get("reason")
            item["metadata"]["memory_curator_provider"] = curation.provider
            item["metadata"]["memory_curator_model"] = curation.model
            item["metadata"]["memory_curator_source"] = decision.get("decision_source")
            item["metadata"]["importance"] = decision.get("importance") or item["metadata"].get("importance", "medium")
            if decision.get("merge_with_source_id"):
                item["metadata"]["merge_with_source_id"] = decision.get("merge_with_source_id")
            useful_pending.append(item)
        else:
            skipped.append(
                {
                    "memoryType": item.get("memory_type"),
                    "sourceId": item.get("source_id"),
                    "reason": decision.get("reason"),
                    "decisionSource": decision.get("decision_source"),
                    "textLength": len(str(item.get("text", ""))),
                }
            )

    decisions = [
        tool_decision(
            "Memory Agent",
            "write_memory",
            f"Memory Curation Agent marked {item['memory_type']} lifecycle output useful for persistence.",
            item,
        )
        for item in useful_pending
    ]
    records = [await execute_tool_decision(decision) for decision in decisions]
    writes = [
        {
            "memoryType": record["decision"]["inputs"]["memory_type"],
            "sourceId": record["decision"]["inputs"]["source_id"],
            "textLength": record["decision"]["inputs"]["metadata"].get("textLength")
            or len(str(record["decision"]["inputs"].get("text", ""))),
            "ok": record["ok"],
            "error": record.get("error"),
        }
        for record in records
    ]

    return {
        "memory_writes": writes,
        "skipped_memory_writes": skipped,
        "memory_curation_decisions": curation.decisions,
        "tool_decisions": [*state.get("tool_decisions", []), *curation.tool_decisions, *decisions],
        "tool_results": [*state.get("tool_results", []), *curation.tool_results, *records],
        "logs": _logs_with(
            state,
            "Memory Agent",
            f"Wrote {len(writes)} lifecycle memory record(s) after autonomous curation.",
            metadata={
                "writes": writes,
                "skipped": skipped,
                "curatorProvider": curation.provider,
                "fallbackUsed": curation.fallback_used,
            },
            event_type="success",
        ),
    }


def _checkpoint_payload(state: LifecycleState) -> dict[str, Any]:
    return {
        "status": "succeeded",
        "evaluation_summary": state.get("evaluation_summary", {}),
        "weakness_profile": state.get("weakness_profile", {}),
        "memory_state": {
            "query": (state.get("memory_state") or {}).get("query", ""),
            "memory_types": (state.get("memory_state") or {}).get("memory_types", []),
            "retrieved_count": len((state.get("memory_state") or {}).get("retrieved", [])),
        },
        "lifecycle_security_state": state.get("lifecycle_security_state", {}),
        "memory_curation_decisions": state.get("memory_curation_decisions", []),
        "checkpoint_metadata": state.get("checkpoint_metadata", {}),
        "report_id": (state.get("report") or {}).get("id"),
        "roadmap_id": (state.get("roadmap") or {}).get("id"),
        "memory_writes": state.get("memory_writes", []),
        "skipped_memory_writes": state.get("skipped_memory_writes", []),
        "tool_decision_count": len(state.get("tool_decisions", [])),
        "tool_result_count": len(state.get("tool_results", [])),
        "report_attempt": state.get("report_attempt", 0),
        "roadmap_attempt": state.get("roadmap_attempt", 0),
        "lifecycle_reviewer_critiques": state.get("lifecycle_reviewer_critiques", []),
        "report_review_errors": state.get("report_review_errors", []),
        "roadmap_review_errors": state.get("roadmap_review_errors", []),
    }


async def complete_lifecycle_node(state: LifecycleState) -> dict[str, Any]:
    interview = state["interview"]
    report = state["report"]
    interview["status"] = "completed"
    interview["currentStep"] = "completed"
    interview["overallScore"] = report["overallScore"]
    interview["completedAt"] = interview.get("completedAt") or iso_now()

    result = {"lifecycle_state": _checkpoint_payload(state)}
    if _can_record_workflow(interview):
        job = ensure_workflow_job(interview)
        result = dict(job.get("result") or {})
        result["lifecycle_state"] = _checkpoint_payload(state)
        update_workflow_job(interview, status="succeeded", current_node="completed", result=result)

    return {
        "status": "succeeded",
        "logs": _logs_with(
            state,
            "Workflow Orchestrator Agent",
            "Lifecycle graph completed and workflow checkpoint updated.",
            metadata={"checkpoint": result["lifecycle_state"]},
            event_type="success",
        ),
    }


lifecycle_checkpointer = MemorySaver() if MemorySaver is not None else None


def _interrupt_nodes(value: str) -> list[str] | None:
    nodes = [item.strip() for item in str(value or "").split(",") if item.strip()]
    return nodes or None


def _compile_interrupt_kwargs(before: str, after: str) -> dict[str, Any]:
    if not settings.langgraph_human_interrupts_enabled:
        return {}
    kwargs: dict[str, Any] = {}
    before_nodes = _interrupt_nodes(before)
    after_nodes = _interrupt_nodes(after)
    if before_nodes:
        kwargs["interrupt_before"] = before_nodes
    if after_nodes:
        kwargs["interrupt_after"] = after_nodes
    return kwargs


def build_lifecycle_artifact_subgraph():
    graph = StateGraph(LifecycleState)
    graph.add_node("report", _with_lifecycle_node("report", "Report Agent", report_node))
    graph.add_node("review_report", _with_lifecycle_node("review_report", "Reviewer Agent", review_report_node))
    graph.add_node("repair_report", _with_lifecycle_node("repair_report", "Reviewer Agent", repair_report_node))
    graph.add_node("roadmap", _with_lifecycle_node("roadmap", "Roadmap Agent", roadmap_node))
    graph.add_node("review_roadmap", _with_lifecycle_node("review_roadmap", "Reviewer Agent", review_roadmap_node))
    graph.add_node("repair_roadmap", _with_lifecycle_node("repair_roadmap", "Reviewer Agent", repair_roadmap_node))
    graph.add_node("write_memory", _with_lifecycle_node("write_memory", "Memory Curator Agent", write_memory_node))

    graph.add_edge(START, "report")
    graph.add_edge("report", "review_report")
    graph.add_conditional_edges(
        "review_report",
        route_after_report_review,
        {
            "accepted": "roadmap",
            "repair": "repair_report",
            "accepted_with_warnings": "roadmap",
        },
    )
    graph.add_edge("repair_report", "report")
    graph.add_edge("roadmap", "review_roadmap")
    graph.add_conditional_edges(
        "review_roadmap",
        route_after_roadmap_review,
        {
            "accepted": "write_memory",
            "repair": "repair_roadmap",
            "accepted_with_warnings": "write_memory",
        },
    )
    graph.add_edge("repair_roadmap", "roadmap")
    graph.add_edge("write_memory", END)
    return graph.compile(name="lifecycle_artifact_subgraph")


lifecycle_artifact_subgraph = build_lifecycle_artifact_subgraph()


def build_lifecycle_graph():
    graph = StateGraph(LifecycleState)
    graph.add_node(
        "collect_round_performance",
        _with_lifecycle_node("collect_round_performance", "Evaluation Agent", collect_round_performance_node),
    )
    graph.add_node(
        "retrieve_lifecycle_memory",
        _with_lifecycle_node("retrieve_lifecycle_memory", "Memory Agent", retrieve_lifecycle_memory_node),
    )
    graph.add_node(
        "final_evaluation",
        _with_lifecycle_node("final_evaluation", "Evaluation Agent", final_evaluation_node),
    )
    graph.add_node("lifecycle_artifacts", lifecycle_artifact_subgraph)
    graph.add_node(
        "complete_lifecycle",
        _with_lifecycle_node("complete_lifecycle", "Workflow Orchestrator Agent", complete_lifecycle_node),
    )

    graph.add_edge(START, "collect_round_performance")
    graph.add_edge("collect_round_performance", "retrieve_lifecycle_memory")
    graph.add_edge("retrieve_lifecycle_memory", "final_evaluation")
    graph.add_edge("final_evaluation", "lifecycle_artifacts")
    graph.add_edge("lifecycle_artifacts", "complete_lifecycle")
    graph.add_edge("complete_lifecycle", END)
    compile_kwargs = _compile_interrupt_kwargs(
        settings.langgraph_lifecycle_interrupt_before,
        settings.langgraph_lifecycle_interrupt_after,
    )
    if lifecycle_checkpointer is not None:
        return graph.compile(checkpointer=lifecycle_checkpointer, name="interview_lifecycle_graph", **compile_kwargs)
    return graph.compile(name="interview_lifecycle_graph", **compile_kwargs)


lifecycle_graph = build_lifecycle_graph()


async def run_interview_lifecycle(
    user_id: str,
    interview: dict[str, Any],
    dsa_submissions: list[dict[str, Any]],
    aptitude_result: dict[str, Any] | None,
    technical_answers: list[dict[str, Any]],
    hr_answers: list[dict[str, Any]],
) -> LifecycleState:
    graph_input = {
            "user_id": user_id,
            "interview": interview,
            "dsa_submissions": dsa_submissions,
            "aptitude_result": aptitude_result,
            "technical_answers": technical_answers,
            "hr_answers": hr_answers,
            "tool_decisions": [],
            "tool_results": [],
            "report_attempt": 0,
            "roadmap_attempt": 0,
            "max_lifecycle_review_attempts": _graph_limit(settings.langgraph_max_lifecycle_review_attempts, 2),
            "report_reflection_feedback": [],
            "roadmap_reflection_feedback": [],
            "lifecycle_reviewer_critiques": [],
            "memory_curation_decisions": [],
            "report_review_errors": [],
            "roadmap_review_errors": [],
            "lifecycle_security_state": {},
            "checkpoint_metadata": {},
            "skipped_memory_writes": [],
            "logs": [
                agent_event(
                    "Workflow Orchestrator Agent",
                    "Interview lifecycle graph started.",
                    "completed",
                )
            ],
            "status": "running",
        }
    graph_config = {
        "configurable": {"thread_id": f"interview-lifecycle:{interview.get('id', 'unknown')}"},
        "recursion_limit": _graph_limit(settings.langgraph_lifecycle_recursion_limit, 40, minimum=8),
    }
    if lifecycle_checkpointer is not None:
        graph_input["checkpoint_metadata"] = {
            "thread_id": graph_config["configurable"]["thread_id"],
            "checkpointer": "MemorySaver",
            "subgraphs": ["lifecycle_artifact_subgraph"],
            "human_interrupts_enabled": settings.langgraph_human_interrupts_enabled,
            "interrupt_before": _interrupt_nodes(settings.langgraph_lifecycle_interrupt_before) or [],
            "interrupt_after": _interrupt_nodes(settings.langgraph_lifecycle_interrupt_after) or [],
            "interrupt_safe_nodes": ["review_report", "review_roadmap", "write_memory"],
            "resume_hint": "Resume with the same thread_id through LangGraph checkpointer when future human-in-loop interrupts are enabled.",
        }
    return await lifecycle_graph.ainvoke(
        graph_input,
        config=graph_config,
    )
