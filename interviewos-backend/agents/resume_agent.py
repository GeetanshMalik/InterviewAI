from __future__ import annotations

import json
import re
from ast import literal_eval
from datetime import date, datetime
from typing import Any

from services.llm import llm_service
from utils.parsers import clean_text as parser_clean_text, json_from_text


SECTION_ALIASES = {
    "summary": {"summary", "profile", "objective", "about me", "professional summary", "career summary"},
    "experience": {
        "experience",
        "experiences",
        "work experience",
        "professional experience",
        "employment",
        "employment history",
        "internship",
        "internships",
    },
    "projects": {"project", "projects", "personal projects", "academic projects", "selected projects"},
    "skills": {"skills", "technical skills", "core skills", "competencies", "tools", "technologies"},
    "education": {"education", "educations", "academic background", "academics"},
    "certifications": {"certification", "certifications", "certificate", "certificates", "licenses", "training"},
    "achievements": {"achievements", "awards", "honors", "publications", "leadership"},
    "languages": {"language", "languages"},
}

DISPLAY_NAMES = {
    "summary": "Summary",
    "experience": "Experience",
    "projects": "Projects",
    "skills": "Skills",
    "education": "Education",
    "certifications": "Certifications",
    "achievements": "Achievements",
    "languages": "Languages",
}

GENERAL_KEYWORDS = [
    "leadership",
    "collaboration",
    "communication",
    "analytics",
    "strategy",
    "project management",
    "problem solving",
    "documentation",
    "testing",
    "stakeholder",
]

ROLE_KEYWORDS: dict[str, list[str]] = {
    "software": [
        "python",
        "javascript",
        "typescript",
        "java",
        "react",
        "node",
        "api",
        "database",
        "sql",
        "testing",
        "git",
        "cloud",
        "system design",
    ],
    "frontend": ["javascript", "typescript", "react", "html", "css", "accessibility", "performance", "testing", "api"],
    "backend": ["python", "java", "node", "api", "sql", "database", "microservices", "cloud", "testing", "scalability"],
    "data": ["sql", "python", "excel", "statistics", "dashboard", "analytics", "visualization", "etl", "machine learning"],
    "product": ["roadmap", "metrics", "user research", "prioritization", "experimentation", "stakeholder", "launch", "strategy"],
    "design": ["user research", "wireframe", "prototype", "figma", "accessibility", "usability", "visual design", "design system"],
    "marketing": ["campaign", "seo", "sem", "analytics", "conversion", "content", "brand", "growth", "crm"],
    "sales": ["pipeline", "quota", "crm", "negotiation", "prospecting", "revenue", "account", "forecasting"],
    "finance": ["financial modeling", "forecasting", "excel", "variance", "budget", "audit", "compliance", "reporting"],
    "hr": ["recruiting", "employee relations", "onboarding", "performance management", "hris", "compliance", "talent"],
    "operations": ["process improvement", "vendor", "logistics", "inventory", "kpi", "workflow", "cost reduction"],
    "default": GENERAL_KEYWORDS,
}

KEYWORD_SYNONYMS: dict[str, list[str]] = {
    "api": ["api", "apis", "rest api", "rest apis"],
    "cloud": ["cloud", "cloud computing"],
    "database": ["database", "databases", "mongodb", "mysql", "postgresql", "postgres", "sql", "mern", "mern stack"],
    "git": ["git", "github", "git/github"],
    "javascript": ["javascript", "java script", "js", "mern", "mern stack"],
    "machine learning": ["machine learning", "ml", "xgboost", "scikit-learn", "sklearn", "model evaluation"],
    "node": ["node", "node.js", "nodejs", "mern", "mern stack"],
    "react": ["react", "react.js", "reactjs", "mern", "mern stack"],
    "sql": ["sql", "mysql", "postgresql", "postgres"],
    "testing": ["testing", "test", "model evaluation", "evaluation"],
    "typescript": ["typescript", "ts"],
}

SUPPORTING_SECTIONS = {"languages", "certifications", "education"}

