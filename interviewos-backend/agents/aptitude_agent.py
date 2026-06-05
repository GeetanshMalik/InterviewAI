from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


OPTION_KEYS = ("A", "B", "C", "D")
ORDERING_SPECIFIERS = (
    "ascending",
    "descending",
    "increasing",
    "decreasing",
    "smallest",
    "largest",
    "lowest",
    "highest",
    "alphabetical",
    "chronological",
)


def public_questions(questions: list[dict]) -> list[dict]:
    hidden_keys = {
        "correct_answer",
        "correct_answer_value",
        "correct_answer_values",
        "correct_answers",
        "correct_value",
        "accepted_options",
        "accepted_values",
    }
    return [{key: value for key, value in question.items() if key not in hidden_keys} for question in questions]


def _decimal_from_text(value: Any) -> Decimal | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    fraction = re.search(r"([-+]?\d+(?:\.\d+)?)\s*/\s*([-+]?\d+(?:\.\d+)?)", text)
    if fraction:
        try:
            numerator = Decimal(fraction.group(1))
            denominator = Decimal(fraction.group(2))
            if denominator == 0:
                return None
            return numerator / denominator
        except InvalidOperation:
            return None
    percent = re.search(r"([-+]?\d+(?:\.\d+)?)\s*(?:%|percent\b)", text, flags=re.IGNORECASE)
    if percent:
        try:
            return Decimal(percent.group(1)) / Decimal(100)
        except InvalidOperation:
            return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def _numbers_from_text(text: str) -> list[Decimal]:
    cleaned = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    values: list[Decimal] = []
    for match in re.finditer(r"[-+]?\d+(?:\.\d+)?", cleaned):
        try:
            values.append(Decimal(match.group(0)))
        except InvalidOperation:
            continue
    return values


def _format_decimal(value: Decimal) -> str:
    if value == value.to_integral_value():
        return str(int(value))
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".")


def _format_signed(value: Decimal) -> str:
    prefix = "+" if value >= 0 else ""
    return f"{prefix}{_format_decimal(value)}"


def _format_addition(base: Decimal, delta: Decimal) -> str:
    operator = "+" if delta >= 0 else "-"
    return f"{_format_decimal(base)} {operator} {_format_decimal(abs(delta))}"


def _option_matching_value(options: dict[str, Any], expected: Decimal) -> str | None:
    matches = _option_matching_values(options, expected)
    return matches[0] if matches else None


def _sequence_value(value: Any) -> list[Decimal] | None:
    text = str(value or "").strip()
    if "/" in text or "," not in text:
        return None
    numbers = _numbers_from_text(text)
    return numbers if len(numbers) >= 2 else None


