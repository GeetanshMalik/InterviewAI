from __future__ import annotations

from typing import Any, Literal, TypedDict

from services.context import build_profile, clean_text
from services.context_memory import ensure_interview_memory
from services.store import iso_now


AgentName = Literal[
    "Workflow Orchestrator Agent",
    "Memory Agent",
    "Resume Agent",
    "DSA Agent",
    "Aptitude Agent",
    "Technical Interview Agent",
    "HR Interview Agent",
    "Evaluation Agent",
    "Planning Agent",
    "Reviewer Agent",
    "Report Agent",
    "Roadmap Agent",
    "Practice Agent",
    "AI Consultant Bot Agent",
]


class AgentEvent(TypedDict, total=False):
    type: Literal["info", "success", "warning", "error"]
    agent: str
    message: str
    step: str
    timestamp: str
    metadata: dict[str, Any]


class CandidateProfile(TypedDict, total=False):
    user_id: str
    interview_id: str
    name: str
    email: str
    target_role: str
    difficulty: str
    company_style: str
    preferred_language: str
    skills: list[str]
    inferred_domain: str
    resume_snippets: list[str]
    resume_text_excerpt: str
    job_description: str
    resume_summary: str
    job_description_summary: str
    shared_memory: dict[str, Any]


class MemoryState(TypedDict, total=False):
    retrieved: list[dict[str, Any]]
    query: str
    memory_types: list[str]
    notes: list[str]


class InterviewPlan(TypedDict, total=False):
    target_role: str
    difficulty: str
    company_style: str
    round_order: list[str]
    dsa_topic_plan: list[dict[str, str]]
    technical_strategy: str
    hr_strategy: str
    adaptation_rules: list[str]


class QuestionSetState(TypedDict, total=False):
    dsa_problems: list[dict[str, Any]]
    aptitude_questions: list[dict[str, Any]]
    technical_questions: list[dict[str, Any]]
    hr_questions: list[dict[str, Any]]


class AgentWorkflowState(TypedDict, total=False):
    interview: dict[str, Any]
    generation_profile: Literal["fast", "deep", "turbo"]
    security_state: dict[str, Any]
    checkpoint_metadata: dict[str, Any]
    candidate_profile: CandidateProfile
    memory_state: MemoryState
    interview_plan: InterviewPlan
    blackboard: list[dict[str, Any]]
    tool_decisions: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    section_generation_reviews: list[dict[str, Any]]
    section_generation_attempts: dict[str, int]
    collaboration_transcript: list[dict[str, Any]]
    planning_critiques: list[dict[str, Any]]
    debate_round: int
    max_debate_rounds: int
    orchestrator_replan_count: int
    max_orchestrator_replans: int
    question_set: QuestionSetState
    validation_errors: list[str]
    generation_attempt: int
    max_generation_attempts: int
    reflection_feedback: list[dict[str, Any]]
    reviewer_critiques: list[dict[str, Any]]
    logs: list[AgentEvent]
    status: Literal["queued", "running", "succeeded", "failed"]
    error: str


def agent_event(
    agent: str,
    message: str,
    step: str,
    event_type: Literal["info", "success", "warning", "error"] = "info",
    metadata: dict[str, Any] | None = None,
) -> AgentEvent:
    return {
        "type": event_type,
        "agent": agent,
        "message": message,
        "step": step,
        "timestamp": iso_now(),
        "metadata": metadata or {},
    }


def append_event(state: AgentWorkflowState, event: AgentEvent) -> list[AgentEvent]:
    return [*state.get("logs", []), event]


def build_candidate_profile_from_interview(interview: dict[str, Any]) -> CandidateProfile:
    shared_memory = ensure_interview_memory(interview)
    summarized = shared_memory.get("summarized_memory", {})
    resume_summary = summarized.get("resume", {}) if isinstance(summarized.get("resume"), dict) else {}
    jd_summary = summarized.get("job_description", {}) if isinstance(summarized.get("job_description"), dict) else {}
    profile = build_profile(
        interview.get("target_role", "Software Engineer"),
        interview.get("difficulty", "medium"),
        interview.get("company_style", "general"),
        interview.get("skills", []),
        interview.get("resume_text", ""),
        interview.get("job_description", ""),
    )
    return {
        "user_id": interview.get("userId", ""),
        "interview_id": interview.get("id", ""),
        "name": interview.get("name", ""),
        "email": interview.get("email", ""),
        "target_role": profile["role"],
        "difficulty": profile["difficulty"],
        "company_style": profile["company_style"],
        "preferred_language": interview.get("preferred_language", "javascript"),
        "skills": profile["skills"],
        "inferred_domain": profile["domain"],
        "resume_snippets": resume_summary.get("snippets", profile["resume_snippets"])[:5],
        "resume_text_excerpt": clean_text(str(resume_summary.get("summary") or profile["resume_text"]), 900),
        "job_description": clean_text(str(jd_summary.get("summary") or profile["job_description"]), 800),
        "resume_summary": clean_text(str(resume_summary.get("summary", "")), 900),
        "job_description_summary": clean_text(str(jd_summary.get("summary", "")), 800),
        "shared_memory": shared_memory,
    }
