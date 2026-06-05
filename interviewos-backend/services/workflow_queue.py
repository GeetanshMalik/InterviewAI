from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import socket
from datetime import datetime, timedelta
from typing import Any

from config import settings
from services.repositories.manager import persistence_manager
from services.repository_service import repository_service
from services.store import iso_now, new_id, store, utc_now
from services.workflow import append_workflow_event, build_workflow_state, ensure_workflow_job, update_workflow_job
from services.workflow_generation import InterviewAssetGenerator, WorkflowJobCancelled, run_interview_generation_with_retries


_IN_PROCESS_TASKS: dict[str, asyncio.Task] = {}
logger = logging.getLogger("interviewos.workflow_queue")


class WorkflowQueueUnavailable(Exception):
    """Raised when async workflow generation cannot be handed to a durable worker queue."""


def _cleanup_inprocess_task(interview_id: str, finished: asyncio.Task) -> None:
    _IN_PROCESS_TASKS.pop(interview_id, None)
    if finished.cancelled():
        return
    try:
        finished.result()
    except Exception:
        logger.exception("In-process workflow job finished with an error")


def _queue_backend() -> str:
    backend = str(settings.workflow_queue_backend or "inprocess").strip().lower()
    return backend if backend in {"inprocess", "redis"} else "inprocess"


def _redis_payload(interview_id: str, job_id: str) -> dict[str, Any]:
    return {
        "id": new_id(),
        "job_id": job_id,
        "interview_id": interview_id,
        "kind": "interview_generation",
        "queued_at": iso_now(),
    }


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _worker_registry_key() -> str:
    return f"{settings.workflow_queue_name}:workers"


def _worker_heartbeat_fresh_for() -> float:
    return max(
        float(settings.workflow_queue_pickup_grace_seconds),
        float(settings.workflow_worker_heartbeat_seconds) * 3,
    )


def _parse_age_seconds(value: Any) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=utc_now().tzinfo)
    return max(0.0, (utc_now() - parsed).total_seconds())


def _lease_expires_at() -> str:
    return (utc_now() + timedelta(seconds=max(1.0, float(settings.workflow_queue_visibility_timeout_seconds)))).isoformat()


def _terminal(status: str | None) -> bool:
    return str(status or "") in {"succeeded", "failed", "cancelled"}


def _age_seconds(value: Any) -> float | None:
    return _parse_age_seconds(value)


async def _has_fresh_worker_heartbeat() -> bool:
    heartbeat = _latest_worker_heartbeat(await _read_redis_worker_heartbeat())
    age = heartbeat.get("latestHeartbeatAgeSeconds")
    if age is None:
        return False
    return float(age) <= _worker_heartbeat_fresh_for()


async def run_interview_generation_inline(
    interview_id: str,
    generator: InterviewAssetGenerator | None = None,
) -> dict[str, Any]:
    interview = store.interviews[interview_id]
    job = update_workflow_job(
        interview,
        status="queued",
        current_node="generate_interview_assets",
        queue_backend="inline",
        error=None,
        cancel_requested=False,
    )
    append_workflow_event(
        interview,
        "info",
        "Interview generation queued for inline execution.",
        "form",
        {"queue_backend": "inline", "job_id": job["id"]},
    )
    return await run_interview_generation_with_retries(interview_id, generator=generator)


def _mark_queue_unavailable(interview: dict, backend: str, error: str, *, commit: bool = True) -> None:
    update_workflow_job(
        interview,
        status="failed",
        current_node="queue_interview_generation",
        queue_backend=backend,
        error=error,
        commit=commit,
    )
    append_workflow_event(
        interview,
        "error",
        "Durable workflow queue is unavailable; interview generation was not started in the API process.",
        "form",
        {"queue_backend": backend, "durable_queue_required": True, "error": error},
        commit=commit,
    )


def _start_inprocess_generation(interview_id: str, interview: dict, job: dict) -> dict[str, Any]:
    task = asyncio.create_task(run_interview_generation_with_retries(interview_id))
    _IN_PROCESS_TASKS[interview_id] = task
    append_workflow_event(
        interview,
        "info",
        "Interview generation enqueued in the in-process worker.",
        "form",
        {"queue_backend": "inprocess", "job_id": job["id"]},
    )
    task.add_done_callback(lambda finished: _cleanup_inprocess_task(interview_id, finished))
    return build_workflow_state(interview)