def _normalized_value(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,:;-")


def _values_match(left: Any, right: Any) -> bool:
    left_sequence = _sequence_value(left)
    right_sequence = _sequence_value(right)
    if left_sequence is not None or right_sequence is not None:
        return left_sequence is not None and right_sequence is not None and left_sequence == right_sequence
    left_decimal = _decimal_from_text(left)
    right_decimal = _decimal_from_text(right)
    if left_decimal is not None and right_decimal is not None:
        return left_decimal == right_decimal
    return bool(_normalized_value(left)) and _normalized_value(left) == _normalized_value(right)


def _option_matching_values(options: dict[str, Any], expected_value: Any) -> list[str]:
    return [key for key in OPTION_KEYS if _values_match(options.get(key), expected_value)]


def _unique_values(values: list[Any]) -> list[Any]:
    unique: list[Any] = []
    for value in values:
        if value is None:
            continue
        if not any(_values_match(value, existing) for existing in unique):
            unique.append(value)
    return unique


def _answer_values(options: dict[str, Any], answers: list[str], fallback_value: Any = None) -> list[Any]:
    values = [options.get(answer) for answer in answers if answer in options]
    if fallback_value is not None:
        values.append(fallback_value)
    return _unique_values(values)


def _resolution(
    *,
    stored_answer: str,
    correct_answers: list[str],
    correct_values: list[Any],
    explanation: str,
    ambiguous_question: bool = False,
) -> dict[str, Any]:
    normalized_answers = [answer for answer in OPTION_KEYS if answer in {str(item).upper() for item in correct_answers}]
    correct_answer = stored_answer if stored_answer in normalized_answers else (normalized_answers[0] if normalized_answers else stored_answer)
    normalized_values = _unique_values(correct_values)
    correct_value = normalized_values[0] if normalized_values else None
    return {
        "correct_answer": correct_answer,
        "correct_answers": normalized_answers or ([stored_answer] if stored_answer else []),
        "correct_value": correct_value,
        "correct_values": normalized_values,
        "explanation": explanation,
        "answer_key_corrected": bool(stored_answer and normalized_answers and stored_answer not in normalized_answers),
        "original_correct_answer": stored_answer,
        "ambiguous_question": ambiguous_question,
    }


def _numeric_sequence_solution(question_text: str) -> tuple[Decimal, str] | None:
    lowered = question_text.lower()
    if "sequence" not in lowered or "next" not in lowered:
        return None

    numbers = _numbers_from_text(question_text)
    if len(numbers) < 4:
        return None

    differences = [numbers[index + 1] - numbers[index] for index in range(len(numbers) - 1)]
    if all(difference == differences[0] for difference in differences[1:]):
        expected = numbers[-1] + differences[-1]
        explanation = (
            f"The difference is {_format_signed(differences[-1])} each time, so "
            f"{_format_addition(numbers[-1], differences[-1])} = {_format_decimal(expected)}."
        )
        return expected, explanation

    if len(differences) >= 3:
        second_differences = [
            differences[index + 1] - differences[index] for index in range(len(differences) - 1)
        ]
        if all(delta == second_differences[0] for delta in second_differences[1:]):
            next_difference = differences[-1] + second_differences[-1]
            expected = numbers[-1] + next_difference
            explanation = (
                "The differences are "
                f"{', '.join(_format_signed(difference) for difference in differences)}. "
                f"They increase by {_format_decimal(second_differences[-1])}, so the next difference is "
                f"{_format_signed(next_difference)}. Therefore "
                f"{_format_addition(numbers[-1], next_difference)} = {_format_decimal(expected)}."
            )
            return expected, explanation

    if all(number != 0 for number in numbers[:-1]):
        ratios = [numbers[index + 1] / numbers[index] for index in range(len(numbers) - 1)]
        if all(ratio == ratios[0] for ratio in ratios[1:]):
            expected = numbers[-1] * ratios[-1]
            explanation = (
                f"Each term is multiplied by {_format_decimal(ratios[-1])}, so "
                f"{_format_decimal(numbers[-1])} x {_format_decimal(ratios[-1])} = {_format_decimal(expected)}."
            )
            return expected, explanation

    if len(numbers) >= 5 and all(numbers[index] == numbers[index - 1] + numbers[index - 2] for index in range(2, len(numbers))):
        expected = numbers[-1] + numbers[-2]
        explanation = (
            "Each term is the sum of the previous two terms, so "
            f"{_format_decimal(numbers[-2])} + {_format_decimal(numbers[-1])} = {_format_decimal(expected)}."
        )
        return expected, explanation

    return None


def _ratio_solution(question_text: str) -> tuple[Decimal, str] | None:
    lowered = question_text.lower()
    if "for every" not in lowered or "if" not in lowered:
        return None
    numbers = _numbers_from_text(question_text)
    if len(numbers) < 3 or numbers[0] == 0:
        return None
    group_size, matching_count, total = numbers[0], numbers[1], numbers[-1]
    expected = total * matching_count / group_size
    explanation = (
        f"For every {_format_decimal(group_size)}, {_format_decimal(matching_count)} match the condition. "
        f"So {_format_decimal(total)} x {_format_decimal(matching_count)} / {_format_decimal(group_size)} = "
        f"{_format_decimal(expected)}."
    )
    return expected, explanation


def _percentage_solution(question_text: str) -> tuple[Decimal, str] | None:
    match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*(?:percent|%)", question_text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        percent = Decimal(match.group(1))
    except InvalidOperation:
        return None
    after_percent_numbers = _numbers_from_text(question_text[match.end() :])
    if not after_percent_numbers:
        return None
    total = after_percent_numbers[-1]
    expected = total * percent / Decimal(100)
    explanation = (
        f"{_format_decimal(percent)} percent of {_format_decimal(total)} is "
        f"{_format_decimal(percent / Decimal(100))} x {_format_decimal(total)} = {_format_decimal(expected)}."
    )
    return expected, explanation


def _die_probability_solution(question_text: str) -> tuple[Decimal, str] | None:
    lowered = question_text.lower()
    if "die" not in lowered and "dice" not in lowered:
        return None

    sides = Decimal(6)
    sided_match = re.search(r"(\d+)\s*[- ]?\s*sided", lowered)
    if sided_match:
        try:
            sides = Decimal(sided_match.group(1))
        except InvalidOperation:
            return None
    if sides <= 0 or sides != sides.to_integral_value():
        return None

    condition_match = re.search(
        r"(?:number|roll|rolling|outcome)\s+(greater than|more than|less than|at least|at most|equal to|equals)\s+([-+]?\d+)",
        lowered,
    )
    if not condition_match:
        condition_match = re.search(
            r"(greater than|more than|less than|at least|at most|equal to|equals)\s+([-+]?\d+)",
            lowered,
        )
    if not condition_match:
        return None

    operator, threshold_text = condition_match.groups()
    try:
        threshold = int(threshold_text)
    except ValueError:
        return None

    side_count = int(sides)
    outcomes = list(range(1, side_count + 1))
    if operator in {"greater than", "more than"}:
        favorable = [value for value in outcomes if value > threshold]
        condition_text = f"greater than {threshold}"
    elif operator == "less than":
        favorable = [value for value in outcomes if value < threshold]
        condition_text = f"less than {threshold}"
    elif operator == "at least":
        favorable = [value for value in outcomes if value >= threshold]
        condition_text = f"at least {threshold}"
    elif operator == "at most":
        favorable = [value for value in outcomes if value <= threshold]
        condition_text = f"at most {threshold}"
    else:
        favorable = [value for value in outcomes if value == threshold]
        condition_text = f"equal to {threshold}"

    expected = Decimal(len(favorable)) / sides
    fraction_text = f"{len(favorable)}/{side_count}"
    explanation = (
        f"A fair {side_count}-sided die has {side_count} equally likely outcomes. "
        f"The outcomes {condition_text} are {', '.join(str(value) for value in favorable) or 'none'}, "
        f"so the probability is {fraction_text}, which equals {_format_decimal(expected)}."
    )
    return expected, explanation


def _deterministic_solution(question_text: str) -> tuple[Decimal, str] | None:
    return (
        _numeric_sequence_solution(question_text)
        or _ratio_solution(question_text)
        or _percentage_solution(question_text)
        or _die_probability_solution(question_text)
    )


def _underspecified_ordering_resolution(
    question_text: str,
    options: dict[str, Any],
    stored_answer: str,
) -> dict[str, Any] | None:
    lowered = question_text.lower()
    if not any(term in lowered for term in ("order", "ordering", "ordered")):
        return None
    if any(term in lowered for term in ORDERING_SPECIFIERS):
        return None
    if "specific" not in lowered and "correct" not in lowered:
        return None

    source_numbers = _numbers_from_text(question_text)
    if len(source_numbers) < 3:
        return None

    accepted_answers: list[str] = []
    for key in OPTION_KEYS:
        option_numbers = _sequence_value(options.get(key))
        if not option_numbers or len(option_numbers) != len(source_numbers):
            continue
        if sorted(option_numbers) == sorted(source_numbers):
            accepted_answers.append(key)

    if not accepted_answers:
        return None

    explanation = (
        "The question does not specify whether the numbers should be arranged ascending, descending, "
        "or by another rule. Because the prompt is underspecified, any option that is a complete ordering "
        "of the given numbers is accepted."
    )
    return _resolution(
        stored_answer=stored_answer,
        correct_answers=accepted_answers,
        correct_values=_answer_values(options, accepted_answers),
        explanation=explanation,
        ambiguous_question=True,
    )


def _explanation_final_option_values(options: dict[str, Any], explanation: str) -> list[str]:
    numbers = _numbers_from_text(explanation)
    for value in reversed(numbers):
        keys = _option_matching_values(options, value)
        if keys:
            return keys
    return []


def _resolved_answer(question: dict) -> dict[str, Any]:
    stored_answer = str(question.get("correct_answer") or "").upper()
    stored_explanation = str(question.get("explanation") or "").strip()
    options = question.get("options")
    if not isinstance(options, dict):
        stored_value = question.get("correct_answer_value") or question.get("correct_value")
        return _resolution(
            stored_answer=stored_answer,
            correct_answers=[stored_answer] if stored_answer else [],
            correct_values=[stored_value] if stored_value is not None else [],
            explanation=stored_explanation,
        )

    question_text = str(question.get("question_text") or question.get("question") or "")
    ambiguous_ordering = _underspecified_ordering_resolution(question_text, options, stored_answer)
    if ambiguous_ordering:
        return ambiguous_ordering

    deterministic_solution = _deterministic_solution(question_text)
    if deterministic_solution:
        expected, explanation = deterministic_solution
        corrected_answers = _option_matching_values(options, expected)
        if corrected_answers:
            return _resolution(
                stored_answer=stored_answer,
                correct_answers=corrected_answers,
                correct_values=_answer_values(options, corrected_answers, _format_decimal(expected)),
                explanation=explanation,
            )

    stored_value = question.get("correct_answer_value") or question.get("correct_value")
    if stored_value:
        corrected_answers = _option_matching_values(options, stored_value)
        if corrected_answers:
            return _resolution(
                stored_answer=stored_answer,
                correct_answers=corrected_answers,
                correct_values=_answer_values(options, corrected_answers, stored_value),
                explanation=stored_explanation,
            )

    explanation_answers = _explanation_final_option_values(options, stored_explanation)
    if explanation_answers:
        return _resolution(
            stored_answer=stored_answer,
            correct_answers=explanation_answers,
            correct_values=_answer_values(options, explanation_answers),
            explanation=stored_explanation,
        )

    fallback_answers = [stored_answer] if stored_answer in options else []
    return _resolution(
        stored_answer=stored_answer,
        correct_answers=fallback_answers,
        correct_values=_answer_values(options, fallback_answers),
        explanation=stored_explanation,
    )


def normalize_question_answer_key(question: dict) -> dict:
    resolved = _resolved_answer(question)
    if resolved["correct_answer"]:
        question["correct_answer"] = resolved["correct_answer"]
    if resolved.get("correct_value"):
        question["correct_answer_value"] = resolved["correct_value"]
    if resolved.get("correct_answers"):
        question["correct_answers"] = resolved["correct_answers"]
    if resolved.get("correct_values"):
        question["correct_answer_values"] = resolved["correct_values"]
    if resolved.get("ambiguous_question"):
        question["ambiguous_question"] = True
    if resolved["explanation"]:
        question["explanation"] = resolved["explanation"]
    return question


def _selected_answer_parts(raw_answer: Any) -> tuple[str, Any]:
    if isinstance(raw_answer, dict):
        selected_key = str(
            raw_answer.get("option")
            or raw_answer.get("selected")
            or raw_answer.get("key")
            or raw_answer.get("answer")
            or ""
        ).upper()
        selected_value = raw_answer.get("value") or raw_answer.get("label") or raw_answer.get("text")
        return selected_key, selected_value
    return str(raw_answer or "").upper(), None


def evaluate_answers(questions: list[dict], answers: dict[str, Any]) -> dict:
    results = []
    correct = 0
    for question in questions:
        resolved = _resolved_answer(question)
        correct_answer = resolved["correct_answer"] or question["correct_answer"]
        correct_value = resolved.get("correct_value")
        correct_answers = [str(answer).upper() for answer in resolved.get("correct_answers", []) if answer]
        correct_values = resolved.get("correct_values", [])
        options = question.get("options") if isinstance(question.get("options"), dict) else {}
        selected, selected_value = _selected_answer_parts(answers.get(question["id"]))
        if selected and selected_value is None and isinstance(options, dict):
            selected_value = options.get(selected)

        selected_candidates = [selected_value]
        if isinstance(options, dict) and selected:
            selected_candidates.append(options.get(selected))
        selected_value_matches = any(
            candidate is not None and _values_match(candidate, accepted_value)
            for candidate in selected_candidates
            for accepted_value in correct_values
        )
        is_correct = selected in (correct_answers or [correct_answer]) or selected_value_matches
        correct += int(is_correct)
        results.append(
            {
                "question_id": question["id"],
                "selected": selected,
                "selected_value": selected_value,
                "correct": correct_answer,
                "correct_value": correct_value,
                "correct_options": correct_answers,
                "correct_values": correct_values,
                "accepted_options": correct_answers,
                "accepted_values": correct_values,
                "is_correct": is_correct,
                "explanation": resolved["explanation"] or question["explanation"],
                "answer_key_corrected": resolved["answer_key_corrected"],
                "original_correct_answer": resolved["original_correct_answer"],
                "ambiguous_question": resolved.get("ambiguous_question", False),
            }
        )
    score = round((correct / max(len(questions), 1)) * 100, 2)
    return {"score": score, "correct": correct, "wrong": len(questions) - correct, "per_question_results": results}


def repair_saved_result(questions: list[dict], result: dict | None) -> dict | None:
    if not result:
        return result
    answers = {
        str(entry.get("question_id")): {
            "option": entry.get("selected"),
            "value": entry.get("selected_value"),
        }
        for entry in result.get("per_question_results", [])
        if entry.get("question_id")
    }
    if not answers:
        return result
    repaired = evaluate_answers(questions, answers)
    repaired["timeTakenSeconds"] = result.get("timeTakenSeconds")
    return {**result, **repaired}
