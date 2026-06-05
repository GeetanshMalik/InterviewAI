from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any

from config import settings
from services.chroma import chroma_service
from services.file_service import extract_upload_text
from services.repository_service import repository_service
from services.llm_optimization import is_non_retryable_llm_error
from services.store import store
from services.workflow import append_workflow_event, ensure_workflow_job, update_workflow_job


InterviewAssetGenerator = Callable[[dict], Awaitable[dict]]
logger = logging.getLogger("interviewos.workflow_generation")


class WorkflowJobCancelled(Exception):
    """Raised when a workflow job is cancelled before its generated output is committed."""


def _assets_summary(assets: dict[str, Any]) -> dict[str, Any]:
    return {
        "dsa_problem_count": len(assets.get("dsa_problems", [])),
        "aptitude_question_count": len(assets.get("aptitude_questions", [])),
        "technical_question_count": len(assets.get("technical_questions", [])),
        "hr_question_count": len(assets.get("hr_questions", [])),
    }


async def _default_asset_generator(interview: dict) -> dict:
    from agents.graph import generate_interview_assets

    return await generate_interview_assets(interview)


def _interview_or_raise(interview_id: str) -> dict:
    interview = store.interviews.get(interview_id)
    if not interview:
        raise ValueError(f"Interview '{interview_id}' was not found.")
    return interview


def _persist_assets(interview: dict, assets: dict[str, Any]) -> None:
    repository_service.set_round_assets(interview["id"], assets, commit=False)


async def _hydrate_deferred_resume_text(interview: dict) -> None:
    if str(interview.get("resume_text") or "").strip():
        return
    resume_id = str(interview.get("resumeId") or "")
    resume = store.resumes.get(resume_id) if resume_id else None
    if not resume or str(resume.get("text") or "").strip():
        if resume and str(resume.get("text") or "").strip():
            interview["resume_text"] = str(resume.get("text") or "")
        return

    file_path = resume.get("filePath")
    if not file_path:
        return
    path = Path(file_path)
    if not path.exists():
        return

    started = asyncio.get_running_loop().time()
    content = await asyncio.to_thread(path.read_bytes)
    extracted_text = await asyncio.to_thread(extract_upload_text, resume.get("fileName") or path.name, content)
    if not extracted_text.strip():
        return

    resume["text"] = extracted_text
    interview["resume_text"] = extracted_text
    repository_service.upsert_resume(resume, commit=False)
    repository_service.update_interview(interview, {"resume_text": extracted_text}, commit=False)
    append_workflow_event(
        interview,
        "info",
        "Deferred resume text extraction completed in the workflow worker.",
        "form",
        {"duration_ms": round((asyncio.get_running_loop().time() - started) * 1000, 2)},
        agent="Resume Agent",
        commit=False,
    )


def _mirror_generation_logs(interview: dict, assets: dict[str, Any]) -> None:
    interview_id = interview["id"]
    for log in assets.get("logs", []):
        event_type = log.get("type", "info")
        agent = log.get("agent", "Interview Graph")
        message = log.get("message", "Graph step completed.")
        step = log.get("step", "form")
        repository_service.create_log(interview_id, event_type, agent, message, step, commit=False)
        append_workflow_event(
            interview,
            event_type,
            message,
            step,
            metadata=log.get("metadata", {}),
            agent=agent,
            commit=False,
        )


def _generation_memory_text(interview: dict, assets: dict[str, Any]) -> str:
    def item_text(item: dict[str, Any]) -> str:
        return str(item.get("title") or item.get("question_text") or item.get("description") or "")[:260]

    summary = {
        "role": interview.get("target_role"),
        "difficulty": interview.get("difficulty"),
        "company_style": interview.get("company_style"),
        "dsa": [
            {"category": item.get("category"), "title": item_text(item)}
            for item in assets.get("dsa_problems", [])[:3]
        ],
        "aptitude": [
            {"category": item.get("category"), "question": item_text(item)}
            for item in assets.get("aptitude_questions", [])[:5]
        ],
        "technical": [item_text(item) for item in assets.get("technical_questions", [])[:5]],
        "hr": [item_text(item) for item in assets.get("hr_questions", [])[:8]],
    }
    return json.dumps(summary, ensure_ascii=False)


async def _remember_generated_assets(interview: dict, assets: dict[str, Any]) -> None:
    if interview.get("ai_memory_enabled") is False:
        return
    user_id = str(interview.get("userId") or "")
    interview_id = str(interview.get("id") or "")
    if not user_id or not interview_id:
        return
    try:
        await asyncio.to_thread(
            chroma_service.add_memory,
            user_id,
            "generation",
            interview_id,
            _generation_memory_text(interview, assets),
            {
                "privacy_scope": "user",
                "interview_id": interview_id,
                "target_role": interview.get("target_role"),
                "difficulty": interview.get("difficulty"),
                "company_style": interview.get("company_style"),
                "source": "interview_generation",
            },
        )
    except Exception:
        logger.exception("Failed to remember generated interview assets for %s", interview_id)


