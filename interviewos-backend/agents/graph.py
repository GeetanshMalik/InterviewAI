from __future__ import annotations

import asyncio
import inspect
import json
import time
from typing import Any

from langgraph.graph import END, START, StateGraph
try:
    from langgraph.checkpoint.memory import MemorySaver
except Exception:  # pragma: no cover - optional by installed LangGraph version
    MemorySaver = None

from agents.blackboard import append_blackboard, blackboard_entry, checkpoint_blackboard
from agents.generation_agent import run_section_generation_agent
from agents.interview_generator import _dsa_topic_plan, generate_interview_assets_with_llm
from agents.reviewer_agent import review_interview_generation_quality
from agents.security_agent import route_after_security, security_gatekeeper_node
from agents.state import (
    AgentWorkflowState,
    append_event,
    agent_event,
    build_candidate_profile_from_interview,
)
from agents.tools import default_tool_registry
from agents.tools.autonomous import execute_autonomous_tool_selection
from agents.tools.decision import tool_decision
from config import settings
from services.context_memory import compact_memory_items, rolling_summary
from services.llm import llm_service
from services.store import store
from services.workflow import append_workflow_event, update_workflow_job
from utils.parsers import json_from_text


def _public_logs(state: AgentWorkflowState) -> list[dict[str, str]]:
    return [
        {
            "type": event.get("type", "info"),
            "agent": event.get("agent", "Workflow Orchestrator Agent"),
            "message": event.get("message", "Workflow step completed."),
            "step": event.get("step", "form"),
            "metadata": event.get("metadata", {}),
        }
        for event in state.get("logs", [])
    ]


def _can_record_workflow(interview: dict[str, Any] | None) -> bool:
    interview_id = str((interview or {}).get("id") or "")
    return bool(interview_id and (interview_id in store.interviews or interview_id in store.workflow_jobs))


def _emit_live_workflow_event(
    state: AgentWorkflowState,
    agent: str,
    message: str,
    step: str = "form",
    event_type: str = "info",
    metadata: dict[str, Any] | None = None,
) -> None:
    interview = state.get("interview")
    if not _can_record_workflow(interview):
        return
    try:
        append_workflow_event(interview, event_type, message, step, metadata or {}, agent=agent, commit=False)
    except Exception:
        return


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


def _generation_profile_from(value: Any) -> str:
    profile = str(value or settings.workflow_generation_profile or "fast").strip().lower()
    return profile if profile in {"fast", "deep", "turbo"} else "fast"


def _generation_profile(state: AgentWorkflowState | None = None) -> str:
    interview = (state or {}).get("interview", {}) if isinstance(state, dict) else {}
    return _generation_profile_from((state or {}).get("generation_profile") or interview.get("generation_profile"))


def _is_fast_generation(state: AgentWorkflowState) -> bool:
    return _generation_profile(state) in {"fast", "turbo"}


def _skipped_generation_review(profile: str, deterministic_errors: list[str]) -> dict[str, Any]:
    return {
        "agent": "Reviewer Agent",
        "artifact": "interview_generation",
        "accepted": not deterministic_errors,
        "deterministicErrors": deterministic_errors,
        "qualityErrors": [],
        "repairInstructions": [],
        "summary": f"{profile} generation profile used deterministic validation without a live qualitative review.",
        "provider": "skipped",
        "model": profile,
        "fallbackUsed": True,
    }


