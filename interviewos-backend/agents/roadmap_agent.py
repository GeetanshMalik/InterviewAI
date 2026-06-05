from __future__ import annotations

import json
import re
from ast import literal_eval
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from typing import Any

from agents.tools.autonomous import execute_autonomous_tool_selection
from agents.tools.decision import ToolDecision, ToolExecutionRecord, tool_decision
from services.llm import llm_service
from services.store import iso_now, new_id
from utils.parsers import json_from_text


def _json_from_text(text: str) -> dict[str, Any]:
    return json_from_text(text, root_error="Roadmap agent response must be a JSON object.")


def _string(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _clean_generated_text(value: Any, fallback: str = "") -> str:
    text = _string(value, fallback).replace("\\n", "\n")
    text = re.sub(r"```(?:\w+)?\n?", "", text)
    text = text.replace("```", "")
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*\*\*([^*\n]+)\*\*\*", r"\1", text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_\n]+)__", r"\1", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return cleaned or fallback


def _list(value: Any, fallback: list[Any] | None = None) -> list[Any]:
    return value if isinstance(value, list) else fallback or []


def _priority(value: Any) -> str:
    text = _clean_generated_text(value, "medium").lower()
    return text if text in {"low", "medium", "high"} else "medium"


def _int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _weeks(duration_days: int) -> int:
    return max(4, min(12, round(duration_days / 7)))


def _roadmap_context(report: dict | None, target_role: str | None, duration_days: int) -> dict[str, Any]:
    return {
        "target_role": target_role or "Interview",
        "duration_days": duration_days,
        "latest_report": {
            "overallScore": (report or {}).get("overallScore"),
            "strengths": (report or {}).get("strengths", []),
            "weaknesses": (report or {}).get("weaknesses", []),
            "whatWentWrong": (report or {}).get("whatWentWrong", []),
            "nextTimeSuggestions": (report or {}).get("nextTimeSuggestions", []),
            "sections": [
                {
                    "name": section.get("name"),
                    "score": section.get("score"),
                    "feedback": section.get("feedback"),
                    "actionItems": section.get("details", {}).get("actionItems", []),
                }
                for section in (report or {}).get("sections", [])
            ],
        },
        "reviewer_feedback": (report or {}).get("lifecycleReviewerFeedback")
        or (report or {}).get("_agentic_roadmap_reflection_feedback", []),
    }


def _roadmap_query(report: dict | None, target_role: str | None) -> str:
    return " ".join(
        str(part)
        for part in [
            target_role or (report or {}).get("targetRole"),
            "weaknesses " + ", ".join(str(item) for item in (report or {}).get("weaknesses", [])[:5]),
            "suggestions " + ", ".join(str(item) for item in (report or {}).get("nextTimeSuggestions", [])[:5]),
        ]
        if part
    )


def _records_for_tool(tool_results: list[ToolExecutionRecord], tool_name: str, key: str, limit: int) -> list[dict[str, Any]]:
    return [
        item
        for record in tool_results
        if record.get("ok") and record.get("decision", {}).get("tool") == tool_name
        for item in record.get("data", {}).get(key, [])
    ][:limit]


async def _roadmap_agent_tool_context(
    user_id: str,
    report: dict | None,
    target_role: str | None,
    duration_days: int,
) -> tuple[dict[str, Any], list[ToolDecision], list[ToolExecutionRecord]]:
    query = _roadmap_query(report, target_role) or "learning roadmap weakness practice"
    fallback_decisions = [
        tool_decision(
            "Roadmap Agent",
            "retrieve_memory_context",
            "Ground the roadmap in historical weaknesses, practice outcomes, and prior learning progress.",
            {
                "user_id": user_id,
                "query": query,
                "limit": 6,
                "memory_types": ["weakness", "evaluation", "roadmap", "practice", "report", "transcript"],
            },
            required=False,
        ),
        tool_decision(
            "Roadmap Agent",
            "retrieve_reports",
            "Inspect recent reports so the roadmap targets persistent gaps instead of only the latest score.",
            {"user_id": user_id, "limit": 3},
            required=False,
        ),
        tool_decision(
            "Roadmap Agent",
            "retrieve_roadmap",
            "Retrieve active roadmap context before creating a replacement plan.",
            {"user_id": user_id, "active_only": True, "limit": 2},
            required=False,
        ),
        tool_decision(
            "Roadmap Agent",
            "retrieve_practice_history",
            "Retrieve practice history so weekly tasks do not repeat ineffective drills.",
            {"user_id": user_id, "limit": 4},
            required=False,
        ),
    ]
    tool_run = await execute_autonomous_tool_selection(
        agent="roadmap",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the InterviewOS Roadmap Agent. Decide which tools are needed before creating "
                    "or revising a learning roadmap. Use tools when memory, reports, roadmap history, or "
                    "practice history can make the plan more adaptive."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Roadmap query: {query}\nDuration days: {duration_days}\n"
                    f"Report weaknesses: {(report or {}).get('weaknesses', [])}\n"
                    f"User id: {user_id}"
                )[:7000],
            },
        ],
        available_tools=["retrieve_memory_context", "retrieve_reports", "retrieve_roadmap", "retrieve_practice_history"],
        fallback_decisions=fallback_decisions,
        max_total_tool_calls=4,
    )
    tool_context = {
        "tool_selection": tool_run.provider_metadata,
        "semantic_memory": _records_for_tool(tool_run.tool_results, "retrieve_memory_context", "memories", 6),
        "historical_reports": _records_for_tool(tool_run.tool_results, "retrieve_reports", "reports", 3),
        "roadmaps": _records_for_tool(tool_run.tool_results, "retrieve_roadmap", "roadmaps", 2),
        "practice_sessions": _records_for_tool(tool_run.tool_results, "retrieve_practice_history", "sessions", 4),
    }
    return tool_context, tool_run.tool_decisions, tool_run.tool_results


