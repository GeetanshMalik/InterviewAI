from __future__ import annotations

import json
import re
from ast import literal_eval
from typing import TYPE_CHECKING, Any, Literal

from config import settings
from services.evaluator import score_text_answer
from services.llm import llm_service
from services.llm_optimization import generic_cache_key, prompt_cache
from services.store import iso_now
from utils.parsers import clean_generated_text, json_from_text

if TYPE_CHECKING:
    from agents.tools.base import ToolResult


RoundName = Literal["technical", "hr"]

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "with",
    "you",
    "your",
}

TECHNICAL_RUBRIC = {
    "relevance": "Directly answers the asked technical question.",
    "conceptualAccuracy": "Uses correct concepts, tradeoffs, and constraints.",
    "problemSolving": "Shows a concrete approach, debugging path, or validation plan.",
    "specificity": "Includes examples, implementation details, metrics, or edge cases.",
    "communication": "Explains clearly and concisely using captured delivery signals.",
}

HR_RUBRIC = {
    "relevance": "Directly answers the behavioral or motivation question.",
    "starStructure": "Covers situation, task, action, and result.",
    "ownership": "Shows personal responsibility without exaggeration.",
    "impact": "Names outcome, learning, or measurable business/team effect.",
    "communication": "Explains clearly and professionally using captured delivery signals.",
}

DSA_RUBRIC = {
    "complexityAnalysis": "Algorithmic cost, data structure choice, and scalability.",
    "codeQuality": "Readability, maintainability, decomposition, and implementation hygiene.",
    "edgeCaseReasoning": "Handling of boundary cases, invalid input, and failed tests.",
}


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-zA-Z_][a-zA-Z0-9_+-]*", str(value or "").lower())


def _clean_text(value: Any, fallback: str = "") -> str:
    return clean_generated_text(value, fallback)


def _json_from_text(text: str) -> dict[str, Any]:
    return json_from_text(text, root_error="Evaluation Agent response must be a JSON object.")


