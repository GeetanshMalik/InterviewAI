import asyncio
from datetime import UTC, datetime, timedelta
from copy import deepcopy
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends

from auth.dependencies import get_current_user
from services.llm_optimization import llm_usage_metrics
from services.repositories.manager import persistence_manager
from services.store import store


router = APIRouter()
logger = logging.getLogger("interviewos.dashboard")
_overview_cache: dict[str, tuple[float, tuple[Any, ...], dict[str, Any]]] = {}
_last_dashboard_hydrate_at = 0.0
_last_dashboard_hydrate_warning_at = 0.0
_dashboard_hydrate_task: asyncio.Task[None] | None = None

DASHBOARD_HYDRATE_MIN_INTERVAL_SECONDS = 10.0
DASHBOARD_HYDRATE_WAIT_SECONDS = 1.25
DASHBOARD_HYDRATE_WARNING_INTERVAL_SECONDS = 30.0


async def _run_dashboard_hydration() -> None:
    if persistence_manager.enabled:
        await asyncio.to_thread(persistence_manager.hydrate_store, store)
    else:
        await asyncio.to_thread(store.load)


def _finish_dashboard_hydration(task: asyncio.Task[None]) -> None:
    global _dashboard_hydrate_task, _last_dashboard_hydrate_at
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:
        logger.warning("Dashboard hydration failed; returning current in-memory dashboard state.", exc_info=True)
    else:
        _last_dashboard_hydrate_at = time.monotonic()
    finally:
        if _dashboard_hydrate_task is task:
            _dashboard_hydrate_task = None


async def hydrate_dashboard_state(*, force: bool = False) -> None:
    global _dashboard_hydrate_task, _last_dashboard_hydrate_warning_at
    now = time.monotonic()
    if not force and now - _last_dashboard_hydrate_at < DASHBOARD_HYDRATE_MIN_INTERVAL_SECONDS:
        return

    current_loop = asyncio.get_running_loop()
    task = _dashboard_hydrate_task
    task_is_active = task is not None and not task.done() and task.get_loop() is current_loop

    if task_is_active and not force:
        return

    if not task_is_active:
        task = current_loop.create_task(_run_dashboard_hydration())
        _dashboard_hydrate_task = task
        task.add_done_callback(_finish_dashboard_hydration)

    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=DASHBOARD_HYDRATE_WAIT_SECONDS)
    except asyncio.TimeoutError:
        warning_now = time.monotonic()
        if warning_now - _last_dashboard_hydrate_warning_at > DASHBOARD_HYDRATE_WARNING_INTERVAL_SECONDS:
            logger.warning("Dashboard hydration is still running; returning current dashboard state.")
            _last_dashboard_hydrate_warning_at = warning_now
    except Exception:
        logger.warning("Dashboard hydration failed; returning current dashboard state.", exc_info=True)


def generated_round_asset_count(interview_id: str) -> int:
    return (
        len(store.dsa_problems.get(interview_id, []))
        + len(store.aptitude_questions.get(interview_id, []))
        + len(store.technical_questions.get(interview_id, []))
        + len(store.hr_questions.get(interview_id, []))
    )


def avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0


def dashboard_signature(user_id: str) -> tuple[Any, ...]:
    reports = store.user_reports(user_id)
    interviews = [item for item in store.interviews.values() if item["userId"] == user_id]
    interview_ids = {str(item.get("id") or "") for item in interviews if item.get("id")}
    practice_sessions = [item for item in store.practice_sessions.values() if item.get("userId") == user_id]
    roadmap = store.active_roadmap(user_id)
    return (
        len(reports),
        reports[0].get("id") if reports else "",
        reports[0].get("createdAt") if reports else "",
        len(interviews),
        max((item.get("updatedAt") or item.get("completedAt") or item.get("createdAt") or "" for item in interviews), default=""),
        sum(generated_round_asset_count(interview_id) for interview_id in interview_ids),
        max(
            (
                (store.workflow_jobs.get(interview_id) or {}).get("updatedAt")
                or (store.workflow_jobs.get(interview_id) or {}).get("finishedAt")
                or ""
                for interview_id in interview_ids
            ),
            default="",
        ),
        len(practice_sessions),
        max((item.get("updatedAt") or item.get("endedAt") or item.get("startedAt") or "" for item in practice_sessions), default=""),
        roadmap.get("id") if roadmap else "",
        roadmap.get("updatedAt") if roadmap else "",
    )


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def month_start(value: datetime) -> datetime:
    return datetime(value.year, value.month, 1, tzinfo=UTC)