def _with_node_lifecycle(node_name: str, agent: str, node_func):
    async def wrapped(state: AgentWorkflowState) -> dict[str, Any]:
        interview = state.get("interview")
        timeout_seconds = _graph_timeout(settings.workflow_graph_node_timeout_seconds, 120.0)
        started = time.perf_counter()
        if _can_record_workflow(interview):
            _emit_live_workflow_event(
                state,
                agent,
                f"{agent} started graph node {node_name}.",
                "form",
                metadata={"node": node_name, "phase": "start", "timeout_seconds": timeout_seconds},
            )
            update_workflow_job(interview, status="running", current_node=node_name, commit=False)

        async def call_node():
            result = node_func(state)
            if inspect.isawaitable(result):
                return await result
            return result

        try:
            result = await asyncio.wait_for(call_node(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            if _can_record_workflow(interview):
                _emit_live_workflow_event(
                    state,
                    agent,
                    f"{agent} graph node {node_name} timed out.",
                    "form",
                    "error",
                    {"node": node_name, "timeout_seconds": timeout_seconds},
                )
                update_workflow_job(
                    interview,
                    status="running",
                    current_node=node_name,
                    error=f"Graph node {node_name} exceeded {timeout_seconds} seconds.",
                    commit=False,
                )
            raise TimeoutError(f"Graph node {node_name} exceeded {timeout_seconds} seconds.") from exc
        except Exception as exc:
            if _can_record_workflow(interview):
                _emit_live_workflow_event(
                    state,
                    agent,
                    f"{agent} graph node {node_name} failed.",
                    "form",
                    "error",
                    {"node": node_name, "error": f"{type(exc).__name__}: {exc}"[:600]},
                )
                update_workflow_job(interview, status="running", current_node=node_name, commit=False)
            raise

        if _can_record_workflow(interview):
            _emit_live_workflow_event(
                state,
                agent,
                f"{agent} completed graph node {node_name}.",
                "form",
                "success",
                {
                    "node": node_name,
                    "phase": "end",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            update_workflow_job(interview, status="running", current_node=node_name, commit=False)
        return result

    return wrapped


def _ai_memory_enabled(interview: dict[str, Any] | None) -> bool:
    return not (isinstance(interview, dict) and interview.get("ai_memory_enabled") is False)


def _compact_profile_for_prompt(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": profile.get("user_id"),
        "target_role": profile.get("target_role"),
        "difficulty": profile.get("difficulty"),
        "company_style": profile.get("company_style"),
        "preferred_language": profile.get("preferred_language"),
        "skills": profile.get("skills", [])[:10],
        "inferred_domain": profile.get("inferred_domain"),
        "resume_summary": str(profile.get("resume_summary") or profile.get("resume_text_excerpt") or "")[:900],
        "job_description_summary": str(profile.get("job_description_summary") or profile.get("job_description") or "")[:800],
        "resume_snippets": profile.get("resume_snippets", [])[:5],
    }


def _compact_memory_state_for_prompt(memory_state: dict[str, Any], *, limit: int = 5) -> dict[str, Any]:
    return {
        "query": memory_state.get("query"),
        "memory_types": memory_state.get("memory_types", []),
        "notes": memory_state.get("notes", [])[:4],
        "retrieved": compact_memory_items(memory_state.get("retrieved", []), limit=limit, chars=360),
        "planner_tool_context": {
            "semantic_memory": compact_memory_items(
                (memory_state.get("planner_tool_context") or {}).get("semantic_memory", []),
                limit=limit,
                chars=320,
            ),
            "report_count": len((memory_state.get("planner_tool_context") or {}).get("reports", [])),
            "practice_count": len((memory_state.get("planner_tool_context") or {}).get("practice_sessions", [])),
            "generation_history_count": len((memory_state.get("planner_tool_context") or {}).get("generation_history", [])),
        }
        if isinstance(memory_state.get("planner_tool_context"), dict)
        else {},
    }


async def prepare_candidate_profile_node(state: AgentWorkflowState) -> dict[str, Any]:
    _emit_live_workflow_event(
        state,
        "Resume Agent",
        "Resume Agent is normalizing the candidate profile.",
        "form",
        metadata={"node": "prepare_candidate_profile"},
    )
    profile = build_candidate_profile_from_interview(state["interview"])
    return {
        "candidate_profile": profile,
        "logs": append_event(
            state,
            agent_event(
                "Resume Agent",
                "Structured candidate profile prepared for downstream agents.",
                "form",
                metadata={
                    "skills": profile.get("skills", []),
                    "domain": profile.get("inferred_domain"),
                },
            ),
        ),
    }


async def retrieve_memory_context_node(state: AgentWorkflowState) -> dict[str, Any]:
    if not _ai_memory_enabled(state.get("interview")):
        return {
            "memory_state": {
                "retrieved": [],
                "query": "",
                "memory_types": [],
                "notes": ["AI memory is disabled for this user."],
            },
            "logs": append_event(
                state,
                agent_event(
                    "Memory Agent",
                    "AI memory is disabled; skipping saved context retrieval.",
                    "form",
                    metadata={"memory_disabled": True},
                ),
            ),
        }

    _emit_live_workflow_event(
        state,
        "Memory Agent",
        "Memory Agent is retrieving prior resume, report, transcript, and weakness context.",
        "form",
        metadata={"node": "retrieve_memory_context", "tool": "retrieve_memory_context"},
    )
    profile = state.get("candidate_profile") or {}
    user_id = profile.get("user_id") or state["interview"].get("userId", "")
    query = " ".join(
        str(part)
        for part in [
            profile.get("target_role", ""),
            profile.get("inferred_domain", ""),
            " ".join(profile.get("skills", [])),
            state["interview"].get("difficulty", ""),
            state["interview"].get("company_style", ""),
        ]
        if part
    )
    memory_result = await default_tool_registry.arun(
        "retrieve_memory_context",
        user_id=user_id,
        query=query or "interview preparation",
        limit=6,
    )
    memories = memory_result.data.get("memories", []) if memory_result.ok else []
    return {
        "memory_state": {
            "retrieved": memories,
            "query": query,
            "memory_types": sorted({str(item.get("metadata", {}).get("memory_type", "unknown")) for item in memories}),
            "notes": [f"Retrieved {len(memories)} memory item(s) for interview generation."],
        },
        "logs": append_event(
            state,
            agent_event(
                "Memory Agent",
                f"Retrieved {len(memories)} relevant memory item(s) for agent planning.",
                "form",
                metadata={
                    "query": query,
                    "count": len(memories),
                    "tool": "retrieve_memory_context",
                    "tool_ok": memory_result.ok,
                    "tool_error": memory_result.error,
                },
            ),
        ),
    }


def _base_interview_plan(state: AgentWorkflowState) -> dict[str, Any]:
    profile = state.get("candidate_profile") or {}
    difficulty = str(profile.get("difficulty") or state["interview"].get("difficulty", "medium"))
    company_style = str(profile.get("company_style") or state["interview"].get("company_style", "product"))
    topic_plan = _dsa_topic_plan(company_style, difficulty)
    return {
        "target_role": str(profile.get("target_role") or "Software Engineer"),
        "difficulty": difficulty,
        "company_style": company_style,
        "round_order": ["dsa", "aptitude", "technical", "hr"],
        "strict_frontend_contract": True,
        "route_plan": {
            "required_sections": ["dsa", "aptitude", "technical", "hr"],
            "allowed_dynamic_controls": ["focus_topics", "difficulty_distribution", "review_depth"],
            "cannot_skip_sections": True,
        },
        "dsa_topic_plan": topic_plan,
        "difficulty_distribution": {
            "dsa": difficulty,
            "aptitude": difficulty,
            "technical": difficulty,
            "hr": "medium" if difficulty == "hard" else difficulty,
        },
        "technical_strategy": "Use resume, role, and earlier-round signals to test reasoning, tradeoffs, debugging, and implementation.",
        "hr_strategy": "Use STAR-style behavioral prompts, role motivation, ownership, and communication clarity.",
        "adaptation_rules": [
            "Prefer startup/product styles for arrays, strings, hash maps, queues, and linked-list style state.",
            "Prefer FAANG/enterprise hard styles for trees, graphs, dynamic programming, heaps, and systems constraints.",
            "Increase difficulty after strong evidence; reduce pressure after repeated unclear or passed answers.",
        ],
    }


def _merge_plan(base: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    plan = {**base}
    for key in [
        "target_role",
        "difficulty",
        "company_style",
        "round_order",
        "dsa_topic_plan",
        "difficulty_distribution",
        "technical_strategy",
        "hr_strategy",
        "adaptation_rules",
        "focus_topics",
        "candidate_summary",
        "memory_strategy",
        "route_plan",
        "review_depth",
        "strict_frontend_contract",
    ]:
        if key in payload and payload[key]:
            plan[key] = payload[key]
    return plan


async def planning_agent_propose_node(state: AgentWorkflowState) -> dict[str, Any]:
    _emit_live_workflow_event(
        state,
        "Planning Agent",
        "Planning Agent is grounding the interview strategy with tools and memory.",
        "form",
        metadata={"node": "planning_agent_propose"},
    )
    base = _base_interview_plan(state)
    profile = state.get("candidate_profile") or {}
    memory_state = state.get("memory_state") or {}
    compact_profile = _compact_profile_for_prompt(profile)
    compact_memory_state = _compact_memory_state_for_prompt(memory_state)
    prior_critiques = state.get("planning_critiques", [])
    debate_round = int(state.get("debate_round") or 0)
    if prior_critiques:
        debate_round += 1
    provider = "deterministic-planner"
    model = "local-planner-v1"
    plan = base
    user_id = profile.get("user_id") or state["interview"].get("userId", "")
    memory_enabled = _ai_memory_enabled(state.get("interview"))
    planning_query = " ".join(
        str(part)
        for part in [
            profile.get("target_role", ""),
            profile.get("inferred_domain", ""),
            " ".join(profile.get("skills", [])),
            state["interview"].get("difficulty", ""),
            state["interview"].get("company_style", ""),
            " ".join(str(item.get("recommendation", "")) for item in prior_critiques if isinstance(item, dict)),
        ]
        if part
    )
    fallback_decisions = [
        tool_decision(
            "Planning Agent",
            "retrieve_memory_context",
            "Ground the interview plan in semantic weakness, transcript, report, and roadmap memory.",
            {
                "user_id": user_id,
                "query": planning_query or "interview planning",
                "limit": 6,
                "memory_types": ["resume", "report", "transcript", "weakness", "evaluation", "roadmap"],
            },
            required=False,
        ),
        tool_decision(
            "Planning Agent",
            "retrieve_reports",
            "Review recent interview reports before proposing the next plan.",
            {"user_id": user_id, "limit": 3},
            required=False,
        ),
        tool_decision(
            "Planning Agent",
            "retrieve_practice_history",
            "Review practice history to avoid redundant planning and target persistent gaps.",
            {"user_id": user_id, "limit": 3},
            required=False,
        ),
        tool_decision(
            "Planning Agent",
            "retrieve_generation_history",
            "Review previous generated questions so the plan avoids repetition.",
            {"user_id": user_id, "limit": 3},
            required=False,
        ),
    ] if memory_enabled else []
    available_tools = [
        "retrieve_memory_context",
        "retrieve_reports",
        "retrieve_practice_history",
        "retrieve_generation_history",
    ] if memory_enabled else []
    tool_run = await execute_autonomous_tool_selection(
        agent="planning",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the InterviewOS Planning Agent. Decide which historical tools are needed before "
                    "planning. Use no tool only when the supplied profile and memory are already sufficient."
                ),
            },
            {
                        "role": "user",
                        "content": (
                            f"Planning query: {planning_query}\n"
                            f"Base plan: {json.dumps(base, ensure_ascii=False)}\n"
                            f"Candidate profile summary: {json.dumps(compact_profile, ensure_ascii=False)}\n"
                            f"Existing memory summary: {json.dumps(compact_memory_state, ensure_ascii=False)}\n"
                            f"Prior critic feedback summary: {json.dumps(rolling_summary(prior_critiques, limit=5), ensure_ascii=False)}\n"
                            f"User id for tool calls: {user_id}"
                        ),
                    },
        ],
        available_tools=available_tools,
        fallback_decisions=fallback_decisions,
        max_total_tool_calls=4,
    )
    planner_tool_context = {
        "tool_selection": tool_run.provider_metadata,
        "semantic_memory": [
            memory
            for record in tool_run.tool_results
            if record.get("ok") and record.get("decision", {}).get("tool") == "retrieve_memory_context"
            for memory in record.get("data", {}).get("memories", [])
        ][:6],
        "reports": [
            report
            for record in tool_run.tool_results
            if record.get("ok") and record.get("decision", {}).get("tool") == "retrieve_reports"
            for report in record.get("data", {}).get("reports", [])
        ][:3],
        "practice_sessions": [
            session
            for record in tool_run.tool_results
            if record.get("ok") and record.get("decision", {}).get("tool") == "retrieve_practice_history"
            for session in record.get("data", {}).get("sessions", [])
        ][:3],
        "generation_history": [
            item
            for record in tool_run.tool_results
            if record.get("ok") and record.get("decision", {}).get("tool") == "retrieve_generation_history"
            for item in record.get("data", {}).get("history", [])
        ][:3],
    }
    enriched_memory_state = {
        **memory_state,
        "planner_tool_context": planner_tool_context,
        "retrieved": [
            *memory_state.get("retrieved", []),
            *planner_tool_context["semantic_memory"],
        ],
        "memory_types": sorted(
            {
                *memory_state.get("memory_types", []),
                *[
                    str(item.get("metadata", {}).get("memory_type", "unknown"))
                    for item in planner_tool_context["semantic_memory"]
                ],
            }
        ),
    }
    planning_messages = [
        {
            "role": "system",
            "content": (
                "You are the InterviewOS Planning Agent. Propose a concrete interview plan from the "
                "candidate profile and retrieved memory. Return only JSON. Do not invent resume facts."
            ),
        },
        {
            "role": "user",
            "content": (
                "Return this JSON shape with concise values:\n"
                "{\n"
                '  "candidate_summary": "short evidence-grounded summary",\n'
                '  "round_order": ["dsa", "aptitude", "technical", "hr"],\n'
                '  "difficulty_distribution": {"dsa": "easy|medium|hard", "aptitude": "easy|medium|hard", "technical": "easy|medium|hard", "hr": "easy|medium|hard"},\n'
                '  "focus_topics": ["topic"],\n'
                '  "dsa_topic_plan": [{"slot": "problem 1", "topic": "topic", "reason": "why"}],\n'
                '  "technical_strategy": "strategy",\n'
                '  "hr_strategy": "strategy",\n'
                '  "memory_strategy": "how historical memory should shape questions",\n'
                '  "adaptation_rules": ["rule"]\n'
                "}\n\n"
                f"Base plan JSON: {json.dumps(base, ensure_ascii=False)}\n"
                f"Candidate profile JSON: {json.dumps(compact_profile, ensure_ascii=False)}\n"
                f"Retrieved memory JSON: {json.dumps(_compact_memory_state_for_prompt(enriched_memory_state), ensure_ascii=False)}\n"
                f"Planner autonomous tool context JSON: {json.dumps(_compact_memory_state_for_prompt({'planner_tool_context': planner_tool_context}), ensure_ascii=False)}\n"
                f"Prior critic feedback JSON: {json.dumps(rolling_summary(prior_critiques, limit=6), ensure_ascii=False)}\n"
                "Strict frontend contract: produce all required sections; do not skip DSA, aptitude, technical, or HR."
            ),
        },
    ]
    live_timeout = max(0.1, float(settings.planning_agent_live_timeout_seconds))
    fallback_reason = ""
    try:
        response = await asyncio.wait_for(
            llm_service.invoke_live(planning_messages, agent="planning"),
            timeout=live_timeout,
        )
        plan = _merge_plan(base, json_from_text(response.content))
        provider = response.provider
        model = response.model
    except Exception as exc:
        fallback_reason = f"{type(exc).__name__}: {exc}"[:600]
        memory_count = len(enriched_memory_state.get("retrieved", []))
        plan = {
            **base,
            "candidate_summary": (
                f"{profile.get('target_role', 'Candidate')} profile with {len(profile.get('skills', []))} skill signal(s) "
                f"and {memory_count} retrieved memory item(s)."
            ),
            "focus_topics": profile.get("skills", [])[:6] or [profile.get("inferred_domain", "general engineering")],
            "memory_strategy": "Use retrieved weaknesses and transcripts to avoid repeated shallow questioning.",
        }
        _emit_live_workflow_event(
            state,
            "Planning Agent",
            "Planning Agent live model was slow or unavailable; using deterministic interview planning.",
            "form",
            "warning",
            {
                "node": "planning_agent_propose",
                "fallback": "deterministic_planner",
                "timeout_seconds": live_timeout,
                "reason": fallback_reason,
            },
        )

    transcript_item = {
        "agent": "Planning Agent",
        "type": "proposal",
        "provider": provider,
        "model": model,
        "debateRound": debate_round,
        "plan": plan,
        "fallbackReason": fallback_reason or None,
    }
    return {
        "interview_plan": plan,
        "memory_state": enriched_memory_state,
        "debate_round": debate_round,
        "blackboard": append_blackboard(
            state,
            blackboard_entry(
                entry_type="proposal",
                agent="Planning Agent",
                summary="Planning Agent proposed an interview strategy from profile, memory, and critic feedback.",
                decision="propose_plan",
                payload={
                    "provider": provider,
                    "model": model,
                    "debateRound": debate_round,
                    "plan": plan,
                    "fallbackReason": fallback_reason or None,
                },
            ),
            blackboard_entry(
                entry_type="tool_observation",
                agent="Planning Agent",
                summary="Planning Agent completed autonomous tool selection before proposing the interview plan.",
                decision=tool_run.provider_metadata.get("stopReason", ""),
                payload={
                    "toolSelection": tool_run.provider_metadata,
                    "memoryCount": len(planner_tool_context["semantic_memory"]),
                    "reportCount": len(planner_tool_context["reports"]),
                    "practiceCount": len(planner_tool_context["practice_sessions"]),
                    "generationHistoryCount": len(planner_tool_context["generation_history"]),
                },
            ),
        ),
        "collaboration_transcript": [*state.get("collaboration_transcript", []), transcript_item],
        "tool_decisions": [*state.get("tool_decisions", []), *tool_run.tool_decisions],
        "tool_results": [*state.get("tool_results", []), *tool_run.tool_results],
        "logs": append_event(
            state,
            agent_event(
                "Planning Agent",
                "Planning Agent used deterministic interview planning after the live model was slow or unavailable."
                if fallback_reason
                else "Planning Agent proposed an interview strategy after autonomous memory/tool grounding.",
                "form",
                "warning" if fallback_reason else "info",
                metadata={
                    "provider": provider,
                    "model": model,
                    "round_order": plan.get("round_order", []),
                    "focus_topics": plan.get("focus_topics", []),
                    "tool_decisions": len(tool_run.tool_decisions),
                    "fallback_reason": fallback_reason or None,
                },
            ),
        ),
    }


def _deterministic_plan_critiques(
    plan: dict[str, Any],
    profile: dict[str, Any],
    memory_state: dict[str, Any],
) -> list[dict[str, Any]]:
    skills = [str(skill).lower() for skill in profile.get("skills", [])]
    memory_types = memory_state.get("memory_types", [])
    return [
        {
            "agent": "DSA Agent",
            "decision": "accept_with_change",
            "concern": "DSA plan must map problem topics to role/company style and avoid generic repeats.",
            "recommendation": (
                "Include hash-map/string or API-data manipulation tasks for product/startup roles."
                if plan.get("company_style") != "faang"
                else "Include at least one graph/tree/heap style task for FAANG-style depth."
            ),
            "provider": "deterministic-critic",
            "model": "local-fallback",
            "fallbackUsed": True,
        },
        {
            "agent": "Technical Interview Agent",
            "decision": "accept_with_change",
            "concern": "Technical questions need resume and job-description grounding.",
            "recommendation": (
                f"Prioritize tradeoff questions around {', '.join(profile.get('skills', [])[:4])}."
                if skills
                else "Prioritize system reasoning, debugging, validation, and implementation tradeoffs."
            ),
            "provider": "deterministic-critic",
            "model": "local-fallback",
            "fallbackUsed": True,
        },
        {
            "agent": "HR Interview Agent",
            "decision": "accept_with_change",
            "concern": "Behavioral questions need measurable outcomes and role motivation.",
            "recommendation": "Ask at least one STAR question requiring outcome metrics and one ownership/conflict question.",
            "provider": "deterministic-critic",
            "model": "local-fallback",
            "fallbackUsed": True,
        },
        {
            "agent": "Memory Agent",
            "decision": "accept" if memory_state.get("retrieved") else "accept_with_caution",
            "concern": "Historical memory should influence difficulty and avoid repeated weak patterns.",
            "recommendation": (
                f"Use retrieved memory types {memory_types} to target repeated weaknesses."
                if memory_state.get("retrieved")
                else "No memory retrieved; rely on resume/job evidence and write useful outcomes later."
            ),
            "provider": "deterministic-critic",
            "model": "local-fallback",
            "fallbackUsed": True,
        },
    ]


def _normalize_critic_payload(agent: str, payload: dict[str, Any], provider: str, model: str, fallback: bool) -> dict[str, Any]:
    decision = str(payload.get("decision") or "accept_with_change").strip().lower()
    if decision not in {"accept", "accept_with_change", "accept_with_caution", "reject"}:
        decision = "accept_with_change"
    return {
        "agent": agent,
        "decision": decision,
        "concern": str(payload.get("concern") or payload.get("summary") or "").strip()[:700],
        "recommendation": str(payload.get("recommendation") or "").strip()[:900],
        "provider": provider,
        "model": model,
        "fallbackUsed": fallback,
    }


def _critic_tool_records(tool_results: list[dict[str, Any]], tool_name: str, key: str, limit: int) -> list[dict[str, Any]]:
    return [
        item
        for record in tool_results
        if record.get("ok") and record.get("decision", {}).get("tool") == tool_name
        for item in record.get("data", {}).get(key, [])
    ][:limit]


async def _critic_tool_context(
    *,
    agent: str,
    plan: dict[str, Any],
    profile: dict[str, Any],
    memory_state: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    user_id = profile.get("user_id", "")
    query = " ".join(
        str(part)
        for part in [
            agent,
            profile.get("target_role", ""),
            profile.get("inferred_domain", ""),
            " ".join(profile.get("skills", [])),
            " ".join(plan.get("focus_topics", [])[:6]) if isinstance(plan.get("focus_topics"), list) else "",
            plan.get("memory_strategy", ""),
        ]
        if part
    )
    available_tools = ["retrieve_memory_context", "retrieve_reports", "retrieve_generation_history", "retrieve_practice_history"]
    if agent == "Memory Agent":
        available_tools = ["retrieve_memory_context", "retrieve_reports", "retrieve_roadmap"]

    section = None
    if agent == "DSA Agent":
        section = "dsa_problems"
    elif agent == "Technical Interview Agent":
        section = "technical_questions"
    elif agent == "HR Interview Agent":
        section = "hr_questions"

    fallback_decisions = [
        tool_decision(
            agent,
            "retrieve_memory_context",
            f"Ground {agent} critique in semantic memories relevant to this plan.",
            {
                "user_id": user_id,
                "query": query or "interview plan critique",
                "limit": 4,
                "memory_types": ["resume", "report", "transcript", "weakness", "evaluation", "roadmap", "practice"],
            },
            required=False,
        ),
        tool_decision(
            agent,
            "retrieve_reports",
            f"Ground {agent} critique in recent reports and scores.",
            {"user_id": user_id, "limit": 2},
            required=False,
        ),
    ]
    if "retrieve_generation_history" in available_tools:
        fallback_decisions.append(
            tool_decision(
                agent,
                "retrieve_generation_history",
                f"Check previous generated questions before {agent} approves the plan.",
                {"user_id": user_id, "limit": 2, "section": section},
                required=False,
            )
        )
    if "retrieve_practice_history" in available_tools:
        fallback_decisions.append(
            tool_decision(
                agent,
                "retrieve_practice_history",
                f"Check practice history before {agent} approves the plan.",
                {"user_id": user_id, "limit": 2},
                required=False,
            )
        )
    if "retrieve_roadmap" in available_tools:
        fallback_decisions.append(
            tool_decision(
                agent,
                "retrieve_roadmap",
                "Check active roadmap context before Memory Agent critiques the plan.",
                {"user_id": user_id, "active_only": True, "limit": 2},
                required=False,
            )
        )

    tool_run = await execute_autonomous_tool_selection(
        agent="evaluation",
        messages=[
            {
                "role": "system",
                "content": (
                    f"You are the InterviewOS {agent}. Decide which tools are needed before critiquing "
                    "the proposed interview plan from your domain."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Critique query: {query}\n"
                    f"Proposed plan: {json.dumps(plan, ensure_ascii=False)}\n"
                    f"Candidate profile summary: {json.dumps(_compact_profile_for_prompt(profile), ensure_ascii=False)}\n"
                    f"Existing memory summary: {json.dumps(_compact_memory_state_for_prompt(memory_state), ensure_ascii=False)}"
                )[:10000],
            },
        ],
        available_tools=available_tools,
        fallback_decisions=fallback_decisions,
        max_total_tool_calls=3,
    )
    context = {
        "tool_selection": tool_run.provider_metadata,
        "semantic_memory": _critic_tool_records(tool_run.tool_results, "retrieve_memory_context", "memories", 4),
        "historical_reports": _critic_tool_records(tool_run.tool_results, "retrieve_reports", "reports", 2),
        "generation_history": _critic_tool_records(tool_run.tool_results, "retrieve_generation_history", "history", 2),
        "practice_sessions": _critic_tool_records(tool_run.tool_results, "retrieve_practice_history", "sessions", 2),
        "roadmaps": _critic_tool_records(tool_run.tool_results, "retrieve_roadmap", "roadmaps", 2),
    }
    return context, tool_run.tool_decisions, tool_run.tool_results


async def _llm_plan_critique(
    *,
    agent: str,
    plan: dict[str, Any],
    profile: dict[str, Any],
    memory_state: dict[str, Any],
    fallback: dict[str, Any],
) -> dict[str, Any]:
    tool_context, tool_decisions, tool_results = await _critic_tool_context(
        agent=agent,
        plan=plan,
        profile=profile,
        memory_state=memory_state,
    )
    try:
        response = await asyncio.wait_for(
            llm_service.invoke_live(
                [
                    {
                        "role": "system",
                        "content": (
                            f"You are the InterviewOS {agent}. Critique the proposed interview plan only from your domain. "
                            "Return only JSON with decision, concern, recommendation. Allowed decisions: "
                            "accept, accept_with_change, accept_with_caution, reject. Do not include hidden reasoning."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                        {
                            "candidateProfile": _compact_profile_for_prompt(profile),
                            "retrievedMemory": _compact_memory_state_for_prompt(memory_state),
                            "criticToolContext": tool_context,
                            "proposedPlan": plan,
                            "strictFrontendContract": "All four sections must remain present.",
                            },
                            ensure_ascii=False,
                        )[:14000],
                    },
                ],
                agent="evaluation",
            ),
            timeout=5.0,
        )
        payload = json_from_text(response.content, root_error="Critic response must be a JSON object.")
        critique = _normalize_critic_payload(agent, payload, response.provider, response.model, False)
    except Exception as exc:
        critique = dict(fallback)
        critique["fallbackReason"] = f"{type(exc).__name__}: {exc}"
    critique["toolContext"] = {
        "toolSelection": tool_context.get("tool_selection", {}),
        "semanticMemoryCount": len(tool_context.get("semantic_memory", [])),
        "historicalReportCount": len(tool_context.get("historical_reports", [])),
        "generationHistoryCount": len(tool_context.get("generation_history", [])),
        "practiceSessionCount": len(tool_context.get("practice_sessions", [])),
        "roadmapCount": len(tool_context.get("roadmaps", [])),
    }
    critique["toolDecisions"] = tool_decisions
    critique["toolResults"] = tool_results
    return critique


async def critic_agents_review_plan_node(state: AgentWorkflowState) -> dict[str, Any]:
    _emit_live_workflow_event(
        state,
        "Workflow Orchestrator Agent",
        "DSA, Technical, HR, and Memory critic agents are reviewing the plan in parallel.",
        "form",
        metadata={"node": "critic_agents_review_plan"},
    )
    plan = state.get("interview_plan") or {}
    profile = state.get("candidate_profile") or {}
    memory_state = state.get("memory_state") or {}
    fallback_critiques = _deterministic_plan_critiques(plan, profile, memory_state)
    critiques = await asyncio.gather(
        *[
            _llm_plan_critique(
                agent=str(fallback["agent"]),
                plan=plan,
                profile=profile,
                memory_state=memory_state,
                fallback=fallback,
            )
            for fallback in fallback_critiques
        ]
    )
    critic_tool_decisions = [
        decision
        for critique in critiques
        for decision in critique.get("toolDecisions", [])
    ]
    critic_tool_results = [
        record
        for critique in critiques
        for record in critique.get("toolResults", [])
    ]
    public_critiques = [
        {key: value for key, value in critique.items() if key not in {"toolDecisions", "toolResults"}}
        for critique in critiques
    ]
    blackboard_entries = [
        blackboard_entry(
            entry_type="critique",
            agent=str(critique.get("agent", "Critic Agent")),
            summary=str(critique.get("concern") or "Critic reviewed the plan."),
            decision=str(critique.get("decision") or ""),
            payload={
                "recommendation": critique.get("recommendation"),
                "provider": critique.get("provider"),
                "model": critique.get("model"),
                "fallbackUsed": critique.get("fallbackUsed"),
                "toolContext": critique.get("toolContext", {}),
            },
        )
        for critique in public_critiques
    ]
    return {
        "planning_critiques": public_critiques,
        "blackboard": append_blackboard(state, *blackboard_entries),
        "tool_decisions": [*state.get("tool_decisions", []), *critic_tool_decisions],
        "tool_results": [*state.get("tool_results", []), *critic_tool_results],
        "collaboration_transcript": [
            *state.get("collaboration_transcript", []),
            {"type": "critique_round", "debateRound": state.get("debate_round", 0), "critiques": public_critiques},
        ],
        "logs": append_event(
            state,
            agent_event(
                "Workflow Orchestrator Agent",
                "DSA, Technical, HR, and Memory agents critiqued the proposed interview plan.",
                "form",
                metadata={
                    "critic_count": len(critiques),
                    "llm_critics": sum(1 for critique in critiques if not critique.get("fallbackUsed")),
                    "fallback_critics": sum(1 for critique in critiques if critique.get("fallbackUsed")),
                    "tool_decisions": len(critic_tool_decisions),
                },
            ),
        ),
    }


def route_after_plan_critique(state: AgentWorkflowState) -> str:
    debate_round = int(state.get("debate_round") or 0)
    max_rounds = int(state.get("max_debate_rounds") or 2)
    decisions = {str(item.get("decision", "")).lower() for item in state.get("planning_critiques", [])}
    if debate_round < max_rounds and "reject" in decisions:
        return "debate"
    return "revise"


async def orchestrator_revise_plan_node(state: AgentWorkflowState) -> dict[str, Any]:
    _emit_live_workflow_event(
        state,
        "Workflow Orchestrator Agent",
        "Workflow Orchestrator Agent is synthesizing critic feedback into the final plan.",
        "form",
        metadata={"node": "orchestrator_revise_plan"},
    )
    plan = dict(state.get("interview_plan") or {})
    critiques = state.get("planning_critiques", [])
    accepted = []
    adaptation_rules = list(plan.get("adaptation_rules", []))
    for critique in critiques:
        recommendation = str(critique.get("recommendation", "")).strip()
        if not recommendation:
            continue
        accepted.append({"agent": critique.get("agent"), "recommendation": recommendation})
        if recommendation not in adaptation_rules:
            adaptation_rules.append(recommendation)

    provider = "deterministic-orchestrator"
    model = "local-fallback"
    replan_required = False
    forced_resolution = int(state.get("debate_round") or 0) >= int(state.get("max_debate_rounds") or 2)
    try:
        response = await llm_service.invoke_live(
            [
                {
                    "role": "system",
                    "content": (
                        "You are the InterviewOS Workflow Orchestrator Agent. Synthesize the final plan after "
                        "multi-agent debate. Return only JSON. Preserve the strict frontend contract: all four "
                        "sections must exist. You may request one bounded replan only if unresolved contradictions "
                        "would harm generation quality. Do not include hidden reasoning."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "currentPlan": plan,
                            "critiques": rolling_summary(critiques, limit=8),
                            "blackboard": rolling_summary(checkpoint_blackboard(state), limit=10),
                            "acceptedRecommendations": accepted,
                            "strictFrontendContract": {
                                "requiredSections": ["dsa", "aptitude", "technical", "hr"],
                                "counts": {"dsa": 3, "aptitude": 5, "technical": 5, "hr": 8},
                            },
                            "replanBudgetRemaining": int(state.get("max_orchestrator_replans") or 1)
                            - int(state.get("orchestrator_replan_count") or 0),
                        },
                        ensure_ascii=False,
                    )[:16000],
                },
            ],
            agent="evaluation",
        )
        payload = json_from_text(response.content, root_error="Orchestrator response must be a JSON object.")
        if isinstance(payload.get("adaptation_rules"), list):
            adaptation_rules = [str(item) for item in payload["adaptation_rules"] if str(item).strip()]
        if isinstance(payload.get("accepted_critic_recommendations"), list):
            accepted = payload["accepted_critic_recommendations"]
        if isinstance(payload.get("generation_strategy_by_section"), dict):
            plan["generation_strategy_by_section"] = payload["generation_strategy_by_section"]
        if isinstance(payload.get("route_plan"), dict):
            plan["route_plan"] = {**dict(plan.get("route_plan") or {}), **payload["route_plan"]}
        if payload.get("review_depth"):
            plan["review_depth"] = payload.get("review_depth")
        if payload.get("orchestrator_summary"):
            plan["orchestrator_summary"] = str(payload.get("orchestrator_summary"))[:900]
        replan_required = bool(payload.get("replan_required"))
        provider = response.provider
        model = response.model
    except Exception as exc:
        plan["orchestrator_summary"] = f"Deterministic fallback synthesized the plan after Orchestrator LLM failed: {type(exc).__name__}."

    plan["adaptation_rules"] = adaptation_rules[:12]
    plan["accepted_critic_recommendations"] = accepted
    plan["collaboration_status"] = "revised_after_reasoning_orchestrator"
    plan["round_order"] = ["dsa", "aptitude", "technical", "hr"]
    plan["strict_frontend_contract"] = True
    plan["route_plan"] = {
        **dict(plan.get("route_plan") or {}),
        "required_sections": ["dsa", "aptitude", "technical", "hr"],
        "cannot_skip_sections": True,
        "dynamic_controls": ["focus_topics", "difficulty_distribution", "generation_strategy_by_section", "review_depth"],
    }
    replan_count = int(state.get("orchestrator_replan_count") or 0)
    max_replans = int(state.get("max_orchestrator_replans") or 1)
    has_reject = any(str(critique.get("decision", "")).lower() == "reject" for critique in critiques)
    if replan_required and has_reject and replan_count < max_replans and not forced_resolution:
        replan_count += 1
        plan["orchestrator_replan_requested"] = True
    else:
        plan["orchestrator_replan_requested"] = False
    return {
        "interview_plan": plan,
        "orchestrator_replan_count": replan_count,
        "blackboard": append_blackboard(
            state,
            blackboard_entry(
                entry_type="revision",
                agent="Workflow Orchestrator Agent",
                summary=plan.get("orchestrator_summary") or "Orchestrator synthesized the plan after critic debate.",
                decision="request_replan" if plan["orchestrator_replan_requested"] else "finalize_plan",
                payload={
                    "accepted": accepted,
                    "provider": provider,
                    "model": model,
                    "debateRound": state.get("debate_round", 0),
                    "forcedResolution": forced_resolution,
                    "replanRequired": replan_required,
                    "replanCount": replan_count,
                },
            ),
        ),
        "collaboration_transcript": [
            *state.get("collaboration_transcript", []),
            {
                "agent": "Workflow Orchestrator Agent",
                "type": "revision",
                "accepted": accepted,
                "revised_plan": plan,
            },
        ],
        "logs": append_event(
            state,
            agent_event(
                "Workflow Orchestrator Agent",
                "Reasoning Orchestrator synthesized the interview plan after multi-agent critique.",
                "form",
                metadata={
                    "accepted_recommendations": len(accepted),
                    "provider": provider,
                    "model": model,
                    "replan_requested": plan["orchestrator_replan_requested"],
                    "replan_count": replan_count,
                },
            ),
        ),
    }


def route_after_orchestrator(state: AgentWorkflowState) -> str:
    plan = state.get("interview_plan") or {}
    if plan.get("orchestrator_replan_requested"):
        return "replan"
    return "generate"


def route_after_orchestrator_subgraph(state: AgentWorkflowState) -> str:
    return "replan" if route_after_orchestrator(state) == "replan" else "done"


def _planned_section_names(state: AgentWorkflowState) -> list[str]:
    plan = state.get("interview_plan") or {}
    interview = state.get("interview") or {}
    route_plan = plan.get("route_plan") if isinstance(plan.get("route_plan"), dict) else {}
    explicit_rounds = interview.get("enabled_rounds") or interview.get("rounds") or route_plan.get("required_sections")
    section_map = {
        "dsa": "dsa_problems",
        "coding": "dsa_problems",
        "dsa_problems": "dsa_problems",
        "aptitude": "aptitude_questions",
        "aptitude_questions": "aptitude_questions",
        "technical": "technical_questions",
        "technical_questions": "technical_questions",
        "hr": "hr_questions",
        "behavioral": "hr_questions",
        "hr_questions": "hr_questions",
    }
    default_sections = ["dsa_problems", "aptitude_questions", "technical_questions", "hr_questions"]
    if not isinstance(explicit_rounds, list) or not explicit_rounds:
        return default_sections
    selected: list[str] = []
    for item in explicit_rounds:
        section = section_map.get(str(item).strip().lower())
        if section and section not in selected:
            selected.append(section)
    if plan.get("strict_frontend_contract", True) or route_plan.get("cannot_skip_sections", True):
        return default_sections
    return selected or default_sections


async def generate_assets_node(state: AgentWorkflowState) -> dict[str, Any]:
    section_names = _planned_section_names(state)
    generation_profile = _generation_profile(state)
    _emit_live_workflow_event(
        state,
        "Workflow Orchestrator Agent",
        "Required round agents are queued for provider-aware asset generation.",
        "form",
        metadata={
            "node": "generate_assets",
            "sections": section_names,
            "max_concurrent_sections": int(settings.agent_generation_max_concurrent_sections),
            "generation_profile": generation_profile,
        },
    )
    for agent_name, section in [
        ("DSA Agent", "dsa_problems"),
        ("Aptitude Agent", "aptitude_questions"),
        ("Technical Interview Agent", "technical_questions"),
        ("HR Interview Agent", "hr_questions"),
    ]:
        if section not in section_names:
            continue
        _emit_live_workflow_event(
            state,
            agent_name,
            f"{agent_name} queued tool and memory grounded generation for {section}.",
            "form",
            metadata={"node": "generate_assets", "section": section},
        )
    attempt = int(state.get("generation_attempt") or 0) + 1
    generation_interview = dict(state["interview"])
    if state.get("interview_plan"):
        generation_interview["_agentic_interview_plan"] = state.get("interview_plan", {})
    if generation_profile == "deep" and state.get("collaboration_transcript"):
        generation_interview["_agentic_collaboration_transcript"] = state.get("collaboration_transcript", [])[-6:]
    if state.get("reflection_feedback"):
        generation_interview["_agentic_reflection_feedback"] = state.get("reflection_feedback", [])
        generation_interview["_agentic_repair_attempt"] = attempt

    if generation_profile == "turbo":
        started = time.perf_counter()
        result = await generate_interview_assets_with_llm(generation_interview)
        generated_logs = [
            agent_event(
                str(log.get("agent", "Workflow Orchestrator Agent")),
                str(log.get("message", "Turbo generation step completed.")),
                str(log.get("step", "form")),
                str(log.get("type", "info")) if str(log.get("type", "info")) in {"info", "success", "warning", "error"} else "info",
                dict(log.get("metadata") or {}),
            )
            for log in result.get("logs", [])
        ]
        _emit_live_workflow_event(
            state,
            "Workflow Orchestrator Agent",
            "Turbo profile generated the full interview package with the single-call generator.",
            "form",
            "success",
            {
                "node": "generate_assets",
                "generation_profile": generation_profile,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return {
            "generation_attempt": attempt,
            "section_generation_reviews": [
                *state.get("section_generation_reviews", []),
                {
                    "section": "all_sections",
                    "attempts": 1,
                    "reviews": [
                        {
                            "accepted": True,
                            "fallbackUsed": True,
                            "summary": "Turbo profile used the single-call package generator.",
                            "provider": result.get("provider", "single-call"),
                        }
                    ],
                },
            ],
            "section_generation_attempts": {
                **dict(state.get("section_generation_attempts") or {}),
                **{section: 1 for section in section_names},
            },
            "tool_decisions": state.get("tool_decisions", []),
            "tool_results": state.get("tool_results", []),
            "blackboard": append_blackboard(
                state,
                blackboard_entry(
                    entry_type="decision",
                    agent="Workflow Orchestrator Agent",
                    summary="Turbo profile used the single-call generator instead of section agents.",
                    decision="turbo_single_call_generation",
                    payload={"generationProfile": generation_profile, "sections": section_names},
                ),
            ),
            "question_set": {
                "dsa_problems": result.get("dsa_problems", []),
                "aptitude_questions": result.get("aptitude_questions", []),
                "technical_questions": result.get("technical_questions", []),
                "hr_questions": result.get("hr_questions", []),
            },
            "logs": [
                *state.get("logs", []),
                agent_event(
                    "Workflow Orchestrator Agent",
                    f"Interview asset generation attempt {attempt} started.",
                    "form",
                    metadata={"attempt": attempt, "repair": bool(state.get("reflection_feedback")), "generation_profile": generation_profile},
                ),
                *generated_logs,
                agent_event(
                    "Workflow Orchestrator Agent",
                    f"Interview assets generated by turbo profile on attempt {attempt}.",
                    "form",
                    "success",
                    {"attempt": attempt, "generation_profile": generation_profile},
                ),
            ],
        }

    try:
        section_agents = {
            "dsa_problems": "DSA Agent",
            "aptitude_questions": "Aptitude Agent",
            "technical_questions": "Technical Interview Agent",
            "hr_questions": "HR Interview Agent",
        }
        section_semaphore = asyncio.Semaphore(max(1, int(settings.agent_generation_max_concurrent_sections)))
        section_max_attempts = 2 if generation_profile in {"fast", "deep"} or state.get("reflection_feedback") else 1

        async def run_scheduled_section(section: str):
            async with section_semaphore:
                return await asyncio.wait_for(
                    run_section_generation_agent(
                        section=section,
                        interview=generation_interview,
                        candidate_profile=state.get("candidate_profile") or {},
                        interview_plan=state.get("interview_plan") or {},
                        blackboard=state.get("blackboard", []),
                        reflection_feedback=state.get("reflection_feedback", []),
                        max_attempts=section_max_attempts,
                        generation_profile=generation_profile,
                    ),
                    timeout=_graph_timeout(settings.agent_section_generation_timeout_seconds, 90.0),
                )

        raw_section_results = await asyncio.gather(
            *[run_scheduled_section(section) for section in section_names],
            return_exceptions=True,
        )
        section_results = []
        section_errors: dict[str, str] = {}
        for section, outcome in zip(section_names, raw_section_results):
            if isinstance(outcome, Exception):
                error = f"{type(outcome).__name__}: {outcome}"
                section_errors[section] = error
                _emit_live_workflow_event(
                    state,
                    section_agents[section],
                    f"{section_agents[section]} live generation failed; no fallback questions will be generated.",
                    "form",
                    "error",
                    {"node": "generate_assets", "section": section, "error": error[:600]},
                )
            elif getattr(outcome, "error", ""):
                error = str(outcome.error)
                section_errors[section] = error
                _emit_live_workflow_event(
                    state,
                    section_agents[section],
                    f"{section_agents[section]} needs a strict JSON repair for {section}.",
                    "form",
                    "warning",
                    {"node": "generate_assets", "section": section, "error": error[:600]},
                )
            else:
                section_results.append(outcome)
                _emit_live_workflow_event(
                    state,
                    section_agents[section],
                    f"{section_agents[section]} completed {len(outcome.items)} item(s) for {section}.",
                    "form",
                    "success",
                    {
                        "node": "generate_assets",
                        "section": section,
                        "attempts": outcome.attempts,
                        "provider": outcome.provider,
                        "model": outcome.model,
                    },
                )

        all_section_results = [
            outcome for outcome in raw_section_results if not isinstance(outcome, Exception)
        ]
        result = {section_result.section: section_result.items for section_result in section_results}
        generated_logs = [
            agent_event(
                str(log.get("agent", "Workflow Orchestrator Agent")),
                str(log.get("message", "Agent generation step completed.")),
                str(log.get("step", "form")),
                str(log.get("type", "info")) if str(log.get("type", "info")) in {"info", "success", "warning", "error"} else "info",
                dict(log.get("metadata") or {}),
            )
            for section_result in all_section_results
            for log in section_result.logs
        ]
        section_error_messages = [
            f"{section_agents[section]} failed to generate {section}: {error}"
            for section, error in section_errors.items()
        ]
        if section_errors:
            _emit_live_workflow_event(
                state,
                "Workflow Orchestrator Agent",
                f"Live interview generation needs repair for {len(section_errors)} section(s).",
                "form",
                "warning",
                {"node": "generate_assets", "sections": list(section_errors.keys()), "errors": section_errors},
            )
        section_blackboard = [
            entry
            for section_result in all_section_results
            for entry in section_result.blackboard_entries
        ]
        section_tool_decisions = [
            decision
            for section_result in all_section_results
            for decision in section_result.tool_decisions
        ]
        section_tool_results = [
            record
            for section_result in all_section_results
            for record in section_result.tool_results
        ]
        section_reviews = [
            {"section": section_result.section, "attempts": section_result.attempts, "reviews": section_result.self_reviews}
            for section_result in all_section_results
        ]
        section_attempts = {section_result.section: section_result.attempts for section_result in all_section_results}
    except Exception as exc:
        _emit_live_workflow_event(
            state,
            "Workflow Orchestrator Agent",
            "Autonomous section generation failed. No fallback questions were generated.",
            "form",
            "error",
            {"node": "generate_assets", "error": f"{type(exc).__name__}: {exc}"[:600]},
        )
        raise RuntimeError(
            "Live interview generation failed; no fallback questions were generated. "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    return {
        "generation_attempt": attempt,
        "section_generation_reviews": [*state.get("section_generation_reviews", []), *section_reviews],
        "section_generation_attempts": {
            **dict(state.get("section_generation_attempts") or {}),
            **section_attempts,
        },
        "tool_decisions": [*state.get("tool_decisions", []), *section_tool_decisions],
        "tool_results": [*state.get("tool_results", []), *section_tool_results],
        "blackboard": append_blackboard(state, *section_blackboard),
        "validation_errors": section_error_messages,
        "error": " ".join(section_error_messages),
        "question_set": {
            "dsa_problems": result.get("dsa_problems", []),
            "aptitude_questions": result.get("aptitude_questions", []),
            "technical_questions": result.get("technical_questions", []),
            "hr_questions": result.get("hr_questions", []),
        },
        "logs": [
            *state.get("logs", []),
            agent_event(
                "Workflow Orchestrator Agent",
                f"Interview asset generation attempt {attempt} started.",
                "form",
                metadata={
                    "attempt": attempt,
                    "repair": bool(state.get("reflection_feedback")),
                    "generation_profile": generation_profile,
                },
            ),
            *generated_logs,
            agent_event(
                "Workflow Orchestrator Agent",
                (
                    f"Interview assets generated by section agents on attempt {attempt}."
                    if not section_errors
                    else f"Interview asset generation attempt {attempt} produced repairable section errors."
                ),
                "form",
                "success" if not section_errors else "warning",
                {"attempt": attempt, "generation_profile": generation_profile, "section_errors": list(section_errors.keys())},
            ),
        ],
    }


async def validate_assets_node(state: AgentWorkflowState) -> dict[str, Any]:
    _emit_live_workflow_event(
        state,
        "Reviewer Agent",
        "Reviewer Agent is validating generated assets and deciding whether repair is needed.",
        "form",
        metadata={"node": "validate_assets"},
    )
    question_set = state.get("question_set") or {}
    expected_sections = set(_planned_section_names(state))
    errors = [str(error) for error in state.get("validation_errors", []) if str(error).strip()]
    if "dsa_problems" in expected_sections and len(question_set.get("dsa_problems", [])) != 3:
        errors.append("DSA Agent must produce exactly 3 problems.")
    if "aptitude_questions" in expected_sections and len(question_set.get("aptitude_questions", [])) != 5:
        errors.append("Aptitude Agent must produce exactly 5 questions.")
    if "technical_questions" in expected_sections and len(question_set.get("technical_questions", [])) != 5:
        errors.append("Technical Interview Agent must produce exactly 5 questions.")
    if "hr_questions" in expected_sections and len(question_set.get("hr_questions", [])) != 8:
        errors.append("HR Interview Agent must produce exactly 8 questions.")

    generation_profile = _generation_profile(state)
    needs_live_review = generation_profile == "deep" or bool(errors) or bool(state.get("reflection_feedback"))
    if needs_live_review:
        qualitative_review = await review_interview_generation_quality(
            candidate_profile=state.get("candidate_profile") or {},
            interview_plan=state.get("interview_plan") or {},
            question_set=question_set,
            deterministic_errors=errors,
            attempt=int(state.get("generation_attempt") or 0),
        )
    else:
        qualitative_review = _skipped_generation_review(generation_profile, errors)
    quality_errors = [
        f"Qualitative Reviewer: {error}"
        for error in qualitative_review.get("qualityErrors", [])
        if str(error).strip()
    ]
    if not qualitative_review.get("accepted", not quality_errors) and not quality_errors and not errors:
        quality_errors.append("Qualitative Reviewer rejected the generated assets without a specific error.")
    if not qualitative_review.get("accepted", not quality_errors):
        errors = [*errors, *quality_errors]

    if errors:
        return {
            "validation_errors": errors,
            "error": " ".join(errors),
            "reviewer_critiques": [*state.get("reviewer_critiques", []), qualitative_review],
            "blackboard": append_blackboard(
                state,
                blackboard_entry(
                    entry_type="critique",
                    agent="Reviewer Agent",
                    summary=qualitative_review.get("summary") or "Reviewer rejected generated interview assets.",
                    decision="repair_generation",
                    payload=qualitative_review,
                ),
            ),
            "logs": append_event(
                state,
                agent_event(
                    "Workflow Orchestrator Agent",
                    "Interview asset validation failed.",
                    "form",
                    "error",
                    {
                        "errors": errors,
                        "reviewer_provider": qualitative_review.get("provider"),
                        "reviewer_fallback": qualitative_review.get("fallbackUsed"),
                        "generation_profile": generation_profile,
                    },
                ),
            ),
        }

    return {
        "validation_errors": [],
        "error": "",
        "reviewer_critiques": [*state.get("reviewer_critiques", []), qualitative_review],
        "blackboard": append_blackboard(
            state,
            blackboard_entry(
                entry_type="critique",
                agent="Reviewer Agent",
                summary=qualitative_review.get("summary") or "Reviewer accepted generated interview assets.",
                decision="accept_generation",
                payload=qualitative_review,
            ),
        ),
        "logs": append_event(
            state,
            agent_event(
                "Workflow Orchestrator Agent",
                "Interview assets passed graph validation.",
                "form",
                "success",
                {
                    "reviewer_provider": qualitative_review.get("provider"),
                    "reviewer_fallback": qualitative_review.get("fallbackUsed"),
                    "generation_profile": generation_profile,
                },
            ),
        ),
    }


def route_after_validation(state: AgentWorkflowState) -> str:
    if not state.get("validation_errors"):
        return "finish"
    attempt = int(state.get("generation_attempt") or 0)
    max_attempts = int(state.get("max_generation_attempts") or 2)
    return "repair" if attempt < max_attempts else "fail"


def _section_from_error(error: str) -> str:
    lowered = error.lower()
    if "dsa" in lowered:
        return "dsa_problems"
    if "aptitude" in lowered:
        return "aptitude_questions"
    if "technical" in lowered:
        return "technical_questions"
    if "hr" in lowered:
        return "hr_questions"
    return "all_sections"


async def review_generation_failure_node(state: AgentWorkflowState) -> dict[str, Any]:
    _emit_live_workflow_event(
        state,
        "Reviewer Agent",
        "Reviewer Agent is preparing targeted repair feedback for weak generated assets.",
        "form",
        "warning",
        {"node": "review_generation_failure"},
    )
    errors = state.get("validation_errors", [])
    attempt = int(state.get("generation_attempt") or 0)
    latest_review = (state.get("reviewer_critiques") or [{}])[-1]
    qualitative_instructions = [
        str(item)
        for item in latest_review.get("repairInstructions", [])
        if str(item).strip()
    ]
    critique = {
        "agent": "Reviewer Agent",
        "attempt": attempt,
        "validationErrors": errors,
        "qualitativeReview": latest_review,
        "requiredCorrections": [
            {
                "section": _section_from_error(error),
                "issue": error,
                "instruction": (
                    "Regenerate the affected section with the exact required count and schema. "
                    "Preserve valid unaffected sections when possible."
                ),
            }
            for error in errors
        ]
        + [
            {
                "section": "all_sections",
                "issue": "Qualitative review repair instruction",
                "instruction": instruction,
            }
            for instruction in qualitative_instructions
        ],
        "decision": "repair_generation",
    }
    return {
        "reflection_feedback": [*state.get("reflection_feedback", []), critique],
        "reviewer_critiques": [*state.get("reviewer_critiques", []), critique],
        "blackboard": append_blackboard(
            state,
            blackboard_entry(
                entry_type="decision",
                agent="Reviewer Agent",
                summary="Reviewer requested a repaired generation attempt.",
                decision="repair_generation",
                payload=critique,
            ),
        ),
        "logs": append_event(
            state,
            agent_event(
                "Reviewer Agent",
                "Interview generation failed validation; reviewer requested a repair attempt.",
                "form",
                "warning",
                {
                    "attempt": attempt,
                    "next_attempt": attempt + 1,
                    "validation_errors": errors,
                    "decision": "repair_generation",
                },
            ),
        ),
    }


async def finish_generation_node(state: AgentWorkflowState) -> dict[str, Any]:
    _emit_live_workflow_event(
        state,
        "Workflow Orchestrator Agent",
        "Interview preparation graph finished; assets are being persisted.",
        "dsa",
        "success",
        {"node": "finish_generation"},
    )
    return {
        "status": "succeeded",
        "logs": append_event(
            state,
            agent_event(
                "Workflow Orchestrator Agent",
                "Agentic interview generation graph completed.",
                "dsa",
                "success",
            ),
        ),
    }


async def fail_generation_node(state: AgentWorkflowState) -> dict[str, Any]:
    return {
        "status": "failed",
        "logs": append_event(
            state,
            agent_event(
                "Workflow Orchestrator Agent",
                state.get("error", "Agentic interview generation graph failed."),
                "form",
                "error",
            ),
        ),
    }


generation_checkpointer = MemorySaver() if MemorySaver is not None else None


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


def build_planning_collaboration_subgraph():
    graph = StateGraph(AgentWorkflowState)
    graph.add_node(
        "planning_agent_propose",
        _with_node_lifecycle("planning_agent_propose", "Planning Agent", planning_agent_propose_node),
    )
    graph.add_node(
        "critic_agents_review_plan",
        _with_node_lifecycle("critic_agents_review_plan", "Critic Agents", critic_agents_review_plan_node),
    )
    graph.add_node(
        "orchestrator_revise_plan",
        _with_node_lifecycle("orchestrator_revise_plan", "Workflow Orchestrator Agent", orchestrator_revise_plan_node),
    )

    graph.add_edge(START, "planning_agent_propose")
    graph.add_edge("planning_agent_propose", "critic_agents_review_plan")
    graph.add_conditional_edges(
        "critic_agents_review_plan",
        route_after_plan_critique,
        {
            "debate": "planning_agent_propose",
            "revise": "orchestrator_revise_plan",
        },
    )
    graph.add_conditional_edges(
        "orchestrator_revise_plan",
        route_after_orchestrator_subgraph,
        {
            "replan": "planning_agent_propose",
            "done": END,
        },
    )
    return graph.compile(name="planning_collaboration_subgraph")


planning_collaboration_subgraph = build_planning_collaboration_subgraph()


async def planning_collaboration_node(state: AgentWorkflowState) -> dict[str, Any]:
    profile_name = _generation_profile(state)
    if profile_name == "deep":
        return await planning_collaboration_subgraph.ainvoke(state)

    profile = state.get("candidate_profile") or {}
    memory_state = state.get("memory_state") or {}
    base = _base_interview_plan(state)
    focus_topics = profile.get("skills", [])[:6] or [profile.get("inferred_domain", "general engineering")]
    plan = {
        **base,
        "candidate_summary": (
            f"{profile.get('target_role', 'Candidate')} profile with "
            f"{len(profile.get('skills', []))} skill signal(s) and "
            f"{len(memory_state.get('retrieved', []))} retrieved memory item(s)."
        ),
        "focus_topics": focus_topics,
        "memory_strategy": "Use retrieved weaknesses and resume/job evidence without live planning debate.",
        "review_depth": "deterministic_fast_path" if profile_name == "fast" else "single_call_turbo_path",
        "collaboration_status": f"{profile_name}_deterministic_planning",
    }
    transcript_item = {
        "agent": "Planning Agent",
        "type": "proposal",
        "provider": "deterministic-planner",
        "model": profile_name,
        "debateRound": 0,
        "plan": plan,
        "fallbackReason": None,
        "generationProfile": profile_name,
    }
    _emit_live_workflow_event(
        state,
        "Planning Agent",
        f"Planning Agent used {profile_name} deterministic planning without live debate.",
        "form",
        metadata={"node": "planning_collaboration", "generation_profile": profile_name},
    )
    return {
        "interview_plan": plan,
        "debate_round": 0,
        "orchestrator_replan_count": 0,
        "collaboration_transcript": [*state.get("collaboration_transcript", []), transcript_item],
        "blackboard": append_blackboard(
            state,
            blackboard_entry(
                entry_type="proposal",
                agent="Planning Agent",
                summary=f"{profile_name} profile produced a deterministic interview plan.",
                decision=f"{profile_name}_deterministic_plan",
                payload={"generationProfile": profile_name, "plan": plan},
            ),
        ),
        "logs": append_event(
            state,
            agent_event(
                "Planning Agent",
                f"{profile_name.capitalize()} generation skipped live critic debate and used deterministic planning.",
                "form",
                metadata={
                    "generation_profile": profile_name,
                    "provider": "deterministic-planner",
                    "focus_topics": focus_topics,
                },
            ),
        ),
    }


def build_interview_generation_graph():
    graph = StateGraph(AgentWorkflowState)
    graph.add_node(
        "security_gatekeeper",
        _with_node_lifecycle("security_gatekeeper", "Security Gatekeeper Agent", security_gatekeeper_node),
    )
    graph.add_node(
        "prepare_candidate_profile",
        _with_node_lifecycle("prepare_candidate_profile", "Resume Agent", prepare_candidate_profile_node),
    )
    graph.add_node(
        "retrieve_memory_context",
        _with_node_lifecycle("retrieve_memory_context", "Memory Agent", retrieve_memory_context_node),
    )
    graph.add_node(
        "planning_collaboration",
        _with_node_lifecycle("planning_collaboration", "Planning Agent", planning_collaboration_node),
    )
    graph.add_node(
        "generate_assets",
        _with_node_lifecycle("generate_assets", "Workflow Orchestrator Agent", generate_assets_node),
    )
    graph.add_node(
        "validate_assets",
        _with_node_lifecycle("validate_assets", "Reviewer Agent", validate_assets_node),
    )
    graph.add_node(
        "review_generation_failure",
        _with_node_lifecycle("review_generation_failure", "Reviewer Agent", review_generation_failure_node),
    )
    graph.add_node(
        "finish_generation",
        _with_node_lifecycle("finish_generation", "Workflow Orchestrator Agent", finish_generation_node),
    )
    graph.add_node(
        "fail_generation",
        _with_node_lifecycle("fail_generation", "Workflow Orchestrator Agent", fail_generation_node),
    )

    graph.add_edge(START, "security_gatekeeper")
    graph.add_conditional_edges(
        "security_gatekeeper",
        route_after_security,
        {
            "continue": "prepare_candidate_profile",
            "fail": "fail_generation",
        },
    )
    graph.add_edge("prepare_candidate_profile", "retrieve_memory_context")
    graph.add_edge("retrieve_memory_context", "planning_collaboration")
    graph.add_edge("planning_collaboration", "generate_assets")
    graph.add_edge("generate_assets", "validate_assets")
    graph.add_conditional_edges(
        "validate_assets",
        route_after_validation,
        {
            "finish": "finish_generation",
            "repair": "review_generation_failure",
            "fail": "fail_generation",
        },
    )
    graph.add_edge("review_generation_failure", "generate_assets")
    graph.add_edge("finish_generation", END)
    graph.add_edge("fail_generation", END)
    compile_kwargs = _compile_interrupt_kwargs(
        settings.langgraph_generation_interrupt_before,
        settings.langgraph_generation_interrupt_after,
    )
    if generation_checkpointer is not None:
        return graph.compile(checkpointer=generation_checkpointer, name="interview_generation_graph", **compile_kwargs)
    return graph.compile(name="interview_generation_graph", **compile_kwargs)


interview_generation_graph = build_interview_generation_graph()


async def generate_interview_assets(interview: dict) -> dict:
    graph_started = time.perf_counter()
    generation_profile = _generation_profile_from(interview.get("generation_profile"))
    graph_input = {
            "interview": interview,
            "logs": [
                agent_event(
                    "Workflow Orchestrator Agent",
                    "Agentic interview generation graph started.",
                    "form",
                )
            ],
            "status": "running",
            "generation_profile": generation_profile,
            "generation_attempt": 0,
            "max_generation_attempts": _graph_limit(settings.langgraph_max_generation_attempts, 2),
            "debate_round": 0,
            "max_debate_rounds": _graph_limit(settings.langgraph_max_debate_rounds, 2),
            "orchestrator_replan_count": 0,
            "max_orchestrator_replans": _graph_limit(settings.langgraph_max_orchestrator_replans, 1),
            "blackboard": [],
            "tool_decisions": [],
            "tool_results": [],
            "section_generation_reviews": [],
            "section_generation_attempts": {},
            "security_state": {},
            "reflection_feedback": [],
            "reviewer_critiques": [],
            "collaboration_transcript": [],
            "planning_critiques": [],
        }
    thread_suffix = ""
    if interview.get("_workflow_generation_attempt"):
        thread_suffix = f":attempt-{interview.get('_workflow_generation_attempt')}"
    graph_config = {
        "configurable": {"thread_id": f"interview-generation:{interview.get('id', 'unknown')}{thread_suffix}"},
        "recursion_limit": _graph_limit(settings.langgraph_generation_recursion_limit, 40, minimum=8),
    }
    if generation_checkpointer is not None:
        graph_input["checkpoint_metadata"] = {
            "thread_id": graph_config["configurable"]["thread_id"],
            "checkpointer": "MemorySaver",
            "subgraphs": ["planning_collaboration_subgraph"],
            "human_interrupts_enabled": settings.langgraph_human_interrupts_enabled,
            "generation_profile": generation_profile,
            "interrupt_before": _interrupt_nodes(settings.langgraph_generation_interrupt_before) or [],
            "interrupt_after": _interrupt_nodes(settings.langgraph_generation_interrupt_after) or [],
            "interrupt_safe_nodes": ["planning_agent_propose", "critic_agents_review_plan", "orchestrator_revise_plan", "generate_assets"],
            "resume_hint": "Resume with the same thread_id through LangGraph checkpointer when future human-in-loop interrupts are enabled.",
        }
    state = await interview_generation_graph.ainvoke(
        graph_input,
        config=graph_config,
    )
    if state.get("status") == "failed":
        raise ValueError(state.get("error") or "Agentic interview generation graph failed.")

    question_set = state.get("question_set") or {}
    return {
        "dsa_problems": question_set.get("dsa_problems", []),
        "aptitude_questions": question_set.get("aptitude_questions", []),
        "technical_questions": question_set.get("technical_questions", []),
        "hr_questions": question_set.get("hr_questions", []),
        "logs": _public_logs(state),
            "workflow_state": {
            "generation_profile": generation_profile,
            "generation_duration_ms": round((time.perf_counter() - graph_started) * 1000, 2),
            "candidate_profile": state.get("candidate_profile", {}),
            "memory_state": state.get("memory_state", {}),
            "interview_plan": state.get("interview_plan", {}),
            "security_state": state.get("security_state", {}),
            "checkpoint_metadata": state.get("checkpoint_metadata", {}),
            "collaboration_transcript": state.get("collaboration_transcript", []),
            "planning_critiques": state.get("planning_critiques", []),
            "generation_attempt": state.get("generation_attempt", 1),
            "debate_round": state.get("debate_round", 0),
            "orchestrator_replan_count": state.get("orchestrator_replan_count", 0),
            "blackboard_checkpoint_count": len(checkpoint_blackboard(state)),
            "tool_decision_count": len(state.get("tool_decisions", [])),
            "tool_result_count": len(state.get("tool_results", [])),
            "section_generation_reviews": state.get("section_generation_reviews", []),
            "section_generation_attempts": state.get("section_generation_attempts", {}),
            "reflection_feedback": state.get("reflection_feedback", []),
            "reviewer_critiques": state.get("reviewer_critiques", []),
            "status": state.get("status", "succeeded"),
        },
    }
