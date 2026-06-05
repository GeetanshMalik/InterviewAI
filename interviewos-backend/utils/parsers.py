from __future__ import annotations

import json
import re
from ast import literal_eval
from typing import Any


def _strip_json_fences(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    return re.sub(r"^json\s*", "", cleaned, flags=re.IGNORECASE).strip()


def _extract_json_object(text: str) -> str:
    if text.startswith("{"):
        return text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text


def _balance_json_delimiters(text: str) -> str:
    """Repair common LLM delimiter slips without touching string contents."""

    if not text:
        return text

    expected_closer = {"{": "}", "[": "]"}
    opener_for = {"}": "{", "]": "["}
    stack: list[str] = []
    chars = list(text)
    in_string = False
    escaped = False

    for index, char in enumerate(chars):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char in expected_closer:
            stack.append(char)
        elif char in opener_for:
            if stack and stack[-1] == opener_for[char]:
                stack.pop()
            elif stack:
                chars[index] = expected_closer[stack.pop()]

    if stack:
        chars.extend(expected_closer[opener] for opener in reversed(stack))

    repaired = "".join(chars)
    return re.sub(r",\s*([}\]])", r"\1", repaired)


def _escape_control_chars_in_json_strings(text: str) -> str:
    """Escape raw newlines/tabs that LLMs sometimes place inside JSON strings."""

    if not text:
        return text

    chars: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                chars.append(char)
                escaped = False
                continue
            if char == "\\":
                chars.append(char)
                escaped = True
                continue
            if char == '"':
                chars.append(char)
                in_string = False
                continue
            if char == "\n":
                chars.append("\\n")
                continue
            if char == "\r":
                chars.append("\\n")
                continue
            if char == "\t":
                chars.append("\\t")
                continue
            chars.append(char)
            continue

        chars.append(char)
        if char == '"':
            in_string = True

    return "".join(chars)


def _json_candidates(text: str) -> list[str]:
    cleaned = _extract_json_object(_strip_json_fences(text))
    candidates = [cleaned]
    escaped_control_chars = _escape_control_chars_in_json_strings(cleaned)
    if escaped_control_chars != cleaned:
        candidates.append(escaped_control_chars)
    balanced = _balance_json_delimiters(cleaned)
    if balanced != cleaned:
        candidates.append(balanced)
        escaped_balanced = _escape_control_chars_in_json_strings(balanced)
        if escaped_balanced not in candidates:
            candidates.append(escaped_balanced)
    without_trailing_commas = re.sub(r",\s*([}\]])", r"\1", cleaned)
    if without_trailing_commas not in candidates:
        candidates.append(without_trailing_commas)
    return candidates


def json_from_text(text: str, *, root_error: str = "AI response JSON root must be an object.") -> dict[str, Any]:
    last_error: Exception | None = None
    for candidate in _json_candidates(text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            try:
                parsed = literal_eval(candidate)
            except (SyntaxError, ValueError) as literal_error:
                last_error = literal_error
                continue
        if not isinstance(parsed, dict):
            raise ValueError(root_error)
        return parsed
    if last_error:
        raise last_error
    raise ValueError(root_error)


def clean_text(value: Any, *, limit: int | None = None, preserve_paragraphs: bool = False) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r", "\n")
    if preserve_paragraphs:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        cleaned = text.strip()
    else:
        cleaned = re.sub(r"\s+", " ", text).strip()
    if limit is not None and limit >= 0:
        return cleaned[:limit]
    return cleaned


def clean_generated_text(value: Any, fallback: str = "") -> str:
    text = clean_text(value, preserve_paragraphs=True).replace("\\n", "\n")
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