async def _should_recover_stalled_redis_job(interview: dict, *, force: bool = False) -> bool:
    if not settings.workflow_recover_stalled_redis_jobs_in_api:
        return False
    job = ensure_workflow_job(interview, commit=False)
    if str(job.get("status") or "") != "queued":
        return False
    if str(job.get("queueBackend") or "").lower() != "redis":
        return False
    if job.get("workerId") or job.get("lastHeartbeatAt") or job.get("cancelRequested"):
        return False
    task = _IN_PROCESS_TASKS.get(interview["id"])
    if task and not task.done():
        return False
    if await _has_fresh_worker_heartbeat():
        return False
    if force:
        return True
    elapsed = _age_seconds(job.get("queuedAt") or job.get("createdAt"))
    return elapsed is not None and elapsed >= max(0.0, float(settings.workflow_queue_pickup_grace_seconds))


async def recover_stalled_redis_generation_if_needed(interview: dict, *, force: bool = False) -> bool:
    if not await _should_recover_stalled_redis_job(interview, force=force):
        return False

    job = ensure_workflow_job(interview, commit=False)
    append_workflow_event(
        interview,
        "warning",
        "Redis accepted the workflow job, but no worker heartbeat was detected. Recovering generation in the API background worker.",
        "form",
        {
            "queue_backend": "redis",
            "recovered_queue_backend": "inprocess",
            "external_job_id": job.get("externalJobId"),
            "queue_position": job.get("queuePosition"),
            "queue_depth": job.get("queueDepth"),
            "forced": force,
        },
        commit=False,
    )
    job["queueBackend"] = "inprocess"
    job["externalJobId"] = None
    job["queuePosition"] = None
    job["queueDepth"] = None
    repository_service.save_workflow_job(job, commit=False)
    await repository_service.commit_async()
    _start_inprocess_generation(interview["id"], interview, job)
    return True


async def enqueue_interview_generation(interview_id: str, *, require_durable: bool = False) -> dict[str, Any]:
    interview = store.interviews[interview_id]
    job = ensure_workflow_job(interview, commit=False)
    backend = _queue_backend()
    update_workflow_job(
        interview,
        status="queued",
        current_node="generate_interview_assets",
        queue_backend=backend,
        error=None,
        cancel_requested=False,
        commit=False,
    )

    if require_durable and backend != "redis":
        error = (
            "Async interview generation requires WORKFLOW_QUEUE_BACKEND=redis and a dedicated worker. "
            f"Current backend is '{backend}'."
        )
        _mark_queue_unavailable(interview, backend, error, commit=False)
        await repository_service.commit_async()
        raise WorkflowQueueUnavailable(error)

    if backend == "redis":
        try:
            enqueue_result = await asyncio.wait_for(
                _enqueue_redis(interview_id, job["id"]),
                timeout=max(0.1, float(settings.workflow_enqueue_timeout_seconds)),
            )
            if isinstance(enqueue_result, dict):
                external_job_id = str(enqueue_result.get("external_job_id") or enqueue_result.get("id") or "")
                queue_position = enqueue_result.get("queue_position")
                queue_depth = enqueue_result.get("queue_depth")
            else:
                external_job_id = str(enqueue_result)
                queue_position = None
                queue_depth = None
            update_workflow_job(
                interview,
                external_job_id=external_job_id,
                queue_position=int(queue_position) if isinstance(queue_position, int) else None,
                queue_depth=int(queue_depth) if isinstance(queue_depth, int) else None,
                commit=False,
            )
            append_workflow_event(
                interview,
                "info",
                "Interview generation enqueued in Redis.",
                "form",
                {
                    "queue_backend": "redis",
                    "external_job_id": external_job_id,
                    "queue_position": queue_position,
                    "queue_depth": queue_depth,
                },
                commit=False,
            )
            if queue_position is not None:
                queue_position_value = int(queue_position)
                if queue_position_value <= 0:
                    queue_message = "Redis accepted the workflow job; a worker may already have picked it up."
                elif queue_position_value == 1:
                    queue_message = "Workflow job is next in the Redis queue and waiting for worker pickup."
                else:
                    queue_message = (
                        f"Workflow job is approximately position {queue_position_value} in the Redis queue "
                        f"({queue_position_value - 1} ahead)."
                    )
                append_workflow_event(
                    interview,
                    "info",
                    queue_message,
                    "form",
                    {"queue_backend": "redis", "queue_position": queue_position, "queue_depth": queue_depth},
                    commit=False,
                )
            await repository_service.commit_async()
            return build_workflow_state(interview)
        except Exception as exc:
            if require_durable:
                error = f"{type(exc).__name__}: {exc}"
                _mark_queue_unavailable(interview, "redis", error, commit=False)
                await repository_service.commit_async()
                raise WorkflowQueueUnavailable(error) from exc
            append_workflow_event(
                interview,
                "warning",
                "Redis workflow queue unavailable. Falling back to in-process execution.",
                "form",
                {"queue_backend": "redis", "fallback": "inprocess", "error": f"{type(exc).__name__}: {exc}"},
            )
            update_workflow_job(interview, queue_backend="inprocess")

    return _start_inprocess_generation(interview_id, interview, job)


