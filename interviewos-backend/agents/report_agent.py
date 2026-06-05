from __future__ import annotations

import json
import re
from ast import literal_eval
from typing import Any

from agents.tools.autonomous import execute_autonomous_tool_selection
from agents.tools.decision import ToolDecision, ToolExecutionRecord, tool_decision
from agents.evaluation_agent import public_evaluation_payload
from services.llm import llm_service
from services.store import iso_now, new_id
from utils.parsers import json_from_text


def average(values: list[float], fallback: float = 0) -> float:
    return round(sum(values) / len(values), 2) if values else fallback


def _json_from_text(text: str) -> dict[str, Any]:
    return json_from_text(text, root_error="Report agent response must be a JSON object.")


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


def _string_list(value: Any, fallback: list[str], limit: int = 8) -> list[str]:
    items = [_clean_generated_text(item) for item in _list(value) if _clean_generated_text(item)]
    return (items or fallback)[:limit]


def _communication_summary(answers: list[dict]) -> dict[str, Any]:
    metrics = [answer.get("speechMetrics") or {} for answer in answers if answer.get("speechMetrics")]
    if not metrics:
        return {
            "averageConfidence": 0,
            "averageWordsPerMinute": 0,
            "longPauseCount": 0,
            "unclearCount": 0,
            "dominantLabel": "not captured",
            "notes": ["No speech-confidence metrics were captured for this round."],
        }

    labels = [str(item.get("confidenceLabel") or "steady") for item in metrics]
    notes: list[str] = []
    for item in metrics:
        for note in item.get("notes") or []:
            if isinstance(note, str) and note not in notes:
                notes.append(note)
    return {
        "averageConfidence": average([float(item.get("averageConfidence") or 0) for item in metrics]),
        "averageWordsPerMinute": average([float(item.get("wordsPerMinute") or 0) for item in metrics]),
        "longPauseCount": sum(int(item.get("longPauseCount") or 0) for item in metrics),
        "unclearCount": sum(int(item.get("unclearCount") or 0) for item in metrics),
        "dominantLabel": max(set(labels), key=labels.count) if labels else "steady",
        "notes": notes[:8],
    }


def _proctor_summary(answers: list[dict]) -> dict[str, Any]:
    events = []
    for answer in answers:
        for event in answer.get("proctorEvents") or []:
            if isinstance(event, dict):
                events.append(event)
    return {
        "eventCount": len(events),
        "criticalCount": len([event for event in events if event.get("severity") == "critical"]),
        "messages": [str(event.get("message")) for event in events if event.get("message")][:10],
    }


def _safe_items(items: list[dict], limit: int) -> list[dict]:
    return [public_evaluation_payload(item) for item in items[-limit:]]


def _base_sections(
    dsa_submissions: list[dict],
    aptitude_result: dict | None,
    technical_answers: list[dict],
    hr_answers: list[dict],
) -> list[dict]:
    dsa_score = average([item.get("score", 0) for item in dsa_submissions], 65)
    aptitude_score = float((aptitude_result or {}).get("score", 70))
    technical_score = average([item.get("score", 0) for item in technical_answers], 68)
    hr_score = average([item.get("score", 0) for item in hr_answers], 72)
    return [
        {
            "name": "DSA",
            "score": dsa_score,
            "maxScore": 100,
            "feedback": "Algorithmic problem solving, code correctness, edge-case coverage, and test-case discipline.",
            "details": {"submissions": len(dsa_submissions), "items": _safe_items(dsa_submissions, 3)},
        },
        {
            "name": "Aptitude",
            "score": aptitude_score,
            "maxScore": 100,
            "feedback": "Quantitative reasoning, logical elimination, accuracy, and pace.",
            "details": aptitude_result or {},
        },
        {
            "name": "Technical",
            "score": technical_score,
            "maxScore": 100,
            "feedback": "Concept depth, debugging approach, tradeoff thinking, and validation habits.",
            "details": {
                "answers": len(technical_answers),
                "items": _safe_items(technical_answers, 5),
                "communication": _communication_summary(technical_answers),
                "proctor": _proctor_summary(technical_answers),
            },
        },
        {
            "name": "HR",
            "score": hr_score,
            "maxScore": 100,
            "feedback": "Behavioral clarity, ownership, structure, self-awareness, and role motivation.",
            "details": {
                "answers": len(hr_answers),
                "items": _safe_items(hr_answers, 5),
                "communication": _communication_summary(hr_answers),
                "proctor": _proctor_summary(hr_answers),
            },
        },
    ]


