from dataclasses import dataclass
from typing import Any

from agents.tools.autonomous import execute_autonomous_tool_selection
from agents.tools.decision import ToolDecision, ToolExecutionRecord, execute_tool_decision, tool_decision
from services.llm import llm_service
from services.security_gateway import security_gateway


@dataclass
class BotResponse:
    content: str
    provider: str
    model: str
    tool_decisions: list[ToolDecision]
    tool_results: list[ToolExecutionRecord]


@dataclass
class BotPromptContext:
    messages: list[dict[str, Any]]
    tool_decisions: list[ToolDecision]
    tool_results: list[ToolExecutionRecord]


def _compact_report(report: dict | None) -> dict:
    if not report:
        return {}
    return {
        "overallScore": report.get("overallScore"),
        "weaknesses": report.get("weaknesses", [])[:6],
        "strengths": report.get("strengths", [])[:6],
        "summary": report.get("executiveSummary") or report.get("aiFeedback"),
        "whatWentWrong": report.get("whatWentWrong", [])[:4],
        "nextTimeSuggestions": report.get("nextTimeSuggestions", [])[:4],
        "sections": [
            {
                "name": section.get("name"),
                "score": section.get("score"),
                "feedback": section.get("feedback"),
            }
            for section in report.get("sections", [])[:4]
        ],
    }


def _compact_roadmap(roadmap: dict | None) -> dict:
    if not roadmap:
        return {}
    return {
        "title": roadmap.get("title"),
        "description": roadmap.get("description"),
        "progress": roadmap.get("progress"),
        "milestones": [
            {
                "title": milestone.get("title"),
                "completed": milestone.get("completed"),
                "tasks": [
                    {"title": task.get("title"), "completed": task.get("completed")}
                    for task in milestone.get("tasks", [])[:4]
                ],
            }
            for milestone in roadmap.get("milestones", [])[:6]
        ],
    }


def _message_tokens(message: str) -> set[str]:
    return {part.strip(".,!?;:()[]{}\"'").lower() for part in message.split() if part.strip()}


def ai_memory_enabled_for_user(user: dict) -> bool:
    settings_payload = user.get("settings") if isinstance(user.get("settings"), dict) else {}
    ai_settings = settings_payload.get("ai") if isinstance(settings_payload.get("ai"), dict) else {}
    if "memoryEnabled" in ai_settings:
        return bool(ai_settings["memoryEnabled"])
    return bool(user.get("ai_memory_enabled", True))


def fallback_bot_tool_decisions(user: dict, message: str) -> list[ToolDecision]:
    if not ai_memory_enabled_for_user(user):
        return []

    tokens = _message_tokens(message)
    decisions: list[ToolDecision] = []
    if len(message.strip()) >= 12:
        decisions.append(
            tool_decision(
                "AI Consultant Bot Agent",
                "retrieve_memory_context",
                "Policy fallback: retrieve semantic memory when provider-native tool calling is unavailable.",
                {
                    "user_id": user.get("id", ""),
                    "query": message,
                    "limit": 5,
                    "memory_types": ["resume", "report", "transcript", "weakness", "roadmap", "practice", "bot"],
                },
                required=False,
            )
        )
    if tokens & {"report", "score", "scores", "weakness", "weaknesses", "performance", "feedback", "interview"}:
        decisions.append(
            tool_decision(
                "AI Consultant Bot Agent",
                "retrieve_reports",
                "Policy fallback: retrieve reports for score, weakness, and feedback questions.",
                {"user_id": user.get("id", ""), "limit": 3},
                required=False,
            )
        )
    if tokens & {"roadmap", "plan", "practice", "tasks", "milestone", "milestones", "study"}:
        decisions.append(
            tool_decision(
                "AI Consultant Bot Agent",
                "retrieve_roadmap",
                "Policy fallback: retrieve active roadmap for planning questions.",
                {"user_id": user.get("id", ""), "active_only": True, "limit": 1},
                required=False,
            )
        )
        decisions.append(
            tool_decision(
                "AI Consultant Bot Agent",
                "retrieve_practice_history",
                "Policy fallback: retrieve practice history for planning questions.",
                {"user_id": user.get("id", ""), "limit": 5},
                required=False,
            )
        )
    if tokens & {"resume", "cv", "ats"}:
        decisions.append(
            tool_decision(
                "AI Consultant Bot Agent",
                "retrieve_resume",
                "Policy fallback: retrieve resume records for resume questions.",
                {"user_id": user.get("id", ""), "limit": 3},
                required=False,
            )
        )
    return decisions


async def build_bot_response(
    user: dict,
    message: str,
    reports: list[dict],
    roadmaps: list[dict],
    resumes: list[dict],
    history: list[dict],
) -> str:
    response = await build_bot_response_details(user, message, reports, roadmaps, resumes, history)
    return response.content


