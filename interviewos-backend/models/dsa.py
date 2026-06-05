from typing import Any

from pydantic import BaseModel


class DSASubmissionRequest(BaseModel):
    interview_id: str
    problem_id: str
    code: str
    language: str = "javascript"
    time_taken_seconds: int | None = None


class DSARunRequest(BaseModel):
    problem_id: str
    code: str
    language: str = "javascript"


class DSAProblem(BaseModel):
    id: str
    interview_id: str
    problem_number: int
    category: str | None = None
    title: str
    description: str
    difficulty: str
    examples: list[dict[str, Any]]
    test_cases: list[dict[str, Any]]
    constraints: str
    tags: list[str]
