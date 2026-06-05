from __future__ import annotations

from typing import Any, Literal, TypedDict

from services.store import iso_now, new_id


BlackboardEntryType = Literal["proposal", "critique", "decision", "tool_observation", "revision", "security"]
BlackboardVisibility = Literal["internal", "checkpoint"]


class BlackboardEntry(TypedDict, total=False):
    id: str
    entry_type: BlackboardEntryType
    agent: str
    summary: str
    decision: str
    evidence_refs: list[str]
    payload: dict[str, Any]
    visibility: BlackboardVisibility
    created_at: str


def _safe_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in (payload or {}).items():
        lowered = key.lower()
        if "reasoning" in lowered or "chain" in lowered or "scratchpad" in lowered or "raw" in lowered:
            sanitized[key] = "[redacted]"
        else:
            sanitized[key] = value
    return sanitized


def blackboard_entry(
    *,
    entry_type: BlackboardEntryType,
    agent: str,
    summary: str,
    decision: str = "",
    evidence_refs: list[str] | None = None,
    payload: dict[str, Any] | None = None,
    visibility: BlackboardVisibility = "checkpoint",
) -> BlackboardEntry:
    return {
        "id": new_id(),
        "entry_type": entry_type,
        "agent": agent,
        "summary": summary[:600],
        "decision": decision[:120],
        "evidence_refs": evidence_refs or [],
        "payload": _safe_payload(payload),
        "visibility": visibility,
        "created_at": iso_now(),
    }


def append_blackboard(state: dict[str, Any], *entries: BlackboardEntry) -> list[BlackboardEntry]:
    return [*state.get("blackboard", []), *entries]


def checkpoint_blackboard(state: dict[str, Any]) -> list[BlackboardEntry]:
    return [
        entry
        for entry in state.get("blackboard", [])
        if entry.get("visibility") in {"checkpoint", "internal"}
    ]

