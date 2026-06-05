from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from typing import Any

from jose import JWTError, jwt

from config import settings


def _utc_now() -> datetime:
    return datetime.now(UTC)


def create_jwt_token(user_id: str, token_type: str, expires_delta: timedelta) -> tuple[str, str, datetime]:
    expires_at = _utc_now() + expires_delta
    token_id = secrets.token_urlsafe(16)
    payload = {
        "sub": user_id,
        "type": token_type,
        "jti": token_id,
        "iat": int(_utc_now().timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, token_id, expires_at


def decode_jwt_token(token: str, expected_type: str = "access") -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None

    if payload.get("type") != expected_type:
        return None
    if not payload.get("sub") or not payload.get("jti"):
        return None
    return payload