def _weaknesses(sections: list[dict]) -> list[str]:
    sorted_sections = sorted(sections, key=lambda section: section["score"])
    weak = [section["name"] for section in sorted_sections if section["score"] < 75]
    return weak or [sorted_sections[0]["name"], "Timed consistency"]


def _strengths(sections: list[dict]) -> list[str]:
    strong = [section["name"] for section in sections if section["score"] >= 75]
    return strong or ["Persistence through the full interview"]


def _transcript(technical_answers: list[dict], hr_answers: list[dict]) -> list[dict]:
    transcript = []
    for answer in technical_answers + hr_answers:
        metrics = answer.get("speechMetrics") or {}
        transcript.append(
            {
                "id": new_id(),
                "timestamp": iso_now(),
                "speaker": "user",
                "text": answer.get("answer", ""),
                "confidence": metrics.get("averageConfidence") or answer.get("transcriptConfidence") or answer.get("score", 0) / 100,
            }
        )
    return transcript


def _report_context(
    interview: dict,
    sections: list[dict],
    dsa_submissions: list[dict],
    aptitude_result: dict | None,
    technical_answers: list[dict],
    hr_answers: list[dict],
) -> dict[str, Any]:
    return {
        "interview": {
            "target_role": interview.get("target_role") or interview.get("role"),
            "difficulty": interview.get("difficulty"),
            "company_style": interview.get("company_style"),
            "skills": interview.get("skills", []),
            "job_description_excerpt": str(interview.get("job_description", ""))[:1500],
        },
        "scores": [
            {"name": section["name"], "score": section["score"], "feedback": section["feedback"]}
            for section in sections
        ],
        "dsa_submissions": [
            {
                "score": item.get("score"),
                "status": item.get("status"),
                "feedback": item.get("feedback"),
                "testResults": item.get("testResults", [])[:4],
                "code_excerpt": str(item.get("code", ""))[:1200],
                "reasoningEvaluation": public_evaluation_payload(item.get("reasoningEvaluation", {})),
            }
            for item in dsa_submissions[-3:]
        ],
        "aptitude_result": aptitude_result or {},
        "technical_answers": [
            {
                "score": item.get("score"),
                "answer": str(item.get("answer", ""))[:1200],
                "feedback": item.get("feedback"),
                "matchedKeywords": item.get("matchedKeywords", []),
                "answerMode": item.get("answerMode"),
                "timeTakenSeconds": item.get("timeTakenSeconds"),
                "timerExpired": item.get("timerExpired"),
                "speechMetrics": item.get("speechMetrics", {}),
                "proctorEvents": item.get("proctorEvents", []),
                "repeatCount": item.get("repeatCount", 0),
                "paraphraseCount": item.get("paraphraseCount", 0),
                "answerSource": item.get("answerSource"),
                "rubric": item.get("rubric", {}),
                "evidence": item.get("evidence", []),
                "improvementSuggestions": item.get("improvementSuggestions", []),
                "confidenceScore": item.get("confidenceScore"),
                "communicationScore": item.get("communicationScore"),
                "evaluationProvider": item.get("evaluationProvider"),
            }
            for item in technical_answers[-5:]
        ],
        "hr_answers": [
            {
                "score": item.get("score"),
                "answer": str(item.get("answer", ""))[:1200],
                "feedback": item.get("feedback"),
                "matchedKeywords": item.get("matchedKeywords", []),
                "answerMode": item.get("answerMode"),
                "timeTakenSeconds": item.get("timeTakenSeconds"),
                "timerExpired": item.get("timerExpired"),
                "speechMetrics": item.get("speechMetrics", {}),
                "proctorEvents": item.get("proctorEvents", []),
                "repeatCount": item.get("repeatCount", 0),
                "paraphraseCount": item.get("paraphraseCount", 0),
                "answerSource": item.get("answerSource"),
                "rubric": item.get("rubric", {}),
                "evidence": item.get("evidence", []),
                "improvementSuggestions": item.get("improvementSuggestions", []),
                "confidenceScore": item.get("confidenceScore"),
                "communicationScore": item.get("communicationScore"),
                "evaluationProvider": item.get("evaluationProvider"),
            }
            for item in hr_answers[-5:]
        ],
        "communication_summary": {
            "technical": _communication_summary(technical_answers),
            "hr": _communication_summary(hr_answers),
        },
        "proctor_summary": {
            "technical": _proctor_summary(technical_answers),
            "hr": _proctor_summary(hr_answers),
        },
        "reviewer_feedback": interview.get("_agentic_report_reflection_feedback", []),
    }


