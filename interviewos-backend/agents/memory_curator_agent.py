from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from agents.tools.autonomous import execute_autonomous_tool_selection
from agents.tools.decision import ToolDecision, ToolExecutionRecord, tool_decision
from services.llm import llm_service
from utils.parsers import json_from_text


@dataclass
class MemoryCurationResult:
    decisions: list[dict[str, Any]] = field(default_factory=list)
    tool_decisions: list[ToolDecision] = field(default_factory=list)
    tool_results: list[ToolExecutionRecord] = field(default_factory=list)
    provider: str = "deterministic-memory-curator"
    model: str = "local-memory-policy-v1"
    fallback_used: bool = True


def _deterministic_memory_decision(item: dict[str, Any]) -> dict[str, Any]:
    text = str(item.get("text", "")).strip()
    memory_type = str(item.get("memory_type", ""))
    if len(text) < 30:
        decision = "skip"
        reason = "text_too_short"
    elif memory_type in {"weakness", "evaluation", "report", "roadmap"}:
        decision = "write"
        reason = "high_value_lifecycle_memory"
    elif memory_type == "transcript" and len(text) >= 120:
        decision = "write"
        reason = "substantive_transcript"
    else:
        decision = "skip"
        reason = "not_marked_useful_by_memory_policy"
    return {
        "source_id": item.get("source_id"),
        "memory_type": memory_type,
        "decision": decision,
        "reason": reason,
        "importance": item.get("metadata", {}).get("importance", "medium"),
        "deterministic_reason": reason,
    }


def _memory_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": item.get("source_id"),
        "memory_type": item.get("memory_type"),
        "text_excerpt": str(item.get("text", ""))[:700],
        "metadata": item.get("metadata", {}),
    }


def _merge_llm_decisions(
    pending: list[dict[str, Any]],
    deterministic: list[dict[str, Any]],
    llm_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    by_source = {str(item.get("source_id")): item for item in llm_payload.get("decisions", []) if isinstance(item, dict)}
    merged: list[dict[str, Any]] = []
    for item, fallback in zip(pending, deterministic, strict=False):
        source_id = str(item.get("source_id"))
        candidate = by_source.get(source_id, {})
        if fallback["decision"] != "write":
            merged.append({**fallback, "decision_source": "deterministic_guardrail"})
            continue
        llm_decision = str(candidate.get("decision", fallback["decision"])).lower()
        if llm_decision not in {"write", "skip", "merge"}:
            llm_decision = fallback["decision"]
        merged.append(
            {
                **fallback,
                "decision": "write" if llm_decision in {"write", "merge"} else "skip",
                "reason": str(candidate.get("reason") or fallback["reason"])[:500],
                "importance": str(candidate.get("importance") or fallback.get("importance") or "medium"),
                "merge_with_source_id": candidate.get("merge_with_source_id"),
                "decision_source": "llm_memory_curator",
            }
        )
    return merged


async def curate_lifecycle_memory_items(user_id: str, pending: list[dict[str, Any]]) -> MemoryCurationResult:
    result = MemoryCurationResult()
    if not pending:
        return result

    deterministic = [_deterministic_memory_decision(item) for item in pending]
    query = " ".join(str(item.get("text", ""))[:500] for item in pending if item.get("text"))[:1800]
    memory_types = sorted({str(item.get("memory_type")) for item in pending if item.get("memory_type")})
    lookup_inputs: dict[str, Any] = {
        "user_id": user_id,
        "query": query or "lifecycle interview memory curation",
        "limit": 8,
    }
    if memory_types:
        lookup_inputs["memory_types"] = memory_types
    fallback_lookup = tool_decision(
        "Memory Curation Agent",
        "retrieve_memory_context",
        "Check existing long-term memory for duplicate lifecycle memories before curating writes.",
        lookup_inputs,
        required=False,
    )
    tool_run = await execute_autonomous_tool_selection(
        agent="memory",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the InterviewOS Memory Curation Agent. Use retrieval when needed to avoid duplicate "
                    "or low-value long-term memory writes."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Pending memory summaries: {json.dumps([_memory_summary(item) for item in pending], ensure_ascii=False)}\n"
                    f"User id: {user_id}"
                ),
            },
        ],
        available_tools=["retrieve_memory_context"],
        fallback_decisions=[fallback_lookup],
        max_total_tool_calls=1,
    )
    result.tool_decisions.extend(tool_run.tool_decisions)
    result.tool_results.extend(tool_run.tool_results)

    existing_memories = [
        memory
        for record in tool_run.tool_results
        if record.get("ok")
        for memory in record.get("data", {}).get("memories", [])
    ][:8]

    try:
        response = await llm_service.invoke_live(
            [
                {
                    "role": "system",
                    "content": (
                        "You are the InterviewOS Memory Curation Agent. Decide which lifecycle memories are "
                        "worth persisting. Deterministic guardrails already filtered very short text; focus on "
                        "novelty, weakness significance, deduplication, and future usefulness. Return only JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Return this JSON shape:\n"
                        '{"decisions":[{"source_id":"id","memory_type":"type","decision":"write|skip|merge",'
                        '"reason":"why","importance":"high|medium|low","merge_with_source_id":null}]}\n\n'
                        f"Pending memory JSON: {json.dumps([_memory_summary(item) for item in pending], ensure_ascii=False)}\n"
                        f"Deterministic guardrail decisions: {json.dumps(deterministic, ensure_ascii=False)}\n"
                        f"Similar existing memories: {json.dumps(existing_memories, ensure_ascii=False)}"
                    ),
                },
            ],
            agent="memory",
        )
        result.decisions = _merge_llm_decisions(pending, deterministic, json_from_text(response.content))
        result.provider = response.provider
        result.model = response.model
        result.fallback_used = False
    except Exception as exc:
        result.decisions = [{**item, "decision_source": "deterministic_fallback", "provider_error": f"{type(exc).__name__}: {exc}"} for item in deterministic]

    return result