async def build_bot_response_details(
    user: dict,
    message: str,
    reports: list[dict],
    roadmaps: list[dict],
    resumes: list[dict],
    history: list[dict],
) -> BotResponse:
    prompt = await build_bot_prompt_context(user, message, reports, roadmaps, resumes, history)
    response = await llm_service.invoke_live(
        prompt.messages,
        agent="bot",
        provider_order=("groq", "gemini"),
    )
    return BotResponse(
        content=response.content,
        provider=response.provider,
        model=response.model,
        tool_decisions=prompt.tool_decisions,
        tool_results=prompt.tool_results,
    )


async def build_bot_prompt_context(
    user: dict,
    message: str,
    reports: list[dict],
    roadmaps: list[dict],
    resumes: list[dict],
    history: list[dict],
) -> BotPromptContext:
    sanitized_message = security_gateway.sanitize_text(message, source="bot.user_message", limit=4000)
    memory_enabled = ai_memory_enabled_for_user(user)
    available_tools = [
        "retrieve_memory_context",
        "retrieve_reports",
        "retrieve_roadmap",
        "retrieve_practice_history",
        "retrieve_resume",
    ] if memory_enabled else []
    tool_run = await execute_autonomous_tool_selection(
        agent="bot",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the InterviewOS Bot Agent deciding which backend tools are needed before answering. "
                    "Use tools only when the user's message needs personalized memory, reports, roadmaps, resumes, "
                    "or practice history. If the message is general, choose no tool."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User message: {sanitized_message.clean_text}\n"
                    f"Available local counts: reports={len(reports)}, roadmaps={len(roadmaps)}, resumes={len(resumes)}, "
                    f"recent_chat={len(history[-12:])}.\n"
                    f"User id for tool calls: {user.get('id', '')}"
                ),
            },
        ],
        available_tools=available_tools,
        fallback_decisions=fallback_bot_tool_decisions(user, sanitized_message.clean_text),
        provider_order=("groq", "gemini"),
    )
    by_tool = {record["decision"]["tool"]: record for record in tool_run.tool_results if record.get("ok")}
    semantic_memory = by_tool.get("retrieve_memory_context", {}).get("data", {}).get("memories", [])
    semantic_memory, _ = security_gateway.sanitize_records(semantic_memory, source="bot.semantic_memory")
    selected_reports = by_tool.get("retrieve_reports", {}).get("data", {}).get("reports", [])
    selected_roadmaps = by_tool.get("retrieve_roadmap", {}).get("data", {}).get("roadmaps", [])
    selected_practice = by_tool.get("retrieve_practice_history", {}).get("data", {}).get("sessions", [])
    selected_resumes = by_tool.get("retrieve_resume", {}).get("data", {}).get("resumes", [])
    latest_report = selected_reports[0] if selected_reports else None
    active_roadmap = next((roadmap for roadmap in selected_roadmaps if roadmap.get("isActive")), None)
    context = {
        "user": user.get("name"),
        "tool_selection": tool_run.provider_metadata,
        "message_security": sanitized_message.private_metadata(),
        "latest_report": _compact_report(latest_report),
        "active_roadmap": _compact_roadmap(active_roadmap),
        "resume_count": len(resumes),
        "selected_resume_count": len(selected_resumes),
        "selected_practice": [
            {
                "mode": item.get("mode"),
                "difficulty": item.get("difficulty"),
                "score": item.get("score"),
                "topicFilter": item.get("topicFilter"),
            }
            for item in selected_practice[:5]
        ],
        "semantic_memory": [
            {
                "type": item.get("metadata", {}).get("memory_type"),
                "source_id": item.get("document_id"),
                "excerpt": item.get("excerpt") or str(item.get("text", ""))[:700],
            }
            for item in semantic_memory
        ],
        "recent_chat_memory": [
            {
                "role": item.get("role"),
                "content": security_gateway.sanitize_text(
                    item.get("content", ""),
                    source=f"bot.history.{index}",
                    limit=1200,
                ).clean_text,
            }
            for index, item in enumerate(history[-12:])
        ] if memory_enabled else [],
    }
    return BotPromptContext(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are InterviewOS's AI consultant. Be specific, practical, and remember the "
                    "candidate's previous context. Use the supplied report, roadmap, resume count, "
                    "and chat memory when relevant. For code, always use fenced Markdown code blocks "
                    "with the language name, short explanations, and readable indentation. Do not "
                    "append generic score summaries unless they directly answer the user."
                ),
            },
            {"role": "system", "content": f"User context: {context}"},
            {"role": "user", "content": sanitized_message.clean_text},
        ],
        tool_decisions=tool_run.tool_decisions,
        tool_results=tool_run.tool_results,
    )