def _fallback_payload(report: dict | None, target_role: str | None, duration_days: int) -> dict[str, Any]:
    weakness = ((report or {}).get("weaknesses") or ["DSA"])[0]
    role = target_role or "Interview"
    week_topics = [
        (f"Week 1 - Repair {weakness} fundamentals", "Rebuild the base concepts behind the lowest-scoring area."),
        ("Week 2 - Guided drills and mistake logging", "Practice focused questions and capture repeatable mistakes."),
        ("Week 3 - Mixed timed simulations", "Blend weak-area drills with full interview timing and pressure."),
        ("Week 4 - Mock interview polish", "Turn practice into a repeatable interview routine."),
    ]
    milestones = []
    for index in range(1, _weeks(duration_days) + 1):
        title, description = week_topics[(index - 1) % len(week_topics)]
        if index > len(week_topics):
            title = f"Week {index} - Repeat simulation and repair cycle"
            description = "Use the latest mistake log to choose drills, mocks, and review targets."
        milestones.append(
            {
                "title": title,
                "description": description,
                "tasks": [
                    {
                        "title": f"Complete three focused {weakness} drills",
                        "description": "Review each answer and rewrite the missed reasoning.",
                        "priority": "high",
                    },
                    {
                        "title": "Update the mistake log",
                        "description": "Record issue, root cause, corrected answer, and next prevention drill.",
                        "priority": "high",
                    },
                    {
                        "title": "Do one timed mini-mock",
                        "description": "Practice explaining your approach before giving the final answer.",
                        "priority": "medium",
                    },
                    {
                        "title": "Summarize the week in five bullets",
                        "description": "Write what improved, what repeated, and what to change next week.",
                        "priority": "medium",
                    },
                ],
            }
        )
    return {
        "title": f"{role} Roadmap: {weakness} Recovery Plan",
        "description": f"A {duration_days}-day week-wise plan focused on measurable interview improvement.",
        "skills": [
            {"name": weakness, "category": "priority", "level": 2, "targetLevel": 4, "resources": []},
            {"name": "Timed interview execution", "category": "practice", "level": 2, "targetLevel": 4, "resources": []},
            {"name": "Answer communication", "category": "communication", "level": 3, "targetLevel": 4, "resources": []},
        ],
        "milestones": milestones,
    }