def _report_query(interview: dict, weaknesses: list[str], strengths: list[str]) -> str:
    return " ".join(
        str(part)
        for part in [
            interview.get("target_role") or interview.get("role"),
            interview.get("difficulty"),
            interview.get("company_style"),
            " ".join(interview.get("skills", []) if isinstance(interview.get("skills"), list) else []),
            "weaknesses " + ", ".join(weaknesses[:4]),
            "strengths " + ", ".join(strengths[:4]),
        ]
        if part
    )


def _records_for_tool(tool_results: list[ToolExecutionRecord], tool_name: str, key: str, limit: int) -> list[dict[str, Any]]:
    return [
        item
        for record in tool_results
        if record.get("ok") and record.get("decision", {}).get("tool") == tool_name
        for item in record.get("data", {}).get(key, [])
    ][:limit]


async def _report_agent_tool_context(
    user_id: str,
    interview: dict,
    context: dict[str, Any],
    weaknesses: list[str],
    strengths: list[str],
) -> tuple[dict[str, Any], list[ToolDecision], list[ToolExecutionRecord]]:
    query = _report_query(interview, weaknesses, strengths) or "interview report evidence"
    fallback_decisions = [
        tool_decision(
            "Report Agent",
            "retrieve_memory_context",
            "Ground the report in historical weakness, transcript, report, and roadmap memory.",
            {
                "user_id": user_id,
                "query": query,
                "limit": 5,
                "memory_types": ["report", "transcript", "weakness", "evaluation", "roadmap", "resume"],
            },
            required=False,
        ),
        tool_decision(
            "Report Agent",
            "retrieve_reports",
            "Compare the latest evidence against recent reports before writing the candidate-facing report.",
            {"user_id": user_id, "limit": 3},
            required=False,
        ),
        tool_decision(
            "Report Agent",
            "retrieve_roadmap",
            "Retrieve active roadmap context so report advice can avoid contradicting the current learning plan.",
            {"user_id": user_id, "active_only": True, "limit": 2},
            required=False,
        ),
        tool_decision(
            "Report Agent",
            "retrieve_resume",
            "Retrieve resume context to keep report feedback grounded in the submitted candidate profile.",
            {"user_id": user_id, "limit": 2},
            required=False,
        ),
    ]
    tool_run = await execute_autonomous_tool_selection(
        agent="report",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the InterviewOS Report Agent. Decide which tools are needed before writing a "
                    "final interview report. Use tools when historical weakness, roadmap, or resume context "
                    "would improve evidence grounding."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Report query: {query}\n"
                    f"Current evidence summary: {json.dumps(context.get('scores', []), ensure_ascii=False)}\n"
                    f"Initial weaknesses: {weaknesses}\nInitial strengths: {strengths}\nUser id: {user_id}"
                )[:8000],
            },
        ],
        available_tools=["retrieve_memory_context", "retrieve_reports", "retrieve_roadmap", "retrieve_resume"],
        fallback_decisions=fallback_decisions,
        max_total_tool_calls=4,
    )
    tool_context = {
        "tool_selection": tool_run.provider_metadata,
        "semantic_memory": _records_for_tool(tool_run.tool_results, "retrieve_memory_context", "memories", 5),
        "historical_reports": _records_for_tool(tool_run.tool_results, "retrieve_reports", "reports", 3),
        "roadmaps": _records_for_tool(tool_run.tool_results, "retrieve_roadmap", "roadmaps", 2),
        "resumes": _records_for_tool(tool_run.tool_results, "retrieve_resume", "resumes", 2),
    }
    return tool_context, tool_run.tool_decisions, tool_run.tool_results


