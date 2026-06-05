from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any

from agents.blackboard import BlackboardEntry, blackboard_entry
from agents.interview_generator import (
    _dsa_topic_plan,
    _json_from_text,
    _normalize_aptitude,
    _normalize_dsa,
    _normalize_interview_questions,
    _repair_json_response,
    _section_prompt,
    _variation_seed,
)
from agents.reviewer_agent import review_section_generation_quality
from agents.tools.autonomous import execute_autonomous_tool_selection, execute_policy_tool_selection
from agents.tools.decision import ToolDecision, ToolExecutionRecord, tool_decision
from services.context_memory import rolling_summary
from services.llm import llm_service


SECTION_AGENT = {
    "dsa_problems": "DSA Agent",
    "aptitude_questions": "Aptitude Agent",
    "technical_questions": "Technical Interview Agent",
    "hr_questions": "HR Interview Agent",
}

SECTION_PROVIDER_AGENT = {
    "dsa_problems": "dsa",
    "aptitude_questions": "aptitude",
    "technical_questions": "technical",
    "hr_questions": "hr",
}

SECTION_EXPECTED_COUNT = {
    "dsa_problems": 3,
    "aptitude_questions": 5,
    "technical_questions": 5,
    "hr_questions": 8,
}


@dataclass
class SectionGenerationResult:
    section: str
    items: list[dict[str, Any]] = field(default_factory=list)
    logs: list[dict[str, Any]] = field(default_factory=list)
    tool_decisions: list[ToolDecision] = field(default_factory=list)
    tool_results: list[ToolExecutionRecord] = field(default_factory=list)
    blackboard_entries: list[BlackboardEntry] = field(default_factory=list)
    self_reviews: list[dict[str, Any]] = field(default_factory=list)
    attempts: int = 0
    provider: str = ""
    model: str = ""
    error: str = ""


def _section_query(section: str, profile: dict[str, Any], plan: dict[str, Any]) -> str:
    return " ".join(
        str(part)
        for part in [
            section,
            profile.get("target_role", ""),
            profile.get("inferred_domain", ""),
            " ".join(profile.get("skills", [])),
            plan.get("memory_strategy", ""),
            " ".join(plan.get("focus_topics", [])[:6]) if isinstance(plan.get("focus_topics"), list) else "",
        ]
        if part
    )


def _normalize_section(section: str, raw_items: Any, interview: dict[str, Any]) -> list[dict[str, Any]]:
    role = interview.get("target_role", "Software Engineer")
    difficulty = interview.get("difficulty", "medium")
    if section == "dsa_problems":
        topic_plan = _dsa_topic_plan(
            interview.get("company_style", "product"),
            difficulty,
            _variation_seed(interview, "dsa_problems"),
        )
        return _normalize_dsa(raw_items, interview["id"], difficulty, topic_plan)
    if section == "aptitude_questions":
        return _normalize_aptitude(raw_items, interview["id"], difficulty)
    if section == "technical_questions":
        return _normalize_interview_questions(raw_items, interview["id"], role, difficulty, 5, "technical")
    if section == "hr_questions":
        return _normalize_interview_questions(raw_items, interview["id"], role, difficulty, 8, "hr")
    return []


def _count_errors(section: str, items: list[dict[str, Any]]) -> list[str]:
    expected = SECTION_EXPECTED_COUNT[section]
    if len(items) != expected:
        return [f"{SECTION_AGENT[section]} must produce exactly {expected} item(s) for {section}."]
    return []


