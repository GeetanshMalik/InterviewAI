from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from config import settings
from services.repository_service import repository_service
from services.store import iso_now, new_id, store, utc_now


ROUND_STEPS = ["dsa", "aptitude", "technical", "hr", "completed"]
ACTIVE_JOB_STATUSES = {"ready", "queued", "running", "retrying"}
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}
ORCHESTRATION_GRAPH_NODES = [
    {"id": "security_gatekeeper", "agent": "Security Gatekeeper Agent", "stage": "intake"},
    {"id": "prepare_candidate_profile", "agent": "Resume Agent", "stage": "context"},
    {"id": "retrieve_memory_context", "agent": "Memory Agent", "stage": "context"},
    {"id": "planning_agent_propose", "agent": "Planning Agent", "stage": "planning"},
    {"id": "critic_agents_review_plan", "agent": "Critic Agents", "stage": "planning"},
    {"id": "orchestrator_revise_plan", "agent": "Workflow Orchestrator Agent", "stage": "planning"},
    {"id": "generate_assets", "agent": "Round Generation Agents", "stage": "generation"},
    {"id": "dsa_section_agent", "agent": "DSA Agent", "stage": "generation"},
    {"id": "aptitude_section_agent", "agent": "Aptitude Agent", "stage": "generation"},
    {"id": "technical_section_agent", "agent": "Technical Interview Agent", "stage": "generation"},
    {"id": "hr_section_agent", "agent": "HR Interview Agent", "stage": "generation"},
    {"id": "reviewer_quality_gate", "agent": "Reviewer Agent", "stage": "quality"},
]


def _workflow_event(event_type: str, agent: str, message: str, step: str, metadata: dict[str, Any] | None = None) -> dict:
    return {
        "id": new_id(),
        "timestamp": iso_now(),
        "type": event_type,
        "agent": agent,
        "message": message,
        "step": step,
        "metadata": metadata or {},
    }


async def _commit_round_flow_response() -> None:
    await repository_service.commit_local_async()
    repository_service.commit_mirror_background()


def ensure_workflow_job(interview: dict, *, commit: bool = True) -> dict:
    interview_id = interview["id"]
    job = store.workflow_jobs.get(interview_id)
    if job:
        _normalize_workflow_job(job, interview)
        return job

    current_step = str(interview.get("currentStep") or "dsa")
    job = {
        "id": new_id(),
        "interviewId": interview_id,
        "userId": interview["userId"],
        "kind": "interview_generation",
        "status": "ready",
        "currentNode": current_step,
        "queueBackend": settings.workflow_queue_backend,
        "externalJobId": None,
        "workerId": None,
        "queuePosition": None,
        "queueDepth": None,
        "leaseExpiresAt": None,
        "visibilityTimeoutSeconds": None,
        "attempt": 0,
        "maxAttempts": max(1, settings.workflow_job_max_attempts),
        "cancelRequested": False,
        "queuedAt": None,
        "startedAt": None,
        "finishedAt": None,
        "lastHeartbeatAt": None,
        "events": [
            _workflow_event(
                "info",
                "Workflow Orchestrator Agent",
                "Backend workflow job created.",
                current_step,
            )
        ],
        "result": {},
        "error": None,
        "createdAt": iso_now(),
        "updatedAt": iso_now(),
    }
    repository_service.upsert_workflow_job(interview_id, job, commit=commit)
    return job


def _normalize_workflow_job(job: dict, interview: dict) -> None:
    current_step = str(interview.get("currentStep") or job.get("currentNode") or "dsa")
    job.setdefault("id", new_id())
    job.setdefault("interviewId", interview["id"])
    job.setdefault("userId", interview["userId"])
    job.setdefault("kind", "interview_generation")
    job.setdefault("status", "ready")
    job.setdefault("currentNode", current_step)
    job.setdefault("queueBackend", settings.workflow_queue_backend)
    job.setdefault("externalJobId", None)
    job.setdefault("workerId", None)
    job.setdefault("queuePosition", None)
    job.setdefault("queueDepth", None)
    job.setdefault("leaseExpiresAt", None)
    job.setdefault("visibilityTimeoutSeconds", None)
    job.setdefault("attempt", 0)
    job.setdefault("maxAttempts", max(1, settings.workflow_job_max_attempts))
    job.setdefault("cancelRequested", False)
    job.setdefault("queuedAt", None)
    job.setdefault("startedAt", None)
    job.setdefault("finishedAt", None)
    job.setdefault("lastHeartbeatAt", None)
    job.setdefault("events", [])
    job.setdefault("result", {})
    job.setdefault("error", None)
    job.setdefault("createdAt", iso_now())
    job.setdefault("updatedAt", iso_now())