async def _raise_if_cancelled(interview: dict, location: str) -> None:
    job = ensure_workflow_job(interview, commit=False)
    if job.get("cancelRequested") or job.get("status") == "cancelled":
        update_workflow_job(
            interview,
            status="cancelled",
            error="Workflow generation cancelled.",
            commit=False,
        )
        append_workflow_event(
            interview,
            "warning",
            f"Workflow generation cancelled {location}.",
            str(interview.get("currentStep") or "dsa"),
            {"cancelled_at": location},
            commit=False,
        )
        await repository_service.commit_async()
        raise WorkflowJobCancelled("Workflow generation cancelled.")


async def execute_interview_generation(
    interview_id: str,
    generator: InterviewAssetGenerator | None = None,
) -> dict[str, Any]:
    interview = _interview_or_raise(interview_id)
    ensure_workflow_job(interview, commit=False)
    await _raise_if_cancelled(interview, "before start")

    update_workflow_job(
        interview,
        status="running",
        current_node="generate_interview_assets",
        error=None,
        commit=False,
    )
    append_workflow_event(
        interview,
        "info",
        "Interview generation job started.",
        "form",
        {
            "job_kind": "interview_generation",
            "attempt": ensure_workflow_job(interview, commit=False).get("attempt", 0),
        },
        commit=False,
    )
    await repository_service.commit_async()

    try:
        await _hydrate_deferred_resume_text(interview)
        job_attempt = int(ensure_workflow_job(interview, commit=False).get("attempt") or 0)
        generation_interview = {**interview, "_workflow_generation_attempt": job_attempt}
        assets = await (generator or _default_asset_generator)(generation_interview)
    except asyncio.CancelledError:
        update_workflow_job(interview, status="cancelled", error="Workflow generation task cancelled.", commit=False)
        append_workflow_event(
            interview,
            "warning",
            "Workflow generation task cancelled.",
            str(interview.get("currentStep") or "dsa"),
            {"cancelled_by": "task"},
            commit=False,
        )
        await repository_service.commit_async()
        raise WorkflowJobCancelled("Workflow generation task cancelled.") from None

    await _raise_if_cancelled(interview, "before commit")
    _persist_assets(interview, assets)
    _mirror_generation_logs(interview, assets)
    repository_service.create_log(
        interview_id,
        "success",
        "Interview Orchestrator",
        "All interview rounds are ready.",
        "dsa",
        commit=False,
    )
    append_workflow_event(
        interview,
        "success",
        "All interview rounds are ready.",
        "dsa",
        metadata=_assets_summary(assets),
        agent="Interview Orchestrator",
        commit=False,
    )
    update_workflow_job(
        interview,
        status="succeeded",
        current_node="dsa",
        result={"assets": _assets_summary(assets), "workflow_state": assets.get("workflow_state", {})},
        error=None,
        commit=False,
    )
    await repository_service.commit_async()
    asyncio.create_task(_remember_generated_assets(interview, assets))
    return assets


async def run_interview_generation_with_retries(
    interview_id: str,
    generator: InterviewAssetGenerator | None = None,
) -> dict[str, Any]:
    interview = _interview_or_raise(interview_id)
    job = ensure_workflow_job(interview, commit=False)
    max_attempts = max(1, int(job.get("maxAttempts") or settings.workflow_job_max_attempts))
    delay = max(0.0, float(settings.workflow_retry_base_seconds))
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        await _raise_if_cancelled(interview, "before retry attempt")
        update_workflow_job(
            interview,
            status="running",
            current_node="generate_interview_assets",
            increment_attempt=True,
            error=None,
        )
        try:
            return await execute_interview_generation(interview_id, generator=generator)
        except WorkflowJobCancelled:
            raise
        except Exception as exc:
            last_error = exc
            message = f"{type(exc).__name__}: {exc}"
            non_retryable = is_non_retryable_llm_error(exc)
            if attempt >= max_attempts or non_retryable:
                update_workflow_job(
                    interview,
                    status="failed",
                    current_node="generate_interview_assets",
                    error=message,
                    commit=False,
                )
                append_workflow_event(
                    interview,
                    "error",
                    "Interview generation job failed after all retry attempts.",
                    "form",
                    {
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "non_retryable": non_retryable,
                        "error": message,
                    },
                    commit=False,
                )
                repository_service.create_log(
                    interview_id,
                    "error",
                    "Workflow Orchestrator Agent",
                    "Generation stopped without another retry because the provider error is quota/context related."
                    if non_retryable
                    else message,
                    "form",
                    commit=False,
                )
                await repository_service.commit_async()
                raise

            retry_delay = delay * (2 ** (attempt - 1))
            update_workflow_job(
                interview,
                status="retrying",
                current_node="generate_interview_assets",
                error=message,
                commit=False,
            )
            append_workflow_event(
                interview,
                "warning",
                f"Interview generation attempt {attempt} failed. Retrying.",
                "form",
                {
                    "retry": True,
                    "attempt": attempt,
                    "next_attempt": attempt + 1,
                    "max_attempts": max_attempts,
                    "retry_delay_seconds": retry_delay,
                    "error": message,
                },
                commit=False,
            )
            repository_service.create_log(
                interview_id,
                "warning",
                "Workflow Orchestrator Agent",
                f"Generation attempt {attempt} failed; retrying.",
                "form",
                commit=False,
            )
            await repository_service.commit_async()
            if retry_delay:
                await asyncio.sleep(retry_delay)

    raise last_error or RuntimeError("Interview generation failed.")
