from __future__ import annotations

import hashlib
import random
import re
from typing import Any


SKILL_ALIASES = {
    "python": ["python", "django", "fastapi", "flask", "pandas"],
    "javascript": ["javascript", "js", "node", "node.js", "express"],
    "typescript": ["typescript", "ts", "next.js", "nextjs"],
    "react": ["react", "redux", "frontend", "front-end"],
    "sql": ["sql", "postgres", "postgresql", "mysql", "database"],
    "cloud": ["aws", "azure", "gcp", "cloud", "docker", "kubernetes"],
    "data": ["machine learning", "ml", "data", "analytics", "pandas", "tensorflow"],
    "mobile": ["android", "ios", "react native", "flutter", "mobile"],
    "security": ["security", "auth", "oauth", "jwt", "encryption"],
}


def clean_text(value: str | None, limit: int = 4000) -> str:
    if not value:
        return ""
    collapsed = re.sub(r"\s+", " ", value).strip()
    return collapsed[:limit]


def stable_random(*parts: Any) -> random.Random:
    raw = "|".join(clean_text(str(part), 1000) for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def infer_domain(role: str, skills: list[str] | None = None, text: str = "") -> str:
    haystack = " ".join([role, *(skills or []), text]).lower()
    if any(term in haystack for term in ["frontend", "front-end", "react", "next", "ui", "web"]):
        return "frontend"
    if any(term in haystack for term in ["data", "machine learning", "ml", "analytics", "scientist"]):
        return "data"
    if any(term in haystack for term in ["android", "ios", "mobile", "flutter", "react native"]):
        return "mobile"
    if any(term in haystack for term in ["devops", "cloud", "platform", "sre", "kubernetes"]):
        return "platform"
    if any(term in haystack for term in ["security", "auth", "iam", "compliance"]):
        return "security"
    if any(term in haystack for term in ["backend", "back-end", "api", "distributed", "microservice"]):
        return "backend"
    return "general"


def extract_skills(role: str, skills: list[str] | None, resume_text: str = "", job_description: str = "") -> list[str]:
    found = {skill.strip().lower() for skill in skills or [] if skill.strip()}
    haystack = f"{role} {resume_text} {job_description}".lower()
    for canonical, aliases in SKILL_ALIASES.items():
        if any(alias in haystack for alias in aliases):
            found.add(canonical)
    return sorted(found)[:8]


def resume_snippets(resume_text: str, skills: list[str] | None = None, limit: int = 4) -> list[str]:
    if not resume_text:
        return []
    terms = [term.lower() for term in skills or []]
    sentences = re.split(r"(?<=[.!?])\s+|\n+", resume_text)
    scored: list[tuple[int, str]] = []
    for sentence in sentences:
        cleaned = clean_text(sentence, 280)
        if len(cleaned) < 25:
            continue
        normalized = cleaned.lower()
        score = sum(2 for term in terms if term and term in normalized)
        score += sum(1 for cue in ["built", "led", "created", "improved", "reduced", "designed", "developed", "project"] if cue in normalized)
        if score:
            scored.append((score, cleaned))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [sentence for _, sentence in scored[:limit]]


def build_profile(
    role: str,
    difficulty: str = "medium",
    company_style: str = "general",
    skills: list[str] | None = None,
    resume_text: str = "",
    job_description: str = "",
) -> dict[str, Any]:
    skill_hints = extract_skills(role, skills, resume_text, job_description)
    context_text = clean_text(f"{resume_text} {job_description}", 3000)
    return {
        "role": role or "Software Engineer",
        "difficulty": difficulty or "medium",
        "company_style": company_style or "general",
        "skills": skill_hints,
        "domain": infer_domain(role, skill_hints, context_text),
        "resume_snippets": resume_snippets(resume_text, skill_hints),
        "job_description": clean_text(job_description, 900),
        "resume_text": clean_text(resume_text, 1500),
    }


def human_list(items: list[str], fallback: str = "your current stack") -> str:
    if not items:
        return fallback
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f", and {items[-1]}"
