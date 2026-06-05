import asyncio
from typing import Any

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException

from agents.evaluation_agent import public_evaluation_payload
from agents.evaluation_tool_loops import run_round_evaluator_tool_loop
from agents.tools.decision import execute_tool_decision, tool_decision
from auth.dependencies import get_current_user
from services.llm import llm_service
from services.round_runtime import (
    advance_runtime_after_answer,
    build_round_runtime_state,
    record_round_command,
    start_round_runtime,
)
from services.repository_service import repository_service
from services.store import iso_now, new_id, store


router = APIRouter()


class HRAnswerRequest(BaseModel):
    interview_id: str
    question_id: str
    answer: str
    transcript_confidence: float | None = None
    answer_mode: str | None = None
    time_taken_seconds: int | None = None
    timer_expired: bool = False
    speech_metrics: dict[str, Any] | None = None
    proctor_events: list[dict[str, Any]] = Field(default_factory=list)
    repeat_count: int = 0
    paraphrase_count: int = 0
    answer_source: str | None = None


class ParaphraseRequest(BaseModel):
    interview_id: str
    question_id: str
    question_text: str


class RuntimeCommandRequest(BaseModel):
    command: str
    question_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _empty_runtime_tool_loop(reason: str) -> dict[str, Any]:
    return {
        "tool_results": [],
        "runtime_decision": {
            "should_follow_up": False,
            "follow_up_prompt": "",
            "reason": reason,
            "memory_count": 0,
            "tool_selection": {"skipped": True},
        },
    }


