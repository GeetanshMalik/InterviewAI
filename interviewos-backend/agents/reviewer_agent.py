from __future__ import annotations

import hashlib
import json
from typing import Any

from config import settings
from services.llm import llm_service
from utils.parsers import json_from_text


def _review_mode_allows(subject_id: str, deterministic_errors: list[str]) -> bool:
    mode = str(settings.qualitative_review_mode or "always").strip().lower()
    if mode == "off":
        return bool(deterministic_errors)
    if mode == "sampled" and not deterministic_errors:
        digest = hashlib.sha256(subject_id.encode("utf-8")).hexdigest()
        return int(digest[:2], 16) % 4 == 0
    return True


def _normalize_review(payload: dict[str, Any], deterministic_errors: list[str], *, artifact: str, provider: str, model: str, fallback: bool) -> dict[str, Any]:
    quality_errors = [str(item).strip() for item in payload.get("qualityErrors", []) if str(item).strip()]
    repair_instructions = [
        str(item).strip()
        for item in payload.get("repairInstructions", [])
        if str(item).strip()
    ]
    accepted = bool(payload.get("accepted", not quality_errors))
    if deterministic_errors:
        accepted = False
    return {
        "agent": "Reviewer Agent",
        "artifact": artifact,
        "accepted": accepted,
        "deterministicErrors": deterministic_errors,
        "qualityErrors": quality_errors,
        "repairInstructions": repair_instructions,
        "summary": str(payload.get("summary") or "").strip()[:700],
        "provider": provider,
        "model": model,
        "fallbackUsed": fallback,
        "decision": "accept" if accepted else "repair",
    }


def _compact_candidate_for_review(candidate_profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_role": candidate_profile.get("target_role"),
        "difficulty": candidate_profile.get("difficulty"),
        "company_style": candidate_profile.get("company_style"),
        "skills": candidate_profile.get("skills", [])[:8],
        "resume_summary": str(candidate_profile.get("resume_summary") or candidate_profile.get("resume_text_excerpt") or "")[:500],
        "resume_snippets": candidate_profile.get("resume_snippets", [])[:3],
    }


def _compact_plan_for_review(interview_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "focus_topics": interview_plan.get("focus_topics", [])[:6],
        "difficulty_distribution": interview_plan.get("difficulty_distribution", {}),
        "technical_strategy": str(interview_plan.get("technical_strategy") or "")[:260],
        "hr_strategy": str(interview_plan.get("hr_strategy") or "")[:260],
        "review_depth": interview_plan.get("review_depth"),
    }


def _compact_items_for_review(items: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    compacted = []
    for item in items[:limit]:
        compacted.append(
            {
                "title": str(item.get("title") or "")[:120],
                "question_text": str(item.get("question_text") or item.get("description") or "")[:360],
                "difficulty": item.get("difficulty"),
                "category": item.get("category"),
                "resume_context_used": item.get("resume_context_used"),
            }
        )
    return compacted


def _compact_question_set_for_review(question_set: dict[str, Any]) -> dict[str, Any]:
    return {
        section: {
            "count": len(question_set.get(section, [])),
            "items": _compact_items_for_review(question_set.get(section, [])),
        }
        for section in ("dsa_problems", "aptitude_questions", "technical_questions", "hr_questions")
    }


def _fallback_generation_review(question_set: dict[str, Any], deterministic_errors: list[str]) -> dict[str, Any]:
    texts: list[str] = []
    for section in ["dsa_problems", "aptitude_questions", "technical_questions", "hr_questions"]:
        for item in question_set.get(section, []) or []:
            if isinstance(item, dict):
                texts.append(" ".join(str(item.get(key, "")) for key in ["title", "question", "prompt", "text"]))
    joined = " ".join(texts).lower()
    filled_texts = [text for text in texts if len(text.strip()) >= 10]
    quality_errors: list[str] = []
    if len(filled_texts) >= 3 and len(set(filled_texts)) < max(1, len(filled_texts) - 1):
        quality_errors.append("Generated questions contain duplicate or near-empty prompts.")
    generic_hits = sum(1 for phrase in ["tell me about yourself", "what are your strengths", "explain your project"] if phrase in joined)
    if generic_hits >= 2:
        quality_errors.append("Generated questions are too generic for the candidate-specific plan.")
    return {
        "accepted": not deterministic_errors and not quality_errors,
        "qualityErrors": quality_errors,
        "repairInstructions": [
            "Regenerate weak sections with resume/job-specific evidence and non-duplicative prompts."
        ]
        if quality_errors or deterministic_errors
        else [],
        "summary": "Deterministic qualitative fallback reviewed generated interview assets.",
    }


def _fallback_lifecycle_review(artifact: str, payload: dict[str, Any], deterministic_errors: list[str]) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False).lower()
    quality_errors: list[str] = []
    if artifact == "report" and not any(term in text for term in ["evidence", "weakness", "score", "round"]):
        quality_errors.append("Report lacks explicit evidence, weakness, score, or round alignment.")
    if artifact == "roadmap" and not any(term in text for term in ["practice", "milestone", "task", "weakness"]):
        quality_errors.append("Roadmap lacks concrete weakness-targeted practice tasks.")
    return {
        "accepted": not deterministic_errors and not quality_errors,
        "qualityErrors": quality_errors,
        "repairInstructions": ["Regenerate with concrete evidence, weaknesses, and actionable next steps."]
        if quality_errors or deterministic_errors
        else [],
        "summary": f"Deterministic qualitative fallback reviewed {artifact}.",
    }


