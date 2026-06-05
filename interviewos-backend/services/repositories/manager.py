from __future__ import annotations

from contextlib import contextmanager
import sys
from types import SimpleNamespace
from typing import Any

from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor

from config import settings
from services.repositories.base import (
    logger,
    migration_dir,
    payload_from_row,
    postgres_enabled,
    postgres_strict,
    sync_database_url,
    valid_uuid,
)
from services.repositories.postgres import (
    GraphCheckpointRepository,
    InterviewRepository,
    MemoryRepository,
    ReportRepository,
    RoadmapRepository,
    RoundRepository,
    UserRepository,
    WorkflowRepository,
    BotRepository,
)


class PersistenceManager:
    def __init__(self) -> None:
        self.users = UserRepository()
        self.interviews = InterviewRepository()
        self.rounds = RoundRepository()
        self.reports = ReportRepository()
        self.roadmaps = RoadmapRepository()
        self.bot = BotRepository()
        self.memory = MemoryRepository()
        self.workflow = WorkflowRepository()
        self.graph_checkpoints = GraphCheckpointRepository()
        self._pool: ThreadedConnectionPool | None = None
        self._pool_dsn: str | None = None
        self._disabled_after_startup_failure = False

    @property
    def enabled(self) -> bool:
        return postgres_enabled() and not self._disabled_after_startup_failure

    @property
    def strict(self) -> bool:
        return postgres_strict()

    def _connection_pool(self) -> ThreadedConnectionPool:
        dsn = sync_database_url()
        if not dsn:
            raise RuntimeError("Postgres persistence is enabled but DATABASE_URL_SYNC is missing.")
        if self._pool is not None and self._pool_dsn == dsn:
            return self._pool
        self._pool = ThreadedConnectionPool(
            max(1, int(settings.postgres_pool_min_size)),
            max(1, int(settings.postgres_pool_max_size)),
            dsn,
            cursor_factory=RealDictCursor,
            connect_timeout=max(1, int(settings.postgres_connect_timeout_seconds)),
            options=f"-c statement_timeout={max(1000, int(settings.postgres_statement_timeout_ms))}",
        )
        self._pool_dsn = dsn
        return self._pool

    @contextmanager
    def connect(self):
        pool = self._connection_pool()
        connection = pool.getconn()
        close_connection = False
        try:
            yield connection
        except Exception:
            try:
                if not connection.closed:
                    connection.rollback()
                else:
                    close_connection = True
            except Exception:
                close_connection = True
                logger.exception("Failed to roll back Postgres connection; discarding it from the pool.")
            raise
        finally:
            if connection.closed:
                close_connection = True
            pool.putconn(connection, close=close_connection)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.closeall()
            self._pool = None
            self._pool_dsn = None

    def _handle_startup_persistence_failure(self, action: str) -> None:
        self.close()
        if self.strict:
            logger.exception("Postgres %s failed during startup; strict persistence is enabled.", action)
            raise
        self._disabled_after_startup_failure = True
        exc = sys.exc_info()[1]
        reason = f"{type(exc).__name__}: {exc}" if exc else "unknown error"
        logger.warning("Postgres %s failed during startup; continuing with local store. Reason: %s", action, reason)

    def apply_migrations(self) -> None:
        if not self.enabled:
            return
        try:
            with self.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS schema_migrations (
                            version VARCHAR(255) PRIMARY KEY,
                            applied_at TIMESTAMPTZ DEFAULT NOW()
                        )
                        """
                    )
                    cursor.execute("SELECT version FROM schema_migrations")
                    applied = {row["version"] for row in cursor.fetchall()}
                    for path in sorted(migration_dir().glob("*.sql")):
                        version = path.name
                        if version in applied:
                            continue
                        logger.info("Applying database migration %s", version)
                        cursor.execute(path.read_text(encoding="utf-8"))
                        cursor.execute(
                            "INSERT INTO schema_migrations (version) VALUES (%s) ON CONFLICT DO NOTHING",
                            (version,),
                        )
                connection.commit()
        except Exception:
            self._handle_startup_persistence_failure("migration")

    def _hydrate_store_from_postgres(self, store: Any) -> None:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                self.users.hydrate(cursor, store)
                self.interviews.hydrate(cursor, store)
                self.rounds.hydrate(cursor, store)
                self.reports.hydrate(cursor, store)
                self.roadmaps.hydrate(cursor, store)
                self.bot.hydrate(cursor, store)
                self.workflow.hydrate(cursor, store)

    def hydrate_store(self, store: Any) -> None:
        if not self.enabled:
            return
        try:
            self._hydrate_store_from_postgres(store)
        except Exception:
            self._handle_startup_persistence_failure("store hydration")
            return
        logger.info("Hydrated development store facade from Postgres persistence.")

    def hydrate_workflow_jobs(self, store: Any) -> None:
        if not self.enabled:
            return
        try:
            with self.connect() as connection:
                with connection.cursor() as cursor:
                    self.workflow.hydrate(cursor, store)
        except Exception:
            self._handle_startup_persistence_failure("workflow hydration")

    def sync_from_store(self, store: Any) -> None:
        if not self.enabled:
            return
        with self.connect() as connection:
            with connection.cursor() as cursor:
                self.users.sync(cursor, store)
                self.interviews.sync(cursor, store)
                self.rounds.sync(cursor, store)
                self.reports.sync(cursor, store)
                self.roadmaps.sync(cursor, store)
                self.bot.sync(cursor, store)
                self.workflow.sync(cursor, store)
            connection.commit()

    def sync_dirty(self, store: Any, dirty: dict[str, set[str]]) -> None:
        """Persist only objects touched by the current request/workflow update.

        The development store can contain large historical workflow payloads and
        user-provided blobs. Mirroring the full store on every small workflow
        event makes async enqueueing block behind unrelated data, so request and
        worker paths use this delta sync instead.
        """

        if not self.enabled:
            return

        dirty_round_ids = set()
        for key in [
            "round_assets",
            "dsa_submissions",
            "aptitude_results",
            "technical_answers",
            "hr_answers",
        ]:
            dirty_round_ids.update(dirty.get(key, set()))

        dirty_runtime_ids = dirty.get("round_runtimes", set())
        dirty_practice_ids = dirty.get("practice_sessions", set())
        dirty_resume_ids = set(dirty.get("resumes", set()))
        dirty_report_ids = set(dirty.get("reports", set()))
        dirty_roadmap_ids = set(dirty.get("roadmaps", set()))
        dirty_bot_user_ids = set(dirty.get("bot_messages", set()))
        dirty_workflow_ids = set(dirty.get("workflow_jobs", set()))
        dirty_log_ids = set(dirty.get("logs", set()))
        dirty_direct_interview_ids = {str(key) for key in dirty.get("interviews", set())}
        dirty_interview_ids = dirty_direct_interview_ids | dirty_round_ids | dirty_log_ids
        for key in dirty_runtime_ids:
            dirty_interview_ids.add(str(key).split(":", 1)[0])

        parent_user_ids = {str(key) for key in dirty.get("users", set())}

        def add_user(user_id: Any) -> None:
            if user_id:
                parent_user_ids.add(str(user_id))

        def add_interview(interview_id: Any) -> None:
            if interview_id:
                dirty_interview_ids.add(str(interview_id))

        for resume_id in list(dirty_resume_ids):
            resume = store.resumes.get(resume_id)
            if resume:
                add_user(resume.get("userId"))

        for interview_id in list(dirty_interview_ids):
            interview = store.interviews.get(interview_id)
            if interview:
                if str(interview_id) in dirty_direct_interview_ids:
                    add_user(interview.get("userId"))
                if interview.get("resumeId"):
                    dirty_resume_ids.add(str(interview["resumeId"]))

        for workflow_id in dirty_workflow_ids:
            job = store.workflow_jobs.get(workflow_id)
            add_interview((job or {}).get("interviewId") or workflow_id)

        for report_id in dirty_report_ids:
            report = store.reports.get(report_id)
            if report:
                add_user(report.get("userId"))
                add_interview(report.get("interviewId"))

        for roadmap_id in dirty_roadmap_ids:
            roadmap = store.roadmaps.get(roadmap_id)
            if roadmap:
                add_user(roadmap.get("userId"))

        for session in store.sessions.values():
            if session.get("token") in dirty.get("sessions", set()) or session.get("id") in dirty.get("sessions", set()):
                add_user(session.get("user_id") or session.get("userId"))

        for practice_id in dirty_practice_ids:
            session = store.practice_sessions.get(practice_id)
            if session:
                add_user(session.get("userId"))

        for user_id in dirty_bot_user_ids:
            add_user(user_id)

        for interview_id in list(dirty_interview_ids):
            interview = store.interviews.get(interview_id)
            if interview:
                if str(interview_id) in dirty_direct_interview_ids:
                    add_user(interview.get("userId"))
                if interview.get("resumeId"):
                    dirty_resume_ids.add(str(interview["resumeId"]))

        view = SimpleNamespace(
            users={key: store.users[key] for key in parent_user_ids if key in store.users},
            sessions={key: store.sessions[key] for key in dirty.get("sessions", set()) if key in store.sessions},
            resumes={key: store.resumes[key] for key in dirty_resume_ids if key in store.resumes},
            interviews={key: store.interviews[key] for key in dirty_interview_ids if key in store.interviews},
            logs={key: store.logs.get(key, []) for key in dirty_log_ids},
            dsa_problems={key: store.dsa_problems.get(key, []) for key in dirty_round_ids},
            dsa_submissions={key: store.dsa_submissions.get(key, []) for key in dirty.get("dsa_submissions", set())},
            aptitude_questions={key: store.aptitude_questions.get(key, []) for key in dirty_round_ids},
            aptitude_results={
                key: store.aptitude_results[key]
                for key in dirty.get("aptitude_results", set())
                if key in store.aptitude_results
            },
            technical_questions={key: store.technical_questions.get(key, []) for key in dirty_round_ids},
            technical_answers={
                key: store.technical_answers.get(key, []) for key in dirty.get("technical_answers", set())
            },
            hr_questions={key: store.hr_questions.get(key, []) for key in dirty_round_ids},
            hr_answers={key: store.hr_answers.get(key, []) for key in dirty.get("hr_answers", set())},
            round_runtimes={
                key: store.round_runtimes[key] for key in dirty_runtime_ids if key in store.round_runtimes
            },
            reports={key: store.reports[key] for key in dirty_report_ids if key in store.reports},
            roadmaps={key: store.roadmaps[key] for key in dirty_roadmap_ids if key in store.roadmaps},
            bot_messages={key: store.bot_messages.get(key, []) for key in dirty_bot_user_ids},
            practice_sessions={
                key: store.practice_sessions[key]
                for key in dirty_practice_ids
                if key in store.practice_sessions
            },
            workflow_jobs={
                key: store.workflow_jobs[key] for key in dirty_workflow_ids if key in store.workflow_jobs
            },
        )

        with self.connect() as connection:
            with connection.cursor() as cursor:
                if view.users or view.sessions:
                    self.users.sync(cursor, view)
                if view.resumes or view.interviews or view.logs:
                    self.interviews.sync(cursor, view)
                if (
                    view.dsa_problems
                    or view.aptitude_questions
                    or view.technical_questions
                    or view.hr_questions
                    or view.dsa_submissions
                    or view.aptitude_results
                    or view.technical_answers
                    or view.hr_answers
                    or view.round_runtimes
                    or view.practice_sessions
                ):
                    self.rounds.sync(cursor, view)
                if view.reports:
                    self.reports.sync(cursor, view)
                if view.roadmaps:
                    self.roadmaps.sync(cursor, view)
                if view.bot_messages:
                    self.bot.sync(cursor, view)
                if view.workflow_jobs:
                    self.workflow.sync(cursor, view)
            connection.commit()

    def hydrate_interview_bundle(self, store: Any, interview_id: str) -> bool:
        """Refresh one interview and its workflow/round payloads from Postgres."""

        parent_id = valid_uuid(interview_id)
        if not self.enabled or not parent_id:
            return False

        def payloads_for(cursor, table: str) -> list[dict[str, Any]]:
            cursor.execute(f"SELECT payload FROM {table} WHERE interview_id = %s", (parent_id,))
            return [payload_from_row(row) for row in cursor.fetchall() if payload_from_row(row)]

        found = False
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT payload FROM interviews WHERE id = %s LIMIT 1", (parent_id,))
                interview = payload_from_row(cursor.fetchone() or {})
                if interview:
                    store.interviews[parent_id] = interview
                    found = True

                user_id = valid_uuid(interview.get("userId")) if interview else None
                if user_id:
                    cursor.execute("SELECT payload FROM users WHERE id = %s LIMIT 1", (user_id,))
                    user = payload_from_row(cursor.fetchone() or {})
                    if user:
                        store.users[user_id] = user
                        if user.get("email"):
                            store.users_by_email[str(user["email"]).lower()] = user_id

                resume_id = valid_uuid(interview.get("resumeId")) if interview and interview.get("resumeId") else None
                if resume_id:
                    cursor.execute("SELECT payload FROM resumes WHERE id = %s LIMIT 1", (resume_id,))
                    resume = payload_from_row(cursor.fetchone() or {})
                    if resume:
                        store.resumes[resume_id] = resume

                logs = payloads_for(cursor, "execution_logs")
                if logs or found:
                    store.logs[parent_id] = logs

                store.dsa_problems[parent_id] = payloads_for(cursor, "dsa_problems")
                store.aptitude_questions[parent_id] = payloads_for(cursor, "aptitude_questions")
                store.technical_questions[parent_id] = payloads_for(cursor, "technical_questions")
                store.hr_questions[parent_id] = payloads_for(cursor, "hr_questions")
                store.dsa_submissions[parent_id] = payloads_for(cursor, "dsa_submissions")
                store.technical_answers[parent_id] = payloads_for(cursor, "technical_answers")
                store.hr_answers[parent_id] = payloads_for(cursor, "hr_answers")

                cursor.execute("SELECT payload FROM aptitude_results WHERE interview_id = %s LIMIT 1", (parent_id,))
                aptitude_result = payload_from_row(cursor.fetchone() or {})
                if aptitude_result:
                    store.aptitude_results[parent_id] = aptitude_result

                cursor.execute(
                    "SELECT payload FROM workflow_jobs WHERE interview_id = %s ORDER BY updated_at DESC LIMIT 1",
                    (parent_id,),
                )
                workflow_job = payload_from_row(cursor.fetchone() or {})
                if workflow_job:
                    store.workflow_jobs[parent_id] = workflow_job

                for runtime in payloads_for(cursor, "round_runtimes"):
                    if runtime.get("interviewId") and runtime.get("round"):
                        store.round_runtimes[f"{runtime['interviewId']}:{runtime['round']}"] = runtime
        return found

    def upsert_user(self, user: dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self.connect() as connection:
            with connection.cursor() as cursor:
                self.users.upsert_user(cursor, user)
            connection.commit()

    def upsert_session(self, token: str, session: dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self.connect() as connection:
            with connection.cursor() as cursor:
                self.users.upsert_session(cursor, token, session)
            connection.commit()

    def delete_session(self, token: str) -> None:
        if not self.enabled:
            return
        with self.connect() as connection:
            with connection.cursor() as cursor:
                self.users.delete_session(cursor, token)
            connection.commit()

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        with self.connect() as connection:
            with connection.cursor() as cursor:
                return self.users.get_user_by_email(cursor, email)

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        with self.connect() as connection:
            with connection.cursor() as cursor:
                return self.users.get_user_by_id(cursor, user_id)

    def get_session_by_token(self, token: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        with self.connect() as connection:
            with connection.cursor() as cursor:
                return self.users.get_session_by_token(cursor, token)

    def get_session_by_refresh_token(self, refresh_token: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        with self.connect() as connection:
            with connection.cursor() as cursor:
                return self.users.get_session_by_refresh_token(cursor, refresh_token)

    def clear_round_state(self, interview_id: str, round_name: str) -> None:
        if not self.enabled:
            return
        with self.connect() as connection:
            with connection.cursor() as cursor:
                self.rounds.clear_round_state(cursor, interview_id, round_name)
            connection.commit()

    def delete_round_runtime(self, interview_id: str, round_name: str) -> None:
        if not self.enabled:
            return
        with self.connect() as connection:
            with connection.cursor() as cursor:
                self.rounds.delete_round_runtime(cursor, interview_id, round_name)
            connection.commit()

    def delete_report(self, report_id: str) -> None:
        if not self.enabled:
            return
        with self.connect() as connection:
            with connection.cursor() as cursor:
                self.reports.delete_report(cursor, report_id)
            connection.commit()

    def upsert_memory(
        self,
        *,
        memory_id: str,
        user_id: str,
        memory_type: str,
        source_id: str,
        text: str,
        metadata: dict[str, Any],
        embedding: list[float] | None = None,
    ) -> None:
        if not self.enabled:
            return
        with self.connect() as connection:
            with connection.cursor() as cursor:
                self.memory.upsert_memory(
                    cursor,
                    memory_id=memory_id,
                    user_id=user_id,
                    memory_type=memory_type,
                    source_id=source_id,
                    text=text,
                    metadata=metadata,
                    embedding=embedding,
                )
            connection.commit()

    def query_memory(
        self,
        *,
        user_id: str,
        query: str,
        query_embedding: list[float],
        limit: int = 5,
        memory_types: list[str] | None = None,
        privacy_scopes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        with self.connect() as connection:
            with connection.cursor() as cursor:
                return self.memory.query_memory(
                    cursor,
                    user_id=user_id,
                    query=query,
                    query_embedding=query_embedding,
                    limit=limit,
                    memory_types=memory_types,
                    privacy_scopes=privacy_scopes,
                )


persistence_manager = PersistenceManager()
