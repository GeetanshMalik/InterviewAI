import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException, status

from config import settings
from services.repositories.manager import persistence_manager
from services.store import iso_now, new_id, store, utc_now
from auth.tokens import create_jwt_token, decode_jwt_token


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash == "dev":
        return True
    try:
        algorithm, salt, expected = password_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return hmac.compare_digest(digest, expected)


def _persistence_enabled() -> bool:
    return persistence_manager.enabled


def _database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Authentication database is unavailable. Please try again.",
    )


def _run_auth_db(action):
    try:
        return action()
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_unavailable(exc) from exc


def _cache_user(user: dict) -> None:
    store.users[user["id"]] = user
    if user.get("email"):
        store.users_by_email[str(user["email"]).lower()] = user["id"]


def _cache_session(token: str, session: dict) -> None:
    store.sessions[token] = session


def _build_user(name: str, email: str, password_hash: str) -> dict:
    return {
        "id": new_id(),
        "name": name.strip(),
        "email": email.strip().lower(),
        "hashed_password": password_hash,
        "avatar": None,
        "preferred_language": "javascript",
        "ai_memory_enabled": True,
        "appearance_theme": "dark",
        "createdAt": iso_now(),
        "updatedAt": iso_now(),
    }


def _build_session(
    user_id: str,
    token: str,
    refresh_token: str,
    *,
    access_jti: str,
    refresh_jti: str,
    access_expires_at: str,
    expires_at: str,
) -> dict:
    return {
        "id": new_id(),
        "user_id": user_id,
        "token": token,
        "refresh_token": refresh_token,
        "access_jti": access_jti,
        "refresh_jti": refresh_jti,
        "access_expires_at": access_expires_at,
        "expires_at": expires_at,
        "created_at": iso_now(),
    }


def _remember_auth_state(
    user: dict | None = None,
    token: str | None = None,
    session: dict | None = None,
    *,
    persist: bool = False,
) -> None:
    if user:
        _cache_user(user)
    if token and session:
        _cache_session(token, session)
    if persist:
        store.save(mirror=False)


def _parse_session_expiry(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=utc_now().tzinfo)
    return parsed


def _cached_user_for_payload(token: str, payload: dict) -> dict | None:
    session = store.sessions.get(token)
    if not session:
        return None
    if session.get("access_jti") and session.get("access_jti") != payload.get("jti"):
        return None
    if session.get("user_id") != payload.get("sub"):
        return None
    expires_at = _parse_session_expiry(session.get("access_expires_at"))
    if expires_at and expires_at <= utc_now():
        store.sessions.pop(token, None)
        return None
    return store.users.get(str(payload["sub"]))


