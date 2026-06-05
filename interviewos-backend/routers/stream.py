import asyncio
import json
import time

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse

from auth.service import get_user_for_token
from config import settings
from services.round_runtime import build_round_runtime_state, record_round_command
from services.repository_service import repository_service
from services.store import iso_now, store
from services.workflow import build_workflow_state
from services.workflow_queue import recover_stalled_redis_generation_if_needed


router = APIRouter()
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def sse_stream_response(generator) -> StreamingResponse:
    return StreamingResponse(generator, media_type="text/event-stream", headers=SSE_HEADERS)


async def event_generator(interview_id: str, follow: bool = False):
    yield sse("connected", {"interview_id": interview_id, "timestamp": iso_now()})
    sent = set()
    last_refresh_at = 0.0
    while True:
        if follow and time.monotonic() - last_refresh_at >= 1:
            last_refresh_at = time.monotonic()
            await repository_service.refresh_interview_async(interview_id)
        for log in store.logs.get(interview_id, []):
            if log["id"] in sent:
                continue
            sent.add(log["id"])
            event_name = "step_changed" if "Moved to" in log["message"] else "log"
            yield sse(event_name, log)

        interview = store.interviews.get(interview_id)
        if interview and interview.get("status") == "completed":
            yield sse("completed", {"interview_id": interview_id, "timestamp": iso_now()})
            return

        if not follow:
            return

        await asyncio.sleep(1)


def _workflow_event_name(event: dict, state: dict) -> str:
    metadata = event.get("metadata", {}) if isinstance(event.get("metadata"), dict) else {}
    if metadata.get("llm_token") or event.get("type") == "token":
        return "llm_token"
    if metadata.get("retry"):
        return "workflow_retry"
    if metadata.get("tool"):
        return "tool_call"
    if state.get("job", {}).get("status") == "cancelled" or "cancelled" in str(event.get("message", "")).lower():
        return "workflow_cancelled"
    if event.get("type") == "error":
        return "workflow_error"
    if "moved from" in str(event.get("message", "")).lower():
        return "workflow_transition"
    return "workflow_event"


def _workflow_state_signature(state: dict) -> str:
    job = state.get("job", {}) if isinstance(state.get("job"), dict) else {}
    events = state.get("events", []) if isinstance(state.get("events"), list) else []
    return json.dumps(
        {
            "currentStep": state.get("currentStep"),
            "status": state.get("status"),
            "jobStatus": job.get("status"),
            "jobNode": job.get("currentNode"),
            "jobAttempt": job.get("attempt"),
            "jobError": job.get("error"),
            "jobWorkerId": job.get("workerId"),
            "jobQueuePosition": job.get("queuePosition"),
            "jobQueueDepth": job.get("queueDepth"),
            "jobLeaseExpiresAt": job.get("leaseExpiresAt"),
            "jobLastHeartbeatAt": job.get("lastHeartbeatAt"),
            "jobUpdatedAt": job.get("updatedAt"),
            "roundProgress": state.get("roundProgress", {}),
            "allowedActions": state.get("allowedActions", []),
            "lastEventIds": [event.get("id") for event in events[-5:] if isinstance(event, dict)],
        },
        sort_keys=True,
        default=str,
    )


async def workflow_event_generator(request: Request, interview_id: str, follow: bool = False):
    yield sse("connected", {"interview_id": interview_id, "timestamp": iso_now(), "stream": "workflow"})
    sent = set()
    last_state_signature = ""
    last_heartbeat_at = time.monotonic()
    last_refresh_at = 0.0
    while True:
        if await request.is_disconnected():
            return

        if follow and time.monotonic() - last_refresh_at >= 1:
            last_refresh_at = time.monotonic()
            await repository_service.refresh_interview_async(interview_id)

        interview = store.interviews.get(interview_id)
        if not interview:
            yield sse("workflow_error", {"interview_id": interview_id, "error": "Interview not found"})
            return

        await recover_stalled_redis_generation_if_needed(interview)
        state = build_workflow_state(interview)
        state_signature = _workflow_state_signature(state)
        if state_signature != last_state_signature:
            last_state_signature = state_signature
            yield sse("workflow_state", state)
        elif follow and time.monotonic() - last_heartbeat_at >= 15:
            last_heartbeat_at = time.monotonic()
            yield sse("heartbeat", {"interview_id": interview_id, "timestamp": iso_now(), "stream": "workflow"})
        for event in state.get("events", []):
            if event["id"] in sent:
                continue
            sent.add(event["id"])
            yield sse(_workflow_event_name(event, state), event)

        job_status = state.get("job", {}).get("status")
        if job_status == "cancelled":
            yield sse("workflow_cancelled", {"interview_id": interview_id, "timestamp": iso_now()})
            return

        if state.get("status") == "completed" or state.get("currentStep") == "completed":
            yield sse("completed", {"interview_id": interview_id, "timestamp": iso_now()})
            return

        if not follow:
            return

        await asyncio.sleep(1)


