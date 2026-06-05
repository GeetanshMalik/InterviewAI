from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


InterviewStep = Literal["form", "dsa", "aptitude", "technical", "hr", "completed"]
DifficultyLevel = Literal["easy", "medium", "hard"]


class InterviewCreate(BaseModel):
    name: str
    email: str
    role: str | None = None
    target_role: str | None = None
    companyStyle: str | None = None
    company_style: str | None = None
    difficulty: DifficultyLevel = "medium"
    jobDescription: str | None = None
    job_description: str | None = None
    skills: list[str] = Field(default_factory=list)
    language: str | None = None
    preferred_language: str | None = None

    def normalized(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "email": self.email,
            "target_role": self.target_role or self.role or "Software Engineer",
            "company_style": self.company_style or self.companyStyle or "faang",
            "difficulty": self.difficulty,
            "job_description": self.job_description or self.jobDescription or "",
            "skills": self.skills,
            "preferred_language": self.preferred_language or self.language or "javascript",
        }


class StepUpdate(BaseModel):
    current_step: InterviewStep


class WorkflowActionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    action: str
    target_step: InterviewStep | None = Field(default=None, alias="targetStep")
    metadata: dict[str, Any] = Field(default_factory=dict)


class LogEvent(BaseModel):
    id: str
    timestamp: str
    type: Literal["info", "success", "error", "warning"]
    agent: str
    message: str
    interview_id: str
    step: InterviewStep | str = "form"