def previous_month_start(value: datetime) -> datetime:
    if value.month == 1:
        return datetime(value.year - 1, 12, 1, tzinfo=UTC)
    return datetime(value.year, value.month - 1, 1, tzinfo=UTC)


def percent_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None if current == 0 else 100
    return round(((current - previous) / previous) * 100, 2)


def date_label(value: Any, fallback: str) -> str:
    parsed = parse_datetime(value)
    if not parsed:
        return fallback
    return f"{parsed.strftime('%b')} {parsed.day}"


def report_confidence(report: dict) -> float:
    transcript = report.get("transcript") or []
    confidences = [
        float(item.get("confidence", 0)) * 100
        for item in transcript
        if isinstance(item, dict) and item.get("confidence") is not None
    ]
    return avg(confidences) if confidences else float(report.get("overallScore") or 0)


def is_completed_interview(interview: dict[str, Any]) -> bool:
    return (
        interview.get("status") == "completed"
        or interview.get("currentStep") == "completed"
        or bool(interview.get("completedAt"))
    )


def completed_interview_entries(user_id: str) -> list[dict[str, Any]]:
    reports = store.user_reports(user_id)
    interviews = [item for item in store.interviews.values() if item["userId"] == user_id]
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    for report in reports:
        interview_id = report.get("interviewId")
        key = str(interview_id or f"report:{report['id']}")
        entries.append(
            {
                "id": key,
                "interview": store.interviews.get(interview_id) if interview_id else None,
                "report": report,
                "createdAt": report.get("createdAt"),
                "completedAt": report.get("createdAt"),
            }
        )
        seen.add(key)

    for interview in interviews:
        interview_id = str(interview["id"])
        if interview_id in seen:
            continue
        if not is_completed_interview(interview):
            continue
        entries.append(
            {
                "id": interview_id,
                "interview": interview,
                "report": None,
                "createdAt": interview.get("createdAt"),
                "completedAt": interview.get("completedAt") or interview.get("createdAt"),
            }
        )

    return sorted(
        entries,
        key=lambda item: parse_datetime(item.get("completedAt")) or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )


def practice_duration_seconds(item: dict) -> float:
    start = parse_datetime(item.get("startedAt") or item.get("createdAt"))
    end = parse_datetime(item.get("endedAt") or item.get("completedAt"))
    if not start or not end or end <= start:
        return 0
    duration = (end - start).total_seconds()
    return duration if duration <= 12 * 60 * 60 else 0


def interview_duration_seconds(interview: dict) -> float:
    created = parse_datetime(interview.get("createdAt"))
    completed = parse_datetime(interview.get("completedAt"))
    if not created or not completed or completed <= created:
        return 0
    duration = (completed - created).total_seconds()
    return duration if duration <= 12 * 60 * 60 else 0


def is_between(value: Any, start: datetime, end: datetime) -> bool:
    parsed = parse_datetime(value)
    return bool(parsed and start <= parsed < end)