PROFICIENCY_TERMS = {
    "native",
    "fluent",
    "bilingual",
    "professional",
    "advanced",
    "intermediate",
    "conversational",
    "beginner",
    "basic",
}

TECHNICAL_TERMS = [
    "python",
    "javascript",
    "typescript",
    "java",
    "react",
    "node",
    "express",
    "mongodb",
    "mysql",
    "sql",
    "html",
    "css",
    "tailwind",
    "mern stack",
    "machine learning",
    "xgboost",
    "scikit-learn",
    "sklearn",
    "numpy",
    "pandas",
    "data preprocessing",
    "model evaluation",
    "git",
    "github",
    "linux",
    "postman",
    "cloud",
]

PRODUCTION_ASSUMPTION_TERMS = {
    "users",
    "customers",
    "customer",
    "production",
    "published",
    "deployed",
    "deployment",
    "launched",
    "live",
    "business impact",
    "impact of the project",
}

PRODUCTION_EVIDENCE_TERMS = {
    "users",
    "customers",
    "production",
    "published",
    "deployed",
    "deployment",
    "launched",
    "live",
}

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _review_date() -> date:
    return datetime.now().astimezone().date()


def _clean_text(value: str) -> str:
    return parser_clean_text(value, preserve_paragraphs=True)


def _json_from_text(text: str) -> dict[str, Any]:
    return json_from_text(text, root_error="Resume analysis response must be a JSON object.")


def _string(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _list(value: Any, fallback: list[Any] | None = None) -> list[Any]:
    return value if isinstance(value, list) else fallback or []


def _normalize_key(value: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9 &/+-]", "", value.lower()).strip()
    normalized = normalized.replace("&", "and")
    for key, aliases in SECTION_ALIASES.items():
        if normalized in aliases:
            return key
    return None


def _extract_sections(text: str) -> dict[str, str]:
    lines = [line.strip() for line in _clean_text(text).splitlines()]
    sections: dict[str, list[str]] = {"header": []}
    current = "header"

    for line in lines:
        if not line:
            continue
        heading_candidate = re.sub(r"[:\-]+$", "", line).strip()
        key = _normalize_key(heading_candidate)
        if key and len(line.split()) <= 4:
            current = key
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)

    parsed = {
        key: "\n".join(value).strip()
        for key, value in sections.items()
        if key != "header" and "\n".join(value).strip()
    }
    header_text = "\n".join(sections.get("header", [])).strip()
    if not parsed and header_text:
        parsed["summary"] = header_text
    return parsed


def _role_keyword_bucket(target_role: str | None) -> list[str]:
    role = (target_role or "").lower()
    if not role:
        return []
    if any(token in role for token in ["frontend", "react", "ui engineer", "web developer"]):
        return ROLE_KEYWORDS["frontend"]
    if any(token in role for token in ["backend", "api", "server"]):
        return ROLE_KEYWORDS["backend"]
    if any(token in role for token in ["software", "developer", "engineer", "programmer"]):
        return ROLE_KEYWORDS["software"]
    if any(token in role for token in ["data", "analyst", "scientist", "business intelligence"]):
        return ROLE_KEYWORDS["data"]
    if "product" in role:
        return ROLE_KEYWORDS["product"]
    if any(token in role for token in ["designer", "design", "ux", "ui"]):
        return ROLE_KEYWORDS["design"]
    if any(token in role for token in ["marketing", "growth", "seo", "brand"]):
        return ROLE_KEYWORDS["marketing"]
    if any(token in role for token in ["sales", "account executive", "business development"]):
        return ROLE_KEYWORDS["sales"]
    if any(token in role for token in ["finance", "accountant", "audit", "banking"]):
        return ROLE_KEYWORDS["finance"]
    if any(token in role for token in ["hr", "recruit", "talent", "people"]):
        return ROLE_KEYWORDS["hr"]
    if any(token in role for token in ["operations", "supply", "logistics", "manager"]):
        return ROLE_KEYWORDS["operations"]
    return ROLE_KEYWORDS["default"]