def update_workflow_job(
    interview: dict,
    *,
    status: str | None = None,
    current_node: str | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    external_job_id: str | None = None,
    queue_backend: str | None = None,
    worker_id: str | None = None,
    queue_position: int | None = None,
    queue_depth: int | None = None,
    lease_expires_at: str | None = None,
    visibility_timeout_seconds: float | None = None,
    heartbeat: bool = False,
    increment_attempt: bool = False,
    cancel_requested: bool | None = None,
    commit: bool = True,
) -> dict:
    job = ensure_workflow_job(interview, commit=commit)
    now = iso_now()
    if status:
        job["status"] = status
        if status == "queued":
            job["queuedAt"] = job.get("queuedAt") or now
            job["finishedAt"] = None
        elif status == "running":
            job["startedAt"] = now
            job["finishedAt"] = None
        elif status in TERMINAL_JOB_STATUSES:
            job["finishedAt"] = now
    if current_node:
        job["currentNode"] = current_node
    if result is not None:
        job["result"] = result
    if error is not None or status in {"succeeded", "running", "queued", "retrying"}:
        job["error"] = error
    if external_job_id is not None:
        job["externalJobId"] = external_job_id
    if queue_backend is not None:
        job["queueBackend"] = queue_backend
    if worker_id is not None:
        job["workerId"] = worker_id
    if queue_position is not None:
        job["queuePosition"] = queue_position
    if queue_depth is not None:
        job["queueDepth"] = queue_depth
    if lease_expires_at is not None:
        job["leaseExpiresAt"] = lease_expires_at
    if visibility_timeout_seconds is not None:
        job["visibilityTimeoutSeconds"] = visibility_timeout_seconds
    if increment_attempt:
        job["attempt"] = int(job.get("attempt") or 0) + 1
    if cancel_requested is not None:
        job["cancelRequested"] = cancel_requested
    job["lastHeartbeatAt"] = now if status == "running" or heartbeat else job.get("lastHeartbeatAt")
    job["updatedAt"] = now
    repository_service.save_workflow_job(job, commit=commit)
    return job


def append_workflow_event(
    interview: dict,
    event_type: str,
    message: str,
    step: str | None = None,
    metadata: dict[str, Any] | None = None,
    agent: str = "Workflow Orchestrator Agent",
    *,
    commit: bool = True,
) -> dict:
    if not repository_service.execution_logs_enabled(str(interview.get("id", ""))):
        return _workflow_event(event_type, agent, message, step or str(interview.get("currentStep") or "dsa"), metadata)
    job = ensure_workflow_job(interview, commit=commit)
    event = _workflow_event(event_type, agent, message, step or str(interview.get("currentStep") or "dsa"), metadata)
    job.setdefault("events", []).append(event)
    job["updatedAt"] = iso_now()
    job["currentNode"] = str(job.get("currentNode") or interview.get("currentStep") or "dsa")
    repository_service.save_workflow_job(job, commit=commit)
    return event


def append_workflow_token_event(interview: dict, token: str, step: str, agent: str, metadata: dict[str, Any] | None = None) -> dict:
    return append_workflow_event(
        interview,
        "token",
        token,
        step,
        {**(metadata or {}), "llm_token": True},
        agent=agent,
    )


def _unique_submitted_problem_count(interview_id: str) -> int:
    return len({submission.get("problemId") for submission in store.dsa_submissions.get(interview_id, [])})


def round_progress(interview_id: str) -> dict[str, dict[str, Any]]:
    dsa_total = len(store.dsa_problems.get(interview_id, []))
    aptitude_total = len(store.aptitude_questions.get(interview_id, []))
    technical_total = len(store.technical_questions.get(interview_id, []))
    hr_total = len(store.hr_questions.get(interview_id, []))

    dsa_done = _unique_submitted_problem_count(interview_id)
    aptitude_done = aptitude_total if store.aptitude_results.get(interview_id) else 0
    technical_done = len(store.technical_answers.get(interview_id, []))
    hr_done = len(store.hr_answers.get(interview_id, []))

    return {
        "dsa": {
            "completed": dsa_done,
            "total": dsa_total,
            "isComplete": dsa_total > 0 and dsa_done >= dsa_total,
        },
        "aptitude": {
            "completed": aptitude_done,
            "total": aptitude_total,
            "isComplete": aptitude_total > 0 and bool(store.aptitude_results.get(interview_id)),
        },
        "technical": {
            "completed": technical_done,
            "total": technical_total,
            "isComplete": technical_total > 0 and technical_done >= technical_total,
        },
        "hr": {
            "completed": hr_done,
            "total": hr_total,
            "isComplete": hr_total > 0 and hr_done >= hr_total,
        },
    }