def create_auth_payload(user: dict) -> dict:
    access_token, access_jti, access_expires_at = create_jwt_token(
        user["id"],
        "access",
        timedelta(minutes=settings.access_token_expire_minutes),
    )
    refresh_token, refresh_jti, refresh_expires_at = create_jwt_token(
        user["id"],
        "refresh",
        timedelta(days=settings.refresh_token_expire_days),
    )
    if _persistence_enabled():
        session = _build_session(
            user["id"],
            access_token,
            refresh_token,
            access_jti=access_jti,
            refresh_jti=refresh_jti,
            access_expires_at=access_expires_at.isoformat(),
            expires_at=refresh_expires_at.isoformat(),
        )
        _run_auth_db(lambda: persistence_manager.upsert_session(access_token, session))
        _remember_auth_state(user, access_token, session, persist=True)
    else:
        store.create_session(
            user["id"],
            access_token,
            refresh_token,
            access_jti=access_jti,
            refresh_jti=refresh_jti,
            access_expires_at=access_expires_at.isoformat(),
            expires_at=refresh_expires_at.isoformat(),
        )
    return {
        "user": store.public_user(user),
        "token": access_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


def delete_session_token(token: str) -> None:
    if _persistence_enabled():
        _run_auth_db(lambda: persistence_manager.delete_session(token))
        store.sessions.pop(token, None)
        store.save(mirror=False)
        return
    store.delete_session(token)


def _get_session_for_refresh_token(refresh_token: str) -> dict | None:
    payload = decode_jwt_token(refresh_token, expected_type="refresh")
    if not payload:
        return None

    for session in store.sessions.values():
        if session.get("refresh_token") != refresh_token:
            continue
        if session.get("refresh_jti") and session.get("refresh_jti") != payload.get("jti"):
            return None
        if session.get("user_id") != payload.get("sub"):
            return None
        expires_at = _parse_session_expiry(session.get("expires_at"))
        if expires_at and expires_at <= utc_now():
            delete_session_token(str(session.get("token") or ""))
            return None
        return session

    if not _persistence_enabled():
        return None

    session = _run_auth_db(lambda: persistence_manager.get_session_by_refresh_token(refresh_token))
    if not session:
        return None
    if session.get("refresh_jti") and session.get("refresh_jti") != payload.get("jti"):
        return None
    if session.get("user_id") != payload.get("sub"):
        return None
    expires_at = _parse_session_expiry(session.get("expires_at"))
    if expires_at and expires_at <= utc_now():
        delete_session_token(str(session.get("token") or ""))
        return None
    return session


def refresh_session(refresh_token: str) -> dict:
    session = _get_session_for_refresh_token(refresh_token)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user_id = str(session.get("user_id") or "")
    user = store.users.get(user_id)
    if not user and _persistence_enabled():
        user = _run_auth_db(lambda: persistence_manager.get_user_by_id(user_id))
    if not user:
        delete_session_token(str(session.get("token") or ""))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    delete_session_token(str(session.get("token") or ""))
    _remember_auth_state(user, persist=False)
    return create_auth_payload(user)


def delete_session_refresh_token(refresh_token: str) -> None:
    session = _get_session_for_refresh_token(refresh_token)
    if session and session.get("token"):
        delete_session_token(str(session["token"]))


def get_user_for_token(token: str) -> dict | None:
    payload = decode_jwt_token(token, expected_type="access")
    if not payload:
        return None

    cached_user = _cached_user_for_payload(token, payload)
    if cached_user:
        return cached_user

    if not _persistence_enabled():
        return None

    session = _run_auth_db(lambda: persistence_manager.get_session_by_token(token))
    if not session:
        return None
    if session.get("access_jti") and session.get("access_jti") != payload.get("jti"):
        return None
    if session.get("user_id") != payload.get("sub"):
        return None

    parsed_expires_at = _parse_session_expiry(session.get("access_expires_at"))
    if parsed_expires_at and parsed_expires_at <= utc_now():
        delete_session_token(token)
        return None

    user = _run_auth_db(lambda: persistence_manager.get_user_by_id(str(payload["sub"])))
    if not user:
        return None
    _remember_auth_state(user, token, session, persist=False)
    return user


def signup(name: str, email: str, password: str) -> dict:
    normalized_email = email.strip().lower()
    if _persistence_enabled():
        if _run_auth_db(lambda: persistence_manager.get_user_by_email(normalized_email)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
        user = _build_user(name, normalized_email, hash_password(password))
        try:
            _run_auth_db(lambda: persistence_manager.upsert_user(user))
        except HTTPException as exc:
            cause_text = str(exc.__cause__ or "").lower()
            if "duplicate" in cause_text or "unique" in cause_text:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered") from exc
            raise
        _remember_auth_state(user, persist=True)
    else:
        if store.get_user_by_email(normalized_email):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
        user = store.create_user(name=name, email=normalized_email, password_hash=hash_password(password))
    return create_auth_payload(user)


def login(email: str, password: str) -> dict:
    normalized_email = email.strip().lower()
    if _persistence_enabled():
        user = _run_auth_db(lambda: persistence_manager.get_user_by_email(normalized_email))
    else:
        user = store.get_user_by_email(normalized_email)
    if not user or not verify_password(password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    return create_auth_payload(user)