def _contains_keyword(text: str, keyword: str) -> bool:
    normalized = text.lower()
    for variant in KEYWORD_SYNONYMS.get(keyword.lower(), [keyword.lower()]):
        escaped = re.escape(variant)
        if re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", normalized):
            return True
    return False


def _has_date(text: str) -> bool:
    months = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december"
    return bool(re.search(rf"({months})\s+\d{{4}}|\b(19|20)\d{{2}}\b|present|current", text.lower()))


def _has_metric(text: str) -> bool:
    return bool(re.search(r"(\d+%|\$\d+|\b\d+[kKmM]?\b|x\b|times\b)", text))


def _meaningful_lines(text: str) -> list[str]:
    return [line.strip(" \t-*•") for line in text.splitlines() if line.strip(" \t-*•")]


def _has_proficiency(text: str) -> bool:
    return bool(re.search(rf"\b({'|'.join(sorted(PROFICIENCY_TERMS))})\b", text.lower()))


def _detected_terms(text: str, limit: int = 8) -> list[str]:
    detected: list[str] = []
    for term in TECHNICAL_TERMS:
        if term in detected:
            continue
        if _contains_keyword(text, term) or re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", text.lower()):
            detected.append(term)
        if len(detected) >= limit:
            break
    return detected


def _dedupe_texts(items: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = re.sub(r"\s+", " ", item.strip().lower())
        if item and normalized not in seen:
            deduped.append(item)
            seen.add(normalized)
    return deduped


def _has_production_evidence(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in PRODUCTION_EVIDENCE_TERMS)


def _contains_unsupported_production_assumption(review_text: str, resume_text: str) -> bool:
    lower = review_text.lower()
    if not any(term in lower for term in PRODUCTION_ASSUMPTION_TERMS):
        return False
    return not _has_production_evidence(resume_text)


def _section_evidence_floor(key: str, current_text: str) -> int:
    if not current_text.strip():
        return 0

    lines = _meaningful_lines(current_text)
    lower = current_text.lower()
    detected_terms = _detected_terms(current_text, limit=20)

    if key == "languages":
        return 88 if _has_proficiency(current_text) else 74

    if key == "certifications":
        has_certificate_signal = bool(
            re.search(
                r"\b(certificate|certification|certified|course|training|nptel|coursera|udemy|aws|azure|google|microsoft|by|from)\b",
                lower,
            )
        )
        if len(lines) >= 2 or has_certificate_signal:
            return 82

    if key == "education":
        has_degree = bool(re.search(r"\b(bachelor|master|diploma|degree|b\.?tech|m\.?tech|bsc|msc|mba|school|university|college)\b", lower))
        if has_degree and _has_date(current_text):
            return 85

    if key == "skills":
        if len(detected_terms) >= 6 or any(marker in lower for marker in ["tools", "databases", "soft skills", "languages"]):
            return 82
        if len(detected_terms) >= 3:
            return 74

    if key == "projects":
        if _has_metric(current_text) and len(detected_terms) >= 2:
            return 82
        if len(lines) >= 2 and detected_terms:
            return 75

    return 0


def _positive_improvement_for_section(key: str, current_text: str) -> str:
    if key == "languages" and _has_proficiency(current_text):
        return "Pretty good. No change required; the section already names each language with proficiency."
    if key == "certifications":
        return "Pretty good. Keep the certificate names unchanged; add dates or credential IDs only when available."
    if key == "education":
        return "Pretty good. The education details are clear; add only role-relevant coursework if it is available."
    if key == "skills":
        return "Pretty good. Put the strongest role-matching skills first instead of adding proficiency labels to every skill."
    return "Pretty good. No rewrite is required unless you want a sharper version."


def _clean_section_improvements(key: str, current_text: str, improvements: list[str], score: int) -> list[str]:
    cleaned: list[str] = []
    for item in improvements:
        lower = item.lower()
        if key == "languages" and "level of proficiency" in lower and _has_proficiency(current_text):
            continue
        if key == "skills" and "level of proficiency" in lower:
            cleaned.append("Optional: put the strongest role-matching skills first instead of adding proficiency labels to every skill.")
            continue
        if key == "certifications" and ("more specific" in lower or "relevance to the role" in lower):
            cleaned.append("Optional: add completion dates or credential IDs where available; keep certificate names unchanged.")
            continue
        cleaned.append(item)

    if not cleaned and score >= 80:
        cleaned.append(_positive_improvement_for_section(key, current_text))
    return _dedupe_texts(cleaned)[:6]


def _mentioned_dates(text: str) -> list[date]:
    dates: list[date] = []
    for match in re.finditer(
        r"\b(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\s+((?:19|20)\d{2})\b",
        text,
        flags=re.IGNORECASE,
    ):
        month = MONTHS[match.group(1).lower()]
        dates.append(date(int(match.group(2)), month, 1))
    if not dates:
        for year in re.findall(r"\b((?:19|20)\d{2})\b", text):
            dates.append(date(int(year), 1, 1))
    return dates


def _is_false_future_date_claim(text: str, review_date: date | None = None) -> bool:
    if "future" not in text.lower():
        return False
    actual_review_date = review_date or _review_date()
    dates = _mentioned_dates(text)
    return bool(dates) and all(item <= actual_review_date for item in dates)


def _valid_review_text(text: str, review_date: date | None = None) -> bool:
    return bool(_string(text)) and not _is_false_future_date_claim(text, review_date)


def _section_preview(sections: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"key": key, "name": DISPLAY_NAMES.get(key, key.title()), "text": value[:2200]}
        for key, value in sections.items()
        if value
    ]


