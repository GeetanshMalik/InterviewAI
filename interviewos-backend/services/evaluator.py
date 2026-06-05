from __future__ import annotations

import re


UNSAFE_PATTERNS = [
    "kill",
    "killed",
    "murder",
    "buried",
    "dead body",
    "press her neck",
    "choke",
    "weapon",
    "violence",
    "threat",
]


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-zA-Z_][a-zA-Z0-9_+-]*", value.lower())


def _unsafe_hits(answer: str) -> list[str]:
    normalized = answer.lower()
    return [pattern for pattern in UNSAFE_PATTERNS if pattern in normalized]


def score_text_answer(
    answer: str,
    keywords: list[str],
    question_text: str = "",
    round_name: str = "interview",
) -> dict:
    unsafe = _unsafe_hits(answer)
    if unsafe:
        return {
            "score": 0.0,
            "matched_keywords": [],
            "safety_flags": unsafe,
            "feedback": "Unsafe or violent content is not acceptable in an interview answer. Re-answer professionally with a real workplace example.",
        }

    words = _tokens(answer)
    unique_words = set(words)
    question_terms = set(_tokens(question_text)) - {"the", "and", "you", "your", "with", "for", "this", "that", "how", "what"}
    keyword_hits = [keyword for keyword in keywords if keyword.lower() in " ".join(words)]

    word_count = len(words)
    length_score = min(word_count / 110 * 25, 25)
    specificity_score = 0
    if any(char.isdigit() for char in answer):
        specificity_score += 10
    if any(term in unique_words for term in ["i", "my", "we", "built", "led", "designed", "implemented", "debugged", "improved"]):
        specificity_score += 10
    if any(term in unique_words for term in ["because", "therefore", "tradeoff", "result", "impact", "learned"]):
        specificity_score += 10
    if len(answer.split(".")) >= 3:
        specificity_score += 5

    keyword_score = (len(keyword_hits) / max(len(keywords), 1)) * 30
    relevance_score = min(len(question_terms & unique_words) / max(len(question_terms), 1) * 25, 25)
    score = round(min(length_score + specificity_score + keyword_score + relevance_score, 100), 2)

    if word_count < 12:
        score = min(score, 20)
    if score >= 75:
        feedback = "Strong answer: it is relevant, specific, and includes interview-quality evidence."
    elif score >= 45:
        feedback = "Decent start. Add a clearer situation, concrete actions, tradeoffs, and measurable result."
    else:
        feedback = f"This {round_name} answer is too vague or off-topic. Use a real example, your actions, and the outcome."

    return {
        "score": score,
        "matched_keywords": keyword_hits,
        "safety_flags": [],
        "feedback": feedback,
    }