def _current_step(interview: dict) -> str:
    value = str(interview.get("currentStep") or "dsa")
    return value if value in ROUND_STEPS else "dsa"


def _next_step(step: str) -> str | None:
    if step not in ROUND_STEPS:
        return None
    index = ROUND_STEPS.index(step)
    if index >= len(ROUND_STEPS) - 1:
        return None
    return ROUND_STEPS[index + 1]


def _previous_steps(step: str) -> list[str]:
    if step not in ROUND_STEPS:
        return []
    return ROUND_STEPS[: ROUND_STEPS.index(step)]


def _age_seconds(value: Any) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=utc_now().tzinfo)
    return max(0.0, (utc_now() - parsed).total_seconds())


def _job_runtime_health(job: dict[str, Any]) -> dict[str, Any]:
    status = str(job.get("status") or "")
    elapsed = _age_seconds(job.get("queuedAt") or job.get("createdAt"))
    heartbeat_age = _age_seconds(job.get("lastHeartbeatAt"))
    visibility_timeout = float(job.get("visibilityTimeoutSeconds") or settings.workflow_queue_visibility_timeout_seconds)
    queued_stale_after = max(5.0, float(settings.workflow_queue_pickup_grace_seconds))
    running_stale_after = max(30.0, visibility_timeout + float(settings.workflow_worker_heartbeat_seconds) * 2)
    stale_reason = None

    if status == "queued" and elapsed is not None and elapsed > queued_stale_after and not job.get("workerId"):
        stale_reason = "queued_without_worker_heartbeat"
    elif status in {"running", "retrying"} and heartbeat_age is not None and heartbeat_age > running_stale_after:
        stale_reason = "worker_heartbeat_expired"

    return {
        "elapsedSeconds": round(elapsed, 2) if elapsed is not None else None,
        "heartbeatAgeSeconds": round(heartbeat_age, 2) if heartbeat_age is not None else None,
        "isStale": stale_reason is not None,
        "staleReason": stale_reason,
    }


def build_orchestration_proof(interview: dict, job: dict[str, Any] | None = None) -> dict[str, Any]:
    job = job or ensure_workflow_job(interview, commit=False)
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    workflow_state = result.get("workflow_state") if isinstance(result.get("workflow_state"), dict) else {}
    events = job.get("events", []) if isinstance(job.get("events"), list) else []
    agents = sorted({str(event.get("agent")) for event in events if event.get("agent")})
    section_reviews = workflow_state.get("section_generation_reviews")
    reviewer_critiques = workflow_state.get("reviewer_critiques")
    planning_critiques = workflow_state.get("planning_critiques")
    collaboration = workflow_state.get("collaboration_transcript")
    current_node = str(job.get("currentNode") or interview.get("currentStep") or "dsa")
    fallback_used = any(
        str((event.get("metadata") or {}).get("source") or "").startswith("local")
        or "fallback" in str(event.get("message") or "").lower()
        for event in events
    )
    return {
        "graphName": "interview_generation_graph",
        "graphNodes": ORCHESTRATION_GRAPH_NODES,
        "currentNode": current_node,
        "currentAgent": next(
            (node["agent"] for node in ORCHESTRATION_GRAPH_NODES if node["id"] == current_node),
            "Workflow Orchestrator Agent",
        ),
        "agentCount": len(agents),
        "agentsObserved": agents,
        "toolDecisionCount": int(workflow_state.get("tool_decision_count") or 0),
        "toolResultCount": int(workflow_state.get("tool_result_count") or 0),
        "blackboardCheckpointCount": int(workflow_state.get("blackboard_checkpoint_count") or 0),
        "planningCritiqueCount": len(planning_critiques) if isinstance(planning_critiques, list) else 0,
        "reviewerCritiqueCount": len(reviewer_critiques) if isinstance(reviewer_critiques, list) else 0,
        "sectionReviewCount": len(section_reviews) if isinstance(section_reviews, list) else 0,
        "collaborationTurnCount": len(collaboration) if isinstance(collaboration, list) else 0,
        "generationProfile": workflow_state.get("generation_profile"),
        "fallbackUsed": fallback_used,
        "artifactCounts": {
            "dsa": len(store.dsa_problems.get(interview["id"], [])),
            "aptitude": len(store.aptitude_questions.get(interview["id"], [])),
            "technical": len(store.technical_questions.get(interview["id"], [])),
            "hr": len(store.hr_questions.get(interview["id"], [])),
        },
        "timings": {
            "queuedAt": job.get("queuedAt"),
            "startedAt": job.get("startedAt"),
            "finishedAt": job.get("finishedAt"),
            "lastHeartbeatAt": job.get("lastHeartbeatAt"),
            "generationDurationMs": workflow_state.get("generation_duration_ms"),
            **_job_runtime_health(job),
        },
        "latestEvents": events[-20:],
    }


