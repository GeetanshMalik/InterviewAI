from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from services.repository_service import repository_service
from services.store import iso_now, new_id, store, utc_now
from services.workflow import append_workflow_event


RoundName = Literal["technical", "hr"]
RuntimeStatus = Literal["not_started", "in_progress", "awaiting_follow_up", "completed", "terminated"]


def runtime_key(interview_id: str, round_name: RoundName) -> str:
    return f"{interview_id}:{round_name}"


def _questions(interview_id: str, round_name: RoundName) -> list[dict[str, Any]]:
    if round_name == "technical":
        return store.technical_questions.get(interview_id, [])
    return store.hr_questions.get(interview_id, [])


def _answers(interview_id: str, round_name: RoundName) -> list[dict[str, Any]]:
    if round_name == "technical":
        return store.technical_answers.get(interview_id, [])
    return store.hr_answers.get(interview_id, [])


def _question_text(question: dict[str, Any]) -> str:
    return str(question.get("question_text") or question.get("question") or "").strip()


def _difficulty_rank(value: Any) -> int:
    level = str(value or "medium").lower()
    return {"easy": 1, "medium": 2, "hard": 3}.get(level, 2)


def answer_mode_for(round_name: RoundName, question: dict[str, Any], index: int) -> str:
    explicit = str(question.get("answer_mode") or "").lower()
    if explicit in {"spoken", "code"}:
        return explicit
    return "code" if round_name == "technical" and index >= 3 else "spoken"


def timer_seconds_for(round_name: RoundName, question: dict[str, Any], index: int, pressure_level: str = "normal") -> int:
    explicit = question.get("timer_seconds")
    if isinstance(explicit, int | float) and explicit > 0:
        base = int(explicit)
    elif answer_mode_for(round_name, question, index) == "code":
        base = 10 * 60
    else:
        rank = _difficulty_rank(question.get("difficulty"))
        base = {1: 3 * 60, 2: 4 * 60, 3: 5 * 60}.get(rank, 4 * 60)

    if answer_mode_for(round_name, question, index) == "code":
        return base
    if pressure_level == "reduced":
        return min(base + 45, 6 * 60)
    if pressure_level == "elevated":
        return max(base - 30, 2 * 60)
    return base


def _runtime_event(event_type: str, message: str, question_id: str | None = None, metadata: dict[str, Any] | None = None) -> dict:
    return {
        "id": new_id(),
        "timestamp": iso_now(),
        "type": event_type,
        "message": message,
        "questionId": question_id,
        "metadata": metadata or {},
    }


def _new_runtime(interview: dict, round_name: RoundName) -> dict[str, Any]:
    questions = _questions(interview["id"], round_name)
    return {
        "id": new_id(),
        "interviewId": interview["id"],
        "userId": interview["userId"],
        "round": round_name,
        "status": "not_started",
        "currentIndex": None,
        "currentQuestionId": None,
        "questionOrder": [question["id"] for question in questions],
        "answeredQuestionIds": [],
        "skippedQuestionIds": [],
        "followUpByQuestion": {},
        "followUpUsedQuestionIds": [],
        "events": [],
        "adaptationSignals": {
            "pressureLevel": "normal",
            "strongAnswers": 0,
            "weakAnswers": 0,
            "unclearAnswers": 0,
            "passCount": 0,
            "timerExpiredCount": 0,
            "difficultyTrend": "steady",
        },
        "timer": {
            "startedAt": None,
            "timerSeconds": 0,
            "expiresAt": None,
        },
        "startedAt": None,
        "completedAt": None,
        "updatedAt": iso_now(),
    }


def ensure_round_runtime(interview: dict, round_name: RoundName, *, commit: bool = True) -> dict[str, Any]:
    key = runtime_key(interview["id"], round_name)
    runtime = store.round_runtimes.get(key)
    if not runtime:
        runtime = _new_runtime(interview, round_name)
        repository_service.upsert_round_runtime(runtime, commit=commit)
        return runtime

    questions = _questions(interview["id"], round_name)
    runtime.setdefault("questionOrder", [question["id"] for question in questions])
    runtime.setdefault("answeredQuestionIds", [])
    runtime.setdefault("skippedQuestionIds", [])
    runtime.setdefault("followUpByQuestion", {})
    runtime.setdefault("followUpUsedQuestionIds", [])
    runtime.setdefault("events", [])
    runtime.setdefault("adaptationSignals", {})
    runtime.setdefault("timer", {"startedAt": None, "timerSeconds": 0, "expiresAt": None})
    runtime["adaptationSignals"].setdefault("pressureLevel", "normal")
    runtime["adaptationSignals"].setdefault("strongAnswers", 0)
    runtime["adaptationSignals"].setdefault("weakAnswers", 0)
    runtime["adaptationSignals"].setdefault("unclearAnswers", 0)
    runtime["adaptationSignals"].setdefault("passCount", 0)
    runtime["adaptationSignals"].setdefault("timerExpiredCount", 0)
    runtime["adaptationSignals"].setdefault("difficultyTrend", "steady")
    return runtime


