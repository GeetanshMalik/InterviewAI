from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import re
from typing import Any, Literal


SecurityRiskLevel = Literal["clean", "low", "medium", "high"]


@dataclass
class QuarantinedSpan:
    source: str
    label: str
    severity: SecurityRiskLevel
    start: int
    end: int
    text_hash: str
    replacement: str


@dataclass
class SanitizedText:
    source: str
    clean_text: str
    risk_level: SecurityRiskLevel = "clean"
    reasons: list[str] = field(default_factory=list)
    quarantined_spans: list[QuarantinedSpan] = field(default_factory=list)
    original_length: int = 0

    def private_metadata(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "risk_level": self.risk_level,
            "reasons": self.reasons,
            "original_length": self.original_length,
            "quarantined_spans": [asdict(span) for span in self.quarantined_spans],
        }


_RISK_ORDER: dict[SecurityRiskLevel, int] = {"clean": 0, "low": 1, "medium": 2, "high": 3}


_PROMPT_INJECTION_PATTERNS: list[tuple[str, SecurityRiskLevel, re.Pattern[str]]] = [
    (
        "ignore_previous_instructions",
        "high",
        re.compile(r"\b(ignore|disregard|forget|override)\s+(all\s+)?(previous|prior|above|system|developer)\s+instructions?\b", re.I),
    ),
    (
        "system_prompt_exfiltration",
        "high",
        re.compile(r"\b(reveal|print|show|dump|repeat)\s+(the\s+)?(system|developer)\s+(prompt|message|instructions?)\b", re.I),
    ),
    (
        "forced_score_or_hiring_decision",
        "high",
        re.compile(r"\b(give|assign|return|mark)\s+(me|this candidate|the candidate)?\s*(a\s+)?(100|perfect|full)\s*(/100|score|rating)?\b", re.I),
    ),
    (
        "role_hijack",
        "medium",
        re.compile(r"\b(you are now|act as|pretend to be)\s+(a\s+)?(different|new)?\s*(system|developer|admin|evaluator|interviewer)\b", re.I),
    ),
    (
        "tool_control_attempt",
        "medium",
        re.compile(r"\b(call|use|invoke|execute)\s+(the\s+)?(tool|function|api)\b.*\b(ignore|bypass|disable|override)\b", re.I),
    ),
    (
        "instruction_boundary_attack",
        "medium",
        re.compile(r"\b(system message|developer message|hidden instructions?|jailbreak|prompt injection)\b", re.I),
    ),
]


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _max_risk(current: SecurityRiskLevel, candidate: SecurityRiskLevel) -> SecurityRiskLevel:
    return candidate if _RISK_ORDER[candidate] > _RISK_ORDER[current] else current


def sanitize_untrusted_text(
    text: Any,
    *,
    source: str,
    limit: int | None = None,
) -> SanitizedText:
    raw = "" if text is None else str(text)
    clean = raw.replace("\x00", "")
    spans: list[QuarantinedSpan] = []
    risk: SecurityRiskLevel = "clean"
    reasons: list[str] = []

    replacements: list[tuple[int, int, str]] = []
    for label, severity, pattern in _PROMPT_INJECTION_PATTERNS:
        for match in pattern.finditer(clean):
            matched = match.group(0)
            replacement = f"[quarantined:{label}]"
            spans.append(
                QuarantinedSpan(
                    source=source,
                    label=label,
                    severity=severity,
                    start=match.start(),
                    end=match.end(),
                    text_hash=_hash_text(matched),
                    replacement=replacement,
                )
            )
            replacements.append((match.start(), match.end(), replacement))
            risk = _max_risk(risk, severity)
            if label not in reasons:
                reasons.append(label)

    for start, end, replacement in sorted(replacements, key=lambda item: item[0], reverse=True):
        clean = clean[:start] + replacement + clean[end:]

    clean = re.sub(r"[ \t]+", " ", clean)
    clean = re.sub(r"\n{4,}", "\n\n\n", clean).strip()
    if limit is not None and limit >= 0:
        clean = clean[:limit]

    return SanitizedText(
        source=source,
        clean_text=clean,
        risk_level=risk,
        reasons=reasons,
        quarantined_spans=spans,
        original_length=len(raw),
    )


def should_fail_closed(result: SanitizedText) -> bool:
    high_hits = [span for span in result.quarantined_spans if span.severity == "high"]
    return len(high_hits) >= 2


def merge_security_metadata(results: list[SanitizedText], *, source: str) -> dict[str, Any]:
    risk: SecurityRiskLevel = "clean"
    reasons: list[str] = []
    spans: list[dict[str, Any]] = []
    for result in results:
        risk = _max_risk(risk, result.risk_level)
        for reason in result.reasons:
            if reason not in reasons:
                reasons.append(reason)
        spans.extend(asdict(span) for span in result.quarantined_spans)
    return {
        "source": source,
        "risk_level": risk,
        "reasons": reasons,
        "quarantined_spans": spans,
        "quarantined_count": len(spans),
        "failed_closed": any(should_fail_closed(result) for result in results),
    }


def sanitize_memory_records(records: list[dict[str, Any]], *, source: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sanitized_records: list[dict[str, Any]] = []
    results: list[SanitizedText] = []
    for index, record in enumerate(records):
        item = dict(record)
        text_key = "text" if "text" in item else "excerpt"
        result = sanitize_untrusted_text(item.get(text_key, ""), source=f"{source}:{index}")
        results.append(result)
        item[text_key] = result.clean_text
        metadata = dict(item.get("metadata") or {})
        if result.quarantined_spans:
            metadata["security"] = result.private_metadata()
        item["metadata"] = metadata
        sanitized_records.append(item)
    return sanitized_records, merge_security_metadata(results, source=source)


def sanitize_tool_observation(data: dict[str, Any], *, source: str, max_chars: int = 4000) -> tuple[dict[str, Any], dict[str, Any]]:
    result = sanitize_untrusted_text(data, source=source, limit=max_chars)
    return {"observation": result.clean_text}, result.private_metadata()