def _runtime_event_name(event: dict) -> str:
    event_type = str(event.get("type") or "runtime_event")
    if event_type == "adaptive_next_question":
        return "runtime_next_question"
    if event_type == "adaptive_follow_up":
        return "runtime_follow_up"
    if event_type == "round_completed":
        return "runtime_completed"
    if event_type == "command":
        return "runtime_command"
    return "runtime_event"


def _runtime_state_signature(state: dict) -> str:
    runtime = state.get("runtime", {}) if isinstance(state.get("runtime"), dict) else {}
    events = state.get("events", []) if isinstance(state.get("events"), list) else []
    question = state.get("currentQuestion") if isinstance(state.get("currentQuestion"), dict) else {}
    return json.dumps(
        {
            "status": runtime.get("status"),
            "currentIndex": runtime.get("currentIndex"),
            "currentQuestionId": runtime.get("currentQuestionId"),
            "answeredQuestionIds": runtime.get("answeredQuestionIds", []),
            "skippedQuestionIds": runtime.get("skippedQuestionIds", []),
            "timer": runtime.get("timer", {}),
            "updatedAt": runtime.get("updatedAt"),
            "questionId": question.get("id"),
            "allowedActions": state.get("allowedActions", []),
            "lastEventIds": [event.get("id") for event in events[-5:] if isinstance(event, dict)],
        },
        sort_keys=True,
        default=str,
    )


async def runtime_event_generator(request: Request, interview_id: str, round_name: str, follow: bool = False):
    yield sse(
        "connected",
        {
            "interview_id": interview_id,
            "round": round_name,
            "timestamp": iso_now(),
            "stream": "round_runtime",
        },
    )
    sent = set()
    last_state_signature = ""
    last_heartbeat_at = time.monotonic()
    last_refresh_at = 0.0
    while True:
        if await request.is_disconnected():
            return

        if follow and time.monotonic() - last_refresh_at >= 1:
            last_refresh_at = time.monotonic()
            await repository_service.refresh_interview_async(interview_id)

        interview = store.interviews.get(interview_id)
        if not interview:
            yield sse("runtime_error", {"interview_id": interview_id, "error": "Interview not found"})
            return
        if round_name not in {"technical", "hr"}:
            yield sse("runtime_error", {"interview_id": interview_id, "error": "Unsupported runtime round"})
            return

        state = build_round_runtime_state(interview, round_name)  # type: ignore[arg-type]
        state_signature = _runtime_state_signature(state)
        if state_signature != last_state_signature:
            last_state_signature = state_signature
            yield sse("runtime_state", state)
        elif follow and time.monotonic() - last_heartbeat_at >= 15:
            last_heartbeat_at = time.monotonic()
            yield sse(
                "heartbeat",
                {"interview_id": interview_id, "round": round_name, "timestamp": iso_now(), "stream": "round_runtime"},
            )
        for event in state.get("events", []):
            if event["id"] in sent:
                continue
            sent.add(event["id"])
            yield sse(_runtime_event_name(event), event)

        status = state.get("runtime", {}).get("status")
        if status in {"completed", "terminated"}:
            yield sse("runtime_completed", {"interview_id": interview_id, "round": round_name, "timestamp": iso_now()})
            return

        if not follow:
            return

        await asyncio.sleep(1)


def resolve_stream_user(request: Request, token: str | None) -> dict:
    if token:
        user = get_user_for_token(token)
        if user:
            return user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired stream token")

    auth_header = request.headers.get("authorization", "")
    scheme, _, credentials = auth_header.partition(" ")
    if scheme.lower() == "bearer" and credentials:
        user = get_user_for_token(credentials)
        if user:
            return user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    if settings.app_env == "development" and settings.allow_dev_auth_fallback:
        return store.get_demo_user()

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


