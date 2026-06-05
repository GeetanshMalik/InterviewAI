from fastapi import APIRouter, Depends, HTTPException

from agents.evaluation_agent import public_evaluation_payload
from agents.evaluation_tool_loops import run_dsa_dynamic_tool_loop
from agents.tools.decision import execute_tool_decision, tool_decision
from auth.dependencies import get_current_user
from models.dsa import DSARunRequest, DSASubmissionRequest
from services.judge0 import evaluate_with_judge0
from services.repository_service import repository_service
from services.store import iso_now, new_id, store


router = APIRouter()


def get_problem(problem_id: str) -> dict | None:
    for problems in store.dsa_problems.values():
        for problem in problems:
            if problem["id"] == problem_id:
                return problem
    return None


def _execution_fully_passed(evaluation: dict) -> bool:
    tests = evaluation.get("test_results") or evaluation.get("testResults") or []
    if not tests:
        return str(evaluation.get("status") or "").lower() == "passed"
    return str(evaluation.get("status") or "").lower() == "passed" and all(
        bool(test.get("passed")) for test in tests if isinstance(test, dict)
    )


def _skipped_dynamic_loop(reason: str) -> dict:
    return {
        "tool_decisions": [],
        "tool_results": [],
        "provider_metadata": {"skipped": True, "reason": reason},
        "summary": {
            "toolCallCount": 0,
            "extraScore": None,
            "provider": "local",
            "fallbackUsed": True,
            "skipped": reason,
            "results": [],
        },
    }


@router.get("/interviews/{interview_id}/problems")
async def list_problems(interview_id: str, current_user: dict = Depends(get_current_user)):
    interview = store.interviews.get(interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    return store.dsa_problems.get(interview_id, [])


@router.post("/run")
async def run_code(payload: DSARunRequest, current_user: dict = Depends(get_current_user)):
    problem = get_problem(payload.problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    return await evaluate_with_judge0(
        payload.code,
        payload.language,
        problem.get("test_cases", []),
        problem.get("title"),
    )


@router.post("/submissions")
async def submit_code(payload: DSASubmissionRequest, current_user: dict = Depends(get_current_user)):
    interview = store.interviews.get(payload.interview_id)
    problem = get_problem(payload.problem_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    existing_submission = next(
        (
            submission
            for submission in store.dsa_submissions.get(payload.interview_id, [])
            if submission.get("problemId") == payload.problem_id
        ),
        None,
    )
    if existing_submission:
        cached_submission = {**existing_submission, "dedupedEvaluation": True}
        return public_evaluation_payload(cached_submission)

    submission_decision = tool_decision(
        "DSA Agent",
        "evaluate_submission",
        "Evaluate submitted DSA code through the configured execution tool.",
        {
            "code": payload.code,
            "language": payload.language,
            "problem": problem,
        },
    )
    submission_record = await execute_tool_decision(submission_decision)
    if not submission_record["ok"]:
        status_code = int(submission_record.get("metadata", {}).get("status_code") or 502)
        raise HTTPException(status_code=status_code, detail=submission_record.get("error") or "DSA evaluation failed.")
    evaluation = submission_record["data"].get("evaluation", {})
    if _execution_fully_passed(evaluation):
        dynamic_loop = await run_dsa_dynamic_tool_loop(
            problem=problem,
            code=payload.code,
            language=payload.language,
            execution_result=evaluation,
            time_taken_seconds=payload.time_taken_seconds,
        )
    else:
        dynamic_loop = _skipped_dynamic_loop("canonical_execution_failed")
    dynamic_summary = dynamic_loop.get("summary", {})
    dynamic_score = dynamic_summary.get("extraScore")
    final_score = evaluation.get("score", 0)
    if dynamic_score is not None:
        try:
            final_score = round(float(evaluation.get("score", 0)) * 0.85 + float(dynamic_score) * 0.15, 2)
            evaluation["score"] = final_score
            evaluation["feedback"] = (
                f"{evaluation.get('feedback', '')} Dynamic evaluator edge-case score: {dynamic_score}/100."
            ).strip()
        except (TypeError, ValueError):
            final_score = evaluation.get("score", 0)
    reasoning_decision = tool_decision(
        "Evaluation Agent",
        "evaluate_dsa_reasoning",
        "Augment execution and dynamic tool-loop results with reasoning, complexity, and edge-case analysis.",
        {
            "problem": problem,
            "code": payload.code,
            "language": payload.language,
            "execution_result": evaluation,
            "time_taken_seconds": payload.time_taken_seconds,
            "dynamic_tool_evidence": dynamic_summary,
        },
    )
    reasoning_record = await execute_tool_decision(reasoning_decision)
    if not reasoning_record["ok"]:
        raise HTTPException(status_code=502, detail=reasoning_record.get("error") or "DSA reasoning evaluation failed.")
    reasoning_evaluation = reasoning_record["data"].get("evaluation", {})
    submission = {
        "id": new_id(),
        "interviewId": payload.interview_id,
        "problemId": payload.problem_id,
        "userId": current_user["id"],
        "code": payload.code,
        "language": payload.language,
        "status": evaluation["status"],
        "testResults": evaluation["test_results"],
        "timeTakenSeconds": payload.time_taken_seconds,
        "score": final_score,
        "submittedAt": iso_now(),
        "feedback": evaluation["feedback"],
        "toolDecisionRecords": [submission_record, *dynamic_loop.get("tool_results", []), reasoning_record],
        "dynamicEvaluation": dynamic_summary,
        "reasoningEvaluation": reasoning_evaluation,
    }
    repository_service.add_dsa_submission(payload.interview_id, submission, commit=False)
    repository_service.create_log(
        payload.interview_id,
        "success",
        "Evaluation Agent",
        f"DSA submission scored {evaluation['score']}/100 with reasoning score {reasoning_evaluation['reasoningScore']}/100.",
        "dsa",
        commit=False,
    )
    await repository_service.commit_local_async()
    repository_service.commit_mirror_background()
    return public_evaluation_payload(submission)


@router.post("/interviews/{interview_id}/submit")
async def submit_code_alias(interview_id: str, payload: DSASubmissionRequest, current_user: dict = Depends(get_current_user)):
    payload.interview_id = interview_id
    return await submit_code(payload, current_user)