def _evidence_hints(file_name: str, text: str, target_role: str | None) -> dict[str, Any]:
    sections = _extract_sections(text)
    role_keywords = _role_keyword_bucket(target_role)
    found_keywords = [keyword for keyword in role_keywords if _contains_keyword(text, keyword)]
    missing_keywords = [keyword for keyword in role_keywords if keyword not in found_keywords]
    return {
        "fileName": file_name,
        "targetRole": target_role or None,
        "sectionsDetected": list(sections.keys()),
        "sectionPreview": _section_preview(sections),
        "roleKeywordHints": role_keywords,
        "roleKeywordsDetected": found_keywords,
        "roleKeywordGapsByLiteralScan": missing_keywords,
        "generalSignals": {
            "emailDetected": bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)),
            "phoneDetected": bool(re.search(r"(\+?\d[\d\s().-]{8,}\d)", text)),
            "dateDetected": _has_date(text),
            "metricDetected": _has_metric(text),
            "containsMernStack": bool(re.search(r"\bmern(?:\s+stack)?\b", text, re.I)),
        },
    }


def _normalize_section_analysis(
    raw_items: Any,
    sections: dict[str, str],
    review_date: date | None = None,
    target_role: str | None = None,
) -> list[dict[str, Any]]:
    normalized = []
    used_keys: set[str] = set()
    for raw in _list(raw_items):
        if not isinstance(raw, dict):
            continue
        key = _string(raw.get("key")).lower()
        if key not in DISPLAY_NAMES:
            key = _normalize_key(_string(raw.get("name"))) or key
        name = _string(raw.get("name"), DISPLAY_NAMES.get(key, "Section"))
        current_text = _string(raw.get("currentText"), sections.get(key, ""))
        strengths = [_string(item) for item in _list(raw.get("strengths")) if _valid_review_text(_string(item), review_date)][:6]
        improvements = [_string(item) for item in _list(raw.get("improvements")) if _valid_review_text(_string(item), review_date)][:6]
        basis = [_string(item) for item in _list(raw.get("basis")) if _valid_review_text(_string(item), review_date)][:6]
        rewrites = []
        for item in _list(raw.get("rewriteSuggestions")):
            if not isinstance(item, dict):
                continue
            current = _string(item.get("currentText"))
            suggested = _string(item.get("suggestedText"))
            reason = _string(item.get("reason"))
            combined_claim = " ".join([current, suggested, reason])
            if (
                current
                and suggested
                and not _is_false_future_date_claim(combined_claim, review_date)
                and not _contains_unsupported_production_assumption(combined_claim, "\n".join(sections.values()))
            ):
                suggestion_type = _string(item.get("type"), "line").lower()
                if suggestion_type not in {"line", "paragraph", "section"}:
                    suggestion_type = "paragraph" if "\n" in current or len(current.split()) > 35 else "line"
                rewrites.append(
                    {
                        "type": suggestion_type,
                        "currentText": current,
                        "suggestedText": suggested,
                        "reason": reason,
                    }
                )
        raw_score = max(0, min(100, int(float(raw.get("score", 0) or 0))))
        status_text = _string(raw.get("status"), "Reviewed")
        positive_review_text = " ".join([status_text, *strengths, *improvements, *basis]).lower()
        says_no_change = any(
            phrase in positive_review_text
            for phrase in [
                "pretty good",
                "no change",
                "clear and complete",
                "well-formatted",
                "well formatted",
                "all essential",
                "good overview",
                "some evidence",
            ]
        )
        if 0 < raw_score <= 10 and current_text and (key in SUPPORTING_SECTIONS or says_no_change or raw_score >= 6):
            raw_score *= 10
        evidence_floor = _section_evidence_floor(key, current_text)
        if evidence_floor and raw_score < evidence_floor:
            raw_score = evidence_floor
        if raw_score <= 10 and says_no_change:
            raw_score = 90
        elif raw_score < 70 and says_no_change and not rewrites:
            raw_score = 85
        improvements = _clean_section_improvements(key, current_text, improvements, raw_score)
        status_text = "Pretty good" if raw_score >= 80 else "Needs polish" if raw_score >= 60 else "Needs attention"
        normalized.append(
            {
                "key": key or name.lower().replace(" ", "_"),
                "name": name,
                "score": raw_score,
                "status": status_text,
                "currentText": current_text,
                "strengths": strengths,
                "improvements": improvements,
                "basis": basis,
                "rewriteSuggestions": rewrites[:5],
            }
        )
        used_keys.add(key)
    for key in ["summary", "experience", "projects", "skills", "education", "certifications"]:
        if key in sections and key not in used_keys:
            normalized.append(
                {
                    "key": key,
                    "name": DISPLAY_NAMES[key],
                    "score": 70,
                    "status": "Reviewed",
                    "currentText": sections[key],
                    "strengths": [],
                    "improvements": ["The reviewer did not provide a specific change for this section."],
                    "basis": ["Section text was detected in the parsed resume."],
                    "rewriteSuggestions": [],
                }
            )
    return normalized


