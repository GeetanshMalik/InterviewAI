from pydantic import BaseModel


class ResumeAnalysisResponse(BaseModel):
    id: str
    userId: str
    fileName: str
    uploadedAt: str
    atsScore: float
    keywords: dict
    suggestions: list[dict]
    formatIssues: list[str]
    missingSkills: list[str]