def resolve_websocket_user(token: str | None) -> dict | None:
    if token:
        return get_user_for_token(token)
    if settings.app_env == "development" and settings.allow_dev_auth_fallback:
        return store.get_demo_user()
    return None


@router.get("/interviews/{interview_id}/logs")
async def interview_logs(
    request: Request,
    interview_id: str,
    follow: bool = False,
    token: str | None = None,
):
    current_user = resolve_stream_user(request, token)

    await repository_service.refresh_interview_async(interview_id)
    interview = store.interviews.get(interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    return sse_stream_response(event_generator(interview_id, follow=follow))


@router.get("/interviews/{interview_id}/workflow")
async def interview_workflow_events(
    request: Request,
    interview_id: str,
    follow: bool = False,
    token: str | None = None,
):
    current_user = resolve_stream_user(request, token)

    await repository_service.refresh_interview_async(interview_id)
    interview = store.interviews.get(interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    return sse_stream_response(workflow_event_generator(request, interview_id, follow=follow))


@router.get("/interviews/{interview_id}/rounds/{round_name}/runtime")
async def interview_round_runtime_events(
    request: Request,
    interview_id: str,
    round_name: str,
    follow: bool = False,
    token: str | None = None,
):
    current_user = resolve_stream_user(request, token)

    await repository_service.refresh_interview_async(interview_id)
    interview = store.interviews.get(interview_id)
    if not interview or interview["userId"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    if round_name not in {"technical", "hr"}:
        raise HTTPException(status_code=422, detail="Runtime stream only supports technical or hr rounds")
    return sse_stream_response(runtime_event_generator(request, interview_id, round_name, follow=follow))


@router.websocket("/ws/interviews/{interview_id}/rounds/{round_name}/runtime")
async def interview_round_runtime_socket(
    websocket: WebSocket,
    interview_id: str,
    round_name: str,
    token: str | None = None,
):
    await websocket.accept()
    current_user = resolve_websocket_user(token)
    interview = store.interviews.get(interview_id)
    if not current_user or not interview or interview["userId"] != current_user["id"]:
        await websocket.send_json({"event": "runtime_error", "error": "Interview not found or unauthorized"})
        await websocket.close(code=1008)
        return
    if round_name not in {"technical", "hr"}:
        await websocket.send_json({"event": "runtime_error", "error": "Runtime socket only supports technical or hr rounds"})
        await websocket.close(code=1003)
        return

    await websocket.send_json({"event": "connected", "interview_id": interview_id, "round": round_name, "stream": "round_runtime_ws"})
    await websocket.send_json({"event": "runtime_state", "data": build_round_runtime_state(interview, round_name)})  # type: ignore[arg-type]
    media_chunk_count = 0
    media_bytes_total = 0

    try:
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=15)
            except TimeoutError:
                await websocket.send_json({"event": "runtime_state", "data": build_round_runtime_state(interview, round_name)})  # type: ignore[arg-type]
                continue

            if message.get("type") == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                media_bytes = message["bytes"] or b""
                media_chunk_count += 1
                media_bytes_total += len(media_bytes)
                await websocket.send_json(
                    {
                        "event": "runtime_media_ack",
                        "bytes": len(media_bytes),
                        "mediaChunks": media_chunk_count,
                        "mediaBytesTotal": media_bytes_total,
                    }
                )
                continue

            raw_text = message.get("text") or "{}"
            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError:
                await websocket.send_json({"event": "runtime_error", "error": "Expected JSON text or binary media frame"})
                continue

            event_type = str(payload.get("type") or payload.get("event") or "refresh")
            if event_type == "command":
                state = record_round_command(
                    interview,
                    round_name,  # type: ignore[arg-type]
                    str(payload.get("command") or "unknown"),
                    question_id=payload.get("question_id") or payload.get("questionId"),
                    metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {"transport": "websocket"},
                    commit=False,
                )
                await repository_service.commit_async()
                await websocket.send_json({"event": "runtime_command", "data": state})
            elif event_type == "close":
                await websocket.close(code=1000)
                return
            else:
                await websocket.send_json({"event": "runtime_state", "data": build_round_runtime_state(interview, round_name)})  # type: ignore[arg-type]
    except WebSocketDisconnect:
        return
