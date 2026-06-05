from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException

from agents.aptitude_agent import evaluate_answers
from agents.practice_agent import generate_practice_mcqs, public_practice_questions
from agents.tools.decision import execute_tool_decision, tool_decision
from auth.dependencies import get_current_user
from services.repository_service import repository_service
from services.store import iso_now, new_id, store


router = APIRouter()


class PracticeStartRequest(BaseModel):
    type: str
    difficulty: str = "medium"
    topic_filter: str | None = None
    question_count: int = Field(default=20, ge=5, le=30)


class PracticeSubmitRequest(BaseModel):
    answers: dict


async def remember_practice_session(user_id: str, session: dict, result: dict) -> dict:
    categories = [
        str(question.get("category") or question.get("skill_tested") or "")
        for question in session.get("privateQuestions", [])
        if isinstance(question, dict)
    ]
    misses = [
        item
        for item in result.get("per_question_results", [])
        if isinstance(item, dict) and not item.get("is_correct")
    ]
    text = (
        f"Practice mode: {session.get('mode')}. Difficulty: {session.get('difficulty')}. "
        f"Score: {result.get('score')}. Categories: {', '.join(categories[:12])}. "
        f"Missed questions: {len(misses)}."
    )
    decision = tool_decision(
        "Practice Agent",
        "write_memory",
        "Persist practice result memory for future adaptive practice generation.",
        {
            "user_id": user_id,
            "memory_type": "practice",
            "source_id": session["id"],
            "text": text,
            "metadata": {
                "type": "practice",
                "mode": session.get("mode"),
                "difficulty": session.get("difficulty"),
                "score": result.get("score"),
                "privacy_scope": "user",
                "importance": "medium",
            },
        },
        required=False,
    )
    return await execute_tool_decision(decision)


def public_session(session: dict) -> dict:
    private_questions = session.get("privateQuestions")
    questions = public_practice_questions(private_questions) if isinstance(private_questions, list) else session.get("questions", [])
    return {
        **{key: value for key, value in session.items() if key != "privateQuestions"},
        "questions": questions,
    }


@router.post("/session/start")
async def start_session(payload: PracticeStartRequest, current_user: dict = Depends(get_current_user)):
    session_id = new_id()
    history_decision = tool_decision(
        "Practice Agent",
        "retrieve_practice_history",
        "Retrieve previous practice sessions to avoid repeated patterns.",
        {"user_id": current_user["id"], "limit": 5, "mode": payload.type},
        required=False,
    )
    history_result = await execute_tool_decision(history_decision)
    history = history_result.get("data", {}).get("sessions", []) if history_result.get("ok") else []
    try:
        questions = await generate_practice_mcqs(
            payload.type,
            payload.difficulty,
            payload.topic_filter,
            count=payload.question_count,
            history=history,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Something went wrong while generating questions. {exc} Please try again.",
        ) from exc
    session = {
        "id": session_id,
        "userId": current_user["id"],
        "mode": payload.type,
        "difficulty": payload.difficulty,
        "topicFilter": payload.topic_filter,
        "startedAt": iso_now(),
        "endedAt": None,
        "score": 0,
        "questions": public_practice_questions(questions),
        "privateQuestions": questions,
        "results": None,
    }
    repository_service.add_practice_session(session, commit=False)
    await repository_service.commit_async()
    return {"session_id": session_id, "questions": session["questions"], "session": public_session(session)}


@router.post("/session/{session_id}/submit")
async def submit_session(session_id: str, payload: PracticeSubmitRequest, current_user: dict = Depends(get_current_user)):
    session = store.practice_sessions.get(session_id)
    if not session or session["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Practice session not found")
    questions = session.get("privateQuestions", [])
    result = evaluate_answers(questions, payload.answers)
    repository_service.update_practice_session(
        session,
        {"score": result["score"], "endedAt": iso_now(), "results": result},
        commit=False,
    )
    await remember_practice_session(current_user["id"], session, result)
    await repository_service.commit_async()
    return result


@router.get("/sessions")
async def list_sessions(current_user: dict = Depends(get_current_user)):
    sessions = [session for session in store.practice_sessions.values() if session["userId"] == current_user["id"]]
    return [public_session(session) for session in sorted(sessions, key=lambda item: item["startedAt"], reverse=True)]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, current_user: dict = Depends(get_current_user)):
    session = store.practice_sessions.get(session_id)
    if not session or session["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Practice session not found")
    return public_session(session)


@router.get("/recommended")
async def recommended(current_user: dict = Depends(get_current_user)):
    latest = store.user_reports(current_user["id"])[:1]
    weakness = latest[0]["weaknesses"][0] if latest else "DSA"
    return {
        "recommended_type": weakness.lower() if weakness.lower() in {"dsa", "aptitude", "hr"} else "mixed",
        "recommended_topics": [weakness, "timed drills"],
        "reason": "Based on your lowest recent report section." if latest else "Start with mixed practice to establish a baseline.",
    }