def _normalize_missing_information(raw_items: Any, resume_text: str, review_date: date | None = None) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    email_detected = bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", resume_text))
    phone_detected = bool(re.search(r"(\+?\d[\d\s().-]{8,}\d)", resume_text))
    professional_link_detected = bool(re.search(r"\b(linkedin|github|portfolio|https?://|www\.)\b", resume_text, re.I))

    for item in _list(raw_items):
        if not isinstance(item, dict):
            continue
        label = _string(item.get("label"), "Missing information")
        severity = _string(item.get("severity"), "medium")
        reason = _string(item.get("reason"))
        combined = f"{label} {reason}"
        lower = combined.lower()
        if not _valid_review_text(reason, review_date):
            continue
        if _contains_unsupported_production_assumption(combined, resume_text):
            continue
        if any(term in lower for term in ["specific metric", "specific metrics", "business impact", "impact of the project"]):
            continue
        if "contact" in lower and email_detected and phone_detected and professional_link_detected:
            continue
        if any(phrase in lower for phrase in ["always a good idea", "would be helpful", "could include"]) and any(
            optional_term in lower for optional_term in ["github", "portfolio", "website", "users", "impact", "metrics"]
        ):
            continue

        normalized.append({"label": label, "severity": severity, "reason": reason})

    return normalized[:8]