async def _enqueue_redis(interview_id: str, job_id: str) -> dict[str, Any]:
    try:
        import redis.asyncio as redis
    except Exception as exc:
        raise RuntimeError("Install redis-py to use workflow_queue_backend=redis.") from exc

    payload = _redis_payload(interview_id, job_id)
    client = redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=max(0.1, float(settings.workflow_enqueue_timeout_seconds)),
        socket_timeout=max(0.1, float(settings.workflow_enqueue_timeout_seconds)),
    )
    try:
        await client.lpush(settings.workflow_queue_name, json.dumps(payload))
        queue_depth = await client.llen(settings.workflow_queue_name)
    finally:
        await client.aclose()
    return {
        "external_job_id": payload["id"],
        "queue_position": int(queue_depth),
        "queue_depth": int(queue_depth),
    }


def cancel_inprocess_workflow_job(interview_id: str) -> bool:
    task = _IN_PROCESS_TASKS.get(interview_id)
    if task and not task.done():
        task.cancel()
        return True
    return False


async def _publish_worker_heartbeat(client: Any, worker_id: str) -> None:
    payload = {
        "workerId": worker_id,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "queueName": settings.workflow_queue_name,
        "heartbeatAt": iso_now(),
    }
    await client.hset(_worker_registry_key(), worker_id, json.dumps(payload))
    ttl_seconds = int(max(60.0, _worker_heartbeat_fresh_for() * 3))
    await client.expire(_worker_registry_key(), ttl_seconds)


async def _redis_worker_heartbeat_snapshot(client: Any) -> dict[str, Any]:
    entries = await client.hgetall(_worker_registry_key())
    stale_worker_ids: list[str] = []
    latest: dict[str, Any] | None = None
    latest_age: float | None = None
    active_count = 0

    for worker_id, raw_payload in (entries or {}).items():
        try:
            payload = json.loads(raw_payload)
        except (TypeError, json.JSONDecodeError):
            stale_worker_ids.append(str(worker_id))
            continue

        heartbeat_at = payload.get("heartbeatAt")
        age = _parse_age_seconds(heartbeat_at)
        if age is None or age > _worker_heartbeat_fresh_for():
            stale_worker_ids.append(str(worker_id))
            continue

        active_count += 1
        if latest_age is None or age < latest_age:
            latest = payload
            latest_age = age

    if stale_worker_ids:
        await client.hdel(_worker_registry_key(), *stale_worker_ids)

    return {
        "redisWorkerCount": active_count,
        "latestRedisWorkerId": latest.get("workerId") if latest else None,
        "latestRedisWorkerHeartbeatAt": latest.get("heartbeatAt") if latest else None,
        "latestRedisWorkerHeartbeatAgeSeconds": round(latest_age, 2) if latest_age is not None else None,
    }


