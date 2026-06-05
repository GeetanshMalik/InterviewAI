from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile as FormUploadFile

from agents.aptitude_agent import public_questions
from agents.graph import generate_interview_assets
from auth.dependencies import get_current_user
from models.interview import InterviewCreate, StepUpdate, WorkflowActionRequest
from services.file_service import save_upload
from services.repository_service import repository_service
from services.store import iso_now, new_id, store
from services.workflow import (
    append_workflow_event,
    apply_workflow_action,
    build_orchestration_proof,
    build_workflow_state,
    ensure_workflow_job,
    update_workflow_job,
)
from services.workflow_queue import (
    WorkflowQueueUnavailable,
    enqueue_interview_generation,
    recover_stalled_redis_generation_if_needed,
    run_interview_generation_inline,
)
from config import settings


router = APIRouter()


def user_nested_setting(user: dict, section: str, key: str, fallback_key: str, default):
    settings_payload = user.get("settings") if isinstance(user.get("settings"), dict) else {}
    section_payload = settings_payload.get(section) if isinstance(settings_payload.get(section), dict) else {}
    if key in section_payload:
        return section_payload[key]
    return user.get(fallback_key, default)


async def parse_interview_payload(request: Request, *, extract_resume_text: bool = True) -> dict:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        skills = form.get("skills", "")
        if isinstance(skills, str):
            skill_list = [skill.strip() for skill in skills.split(",") if skill.strip()]
        else:
            skill_list = []
        upload = form.get("resume")
        resume_payload = None
        if isinstance(upload, FormUploadFile) and upload.filename:
            saved = await save_upload(upload, extract_text=extract_resume_text)
            resume_payload = {
                "id": new_id(),
                "fileName": saved["file_name"],
                "filePath": saved["file_path"],
                "text": saved.get("text", ""),
            }
        return {
            "name": str(form.get("name", "")),
            "email": str(form.get("email", "")),
            "target_role": str(form.get("target_role") or form.get("role") or ""),
            "company_style": str(form.get("company_style") or form.get("companyStyle") or "faang"),
            "difficulty": str(form.get("difficulty") or "medium"),
            "job_description": str(form.get("job_description") or form.get("jobDescription") or ""),
            "skills": skill_list,
            "preferred_language": str(form.get("preferred_language") or form.get("language") or "javascript"),
            "resume": resume_payload,
        }
    payload = await request.json()
    normalized = InterviewCreate(**payload).normalized()
    normalized["resume"] = None
    return normalized


@router.post("")
@router.post("/")
async def create_interview(
    request: Request,
    async_generation: bool = False,
    current_user: dict = Depends(get_current_user),
):
    queued = bool(async_generation or settings.workflow_async_generation)
    payload = await parse_interview_payload(request, extract_resume_text=True)
    if not payload["name"] or not payload["email"]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="name and email are required")

    resume = payload.get("resume")
    if resume:
        resume_record = {
            "id": resume["id"],
            "userId": current_user["id"],
            "fileName": resume["fileName"],
            "filePath": resume["filePath"],
            "uploadedAt": iso_now(),
            "text": resume.get("text", ""),
        }
        repository_service.upsert_resume(resume_record, commit=False)

    interview = {
        "id": new_id(),
        "userId": current_user["id"],
        "name": payload["name"],
        "email": payload["email"],
        "target_role": payload["target_role"],
        "company_style": payload["company_style"],
        "difficulty": payload["difficulty"],
        "job_description": payload["job_description"],
        "preferred_language": payload["preferred_language"],
        "skills": payload["skills"],
        "ai_memory_enabled": bool(user_nested_setting(current_user, "ai", "memoryEnabled", "ai_memory_enabled", True)),
        "show_execution_logs": bool(
            user_nested_setting(current_user, "interview", "showExecutionLogs", "show_execution_logs", True)
        ),
        "auto_save_answers": bool(
            user_nested_setting(current_user, "interview", "autoSaveAnswers", "auto_save_answers", True)
        ),
        "status": "in_progress",
        "currentStep": "dsa",
        "resumeId": resume["id"] if resume else None,
        "resume_text": resume.get("text", "") if resume else "",
        "overallScore": None,
        "createdAt": iso_now(),
        "completedAt": None,
    }
    repository_service.upsert_interview(interview, commit=False)
    ensure_workflow_job(interview, commit=False)
    repository_service.create_log(interview["id"], "info", "Interview Orchestrator", "Interview created.", "form", commit=False)
    repository_service.create_log(interview["id"], "info", "DSA Agent", "Generating DSA problems.", "dsa", commit=False)
    await repository_service.commit_async()

    assets = None
    if queued:
        try:
            await enqueue_interview_generation(interview["id"], require_durable=True)
            await recover_stalled_redis_generation_if_needed(interview, force=True)
        except WorkflowQueueUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Interview generation queue is unavailable. Start the workflow worker/Redis queue "
                    f"and try again. {exc}"
                ),
            ) from exc
    else:
        assets = await run_interview_generation_inline(
            interview["id"],
            generator=generate_interview_assets,
        )

    return {
        "interview": interview,
        "dsa_problems": (assets or {}).get("dsa_problems", store.dsa_problems.get(interview["id"], [])),
        "aptitude_questions": public_questions(
            (assets or {}).get("aptitude_questions", store.aptitude_questions.get(interview["id"], []))
        ),
        "technical_questions": (assets or {}).get("technical_questions", store.technical_questions.get(interview["id"], [])),
        "hr_questions": (assets or {}).get("hr_questions", store.hr_questions.get(interview["id"], [])),
        "workflow": build_workflow_state(interview),
        "assets_ready": not queued,
    }