async def run_section_generation_agent(
    *,
    section: str,
    interview: dict[str, Any],
    candidate_profile: dict[str, Any],
    interview_plan: dict[str, Any],
    blackboard: list[dict[str, Any]],
    reflection_feedback: list[dict[str, Any]],
    max_attempts: int = 2,
    generation_profile: str = "deep",
) -> SectionGenerationResult:
    agent_name = SECTION_AGENT[section]
    provider_agent = SECTION_PROVIDER_AGENT[section]
    section_started = time.perf_counter()
    result = SectionGenerationResult(section=section)

    query = _section_query(section, candidate_profile, interview_plan)
    memory_enabled = interview.get("ai_memory_enabled") is not False
    fallback_decisions = [
        tool_decision(
            agent_name,
            "retrieve_memory_context",
            f"Retrieve section-specific memory before generating {section}.",
            {
                "user_id": candidate_profile.get("user_id") or interview.get("userId", ""),
                "query": query or section,
                "limit": 4,
                "memory_types": ["resume", "report", "transcript", "weakness", "evaluation", "roadmap", "generation"],
            },
            required=False,
        ),
        tool_decision(
            agent_name,
            "retrieve_generation_history",
            f"Retrieve previous generated questions before generating {section}.",
            {
                "user_id": candidate_profile.get("user_id") or interview.get("userId", ""),
                "limit": 3,
                "section": section,
            },
            required=False,
        ),
        tool_decision(
            agent_name,
            "retrieve_practice_history",
            f"Retrieve practice history signals before generating {section}.",
            {
                "user_id": candidate_profile.get("user_id") or interview.get("userId", ""),
                "limit": 3,
            },
            required=False,
        ),
    ] if memory_enabled else []
    available_tools = [
        "retrieve_memory_context",
        "retrieve_generation_history",
        "retrieve_practice_history",
    ] if memory_enabled else []
    if generation_profile == "fast":
        fast_tool_limit = 2 if section in {"dsa_problems", "aptitude_questions"} else 2
        tool_run = await execute_policy_tool_selection(
            agent=provider_agent,
            available_tools=available_tools,
            fallback_decisions=fallback_decisions,
            max_tool_calls=fast_tool_limit,
        )
    else:
        tool_run = await execute_autonomous_tool_selection(
            agent=provider_agent,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are the InterviewOS {agent_name}. Decide whether semantic memory is needed before "
                        f"generating {section}. Use no tool only if the plan/profile already has enough evidence."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Section: {section}\nQuery: {query}\n"
                        f"Candidate profile summary: {candidate_profile.get('resume_summary') or candidate_profile.get('resume_text_excerpt', '')}\n"
                        f"Skills: {candidate_profile.get('skills', [])}\n"
                        f"Interview plan focus: {interview_plan.get('focus_topics', [])}\n"
                        f"Recent blackboard summary: {rolling_summary(blackboard, limit=5)}"
                    ),
                },
            ],
            available_tools=available_tools,
            fallback_decisions=fallback_decisions,
        )
    result.tool_decisions.extend(tool_run.tool_decisions)
    result.tool_results.extend(tool_run.tool_results)

    section_memories = [
        memory
        for record in tool_run.tool_results
        if record.get("ok")
        for memory in record.get("data", {}).get("memories", [])
    ][:4]
    generation_history = [
        item
        for record in tool_run.tool_results
        if record.get("ok") and record.get("decision", {}).get("tool") == "retrieve_generation_history"
        for item in record.get("data", {}).get("history", [])
    ][:3]
    practice_history = [
        item
        for record in tool_run.tool_results
        if record.get("ok") and record.get("decision", {}).get("tool") == "retrieve_practice_history"
        for item in record.get("data", {}).get("sessions", [])
    ][:3]
    result.blackboard_entries.append(
        blackboard_entry(
            entry_type="tool_observation",
            agent=agent_name,
            summary=f"{agent_name} completed autonomous memory/tool selection before {section} generation.",
            decision=tool_run.provider_metadata.get("stopReason", ""),
            payload={
                "toolSelection": tool_run.provider_metadata,
                "memoryCount": len(section_memories),
                "generationHistoryCount": len(generation_history),
                "practiceHistoryCount": len(practice_history),
                "section": section,
            },
        )
    )

    section_feedback = list(reflection_feedback)
    for attempt in range(1, max(1, max_attempts) + 1):
        result.attempts = attempt
        section_interview = dict(interview)
        section_interview["_agentic_interview_plan"] = interview_plan
        section_interview["_agentic_generation_memory"] = section_memories
        if generation_profile == "deep":
            section_interview["_agentic_collaboration_transcript"] = [
                {"agent": item.get("agent"), "type": item.get("entry_type"), "summary": item.get("summary"), "decision": item.get("decision")}
                for item in blackboard[-10:]
                if isinstance(item, dict)
            ]
            section_interview["_agentic_generation_history"] = generation_history
            section_interview["_agentic_practice_history"] = practice_history
        if section_feedback:
            section_interview["_agentic_reflection_feedback"] = section_feedback
            section_interview["_agentic_repair_attempt"] = attempt

        response = await llm_service.invoke_live(_section_prompt(section_interview, section), agent=provider_agent)
        result.provider = response.provider
        result.model = response.model
        generation_error = ""
        try:
            payload = _json_from_text(response.content)
        except Exception as parse_error:
            try:
                payload = await _repair_json_response(response.content, parse_error, section, provider_agent)
            except Exception as repair_error:
                payload = {}
                generation_error = (
                    f"{type(parse_error).__name__}: {parse_error}; "
                    f"repair failed with {type(repair_error).__name__}: {repair_error}"
                )
        if not generation_error:
            try:
                items = _normalize_section(section, payload.get(section), interview)
            except Exception as normalize_error:
                items = []
                generation_error = f"{type(normalize_error).__name__}: {normalize_error}"
        else:
            items = []
        if generation_error:
            result.error = generation_error
            retrying = attempt < max(1, max_attempts)
            review = {
                "agent": "Reviewer Agent",
                "artifact": section,
                "accepted": False,
                "deterministicErrors": [generation_error],
                "qualityErrors": [],
                "repairInstructions": [
                    "Return only strict JSON with the exact requested top-level key and item count.",
                ],
                "summary": f"{agent_name} output could not be parsed or normalized on attempt {attempt}.",
                "provider": "deterministic-validator",
                "model": "local",
                "fallbackUsed": False,
            }
            result.self_reviews.append(review)
            result.blackboard_entries.append(
                blackboard_entry(
                    entry_type="critique",
                    agent=agent_name,
                    summary=review["summary"],
                    decision="repair_section" if retrying else "section_failed",
                    payload={"section": section, "attempt": attempt, "review": review},
                )
            )
            result.logs.append(
                {
                    "type": "warning" if retrying else "error",
                    "agent": agent_name,
                    "message": (
                        f"{agent_name} could not parse or validate {section} on attempt {attempt}; "
                        + ("requesting strict JSON repair." if retrying else "section generation failed.")
                    ),
                    "step": "form" if section == "dsa_problems" else provider_agent,
                    "metadata": {
                        "section": section,
                        "attempt": attempt,
                        "error": generation_error[:600],
                        "generation_profile": generation_profile,
                        "duration_ms": round((time.perf_counter() - section_started) * 1000, 2),
                    },
                }
            )
            if retrying:
                section_feedback = [
                    {
                        "agent": agent_name,
                        "section": section,
                        "attempt": attempt,
                        "validationErrors": [generation_error],
                        "qualityErrors": [],
                        "requiredCorrections": review["repairInstructions"],
                        "decision": "repair_section",
                    }
                ]
                continue
            return result

        result.error = ""
        deterministic_errors = _count_errors(section, items)
        if generation_profile == "fast" and not deterministic_errors and not section_feedback:
            review = {
                "agent": "Reviewer Agent",
                "artifact": section,
                "accepted": True,
                "deterministicErrors": [],
                "qualityErrors": [],
                "repairInstructions": [],
                "summary": f"Fast profile accepted {section} after deterministic count/schema validation.",
                "provider": "skipped",
                "model": "fast",
                "fallbackUsed": True,
            }
        else:
            review = await review_section_generation_quality(
                section=section,
                agent=agent_name,
                candidate_profile=candidate_profile,
                interview_plan=interview_plan,
                items=items,
                deterministic_errors=deterministic_errors,
                attempt=attempt,
            )
        result.self_reviews.append(review)
        result.blackboard_entries.append(
            blackboard_entry(
                entry_type="critique",
                agent=agent_name,
                summary=review.get("summary") or f"{agent_name} self-reviewed {section}.",
                decision=review.get("decision") or "",
                payload={"section": section, "attempt": attempt, "review": review},
            )
        )
        result.logs.append(
            {
                "type": "success" if review.get("accepted") else "warning",
                "agent": agent_name,
                "message": (
                    f"{agent_name} generated and self-reviewed {section} on attempt {attempt} "
                    f"with {response.provider} ({response.model})."
                ),
                "step": "form" if section == "dsa_problems" else provider_agent,
                "metadata": {
                    "section": section,
                    "attempt": attempt,
                    "accepted": review.get("accepted"),
                    "tool_decisions": len(tool_run.tool_decisions),
                    "memory_count": len(section_memories),
                    "generation_profile": generation_profile,
                    "duration_ms": round((time.perf_counter() - section_started) * 1000, 2),
                },
            }
        )
        result.items = items
        if review.get("accepted", not deterministic_errors):
            break
        section_feedback = [
            {
                "agent": agent_name,
                "section": section,
                "attempt": attempt,
                "validationErrors": deterministic_errors,
                "qualityErrors": review.get("qualityErrors", []),
                "requiredCorrections": review.get("repairInstructions", []),
                "decision": "repair_section",
            }
        ]

    return result