async def _get_cached_evaluation(namespace: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    cached = await prompt_cache.get(generic_cache_key(namespace, payload))
    if not cached:
        return None
    result = dict(cached)
    trace = dict(result.get("internalReasoningTrace") or {})
    trace["cache_hit"] = True
    result["internalReasoningTrace"] = trace
    return result


async def _set_cached_evaluation(namespace: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
    await prompt_cache.set(
        generic_cache_key(namespace, payload),
        result,
        ttl_seconds=int(settings.llm_evaluation_cache_ttl_seconds),
    )


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = low
    return round(max(low, min(high, number)), 2)


def _list_strings(value: Any, fallback: list[str] | None = None, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return (fallback or [])[:limit]
    items = [_clean_text(item) for item in value if _clean_text(item)]
    return (items or fallback or [])[:limit]


def _question_text(question: dict[str, Any]) -> str:
    return str(question.get("question_text") or question.get("question") or "").strip()


def _keywords(question: dict[str, Any]) -> list[str]:
    raw = question.get("keywords") or question.get("expected_keywords") or []
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.split(",")]
    return [str(item).strip() for item in raw if str(item).strip()]


def _keyword_hits(answer: str, keywords: list[str]) -> list[str]:
    haystack = " ".join(_tokens(answer))
    return [keyword for keyword in keywords if keyword.lower() in haystack]


def _question_overlap(answer: str, question_text: str) -> float:
    answer_tokens = set(_tokens(answer)) - STOPWORDS
    question_tokens = set(_tokens(question_text)) - STOPWORDS
    if not question_tokens:
        return 0.0
    return len(answer_tokens & question_tokens) / len(question_tokens)


def _answer_sentences(answer: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", str(answer or ""))
        if sentence.strip()
    ]


def _is_non_answer(answer: str) -> bool:
    normalized = " ".join(_tokens(answer))
    if not normalized:
        return True
    patterns = [
        r"\b(i\s+)?(don t|dont|do not)\s+know(\s+the\s+answer)?\b",
        r"\b(no\s+idea|not\s+sure|i\s+am\s+not\s+sure)\b",
        r"\b(proceed|continue|move|go)\s+(to\s+)?(the\s+)?next\s+(question|one)\b",
        r"\b(skip|pass)\s+(this|it|question|one)?\b",
        r"\b(can t|cant|cannot|could not|unable|not able)\s+(answer|solve|attempt|figure)\b",
    ]
    return any(re.search(pattern, normalized) for pattern in patterns)


def _realtime_signals(speech_metrics: dict[str, Any] | None) -> list[dict[str, Any]]:
    metrics = speech_metrics or {}
    signals = metrics.get("realtimeSignals") or metrics.get("realtime_signals") or []
    return [item for item in signals if isinstance(item, dict)]


def _signal_types(speech_metrics: dict[str, Any] | None) -> set[str]:
    return {str(item.get("type") or "") for item in _realtime_signals(speech_metrics)}


def _evidence_snippets(answer: str, question: dict[str, Any], keywords: list[str], limit: int = 3) -> list[str]:
    terms = {token for keyword in keywords for token in _tokens(keyword)}
    terms |= (set(_tokens(_question_text(question))) - STOPWORDS)
    snippets: list[str] = []
    for sentence in _answer_sentences(answer):
        if terms and set(_tokens(sentence)) & terms:
            snippets.append(sentence[:260])
        if len(snippets) >= limit:
            break
    if not snippets and answer.strip():
        snippets = [sentence[:260] for sentence in _answer_sentences(answer)[:limit]]
    return snippets


def _specificity_score(answer: str, round_name: RoundName) -> float:
    tokens = set(_tokens(answer))
    word_count = len(_tokens(answer))
    score = min(word_count / 100 * 35, 35)
    if any(char.isdigit() for char in answer):
        score += 10
    if tokens & {"built", "designed", "implemented", "debugged", "led", "owned", "improved", "reduced", "increased"}:
        score += 15
    if tokens & {"because", "therefore", "tradeoff", "constraint", "edge", "result", "impact", "learned"}:
        score += 15
    if round_name == "hr" and tokens & {"situation", "task", "action", "result", "learned", "feedback"}:
        score += 15
    if len(_answer_sentences(answer)) >= 3:
        score += 10
    return _clamp(score)


def _domain_signal_score(answer: str, round_name: RoundName) -> float:
    tokens = set(_tokens(answer))
    if not tokens:
        return 0.0
    if round_name == "technical":
        signals = {
            "api",
            "architecture",
            "cache",
            "complexity",
            "database",
            "debug",
            "edge",
            "failure",
            "index",
            "latency",
            "monitoring",
            "queue",
            "scale",
            "schema",
            "security",
            "test",
            "tradeoff",
            "validate",
        }
    else:
        signals = {
            "communicated",
            "conflict",
            "deadline",
            "feedback",
            "impact",
            "learned",
            "owned",
            "prioritized",
            "stakeholder",
            "team",
            "unblocked",
            "worked",
        }
    return _clamp(len(tokens & signals) / max(len(signals), 1) * 100)


def _confidence_score(
    answer: str,
    speech_metrics: dict[str, Any] | None,
    transcript_confidence: float | None,
    answer_source: str | None,
) -> float:
    metrics = speech_metrics or {}
    if transcript_confidence is not None:
        score = float(transcript_confidence) * 100
    elif metrics.get("averageConfidence") is not None:
        score = float(metrics.get("averageConfidence") or 0) * 100
    else:
        score = 72 if answer.strip() else 20

    label = str(metrics.get("confidenceLabel") or "").lower()
    if label == "strong":
        score += 8
    elif label == "hesitant":
        score -= 12
    elif label == "unclear":
        score -= 25
    if _is_non_answer(answer):
        score = min(score, 20)
    elif re.search(r"\b(maybe|i guess|not sure|i don't know|dont know)\b", answer.lower()):
        score -= 20
    if str(answer_source or "") in {"pass", "dont_know", "time_expired"}:
        score = min(score, 25)
    return _clamp(score)


def _communication_score(
    answer: str,
    speech_metrics: dict[str, Any] | None,
    transcript_confidence: float | None,
    answer_source: str | None,
    repeat_count: int = 0,
    paraphrase_count: int = 0,
) -> float:
    metrics = speech_metrics or {}
    confidence = _confidence_score(answer, metrics, transcript_confidence, answer_source)
    score = confidence * 0.65 + 25
    wpm = float(metrics.get("wordsPerMinute") or 0)
    if 80 <= wpm <= 180:
        score += 8
    elif wpm and (wpm < 55 or wpm > 230):
        score -= 10
    score -= int(metrics.get("longPauseCount") or 0) * 5
    score -= int(metrics.get("unclearCount") or 0) * 8
    score -= max(0, repeat_count) * 2
    score -= max(0, paraphrase_count) * 1.5
    if not answer.strip():
        score = min(score, 20)
    return _clamp(score)


def _score_cap(
    answer: str,
    answer_source: str | None,
    safety_flags: list[str],
    speech_metrics: dict[str, Any] | None = None,
) -> float:
    word_count = len(_tokens(answer))
    signals = _signal_types(speech_metrics)
    if safety_flags:
        return 0.0
    if "unsafe" in signals:
        return 0.0
    if _is_non_answer(answer) or "non_answer" in signals:
        return 0.0
    if "off_topic" in signals:
        return 20.0
    if "low_relevance" in signals:
        return 45.0
    if word_count == 0:
        return 0.0
    if str(answer_source or "") in {"pass", "dont_know"}:
        return 0.0
    if str(answer_source or "") == "time_expired" and word_count < 15:
        return 35.0
    if word_count < 8:
        return 25.0
    return 100.0


def _code_structure_score(code: str) -> float:
    lines = [line.strip() for line in str(code or "").splitlines() if line.strip()]
    if not lines:
        return 0.0
    score = min(len(lines) * 8, 32)
    if re.search(r"\b(function|def|class|const|let|var|public|private|func|fn)\b", code):
        score += 18
    if re.search(r"\b(if|else|switch|case|try|catch|guard)\b", code):
        score += 14
    if re.search(r"\b(for|while|map|filter|reduce|forEach)\b", code):
        score += 14
    if re.search(r"\b(return|print|console\.log|raise|throw)\b", code):
        score += 12
    pairs = [("(", ")"), ("[", "]"), ("{", "}")]
    if all(code.count(open_char) == code.count(close_char) for open_char, close_char in pairs):
        score += 10
    return _clamp(score)


def _deterministic_technical_code_evaluation(
    answer: str,
    question: dict[str, Any],
    *,
    answer_source: str | None = None,
    timer_expired: bool = False,
    proctor_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    question_text = _question_text(question)
    keywords = _keywords(question)
    safety_flags = score_text_answer(answer, keywords, question_text, round_name="technical").get("safety_flags", [])
    answer_source = str(answer_source or "")
    if safety_flags:
        score = 0.0
    elif answer_source in {"pass", "dont_know"} or not answer.strip() or _is_non_answer(answer):
        score = 0.0
    else:
        matched_keywords = _keyword_hits(answer, keywords)
        keyword_ratio = len(matched_keywords) / max(len(keywords), 1)
        overlap = _question_overlap(answer, question_text)
        structure = _code_structure_score(answer)
        has_edge_handling = bool(re.search(r"\b(if|else|try|catch|null|none|undefined|empty|length|len|error|throw|raise)\b", answer.lower()))
        has_expected_output_signal = bool(re.search(r"\b(return|print|console\.log|output|result|expected|assert)\b", answer.lower()))
        has_complexity_signal = bool(re.search(r"\b(o\(|complexity|time|space|edge|test|case)\b", answer.lower()))
        problem_fit = _clamp(25 + keyword_ratio * 45 + overlap * 35)
        syntax_and_structure = structure
        correctness_signal = _clamp(
            20
            + problem_fit * 0.35
            + (20 if has_expected_output_signal else 0)
            + (15 if has_edge_handling else 0)
            + (10 if has_complexity_signal else 0)
        )
        code_quality = _clamp(
            25
            + syntax_and_structure * 0.45
            + (15 if len([line for line in answer.splitlines() if line.strip()]) >= 4 else 0)
            - (20 if re.search(r"\b(todo|fixme|pass|null;\s*$|return\s+null)\b", answer.lower()) else 0)
        )
        score = _clamp(problem_fit * 0.25 + syntax_and_structure * 0.25 + correctness_signal * 0.30 + code_quality * 0.20)
        if timer_expired and score < 70:
            score = min(score, 60.0)

    matched_keywords = _keyword_hits(answer, keywords)
    proctor_events = proctor_events or []
    critical_proctor_events = [event for event in proctor_events if event.get("severity") == "critical"]
    if critical_proctor_events:
        score = min(score, 60.0)

    if not answer.strip() or answer_source in {"pass", "dont_know"}:
        feedback = "No code was submitted, so this code question is scored 0."
    elif score >= 80:
        feedback = "Strong code answer: it is structured, relevant to the prompt, and shows usable implementation logic."
    elif score >= 55:
        feedback = "Good code direction. Improve edge-case handling, expected output alignment, and code organization."
    else:
        feedback = "This code answer needs clearer syntax, stronger problem fit, and more complete implementation logic."

    evidence = _evidence_snippets(answer, question, keywords) if answer.strip() else ["No code was submitted."]
    return {
        "score": score,
        "feedback": feedback,
        "matched_keywords": matched_keywords,
        "safety_flags": list(safety_flags),
        "rubric": {
            "problemFit": _clamp(25 + (len(matched_keywords) / max(len(keywords), 1)) * 45 + _question_overlap(answer, question_text) * 35),
            "syntaxAndStructure": _code_structure_score(answer),
            "correctnessSignal": _clamp(score),
            "codeQuality": _clamp(score),
            "speechDelivery": 0,
        },
        "evidence": evidence,
        "improvementSuggestions": [
            "Submit a complete code block or implementation sketch that directly answers the prompt.",
            "Include edge-case handling, expected output behavior, and clear return/output syntax.",
        ],
        "confidenceScore": 100.0 if answer.strip() else 0.0,
        "communicationScore": _clamp(score),
        "biasGuardrails": [
            "Scored written code only; speech confidence, WPM, accent, and voice delivery were not used.",
            "Protected traits and personal background were not used as scoring criteria.",
        ],
        "evaluationProvider": "deterministic-fallback",
        "evaluationModel": "local-technical-code-rubric-v1",
        "evaluationAgent": "Evaluation Agent",
        "evaluatedAt": iso_now(),
        "internalReasoningTrace": {
            "version": "technical-code-rubric-v1",
            "source": "deterministic",
            "answer_mode": "code",
            "speech_metrics_used": False,
            "code_line_count": len([line for line in answer.splitlines() if line.strip()]),
            "matched_keyword_count": len(matched_keywords),
            "critical_proctor_events": len(critical_proctor_events),
        },
    }


def _deterministic_round_evaluation(
    round_name: RoundName,
    answer: str,
    question: dict[str, Any],
    *,
    transcript_confidence: float | None = None,
    answer_mode: str | None = None,
    speech_metrics: dict[str, Any] | None = None,
    proctor_events: list[dict[str, Any]] | None = None,
    repeat_count: int = 0,
    paraphrase_count: int = 0,
    answer_source: str | None = None,
    timer_expired: bool = False,
) -> dict[str, Any]:
    if round_name == "technical" and str(answer_mode or question.get("answer_mode") or "").lower() == "code":
        return _deterministic_technical_code_evaluation(
            answer,
            question,
            answer_source=answer_source,
            timer_expired=timer_expired,
            proctor_events=proctor_events,
        )

    question_text = _question_text(question)
    keywords = _keywords(question)
    base = score_text_answer(answer, keywords, question_text, round_name=round_name)
    safety_flags = list(base.get("safety_flags", []))
    cap = _score_cap(answer, answer_source, safety_flags, speech_metrics)
    matched_keywords = _keyword_hits(answer, keywords)
    keyword_ratio = len(matched_keywords) / max(len(keywords), 1)
    overlap = _question_overlap(answer, question_text)
    specificity = _specificity_score(answer, round_name)
    domain_signal = _domain_signal_score(answer, round_name)
    confidence = _confidence_score(answer, speech_metrics, transcript_confidence, answer_source)
    communication = _communication_score(
        answer,
        speech_metrics,
        transcript_confidence,
        answer_source,
        repeat_count,
        paraphrase_count,
    )

    relevance = _clamp(max(25 + keyword_ratio * 45 + overlap * 35, 20 + domain_signal * 0.35 + overlap * 45))
    if round_name == "technical":
        conceptual = _clamp(20 + keyword_ratio * 35 + specificity * 0.25 + domain_signal * 0.35 + (15 if "tradeoff" in answer.lower() else 0))
        problem_solving = _clamp(20 + specificity * 0.35 + domain_signal * 0.35 + (18 if re.search(r"\b(test|edge|debug|validate|complexity)\b", answer.lower()) else 0))
        rubric = {
            "relevance": relevance,
            "conceptualAccuracy": conceptual,
            "problemSolving": problem_solving,
            "specificity": specificity,
            "communication": communication,
        }
        weighted = (
            relevance * 0.20
            + conceptual * 0.25
            + problem_solving * 0.20
            + specificity * 0.15
            + communication * 0.20
        )
    else:
        tokens = set(_tokens(answer))
        context_tokens = {"situation", "context", "project", "team", "when", "during", "while"}
        task_tokens = {"task", "goal", "needed", "deadline", "expected", "requirement", "challenge"}
        action_tokens = {"action", "did", "built", "led", "handled", "communicated", "prioritized", "decided", "unblocked", "fixed"}
        result_tokens = {"result", "impact", "outcome", "learned", "improved", "reduced", "delivered", "resolved", "so"}
        star = _clamp(
            (25 if tokens & context_tokens else 0)
            + (25 if tokens & task_tokens else 0)
            + (25 if tokens & action_tokens else 0)
            + (25 if tokens & result_tokens else 0)
        )
        ownership = _clamp(25 + specificity * 0.35 + domain_signal * 0.25 + (25 if tokens & {"i", "my", "owned", "led"} else 0))
        impact = _clamp(20 + specificity * 0.35 + domain_signal * 0.25 + (25 if any(char.isdigit() for char in answer) else 0))
        rubric = {
            "relevance": relevance,
            "starStructure": star,
            "ownership": ownership,
            "impact": impact,
            "communication": communication,
        }
        weighted = relevance * 0.20 + star * 0.20 + ownership * 0.20 + impact * 0.15 + communication * 0.25

    score = _clamp(min(weighted * 0.75 + float(base.get("score") or 0) * 0.25, cap))
    proctor_events = proctor_events or []
    critical_proctor_events = [event for event in proctor_events if event.get("severity") == "critical"]
    if critical_proctor_events:
        score = min(score, 60.0)

    non_answer = _is_non_answer(answer) or "non_answer" in _signal_types(speech_metrics)
    if non_answer:
        feedback = "No substantive answer was provided, so this question is scored 0. Try to answer the question directly before asking to move on."
    elif not answer.strip():
        feedback = "No substantive answer was captured, so this question is scored 0. Answer with a direct explanation and one concrete example next time."
    elif safety_flags:
        feedback = base["feedback"]
    elif score >= 80:
        feedback = "Strong answer: it gives relevant evidence, explains reasoning clearly, and supports the interviewer signal."
    elif score >= 55:
        feedback = "Good start. Add sharper evidence, tradeoffs, concrete outcomes, and a clearer closing statement."
    else:
        feedback = f"This {round_name} answer needs more job-relevant evidence, structure, and specific reasoning."

    evidence = _evidence_snippets(answer, question, keywords)
    if non_answer:
        evidence = ["Candidate indicated they did not know the answer or asked to move to the next question."]
    elif not evidence and not answer.strip():
        evidence = ["No substantive answer was captured."]

    return {
        "score": score,
        "feedback": feedback,
        "matched_keywords": matched_keywords,
        "safety_flags": safety_flags,
        "rubric": rubric,
        "evidence": evidence,
        "improvementSuggestions": [
            "Answer the exact question first, then add one concrete example.",
            "Name the tradeoff, result, or lesson learned before moving on.",
        ],
        "confidenceScore": confidence,
        "communicationScore": communication,
        "biasGuardrails": [
            "Scored only job-relevant answer content and captured delivery signals.",
            "Protected traits and personal background were not used as scoring criteria.",
        ],
        "evaluationProvider": "deterministic-fallback",
        "evaluationModel": "local-rubric-v1",
        "evaluationAgent": "Evaluation Agent",
        "evaluatedAt": iso_now(),
        "internalReasoningTrace": {
            "version": "round-rubric-v1",
            "source": "deterministic",
            "word_count": len(_tokens(answer)),
            "keyword_ratio": round(keyword_ratio, 3),
            "question_overlap": round(overlap, 3),
            "domain_signal": round(domain_signal, 3),
            "score_cap": cap,
            "critical_proctor_events": len(critical_proctor_events),
            "realtime_signal_types": sorted(_signal_types(speech_metrics)),
            "non_answer_detected": non_answer,
        },
    }


def _normalize_round_evaluation(
    payload: dict[str, Any],
    fallback: dict[str, Any],
    *,
    provider: str,
    model: str,
) -> dict[str, Any]:
    fallback_rubric = fallback["rubric"]
    raw_rubric = payload.get("rubric") if isinstance(payload.get("rubric"), dict) else {}
    rubric = {
        key: _clamp(raw_rubric.get(key, fallback_rubric.get(key, 0)))
        for key in fallback_rubric
    }
    score = _clamp(payload.get("score", fallback["score"]))
    score = min(score, float(fallback.get("internalReasoningTrace", {}).get("score_cap", 100)))
    if fallback.get("safety_flags"):
        score = 0.0
    return {
        **fallback,
        "score": score,
        "feedback": _clean_text(payload.get("feedback"), fallback["feedback"]),
        "rubric": rubric,
        "evidence": _list_strings(payload.get("evidence"), fallback["evidence"], limit=5),
        "improvementSuggestions": _list_strings(
            payload.get("improvementSuggestions") or payload.get("improvement_suggestions"),
            fallback["improvementSuggestions"],
            limit=5,
        ),
        "confidenceScore": _clamp(payload.get("confidenceScore", fallback["confidenceScore"])),
        "communicationScore": _clamp(payload.get("communicationScore", fallback["communicationScore"])),
        "safety_flags": _list_strings(payload.get("safetyFlags") or payload.get("safety_flags"), fallback["safety_flags"]),
        "biasGuardrails": _list_strings(payload.get("biasGuardrails"), fallback["biasGuardrails"], limit=5),
        "evaluationProvider": provider,
        "evaluationModel": model,
        "internalReasoningTrace": {
            **fallback.get("internalReasoningTrace", {}),
            "source": "llm",
            "provider": provider,
            "model": model,
            "llm_audit_summary": _clean_text(
                payload.get("internalReasoningTrace") or payload.get("reasoningTrace"),
                "LLM rubric result normalized with deterministic safety caps.",
            )[:900],
        },
    }


async def evaluate_round_answer(
    round_name: RoundName,
    answer: str,
    question: dict[str, Any],
    *,
    interview: dict[str, Any] | None = None,
    transcript_confidence: float | None = None,
    answer_mode: str | None = None,
    time_taken_seconds: int | None = None,
    timer_expired: bool = False,
    speech_metrics: dict[str, Any] | None = None,
    proctor_events: list[dict[str, Any]] | None = None,
    repeat_count: int = 0,
    paraphrase_count: int = 0,
    answer_source: str | None = None,
) -> dict[str, Any]:
    fallback = _deterministic_round_evaluation(
        round_name,
        answer,
        question,
        transcript_confidence=transcript_confidence,
        answer_mode=answer_mode,
        speech_metrics=speech_metrics,
        proctor_events=proctor_events,
        repeat_count=repeat_count,
        paraphrase_count=paraphrase_count,
        answer_source=answer_source,
        timer_expired=timer_expired,
    )
    signal_types = _signal_types(speech_metrics)
    if (
        (round_name == "technical" and str(answer_mode or question.get("answer_mode") or "").lower() == "code")
        or fallback.get("safety_flags")
        or not answer.strip()
        or _is_non_answer(answer)
        or signal_types & {"non_answer", "unsafe", "off_topic"}
        or str(answer_source or "") in {"pass", "dont_know", "end_call"}
    ):
        return fallback
    if not settings.live_round_llm_evaluation_enabled:
        return fallback

    rubric = TECHNICAL_RUBRIC if round_name == "technical" else HR_RUBRIC
    context = {
        "round": round_name,
        "interview": {
            "target_role": (interview or {}).get("target_role"),
            "difficulty": (interview or {}).get("difficulty"),
            "company_style": (interview or {}).get("company_style"),
            "skills": (interview or {}).get("skills", []),
        },
        "question": {
            "text": _question_text(question),
            "keywords": _keywords(question),
            "difficulty": question.get("difficulty"),
            "answer_mode": answer_mode,
        },
        "answer": answer[:4000],
        "signals": {
            "time_taken_seconds": time_taken_seconds,
            "timer_expired": timer_expired,
            "speech_metrics": speech_metrics or {},
            "proctor_events": proctor_events or [],
            "repeat_count": repeat_count,
            "paraphrase_count": paraphrase_count,
            "answer_source": answer_source,
        },
        "deterministic_guardrail": {
            "score": fallback["score"],
            "score_cap": fallback["internalReasoningTrace"]["score_cap"],
            "safety_flags": fallback["safety_flags"],
        },
        "rubric": rubric,
    }
    cached = await _get_cached_evaluation("evaluation:round", context)
    if cached:
        return cached
    try:
        response = await llm_service.invoke_live(
            [
                {
                    "role": "system",
                    "content": (
                        "You are the InterviewOS Evaluation Agent. Score only job-relevant evidence. "
                        "Do not infer or score protected traits, accent, gender, age, caste, religion, "
                        "health, nationality, or socioeconomic background. Use the deterministic cap "
                        "and safety flags as hard guardrails. Do not reveal hidden chain-of-thought; "
                        "internalReasoningTrace must be a compact audit summary. Return only JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Evaluate this interview answer with the exact JSON shape:\n"
                        "{\n"
                        '  "score": 0,\n'
                        '  "feedback": "candidate-facing paragraph",\n'
                        '  "rubric": {"dimensionName": 0},\n'
                        '  "evidence": ["short evidence quoted or paraphrased from answer"],\n'
                        '  "improvementSuggestions": ["specific next improvement"],\n'
                        '  "confidenceScore": 0,\n'
                        '  "communicationScore": 0,\n'
                        '  "safetyFlags": [],\n'
                        '  "biasGuardrails": ["guardrail applied"],\n'
                        '  "internalReasoningTrace": "brief private audit summary"\n'
                        "}\n\n"
                        f"Evidence JSON:\n{json.dumps(context, ensure_ascii=False)}"
                    ),
                },
            ],
            agent="evaluation",
        )
        result = _normalize_round_evaluation(
            _json_from_text(response.content),
            fallback,
            provider=response.provider,
            model=response.model,
        )
        await _set_cached_evaluation("evaluation:round", context, result)
        return result
    except Exception:
        return fallback


def _nonempty_code_lines(code: str) -> list[str]:
    lines = []
    for line in str(code or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "/*", "*")):
            continue
        lines.append(stripped)
    return lines


def _code_signals(code: str, language: str) -> dict[str, Any]:
    lowered = code.lower()
    lines = _nonempty_code_lines(code)
    loop_count = len(re.findall(r"\b(for|while|forEach|map|filter|reduce)\b", code))
    has_recursion = bool(re.search(r"\bdef\s+(\w+)|function\s+(\w+)|func\s+(\w+)", code)) and "return" in lowered
    has_sort = bool(re.search(r"\b(sort|sorted|Arrays\.sort|Collections\.sort)\b", code))
    has_hash = bool(re.search(r"\b(dict|map|set|hash|object|unordered_map|HashMap|Set)\b", code))
    has_edge_checks = bool(re.search(r"\b(if|guard|return\s+\[\]|return\s+0|None|null|undefined|len|length|empty)\b", code))
    nested_loop_hint = bool(re.search(r"\b(for|while)\b[\s\S]{0,260}\b(for|while)\b", code))
    hardcoded = bool(re.search(r"return\s+(\[[^\]]{0,40}\]|\{[^}]{0,40}\}|[\"'].*[\"']|\d+)\s*;?\s*$", code.strip()))
    return {
        "language": language,
        "line_count": len(lines),
        "loop_count": loop_count,
        "has_recursion": has_recursion,
        "has_sort": has_sort,
        "has_hash_structure": has_hash,
        "has_edge_checks": has_edge_checks,
        "nested_loop_hint": nested_loop_hint,
        "hardcoded_return_hint": hardcoded,
        "uses_eval": "eval(" in lowered,
    }


def _observed_complexity(signals: dict[str, Any]) -> str:
    if signals["nested_loop_hint"]:
        return "O(n^2) or worse from nested iteration"
    if signals["has_sort"]:
        return "O(n log n) from sorting"
    if signals["loop_count"] or signals["has_hash_structure"]:
        return "O(n) typical single-pass/hash-based approach"
    if signals["has_recursion"]:
        return "Recursive complexity depends on branching depth"
    return "O(1) or not enough structure to infer"


def _test_counts(execution_result: dict[str, Any]) -> tuple[int, int]:
    tests = execution_result.get("test_results") or execution_result.get("testResults") or []
    total = len(tests)
    passed = len([item for item in tests if isinstance(item, dict) and item.get("passed")])
    return passed, total


def _deterministic_dsa_reasoning(
    problem: dict[str, Any],
    code: str,
    language: str,
    execution_result: dict[str, Any],
    time_taken_seconds: int | None = None,
    dynamic_tool_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    signals = _code_signals(code, language)
    passed, total = _test_counts(execution_result)
    pass_ratio = passed / total if total else 0
    execution_score = _clamp(execution_result.get("score", 0))

    complexity_score = 55 + pass_ratio * 30
    if signals["has_hash_structure"] or signals["has_sort"] or signals["has_recursion"]:
        complexity_score += 8
    if signals["nested_loop_hint"] and str(problem.get("difficulty", "")).lower() == "hard":
        complexity_score -= 12
    if signals["hardcoded_return_hint"]:
        complexity_score -= 25

    quality_score = 45 + pass_ratio * 25
    if 3 <= signals["line_count"] <= 120:
        quality_score += 10
    if re.search(r"\b(solve|solution|main)\b", code):
        quality_score += 8
    if signals["has_edge_checks"]:
        quality_score += 7
    if signals["uses_eval"]:
        quality_score -= 25
    if signals["hardcoded_return_hint"]:
        quality_score -= 20

    edge_score = 35 + pass_ratio * 40
    if signals["has_edge_checks"]:
        edge_score += 15
    if total >= 4:
        edge_score += 5
    if execution_result.get("status") != "passed":
        edge_score -= 10

    reasoning_score = _clamp(
        _clamp(complexity_score) * 0.35
        + _clamp(quality_score) * 0.30
        + _clamp(edge_score) * 0.25
        + execution_score * 0.10
    )
    dynamic_tool_evidence = dynamic_tool_evidence or {}
    extra_score = dynamic_tool_evidence.get("extraScore")
    if extra_score is not None:
        try:
            reasoning_score = _clamp(reasoning_score * 0.85 + float(extra_score) * 0.15)
        except (TypeError, ValueError):
            pass
    if time_taken_seconds and time_taken_seconds > 45 * 60:
        reasoning_score = max(0, reasoning_score - 5)

    failed_tests = [
        item
        for item in (execution_result.get("test_results") or execution_result.get("testResults") or [])
        if isinstance(item, dict) and not item.get("passed")
    ][:3]

    return {
        "reasoningScore": reasoning_score,
        "complexityAnalysis": {
            "score": _clamp(complexity_score),
            "observedComplexity": _observed_complexity(signals),
            "evidence": [
                f"Detected {signals['loop_count']} loop-style construct(s).",
                "Hash/set/map usage detected." if signals["has_hash_structure"] else "No clear hash-based optimization detected.",
            ],
            "notes": "Static complexity is an estimate; internal execution correctness remains canonical.",
        },
        "codeQuality": {
            "score": _clamp(quality_score),
            "strengths": [
                item
                for item in [
                    "Uses a recognizable solve/solution entry point." if re.search(r"\b(solve|solution|main)\b", code) else "",
                    "Includes boundary checks." if signals["has_edge_checks"] else "",
                ]
                if item
            ],
            "issues": [
                item
                for item in [
                    "Possible hard-coded return detected." if signals["hardcoded_return_hint"] else "",
                    "Avoid eval-style execution in interview submissions." if signals["uses_eval"] else "",
                    "Add clearer input validation or empty-case handling." if not signals["has_edge_checks"] else "",
                ]
                if item
            ],
        },
        "edgeCaseReasoning": {
            "score": _clamp(edge_score),
            "coveredSignals": [
                item
                for item in [
                    "Explicit conditional or empty/null handling." if signals["has_edge_checks"] else "",
                    f"{passed}/{total} generated tests passed." if total else "No generated tests available.",
                ]
                if item
            ],
            "missingSignals": [
                item
                for item in [
                    "Review failed generated cases." if failed_tests else "",
                    "Add empty input, duplicate, and boundary-value checks." if not signals["has_edge_checks"] else "",
                ]
                if item
            ],
        },
        "feedback": (
            "Reasoning looks solid beyond pass/fail; now explain complexity and edge cases verbally."
            if reasoning_score >= 75
            else "Beyond correctness, improve complexity explanation, code hygiene, and edge-case coverage."
        ),
        "evidence": [
            f"Internal execution engine status: {execution_result.get('status')}.",
            f"Generated tests passed: {passed}/{total}.",
            f"Observed complexity: {_observed_complexity(signals)}.",
        ]
        + (
            [f"Dynamic evaluator tool loop ran {dynamic_tool_evidence.get('toolCallCount', 0)} extra code tool call(s)."]
            if dynamic_tool_evidence
            else []
        ),
        "dynamicToolEvidence": dynamic_tool_evidence,
        "evaluationProvider": "deterministic-fallback",
        "evaluationModel": "local-dsa-rubric-v1",
        "evaluationAgent": "Evaluation Agent",
        "evaluatedAt": iso_now(),
        "internalReasoningTrace": {
            "version": "dsa-rubric-v1",
            "source": "deterministic",
            "signals": signals,
            "passed": passed,
            "total": total,
            "dynamic_tool_evidence": dynamic_tool_evidence,
        },
    }


def _normalize_dsa_reasoning(
    payload: dict[str, Any],
    fallback: dict[str, Any],
    *,
    provider: str,
    model: str,
) -> dict[str, Any]:
    result = {**fallback}
    result["reasoningScore"] = _clamp(payload.get("reasoningScore", fallback["reasoningScore"]))
    for section in DSA_RUBRIC:
        raw = payload.get(section) if isinstance(payload.get(section), dict) else {}
        fallback_section = fallback.get(section, {})
        result[section] = {
            **fallback_section,
            **raw,
            "score": _clamp(raw.get("score", fallback_section.get("score", 0))),
        }
    result["feedback"] = _clean_text(payload.get("feedback"), fallback["feedback"])
    result["evidence"] = _list_strings(payload.get("evidence"), fallback["evidence"], limit=6)
    result["evaluationProvider"] = provider
    result["evaluationModel"] = model
    result["internalReasoningTrace"] = {
        **fallback.get("internalReasoningTrace", {}),
        "source": "llm",
        "provider": provider,
        "model": model,
        "llm_audit_summary": _clean_text(
            payload.get("internalReasoningTrace") or payload.get("reasoningTrace"),
            "LLM DSA rubric result normalized with deterministic evidence.",
        )[:900],
    }
    return result


def public_evaluation_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: public_evaluation_payload(item)
            for key, item in value.items()
            if key not in {"internalReasoningTrace", "internalEvaluationTrace"}
        }
    if isinstance(value, list):
        return [public_evaluation_payload(item) for item in value]
    return value


async def evaluate_dsa_submission_reasoning(
    problem: dict[str, Any],
    code: str,
    language: str,
    execution_result: dict[str, Any],
    *,
    time_taken_seconds: int | None = None,
    dynamic_tool_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback = _deterministic_dsa_reasoning(
        problem,
        code,
        language,
        execution_result,
        time_taken_seconds,
        dynamic_tool_evidence,
    )
    passed, total = _test_counts(execution_result)
    if not code.strip() or str(execution_result.get("status") or "").lower() != "passed" or (total > 0 and passed < total):
        return fallback

    context = {
        "problem": {
            "title": problem.get("title"),
            "description": str(problem.get("description", ""))[:2000],
            "difficulty": problem.get("difficulty"),
            "constraints": str(problem.get("constraints", ""))[:1000],
            "test_case_count": len(problem.get("test_cases", [])),
        },
        "submission": {
            "language": language,
            "code_excerpt": code[:5000],
            "time_taken_seconds": time_taken_seconds,
        },
        "execution": {
            "status": execution_result.get("status"),
            "score": execution_result.get("score"),
            "feedback": execution_result.get("feedback"),
            "test_results": (execution_result.get("test_results") or [])[:6],
        },
        "dynamic_tool_evidence": dynamic_tool_evidence or {},
        "deterministic_reasoning": fallback,
        "rubric": DSA_RUBRIC,
    }
    cached = await _get_cached_evaluation("evaluation:dsa_reasoning", context)
    if cached:
        return cached
    try:
        response = await llm_service.invoke_live(
            [
                {
                    "role": "system",
                    "content": (
                        "You are the InterviewOS Evaluation Agent for DSA. Internal execution correctness remains "
                        "canonical; your job is to augment it with complexity, code quality, and "
                        "edge-case reasoning. Do not reward style over correctness. Return only JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Evaluate this DSA submission with the exact JSON shape:\n"
                        "{\n"
                        '  "reasoningScore": 0,\n'
                        '  "complexityAnalysis": {"score": 0, "observedComplexity": "text", "evidence": ["text"], "notes": "text"},\n'
                        '  "codeQuality": {"score": 0, "strengths": ["text"], "issues": ["text"]},\n'
                        '  "edgeCaseReasoning": {"score": 0, "coveredSignals": ["text"], "missingSignals": ["text"]},\n'
                        '  "feedback": "candidate-facing paragraph",\n'
                        '  "evidence": ["specific evidence"],\n'
                        '  "internalReasoningTrace": "brief private audit summary"\n'
                        "}\n\n"
                        f"Evidence JSON:\n{json.dumps(context, ensure_ascii=False)}"
                    ),
                },
            ],
            agent="evaluation",
        )
        result = _normalize_dsa_reasoning(
            _json_from_text(response.content),
            fallback,
            provider=response.provider,
            model=response.model,
        )
        await _set_cached_evaluation("evaluation:dsa_reasoning", context, result)
        return result
    except Exception:
        return fallback


async def evaluate_round_answer_tool(**kwargs: Any) -> ToolResult:
    from agents.tools.base import tool_error, tool_success

    try:
        result = await evaluate_round_answer(**kwargs)
        return tool_success("evaluate_round_answer", {"evaluation": result}, {"round": kwargs.get("round_name")})
    except Exception as exc:
        return tool_error("evaluate_round_answer", f"{type(exc).__name__}: {exc}")


async def evaluate_dsa_reasoning_tool(**kwargs: Any) -> ToolResult:
    from agents.tools.base import tool_error, tool_success

    try:
        result = await evaluate_dsa_submission_reasoning(**kwargs)
        return tool_success("evaluate_dsa_reasoning", {"evaluation": result})
    except Exception as exc:
        return tool_error("evaluate_dsa_reasoning", f"{type(exc).__name__}: {exc}")
