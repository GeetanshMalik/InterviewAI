import json
import time
from typing import Any
from urllib.parse import urlencode

from jose import jwt

from config import settings


VALID_REALTIME_ROUNDS = {"technical", "hr"}


def validate_round_name(round_name: str) -> str:
    normalized = round_name.lower().strip()
    if normalized not in VALID_REALTIME_ROUNDS:
        raise ValueError("Realtime voice only supports technical or hr rounds")
    return normalized


def livekit_room_name(interview_id: str, round_name: str) -> str:
    return f"interviewos-{interview_id}-{validate_round_name(round_name)}"


def livekit_enabled() -> bool:
    return bool(settings.livekit_url and settings.livekit_api_key and settings.livekit_api_secret)


def deepgram_enabled() -> bool:
    return bool(settings.deepgram_api_key)


def build_livekit_token(interview_id: str, round_name: str, user: dict[str, Any]) -> dict[str, Any]:
    round_key = validate_round_name(round_name)
    if not livekit_enabled():
        return {
            "enabled": False,
            "reason": "LiveKit is not configured. Set LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET.",
        }

    now = int(time.time())
    room = livekit_room_name(interview_id, round_key)
    identity = f"{user['id']}:{interview_id}:{round_key}"
    expires_at = now + max(300, settings.livekit_token_ttl_seconds)
    payload = {
        "iss": settings.livekit_api_key,
        "sub": identity,
        "name": user.get("name") or user.get("email") or "Interview candidate",
        "nbf": now - 5,
        "exp": expires_at,
        "metadata": json.dumps(
            {
                "interviewId": interview_id,
                "round": round_key,
                "role": "candidate",
            }
        ),
        "video": {
            "room": room,
            "roomJoin": True,
            "canPublish": True,
            "canPublishData": True,
            "canSubscribe": True,
            "canPublishSources": ["microphone"],
        },
    }
    token = jwt.encode(payload, settings.livekit_api_secret or "", algorithm="HS256")
    return {
        "enabled": True,
        "serverUrl": settings.livekit_url,
        "token": token,
        "room": room,
        "identity": identity,
        "expiresAt": expires_at,
    }


def deepgram_listen_url() -> str:
    params = {
        "model": settings.deepgram_model,
        "language": settings.deepgram_language,
        "smart_format": "true",
        "punctuate": "true",
        "interim_results": "true",
        "vad_events": "true",
        "endpointing": str(settings.deepgram_endpointing_ms),
        "utterance_end_ms": str(settings.deepgram_utterance_end_ms),
    }
    return f"wss://api.deepgram.com/v1/listen?{urlencode(params)}"


def normalize_deepgram_message(payload: dict[str, Any]) -> dict[str, Any] | None:
    event_type = str(payload.get("type") or "")
    if event_type == "SpeechStarted":
        return {
            "event": "speech_started",
            "timestamp": payload.get("timestamp"),
        }
    if event_type == "UtteranceEnd":
        return {
            "event": "utterance_end",
            "lastWordEnd": payload.get("last_word_end"),
        }
    if event_type == "Metadata":
        return {
            "event": "transcription_metadata",
            "requestId": payload.get("request_id"),
            "duration": payload.get("duration"),
        }
    if event_type != "Results":
        return {
            "event": "transcription_event",
            "type": event_type or "unknown",
        }

    channel = payload.get("channel") if isinstance(payload.get("channel"), dict) else {}
    alternatives = channel.get("alternatives") if isinstance(channel.get("alternatives"), list) else []
    alternative = alternatives[0] if alternatives and isinstance(alternatives[0], dict) else {}
    transcript = str(alternative.get("transcript") or "").strip()
    if not transcript:
        return None

    is_final = bool(payload.get("is_final"))
    speech_final = bool(payload.get("speech_final"))
    confidence = alternative.get("confidence")
    words = alternative.get("words") if isinstance(alternative.get("words"), list) else []
    event_name = "transcript_final" if is_final or speech_final else "transcript_partial"
    return {
        "event": event_name,
        "text": transcript,
        "confidence": confidence if isinstance(confidence, (int, float)) else None,
        "isFinal": is_final,
        "speechFinal": speech_final,
        "words": len(words),
        "start": payload.get("start"),
        "duration": payload.get("duration"),
    }
