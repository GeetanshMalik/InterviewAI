import asyncio
import logging
from time import monotonic
from typing import Any, Literal

from services.repositories.manager import persistence_manager
from services.store import store


RoundName = Literal["dsa", "aptitude", "technical", "hr"]


class RepositoryService:
    """Application-facing repository facade.

    DevelopmentStore remains the local facade, and its save path mirrors to
    Postgres when production persistence is enabled. Runtime code should use
    this service for mutations so route handlers do not directly own storage
    writes.
    """

    _DIRTY_KEYS = {
        "users",
        "sessions",
        "resumes",
        "interviews",
        "logs",
        "round_assets",
        "dsa_submissions",
        "aptitude_results",
        "technical_answers",
        "hr_answers",
        "round_runtimes",
        "reports",
        "roadmaps",
        "bot_messages",
        "practice_sessions",
        "workflow_jobs",
    }

    def __init__(self) -> None:
        self._dirty: dict[str, set[str]] = {key: set() for key in self._DIRTY_KEYS}
        self._logger = logging.getLogger("interviewos.repository_service")
        self._last_interview_refresh: dict[str, float] = {}
        self._background_commit_task: asyncio.Task | None = None

    def _mark_dirty(self, key: str, item_id: str | None) -> None:
        if key in self._dirty and item_id:
            self._dirty[key].add(str(item_id))

    def _dirty_snapshot(self) -> dict[str, set[str]]:
        return {key: set(values) for key, values in self._dirty.items() if values}

    def _clear_dirty(self, synced: dict[str, set[str]]) -> None:
        for key, values in synced.items():
            self._dirty.get(key, set()).difference_update(values)

    def commit(self, *, mirror: bool = True) -> None:
        store.save(mirror=False)
        dirty = self._dirty_snapshot()
        if not mirror or not persistence_manager.enabled:
            self._clear_dirty(dirty)
            return
        if not dirty:
            return
        try:
            persistence_manager.sync_dirty(store, dirty)
        except Exception:
            self._logger.exception("Failed to commit dirty repository state to Postgres; preserving dirty state")
            if persistence_manager.strict:
                raise
            return
        self._clear_dirty(dirty)

    async def commit_async(self, *, mirror: bool = True) -> bool:
        await asyncio.to_thread(store.save, mirror=False)
        dirty = self._dirty_snapshot()
        if not mirror or not persistence_manager.enabled:
            self._clear_dirty(dirty)
            return True
        if not dirty:
            return True
        try:
            await asyncio.to_thread(persistence_manager.sync_dirty, store, dirty)
        except Exception:
            self._logger.exception("Failed async commit to Postgres; preserving dirty state")
            if persistence_manager.strict:
                raise
            return False
        self._clear_dirty(dirty)
        return True

    async def commit_local_async(self) -> None:
        await asyncio.to_thread(store.save, mirror=False)

    def commit_mirror_background(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.commit()
            return
        if self._background_commit_task and not self._background_commit_task.done():
            return

        async def _mirror() -> bool:
            try:
                return await self.commit_async()
            except Exception:
                self._logger.exception("Background Postgres mirror failed")
                return False

        def _finished(_task: asyncio.Task) -> None:
            self._background_commit_task = None
            try:
                succeeded = bool(_task.result())
            except Exception:
                succeeded = False
            if succeeded and self._dirty_snapshot():
                self.commit_mirror_background()

        self._background_commit_task = loop.create_task(_mirror())
        self._background_commit_task.add_done_callback(_finished)

    def refresh_interview(self, interview_id: str, *, force: bool = False) -> bool:
        if not force and interview_id in store.interviews:
            job = store.workflow_jobs.get(interview_id) or {}
            job_status = str(job.get("status") or "").lower()
            assets_loaded = all(
                [
                    store.dsa_problems.get(interview_id),
                    store.aptitude_questions.get(interview_id),
                    store.technical_questions.get(interview_id),
                    store.hr_questions.get(interview_id),
                ]
            )
            if job_status in {"succeeded", "failed", "cancelled"} and assets_loaded:
                return True
            last_refresh = self._last_interview_refresh.get(interview_id, 0)
            if monotonic() - last_refresh < 3:
                return True

        if persistence_manager.enabled:
            try:
                if persistence_manager.hydrate_interview_bundle(store, interview_id):
                    self._last_interview_refresh[interview_id] = monotonic()
                    return True
                if interview_id in store.interviews:
                    return True
            except Exception:
                self._logger.exception("Failed to hydrate interview %s from persistence", interview_id)

        try:
            store.load()
        except Exception:
            self._logger.exception("Failed to reload local development store before reading interview %s", interview_id)
        if interview_id in store.interviews:
            self._last_interview_refresh[interview_id] = monotonic()
        return interview_id in store.interviews

    async def refresh_interview_async(self, interview_id: str, *, force: bool = False) -> bool:
        if not force and interview_id in store.interviews:
            job = store.workflow_jobs.get(interview_id) or {}
            job_status = str(job.get("status") or "").lower()
            assets_loaded = all(
                [
                    store.dsa_problems.get(interview_id),
                    store.aptitude_questions.get(interview_id),
                    store.technical_questions.get(interview_id),
                    store.hr_questions.get(interview_id),
                ]
            )
            if job_status in {"succeeded", "failed", "cancelled"} and assets_loaded:
                return True
            last_refresh = self._last_interview_refresh.get(interview_id, 0)
            if monotonic() - last_refresh < 3:
                return True

        if persistence_manager.enabled:
            try:
                success = await asyncio.to_thread(persistence_manager.hydrate_interview_bundle, store, interview_id)
                if success:
                    self._last_interview_refresh[interview_id] = monotonic()
                    return True
                if interview_id in store.interviews:
                    return True
            except Exception:
                self._logger.exception("Failed async hydrate of interview %s from persistence", interview_id)

        try:
            await asyncio.to_thread(store.load)
        except Exception:
            self._logger.exception("Failed async reload of local development store before reading interview %s", interview_id)
        if interview_id in store.interviews:
            self._last_interview_refresh[interview_id] = monotonic()
        return interview_id in store.interviews

    def execution_logs_enabled(self, interview_id: str) -> bool:
        interview = store.interviews.get(interview_id)
        user = store.users.get(interview.get("userId")) if interview else None
        user_settings = user.get("settings") if isinstance(user, dict) and isinstance(user.get("settings"), dict) else {}
        interview_settings = (
            user_settings.get("interview")
            if isinstance(user_settings.get("interview"), dict)
            else {}
        )

        if "showExecutionLogs" in interview_settings:
            return bool(interview_settings["showExecutionLogs"])
        if isinstance(user, dict) and "show_execution_logs" in user:
            return bool(user["show_execution_logs"])
        if isinstance(interview, dict) and "show_execution_logs" in interview:
            return bool(interview["show_execution_logs"])
        return True

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
        if not self.execution_logs_enabled(interview_id):
            return {}
        log = store.create_log(interview_id, event_type, agent, message, step, commit=False)
        self._mark_dirty("logs", interview_id)
        if commit:
            self.commit()
        return log

    def upsert_resume(self, resume: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        store.resumes[resume["id"]] = resume
        self._mark_dirty("resumes", resume.get("id"))
        if commit:
            self.commit()
        return resume

    def upsert_interview(self, interview: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        store.interviews[interview["id"]] = interview
        self._mark_dirty("interviews", interview.get("id"))
        if commit:
            self.commit()
        return interview

    def update_user(self, user: dict[str, Any], updates: dict[str, Any] | None = None, *, commit: bool = True) -> dict[str, Any]:
        if updates:
            user.update(updates)
        store.users[user["id"]] = user
        if user.get("email"):
            store.users_by_email[str(user["email"]).lower()] = user["id"]
        self._mark_dirty("users", user.get("id"))
        if commit:
            if persistence_manager.enabled:
                persistence_manager.upsert_user(user)
                store.save(mirror=False)
            else:
                self.commit()
        return user

    def revoke_session_token(self, token: str, *, commit: bool = True) -> None:
        store.sessions.pop(token, None)
        if commit:
            if persistence_manager.enabled:
                persistence_manager.delete_session(token)
                store.save(mirror=False)
            else:
                self.commit()

    def revoke_user_sessions(self, user_id: str, *, except_session_id: str | None = None, commit: bool = True) -> None:
        revoked_tokens: list[str] = []
        for token, session in list(store.sessions.items()):
            if session.get("user_id") == user_id and session.get("id") != except_session_id:
                store.sessions.pop(token, None)
                revoked_tokens.append(token)
        if commit:
            if persistence_manager.enabled:
                for token in revoked_tokens:
                    persistence_manager.delete_session(token)
                store.save(mirror=False)
            else:
                self.commit()

    def update_interview(self, interview: dict[str, Any], updates: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        interview.update(updates)
        self._mark_dirty("interviews", interview.get("id"))
        if commit:
            self.commit()
        return interview

    def set_round_assets(self, interview_id: str, assets: dict[str, Any], *, commit: bool = True) -> None:
        store.dsa_problems[interview_id] = assets.get("dsa_problems", [])
        store.aptitude_questions[interview_id] = assets.get("aptitude_questions", [])
        store.technical_questions[interview_id] = assets.get("technical_questions", [])
        store.hr_questions[interview_id] = assets.get("hr_questions", [])
        self._mark_dirty("round_assets", interview_id)
        if commit:
            self.commit()

    def add_dsa_submission(self, interview_id: str, submission: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        store.dsa_submissions.setdefault(interview_id, []).append(submission)
        self._mark_dirty("dsa_submissions", interview_id)
        if commit:
            self.commit()
        return submission

    def set_aptitude_result(self, interview_id: str, result: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        store.aptitude_results[interview_id] = result
        self._mark_dirty("aptitude_results", interview_id)
        if commit:
            self.commit()
        return result

    def add_round_answer(
        self,
        interview_id: str,
        round_name: Literal["technical", "hr"],
        answer: dict[str, Any],
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        if round_name == "technical":
            store.technical_answers.setdefault(interview_id, []).append(answer)
            self._mark_dirty("technical_answers", interview_id)
        else:
            store.hr_answers.setdefault(interview_id, []).append(answer)
            self._mark_dirty("hr_answers", interview_id)
        if commit:
            self.commit()
        return answer

    def clear_round_state(self, interview_id: str, round_name: RoundName, *, commit: bool = True) -> None:
        if round_name == "dsa":
            store.dsa_submissions[interview_id] = []
            self._mark_dirty("dsa_submissions", interview_id)
        elif round_name == "aptitude":
            store.aptitude_results.pop(interview_id, None)
            self._mark_dirty("aptitude_results", interview_id)
        elif round_name == "technical":
            store.technical_answers[interview_id] = []
            store.round_runtimes.pop(f"{interview_id}:technical", None)
            self._mark_dirty("technical_answers", interview_id)
            self._mark_dirty("round_runtimes", f"{interview_id}:technical")
        elif round_name == "hr":
            store.hr_answers[interview_id] = []
            store.round_runtimes.pop(f"{interview_id}:hr", None)
            self._mark_dirty("hr_answers", interview_id)
            self._mark_dirty("round_runtimes", f"{interview_id}:hr")
        if persistence_manager.enabled:
            persistence_manager.clear_round_state(interview_id, round_name)
        if commit:
            self.commit()

    def upsert_round_runtime(self, runtime: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        store.round_runtimes[f"{runtime['interviewId']}:{runtime['round']}"] = runtime
        self._mark_dirty("round_runtimes", f"{runtime['interviewId']}:{runtime['round']}")
        if commit:
            self.commit()
        return runtime

    def delete_round_runtime(self, interview_id: str, round_name: Literal["technical", "hr"], *, commit: bool = True) -> None:
        store.round_runtimes.pop(f"{interview_id}:{round_name}", None)
        self._mark_dirty("round_runtimes", f"{interview_id}:{round_name}")
        if persistence_manager.enabled:
            persistence_manager.delete_round_runtime(interview_id, round_name)
        if commit:
            self.commit()

    def upsert_report(self, report: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        store.reports[report["id"]] = report
        self._mark_dirty("reports", report.get("id"))
        if commit:
            self.commit()
        return report

    def delete_report(self, report_id: str, *, commit: bool = True) -> None:
        store.reports.pop(report_id, None)
        self._mark_dirty("reports", report_id)
        if persistence_manager.enabled:
            persistence_manager.delete_report(report_id)
        if commit:
            self.commit()

    def upsert_roadmap(self, roadmap: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        store.roadmaps[roadmap["id"]] = roadmap
        self._mark_dirty("roadmaps", roadmap.get("id"))
        if commit:
            self.commit()
        return roadmap

    def deactivate_user_roadmaps(self, user_id: str, *, except_id: str | None = None, commit: bool = True) -> None:
        for roadmap in store.user_roadmaps(user_id):
            roadmap["isActive"] = roadmap["id"] == except_id if except_id else False
            self._mark_dirty("roadmaps", roadmap.get("id"))
        if commit:
            self.commit()

    def update_roadmap(self, roadmap: dict[str, Any], updates: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        roadmap.update(updates)
        self._mark_dirty("roadmaps", roadmap.get("id"))
        if commit:
            self.commit()
        return roadmap

    def upsert_workflow_job(self, interview_id: str, job: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        store.workflow_jobs[interview_id] = job
        self._mark_dirty("workflow_jobs", interview_id)
        if commit:
            self.commit()
        return job

    def save_workflow_job(self, job: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        if job.get("interviewId"):
            store.workflow_jobs[job["interviewId"]] = job
            self._mark_dirty("workflow_jobs", job.get("interviewId"))
        if commit:
            self.commit()
        return job

    def add_practice_session(self, session: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        store.practice_sessions[session["id"]] = session
        self._mark_dirty("practice_sessions", session.get("id"))
        if commit:
            self.commit()
        return session

    def update_practice_session(self, session: dict[str, Any], updates: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        session.update(updates)
        self._mark_dirty("practice_sessions", session.get("id"))
        if commit:
            self.commit()
        return session

    def add_bot_message(self, user_id: str, message: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        store.bot_messages.setdefault(user_id, []).append(message)
        self._mark_dirty("bot_messages", user_id)
        if commit:
            self.commit()
        return message

    def clear_bot_messages(self, user_id: str, *, commit: bool = True) -> None:
        store.bot_messages[user_id] = []
        self._mark_dirty("bot_messages", user_id)
        if commit:
            self.commit()


repository_service = RepositoryService()