async def _read_redis_worker_heartbeat() -> dict[str, Any]:
    if _queue_backend() != "redis":
        return {}
    try:
        import redis.asyncio as redis
    except Exception:
        return {}

    client = redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=max(0.1, float(settings.workflow_enqueue_timeout_seconds)),
        socket_timeout=max(0.1, float(settings.workflow_enqueue_timeout_seconds)),
    )
    try:
        return await _redis_worker_heartbeat_snapshot(client)
    except Exception as exc:
        logger.debug("Could not read Redis workflow worker heartbeat: %s: %s", type(exc).__name__, exc)
        return {}
    finally:
        await client.aclose()


def _latest_worker_heartbeat(redis_heartbeat: dict[str, Any] | None = None) -> dict[str, Any]:
    active_statuses = {"queued", "running", "retrying"}
    active_jobs = [
        job
        for job in store.workflow_jobs.values()
        if str(job.get("status") or "") in active_statuses
    ]
    heartbeats = [job for job in active_jobs if job.get("lastHeartbeatAt")]
    latest = max(heartbeats, key=lambda job: str(job.get("lastHeartbeatAt") or ""), default=None)
    age_seconds = None
    if latest and latest.get("lastHeartbeatAt"):
        age_seconds = _parse_age_seconds(latest["lastHeartbeatAt"])

    redis_heartbeat = redis_heartbeat or {}
    redis_age = redis_heartbeat.get("latestRedisWorkerHeartbeatAgeSeconds")
    if redis_age is not None and (age_seconds is None or float(redis_age) < float(age_seconds)):
        latest_worker_id = redis_heartbeat.get("latestRedisWorkerId")
        latest_heartbeat_at = redis_heartbeat.get("latestRedisWorkerHeartbeatAt")
        latest_age_seconds = float(redis_age)
        latest_source = "redis_registry"
    else:
        latest_worker_id = latest.get("workerId") if latest else None
        latest_heartbeat_at = latest.get("lastHeartbeatAt") if latest else None
        latest_age_seconds = age_seconds
        latest_source = "active_job" if latest else None

    return {
        "activeJobCount": len(active_jobs),
        "latestWorkerId": latest_worker_id,
        "latestHeartbeatAt": latest_heartbeat_at,
        "latestHeartbeatAgeSeconds": round(latest_age_seconds, 2) if latest_age_seconds is not None else None,
        "heartbeatSource": latest_source,
        "isAvailable": latest_age_seconds is not None and latest_age_seconds <= _worker_heartbeat_fresh_for(),
        "redisWorkerCount": int(redis_heartbeat.get("redisWorkerCount") or 0),
    }


async def workflow_queue_health() -> dict[str, Any]:
    backend = _queue_backend()
    redis_status: dict[str, Any] = {
        "configured": bool(settings.redis_url),
        "ok": None,
        "queueName": settings.workflow_queue_name,
        "queueDepth": None,
        "error": None,
    }
    redis_heartbeat: dict[str, Any] = {}
    if backend == "redis":
        try:
            import redis.asyncio as redis

            client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=max(0.1, float(settings.workflow_enqueue_timeout_seconds)),
                socket_timeout=max(0.1, float(settings.workflow_enqueue_timeout_seconds)),
            )
            try:
                redis_status["ok"] = bool(await client.ping())
                redis_status["queueDepth"] = int(await client.llen(settings.workflow_queue_name))
                redis_heartbeat = await _redis_worker_heartbeat_snapshot(client)
            finally:
                await client.aclose()
        except Exception as exc:
            redis_status["ok"] = False
            redis_status["error"] = f"{type(exc).__name__}: {exc}"

    if persistence_manager.enabled:
        try:
            persistence_manager.hydrate_workflow_jobs(store)
        except Exception:
            logger.exception("Workflow health could not hydrate workflow jobs from persistence")
    else:
        try:
            store.load()
        except Exception:
            logger.exception("Workflow health could not reload local store")

    heartbeat = _latest_worker_heartbeat(redis_heartbeat)
    healthy = backend != "redis" or bool(redis_status.get("ok"))
    return {
        "status": "ok" if healthy else "degraded",
        "backend": backend,
        "asyncGeneration": bool(settings.workflow_async_generation),
        "redis": redis_status,
        "worker": heartbeat,
        "persistence": {
            "enabled": bool(persistence_manager.enabled),
            "mode": "postgres" if persistence_manager.enabled else "development-store",
            "strict": bool(settings.postgres_persistence_strict or settings.app_env == "production"),
        },
        "timeouts": {
            "enqueueSeconds": float(settings.workflow_enqueue_timeout_seconds),
            "generationSeconds": float(settings.workflow_generation_timeout_seconds),
            "pickupGraceSeconds": float(settings.workflow_queue_pickup_grace_seconds),
            "heartbeatSeconds": float(settings.workflow_worker_heartbeat_seconds),
            "visibilitySeconds": float(settings.workflow_queue_visibility_timeout_seconds),
        },
        "recovery": {
            "stalledRedisJobsInApi": bool(settings.workflow_recover_stalled_redis_jobs_in_api),
        },
    }


