from pydantic import BaseModel


class RoadmapCreateRequest(BaseModel):
    report_id: str | None = None
    target_role: str | None = None
    duration_days: int = 30


class RoadmapUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    isActive: bool | None = None
    milestones: list[dict] | None = None
    skills: list[dict] | None = None
    progress: float | None = None


class RoadmapRevisionRequest(BaseModel):
    instructions: str


class RoadmapRevisionApplyRequest(BaseModel):
    proposed_roadmap: dict
    make_active: bool = True