@router.get("/{interview_id}/workflow")
async def get_workflow_state(interview_id: str, current_user: dict = Depends(get_current_user)):
    await repository_service.refresh_interview_async(interview_id)
    interview = store.interviews.get(interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    await recover_stalled_redis_generation_if_needed(interview)
    return build_workflow_state(interview)


@router.get("/{interview_id}/workflow/proof")
async def get_workflow_orchestration_proof(interview_id: str, current_user: dict = Depends(get_current_user)):
    await repository_service.refresh_interview_async(interview_id)
    interview = store.interviews.get(interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    return build_orchestration_proof(interview)


@router.post("/{interview_id}/actions")
async def run_workflow_action(
    interview_id: str,
    payload: WorkflowActionRequest,
    current_user: dict = Depends(get_current_user),
):
    await repository_service.refresh_interview_async(interview_id)
    interview = store.interviews.get(interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    if payload.action == "retry_generation":
        current_state = build_workflow_state(interview)
        if not any(action["action"] == "retry_generation" for action in current_state.get("allowedActions", [])):
            raise HTTPException(status_code=409, detail="Interview generation retry is not available for this workflow state.")
        update_workflow_job(
            interview,
            status="queued",
            current_node="queue_interview_generation",
            error=None,
            cancel_requested=False,
            commit=False,
        )
        append_workflow_event(
            interview,
            "warning",
            "Interview generation retry requested; creating a fresh durable queue payload.",
            "form",
            {**(payload.metadata or {}), "retry_generation": True},
            commit=False,
        )
        await repository_service.commit_async()
        if await recover_stalled_redis_generation_if_needed(interview, force=True):
            return build_workflow_state(interview)
        try:
            return await enqueue_interview_generation(interview["id"], require_durable=True)
        except WorkflowQueueUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Interview generation queue is unavailable. Start the workflow worker/Redis queue "
                    f"and try again. {exc}"
                ),
            ) from exc
    try:
        return await apply_workflow_action(
            interview,
            payload.action,
            target_step=payload.target_step,
            metadata=payload.metadata,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
@router.get("/")
async def list_interviews(current_user: dict = Depends(get_current_user)):
    await asyncio.to_thread(store.load)
    interviews = [item for item in store.interviews.values() if item["userId"] == current_user["id"]]
    return sorted(interviews, key=lambda item: item["createdAt"], reverse=True)


@router.get("/{interview_id}")
async def get_interview(interview_id: str, current_user: dict = Depends(get_current_user)):
    await repository_service.refresh_interview_async(interview_id)
    interview = store.interviews.get(interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    return {
        "interview": interview,
        "dsa_problems": store.dsa_problems.get(interview_id, []),
        "aptitude_questions": public_questions(store.aptitude_questions.get(interview_id, [])),
        "technical_questions": store.technical_questions.get(interview_id, []),
        "hr_questions": store.hr_questions.get(interview_id, []),
    }


@router.patch("/{interview_id}/step")
async def update_step(interview_id: str, payload: StepUpdate, current_user: dict = Depends(get_current_user)):
    await repository_service.refresh_interview_async(interview_id)
    interview = store.interviews.get(interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    repository_service.update_interview(interview, {"currentStep": payload.current_step}, commit=False)
    job = ensure_workflow_job(interview)
    job["currentNode"] = payload.current_step
    job["updatedAt"] = iso_now()
    repository_service.save_workflow_job(job, commit=False)
    repository_service.create_log(
        interview_id,
        "info",
        "Interview Orchestrator",
        f"Moved to {payload.current_step}.",
        payload.current_step,
        commit=False,
    )
    await repository_service.commit_async()
    return interview


@router.get("/{interview_id}/logs")
async def stream_logs_alias(interview_id: str, current_user: dict = Depends(get_current_user)):
    from routers.stream import event_generator

    await repository_service.refresh_interview_async(interview_id)
    interview = store.interviews.get(interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    return StreamingResponse(event_generator(interview_id, follow=False), media_type="text/event-stream")