def allowed_workflow_actions(interview: dict) -> list[dict[str, Any]]:
    step = _current_step(interview)
    job = ensure_workflow_job(interview, commit=False)
    progress = round_progress(interview["id"])
    runtime_health = _job_runtime_health(job)
    if job.get("status") == "cancelled":
        return [
            {"action": "refresh_state", "label": "Refresh workflow state"},
            {"action": "retry_generation", "label": "Retry interview generation"},
            {"action": "restart_round", "targetStep": step, "label": f"Restart {step} round"},
        ]
    if step == "completed" or interview.get("status") == "completed":
        return [{"action": "refresh_state", "label": "Refresh workflow state"}]

    actions: list[dict[str, Any]] = [{"action": "refresh_state", "label": "Refresh workflow state"}]
    if job.get("status") in ACTIVE_JOB_STATUSES:
        actions.append({"action": "cancel_workflow", "label": "Cancel workflow job"})
    if job.get("status") == "failed" or runtime_health["isStale"]:
        actions.append({"action": "retry_generation", "label": "Retry interview generation"})
    actions.append(
        {
            "action": "restart_round",
            "targetStep": step,
            "label": f"Restart {step} round",
        }
    )

    for previous in _previous_steps(step):
        actions.append(
            {
                "action": "move_to_step",
                "targetStep": previous,
                "label": f"Return to {previous}",
            }
        )

    current_progress = progress.get(step, {})
    next_step = _next_step(step)
    if current_progress.get("isComplete") and next_step:
        actions.append(
            {
                "action": "move_to_next_step",
                "targetStep": next_step,
                "label": f"Continue to {next_step}",
            }
        )
        actions.append(
            {
                "action": "move_to_step",
                "targetStep": next_step,
                "label": f"Move to {next_step}",
            }
        )

    return actions


def build_workflow_state(interview: dict) -> dict[str, Any]:
    job = ensure_workflow_job(interview, commit=False)
    step = _current_step(interview)
    if not job.get("currentNode"):
        job["currentNode"] = step
        job["updatedAt"] = iso_now()
    runtime_health = _job_runtime_health(job)
    actions = allowed_workflow_actions(interview)
    next_action = next((action for action in actions if action["action"] == "move_to_next_step"), None)
    return {
        "interviewId": interview["id"],
        "currentStep": step,
        "status": interview.get("status", "in_progress"),
        "job": {
            "id": job["id"],
            "status": job.get("status", "ready"),
            "kind": job.get("kind", "interview_generation"),
            "currentNode": job.get("currentNode", step),
            "queueBackend": job.get("queueBackend"),
            "externalJobId": job.get("externalJobId"),
            "workerId": job.get("workerId"),
            "queuePosition": job.get("queuePosition"),
            "queueDepth": job.get("queueDepth"),
            "leaseExpiresAt": job.get("leaseExpiresAt"),
            "visibilityTimeoutSeconds": job.get("visibilityTimeoutSeconds"),
            "attempt": job.get("attempt", 0),
            "maxAttempts": job.get("maxAttempts", max(1, settings.workflow_job_max_attempts)),
            "cancelRequested": job.get("cancelRequested", False),
            "result": job.get("result", {}),
            "error": job.get("error"),
            "queuedAt": job.get("queuedAt"),
            "startedAt": job.get("startedAt"),
            "finishedAt": job.get("finishedAt"),
            "lastHeartbeatAt": job.get("lastHeartbeatAt"),
            "createdAt": job.get("createdAt"),
            "updatedAt": job.get("updatedAt"),
            **runtime_health,
        },
        "events": job.get("events", [])[-100:],
        "orchestration": build_orchestration_proof(interview, job),
        "roundProgress": round_progress(interview["id"]),
        "allowedActions": actions,
        "nextAction": next_action,
    }


