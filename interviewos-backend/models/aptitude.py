from typing import Any

from pydantic import BaseModel


class AptitudeSubmitRequest(BaseModel):
    interview_id: str
    answers: dict[str, str | dict[str, Any]]
    time_taken_seconds: int | None = None


class AptitudeQuestion(BaseModel):
    id: str
    interview_id: str
    question_number: int
    question_text: str
    options: dict[str, str]
    category: str
    difficulty: str