async def _ai_analysis(context: dict[str, Any], overall: float, weaknesses: list[str], strengths: list[str]) -> tuple[dict[str, Any], str | None]:
    response = await llm_service.invoke_live(
        [
            {
                "role": "system",
                "content": (
                    "You are the InterviewOS Report Agent. Produce a detailed, candid interview report "
                    "from the provided evidence. Be concrete about what went wrong, why it likely "
                    "happened, what the candidate should change, and how to practice next. "
                    "Stay neutral and non-biased: judge only answer quality, captured communication signals, "
                    "timing, and proctor evidence. Do not infer personal traits or protected characteristics. "
                    "Return only JSON with plain-text string values, no markdown."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Create a report analysis for this interview.\n"
                    f"Overall score: {overall}/100\n"
                    f"Initial strengths: {strengths}\n"
                    f"Initial weaknesses: {weaknesses}\n\n"
                    f"Reviewer repair feedback, if any: {json.dumps(context.get('reviewer_feedback', []), ensure_ascii=False)}\n\n"
                    "Do not include markdown emphasis markers like **, __, or backticks in any string value.\n"
                    "Return this exact JSON shape:\n"
                    "{\n"
                    '  "executiveSummary": "4-6 sentence summary",\n'
                    '  "aiFeedback": "detailed paragraph",\n'
                    '  "strengths": ["specific strength"],\n'
                    '  "weaknesses": ["specific weakness"],\n'
                    '  "whatWentWrong": ["specific issue observed"],\n'
                    '  "nextTimeSuggestions": ["specific suggestion"],\n'
                    '  "actionPlan": [{"title": "task", "description": "why/how", "priority": "high|medium|low"}],\n'
                    '  "sectionAnalyses": [{"name": "DSA|Aptitude|Technical|HR", "feedback": "paragraph", "evidence": ["evidence"], "actionItems": ["task"]}]\n'
                    "}\n\n"
                    f"Evidence JSON:\n{json.dumps(context, ensure_ascii=False)}"
                ),
            },
        ],
        agent="report",
    )
    return _json_from_text(response.content), response.provider


def _fallback_analysis(overall: float, sections: list[dict], weaknesses: list[str], strengths: list[str]) -> dict[str, Any]:
    lowest = sorted(sections, key=lambda section: section["score"])[0]
    section_analyses = []
    for section in sections:
        score = round(section["score"])
        if score < 60:
            tone = "needs immediate repair"
        elif score < 75:
            tone = "is workable but inconsistent"
        else:
            tone = "is currently a relative strength"
        section_analyses.append(
            {
                "name": section["name"],
                "feedback": f"{section['name']} scored {score}/100 and {tone}. {section['feedback']}",
                "evidence": [
                    f"Recorded score: {score}/100",
                    f"Captured activity: {section['details']}",
                ],
                "actionItems": [
                    f"Review every missed or low-confidence {section['name']} answer.",
                    "Write a one-line mistake label and a corrected version after each practice item.",
                ],
            }
        )
    return {
        "executiveSummary": (
            f"Your overall interview score was {overall}/100. The biggest improvement area is "
            f"{lowest['name']}, so the next cycle should focus on fewer topics with deeper review. "
            "The score pattern suggests that practice needs to move beyond completing questions into "
            "reviewing mistakes, explaining reasoning, and validating answers under time pressure."
        ),
        "aiFeedback": (
            f"Overall score {overall}/100. Focus first on {weaknesses[0]}, keep {strengths[0]} active, "
            "and use a mistake log after each session so repeated gaps become visible."
        ),
        "strengths": strengths,
        "weaknesses": weaknesses,
        "whatWentWrong": [
            f"{lowest['name']} was the lowest-scoring area, which pulled down the final score.",
            "The interview evidence does not show enough deliberate review after mistakes.",
            "Several sections need clearer explanation of reasoning, not only final answers.",
        ],
        "nextTimeSuggestions": [
            f"Spend the first week repairing {lowest['name']} fundamentals with short daily drills.",
            "After every answer, write what signal the interviewer was looking for and what was missing.",
            "Run one timed mock at the end of each week and compare the error pattern with this report.",
        ],
        "actionPlan": [
            {
                "title": f"Repair {lowest['name']} basics",
                "description": "Do focused drills, then rewrite each wrong answer with the missing concept included.",
                "priority": "high",
            },
            {
                "title": "Build a mistake log",
                "description": "Track issue, cause, corrected answer, and the next drill that prevents repetition.",
                "priority": "high",
            },
            {
                "title": "Mock under time pressure",
                "description": "Simulate the interview flow weekly and compare progress section by section.",
                "priority": "medium",
            },
        ],
        "sectionAnalyses": section_analyses,
    }