def _normalize_agent_payload(
    payload: dict[str, Any],
    file_name: str,
    text: str,
    target_role: str | None,
    review_date: date | None = None,
) -> dict[str, Any]:
    actual_review_date = review_date or _review_date()
    sections = _extract_sections(text)
    role_keywords = _role_keyword_bucket(target_role)
    found_keywords = [keyword for keyword in role_keywords if _contains_keyword(text, keyword)]
    missing_keywords = [keyword for keyword in role_keywords if keyword not in found_keywords]
    section_analyses = _normalize_section_analysis(payload.get("sectionAnalyses"), sections, actual_review_date, target_role)
    ats_score = max(0, min(100, float(payload.get("atsScore") or payload.get("overallResumeScore") or 0)))
    keyword_score = max(0, min(100, float(payload.get("keywordScore") or 0)))
    section_scores = [float(item["score"]) for item in section_analyses if item.get("currentText")]
    section_average = round(sum(section_scores) / len(section_scores), 2) if section_scores else 0
    if section_average and ats_score < section_average - 15:
        ats_score = section_average
    if not target_role and section_average and keyword_score < 40:
        keyword_score = max(keyword_score, min(75, section_average))
    overall = max(
        0,
        min(
            100,
            float(payload.get("overallResumeScore") or round(ats_score * (0.8 if not target_role else 0.65) + keyword_score * (0.2 if not target_role else 0.35), 2)),
        ),
    )
    if section_average and overall < section_average - 20:
        overall = round(ats_score * (0.8 if not target_role else 0.65) + keyword_score * (0.2 if not target_role else 0.35), 2)

    keyword_payload = payload.get("keywords") if isinstance(payload.get("keywords"), dict) else {}
    agent_found = [_string(item) for item in _list(keyword_payload.get("found")) if _string(item)]
    agent_missing = [_string(item) for item in _list(keyword_payload.get("missing")) if _string(item)]
    combined_found = []
    for item in [*agent_found, *found_keywords]:
        if item and item.lower() not in {existing.lower() for existing in combined_found}:
            combined_found.append(item)
    found_keyword_names = {item.lower() for item in combined_found}
    filtered_missing = [
        item
        for item in (agent_missing or missing_keywords)
        if item.lower() not in found_keyword_names and not _contains_keyword(text, item)
    ]

    return {
        "targetRole": target_role or None,
        "roleSpecific": bool(target_role),
        "atsScore": ats_score,
        "keywordScore": keyword_score,
        "overallResumeScore": overall,
        "scoreBasis": {
            "atsScore": _string(
                (payload.get("scoreBasis") or {}).get("atsScore") if isinstance(payload.get("scoreBasis"), dict) else "",
                "ATS score reflects human-style review of section clarity, completeness, formatting, evidence, and role relevance. Dates are used only to understand timeline clarity.",
            ),
            "keywordScore": _string(
                (payload.get("scoreBasis") or {}).get("keywordScore") if isinstance(payload.get("scoreBasis"), dict) else "",
                "Keyword score reflects role-relevant wording found in the resume. It is not a demand to learn every missing item.",
            ),
            "overallResumeScore": _string(
                (payload.get("scoreBasis") or {}).get("overallResumeScore") if isinstance(payload.get("scoreBasis"), dict) else "",
                "Overall score combines resume quality, evidence, and role fit.",
            ),
        },
        "marketSummary": _string(payload.get("marketSummary")),
        "keywords": {
            "expected": role_keywords,
            "found": combined_found,
            "missing": filtered_missing,
            "coverage": keyword_score,
            "explanation": _string(
                keyword_payload.get("explanation"),
                "Skills are treated as wording signals. Abbreviations such as MERN Stack count for the technologies they imply.",
            ),
        },
        "sectionAnalyses": section_analyses,
        "missingInformation": _normalize_missing_information(payload.get("missingInformation"), text, actual_review_date),
        "suggestions": [
            {
                "section": _string(item.get("section"), "Resume"),
                "type": _string(item.get("type"), "review"),
                "suggested": _string(item.get("suggested")),
                "reason": _string(item.get("reason")),
            }
            for item in _list(payload.get("suggestions"))
            if isinstance(item, dict)
            and _valid_review_text(_string(item.get("suggested")), actual_review_date)
            and _valid_review_text(_string(item.get("reason")), actual_review_date)
        ],
        "formatIssues": [_string(item) for item in _list(payload.get("formatIssues")) if _valid_review_text(_string(item), actual_review_date)],
        "missingSkills": [
            item
            for item in filtered_missing
            if item
        ],
        "generationProvider": _string(payload.get("generationProvider")),
    }


