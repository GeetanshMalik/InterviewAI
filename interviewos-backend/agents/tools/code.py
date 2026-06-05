from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from agents.tools.base import ToolResult, tool_error, tool_success
from services.judge0 import evaluate_with_judge0


def _test_evidence(evaluation: dict[str, Any]) -> dict[str, Any]:
    tests = evaluation.get("test_results") or evaluation.get("testResults") or []
    passed = [item for item in tests if isinstance(item, dict) and item.get("passed")]
    failed = [item for item in tests if isinstance(item, dict) and not item.get("passed")]
    return {
        "total": len(tests),
        "passed": len(passed),
        "failed": len(failed),
        "first_failure": failed[0] if failed else None,
        "stderr": [item.get("stderr") for item in failed if isinstance(item, dict) and item.get("stderr")][:3],
        "compile_output": [
            item.get("compileOutput") or item.get("compile_output")
            for item in failed
            if isinstance(item, dict) and (item.get("compileOutput") or item.get("compile_output"))
        ][:3],
    }


async def run_code(
    code: str,
    language: str,
    test_cases: list[dict[str, Any]],
    problem_title: str | None = None,
) -> ToolResult:
    try:
        evaluation = await evaluate_with_judge0(code, language, test_cases, problem_title)
    except HTTPException as exc:
        return tool_error(
            "run_code",
            str(exc.detail),
            {"status_code": exc.status_code, "language": language, "problem_title": problem_title},
        )

    return tool_success(
        "run_code",
        {
            "evaluation": evaluation,
            "status": evaluation.get("status"),
            "score": evaluation.get("score"),
            "feedback": evaluation.get("feedback"),
            "test_evidence": _test_evidence(evaluation),
        },
        {"language": language, "problem_title": problem_title},
    )


async def evaluate_submission(
    code: str,
    language: str,
    problem: dict[str, Any],
    submission_id: str | None = None,
) -> ToolResult:
    result = await run_code(
        code,
        language,
        problem.get("test_cases", []),
        problem.get("title"),
    )
    result.name = "evaluate_submission"
    result.metadata.update(
        {
            "problem_id": problem.get("id"),
            "submission_id": submission_id,
            "problem_title": problem.get("title"),
        }
    )
    return result