async def execute_queued_payload(payload: dict[str, Any]) -> None:
    interview_id = str(payload.get("interview_id") or "")
    if not interview_id:
        raise ValueError("Queued workflow payload is missing interview_id.")
    await repository_service.refresh_interview_async(interview_id)
    interview = store.interviews.get(interview_id)
    if not interview:
        raise ValueError(
            f"Interview '{interview_id}' was not found after refreshing durable state. "
            "The API and worker are not sharing persistence correctly."
        )
    existing_job = ensure_workflow_job(interview, commit=False)
    if _terminal(existing_job.get("status")) or str(existing_job.get("queueBackend") or "").lower() != "redis":
        append_workflow_event(
            interview,
            "info",
            "Dedicated worker skipped a stale Redis payload because the workflow job is already handled.",
            "form",
            {
                "queue_backend": existing_job.get("queueBackend"),
                "status": existing_job.get("status"),
                "external_job_id": payload.get("id"),
            },
            commit=False,
        )
        await repository_service.commit_async()
        return
    worker_id = _worker_id()
    heartbeat_stop = asyncio.Event()

    async def heartbeat() -> None:
        while not heartbeat_stop.is_set():
            await asyncio.sleep(max(0.1, float(settings.workflow_worker_heartbeat_seconds)))
            current = store.interviews.get(interview_id)
            if not current:
                return
            job = ensure_workflow_job(current, commit=False)
            if _terminal(job.get("status")):
                return
            update_workflow_job(
                current,
                current_node=str(job.get("currentNode") or "generate_interview_assets"),
                worker_id=worker_id,
                lease_expires_at=_lease_expires_at(),
                visibility_timeout_seconds=float(settings.workflow_queue_visibility_timeout_seconds),
                heartbeat=True,
            )

    update_workflow_job(
        interview,
        status="running",
        current_node="worker_start",
        queue_backend="redis",
        external_job_id=str(payload.get("id") or payload.get("external_job_id") or ""),
        worker_id=worker_id,
        lease_expires_at=_lease_expires_at(),
        visibility_timeout_seconds=float(settings.workflow_queue_visibility_timeout_seconds),
        commit=False,
    )
    append_workflow_event(
        interview,
        "info",
        "Dedicated workflow worker picked up the queued interview generation job.",
        "form",
        {
            "queue_backend": "redis",
            "worker_id": worker_id,
            "external_job_id": payload.get("id"),
            "lease_expires_at": _lease_expires_at(),
        },
        commit=False,
    )
    await repository_service.commit_async()
    job = ensure_workflow_job(interview, commit=False)
    if job.get("cancelRequested") or job.get("status") == "cancelled":
        update_workflow_job(interview, status="cancelled", current_node="worker_start", worker_id=worker_id, commit=False)
        append_workflow_event(
            interview,
            "warning",
            "Dedicated worker skipped a cancelled workflow job before graph execution.",
            "form",
            {"worker_id": worker_id, "external_job_id": payload.get("id")},
            commit=False,
        )
        await repository_service.commit_async()
        raise WorkflowJobCancelled("Workflow generation cancelled before worker execution.")
    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        await asyncio.wait_for(
            run_interview_generation_with_retries(interview_id),
            timeout=max(0.01, float(settings.workflow_generation_timeout_seconds)),
        )
    except asyncio.TimeoutError as exc:
        interview = store.interviews.get(interview_id)
        if interview:
            update_workflow_job(
                interview,
                status="failed",
                current_node="generate_interview_assets",
                error=f"Workflow generation exceeded {settings.workflow_generation_timeout_seconds} seconds.",
                commit=False,
            )
            append_workflow_event(
                interview,
                "error",
                "Workflow generation timed out in the dedicated worker.",
                "form",
                {
                    "timeout_seconds": settings.workflow_generation_timeout_seconds,
                    "worker_id": worker_id,
                },
                commit=False,
            )
            await repository_service.commit_async()
        raise TimeoutError(f"Workflow generation timed out for interview {interview_id}.") from exc
    except WorkflowJobCancelled:
        interview = store.interviews.get(interview_id)
        if interview:
            update_workflow_job(
                interview,
                status="cancelled",
                current_node="generate_interview_assets",
                worker_id=worker_id,
                commit=False,
            )
            append_workflow_event(
                interview,
                "warning",
                "Workflow generation was cancelled in the dedicated worker.",
                "form",
                {"worker_id": worker_id, "external_job_id": payload.get("id")},
                commit=False,
            )
            await repository_service.commit_async()
        raise
    except Exception as exc:
        interview = store.interviews.get(interview_id)
        if interview:
            job = ensure_workflow_job(interview, commit=False)
            if not _terminal(job.get("status")):
                update_workflow_job(
                    interview,
                    status="failed",
                    current_node=str(job.get("currentNode") or "generate_interview_assets"),
                    worker_id=worker_id,
                    error=f"{type(exc).__name__}: {exc}",
                    commit=False,
                )
                append_workflow_event(
                    interview,
                    "error",
                    "Workflow generation failed in the dedicated worker.",
                    "form",
                    {"worker_id": worker_id, "external_job_id": payload.get("id"), "error": f"{type(exc).__name__}: {exc}"},
                    commit=False,
                )
                await repository_service.commit_async()
        raise
    finally:
        heartbeat_stop.set()
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task