async def _ai_roadmap(
    report: dict | None,
    target_role: str | None,
    duration_days: int,
    agent_tool_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    week_count = _weeks(duration_days)
    context = _roadmap_context(report, target_role, duration_days)
    if agent_tool_context:
        context["agent_tool_context"] = agent_tool_context
    response = await llm_service.invoke_live(
        [
            {
                "role": "system",
                "content": (
                    "You are the InterviewOS Roadmap Agent. Generate practical, week-wise interview "
                    "preparation roadmaps with checkbox-style tasks, measurable outcomes, and realistic "
                    "progression. Return only JSON with plain-text string values, no markdown."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Create a {week_count}-week roadmap from this report context. Each week needs 4-6 tasks.\n"
                    "Do not include markdown emphasis markers like **, __, or backticks in any string value.\n"
                    "Return this JSON shape:\n"
                    "{\n"
                    '  "title": "string",\n'
                    '  "description": "short description",\n'
                    '  "skills": [{"name": "skill", "category": "priority|practice|communication|technical", "level": 1, "targetLevel": 4, "resources": [{"title": "resource", "type": "article|video|course|book", "url": "", "completed": false}]}],\n'
                    '  "milestones": [{"title": "Week 1 - theme", "description": "outcome", "tasks": [{"title": "checkbox task", "description": "how to do it", "priority": "high|medium|low"}]}]\n'
                    "}\n\n"
                    f"Context JSON:\n{json.dumps(context, ensure_ascii=False)}"
                ),
            },
        ],
        agent="roadmap",
    )
    return _json_from_text(response.content)


def _normalize_resources(resources: Any) -> list[dict]:
    normalized = []
    for item in _list(resources)[:6]:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "id": new_id(),
                "title": _clean_generated_text(item.get("title"), "Practice resource"),
                "type": _clean_generated_text(item.get("type"), "article"),
                "url": _clean_generated_text(item.get("url"), ""),
                "completed": bool(item.get("completed", False)),
            }
        )
    return normalized


def _normalize_roadmap(
    user_id: str,
    payload: dict[str, Any],
    report: dict | None,
    target_role: str | None,
    duration_days: int,
    *,
    existing: dict | None = None,
    is_active: bool = True,
) -> dict:
    now = datetime.now(UTC)
    week_count = _weeks(duration_days)
    raw_milestones = _list(payload.get("milestones"))
    fallback = _fallback_payload(report, target_role, duration_days)
    if len(raw_milestones) < week_count:
        raw_milestones = fallback["milestones"]

    milestones = []
    for index, raw in enumerate(raw_milestones[:week_count], start=1):
        item = raw if isinstance(raw, dict) else {}
        tasks = []
        for task_raw in _list(item.get("tasks"))[:6]:
            task = task_raw if isinstance(task_raw, dict) else {}
            tasks.append(
                {
                    "id": new_id(),
                    "title": _clean_generated_text(task.get("title"), f"Week {index} practice task"),
                    "description": _clean_generated_text(task.get("description"), ""),
                    "completed": bool(task.get("completed", False)),
                    "priority": _priority(task.get("priority")),
                }
            )
        if len(tasks) < 4:
            tasks.extend(
                {
                    "id": new_id(),
                    "title": _clean_generated_text(fallback_task["title"]),
                    "description": _clean_generated_text(fallback_task.get("description", "")),
                    "completed": False,
                    "priority": fallback_task.get("priority", "medium"),
                }
                for fallback_task in fallback["milestones"][min(index - 1, len(fallback["milestones"]) - 1)]["tasks"][len(tasks):4]
            )
        milestones.append(
            {
                "id": new_id(),
                "title": _clean_generated_text(item.get("title"), f"Week {index}"),
                "description": _clean_generated_text(item.get("description"), "Focused interview preparation week."),
                "dueDate": (now + timedelta(days=7 * index)).isoformat(),
                "completed": all(task["completed"] for task in tasks),
                "tasks": tasks,
            }
        )

    raw_skills = _list(payload.get("skills")) or fallback["skills"]
    skills = []
    for raw in raw_skills[:8]:
        item = raw if isinstance(raw, dict) else {}
        skills.append(
            {
                "id": new_id(),
                "name": _clean_generated_text(item.get("name"), "Interview skill"),
                "category": _clean_generated_text(item.get("category"), "priority"),
                "level": _int(item.get("level"), 2),
                "targetLevel": _int(item.get("targetLevel"), 4),
                "resources": _normalize_resources(item.get("resources")),
            }
        )

    roadmap_id = (existing or {}).get("id") or new_id()
    created_at = (existing or {}).get("createdAt") or iso_now()
    tasks = [task for milestone in milestones for task in milestone["tasks"]]
    completed = [task for task in tasks if task.get("completed")]
    return {
        "id": roadmap_id,
        "userId": user_id,
        "title": _clean_generated_text(payload.get("title"), fallback["title"]),
        "description": _clean_generated_text(payload.get("description"), fallback["description"]),
        "createdAt": created_at,
        "updatedAt": iso_now(),
        "milestones": milestones,
        "skills": skills,
        "progress": round((len(completed) / max(len(tasks), 1)) * 100, 2),
        "isActive": is_active,
        "sourceReportId": (report or {}).get("id") or (existing or {}).get("sourceReportId"),
    }


