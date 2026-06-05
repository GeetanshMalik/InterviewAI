from __future__ import annotations

import hashlib
import re
from typing import Any

from services.context import clean_text, extract_skills, infer_domain, resume_snippets


_summary_cache: dict[str, dict[str, Any]] = {}


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _sentences(text: str) -> list[str]:
    return [
        clean_text(sentence, 360)
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or "")
        if len(clean_text(sentence, 360)) >= 24
    ]


def _score_sentence(sentence: str, terms: list[str]) -> int:
    normalized = sentence.lower()
    score = sum(3 for term in terms if term and term.lower() in normalized)
    score += sum(
        1
        for cue in [
            "built",
            "designed",
            "developed",
            "implemented",
            "led",
            "owned",
            "optimized",
            "scaled",
            "reduced",
            "improved",
            "project",
            "api",
            "database",
            "system",
            "model",
        ]
        if cue in normalized
    )
    return score


def _ranked_snippets(text: str, terms: list[str], *, limit: int, chars: int) -> list[str]:
    ranked = sorted(
        ((_score_sentence(sentence, terms), sentence) for sentence in _sentences(text)),
        key=lambda item: item[0],
        reverse=True,
    )
    snippets = [sentence[:chars] for score, sentence in ranked if score > 0][:limit]
    if snippets:
        return snippets
    return [sentence[:chars] for sentence in _sentences(text)[:limit]]


def summarize_resume(resume_text: str, *, role: str = "", skills: list[str] | None = None) -> dict[str, Any]:
    cache_key = f"resume:{_stable_hash('|'.join([role, ','.join(skills or []), resume_text or '']))}"
    if cache_key in _summary_cache:
        return dict(_summary_cache[cache_key])
    skill_terms = extract_skills(role, skills or [], resume_text, "")
    snippets = resume_snippets(resume_text, skill_terms, limit=5) or _ranked_snippets(
        resume_text,
        [role, *skill_terms],
        limit=5,
        chars=280,
    )
    summary = {
        "hash": _stable_hash(resume_text or ""),
        "skills": skill_terms[:10],
        "domain": infer_domain(role, skill_terms, resume_text),
        "snippets": snippets[:5],
        "summary": clean_text(" ".join(snippets[:4]), 900),
        "raw_chars": len(resume_text or ""),
    }
    _summary_cache[cache_key] = dict(summary)
    return summary


def summarize_job_description(job_description: str, *, role: str = "", skills: list[str] | None = None) -> dict[str, Any]:
    cache_key = f"job_description:{_stable_hash('|'.join([role, ','.join(skills or []), job_description or '']))}"
    if cache_key in _summary_cache:
        return dict(_summary_cache[cache_key])
    skill_terms = extract_skills(role, skills or [], "", job_description)
    snippets = _ranked_snippets(job_description, [role, *skill_terms], limit=5, chars=260)
    summary = {
        "hash": _stable_hash(job_description or ""),
        "skills": skill_terms[:10],
        "domain": infer_domain(role, skill_terms, job_description),
        "requirements": snippets[:5],
        "summary": clean_text(" ".join(snippets[:4]), 850),
        "raw_chars": len(job_description or ""),
    }
    _summary_cache[cache_key] = dict(summary)
    return summary


def _compact_memory_item(item: dict[str, Any], *, chars: int = 420) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "type": metadata.get("memory_type") or item.get("memory_type") or metadata.get("type") or "memory",
        "sourceId": item.get("source_id") or metadata.get("source_id") or item.get("id"),
        "text": clean_text(str(item.get("text") or item.get("excerpt") or item.get("content") or ""), chars),
        "score": item.get("score") or item.get("distance"),
    }


def compact_memory_items(items: list[dict[str, Any]] | None, *, limit: int = 4, chars: int = 420) -> list[dict[str, Any]]:
    return [_compact_memory_item(item, chars=chars) for item in (items or [])[:limit] if isinstance(item, dict)]


def ensure_interview_memory(interview: dict[str, Any]) -> dict[str, Any]:
    """Build and cache compact memory layers on the interview dict.

    The raw resume/JD stay in persistence for audit and future extraction, but agents receive this
    compact shared-memory view unless a task explicitly needs raw text.
    """

    role = str(interview.get("target_role") or "Software Engineer")
    skills = [str(skill) for skill in interview.get("skills", []) if str(skill).strip()]
    resume_text = str(interview.get("resume_text") or "")
    job_description = str(interview.get("job_description") or "")
    cache_key = _stable_hash("|".join([role, ",".join(skills), resume_text, job_description]))
    existing = interview.get("_shared_memory")
    if isinstance(existing, dict) and existing.get("cacheKey") == cache_key:
        return existing

    resume_summary = summarize_resume(resume_text, role=role, skills=skills)
    jd_summary = summarize_job_description(job_description, role=role, skills=skills)
    merged_skills = sorted({*skills, *resume_summary.get("skills", []), *jd_summary.get("skills", [])})[:12]
    shared = {
        "cacheKey": cache_key,
        "short_term_memory": {
            "role": role,
            "difficulty": interview.get("difficulty", "medium"),
            "company_style": interview.get("company_style", "general"),
            "preferred_language": interview.get("preferred_language", "javascript"),
            "skills": merged_skills,
            "domain": infer_domain(role, merged_skills, f"{resume_summary.get('summary', '')} {jd_summary.get('summary', '')}"),
        },
        "summarized_memory": {
            "resume": resume_summary,
            "job_description": jd_summary,
        },
        "retrieval_memory": {
            "query": clean_text(" ".join([role, *merged_skills, jd_summary.get("summary", "")]), 700),
            "resume_snippets": resume_summary.get("snippets", [])[:4],
            "jd_requirements": jd_summary.get("requirements", [])[:4],
        },
    }
    interview["_shared_memory"] = shared
    return shared