def reset_round_runtime(interview_id: str, round_name: RoundName) -> None:
    repository_service.delete_round_runtime(interview_id, round_name)


def _question_by_id(interview_id: str, round_name: RoundName, question_id: str | None) -> tuple[int, dict[str, Any] | None]:
    if not question_id:
        return -1, None
    for index, question in enumerate(_questions(interview_id, round_name)):
        if question.get("id") == question_id:
            return index, question
    return -1, None


def _started_timer(question: dict[str, Any], round_name: RoundName, index: int, pressure_level: str) -> dict[str, Any]:
    seconds = timer_seconds_for(round_name, question, index, pressure_level)
    started = utc_now()
    return {
        "startedAt": started.isoformat(),
        "timerSeconds": seconds,
        "expiresAt": (started + timedelta(seconds=seconds)).isoformat(),
    }


def _public_question(question: dict[str, Any] | None, round_name: RoundName, index: int) -> dict[str, Any] | None:
    if not question:
        return None
    return {
        **question,
        "question_text": _question_text(question),
        "answer_mode": answer_mode_for(round_name, question, index),
        "timer_seconds": timer_seconds_for(round_name, question, index),
    }


def _allowed_actions(runtime: dict[str, Any], question: dict[str, Any] | None, round_name: RoundName) -> list[str]:
    if runtime.get("status") in {"completed", "terminated"}:
        return ["restart_round"]
    if runtime.get("status") == "not_started":
        return ["start_round"]
    if not question:
        return ["complete_round"]
    actions = ["submit_answer", "pass", "repeat", "paraphrase", "end_round"]
    index, _ = _question_by_id(runtime["interviewId"], round_name, runtime.get("currentQuestionId"))
    if answer_mode_for(round_name, question, index) == "code":
        actions.append("open_code_editor")
    return actions


def build_round_runtime_state(interview: dict, round_name: RoundName) -> dict[str, Any]:
    runtime = ensure_round_runtime(interview, round_name, commit=False)
    index, question = _question_by_id(interview["id"], round_name, runtime.get("currentQuestionId"))
    answered = set(runtime.get("answeredQuestionIds", []))
    all_question_ids = [question["id"] for question in _questions(interview["id"], round_name)]
    pending = [question_id for question_id in all_question_ids if question_id not in answered]
    return {
        "runtime": {
            "id": runtime["id"],
            "interviewId": runtime["interviewId"],
            "round": runtime["round"],
            "status": runtime["status"],
            "currentIndex": runtime.get("currentIndex"),
            "currentQuestionId": runtime.get("currentQuestionId"),
            "answeredQuestionIds": runtime.get("answeredQuestionIds", []),
            "skippedQuestionIds": runtime.get("skippedQuestionIds", []),
            "pendingQuestionIds": pending,
            "questionOrder": runtime.get("questionOrder", []),
            "adaptationSignals": runtime.get("adaptationSignals", {}),
            "timer": runtime.get("timer", {}),
            "startedAt": runtime.get("startedAt"),
            "completedAt": runtime.get("completedAt"),
            "updatedAt": runtime.get("updatedAt"),
        },
        "currentQuestion": _public_question(question, round_name, index),
        "followUpPrompt": runtime.get("followUpByQuestion", {}).get(runtime.get("currentQuestionId")),
        "allowedActions": _allowed_actions(runtime, question, round_name),
        "events": runtime.get("events", [])[-50:],
    }