async def review_interview_generation_quality(
    *,
    candidate_profile: dict[str, Any],
    interview_plan: dict[str, Any],
    question_set: dict[str, Any],
    deterministic_errors: list[str],
    attempt: int,
) -> dict[str, Any]:
    subject_id = f"generation:{candidate_profile.get('interview_id', '')}:{attempt}"
    if not _review_mode_allows(subject_id, deterministic_errors):
        return _normalize_review(
            {"accepted": not deterministic_errors, "summary": "Qualitative review skipped by mode."},
            deterministic_errors,
            artifact="interview_generation",
            provider="skipped",
            model=str(settings.qualitative_review_mode),
            fallback=True,
        )

    try:
        response = await llm_service.invoke_live(
            [
                {
                    "role": "system",
                    "content": (
                        "You are the InterviewOS Reviewer Agent. Review generated interview assets for "
                        "candidate specificity, role fit, difficulty fit, duplicates, and generic/nonsensical prompts. "
                        "Return only JSON with accepted, qualityErrors, repairInstructions, summary. "
                        "Do not include hidden reasoning."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "candidateProfile": _compact_candidate_for_review(candidate_profile),
                            "interviewPlan": _compact_plan_for_review(interview_plan),
                            "questionSet": _compact_question_set_for_review(question_set),
                            "deterministicErrors": deterministic_errors,
                        },
                        ensure_ascii=False,
                    )[:8000],
                },
            ],
            agent="evaluation",
        )
        payload = json_from_text(response.content, root_error="Reviewer response must be a JSON object.")
        return _normalize_review(payload, deterministic_errors, artifact="interview_generation", provider=response.provider, model=response.model, fallback=False)
    except Exception as exc:
        payload = _fallback_generation_review(question_set, deterministic_errors)
        payload["summary"] = f"{payload.get('summary', '')} LLM reviewer unavailable: {type(exc).__name__}."
        return _normalize_review(payload, deterministic_errors, artifact="interview_generation", provider="deterministic-reviewer", model="local-fallback", fallback=True)