def _action_allowed(interview: dict, action: str, target_step: str | None = None) -> bool:
    for allowed in allowed_workflow_actions(interview):
        if allowed["action"] != action:
            continue
        if target_step is None or allowed.get("targetStep") == target_step:
            return True
    return False


def _clear_round_state(interview_id: str, step: str) -> None:
    if step == "dsa":
        repository_service.clear_round_state(interview_id, "dsa", commit=False)
    elif step == "aptitude":
        repository_service.clear_round_state(interview_id, "aptitude", commit=False)
    elif step == "technical":
        repository_service.clear_round_state(interview_id, "technical", commit=False)
    elif step == "hr":
        repository_service.clear_round_state(interview_id, "hr", commit=False)


async def apply_workflow_action(interview: dict, action: str, target_step: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    job = ensure_workflow_job(interview, commit=False)
    current_step = _current_step(interview)

    if action == "refresh_state":
        append_workflow_event(interview, "info", "Workflow state refreshed.", current_step, metadata, commit=False)
        await _commit_round_flow_response()
        return build_workflow_state(interview)

    if action == "cancel_workflow":
        if not _action_allowed(interview, action, target_step):
            raise PermissionError(f"Action '{action}' is not allowed from step '{current_step}'.")
        update_workflow_job(
            interview,
            status=job.get("status") if job.get("status") == "running" else "cancelled",
            error="Workflow cancellation requested by user.",
            cancel_requested=True,
            commit=False,
        )
        append_workflow_event(
            interview,
            "warning",
            "Workflow cancellation requested.",
            current_step,
            {**(metadata or {}), "cancellation_requested": True},
            commit=False,
        )
        try:
            from services.workflow_queue import cancel_inprocess_workflow_job

            cancel_inprocess_workflow_job(interview["id"])
        except Exception:
            pass
        repository_service.create_log(
            interview["id"],
            "warning",
            "Workflow Orchestrator Agent",
            "Workflow job cancelled.",
            current_step,
            commit=False,
        )
        await _commit_round_flow_response()
        return build_workflow_state(interview)

    if action == "move_to_next_step":
        target_step = _next_step(current_step)

    if action == "restart_round":
        target_step = target_step or current_step

    if target_step is not None and target_step not in ROUND_STEPS:
        raise ValueError(f"Unsupported workflow step: {target_step}")

    if not _action_allowed(interview, action, target_step):
        raise PermissionError(f"Action '{action}' is not allowed from step '{current_step}'.")

    if action in {"move_to_next_step", "move_to_step"}:
        if not target_step:
            raise ValueError("target_step is required.")
        interview["currentStep"] = target_step
        if target_step == "completed":
            interview["status"] = "completed"
            interview["completedAt"] = interview.get("completedAt") or iso_now()
        job["currentNode"] = target_step
        append_workflow_event(
            interview,
            "success",
            f"Workflow moved from {current_step} to {target_step}.",
            target_step,
            metadata,
            commit=False,
        )
        repository_service.create_log(
            interview["id"],
            "info",
            "Workflow Orchestrator Agent",
            f"Moved to {target_step}.",
            target_step,
            commit=False,
        )

    elif action == "restart_round":
        if not target_step or target_step == "completed":
            raise ValueError("A restartable round target is required.")
        await asyncio.to_thread(_clear_round_state, interview["id"], target_step)
        interview["currentStep"] = target_step
        interview["status"] = "in_progress"
        interview["completedAt"] = None
        job["status"] = "ready"
        job["error"] = None
        job["cancelRequested"] = False
        job["attempt"] = 0
        job["queuedAt"] = None
        job["startedAt"] = None
        job["finishedAt"] = None
        job["currentNode"] = target_step
        append_workflow_event(
            interview,
            "warning",
            f"{target_step} round restarted by backend workflow action.",
            target_step,
            metadata,
            commit=False,
        )
        repository_service.create_log(
            interview["id"],
            "warning",
            "Workflow Orchestrator Agent",
            f"{target_step} round restarted.",
            target_step,
            commit=False,
        )

    else:
        raise ValueError(f"Unsupported workflow action: {action}")

    repository_service.upsert_interview(interview, commit=False)
    repository_service.save_workflow_job(job, commit=False)
    await _commit_round_flow_response()
    return build_workflow_state(interview)
