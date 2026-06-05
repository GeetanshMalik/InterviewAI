from __future__ import annotations

import json
import re
from typing import Any

from services.llm import llm_service
from services.store import new_id
from utils.parsers import json_from_text


APTITUDE_DIVERSITY_REQUIREMENT = (
    "For aptitude mode, cover at least six distinct categories across the set: "
    "percentages, ratios, averages, time and work, speed and distance, probability, "
    "number series/logical reasoning, data interpretation, and permutations/combinations. "
    "Do not reuse the same story, arithmetic operation, or sentence template."
)

MIXED_DIVERSITY_REQUIREMENT = (
    "For mixed mode, include both DSA reasoning and aptitude. Use varied DSA topics "
    "such as arrays, strings, hash maps, graphs, recursion, complexity, and debugging, "
    "plus varied aptitude topics."
)


def _json_from_text(text: str) -> dict[str, Any]:
    return json_from_text(text, root_error="Practice agent response must be a JSON object.")


def _string(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _clean_generated_text(value: Any, fallback: str = "") -> str:
    text = _string(value, fallback).replace("\\n", "\n")
    text = re.sub(r"```(?:\w+)?\n?", "", text)
    text = text.replace("```", "")
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*\*\*([^*\n]+)\*\*\*", r"\1", text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_\n]+)__", r"\1", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return cleaned or fallback


def _list(value: Any, fallback: list[Any] | None = None) -> list[Any]:
    return value if isinstance(value, list) else fallback or []


def _question_count(value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 20
    return min(30, max(5, parsed))


def _generation_error_message(error: Exception | None) -> str:
    if error is None:
        return "the model returned no usable response."
    if isinstance(error, (json.JSONDecodeError, SyntaxError)):
        return "the model returned malformed JSON. Please try again."
    return str(error)


def _normalize_questions(raw_items: Any, mode: str, difficulty: str, topic_filter: str | None, count: int) -> list[dict]:
    normalized = []
    for index, raw in enumerate(_list(raw_items)[:count], start=1):
        item = raw if isinstance(raw, dict) else {}
        options = item.get("options")
        if isinstance(options, list):
            options = {letter: str(value) for letter, value in zip(["A", "B", "C", "D"], options)}
        options = options if isinstance(options, dict) else {}
        if set(options.keys()) != {"A", "B", "C", "D"}:
            continue
        answer = _string(item.get("correct_answer")).upper()
        if answer not in options:
            continue
        question_text = _clean_generated_text(item.get("question_text") or item.get("question"))
        if len(question_text) < 15:
            continue
        normalized.append(
            {
                "id": new_id(),
                "type": "mcq",
                "question_number": index,
                "question_text": question_text,
                "question": question_text,
                "options": {key: _clean_generated_text(value) for key, value in options.items()},
                "correct_answer": answer,
                "category": _clean_generated_text(item.get("category"), topic_filter or mode),
                "difficulty": _clean_generated_text(item.get("difficulty"), difficulty),
                "explanation": _clean_generated_text(item.get("explanation"), f"The correct option is {answer}."),
                "skill_tested": _clean_generated_text(item.get("skill_tested"), topic_filter or mode),
                "source": "llm-generated",
            }
        )
    if len(normalized) != count:
        raise ValueError(
            f"Question generation returned {len(normalized)} valid questions, but {count} were required."
        )
    return normalized


def _question_quality_issue(questions: list[dict], mode: str, count: int) -> str | None:
    normalized_texts = [
        re.sub(r"\s+", " ", str(question.get("question_text") or question.get("question", "")).strip().lower())
        for question in questions
    ]
    if len(set(normalized_texts)) != len(normalized_texts):
        return "The model returned duplicate questions."

    if mode != "aptitude" or count < 8:
        return None

    categories = {
        re.sub(r"\s+", " ", str(question.get("category", "")).strip().lower())
        for question in questions
        if question.get("category")
    }
    if len(categories) < min(6, count):
        return f"The model returned only {len(categories)} aptitude categories; at least {min(6, count)} are required."

    repeated_stems: dict[str, int] = {}
    for text in normalized_texts:
        stem = re.sub(r"\b\d+(?:\.\d+)?%?\b", "#", text[:120])
        stem = re.sub(r"\b[a-d]\b", "#", stem)
        repeated_stems[stem] = repeated_stems.get(stem, 0) + 1
    most_repeated = max(repeated_stems.values(), default=0)
    if most_repeated > max(3, count // 4):
        return "The model repeated the same aptitude question pattern too many times."

    return None


def public_practice_questions(questions: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in question.items() if key not in {"correct_answer", "explanation"}}
        for question in questions
    ]


async def generate_practice_mcqs(
    mode: str,
    difficulty: str,
    topic_filter: str | None = None,
    count: int = 20,
    history: list[dict] | None = None,
) -> list[dict]:
    count = _question_count(count)
    agent = "dsa" if mode == "dsa" else "aptitude"
    topic = topic_filter or ("data structures and algorithms" if mode == "dsa" else mode)
    diversity_requirement = ""
    if mode == "aptitude":
        diversity_requirement = APTITUDE_DIVERSITY_REQUIREMENT
    elif mode == "mixed":
        diversity_requirement = MIXED_DIVERSITY_REQUIREMENT
    history_context = [
        {
            "mode": session.get("mode"),
            "score": session.get("score"),
            "categories": [
                question.get("category")
                for question in session.get("questions", [])[:8]
                if isinstance(question, dict)
            ],
            "question_excerpts": [
                str(question.get("question_text") or question.get("question", ""))[:160]
                for question in session.get("questions", [])[:5]
                if isinstance(question, dict)
            ],
        }
        for session in (history or [])[:5]
    ]
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            retry_note = (
                f"\nThe previous response failed validation: {last_error}. Regenerate with more variety."
                if last_error
                else ""
            )
            response = await llm_service.invoke_live(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are the InterviewOS Practice Agent. Generate fresh multiple-choice "
                            "interview practice questions. Avoid repeating common stock questions. "
                            "Return only JSON with plain-text string values."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Generate exactly {count} {difficulty} MCQ questions for mode '{mode}'. "
                            f"Topic focus: {topic}.\n"
                            f"{diversity_requirement}\n"
                            "Avoid repeating recent practice question patterns from this history:\n"
                            f"{json.dumps(history_context, ensure_ascii=False)}\n"
                            "Do not include markdown emphasis markers like **, __, or backticks in any string value.\n"
                            "Return this JSON shape:\n"
                            "{\n"
                            '  "questions": [{"question_text": "string", "options": {"A": "string", "B": "string", "C": "string", "D": "string"}, "correct_answer": "A|B|C|D", "category": "string", "difficulty": "easy|medium|hard", "explanation": "string", "skill_tested": "string"}]\n'
                            "}"
                            f"{retry_note}"
                        ),
                    },
                ],
                agent=agent,
            )
            payload = _json_from_text(response.content)
            questions = _normalize_questions(payload.get("questions"), mode, difficulty, topic_filter, count)
            quality_issue = _question_quality_issue(questions, mode, count)
            if quality_issue:
                raise ValueError(quality_issue)
            return questions
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Practice question generation failed: {_generation_error_message(last_error)}") from last_error
