from fastapi import APIRouter, Depends, HTTPException

from agents.roadmap_agent import build_roadmap, preview_roadmap_update
from agents.tools.decision import execute_tool_decision, tool_decision
from auth.dependencies import get_current_user
from models.roadmap import RoadmapCreateRequest, RoadmapRevisionApplyRequest, RoadmapRevisionRequest, RoadmapUpdateRequest
from services.repository_service import repository_service
from services.store import iso_now, store


router = APIRouter()


async def remember_roadmap(user_id: str, roadmap: dict, source: str = "roadmap") -> dict:
    roadmap_text = "\n".join(
        [
            str(roadmap.get("title") or ""),
            str(roadmap.get("description") or ""),
            "\n".join(str(milestone.get("title", "")) for milestone in roadmap.get("milestones", [])),
            "\n".join(
                str(task.get("title", ""))
                for milestone in roadmap.get("milestones", [])
                for task in milestone.get("tasks", [])
            ),
        ]
    )
    decision = tool_decision(
        "Roadmap Agent",
        "write_memory",
        "Persist roadmap memory through the shared tool registry.",
        {
            "user_id": user_id,
            "memory_type": "roadmap",
            "source_id": roadmap["id"],
            "text": roadmap_text,
            "metadata": {
                "type": "roadmap",
                "source": source,
                "source_report_id": roadmap.get("sourceReportId", ""),
                "progress": roadmap.get("progress", 0),
                "privacy_scope": "user",
                "importance": "high",
                "source_agent": "Roadmap Agent",
                "source_route": "/api/roadmaps",
            },
        },
        required=False,
    )
    return await execute_tool_decision(decision)


def recompute_progress(roadmap: dict) -> None:
    tasks = [task for milestone in roadmap.get("milestones", []) for task in milestone.get("tasks", [])]
    completed = [task for task in tasks if task.get("completed")]
    roadmap["progress"] = round((len(completed) / max(len(tasks), 1)) * 100, 2)
    for milestone in roadmap.get("milestones", []):
        milestone["completed"] = all(task.get("completed") for task in milestone.get("tasks", []))
    roadmap["updatedAt"] = iso_now()


@router.get("")
@router.get("/")
async def list_roadmaps(current_user: dict = Depends(get_current_user)):
    return store.user_roadmaps(current_user["id"])


@router.get("/active")
async def active_roadmap(current_user: dict = Depends(get_current_user)):
    roadmap = store.active_roadmap(current_user["id"])
    if not roadmap:
        raise HTTPException(status_code=404, detail="Active roadmap not found")
    return roadmap