def section_question_count(report: dict, section: dict) -> int:
    name = section.get("name")
    details = section.get("details") or {}
    interview_id = report.get("interviewId")
    if name == "DSA":
        return (
            len(store.dsa_problems.get(interview_id, []))
            or int(details.get("submissions") or 0)
            or len(details.get("items") or [])
        )
    if name == "Aptitude":
        return (
            len(store.aptitude_questions.get(interview_id, []))
            or len(details.get("per_question_results") or [])
            or int(details.get("correct") or 0) + int(details.get("wrong") or 0)
        )
    if name == "Technical":
        return (
            len(store.technical_questions.get(interview_id, []))
            or int(details.get("answers") or 0)
            or len(details.get("items") or [])
        )
    if name == "HR":
        return (
            len(store.hr_questions.get(interview_id, []))
            or int(details.get("answers") or 0)
            or len(details.get("items") or [])
        )
    return 0


def normalize_question_bucket(value: Any) -> str | None:
    text = str(value or "").lower()
    if any(token in text for token in ["dsa", "algorithm", "data structure", "coding"]):
        return "DSA"
    if any(token in text for token in ["aptitude", "quant", "logical", "reasoning", "probability", "ratio"]):
        return "Aptitude"
    if any(token in text for token in ["hr", "behavior", "behaviour", "communication"]):
        return "HR"
    if any(token in text for token in ["technical", "system", "frontend", "backend", "database", "api"]):
        return "Technical"
    return None


@router.get("/stats")
async def stats(current_user: dict = Depends(get_current_user)):
    await hydrate_dashboard_state()
    reports = store.user_reports(current_user["id"])
    scores = [float(report["overallScore"]) for report in reports]
    interviews = [item for item in store.interviews.values() if item["userId"] == current_user["id"]]
    completed_entries = completed_interview_entries(current_user["id"])
    practice_sessions = [
        item for item in store.practice_sessions.values() if item.get("userId") == current_user["id"]
    ]
    now = datetime.now(UTC)
    current_month_start = month_start(now)
    previous_start = previous_month_start(current_month_start)

    current_month_completed = [
        item for item in completed_entries if is_between(item.get("completedAt"), current_month_start, now + timedelta(days=1))
    ]
    previous_month_completed = [
        item for item in completed_entries if is_between(item.get("completedAt"), previous_start, current_month_start)
    ]
    current_month_reports = [
        report for report in reports if is_between(report.get("createdAt"), current_month_start, now + timedelta(days=1))
    ]
    previous_month_reports = [
        report for report in reports if is_between(report.get("createdAt"), previous_start, current_month_start)
    ]
    current_scores = [float(report.get("overallScore") or 0) for report in current_month_reports]
    previous_scores = [float(report.get("overallScore") or 0) for report in previous_month_reports]

    total_seconds = sum(interview_duration_seconds(item) for item in interviews)
    total_seconds += sum(practice_duration_seconds(item) for item in practice_sessions)
    current_seconds = sum(
        interview_duration_seconds(item)
        for item in interviews
        if is_between(item.get("createdAt"), current_month_start, now + timedelta(days=1))
    )
    current_seconds += sum(
        practice_duration_seconds(item)
        for item in practice_sessions
        if is_between(item.get("startedAt") or item.get("createdAt"), current_month_start, now + timedelta(days=1))
    )
    previous_seconds = sum(
        interview_duration_seconds(item)
        for item in interviews
        if is_between(item.get("createdAt"), previous_start, current_month_start)
    )
    previous_seconds += sum(
        practice_duration_seconds(item)
        for item in practice_sessions
        if is_between(item.get("startedAt") or item.get("createdAt"), previous_start, current_month_start)
    )

    return {
        "total_interviews": len(completed_entries),
        "completed_interviews": len(completed_entries),
        "scored_interviews": len(reports),
        "average_score": avg(scores),
        "average_confidence": avg([report_confidence(report) for report in reports]),
        "average_technical": avg([
            section["score"]
            for report in reports
            for section in report.get("sections", [])
            if section["name"] == "Technical"
        ]),
        "average_communication": avg([
            section["score"]
            for report in reports
            for section in report.get("sections", [])
            if section["name"] == "HR"
        ]),
        "best_score": max(scores) if scores else 0,
        "latest_score": scores[0] if scores else 0,
        "improvement_trend": round((scores[0] - scores[-1]), 2) if len(scores) > 1 else 0,
        "interview_change_percent": (
            percent_change(len(current_month_completed), len(previous_month_completed))
            if previous_month_completed
            else None
        ),
        "score_change_percent": (
            percent_change(avg(current_scores), avg(previous_scores)) if previous_scores else None
        ),
        "hours_practiced": round(total_seconds / 3600, 1),
        "hours_change_percent": (
            percent_change(round(current_seconds / 3600, 2), round(previous_seconds / 3600, 2))
            if previous_seconds > 0
            else None
        ),
    }


