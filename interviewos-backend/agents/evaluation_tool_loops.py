from __future__ import annotations

from typing import Any

from agents.tools.autonomous import execute_autonomous_tool_selection
from agents.tools.decision import ToolDecision, ToolExecutionRecord, tool_decision


def _safe_test_cases(cases: Any, limit: int = 3) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    if not isinstance(cases, list):
        return safe
    for index, case in enumerate(cases[:limit], start=1):
        if not isinstance(case, dict) or "input" not in case or "expected" not in case:
            continue
        safe.append(
            {
                "name": str(case.get("name") or f"Evaluator edge case {index}"),
                "input": case.get("input"),
                "expected": case.get("expected"),
            }
        )
    return safe


def _extra_score(records: list[ToolExecutionRecord]) -> float | None:
    scores = []
    for record in records:
        if not record.get("ok"):
            continue
        score = record.get("data", {}).get("score")
        if score is not None:
            try:
                scores.append(float(score))
            except (TypeError, ValueError):
                pass
    if not scores:
        return None
    return round(sum(scores) / len(scores), 2)


async def run_dsa_dynamic_tool_loop(
    *,
    problem: dict[str, Any],
    code: str,
    language: str,
    execution_result: dict[str, Any],
    time_taken_seconds: int | None = None,
) -> dict[str, Any]:
    fallback_cases = _safe_test_cases(problem.get("evaluation_edge_cases") or problem.get("extra_test_cases"))
    fallback_decisions: list[ToolDecision] = []
    if fallback_cases:
        fallback_decisions.append(
            tool_decision(
                "Evaluation Agent",
                "run_code",
                "Policy fallback: run configured evaluator edge cases before final DSA reasoning.",
                {
                    "code": code,
                    "language": language,
                    "test_cases": fallback_cases,
                    "problem_title": problem.get("title"),
                },
                required=False,
            )
        )

    tool_run = await execute_autonomous_tool_selection(
        agent="evaluation",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the InterviewOS DSA Evaluation Agent. Decide whether more code execution is needed "
                    "before final scoring. If the submitted code may hide edge-case bugs, call run_code with 1-3 "
                    "additional JSON test cases with expected outputs. If existing evidence is enough, choose no tool."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Problem: {problem.get('title')}\nDescription: {str(problem.get('description', ''))[:1800]}\n"
                    f"Difficulty: {problem.get('difficulty')}\nLanguage: {language}\nTime taken: {time_taken_seconds}\n"
                    f"Canonical execution result: {execution_result}\nCode excerpt:\n{code[:3500]}\n"
                    "When calling run_code, use exactly these argument keys: code, language, test_cases, problem_title."
                ),
            },
        ],
        available_tools=["run_code"],
        fallback_decisions=fallback_decisions,
        provider_order=("gemini", "groq"),
        max_tool_calls=2,
    )
    return {
        "tool_decisions": tool_run.tool_decisions,
        "tool_results": tool_run.tool_results,
        "provider_metadata": tool_run.provider_metadata,
        "summary": {
            "toolCallCount": len(tool_run.tool_decisions),
            "extraScore": _extra_score(tool_run.tool_results),
            "provider": tool_run.provider_metadata.get("provider"),
            "fallbackUsed": tool_run.provider_metadata.get("fallbackUsed", False),
            "results": [
                {
                    "tool": record.get("decision", {}).get("tool"),
                    "ok": record.get("ok"),
                    "score": record.get("data", {}).get("score"),
                    "status": record.get("data", {}).get("status"),
                    "testEvidence": record.get("data", {}).get("test_evidence"),
                    "error": record.get("error"),
                }
                for record in tool_run.tool_results
            ],
        },
    }


def fallback_round_tool_decisions(
    *,
    round_name: str,
    user_id: str,
    answer: str,
    question: dict[str, Any],
    interview: dict[str, Any],
    evaluation: dict[str, Any],
) -> list[ToolDecision]:
    score = float(evaluation.get("score") or 0)
    if score >= 70:
        return []
    query = " ".join(
        str(part)
        for part in [
            round_name,
            interview.get("target_role"),
            question.get("question_text") or question.get("question"),
            answer[:500],
            "weakness transcript prior examples",
        ]
        if part
    )
    return [
        tool_decision(
            "Evaluation Agent",
            "retrieve_memory_context",
            "Policy fallback: retrieve prior weak-answer memory before runtime follow-up decision.",
            {
                "user_id": user_id,
                "query": query,
                "limit": 3,
                "memory_types": ["transcript", "weakness", "report", "bot"],
            },
            required=False,
        )
    ]


async def run_round_evaluator_tool_loop(
    *,
    round_name: str,
    user_id: str,
    answer: str,
    question: dict[str, Any],
    interview: dict[str, Any],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    memory_count = 0
    return {
        "tool_decisions": [],
        "tool_results": [],
        "runtime_decision": {
            "should_follow_up": False,
            "follow_up_prompt": "",
            "reason": "hardcoded_follow_up_disabled",
            "memory_count": memory_count,
            "tool_selection": {"mode": "disabled", "skipped": "hardcoded_follow_up_removed"},
        },
    }