def start_round_runtime(interview: dict, round_name: RoundName, *, commit: bool = True) -> dict[str, Any]:
    runtime = ensure_round_runtime(interview, round_name, commit=False)
    questions = _questions(interview["id"], round_name)
    if not questions:
        raise ValueError(f"No {round_name} questions are available.")

    answered = set(answer.get("questionId") for answer in _answers(interview["id"], round_name))
    runtime["answeredQuestionIds"] = [question_id for question_id in runtime.get("answeredQuestionIds", []) if question_id in answered]
    first_index = next((index for index, question in enumerate(questions) if question["id"] not in answered), 0)
    first_question = questions[first_index]
    runtime["status"] = "in_progress"
    runtime["currentIndex"] = first_index
    runtime["currentQuestionId"] = first_question["id"]
    runtime["timer"] = _started_timer(first_question, round_name, first_index, runtime["adaptationSignals"]["pressureLevel"])
    runtime["startedAt"] = runtime.get("startedAt") or iso_now()
    runtime["updatedAt"] = iso_now()
    runtime["events"].append(
        _runtime_event(
            "round_started",
            f"{round_name.title()} round runtime started.",
            first_question["id"],
            {"answer_mode": answer_mode_for(round_name, first_question, first_index)},
        )
    )
    append_workflow_event(
        interview,
        "info",
        f"{round_name.title()} runtime started with backend-controlled question flow.",
        round_name,
        {"runtime_id": runtime["id"], "current_question_id": first_question["id"]},
        agent=f"{round_name.title()} Interview Agent",
        commit=False,
    )
    repository_service.upsert_round_runtime(runtime, commit=commit)
    return build_round_runtime_state(interview, round_name)