def rolling_summary(items: list[Any] | None, *, limit: int = 6, chars: int = 700) -> list[dict[str, str]]:
    summary = []
    for item in (items or [])[-limit:]:
        if isinstance(item, dict):
            summary.append(
                {
                    "agent": clean_text(str(item.get("agent") or item.get("type") or "agent"), 80),
                    "type": clean_text(str(item.get("type") or item.get("entry_type") or ""), 80),
                    "summary": clean_text(str(item.get("summary") or item.get("decision") or item.get("recommendation") or item), chars),
                }
            )
        else:
            summary.append({"agent": "system", "type": "note", "summary": clean_text(str(item), chars)})
    return summary


def compact_agent_context(
    interview: dict[str, Any],
    *,
    agent: str,
    section: str | None = None,
    retrieved_memory: list[dict[str, Any]] | None = None,
    collaboration_transcript: list[Any] | None = None,
    generation_history: list[dict[str, Any]] | None = None,
    practice_history: list[dict[str, Any]] | None = None,
    reflection_feedback: list[dict[str, Any]] | None = None,
    interview_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    shared = ensure_interview_memory(interview)
    short = dict(shared["short_term_memory"])
    summarized = shared["summarized_memory"]
    retrieval = shared["retrieval_memory"]
    agent_key = agent.lower()

    context: dict[str, Any] = {
        "cacheKey": shared.get("cacheKey"),
        "task": {"agent": agent, "section": section},
        "short_term_memory": short,
        "summarized_memory": {},
        "retrieval_memory": {
            "query": retrieval.get("query", ""),
            "memories": compact_memory_items(retrieved_memory, limit=4, chars=360),
        },
    }

    if "dsa" in agent_key:
        context["summarized_memory"] = {
            "role": short["role"],
            "skills": short["skills"][:8],
            "job_requirements": summarized["job_description"].get("requirements", [])[:3],
        }
    elif "aptitude" in agent_key:
        context["summarized_memory"] = {
            "role": short["role"],
            "domain": short["domain"],
            "job_summary": summarized["job_description"].get("summary", "")[:500],
        }
    elif "technical" in agent_key:
        context["summarized_memory"] = {
            "resume_summary": summarized["resume"].get("summary", ""),
            "resume_snippets": summarized["resume"].get("snippets", [])[:4],
            "job_requirements": summarized["job_description"].get("requirements", [])[:4],
        }
    elif "hr" in agent_key:
        context["summarized_memory"] = {
            "resume_summary": summarized["resume"].get("summary", "")[:700],
            "resume_snippets": summarized["resume"].get("snippets", [])[:5],
            "job_summary": summarized["job_description"].get("summary", "")[:600],
        }
    else:
        context["summarized_memory"] = {
            "resume_summary": summarized["resume"].get("summary", "")[:800],
            "job_summary": summarized["job_description"].get("summary", "")[:700],
        }

    if interview_plan:
        context["interview_plan"] = {
            "focus_topics": interview_plan.get("focus_topics", [])[:8],
            "difficulty_distribution": interview_plan.get("difficulty_distribution", {}),
            "technical_strategy": clean_text(str(interview_plan.get("technical_strategy", "")), 500),
            "hr_strategy": clean_text(str(interview_plan.get("hr_strategy", "")), 500),
            "memory_strategy": clean_text(str(interview_plan.get("memory_strategy", "")), 500),
            "adaptation_rules": [clean_text(str(item), 220) for item in interview_plan.get("adaptation_rules", [])[:6]],
            "generation_strategy_by_section": interview_plan.get("generation_strategy_by_section", {}),
        }
    if collaboration_transcript:
        context["collaboration_summary"] = rolling_summary(collaboration_transcript, limit=5, chars=420)
    if generation_history:
        compact_history: list[dict[str, Any]] = []
        for item in generation_history:
            if not isinstance(item, dict):
                continue
            sections = item.get("sections")
            if isinstance(sections, list):
                for section_summary in sections:
                    if not isinstance(section_summary, dict):
                        continue
                    for sample in section_summary.get("samples", [])[:4]:
                        if not isinstance(sample, dict):
                            continue
                        compact_history.append(
                            {
                                "section": section_summary.get("section"),
                                "topic": clean_text(str(sample.get("topic") or ""), 120),
                                "question": clean_text(str(sample.get("question_text") or sample.get("title") or ""), 280),
                            }
                        )
                        if len(compact_history) >= 8:
                            break
                    if len(compact_history) >= 8:
                        break
            else:
                compact_history.append(
                    {
                        "section": item.get("section"),
                        "topic": clean_text(str(item.get("topic") or ""), 120),
                        "question": clean_text(str(item.get("question") or item.get("title") or item), 280),
                    }
                )
            if len(compact_history) >= 8:
                break
        context["generation_history"] = compact_history
    if practice_history:
        context["practice_summary"] = rolling_summary(practice_history, limit=3, chars=360)
    if reflection_feedback:
        context["reflection_feedback"] = [
            {
                "section": item.get("section"),
                "decision": item.get("decision"),
                "requiredCorrections": [clean_text(str(text), 220) for text in item.get("requiredCorrections", [])[:5]],
                "validationErrors": [clean_text(str(text), 180) for text in item.get("validationErrors", [])[:5]],
            }
            for item in reflection_feedback[:4]
            if isinstance(item, dict)
        ]
    return context