async def build_roadmap(
    user_id: str,
    report: dict | None,
    target_role: str | None = None,
    duration_days: int = 30,
    *,
    include_agent_evidence: bool = False,
) -> dict:
    tool_context, tool_decisions, tool_results = await _roadmap_agent_tool_context(
        user_id,
        report,
        target_role,
        duration_days,
    )
    try:
        payload = await _ai_roadmap(report, target_role, duration_days, tool_context)
    except Exception:
        payload = _fallback_payload(report, target_role, duration_days)
    roadmap = _normalize_roadmap(user_id, payload, report, target_role, duration_days, is_active=True)
    roadmap["agentToolContext"] = {
        "toolSelection": tool_context.get("tool_selection", {}),
        "semanticMemoryCount": len(tool_context.get("semantic_memory", [])),
        "historicalReportCount": len(tool_context.get("historical_reports", [])),
        "roadmapCount": len(tool_context.get("roadmaps", [])),
        "practiceSessionCount": len(tool_context.get("practice_sessions", [])),
    }
    if include_agent_evidence:
        roadmap["_agentic_tool_decisions"] = tool_decisions
        roadmap["_agentic_tool_results"] = tool_results
    return roadmap


async def preview_roadmap_update(user_id: str, roadmap: dict, instructions: str, report: dict | None = None) -> dict:
    response = await llm_service.invoke_live(
        [
            {
                "role": "system",
                "content": (
                    "You are the InterviewOS Roadmap Agent. Review the user's requested roadmap change, "
                    "explain pros and cons, and produce a proposed revised roadmap. Preserve useful "
                    "completed progress when it still makes sense. Return only JSON with plain-text string values, no markdown."
                ),
            },
            {
                "role": "user",
                "content": (
                    "The user wants to update the active roadmap.\n"
                    f"Requested change: {instructions}\n\n"
                    "Do not include markdown emphasis markers like **, __, or backticks in any string value.\n"
                    "Return this JSON shape:\n"
                    "{\n"
                    '  "summary": "what will change",\n'
                    '  "pros": ["benefit"],\n'
                    '  "cons": ["risk or tradeoff"],\n'
                    '  "proposedRoadmap": {"title": "string", "description": "string", "skills": [], "milestones": []}\n'
                    "}\n\n"
                    f"Current roadmap JSON:\n{json.dumps(roadmap, ensure_ascii=False)}\n\n"
                    f"Latest report JSON:\n{json.dumps(report or {}, ensure_ascii=False)}"
                ),
            },
        ],
        agent="roadmap",
    )
    payload = _json_from_text(response.content)
    proposed = payload.get("proposedRoadmap") if isinstance(payload.get("proposedRoadmap"), dict) else {}
    duration_days = max(30, len(roadmap.get("milestones", [])) * 7)
    normalized = _normalize_roadmap(
        user_id,
        proposed,
        report,
        roadmap.get("title"),
        duration_days,
        existing=roadmap,
        is_active=True,
    )
    return {
        "summary": _clean_generated_text(payload.get("summary"), "The roadmap will be updated using your requested direction."),
        "pros": [_clean_generated_text(item) for item in _list(payload.get("pros"), ["Better alignment with your current goal."])][:6],
        "cons": [_clean_generated_text(item) for item in _list(payload.get("cons"), ["May reduce focus on the original weak area."])][:6],
        "proposedRoadmap": normalized,
        "provider": response.provider,
    }