@router.get("/overview")
async def overview(current_user: dict = Depends(get_current_user)):
    """Single dashboard bootstrap payload.

    This replaces the frontend waterfall of stats/trends/distribution/subjects
    with one auth check, one CORS preflight, and one response.
    """

    user_id = current_user["id"]
    await hydrate_dashboard_state()
    signature = dashboard_signature(user_id)
    cached = _overview_cache.get(user_id)
    now = time.time()
    if cached and cached[0] > now and cached[1] == signature:
        return deepcopy(cached[2])

    score = await score_trend(current_user)
    payload = {
        "stats": await stats(current_user),
        "score_trend": score,
        "confidence_trend": [
            {"label": item["label"], "confidence": item.get("confidence", item.get("overall_score", 0))}
            for item in score
        ],
        "question_distribution": await question_distribution(current_user),
        "weak_strong_subjects": await weak_strong_subjects(current_user),
    }
    _overview_cache[user_id] = (now + 10, signature, deepcopy(payload))
    return payload


@router.get("/llm-metrics")
async def llm_metrics(current_user: dict = Depends(get_current_user)):
    # Metrics are aggregate process-level operational telemetry; no prompt content is exposed.
    return llm_usage_metrics.snapshot()


@router.get("/weak-strong-subjects")
async def weak_strong_subjects(current_user: dict = Depends(get_current_user)):
    await hydrate_dashboard_state()
    reports = store.user_reports(current_user["id"])
    subjects: dict[str, list[float]] = {}
    for report in reports:
        for section in report.get("sections", []):
            subjects.setdefault(section["name"], []).append(float(section["score"]))
    scored = [
        {
            "subject": subject,
            "score": avg(values),
            "status": "strong" if avg(values) >= 70 else "medium" if avg(values) >= 50 else "weak",
        }
        for subject, values in subjects.items()
    ]
    scored.sort(key=lambda item: item["score"], reverse=True)
    return {
        "subjects": scored,
        "strong_subjects": [item for item in scored if item["status"] == "strong"][:5],
        "weak_subjects": [item for item in reversed(scored) if item["status"] == "weak"][:5],
    }


@router.get("/heatmap")
async def heatmap(period: str = "90d", current_user: dict = Depends(get_current_user)):
    await hydrate_dashboard_state()
    days = int(period.removesuffix("d")) if period.endswith("d") and period[:-1].isdigit() else 90
    start = datetime.now(UTC) - timedelta(days=days)
    buckets: dict[str, list[float]] = {}
    for report in store.user_reports(current_user["id"]):
        created = parse_datetime(report.get("createdAt"))
        if not created or created < start:
            continue
        date_key = created.date().isoformat()
        buckets.setdefault(date_key, []).append(float(report.get("overallScore") or 0))
    return [
        {"date": date, "interview_count": len(scores), "avg_score": avg(scores)}
        for date, scores in sorted(buckets.items())
    ]


@router.get("/score-trend")
async def score_trend(current_user: dict = Depends(get_current_user)):
    await hydrate_dashboard_state()
    reports = list(reversed(store.user_reports(current_user["id"])))
    trend = []
    for index, report in enumerate(reports, start=1):
        sections = {section["name"]: section["score"] for section in report.get("sections", [])}
        label = date_label(report.get("createdAt"), f"Interview {index}")
        trend.append(
            {
                "interview_number": index,
                "date": report["createdAt"],
                "label": f"{label} #{index}",
                "overall_score": report["overallScore"],
                "confidence": report_confidence(report),
                "dsa": sections.get("DSA", 0),
                "aptitude": sections.get("Aptitude", 0),
                "technical": sections.get("Technical", 0),
                "hr": sections.get("HR", 0),
            }
        )
    return trend


