import asyncio
import json

import websockets
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from auth.dependencies import get_current_user
from auth.service import get_user_for_token
from config import settings
from services.realtime_voice import (
    build_livekit_token,
    deepgram_enabled,
    deepgram_listen_url,
    normalize_deepgram_message,
    validate_round_name,
)
from services.round_runtime import record_round_command
from services.repository_service import repository_service
from services.store import store


router = APIRouter()


def _resolve_websocket_user(token: str | None) -> dict | None:
    if token:
        return get_user_for_token(token)
    if settings.app_env == "development" and settings.allow_dev_auth_fallback:
        return store.get_demo_user()
    return None


def _get_owned_interview(interview_id: str, user: dict | None) -> dict | None:
    interview = store.interviews.get(interview_id)
    if not user or not interview or interview.get("userId") != user.get("id"):
        return None
    return interview


@router.get("/interviews/{interview_id}/rounds/{round_name}/livekit-token")
async def get_livekit_token(
    interview_id: str,
    round_name: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        round_key = validate_round_name(round_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    interview = _get_owned_interview(interview_id, current_user)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    return build_livekit_token(interview_id, round_key, current_user)


@router.get("/interviews/{interview_id}/rounds/{round_name}/transcription-status")
async def get_transcription_status(
    interview_id: str,
    round_name: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        validate_round_name(round_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    interview = _get_owned_interview(interview_id, current_user)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    return {
        "enabled": deepgram_enabled(),
        "provider": "deepgram",
        "model": settings.deepgram_model,
        "language": settings.deepgram_language,
        "reason": None if deepgram_enabled() else "Deepgram is not configured. Set DEEPGRAM_API_KEY.",
    }


@router.websocket("/ws/interviews/{interview_id}/rounds/{round_name}/transcript")
async def interview_transcript_socket(
    websocket: WebSocket,
    interview_id: str,
    round_name: str,
    token: str | None = None,
):
    await websocket.accept()
    try:
        round_key = validate_round_name(round_name)
    except ValueError as exc:
        await websocket.send_json({"event": "transcription_error", "error": str(exc)})
        await websocket.close(code=1003)
        return

    current_user = _resolve_websocket_user(token)
    interview = _get_owned_interview(interview_id, current_user)
    if not interview:
        await websocket.send_json({"event": "transcription_error", "error": "Interview not found or unauthorized"})
        await websocket.close(code=1008)
        return

    if not deepgram_enabled():
        await websocket.send_json(
            {
                "event": "transcription_unavailable",
                "provider": "deepgram",
                "reason": "Deepgram is not configured. Browser speech fallback may be used in development.",
            }
        )
        await websocket.close(code=1013)
        return

    deepgram_headers = {"Authorization": f"Token {settings.deepgram_api_key}"}
    deepgram_socket = None

    async def receive_from_browser():
        assert deepgram_socket is not None
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    return
                if message.get("bytes") is not None:
                    data = message.get("bytes") or b""
                    if data:
                        await deepgram_socket.send(data)
                    continue

                raw_text = message.get("text") or "{}"
                try:
                    payload = json.loads(raw_text)
                except json.JSONDecodeError:
                    continue
                command = str(payload.get("type") or payload.get("event") or "")
                if command == "finalize":
                    await deepgram_socket.send(json.dumps({"type": "Finalize"}))
                elif command == "keepalive":
                    await deepgram_socket.send(json.dumps({"type": "KeepAlive"}))
                elif command == "close":
                    await deepgram_socket.send(json.dumps({"type": "CloseStream"}))
                    return
                elif command == "media_state":
                    record_round_command(
                        interview,
                        round_key,  # type: ignore[arg-type]
                        "transcription_media_state",
                        question_id=payload.get("question_id") or payload.get("questionId"),
                        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
                        commit=False,
                    )
                    await repository_service.commit_async()
        except WebSocketDisconnect:
            return

    async def receive_from_deepgram():
        assert deepgram_socket is not None
        async for message in deepgram_socket:
            if isinstance(message, bytes):
                continue
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                continue
            normalized = normalize_deepgram_message(payload)
            if normalized:
                await websocket.send_json(normalized)

    try:
        async with websockets.connect(
            deepgram_listen_url(),
            additional_headers=deepgram_headers,
            ping_interval=20,
            ping_timeout=10,
            max_size=4 * 1024 * 1024,
        ) as dg:
            deepgram_socket = dg
            await websocket.send_json(
                {
                    "event": "transcription_connected",
                    "provider": "deepgram",
                    "model": settings.deepgram_model,
                    "language": settings.deepgram_language,
                }
            )
            browser_task = asyncio.create_task(receive_from_browser())
            deepgram_task = asyncio.create_task(receive_from_deepgram())
            done, pending = await asyncio.wait(
                {browser_task, deepgram_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({"event": "transcription_error", "error": str(exc)})
    finally:
        try:
            await websocket.close(code=1000)
        except RuntimeError:
            pass