@router.get("/interviews/{interview_id}/questions")
async def list_questions(interview_id: str, current_user: dict = Depends(get_current_user)):
    interview = store.interviews.get(interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    return store.hr_questions.get(interview_id, [])


@router.delete("/interviews/{interview_id}/answers")
async def clear_answers(interview_id: str, current_user: dict = Depends(get_current_user)):
    interview = store.interviews.get(interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    await asyncio.to_thread(repository_service.clear_round_state, interview_id, "hr", commit=False)
    repository_service.create_log(
        interview_id,
        "warning",
        "HR Agent",
        "HR round answers cleared for same-round restart.",
        "hr",
        commit=False,
    )
    await repository_service.commit_local_async()
    repository_service.commit_mirror_background()
    return {"message": "HR answers cleared"}


@router.post("/answers")
async def submit_answer(payload: HRAnswerRequest, current_user: dict = Depends(get_current_user)):
    interview = store.interviews.get(payload.interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    question = next((item for item in store.hr_questions.get(payload.interview_id, []) if item["id"] == payload.question_id), None)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    answer_source = payload.answer_source or "spoken_submit"
    existing_answer = next(
        (
            item
            for item in store.hr_answers.get(payload.interview_id, [])
            if item.get("questionId") == payload.question_id
            and item.get("answer") == payload.answer
            and item.get("answerSource") == answer_source
        ),
        None,
    )
    if existing_answer:
        cached_answer = {**existing_answer, "dedupedEvaluation": True}
        cached_answer["runtime"] = build_round_runtime_state(interview, "hr")
        return public_evaluation_payload(cached_answer)

    evaluation_decision = tool_decision(
        "Evaluation Agent",
        "evaluate_round_answer",
        "Evaluate an HR answer through the structured rubric tool.",
        {
            "round_name": "hr",
            "answer": payload.answer,
            "question": question,
            "interview": interview,
            "transcript_confidence": payload.transcript_confidence,
            "answer_mode": payload.answer_mode or "spoken",
            "time_taken_seconds": payload.time_taken_seconds,
            "timer_expired": payload.timer_expired,
            "speech_metrics": payload.speech_metrics or {},
            "proctor_events": payload.proctor_events,
            "repeat_count": payload.repeat_count,
            "paraphrase_count": payload.paraphrase_count,
            "answer_source": answer_source,
        },
    )
    evaluation_record = await execute_tool_decision(evaluation_decision)
    if not evaluation_record["ok"]:
        raise HTTPException(status_code=502, detail=evaluation_record.get("error") or "HR evaluation failed.")
    evaluation = evaluation_record["data"].get("evaluation", {})
    if answer_source in {"pass", "dont_know", "time_expired", "end_call"} or not payload.answer.strip():
        runtime_tool_loop = _empty_runtime_tool_loop("skip_follow_up_for_empty_or_finalized_answer")
    else:
        runtime_tool_loop = await run_round_evaluator_tool_loop(
            round_name="hr",
            user_id=current_user["id"],
            answer=payload.answer,
            question=question,
            interview=interview,
            evaluation={**evaluation, "answerSource": answer_source},
        )
    answer = {
        "id": new_id(),
        "interviewId": payload.interview_id,
        "questionId": payload.question_id,
        "answer": payload.answer,
        "score": evaluation["score"],
        "feedback": evaluation["feedback"],
        "matchedKeywords": evaluation["matched_keywords"],
        "safetyFlags": evaluation.get("safety_flags", []),
        "rubric": evaluation.get("rubric", {}),
        "evidence": evaluation.get("evidence", []),
        "improvementSuggestions": evaluation.get("improvementSuggestions", []),
        "confidenceScore": evaluation.get("confidenceScore"),
        "communicationScore": evaluation.get("communicationScore"),
        "biasGuardrails": evaluation.get("biasGuardrails", []),
        "evaluationAgent": evaluation.get("evaluationAgent", "Evaluation Agent"),
        "evaluationProvider": evaluation.get("evaluationProvider"),
        "evaluationModel": evaluation.get("evaluationModel"),
        "evaluatedAt": evaluation.get("evaluatedAt"),
        "internalEvaluationTrace": evaluation.get("internalReasoningTrace", {}),
        "toolDecisionRecords": [evaluation_record, *runtime_tool_loop.get("tool_results", [])],
        "evaluatorRuntimeDecision": runtime_tool_loop.get("runtime_decision", {}),
        "transcriptConfidence": payload.transcript_confidence,
        "answerMode": payload.answer_mode or "spoken",
        "timeTakenSeconds": payload.time_taken_seconds,
        "timerExpired": payload.timer_expired,
        "speechMetrics": payload.speech_metrics or {},
        "proctorEvents": payload.proctor_events,
        "repeatCount": payload.repeat_count,
        "paraphraseCount": payload.paraphrase_count,
        "answerSource": answer_source,
        "submittedAt": iso_now(),
    }
    repository_service.add_round_answer(payload.interview_id, "hr", answer, commit=False)
    runtime_state = advance_runtime_after_answer(interview, "hr", answer)
    repository_service.create_log(
        payload.interview_id,
        "success",
        "Evaluation Agent",
        f"HR answer scored {answer['score']}/100 with rubric evidence.",
        "hr",
        commit=False,
    )
    await repository_service.commit_local_async()
    repository_service.commit_mirror_background()
    answer["runtime"] = runtime_state
    return public_evaluation_payload(answer)


@router.get("/interviews/{interview_id}/runtime")
async def get_runtime(interview_id: str, current_user: dict = Depends(get_current_user)):
    interview = store.interviews.get(interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    return build_round_runtime_state(interview, "hr")


@router.post("/interviews/{interview_id}/runtime/start")
async def start_runtime(interview_id: str, current_user: dict = Depends(get_current_user)):
    interview = store.interviews.get(interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    try:
        state = start_round_runtime(interview, "hr", commit=False)
        await repository_service.commit_local_async()
        repository_service.commit_mirror_background()
        return state
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/interviews/{interview_id}/runtime/commands")
async def record_runtime_command(
    interview_id: str,
    payload: RuntimeCommandRequest,
    current_user: dict = Depends(get_current_user),
):
    interview = store.interviews.get(interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    state = record_round_command(
        interview,
        "hr",
        payload.command,
        question_id=payload.question_id,
        metadata=payload.metadata,
        commit=False,
    )
    await repository_service.commit_local_async()
    repository_service.commit_mirror_background()
    return state


@router.post("/paraphrase")
async def paraphrase_question(payload: ParaphraseRequest, current_user: dict = Depends(get_current_user)):
    interview = store.interviews.get(payload.interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    question = next((item for item in store.hr_questions.get(payload.interview_id, []) if item["id"] == payload.question_id), None)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    try:
        response = await llm_service.invoke_live(
            [
                {
                    "role": "system",
                    "content": "Paraphrase HR interview questions neutrally. Return one plain sentence, no markdown.",
                },
                {
                    "role": "user",
                    "content": f"Paraphrase this question without changing its meaning:\n{payload.question_text}",
                },
            ]
        )
        text = str(response.content or "").strip()
        if len(text) < 20:
            raise RuntimeError("Provider returned an unusable paraphrase.")
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Live HR paraphrase generation failed. No fallback paraphrase was generated.",
        ) from exc

    return {"paraphrase": text}