async def analyze_resume_text_with_agent(file_name: str, text: str, target_role: str | None = None) -> dict[str, Any]:
    cleaned_text = _clean_text(text)
    target = target_role.strip() if target_role and target_role.strip() else None
    actual_review_date = _review_date()
    hints = _evidence_hints(file_name, cleaned_text, target)
    response = await llm_service.invoke_live(
        [
            {
                "role": "system",
                "content": (
                    "You are a senior human resume reviewer. Review the resume like a careful recruiter, not like a template. "
                    "Use only evidence in the resume text. Return strict JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Analyze this resume and produce a human-quality, section-wise report.\n\n"
                    f"Current date for date reasoning: {actual_review_date.strftime('%B %d, %Y')}. "
                    "Any date before this is in the past. For example, Nov 2025 - Jan 2026 is not future on this date.\n\n"
                    "Rules:\n"
                    "- All scores must be on a 0-100 scale. If you mean seven out of ten, output 70, not 7.\n"
                    "- Do not use canned rewrites. Never prefix lines with a fixed verb like Delivered, Built, Led, etc.\n"
                    "- Do not rewrite certificate names, issuer names, locations, school names, company names, dates, or standalone titles as achievement bullets.\n"
                    "- Use your own judgment. For Summary and Projects, provide concrete rewrite suggestions when they materially improve clarity or role fit, but do not force a template onto already strong lines.\n"
                    "- Recognize section heading variants such as EDUCATIONS, CERTIFICATES, CERTIFICATIONS, PROJECT, PROJECTS, SKILLS.\n"
                    "- Recognize common abbreviations. MERN Stack implies MongoDB, Express, React, and Node. REST APIs implies API experience. MySQL implies SQL/database.\n"
                    "- Languages, education, and certifications are supporting sections. Do not score them below 70 when they are parseable and contain normal expected details. Native/fluent language proficiency is already specific.\n"
                    "- Date reasoning must be precise. Do not call a date future unless it is after the current date above.\n"
                    "- Dates should not lower the resume score by themselves. Use dates only to understand timeline clarity. Mention dates neutrally unless a date is truly impossible, contradictory, or after the current date above.\n"
                    "- When no target role is provided, score the resume as a general resume. Do not punish it for missing role-specific keywords. In general mode, strong complete sections should receive strong section scores.\n"
                    "- Do not mark React or Node missing when MERN Stack is present, unless the selected role requires unusually deep explicit React/Node evidence and you explain that nuance.\n"
                    "- Missing information should include only general resume gaps such as contact info, dates, education, experience/projects, links, or unclear timeline.\n"
                    "- Role-specific skill gaps should appear only when a target role is provided, and only if the gap is relevant and not already implied by abbreviations.\n"
                    "- For line-level suggestions, only suggest changes for lines that are actually weak. Preserve the user's facts. Do not invent metrics, tools, companies, or outcomes.\n"
                    "- Do not ask for users, customer impact, production readiness, publishing, deployment, or business impact unless the resume explicitly says the project was used, shipped, deployed, published, or production-ready.\n"
                    "- If a machine-learning project already reports accuracy, optional project improvements should focus on dataset size, validation split, baseline, precision/recall/F1, or model objective. Do not imply missing users or production adoption.\n"
                    "- Suggestion granularity rule: if a paragraph has more than one weak sentence or more than two lines need changes, return one paragraph-level rewrite suggestion for the full paragraph. Do not also return separate line suggestions for that same paragraph.\n"
                    "- If only one bullet, project line, or experience line needs improvement, return one line-level suggestion for that exact line only. Do not create a paragraph suggestion for a single-line issue.\n"
                    "- Use rewriteSuggestions.type = \"paragraph\" for full paragraph replacements, \"line\" for individual bullet/line replacements, and \"section\" only when an entire short section needs replacement.\n"
                    "- For certifications and education, usually evaluate clarity/completeness rather than asking for achievement-style rewrites.\n\n"
                    "Return this exact JSON shape:\n"
                    "{\n"
                    '  "atsScore": 0,\n'
                    '  "keywordScore": 0,\n'
                    '  "overallResumeScore": 0,\n'
                    '  "scoreBasis": {"atsScore": "basis", "keywordScore": "basis", "overallResumeScore": "basis"},\n'
                    '  "marketSummary": "role/general market-fit summary",\n'
                    '  "keywords": {"found": ["skill"], "missing": ["skill"], "explanation": "explain keyword score"},\n'
                    '  "missingInformation": [{"label": "general missing item", "severity": "low|medium|high", "reason": "why"}],\n'
                    '  "sectionAnalyses": [{"key": "summary|experience|projects|skills|education|certifications|achievements|languages", "name": "Section", "score": 0, "status": "Pretty good|Needs polish|Needs attention", "currentText": "text from resume", "strengths": ["specific"], "improvements": ["specific or no change needed"], "basis": ["why score"], "rewriteSuggestions": [{"type": "line|paragraph|section", "currentText": "exact line or paragraph", "suggestedText": "paraphrased replacement", "reason": "why"}]}],\n'
                    '  "suggestions": [{"section": "Section", "type": "keep|modify|add|remove", "suggested": "specific", "reason": "why"}],\n'
                    '  "formatIssues": ["issue"]\n'
                    "}\n\n"
                    f"Target role: {target or 'General resume review'}\n\n"
                    f"Parser hints JSON:\n{json.dumps(hints, ensure_ascii=False)}\n\n"
                    f"Resume text:\n{cleaned_text[:16000]}"
                ),
            },
        ],
        agent="resume",
    )
    payload = _json_from_text(response.content)
    normalized = _normalize_agent_payload(payload, file_name, cleaned_text, target, actual_review_date)
    normalized["generationProvider"] = response.provider
    return normalized


