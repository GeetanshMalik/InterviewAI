from __future__ import annotations

from typing import Any, Literal, TypedDict

from agents.tools.registry import ToolRegistry, default_tool_registry
from services.store import new_id


class ToolDecision(TypedDict, total=False):
    id: str
    agent: str
    tool: str
    reason: str
    inputs: dict[str, Any]
    required: bool
    selectionMode: Literal["policy", "provider_tool_call"]


class ToolExecutionRecord(TypedDict, total=False):
    decision: ToolDecision
    ok: bool
    data: dict[str, Any]
    error: str | None
    metadata: dict[str, Any]


def tool_decision(
    agent: str,
    tool: str,
    reason: str,
    inputs: dict[str, Any],
    *,
    required: bool = True,
    selection_mode: Literal["policy", "provider_tool_call"] = "policy",
) -> ToolDecision:
    return {
        "id": new_id(),
        "agent": agent,
        "tool": tool,
        "reason": reason,
        "inputs": inputs,
        "required": required,
        "selectionMode": selection_mode,
    }


async def execute_tool_decision(
    decision: ToolDecision,
    registry: ToolRegistry = default_tool_registry,
) -> ToolExecutionRecord:
    result = await registry.arun(decision["tool"], **decision.get("inputs", {}))
    return {
        "decision": decision,
        "ok": result.ok,
        "data": result.data,
        "error": result.error,
        "metadata": result.metadata,
    }