@router.get("/{roadmap_id}")
async def get_roadmap(roadmap_id: str, current_user: dict = Depends(get_current_user)):
    roadmap = store.roadmaps.get(roadmap_id)
    if not roadmap or roadmap["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    return roadmap


@router.post("")
@router.post("/")
async def create_roadmap(payload: RoadmapCreateRequest, current_user: dict = Depends(get_current_user)):
    report = store.reports.get(payload.report_id) if payload.report_id else None
    repository_service.deactivate_user_roadmaps(current_user["id"], commit=False)
    roadmap = await build_roadmap(current_user["id"], report, payload.target_role, payload.duration_days)
    repository_service.upsert_roadmap(roadmap, commit=False)
    await remember_roadmap(current_user["id"], roadmap, "create")
    await repository_service.commit_async()
    return roadmap


@router.put("/{roadmap_id}")
async def update_roadmap(roadmap_id: str, payload: RoadmapUpdateRequest, current_user: dict = Depends(get_current_user)):
    roadmap = store.roadmaps.get(roadmap_id)
    if not roadmap or roadmap["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    updates = payload.model_dump(exclude_unset=True)
    updates["updatedAt"] = iso_now()
    repository_service.update_roadmap(roadmap, updates, commit=False)
    await repository_service.commit_async()
    return roadmap


@router.post("/{roadmap_id}/revision-preview")
async def preview_revision(roadmap_id: str, payload: RoadmapRevisionRequest, current_user: dict = Depends(get_current_user)):
    roadmap = store.roadmaps.get(roadmap_id)
    if not roadmap or roadmap["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    report = store.reports.get(roadmap.get("sourceReportId")) if roadmap.get("sourceReportId") else None
    try:
        return await preview_roadmap_update(current_user["id"], roadmap, payload.instructions, report)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Roadmap Agent could not preview the update: {type(exc).__name__}: {exc}") from exc


@router.post("/{roadmap_id}/revision-apply")
async def apply_revision(roadmap_id: str, payload: RoadmapRevisionApplyRequest, current_user: dict = Depends(get_current_user)):
    roadmap = store.roadmaps.get(roadmap_id)
    if not roadmap or roadmap["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    proposed = payload.proposed_roadmap
    proposed["id"] = roadmap_id
    proposed["userId"] = current_user["id"]
    proposed["createdAt"] = roadmap.get("createdAt")
    proposed["updatedAt"] = iso_now()
    proposed["sourceReportId"] = roadmap.get("sourceReportId")
    proposed["isActive"] = payload.make_active
    recompute_progress(proposed)
    if payload.make_active:
        repository_service.deactivate_user_roadmaps(current_user["id"], commit=False)
    repository_service.upsert_roadmap(proposed, commit=False)
    await remember_roadmap(current_user["id"], proposed, "revision")
    await repository_service.commit_async()
    return proposed


@router.post("/{roadmap_id}/activate")
async def activate_roadmap(roadmap_id: str, current_user: dict = Depends(get_current_user)):
    roadmap = store.roadmaps.get(roadmap_id)
    if not roadmap or roadmap["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    repository_service.deactivate_user_roadmaps(current_user["id"], except_id=roadmap_id, commit=False)
    await repository_service.commit_async()
    return roadmap


@router.post("/{roadmap_id}/milestones/{milestone_id}/toggle")
async def toggle_milestone(roadmap_id: str, milestone_id: str, current_user: dict = Depends(get_current_user)):
    roadmap = store.roadmaps.get(roadmap_id)
    if not roadmap or roadmap["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    for milestone in roadmap.get("milestones", []):
        if milestone["id"] == milestone_id:
            next_value = not milestone.get("completed", False)
            milestone["completed"] = next_value
            for task in milestone.get("tasks", []):
                task["completed"] = next_value
            recompute_progress(roadmap)
            repository_service.upsert_roadmap(roadmap, commit=False)
            await repository_service.commit_async()
            return roadmap
    raise HTTPException(status_code=404, detail="Milestone not found")


@router.post("/{roadmap_id}/milestones/{milestone_id}/tasks/{task_id}/toggle")
async def toggle_task(roadmap_id: str, milestone_id: str, task_id: str, current_user: dict = Depends(get_current_user)):
    roadmap = store.roadmaps.get(roadmap_id)
    if not roadmap or roadmap["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    for milestone in roadmap.get("milestones", []):
        if milestone["id"] == milestone_id:
            for task in milestone.get("tasks", []):
                if task["id"] == task_id:
                    task["completed"] = not task.get("completed", False)
                    recompute_progress(roadmap)
                    repository_service.upsert_roadmap(roadmap, commit=False)
                    await repository_service.commit_async()
                    return roadmap
    raise HTTPException(status_code=404, detail="Task not found")


@router.delete("/{roadmap_id}")
async def archive_roadmap(roadmap_id: str, current_user: dict = Depends(get_current_user)):
    roadmap = store.roadmaps.get(roadmap_id)
    if not roadmap or roadmap["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    roadmap["isActive"] = False
    roadmap["archivedAt"] = iso_now()
    repository_service.upsert_roadmap(roadmap, commit=False)
    await repository_service.commit_async()
    return {"message": "Roadmap archived"}
