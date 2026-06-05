from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
import json
import logging
from pathlib import Path
from uuid import uuid4

from config import settings
from auth.tokens import decode_jwt_token


logger = logging.getLogger("interviewos.store")


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return utc_now().isoformat()


class DevelopmentStore:
    """Process-local store used until Neon repositories are connected."""

    def __init__(self) -> None:
        self.users: dict[str, dict] = {}
        self.users_by_email: dict[str, str] = {}
        self.sessions: dict[str, dict] = {}
        self.interviews: dict[str, dict] = {}
        self.logs: dict[str, list[dict]] = {}
        self.dsa_problems: dict[str, list[dict]] = {}
        self.dsa_submissions: dict[str, list[dict]] = {}
        self.aptitude_questions: dict[str, list[dict]] = {}
        self.aptitude_results: dict[str, dict] = {}
        self.technical_questions: dict[str, list[dict]] = {}
        self.technical_answers: dict[str, list[dict]] = {}
        self.hr_questions: dict[str, list[dict]] = {}
        self.hr_answers: dict[str, list[dict]] = {}
        self.round_runtimes: dict[str, dict] = {}
        self.reports: dict[str, dict] = {}
        self.roadmaps: dict[str, dict] = {}
        self.resumes: dict[str, dict] = {}
        self.bot_messages: dict[str, list[dict]] = {}
        self.practice_sessions: dict[str, dict] = {}
        self.workflow_jobs: dict[str, dict] = {}
        self._demo_user_id: str | None = None
        self.load()

    def _persistent_state(self) -> dict:
        return {
            "users": self.users,
            "users_by_email": self.users_by_email,
            "sessions": self.sessions,
            "interviews": self.interviews,
            "logs": self.logs,
            "dsa_problems": self.dsa_problems,
            "dsa_submissions": self.dsa_submissions,
            "aptitude_questions": self.aptitude_questions,
            "aptitude_results": self.aptitude_results,
            "technical_questions": self.technical_questions,
            "technical_answers": self.technical_answers,
            "hr_questions": self.hr_questions,
            "hr_answers": self.hr_answers,
            "round_runtimes": self.round_runtimes,
            "reports": self.reports,
            "roadmaps": self.roadmaps,
            "resumes": self.resumes,
            "bot_messages": self.bot_messages,
            "practice_sessions": self.practice_sessions,
            "workflow_jobs": self.workflow_jobs,
            "_demo_user_id": self._demo_user_id,
        }

    def load(self) -> None:
        path = Path(settings.dev_store_path)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def _raise_on_persistence_failure(self, *, strict: bool) -> bool:
        return bool(strict and (settings.postgres_persistence_strict or settings.app_env == "production"))

    def _mirror_persistence(self, description: str, action, *, strict: bool = True) -> None:
        if not (settings.postgres_persistence_enabled or settings.app_env == "production"):
            return
        try:
            from services.repositories.manager import persistence_manager

            if not persistence_manager.enabled:
                return
            action(persistence_manager)
        except Exception:
            logger.exception("Postgres persistence %s failed", description)
            if self._raise_on_persistence_failure(strict=strict):
                raise

    def save(self, *, mirror: bool = True) -> None:
        path = Path(settings.dev_store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if settings.dev_store_compact_json:
            payload = json.dumps(self._persistent_state(), ensure_ascii=False, separators=(",", ":"))
        else:
            payload = json.dumps(self._persistent_state(), ensure_ascii=False, indent=2)
        path.write_text(
            payload,
            encoding="utf-8",
        )
        if mirror:
            self._mirror_persistence("mirror", lambda persistence: persistence.sync_from_store(self))

    def snapshot(self, value):
        return deepcopy(value)

    def create_user(self, name: str, email: str, password_hash: str) -> dict:
        existing = self.get_user_by_email(email)
        if existing:
            return existing

        user = {
            "id": new_id(),
            "name": name,
            "email": email,
            "hashed_password": password_hash,
            "avatar": None,
            "preferred_language": "javascript",
            "ai_memory_enabled": True,
            "appearance_theme": "dark",
            "createdAt": iso_now(),
            "updatedAt": iso_now(),
        }
        self.users[user["id"]] = user
        self.users_by_email[email.lower()] = user["id"]
        self.save(mirror=False)
        self._mirror_persistence("user upsert", lambda persistence: persistence.upsert_user(user), strict=False)
        return user

    def get_demo_user(self) -> dict:
        if self._demo_user_id and self._demo_user_id in self.users:
            return self.users[self._demo_user_id]
        user = self.create_user("Demo User", "demo@interviewos.dev", "dev")
        self._demo_user_id = user["id"]
        return user

    def get_user_by_email(self, email: str) -> dict | None:
        user_id = self.users_by_email.get(email.lower())
        return self.users.get(user_id) if user_id else None

    def public_user(self, user: dict) -> dict:
        return {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "avatar": user.get("avatar"),
            "createdAt": user["createdAt"],
            "updatedAt": user["updatedAt"],
        }

    def create_session(
        self,
        user_id: str,
        token: str,
        refresh_token: str,
        *,
        access_jti: str | None = None,
        refresh_jti: str | None = None,
        access_expires_at: str | None = None,
        expires_at: str | None = None,
    ) -> dict:
        session = {
            "id": new_id(),
            "user_id": user_id,
            "token": token,
            "refresh_token": refresh_token,
            "access_jti": access_jti,
            "refresh_jti": refresh_jti,
            "access_expires_at": access_expires_at or (utc_now() + timedelta(minutes=settings.access_token_expire_minutes)).isoformat(),
            "expires_at": expires_at or (utc_now() + timedelta(days=settings.refresh_token_expire_days)).isoformat(),
            "created_at": iso_now(),
        }
        self.sessions[token] = session
        self.save(mirror=False)
        self._mirror_persistence(
            "session upsert",
            lambda persistence: persistence.upsert_session(token, session),
            strict=False,
        )
        return session

    def get_user_by_token(self, token: str) -> dict | None:
        payload = decode_jwt_token(token, expected_type="access")
        if not payload:
            return None
        session = self.sessions.get(token)
        if not session:
            return None
        if session.get("access_jti") and session.get("access_jti") != payload.get("jti"):
            return None
        if session.get("user_id") != payload.get("sub"):
            return None
        expires_at = session.get("access_expires_at")
        if expires_at:
            try:
                if datetime.fromisoformat(str(expires_at)) <= utc_now():
                    self.sessions.pop(token, None)
                    return None
            except ValueError:
                return None
        return self.users.get(str(payload["sub"]))

    def delete_session(self, token: str) -> None:
        self.sessions.pop(token, None)
        self.save(mirror=False)
        self._mirror_persistence("session delete", lambda persistence: persistence.delete_session(token), strict=False)

    def create_log(
        self,
        interview_id: str,
        event_type: str,
        agent: str,
        message: str,
        step: str,
        *,
        commit: bool = True,
    ) -> dict:
        log = {
            "id": new_id(),
            "timestamp": iso_now(),
            "type": event_type,
            "agent": agent,
            "message": message,
            "interview_id": interview_id,
            "step": step,
        }
        self.logs.setdefault(interview_id, []).append(log)
        if commit:
            self.save()
        return log

    def user_reports(self, user_id: str) -> list[dict]:
        reports = [r for r in self.reports.values() if r["userId"] == user_id]
        return sorted(reports, key=lambda item: item["createdAt"], reverse=True)

    def user_roadmaps(self, user_id: str) -> list[dict]:
        roadmaps = [r for r in self.roadmaps.values() if r["userId"] == user_id]
        return sorted(roadmaps, key=lambda item: item["createdAt"], reverse=True)

    def active_roadmap(self, user_id: str) -> dict | None:
        for roadmap in self.user_roadmaps(user_id):
            if roadmap.get("isActive"):
                return roadmap
        return None


store = DevelopmentStore()