def analyze_resume_text(file_name: str, text: str, target_role: str | None = None) -> dict[str, Any]:
    """Small deterministic smoke path for tests; the product route uses the live resume agent."""

    cleaned_text = _clean_text(text)
    target = target_role.strip() if target_role and target_role.strip() else None
    role_keywords = _role_keyword_bucket(target)
    found = [keyword for keyword in role_keywords if _contains_keyword(cleaned_text, keyword)]
    keyword_score = round((len(found) / max(len(role_keywords), 1)) * 100, 2) if role_keywords else 0
    ats_score = min(90, 60 + len(found) * 4 + (10 if _has_metric(cleaned_text) else 0))
    return {
        "targetRole": target,
        "roleSpecific": bool(target),
        "atsScore": float(ats_score),
        "keywordScore": float(keyword_score),
        "overallResumeScore": round(ats_score * 0.65 + keyword_score * 0.35, 2),
        "scoreBasis": {
            "atsScore": "Smoke-test score based on parseable content and detected role keywords. Dates are not part of this score.",
            "keywordScore": "Detected role keyword coverage for tests.",
            "overallResumeScore": "Combined smoke-test score.",
        },
        "marketSummary": "",
        "keywords": {"expected": role_keywords, "found": found, "missing": [], "coverage": keyword_score, "explanation": ""},
        "sectionAnalyses": [],
        "missingInformation": [],
        "suggestions": [],
        "formatIssues": [],
        "missingSkills": [],
    }