async def review_lifecycle_artifact_quality(
    *,
    artifact: str,
    lifecycle_state: dict[str, Any],
    deterministic_errors: list[str],
) -> dict[str, Any]:
    subject_id = f"{artifact}:{(lifecycle_state.get('report') or {}).get('id', '')}:{len(deterministic_errors)}"
    if not _review_mode_allows(subject_id, deterministic_errors):
        return _normalize_review(
            {"accepted": not deterministic_errors, "summary": "Qualitative review skipped by mode."},
            deterministic_errors,
            artifact=artifact,
            provider="skipped",
            model=str(settings.qualitative_review_mode),
            fallback=True,
        )

    payload_for_review = {
        "artifact": artifact,
        "report": lifecycle_state.get("report", {}),
        "roadmap": lifecycle_state.get("roadmap", {}),
        "evaluationSummary": lifecycle_state.get("evaluation_summary", {}),
        "weaknessProfile": lifecycle_state.get("weakness_profile", {}),
        "deterministicErrors": deterministic_errors,
    }
    try:
        response = await llm_service.invoke_live(
            [
                {
                    "role": "system",
                    "content": (
                        "You are the InterviewOS Lifecycle Reviewer Agent. Review the artifact for evidence grounding, "
                        "weakness alignment, specificity, and actionability. Return only JSON with accepted, "
                        "qualityErrors, repairInstructions, summary. Do not include hidden reasoning."
                    ),
                },
                {"role": "user", "content": json.dumps(payload_for_review, ensure_ascii=False)[:16000]},
            ],
            agent="evaluation",
        )
        payload = json_from_text(response.content, root_error="Lifecycle reviewer response must be a JSON object.")
        return _normalize_review(payload, deterministic_errors, artifact=artifact, provider=response.provider, model=response.model, fallback=False)
    except Exception as exc:
        payload = _fallback_lifecycle_review(artifact, payload_for_review, deterministic_errors)
        payload["summary"] = f"{payload.get('summary', '')} LLM reviewer unavailable: {type(exc).__name__}."
        return _normalize_review(payload, deterministic_errors, artifact=artifact, provider="deterministic-reviewer", model="local-fallback", fallback=True)


async def review_section_generation_quality(
    *,
    section: str,
    agent: str,
    candidate_profile: dict[str, Any],
    interview_plan: dict[str, Any],
    items: list[dict[str, Any]],
    deterministic_errors: list[str],
    attempt: int,
) -> dict[str, Any]:
    subject_id = f"section:{section}:{candidate_profile.get('interview_id', '')}:{attempt}"
    if not _review_mode_allows(subject_id, deterministic_errors):
        return _normalize_review(
            {"accepted": not deterministic_errors, "summary": "Section qualitative review skipped by mode."},
            deterministic_errors,
            artifact=section,
            provider="skipped",
            model=str(settings.qualitative_review_mode),
            fallback=True,
        )

    try:
        response = await llm_service.invoke_live(
            [
                {
                    "role": "system",
                    "content": (
                        f"You are the InterviewOS {agent} self-reviewer. Review only the generated {section} output "
                        "for role fit, memory/plan alignment, duplicates, count/schema quality, and candidate specificity. "
                        "Return only JSON with accepted, qualityErrors, repairInstructions, summary. "
                        "Do not include hidden reasoning."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "section": section,
                            "candidateProfile": _compact_candidate_for_review(candidate_profile),
                            "interviewPlan": _compact_plan_for_review(interview_plan),
                            "items": _compact_items_for_review(items, limit=10),
                            "deterministicErrors": deterministic_errors,
                        },
                        ensure_ascii=False,
                    )[:7000],
                },
            ],
            agent="evaluation",
        )
        payload = json_from_text(response.content, root_error="Section reviewer response must be a JSON object.")
        return _normalize_review(payload, deterministic_errors, artifact=section, provider=response.provider, model=response.model, fallback=False)
    except Exception as exc:
        quality_errors: list[str] = []
        if deterministic_errors:
            quality_errors.extend(deterministic_errors)
        prompts = [
            " ".join(str(item.get(key, "")) for key in ["title", "description", "question_text", "question", "prompt"])
            for item in items
            if isinstance(item, dict)
        ]
        filled = [prompt for prompt in prompts if len(prompt.strip()) >= 10]
        if len(filled) >= 3 and len(set(filled)) < len(filled):
            quality_errors.append(f"{agent} generated duplicate or near-duplicate {section} prompts.")
        payload = {
            "accepted": not quality_errors,
            "qualityErrors": quality_errors,
            "repairInstructions": [
                f"Regenerate {section} with exact count, non-duplicative prompts, and stronger plan/memory grounding."
            ]
            if quality_errors
            else [],
            "summary": f"Deterministic section self-review completed. LLM reviewer unavailable: {type(exc).__name__}.",
        }
        return _normalize_review(payload, deterministic_errors, artifact=section, provider="deterministic-reviewer", model="local-fallback", fallback=True)