async def redis_worker_loop(stop_after_one: bool = False) -> None:
    try:
        import redis.asyncio as redis
    except Exception as exc:
        raise RuntimeError("Install redis-py before starting the Redis workflow worker.") from exc

    worker_id = _worker_id()
    logger.info("Workflow worker %s starting. queue=%s backend=redis", worker_id, settings.workflow_queue_name)
    client = redis.from_url(settings.redis_url, decode_responses=True)
    reconnect_delay = 1.0
    try:
        while True:
            try:
                await _publish_worker_heartbeat(client, worker_id)
                result = await client.brpop(
                    settings.workflow_queue_name,
                    timeout=max(
                        1,
                        int(min(settings.workflow_redis_brpop_timeout_seconds, settings.workflow_worker_heartbeat_seconds)),
                    ),
                )
                reconnect_delay = 1.0
            except asyncio.CancelledError:
                logger.info("Workflow worker %s received cancellation; shutting down.", worker_id)
                raise
            except Exception as exc:
                logger.warning(
                    "Workflow worker %s lost Redis connection during queue wait; reconnecting in %.1fs. error=%s: %s",
                    worker_id,
                    reconnect_delay,
                    type(exc).__name__,
                    exc,
                )
                with contextlib.suppress(Exception):
                    await client.aclose()
                if stop_after_one:
                    raise
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(15.0, reconnect_delay * 2)
                client = redis.from_url(settings.redis_url, decode_responses=True)
                continue
            if not result:
                if stop_after_one:
                    return
                continue
            _, raw_payload = result
            payload = json.loads(raw_payload)
            try:
                await execute_queued_payload(payload)
            except Exception:
                logger.exception("Workflow job failed while processing queued payload")
            if stop_after_one:
                return
    finally:
        logger.info("Workflow worker %s stopped.", worker_id)
        with contextlib.suppress(Exception):
            await client.hdel(_worker_registry_key(), worker_id)
        await client.aclose()
