from fastapi import APIRouter, Depends, HTTPException

from agents.aptitude_agent import evaluate_answers, public_questions
from auth.dependencies import get_current_user
from models.aptitude import AptitudeSubmitRequest
from services.repository_service import repository_service
from services.store import store


router = APIRouter()


@router.get("/interviews/{interview_id}/questions")
async def list_questions(interview_id: str, current_user: dict = Depends(get_current_user)):
    interview = store.interviews.get(interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    return public_questions(store.aptitude_questions.get(interview_id, []))


@router.post("/submit")
async def submit_answers(payload: AptitudeSubmitRequest, current_user: dict = Depends(get_current_user)):
    interview = store.interviews.get(payload.interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    questions = store.aptitude_questions.get(payload.interview_id, [])
    result = evaluate_answers(questions, payload.answers)
    result["timeTakenSeconds"] = payload.time_taken_seconds
    repository_service.set_aptitude_result(payload.interview_id, result, commit=False)
    repository_service.create_log(
        payload.interview_id,
        "success",
        "Aptitude Agent",
        f"Aptitude scored {result['score']}/100.",
        "aptitude",
        commit=False,
    )
    await repository_service.commit_local_async()
    repository_service.commit_mirror_background()
    return result