@router.get("/confidence-trend")
async def confidence_trend(current_user: dict = Depends(get_current_user)):
    await hydrate_dashboard_state()
    return [
        {
            "label": item["label"],
            "confidence": report_confidence(report),
        }
        for item, report in zip(
            await score_trend(current_user),
            list(reversed(store.user_reports(current_user["id"]))),
        )
    ]


@router.get("/question-distribution")
async def question_distribution(current_user: dict = Depends(get_current_user)):
    await hydrate_dashboard_state()
    reports = store.user_reports(current_user["id"])
    totals = {"DSA": 0, "Aptitude": 0, "Technical": 0, "HR": 0}
    report_interview_ids: set[str] = set()
    for report in reports:
        if report.get("interviewId"):
            report_interview_ids.add(str(report["interviewId"]))
        for section in report.get("sections", []):
            if section["name"] in totals:
                totals[section["name"]] += section_question_count(report, section)
    for interview in store.interviews.values():
        if interview.get("userId") != current_user["id"]:
            continue
        interview_id = str(interview.get("id") or "")
        if not interview_id or interview_id in report_interview_ids:
            continue
        if not is_completed_interview(interview):
            continue
        totals["DSA"] += len(store.dsa_problems.get(interview_id, []))
        totals["Aptitude"] += len(store.aptitude_questions.get(interview_id, []))
        totals["Technical"] += len(store.technical_questions.get(interview_id, []))
        totals["HR"] += len(store.hr_questions.get(interview_id, []))
    for session in store.practice_sessions.values():
        if session.get("userId") != current_user["id"]:
            continue
        for question in session.get("questions") or []:
            bucket = normalize_question_bucket(
                question.get("category") or question.get("skill_tested") or question.get("type")
            )
            if bucket:
                totals[bucket] += 1
    return [{"name": name, "value": value} for name, value in totals.items() if value > 0]


@router.get("/ai-recommendations")
async def ai_recommendations(current_user: dict = Depends(get_current_user)):
    await hydrate_dashboard_state()
    latest = store.user_reports(current_user["id"])[:1]
    weakness = latest[0]["weaknesses"][0] if latest else "DSA"
    return {
        "recommendations": [
            f"Spend 30 minutes daily on {weakness}.",
            "Keep a mistake log after every practice session.",
            "Record one technical answer and review it for specificity.",
        ],
        "priority_topics": [weakness, "Timed practice", "Communication clarity"],
        "suggested_next_action": f"Start a focused {weakness} practice session.",
    }


@router.get("/latest-reports")
async def latest_reports(limit: int = 5, current_user: dict = Depends(get_current_user)):
    await hydrate_dashboard_state()
    return store.user_reports(current_user["id"])[:limit]


@router.get("/roadmap-progress")
async def roadmap_progress(current_user: dict = Depends(get_current_user)):
    await hydrate_dashboard_state()
    roadmap = store.active_roadmap(current_user["id"])
    if not roadmap:
        return {
            "roadmap_title": None,
            "total_topics": 0,
            "completed_topics": 0,
            "percentage": 0,
            "current_phase_title": None,
            "days_remaining": 0,
        }
    tasks = [task for milestone in roadmap["milestones"] for task in milestone["tasks"]]
    completed = [task for task in tasks if task.get("completed")]
    current_phase = next((milestone for milestone in roadmap["milestones"] if not milestone.get("completed")), roadmap["milestones"][-1])
    return {
        "roadmap_title": roadmap["title"],
        "total_topics": len(tasks),
        "completed_topics": len(completed),
        "percentage": roadmap["progress"],
        "current_phase_title": current_phase["title"],
        "days_remaining": 30,
    }