def record_round_command(
    interview: dict,
    round_name: RoundName,
    command: str,
    question_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    runtime = ensure_round_runtime(interview, round_name, commit=False)
    target_question_id = question_id or runtime.get("currentQuestionId")
    runtime["events"].append(
        _runtime_event(
            "command",
            f"Candidate command recorded: {command}.",
            target_question_id,
            {"command": command, **(metadata or {})},
        )
    )
    runtime["updatedAt"] = iso_now()
    repository_service.upsert_round_runtime(runtime, commit=commit)
    return build_round_runtime_state(interview, round_name)


def _should_follow_up(answer: dict[str, Any]) -> bool:
    evaluator_decision = answer.get("evaluatorRuntimeDecision") or {}
    if "should_follow_up" in evaluator_decision:
        return bool(evaluator_decision.get("should_follow_up"))
    score = float(answer.get("score") or 0)
    metrics = answer.get("speechMetrics") or {}
    label = str(metrics.get("confidenceLabel") or "").lower()
    long_pauses = int(metrics.get("longPauseCount") or 0)
    unclear = int(metrics.get("unclearCount") or 0)
    answer_source = str(answer.get("answerSource") or "")
    if answer_source in {"pass", "dont_know", "time_expired", "end_call"}:
        return False
    return 45 <= score < 75 and (label in {"hesitant", "unclear"} or long_pauses > 0 or unclear > 0)


def _follow_up_prompt(question: dict[str, Any], answer: dict[str, Any]) -> str:
    evaluator_decision = answer.get("evaluatorRuntimeDecision") or {}
    if evaluator_decision.get("follow_up_prompt"):
        return str(evaluator_decision["follow_up_prompt"])
    if answer.get("answerMode") == "code":
        return "Before we move on, explain the complexity, edge cases, and one test you would add for this code."
    return (
        "Your answer has a useful direction, but I need more clarity. Please give one concrete example, "
        "state the tradeoff, and explain the result in two or three sentences."
    )


def _update_adaptation_signals(runtime: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    signals = runtime["adaptationSignals"]
    score = float(answer.get("score") or 0)
    metrics = answer.get("speechMetrics") or {}
    answer_source = str(answer.get("answerSource") or "")
    if score >= 80:
        signals["strongAnswers"] = int(signals.get("strongAnswers") or 0) + 1
        signals["difficultyTrend"] = "increase"
        signals["pressureLevel"] = "elevated"
    elif score < 45 or answer_source in {"pass", "dont_know"}:
        signals["weakAnswers"] = int(signals.get("weakAnswers") or 0) + 1
        signals["difficultyTrend"] = "decrease"
        signals["pressureLevel"] = "reduced"
    else:
        signals["difficultyTrend"] = "steady"
    if answer_source in {"pass", "dont_know"}:
        signals["passCount"] = int(signals.get("passCount") or 0) + 1
    if answer.get("timerExpired"):
        signals["timerExpiredCount"] = int(signals.get("timerExpiredCount") or 0) + 1
        signals["pressureLevel"] = "reduced"
    if str(metrics.get("confidenceLabel") or "") in {"hesitant", "unclear"}:
        signals["unclearAnswers"] = int(signals.get("unclearAnswers") or 0) + 1
    return signals


def _select_next_question(
    runtime: dict[str, Any],
    round_name: RoundName,
    questions: list[dict[str, Any]],
    answered_ids: set[str],
    previous_answer: dict[str, Any],
) -> tuple[int, dict[str, Any] | None, str]:
    remaining = [(index, question) for index, question in enumerate(questions) if question["id"] not in answered_ids]
    if not remaining:
        return -1, None, "complete"

    previous_mode = str(previous_answer.get("answerMode") or "spoken")
    technical_spoken_remaining = [
        item for item in remaining if answer_mode_for(round_name, item[1], item[0]) == "spoken"
    ]
    technical_code_remaining = [
        item for item in remaining if answer_mode_for(round_name, item[1], item[0]) == "code"
    ]
    score = float(previous_answer.get("score") or 0)
    answer_source = str(previous_answer.get("answerSource") or "")
    timer_expired = bool(previous_answer.get("timerExpired"))

    if round_name == "technical" and previous_mode == "spoken" and technical_spoken_remaining:
        candidates = technical_spoken_remaining
    elif round_name == "technical" and previous_mode == "spoken" and technical_code_remaining:
        candidates = technical_code_remaining
    else:
        candidates = remaining

    if answer_source in {"pass", "dont_know"} or timer_expired or score < 45:
        return min(candidates, key=lambda item: (_difficulty_rank(item[1].get("difficulty")), item[0])) + ("weak_or_skipped",)
    if score >= 80:
        return max(candidates, key=lambda item: (_difficulty_rank(item[1].get("difficulty")), -item[0])) + ("strong_answer",)
    next_item = min(candidates, key=lambda item: item[0])
    return next_item[0], next_item[1], "sequential"


def advance_runtime_after_answer(interview: dict, round_name: RoundName, answer: dict[str, Any]) -> dict[str, Any]:
    runtime = ensure_round_runtime(interview, round_name, commit=False)
    questions = _questions(interview["id"], round_name)
    question_id = answer.get("questionId")
    index, question = _question_by_id(interview["id"], round_name, question_id)
    answered_ids = set(runtime.get("answeredQuestionIds", []))
    answered_ids.add(str(question_id))
    runtime["answeredQuestionIds"] = [question["id"] for question in questions if question["id"] in answered_ids]

    source = str(answer.get("answerSource") or "")
    if source in {"pass", "dont_know"} and question_id not in runtime.get("skippedQuestionIds", []):
        runtime.setdefault("skippedQuestionIds", []).append(question_id)

    signals = _update_adaptation_signals(runtime, answer)
    if (
        question
        and _should_follow_up(answer)
        and question_id not in runtime.get("followUpUsedQuestionIds", [])
        and runtime.get("status") != "awaiting_follow_up"
    ):
        prompt = _follow_up_prompt(question, answer)
        runtime.setdefault("followUpByQuestion", {})[question_id] = prompt
        runtime.setdefault("followUpUsedQuestionIds", []).append(question_id)
        runtime["status"] = "awaiting_follow_up"
        runtime["timer"] = _started_timer(question, round_name, index, "reduced")
        runtime["events"].append(
            _runtime_event(
                "adaptive_follow_up",
                "Backend selected a clarifying follow-up before moving on.",
                question_id,
                {"reason": "promising_but_unclear", "prompt": prompt},
            )
        )
        repository_service.upsert_round_runtime(runtime, commit=False)
        return build_round_runtime_state(interview, round_name)

    next_index, next_question, reason = _select_next_question(runtime, round_name, questions, answered_ids, answer)
    if not next_question:
        runtime["status"] = "completed"
        runtime["currentIndex"] = None
        runtime["currentQuestionId"] = None
        runtime["timer"] = {"startedAt": None, "timerSeconds": 0, "expiresAt": None}
        runtime["completedAt"] = iso_now()
        runtime["events"].append(
            _runtime_event(
                "round_completed",
                f"{round_name.title()} round completed by backend runtime.",
                question_id,
                {"answered": len(runtime["answeredQuestionIds"])},
            )
        )
        append_workflow_event(
            interview,
            "success",
            f"{round_name.title()} round runtime completed.",
            round_name,
            {"answered": len(runtime["answeredQuestionIds"]), "signals": signals},
            agent=f"{round_name.title()} Interview Agent",
            commit=False,
        )
    else:
        runtime["status"] = "in_progress"
        runtime["currentIndex"] = next_index
        runtime["currentQuestionId"] = next_question["id"]
        runtime["timer"] = _started_timer(next_question, round_name, next_index, signals.get("pressureLevel", "normal"))
        runtime.setdefault("followUpByQuestion", {}).pop(next_question["id"], None)
        runtime["events"].append(
            _runtime_event(
                "adaptive_next_question",
                "Backend selected the next interview question.",
                next_question["id"],
                {
                    "reason": reason,
                    "answer_mode": answer_mode_for(round_name, next_question, next_index),
                    "pressure_level": signals.get("pressureLevel"),
                    "difficulty_trend": signals.get("difficultyTrend"),
                },
            )
        )
    runtime["updatedAt"] = iso_now()
    repository_service.upsert_round_runtime(runtime, commit=False)
    return build_round_runtime_state(interview, round_name)