def _merge_sections(sections: list[dict], analyses: list[dict]) -> list[dict]:
    by_name = {str(item.get("name", "")).lower(): item for item in analyses if isinstance(item, dict)}
    merged = []
    for section in sections:
        analysis = by_name.get(section["name"].lower(), {})
        details = dict(section.get("details", {}))
        details["evidence"] = _string_list(analysis.get("evidence"), [], limit=6)
        details["actionItems"] = _string_list(analysis.get("actionItems"), [], limit=6)
        merged.append(
            {
                **section,
                "feedback": _clean_generated_text(analysis.get("feedback"), section["feedback"]),
                "details": details,
            }
        )
    return merged


async def build_report(
    user_id: str,
    interview: dict,
    dsa_submissions: list[dict],
    aptitude_result: dict | None,
    technical_answers: list[dict],
    hr_answers: list[dict],
    *,
    include_agent_evidence: bool = False,
) -> dict:
    sections = _base_sections(dsa_submissions, aptitude_result, technical_answers, hr_answers)
    overall = round(sum(section["score"] for section in sections) / 4, 2)
    weaknesses = _weaknesses(sections)
    strengths = _strengths(sections)
    context = _report_context(interview, sections, dsa_submissions, aptitude_result, technical_answers, hr_answers)
    tool_context, tool_decisions, tool_results = await _report_agent_tool_context(
        user_id,
        interview,
        context,
        weaknesses,
        strengths,
    )
    context["agent_tool_context"] = tool_context
    provider: str | None = None

    try:
        analysis, provider = await _ai_analysis(context, overall, weaknesses, strengths)
    except Exception:
        analysis = _fallback_analysis(overall, sections, weaknesses, strengths)

    final_strengths = _string_list(analysis.get("strengths"), strengths)
    final_weaknesses = _string_list(analysis.get("weaknesses"), weaknesses)
    section_analyses = [item for item in _list(analysis.get("sectionAnalyses")) if isinstance(item, dict)]
    merged_sections = _merge_sections(sections, section_analyses)

    report = {
        "id": new_id(),
        "userId": user_id,
        "interviewId": interview["id"],
        "createdAt": iso_now(),
        "overallScore": overall,
        "sections": merged_sections,
        "strengths": final_strengths,
        "weaknesses": final_weaknesses,
        "aiFeedback": _clean_generated_text(analysis.get("aiFeedback"), f"Overall score {overall}/100. Focus next on {final_weaknesses[0]}."),
        "executiveSummary": _clean_generated_text(analysis.get("executiveSummary"), ""),
        "whatWentWrong": _string_list(analysis.get("whatWentWrong"), [], limit=10),
        "nextTimeSuggestions": _string_list(analysis.get("nextTimeSuggestions"), [], limit=10),
        "actionPlan": [
            {
                "id": new_id(),
                "title": _clean_generated_text(item.get("title"), "Practice improvement task"),
                "description": _clean_generated_text(item.get("description"), "Review the related interview evidence and practice again."),
                "priority": _clean_generated_text(item.get("priority"), "medium"),
            }
            for item in _list(analysis.get("actionPlan"))
            if isinstance(item, dict)
        ],
        "sectionAnalyses": section_analyses,
        "generationProvider": provider,
        "agentToolContext": {
            "toolSelection": tool_context.get("tool_selection", {}),
            "semanticMemoryCount": len(tool_context.get("semantic_memory", [])),
            "historicalReportCount": len(tool_context.get("historical_reports", [])),
            "roadmapCount": len(tool_context.get("roadmaps", [])),
            "resumeCount": len(tool_context.get("resumes", [])),
        },
        "communicationSummary": context["communication_summary"],
        "proctorSummary": context["proctor_summary"],
        "transcript": _transcript(technical_answers, hr_answers),
    }
    if include_agent_evidence:
        report["_agentic_tool_decisions"] = tool_decisions
        report["_agentic_tool_results"] = tool_results
    return report
