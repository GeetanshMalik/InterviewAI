from __future__ import annotations

from typing import Any

from psycopg2.extras import Json

from services.repositories.base import as_bool, as_float, as_int, dict_or_empty, iso_value, list_or_empty, logger, payload_from_row, valid_uuid


def _payload(value: dict[str, Any]) -> Json:
    return Json(value)


def _fetch_payloads(cursor, table: str) -> list[dict[str, Any]]:
    cursor.execute(f"SELECT payload FROM {table}")
    return [payload_from_row(row) for row in cursor.fetchall() if payload_from_row(row)]


def _group_by_interview(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        interview_id = item.get("interviewId") or item.get("interview_id")
        if interview_id:
            grouped.setdefault(str(interview_id), []).append(item)
    return grouped


def _has_store_user(store, user_id: str) -> bool:
    return str(user_id) in {str(item_id) for item_id in getattr(store, "users", {})}


class UserRepository:
    def _user_from_row(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if not row:
            return None
        user = payload_from_row(row)
        user.update(
            {
                "id": str(row.get("id")),
                "name": row.get("name") or user.get("name") or "",
                "email": row.get("email") or user.get("email") or "",
                "hashed_password": row.get("hashed_password") or user.get("hashed_password") or "dev",
                "avatar": row.get("avatar_url") if row.get("avatar_url") is not None else user.get("avatar"),
                "preferred_language": row.get("preferred_language") or user.get("preferred_language") or "javascript",
                "ai_memory_enabled": row.get("ai_memory_enabled") if row.get("ai_memory_enabled") is not None else user.get("ai_memory_enabled", True),
                "appearance_theme": row.get("appearance_theme") or user.get("appearance_theme") or "dark",
                "createdAt": iso_value(row.get("created_at")) or user.get("createdAt"),
                "updatedAt": iso_value(row.get("updated_at")) or user.get("updatedAt"),
            }
        )
        return user

    def _session_from_row(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if not row:
            return None
        session = payload_from_row(row)
        session.update(
            {
                "id": str(row.get("id")),
                "user_id": str(row.get("user_id")),
                "token": row.get("token") or session.get("token"),
                "refresh_token": row.get("refresh_token") or session.get("refresh_token"),
                "expires_at": iso_value(row.get("expires_at")) or session.get("expires_at"),
                "created_at": iso_value(row.get("created_at")) or session.get("created_at"),
            }
        )
        return session

    def get_user_by_email(self, cursor, email: str) -> dict[str, Any] | None:
        cursor.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(%s) LIMIT 1", (email,))
        return self._user_from_row(cursor.fetchone())

    def get_user_by_id(self, cursor, user_id: str) -> dict[str, Any] | None:
        valid_user_id = valid_uuid(user_id)
        if not valid_user_id:
            return None
        cursor.execute("SELECT * FROM users WHERE id = %s LIMIT 1", (valid_user_id,))
        return self._user_from_row(cursor.fetchone())

    def get_session_by_token(self, cursor, token: str) -> dict[str, Any] | None:
        cursor.execute("SELECT * FROM sessions WHERE token = %s LIMIT 1", (token,))
        return self._session_from_row(cursor.fetchone())

    def get_session_by_refresh_token(self, cursor, refresh_token: str) -> dict[str, Any] | None:
        cursor.execute("SELECT * FROM sessions WHERE refresh_token = %s LIMIT 1", (refresh_token,))
        return self._session_from_row(cursor.fetchone())

    def upsert_user(self, cursor, user: dict[str, Any]) -> None:
        user_id = valid_uuid(user.get("id"))
        if not user_id:
            return
        cursor.execute(
            """
            INSERT INTO users (
                id, name, email, hashed_password, avatar_url, preferred_language,
                ai_memory_enabled, appearance_theme, created_at, updated_at, payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                email = EXCLUDED.email,
                hashed_password = EXCLUDED.hashed_password,
                avatar_url = EXCLUDED.avatar_url,
                preferred_language = EXCLUDED.preferred_language,
                ai_memory_enabled = EXCLUDED.ai_memory_enabled,
                appearance_theme = EXCLUDED.appearance_theme,
                updated_at = EXCLUDED.updated_at,
                payload = EXCLUDED.payload
            """,
            (
                user_id,
                user.get("name") or "",
                user.get("email") or "",
                user.get("hashed_password") or "dev",
                user.get("avatar"),
                user.get("preferred_language") or "javascript",
                user.get("ai_memory_enabled", True),
                user.get("appearance_theme") or "dark",
                iso_value(user.get("createdAt")),
                iso_value(user.get("updatedAt")),
                _payload(user),
            ),
        )

    def upsert_session(self, cursor, token: str, session: dict[str, Any]) -> None:
        session_id = valid_uuid(session.get("id"))
        user_id = valid_uuid(session.get("user_id") or session.get("userId"))
        if not session_id or not user_id:
            return
        cursor.execute(
            """
            INSERT INTO sessions (id, user_id, token, refresh_token, expires_at, created_at, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                token = EXCLUDED.token,
                refresh_token = EXCLUDED.refresh_token,
                expires_at = EXCLUDED.expires_at,
                payload = EXCLUDED.payload
            """,
            (
                session_id,
                user_id,
                session.get("token") or token,
                session.get("refresh_token"),
                iso_value(session.get("expires_at")),
                iso_value(session.get("created_at")),
                _payload(session),
            ),
        )

    def delete_session(self, cursor, token: str) -> None:
        cursor.execute("DELETE FROM sessions WHERE token = %s", (token,))

    def sync(self, cursor, store) -> None:
        for user in store.users.values():
            self.upsert_user(cursor, user)

        for token, session in store.sessions.items():
            self.upsert_session(cursor, token, session)

    def hydrate(self, cursor, store) -> None:
        users = _fetch_payloads(cursor, "users")
        sessions = _fetch_payloads(cursor, "sessions")
        store.users = {item["id"]: item for item in users if item.get("id")}
        store.users_by_email = {item["email"].lower(): item["id"] for item in users if item.get("email") and item.get("id")}
        store.sessions = {item["token"]: item for item in sessions if item.get("token")}


class InterviewRepository:
    def sync(self, cursor, store) -> None:
        for resume in store.resumes.values():
            resume_id = valid_uuid(resume.get("id"))
            user_id = valid_uuid(resume.get("userId"))
            if not resume_id or not user_id:
                continue
            if not _has_store_user(store, user_id):
                logger.warning("Skipping resume %s for missing local user %s during Postgres sync.", resume_id, user_id)
                continue
            cursor.execute(
                """
                INSERT INTO resumes (
                    id, user_id, file_name, file_path, text, ats_score, keyword_score,
                    overall_resume_score, analysis_result, rewrite_suggestions,
                    missing_skills, created_at, payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    file_name = EXCLUDED.file_name,
                    file_path = EXCLUDED.file_path,
                    text = EXCLUDED.text,
                    ats_score = EXCLUDED.ats_score,
                    keyword_score = EXCLUDED.keyword_score,
                    overall_resume_score = EXCLUDED.overall_resume_score,
                    analysis_result = EXCLUDED.analysis_result,
                    rewrite_suggestions = EXCLUDED.rewrite_suggestions,
                    missing_skills = EXCLUDED.missing_skills,
                    payload = EXCLUDED.payload
                """,
                (
                    resume_id,
                    user_id,
                    resume.get("fileName") or resume.get("file_name"),
                    resume.get("filePath") or resume.get("file_path"),
                    resume.get("text") or "",
                    as_float(resume.get("atsScore")),
                    as_float(resume.get("keywordScore")),
                    as_float(resume.get("overallResumeScore")),
                    _payload(resume),
                    _payload({"rewriteSuggestions": resume.get("rewriteSuggestions", [])}),
                    list_or_empty(resume.get("missingSkills")),
                    iso_value(resume.get("uploadedAt") or resume.get("createdAt")),
                    _payload(resume),
                ),
            )

        for interview in store.interviews.values():
            interview_id = valid_uuid(interview.get("id"))
            user_id = valid_uuid(interview.get("userId"))
            resume_id = valid_uuid(interview.get("resumeId")) if interview.get("resumeId") else None
            if not interview_id or not user_id:
                continue
            if not _has_store_user(store, user_id):
                logger.warning("Skipping interview %s for missing local user %s during Postgres sync.", interview_id, user_id)
                continue
            cursor.execute(
                """
                INSERT INTO interviews (
                    id, user_id, name, email, target_role, company_style, difficulty,
                    job_description, preferred_language, skills, status, current_tab,
                    resume_id, overall_score, created_at, completed_at, payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    email = EXCLUDED.email,
                    target_role = EXCLUDED.target_role,
                    company_style = EXCLUDED.company_style,
                    difficulty = EXCLUDED.difficulty,
                    job_description = EXCLUDED.job_description,
                    preferred_language = EXCLUDED.preferred_language,
                    skills = EXCLUDED.skills,
                    status = EXCLUDED.status,
                    current_tab = EXCLUDED.current_tab,
                    resume_id = EXCLUDED.resume_id,
                    overall_score = EXCLUDED.overall_score,
                    completed_at = EXCLUDED.completed_at,
                    payload = EXCLUDED.payload
                """,
                (
                    interview_id,
                    user_id,
                    interview.get("name"),
                    interview.get("email"),
                    interview.get("target_role") or interview.get("role"),
                    interview.get("company_style") or interview.get("companyStyle"),
                    interview.get("difficulty"),
                    interview.get("job_description") or interview.get("jobDescription"),
                    interview.get("preferred_language") or interview.get("language"),
                    list_or_empty(interview.get("skills")),
                    interview.get("status"),
                    interview.get("currentStep") or interview.get("current_tab"),
                    resume_id,
                    as_float(interview.get("overallScore")),
                    iso_value(interview.get("createdAt")),
                    iso_value(interview.get("completedAt")),
                    _payload(interview),
                ),
            )

        for interview_id, logs in store.logs.items():
            for log in logs:
                log_id = valid_uuid(log.get("id"))
                parent_id = valid_uuid(log.get("interview_id") or interview_id)
                if not log_id or not parent_id:
                    continue
                cursor.execute(
                    """
                    INSERT INTO execution_logs (
                        id, interview_id, event_type, agent, message, step, metadata, created_at, payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        event_type = EXCLUDED.event_type,
                        agent = EXCLUDED.agent,
                        message = EXCLUDED.message,
                        step = EXCLUDED.step,
                        metadata = EXCLUDED.metadata,
                        payload = EXCLUDED.payload
                    """,
                    (
                        log_id,
                        parent_id,
                        log.get("type") or log.get("event_type") or "info",
                        log.get("agent") or "Workflow Orchestrator Agent",
                        log.get("message") or "",
                        log.get("step"),
                        _payload(dict_or_empty(log.get("metadata"))),
                        iso_value(log.get("timestamp") or log.get("created_at")),
                        _payload(log),
                    ),
                )

    def hydrate(self, cursor, store) -> None:
        resumes = _fetch_payloads(cursor, "resumes")
        interviews = _fetch_payloads(cursor, "interviews")
        logs = _fetch_payloads(cursor, "execution_logs")
        store.resumes = {item["id"]: item for item in resumes if item.get("id")}
        store.interviews = {item["id"]: item for item in interviews if item.get("id")}
        store.logs = _group_by_interview(logs)


class RoundRepository:
    def sync(self, cursor, store) -> None:
        self._sync_questions(cursor, "dsa_problems", store.dsa_problems)
        self._sync_aptitude_questions(cursor, store.aptitude_questions)
        self._sync_interview_questions(cursor, "technical_questions", store.technical_questions)
        self._sync_interview_questions(cursor, "hr_questions", store.hr_questions)
        self._sync_dsa_submissions(cursor, store)
        self._sync_aptitude_results(cursor, store)
        self._sync_answer_round(cursor, "technical_answers", store.technical_answers, store)
        self._sync_answer_round(cursor, "hr_answers", store.hr_answers, store)
        self._sync_round_runtimes(cursor, store)
        self._sync_practice_sessions(cursor, store)

    def _sync_questions(self, cursor, table: str, grouped: dict[str, list[dict[str, Any]]]) -> None:
        for interview_id, questions in grouped.items():
            parent_id = valid_uuid(interview_id)
            if not parent_id:
                continue
            for item in questions:
                item_id = valid_uuid(item.get("id"))
                if not item_id:
                    continue
                cursor.execute(
                    f"""
                    INSERT INTO {table} (
                        id, interview_id, problem_number, category, title, description, difficulty,
                        examples, test_cases, constraints, tags, payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        category = EXCLUDED.category,
                        title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        difficulty = EXCLUDED.difficulty,
                        examples = EXCLUDED.examples,
                        test_cases = EXCLUDED.test_cases,
                        constraints = EXCLUDED.constraints,
                        tags = EXCLUDED.tags,
                        payload = EXCLUDED.payload
                    """,
                    (
                        item_id,
                        parent_id,
                        as_int(item.get("problem_number") or item.get("question_number")),
                        item.get("category"),
                        item.get("title") or item.get("question_text"),
                        item.get("description") or item.get("question_text"),
                        item.get("difficulty"),
                        _payload({"examples": item.get("examples", [])}),
                        _payload(item.get("test_cases", [])),
                        item.get("constraints"),
                        list_or_empty(item.get("tags")),
                        _payload(item),
                    ),
                )

    def _sync_aptitude_questions(self, cursor, grouped: dict[str, list[dict[str, Any]]]) -> None:
        for interview_id, questions in grouped.items():
            parent_id = valid_uuid(interview_id)
            if not parent_id:
                continue
            for item in questions:
                item_id = valid_uuid(item.get("id"))
                if not item_id:
                    continue
                cursor.execute(
                    """
                    INSERT INTO aptitude_questions (
                        id, interview_id, question_number, question_text, options,
                        correct_answer, category, difficulty, explanation, payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        question_text = EXCLUDED.question_text,
                        options = EXCLUDED.options,
                        correct_answer = EXCLUDED.correct_answer,
                        category = EXCLUDED.category,
                        difficulty = EXCLUDED.difficulty,
                        explanation = EXCLUDED.explanation,
                        payload = EXCLUDED.payload
                    """,
                    (
                        item_id,
                        parent_id,
                        as_int(item.get("question_number")),
                        item.get("question_text") or item.get("question"),
                        _payload(item.get("options", {})),
                        item.get("correct_answer"),
                        item.get("category"),
                        item.get("difficulty"),
                        item.get("explanation"),
                        _payload(item),
                    ),
                )

    def _sync_interview_questions(self, cursor, table: str, grouped: dict[str, list[dict[str, Any]]]) -> None:
        for interview_id, questions in grouped.items():
            parent_id = valid_uuid(interview_id)
            if not parent_id:
                continue
            for item in questions:
                item_id = valid_uuid(item.get("id"))
                if not item_id:
                    continue
                cursor.execute(
                    f"""
                    INSERT INTO {table} (
                        id, interview_id, question_number, question_text, keywords,
                        difficulty, answer_mode, timer_seconds, payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        question_text = EXCLUDED.question_text,
                        keywords = EXCLUDED.keywords,
                        difficulty = EXCLUDED.difficulty,
                        answer_mode = EXCLUDED.answer_mode,
                        timer_seconds = EXCLUDED.timer_seconds,
                        payload = EXCLUDED.payload
                    """,
                    (
                        item_id,
                        parent_id,
                        as_int(item.get("question_number")),
                        item.get("question_text") or item.get("question"),
                        list_or_empty(item.get("keywords")),
                        item.get("difficulty"),
                        item.get("answer_mode"),
                        as_int(item.get("timer_seconds")),
                        _payload(item),
                    ),
                )

    def _sync_dsa_submissions(self, cursor, store) -> None:
        for interview_id, submissions in store.dsa_submissions.items():
            parent_id = valid_uuid(interview_id)
            if not parent_id:
                continue
            for item in submissions:
                item_id = valid_uuid(item.get("id"))
                problem_id = valid_uuid(item.get("problemId"))
                user_id = valid_uuid(item.get("userId"))
                if not item_id or not problem_id or not user_id:
                    continue
                cursor.execute(
                    """
                    INSERT INTO dsa_submissions (
                        id, interview_id, problem_id, user_id, code, language, status,
                        test_results, time_taken_seconds, score, feedback, tool_result,
                        reasoning_evaluation, submitted_at, payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        code = EXCLUDED.code,
                        language = EXCLUDED.language,
                        status = EXCLUDED.status,
                        test_results = EXCLUDED.test_results,
                        time_taken_seconds = EXCLUDED.time_taken_seconds,
                        score = EXCLUDED.score,
                        feedback = EXCLUDED.feedback,
                        tool_result = EXCLUDED.tool_result,
                        reasoning_evaluation = EXCLUDED.reasoning_evaluation,
                        payload = EXCLUDED.payload
                    """,
                    (
                        item_id,
                        parent_id,
                        problem_id,
                        user_id,
                        item.get("code") or "",
                        item.get("language"),
                        item.get("status"),
                        _payload(item.get("testResults", [])),
                        as_int(item.get("timeTakenSeconds")),
                        as_float(item.get("score")),
                        item.get("feedback"),
                        _payload(item.get("toolResult", {})),
                        _payload(item.get("reasoningEvaluation", {})),
                        iso_value(item.get("submittedAt")),
                        _payload(item),
                    ),
                )

    def _sync_aptitude_results(self, cursor, store) -> None:
        for interview_id, item in store.aptitude_results.items():
            parent_id = valid_uuid(interview_id)
            interview = store.interviews.get(interview_id, {})
            user_id = valid_uuid(interview.get("userId"))
            if not parent_id:
                continue
            cursor.execute(
                """
                INSERT INTO aptitude_results (
                    interview_id, user_id, score, correct_count, wrong_count, result, submitted_at, payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (interview_id) DO UPDATE SET
                    score = EXCLUDED.score,
                    correct_count = EXCLUDED.correct_count,
                    wrong_count = EXCLUDED.wrong_count,
                    result = EXCLUDED.result,
                    payload = EXCLUDED.payload
                """,
                (
                    parent_id,
                    user_id,
                    as_float(item.get("score")),
                    as_int(item.get("correct")),
                    as_int(item.get("wrong")),
                    _payload(item),
                    iso_value(item.get("submittedAt")),
                    _payload(item),
                ),
            )

    def _sync_answer_round(self, cursor, table: str, grouped: dict[str, list[dict[str, Any]]], store) -> None:
        for interview_id, answers in grouped.items():
            parent_id = valid_uuid(interview_id)
            interview = store.interviews.get(interview_id, {})
            user_id = valid_uuid(interview.get("userId"))
            if not parent_id or not user_id:
                continue
            for item in answers:
                item_id = valid_uuid(item.get("id"))
                question_id = valid_uuid(item.get("questionId"))
                if not item_id or not question_id:
                    continue
                cursor.execute(
                    f"""
                    INSERT INTO {table} (
                        id, interview_id, question_id, user_id, answer, transcript_confidence,
                        score, feedback, matched_keywords, safety_flags, answer_mode,
                        time_taken_seconds, timer_expired, speech_metrics, proctor_events,
                        repeat_count, paraphrase_count, answer_source, rubric, evidence,
                        improvement_suggestions, confidence_score, communication_score,
                        bias_guardrails, evaluation_agent, evaluation_provider,
                        evaluation_model, evaluated_at, internal_evaluation_trace,
                        submitted_at, payload
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        answer = EXCLUDED.answer,
                        transcript_confidence = EXCLUDED.transcript_confidence,
                        score = EXCLUDED.score,
                        feedback = EXCLUDED.feedback,
                        matched_keywords = EXCLUDED.matched_keywords,
                        safety_flags = EXCLUDED.safety_flags,
                        answer_mode = EXCLUDED.answer_mode,
                        time_taken_seconds = EXCLUDED.time_taken_seconds,
                        timer_expired = EXCLUDED.timer_expired,
                        speech_metrics = EXCLUDED.speech_metrics,
                        proctor_events = EXCLUDED.proctor_events,
                        repeat_count = EXCLUDED.repeat_count,
                        paraphrase_count = EXCLUDED.paraphrase_count,
                        answer_source = EXCLUDED.answer_source,
                        rubric = EXCLUDED.rubric,
                        evidence = EXCLUDED.evidence,
                        improvement_suggestions = EXCLUDED.improvement_suggestions,
                        confidence_score = EXCLUDED.confidence_score,
                        communication_score = EXCLUDED.communication_score,
                        bias_guardrails = EXCLUDED.bias_guardrails,
                        evaluation_agent = EXCLUDED.evaluation_agent,
                        evaluation_provider = EXCLUDED.evaluation_provider,
                        evaluation_model = EXCLUDED.evaluation_model,
                        evaluated_at = EXCLUDED.evaluated_at,
                        internal_evaluation_trace = EXCLUDED.internal_evaluation_trace,
                        payload = EXCLUDED.payload
                    """,
                    (
                        item_id,
                        parent_id,
                        question_id,
                        user_id,
                        item.get("answer") or "",
                        as_float(item.get("transcriptConfidence")),
                        as_float(item.get("score")),
                        item.get("feedback"),
                        list_or_empty(item.get("matchedKeywords")),
                        list_or_empty(item.get("safetyFlags")),
                        item.get("answerMode"),
                        as_int(item.get("timeTakenSeconds")),
                        as_bool(item.get("timerExpired")),
                        _payload(item.get("speechMetrics", {})),
                        _payload(item.get("proctorEvents", [])),
                        as_int(item.get("repeatCount")) or 0,
                        as_int(item.get("paraphraseCount")) or 0,
                        item.get("answerSource"),
                        _payload(item.get("rubric", {})),
                        _payload(item.get("evidence", [])),
                        _payload(item.get("improvementSuggestions", [])),
                        as_float(item.get("confidenceScore")),
                        as_float(item.get("communicationScore")),
                        _payload(item.get("biasGuardrails", [])),
                        item.get("evaluationAgent"),
                        item.get("evaluationProvider"),
                        item.get("evaluationModel"),
                        iso_value(item.get("evaluatedAt")),
                        _payload(item.get("internalEvaluationTrace", {})),
                        iso_value(item.get("submittedAt")),
                        _payload(item),
                    ),
                )

    def _sync_round_runtimes(self, cursor, store) -> None:
        for key, runtime in store.round_runtimes.items():
            runtime_id = valid_uuid(runtime.get("id"))
            interview_id = valid_uuid(runtime.get("interviewId"))
            user_id = valid_uuid(runtime.get("userId"))
            if not runtime_id or not interview_id:
                continue
            cursor.execute(
                """
                INSERT INTO round_runtimes (
                    id, interview_id, user_id, round_name, status, current_question_id,
                    state, payload, started_at, completed_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (interview_id, round_name) DO UPDATE SET
                    status = EXCLUDED.status,
                    current_question_id = EXCLUDED.current_question_id,
                    state = EXCLUDED.state,
                    payload = EXCLUDED.payload,
                    started_at = EXCLUDED.started_at,
                    completed_at = EXCLUDED.completed_at,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    runtime_id,
                    interview_id,
                    user_id,
                    runtime.get("round") or key.split(":")[-1],
                    runtime.get("status") or "not_started",
                    valid_uuid(runtime.get("currentQuestionId")) if runtime.get("currentQuestionId") else None,
                    _payload(runtime),
                    _payload(runtime),
                    iso_value(runtime.get("startedAt")),
                    iso_value(runtime.get("completedAt")),
                    iso_value(runtime.get("updatedAt")),
                ),
            )

    def _sync_practice_sessions(self, cursor, store) -> None:
        for item in store.practice_sessions.values():
            item_id = valid_uuid(item.get("id"))
            user_id = valid_uuid(item.get("userId"))
            if not item_id or not user_id:
                continue
            cursor.execute(
                """
                INSERT INTO practice_sessions (
                    id, user_id, mode, difficulty, topic_filter, questions, answers,
                    results, score, started_at, ended_at, payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    mode = EXCLUDED.mode,
                    difficulty = EXCLUDED.difficulty,
                    topic_filter = EXCLUDED.topic_filter,
                    questions = EXCLUDED.questions,
                    answers = EXCLUDED.answers,
                    results = EXCLUDED.results,
                    score = EXCLUDED.score,
                    ended_at = EXCLUDED.ended_at,
                    payload = EXCLUDED.payload
                """,
                (
                    item_id,
                    user_id,
                    item.get("mode"),
                    item.get("difficulty"),
                    item.get("topicFilter"),
                    _payload(item.get("privateQuestions") or item.get("questions", [])),
                    _payload(item.get("answers", {})),
                    _payload(item.get("results", {})),
                    as_float(item.get("score")),
                    iso_value(item.get("startedAt")),
                    iso_value(item.get("endedAt")),
                    _payload(item),
                ),
            )

    def hydrate(self, cursor, store) -> None:
        store.dsa_problems = _group_by_interview(_fetch_payloads(cursor, "dsa_problems"))
        store.aptitude_questions = _group_by_interview(_fetch_payloads(cursor, "aptitude_questions"))
        store.technical_questions = _group_by_interview(_fetch_payloads(cursor, "technical_questions"))
        store.hr_questions = _group_by_interview(_fetch_payloads(cursor, "hr_questions"))
        store.dsa_submissions = _group_by_interview(_fetch_payloads(cursor, "dsa_submissions"))
        aptitude_results = _fetch_payloads(cursor, "aptitude_results")
        store.aptitude_results = {
            item.get("interviewId") or item.get("interview_id"): item
            for item in aptitude_results
            if item.get("interviewId") or item.get("interview_id")
        }
        store.technical_answers = _group_by_interview(_fetch_payloads(cursor, "technical_answers"))
        store.hr_answers = _group_by_interview(_fetch_payloads(cursor, "hr_answers"))
        runtimes = _fetch_payloads(cursor, "round_runtimes")
        store.round_runtimes = {f"{item['interviewId']}:{item['round']}": item for item in runtimes if item.get("interviewId") and item.get("round")}
        practice = _fetch_payloads(cursor, "practice_sessions")
        store.practice_sessions = {item["id"]: item for item in practice if item.get("id")}

    def clear_round_state(self, cursor, interview_id: str, round_name: str) -> None:
        parent_id = valid_uuid(interview_id)
        if not parent_id:
            return
        if round_name == "dsa":
            cursor.execute("DELETE FROM dsa_submissions WHERE interview_id = %s", (parent_id,))
        elif round_name == "aptitude":
            cursor.execute("DELETE FROM aptitude_results WHERE interview_id = %s", (parent_id,))
        elif round_name == "technical":
            cursor.execute("DELETE FROM technical_answers WHERE interview_id = %s", (parent_id,))
            cursor.execute(
                "DELETE FROM round_runtimes WHERE interview_id = %s AND round_name = %s",
                (parent_id, "technical"),
            )
        elif round_name == "hr":
            cursor.execute("DELETE FROM hr_answers WHERE interview_id = %s", (parent_id,))
            cursor.execute(
                "DELETE FROM round_runtimes WHERE interview_id = %s AND round_name = %s",
                (parent_id, "hr"),
            )

    def delete_round_runtime(self, cursor, interview_id: str, round_name: str) -> None:
        parent_id = valid_uuid(interview_id)
        if not parent_id:
            return
        cursor.execute(
            "DELETE FROM round_runtimes WHERE interview_id = %s AND round_name = %s",
            (parent_id, round_name),
        )


class ReportRepository:
    def sync(self, cursor, store) -> None:
        for report in store.reports.values():
            report_id = valid_uuid(report.get("id"))
            user_id = valid_uuid(report.get("userId"))
            interview_id = valid_uuid(report.get("interviewId"))
            if not report_id or not user_id or not interview_id:
                continue
            cursor.execute(
                """
                INSERT INTO reports (
                    id, user_id, interview_id, overall_score, sections, strengths,
                    weaknesses, ai_feedback, executive_summary, what_went_wrong,
                    next_time_suggestions, action_plan, section_analyses,
                    generation_provider, communication_summary, proctor_summary,
                    transcript, created_at, payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    overall_score = EXCLUDED.overall_score,
                    sections = EXCLUDED.sections,
                    strengths = EXCLUDED.strengths,
                    weaknesses = EXCLUDED.weaknesses,
                    ai_feedback = EXCLUDED.ai_feedback,
                    executive_summary = EXCLUDED.executive_summary,
                    what_went_wrong = EXCLUDED.what_went_wrong,
                    next_time_suggestions = EXCLUDED.next_time_suggestions,
                    action_plan = EXCLUDED.action_plan,
                    section_analyses = EXCLUDED.section_analyses,
                    generation_provider = EXCLUDED.generation_provider,
                    communication_summary = EXCLUDED.communication_summary,
                    proctor_summary = EXCLUDED.proctor_summary,
                    transcript = EXCLUDED.transcript,
                    payload = EXCLUDED.payload
                """,
                (
                    report_id,
                    user_id,
                    interview_id,
                    as_float(report.get("overallScore")),
                    _payload(report.get("sections", [])),
                    list_or_empty(report.get("strengths")),
                    list_or_empty(report.get("weaknesses")),
                    report.get("aiFeedback"),
                    report.get("executiveSummary"),
                    _payload(report.get("whatWentWrong", [])),
                    _payload(report.get("nextTimeSuggestions", [])),
                    _payload(report.get("actionPlan", [])),
                    _payload(report.get("sectionAnalyses", [])),
                    report.get("generationProvider"),
                    _payload(report.get("communicationSummary", {})),
                    _payload(report.get("proctorSummary", {})),
                    _payload(report.get("transcript", [])),
                    iso_value(report.get("createdAt")),
                    _payload(report),
                ),
            )

    def hydrate(self, cursor, store) -> None:
        reports = _fetch_payloads(cursor, "reports")
        store.reports = {item["id"]: item for item in reports if item.get("id")}

    def delete_report(self, cursor, report_id: str) -> None:
        valid_report_id = valid_uuid(report_id)
        if not valid_report_id:
            return
        cursor.execute("DELETE FROM reports WHERE id = %s", (valid_report_id,))


class RoadmapRepository:
    def sync(self, cursor, store) -> None:
        for roadmap in store.roadmaps.values():
            roadmap_id = valid_uuid(roadmap.get("id"))
            user_id = valid_uuid(roadmap.get("userId"))
            report_id = valid_uuid(roadmap.get("sourceReportId")) if roadmap.get("sourceReportId") else None
            if not roadmap_id or not user_id:
                continue
            cursor.execute(
                """
                INSERT INTO roadmaps (
                    id, user_id, report_id, title, description, milestones, skills,
                    progress, is_active, archived_at, created_at, updated_at, payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    milestones = EXCLUDED.milestones,
                    skills = EXCLUDED.skills,
                    progress = EXCLUDED.progress,
                    is_active = EXCLUDED.is_active,
                    archived_at = EXCLUDED.archived_at,
                    updated_at = EXCLUDED.updated_at,
                    payload = EXCLUDED.payload
                """,
                (
                    roadmap_id,
                    user_id,
                    report_id,
                    roadmap.get("title"),
                    roadmap.get("description"),
                    _payload(roadmap.get("milestones", [])),
                    _payload(roadmap.get("skills", [])),
                    as_float(roadmap.get("progress")),
                    as_bool(roadmap.get("isActive")),
                    iso_value(roadmap.get("archivedAt")),
                    iso_value(roadmap.get("createdAt")),
                    iso_value(roadmap.get("updatedAt")),
                    _payload(roadmap),
                ),
            )

    def hydrate(self, cursor, store) -> None:
        roadmaps = _fetch_payloads(cursor, "roadmaps")
        store.roadmaps = {item["id"]: item for item in roadmaps if item.get("id")}


class BotRepository:
    def sync(self, cursor, store) -> None:
        for user_id, messages in getattr(store, "bot_messages", {}).items():
            valid_user_id = valid_uuid(user_id)
            if not valid_user_id:
                continue
            if not _has_store_user(store, valid_user_id):
                logger.warning("Skipping bot messages for missing local user %s during Postgres sync.", valid_user_id)
                continue

            cursor.execute("DELETE FROM bot_conversations WHERE user_id = %s", (valid_user_id,))
            for message in messages:
                message_id = valid_uuid(message.get("id"))
                if not message_id:
                    continue
                payload = {**message, "userId": valid_user_id}
                cursor.execute(
                    """
                    INSERT INTO bot_conversations (id, user_id, role, content, context, created_at, payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        role = EXCLUDED.role,
                        content = EXCLUDED.content,
                        context = EXCLUDED.context,
                        created_at = EXCLUDED.created_at,
                        payload = EXCLUDED.payload
                    """,
                    (
                        message_id,
                        valid_user_id,
                        message.get("role") or "assistant",
                        message.get("content") or "",
                        _payload(dict_or_empty(message.get("context"))),
                        iso_value(message.get("timestamp") or message.get("createdAt")),
                        _payload(payload),
                    ),
                )

    def hydrate(self, cursor, store) -> None:
        cursor.execute("SELECT * FROM bot_conversations ORDER BY created_at ASC")
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in cursor.fetchall():
            user_id = str(row.get("user_id") or "")
            if not user_id:
                continue
            message = payload_from_row(row)
            message.update(
                {
                    "id": str(row.get("id")),
                    "userId": user_id,
                    "role": row.get("role") or message.get("role") or "assistant",
                    "content": row.get("content") or message.get("content") or "",
                    "context": row.get("context") if row.get("context") is not None else message.get("context"),
                    "timestamp": iso_value(row.get("created_at")) or message.get("timestamp"),
                }
            )
            grouped.setdefault(user_id, []).append(message)
        store.bot_messages = grouped


class WorkflowRepository:
    def sync(self, cursor, store) -> None:
        for interview_id, job in store.workflow_jobs.items():
            job_id = valid_uuid(job.get("id"))
            parent_id = valid_uuid(job.get("interviewId") or interview_id)
            user_id = valid_uuid(job.get("userId"))
            if not job_id or not parent_id:
                continue
            cursor.execute(
                """
                INSERT INTO workflow_jobs (
                    id, interview_id, user_id, kind, status, current_node,
                    queue_backend, external_job_id, attempt, max_attempts,
                    cancel_requested, queued_at, started_at, finished_at,
                    last_heartbeat_at, result, error, payload, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    current_node = EXCLUDED.current_node,
                    queue_backend = EXCLUDED.queue_backend,
                    external_job_id = EXCLUDED.external_job_id,
                    attempt = EXCLUDED.attempt,
                    max_attempts = EXCLUDED.max_attempts,
                    cancel_requested = EXCLUDED.cancel_requested,
                    queued_at = EXCLUDED.queued_at,
                    started_at = EXCLUDED.started_at,
                    finished_at = EXCLUDED.finished_at,
                    last_heartbeat_at = EXCLUDED.last_heartbeat_at,
                    result = EXCLUDED.result,
                    error = EXCLUDED.error,
                    payload = EXCLUDED.payload,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    job_id,
                    parent_id,
                    user_id,
                    job.get("kind") or "interview_generation",
                    job.get("status") or "ready",
                    job.get("currentNode"),
                    job.get("queueBackend"),
                    job.get("externalJobId"),
                    as_int(job.get("attempt")) or 0,
                    as_int(job.get("maxAttempts")) or 1,
                    as_bool(job.get("cancelRequested")),
                    iso_value(job.get("queuedAt")),
                    iso_value(job.get("startedAt")),
                    iso_value(job.get("finishedAt")),
                    iso_value(job.get("lastHeartbeatAt")),
                    _payload(job.get("result", {})),
                    job.get("error"),
                    _payload(job),
                    iso_value(job.get("createdAt")),
                    iso_value(job.get("updatedAt")),
                ),
            )
            self._sync_events(cursor, job, parent_id, job_id)
            self._sync_checkpoint(cursor, job, parent_id, user_id, job_id)

    def _sync_events(self, cursor, job: dict[str, Any], interview_id: str, job_id: str) -> None:
        for event in job.get("events", []):
            event_id = valid_uuid(event.get("id"))
            if not event_id:
                continue
            cursor.execute(
                """
                INSERT INTO agent_events (
                    id, interview_id, workflow_job_id, event_type, agent, message,
                    step, metadata, payload, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    event_type = EXCLUDED.event_type,
                    agent = EXCLUDED.agent,
                    message = EXCLUDED.message,
                    step = EXCLUDED.step,
                    metadata = EXCLUDED.metadata,
                    payload = EXCLUDED.payload
                """,
                (
                    event_id,
                    interview_id,
                    job_id,
                    event.get("type") or "info",
                    event.get("agent") or "Workflow Orchestrator Agent",
                    event.get("message") or "",
                    event.get("step"),
                    _payload(event.get("metadata", {})),
                    _payload(event),
                    iso_value(event.get("timestamp")),
                ),
            )

    def _sync_checkpoint(self, cursor, job: dict[str, Any], interview_id: str, user_id: str | None, job_id: str) -> None:
        workflow_state = dict_or_empty(dict_or_empty(job.get("result")).get("workflow_state"))
        if not workflow_state:
            return
        checkpoint_key = f"{job_id}:latest"
        cursor.execute(
            """
            INSERT INTO graph_checkpoints (
                workflow_job_id, interview_id, user_id, graph_name, checkpoint_key,
                state, metadata, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (graph_name, checkpoint_key) DO UPDATE SET
                workflow_job_id = EXCLUDED.workflow_job_id,
                state = EXCLUDED.state,
                metadata = EXCLUDED.metadata,
                updated_at = NOW()
            """,
            (
                job_id,
                interview_id,
                user_id,
                "interview_generation",
                checkpoint_key,
                _payload(workflow_state),
                _payload({"status": job.get("status"), "current_node": job.get("currentNode")}),
            ),
        )

    def hydrate(self, cursor, store) -> None:
        jobs = _fetch_payloads(cursor, "workflow_jobs")
        store.workflow_jobs = {
            (item.get("interviewId") or item.get("interview_id")): item
            for item in jobs
            if item.get("interviewId") or item.get("interview_id")
        }


class MemoryRepository:
    def __init__(self) -> None:
        self._has_vector_column_cache: bool | None = None

    def _has_vector_column(self, cursor) -> bool:
        if self._has_vector_column_cache is not None:
            return self._has_vector_column_cache
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'agent_memories'
                  AND column_name = 'embedding_vector'
            ) AS has_vector
            """
        )
        row = cursor.fetchone()
        self._has_vector_column_cache = bool(row and row.get("has_vector"))
        return self._has_vector_column_cache

    def _vector_literal(self, embedding: list[float]) -> str:
        return "[" + ",".join(f"{float(value):.8f}" for value in embedding) + "]"

    def _excerpt(self, text: str, limit: int = 900) -> str:
        return " ".join(str(text or "").split())[:limit]

    def upsert_memory(
        self,
        cursor,
        *,
        memory_id: str,
        user_id: str,
        memory_type: str,
        source_id: str,
        text: str,
        metadata: dict[str, Any],
        embedding: list[float] | None = None,
    ) -> None:
        valid_user_id = valid_uuid(user_id)
        if not valid_user_id:
            return
        cursor.execute(
            """
            INSERT INTO agent_memories (
                id, user_id, memory_type, source_id, source_route, source_agent,
                text, metadata, importance, privacy_scope, embedding, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                memory_type = EXCLUDED.memory_type,
                source_id = EXCLUDED.source_id,
                source_route = EXCLUDED.source_route,
                source_agent = EXCLUDED.source_agent,
                text = EXCLUDED.text,
                metadata = EXCLUDED.metadata,
                importance = EXCLUDED.importance,
                privacy_scope = EXCLUDED.privacy_scope,
                embedding = EXCLUDED.embedding
            """,
            (
                memory_id,
                valid_user_id,
                memory_type,
                source_id,
                metadata.get("source_route"),
                metadata.get("source_agent"),
                text,
                _payload(metadata),
                as_float(metadata.get("importance")) or 0.5,
                metadata.get("privacy_scope") or "user",
                _payload(embedding or []),
                iso_value(metadata.get("created_at")),
            ),
        )
        if embedding and self._has_vector_column(cursor):
            cursor.execute(
                "UPDATE agent_memories SET embedding_vector = %s::vector WHERE id = %s",
                (self._vector_literal(embedding), memory_id),
            )

    def query_memory(
        self,
        cursor,
        *,
        user_id: str,
        query: str,
        query_embedding: list[float],
        limit: int = 5,
        memory_types: list[str] | None = None,
        privacy_scopes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        valid_user_id = valid_uuid(user_id)
        if not valid_user_id:
            return []

        scopes = privacy_scopes or ["user"]
        filters = ["user_id = %s", "COALESCE(privacy_scope, 'user') = ANY(%s)"]
        params: list[Any] = [valid_user_id, scopes]
        if memory_types:
            filters.append("memory_type = ANY(%s)")
            params.append(memory_types)
        where_sql = " AND ".join(filters)

        if query_embedding and self._has_vector_column(cursor):
            params_with_vector = [self._vector_literal(query_embedding), *params, max(1, limit)]
            cursor.execute(
                f"""
                SELECT id, user_id, memory_type, source_id, text, metadata,
                       embedding_vector <=> %s::vector AS distance
                FROM agent_memories
                WHERE embedding_vector IS NOT NULL AND {where_sql}
                ORDER BY embedding_vector <=> %s::vector
                LIMIT %s
                """,
                [params_with_vector[0], *params, params_with_vector[0], params_with_vector[-1]],
            )
            rows = cursor.fetchall()
        else:
            cursor.execute(
                f"""
                SELECT id, user_id, memory_type, source_id, text, metadata, NULL AS distance
                FROM agent_memories
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                [*params, max(1, limit * 5)],
            )
            terms = {term.lower() for term in str(query).split() if len(term) > 2}
            scored = []
            for row in cursor.fetchall():
                text = str(row.get("text") or "")
                score = sum(1 for term in terms if term in text.lower())
                if not terms or score > 0:
                    scored.append((score, row))
            scored.sort(key=lambda item: item[0], reverse=True)
            rows = [row for _, row in scored[: max(1, limit)]]

        memories: list[dict[str, Any]] = []
        for row in rows:
            metadata = dict_or_empty(row.get("metadata"))
            metadata.setdefault("memory_type", row.get("memory_type"))
            metadata.setdefault("source_id", row.get("source_id"))
            text = str(row.get("text") or "")
            memories.append(
                {
                    "id": row.get("id"),
                    "user_id": str(row.get("user_id") or user_id),
                    "document_id": row.get("source_id"),
                    "text": text,
                    "excerpt": self._excerpt(text),
                    "metadata": metadata,
                    "distance": as_float(row.get("distance")),
                }
            )
        return memories


class GraphCheckpointRepository:
    def upsert_checkpoint(
        self,
        cursor,
        *,
        graph_name: str,
        checkpoint_key: str,
        state: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        workflow_job_id: str | None = None,
        interview_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO graph_checkpoints (
                workflow_job_id, interview_id, user_id, graph_name, checkpoint_key,
                state, metadata, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (graph_name, checkpoint_key) DO UPDATE SET
                workflow_job_id = EXCLUDED.workflow_job_id,
                interview_id = EXCLUDED.interview_id,
                user_id = EXCLUDED.user_id,
                state = EXCLUDED.state,
                metadata = EXCLUDED.metadata,
                updated_at = NOW()
            """,
            (
                valid_uuid(workflow_job_id) if workflow_job_id else None,
                valid_uuid(interview_id) if interview_id else None,
                valid_uuid(user_id) if user_id else None,
                graph_name,
                checkpoint_key,
                _payload(state),
                _payload(metadata or {}),
            ),
        )
