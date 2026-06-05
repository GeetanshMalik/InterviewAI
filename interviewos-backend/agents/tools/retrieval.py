from __future__ import annotations

from typing import Any

from agents.tools.base import ToolResult, tool_success
from services.security_gateway import security_gateway
from services.chroma import chroma_service
from services.store import store


def _limit(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return items[: max(0, limit)]


def retrieve_resume(user_id: str, resume_id: str | None = None, limit: int = 5) -> ToolResult:
    resumes = [
        resume
        for resume in store.resumes.values()
        if resume.get("userId") == user_id and (resume_id is None or resume.get("id") == resume_id)
    ]
    resumes.sort(key=lambda item: item.get("uploadedAt", ""), reverse=True)
    return tool_success(
        "retrieve_resume",
        {
            "resumes": _limit(resumes, limit),
            "count": len(resumes),
        },
        {"user_id": user_id, "resume_id": resume_id},
    )


def retrieve_reports(user_id: str, limit: int = 5) -> ToolResult:
    reports = store.user_reports(user_id)
    return tool_success(
        "retrieve_reports",
        {
            "reports": _limit(reports, limit),
            "count": len(reports),
        },
        {"user_id": user_id},
    )


def retrieve_roadmap(user_id: str, roadmap_id: str | None = None, active_only: bool = False, limit: int = 5) -> ToolResult:
    roadmaps = store.user_roadmaps(user_id)
    if roadmap_id:
        roadmaps = [roadmap for roadmap in roadmaps if roadmap.get("id") == roadmap_id]
    if active_only:
        roadmaps = [roadmap for roadmap in roadmaps if roadmap.get("isActive")]
    return tool_success(
        "retrieve_roadmap",
        {
            "roadmaps": _limit(roadmaps, limit),
            "active": next((roadmap for roadmap in roadmaps if roadmap.get("isActive")), None),
            "count": len(roadmaps),
        },
        {"user_id": user_id, "roadmap_id": roadmap_id, "active_only": active_only},
    )


def retrieve_practice_history(user_id: str, limit: int = 5, mode: str | None = None) -> ToolResult:
    sessions = [
        session
        for session in store.practice_sessions.values()
        if session.get("userId") == user_id and (mode is None or session.get("mode") == mode)
    ]
    sessions.sort(key=lambda item: item.get("startedAt", ""), reverse=True)
    return tool_success(
        "retrieve_practice_history",
        {
            "sessions": _limit(sessions, limit),
            "count": len(sessions),
        },
        {"user_id": user_id, "mode": mode},
    )


def retrieve_generation_history(user_id: str, limit: int = 5, section: str | None = None) -> ToolResult:
    interviews = [item for item in store.interviews.values() if item.get("userId") == user_id]
    interviews.sort(key=lambda item: item.get("createdAt", ""), reverse=True)
    allowed_sections = {
        "dsa_problems": store.dsa_problems,
        "aptitude_questions": store.aptitude_questions,
        "technical_questions": store.technical_questions,
        "hr_questions": store.hr_questions,
    }
    selected_sections = [section] if section in allowed_sections else list(allowed_sections)
    history: list[dict[str, Any]] = []
    for interview in interviews:
        interview_id = interview.get("id")
        if not interview_id:
            continue
        section_summaries = []
        for section_name in selected_sections:
            questions = allowed_sections[section_name].get(interview_id, [])
            if not questions:
                continue
            samples = []
            for item in questions[:8]:
                question_text = (
                    item.get("question_text")
                    or item.get("question")
                    or item.get("title")
                    or item.get("description")
                    or ""
                )
                sanitized = security_gateway.sanitize_text(
                    question_text,
                    source=f"tool.retrieve_generation_history.{section_name}",
                    limit=500,
                )
                samples.append(
                    {
                        "id": item.get("id"),
                        "title": item.get("title") or sanitized.clean_text[:80],
                        "topic": item.get("topic") or item.get("category"),
                        "difficulty": item.get("difficulty"),
                        "question_text": sanitized.clean_text,
                    }
                )
            section_summaries.append(
                {
                    "section": section_name,
                    "count": len(questions),
                    "samples": samples,
                }
            )
        if section_summaries:
            history.append(
                {
                    "interview_id": interview_id,
                    "createdAt": interview.get("createdAt"),
                    "target_role": interview.get("target_role"),
                    "difficulty": interview.get("difficulty"),
                    "sections": section_summaries,
                }
            )
        if len(history) >= max(0, limit):
            break
    return tool_success(
        "retrieve_generation_history",
        {"history": history, "count": len(history), "section": section},
        {"user_id": user_id, "section": section},
    )


def retrieve_memory_context(
    user_id: str,
    query: str,
    limit: int = 5,
    memory_types: list[str] | None = None,
    privacy_scopes: list[str] | None = None,
) -> ToolResult:
    sanitized_query = security_gateway.sanitize_text(query, source="tool.retrieve_memory_context.query", limit=1200)
    memories = chroma_service.query_memory(
        user_id,
        sanitized_query.clean_text,
        limit=limit,
        memory_types=memory_types,
        privacy_scopes=privacy_scopes,
    )
    memories, security_metadata = security_gateway.sanitize_records(memories, source="tool.retrieve_memory_context.results")
    return tool_success(
        "retrieve_memory_context",
        {
            "memories": memories,
            "count": len(memories),
            "query": sanitized_query.clean_text,
            "memory_types": sorted({str(item.get("metadata", {}).get("memory_type", "unknown")) for item in memories}),
            "recall_summaries": [item.get("recall_summary", "") for item in memories if item.get("recall_summary")],
        },
        {
            "user_id": user_id,
            "memory_types": memory_types or [],
            "privacy_scopes": privacy_scopes or ["user"],
            "security": {
                "query": sanitized_query.private_metadata(),
                "results": security_metadata,
            },
        },
    )


def write_memory(
    user_id: str,
    memory_type: str,
    source_id: str,
    text: str,
    metadata: dict[str, Any] | None = None,
    defer_indexing: bool = False,
) -> ToolResult:
    sanitized = security_gateway.sanitize_text(text, source=f"tool.write_memory.{memory_type}", limit=12000)
    final_metadata = dict(metadata or {})
    if sanitized.quarantined_spans:
        final_metadata["security"] = sanitized.private_metadata()
    memory = chroma_service.add_memory(
        user_id,
        memory_type,
        source_id,
        sanitized.clean_text,
        final_metadata,
        defer_indexing=defer_indexing,
    )
    return tool_success(
        "write_memory",
        {
            "memory": {
                "id": memory["id"],
                "user_id": memory["user_id"],
                "document_id": memory["document_id"],
                "metadata": memory["metadata"],
                "textLength": len(sanitized.clean_text),
            }
        },
        {
            "user_id": user_id,
            "memory_type": memory_type,
            "source_id": source_id,
            "defer_indexing": defer_indexing,
            "security": sanitized.private_metadata(),
        },
    )
