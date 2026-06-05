from pydantic import BaseModel


class ReportGenerateRequest(BaseModel):
    interview_id: str


class ReportSection(BaseModel):
    name: str
    score: float
    maxScore: float = 100
    feedback: str
    details: dict
