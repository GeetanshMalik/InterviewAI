from __future__ import annotations

import json
import re
from hashlib import sha256
from ast import literal_eval
from typing import Any

from fastapi import HTTPException

from agents.aptitude_agent import normalize_question_answer_key
from services.context import build_profile, clean_text
from services.context_memory import compact_agent_context
from services.llm import llm_service
from services.store import new_id
from utils.parsers import json_from_text


APTITUDE_OPTION_KEYS = ("A", "B", "C", "D")


def _json_from_text(text: str) -> dict[str, Any]:
    return json_from_text(text)


async def _repair_json_response(raw_text: str, error: Exception, required_key: str, agent: str) -> dict[str, Any]:
    repair = await llm_service.invoke_live(
        [
            {
                "role": "system",
                "content": "Convert malformed interview content into strict valid JSON. Return only JSON.",
            },
            {
                "role": "user",
                "content": (
                    "The previous response could not be parsed as JSON.\n"
                    f"Parser error: {type(error).__name__}: {error}\n\n"
                    f"Return a valid JSON object with exactly one top-level key: {required_key}.\n"
                    "Do not include markdown fences, comments, or explanation.\n\n"
                    f"Malformed response:\n{raw_text[:12000]}"
                ),
            },
        ],
        agent=agent,
    )
    return _json_from_text(repair.content)


def _string(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
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


def _stable_index(seed: str, salt: str, size: int) -> int:
    if size <= 0:
        return 0
    digest = sha256(f"{seed}:{salt}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % size


def _stable_pick(options: list[str], seed: str, salt: str, fallback: str) -> str:
    if not options:
        return fallback
    return options[_stable_index(seed, salt, len(options))]


def _stable_order(items: list[Any], seed: str, salt: str) -> list[Any]:
    return sorted(
        items,
        key=lambda item: sha256(f"{seed}:{salt}:{json.dumps(item, sort_keys=True, default=str)}".encode("utf-8")).hexdigest(),
    )


def _variation_seed(source: dict[str, Any], section: str = "") -> str:
    identity = str(source.get("id") or source.get("interview_id") or "")
    parts = [
        identity,
        str(source.get("createdAt") or source.get("created_at") or ""),
        section,
        str(source.get("target_role") or ""),
        str(source.get("difficulty") or ""),
        str(source.get("company_style") or ""),
        " ".join(str(skill) for skill in source.get("skills", [])),
        str(source.get("_workflow_generation_attempt") or source.get("workflow_generation_attempt") or ""),
        str(source.get("_agentic_repair_attempt") or source.get("repair_attempt") or ""),
    ]
    if not identity:
        parts.extend(
            [
                sha256(str(source.get("resume_text") or source.get("resume_text_excerpt") or "").encode("utf-8")).hexdigest()[:16],
                sha256(str(source.get("job_description") or "").encode("utf-8")).hexdigest()[:16],
            ]
        )
    return sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _balanced_aptitude_answer_targets(seed: str, count: int) -> list[str]:
    base = ["A", "B", "C", "D", "A"]
    rotation = _stable_index(seed, "aptitude-answer-key-rotation", len(APTITUDE_OPTION_KEYS))
    return [APTITUDE_OPTION_KEYS[(APTITUDE_OPTION_KEYS.index(key) + rotation) % len(APTITUDE_OPTION_KEYS)] for key in base[:count]]


def _answer_distribution_is_safe(questions: list[dict[str, Any]]) -> bool:
    counts: dict[str, int] = {}
    for question in questions:
        answer = str(question.get("correct_answer") or "").upper()
        counts[answer] = counts.get(answer, 0) + 1
    return bool(counts) and max(counts.values()) <= 2


def _sanitize_aptitude_explanation_label(text: str) -> str:
    cleaned = re.sub(
        r"(?i)\b(?:the\s+)?correct\s+(?:option|answer|choice)\s+is\s+[A-D][\.:,\s-]*",
        "",
        text,
    )
    cleaned = re.sub(
        r"(?i)\b(?:option|choice|answer)\s+[A-D]\s+(?:is|was)\s+(?:the\s+)?(?:correct|best|right)\s*(?:because|as|since)?\s*",
        "",
        cleaned,
    )
    return cleaned.strip() or "The selected option follows from the stated reasoning."


def _rebalance_aptitude_answer_keys(questions: list[dict[str, Any]], interview_id: str) -> list[dict[str, Any]]:
    if _answer_distribution_is_safe(questions):
        return questions

    for question, target_answer in zip(questions, _balanced_aptitude_answer_targets(interview_id, len(questions))):
        current_answer = str(question.get("correct_answer") or "").upper()
        if current_answer == target_answer:
            continue
        options = question.get("options")
        if not isinstance(options, dict) or current_answer not in options or target_answer not in options:
            continue
        options[current_answer], options[target_answer] = options[target_answer], options[current_answer]
        question["correct_answer"] = target_answer
        question["explanation"] = _sanitize_aptitude_explanation_label(str(question.get("explanation") or ""))
    return questions


def _context_seed(interview: dict[str, Any]) -> str:
    parts = [
        str(interview.get("id", "")),
        str(interview.get("target_role", "")),
        str(interview.get("difficulty", "")),
        str(interview.get("company_style", "")),
        " ".join(str(skill) for skill in interview.get("skills", [])),
        str(interview.get("job_description", ""))[:500],
        str(interview.get("resume_text", ""))[:500],
    ]
    return sha256("|".join(parts).encode("utf-8")).hexdigest()


def _context_terms(context: dict[str, Any]) -> dict[str, str]:
    skills = [str(skill).strip() for skill in context.get("skills", []) if str(skill).strip()]
    snippets = [str(item).strip() for item in context.get("resume_snippets", []) if str(item).strip()]
    seed = _context_seed(
        {
            "id": context.get("interview_id") or context.get("target_role", ""),
            "createdAt": context.get("created_at", ""),
            "target_role": context.get("target_role", ""),
            "difficulty": context.get("difficulty", ""),
            "company_style": context.get("company_style", ""),
            "skills": skills,
            "job_description": context.get("job_description", ""),
            "resume_text": context.get("resume_text_excerpt", ""),
        }
    )
    skill = _stable_pick(skills, seed, "skill", "backend systems")
    secondary_skill = _stable_pick(skills, seed, "secondary-skill", skill)
    resume_signal = _stable_pick(snippets, seed, "resume", f"{skill} experience")
    return {
        "role": str(context.get("target_role") or "Software Engineer"),
        "difficulty": str(context.get("difficulty") or "medium"),
        "domain": str(context.get("inferred_domain") or "software systems"),
        "skill": skill,
        "secondary_skill": secondary_skill,
        "resume_signal": resume_signal,
        "company_style": str(context.get("company_style") or "product"),
        "has_resume": "true" if snippets else "",
        "seed": seed,
        "variation_seed": str(context.get("variation_seed") or seed[:16]),
    }


def _list(value: Any, fallback: list[Any] | None = None) -> list[Any]:
    if isinstance(value, list):
        return value
    return fallback or []


def _dict(value: Any, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return fallback or {}


DSA_TOPIC_POOLS: dict[str, list[tuple[str, str]]] = {
    "easy": [
        ("arrays and hash maps", "Counting, grouping, deduplication, lookup, or simple analytics."),
        ("strings", "Parsing, normalization, validation, slugging, or formatting."),
        ("stack or queue", "Undo, recent activity, batching, request processing, or simulation."),
        ("linked list basics", "Pointer updates, reversal, merge, or cycle-safe traversal."),
        ("two pointers", "Pairing, window boundaries, sorted scans, or validation."),
        ("sorting and binary search", "Deterministic ordering, threshold search, or insertion position."),
    ],
    "medium": [
        ("arrays and hash maps", "Reconciliation, joins, frequency analysis, ranking, or aggregation."),
        ("stack or queue", "Monotonic stack, scheduling, retries, or stream processing."),
        ("linked list or intervals", "Pointer manipulation, merge intervals, time windows, or pagination state."),
        ("trees", "Hierarchy traversal, depth, ancestor, permissions, or folder/org structures."),
        ("graphs", "BFS/DFS, dependencies, connected components, reachability, or service maps."),
        ("heaps or dynamic programming", "Top-k, priority scheduling, state transitions, or optimization."),
        ("sliding window", "Rate limits, rolling metrics, longest/shortest window, or stream constraints."),
    ],
    "hard": [
        ("graphs", "Weighted paths, cycles, topological ordering, multi-source traversal, or dependency safety."),
        ("trees or tries", "Advanced traversal, prefix/range search, nested structures, or hierarchy aggregation."),
        ("dynamic programming", "State design, memoization, sequence/grid optimization, matching, or counting."),
        ("heaps and intervals", "Scheduling, ranking, capacity windows, sweep-line, or resource allocation."),
        ("backtracking or branch and bound", "Constraint search, combinations, pruning, or allocation plans."),
        ("advanced arrays and greedy", "Multiple constraints, proof-driven choices, or optimal partitioning."),
    ],
}


def _dsa_topic_plan(company_style: str, difficulty: str, seed: str | None = None) -> list[dict[str, str]]:
    style = _string(company_style, "product").lower()
    level = _string(difficulty, "medium").lower()

    startup = {
        "easy": [
            ("arrays and hash maps", "CRUD-style counting, filtering, grouping, or inventory lookup."),
            ("strings", "Slug, validation, formatting, parsing, or normalization logic."),
            ("stack or queue", "Simple workflow, undo, batching, recent activity, or request processing."),
        ],
        "medium": [
            ("arrays and hash maps", "Aggregation, frequency maps, deduplication, joins, or ranking."),
            ("stack or queue", "Event stream processing, monotonic stack basics, scheduling, or retries."),
            ("linked list or intervals", "Pointer manipulation, merge intervals, time windows, or pagination state."),
        ],
        "hard": [
            ("arrays and intervals", "Multiple constraints, greedy merging, sweep-line, or allocation."),
            ("stack or heap", "Priority ordering, top-k, throttling, queues, or monotonic patterns."),
            ("linked list and hash maps", "Cache-style state, deduplication, cycle handling, or mutable records."),
        ],
    }
    enterprise = {
        "easy": [
            ("arrays and strings", "Data cleanup, validation, reporting, or transformation."),
            ("hash maps", "Lookup, grouping, reconciliation, or access-control style counting."),
            ("stack or queue", "Workflow, ticket processing, retry, or audit-log traversal."),
        ],
        "medium": [
            ("arrays and hash maps", "Batch processing, reconciliation, frequency analysis, or joins."),
            ("trees", "Org chart, permissions, folder hierarchy, or dependency traversal."),
            ("queues or heaps", "Scheduling, priority escalation, rate limiting, or resource allocation."),
        ],
        "hard": [
            ("graphs", "Dependencies, service topology, permissions, or workflow reachability."),
            ("trees", "Hierarchy aggregation, lowest common manager, or nested policy evaluation."),
            ("dynamic programming or intervals", "Capacity planning, scheduling, cost optimization, or windows."),
        ],
    }
    faang = {
        "easy": [
            ("arrays and strings", "Clean implementation with edge cases and concise complexity."),
            ("hash maps", "Frequency, lookup, two-sum style matching, or grouping."),
            ("stack or two pointers", "Parsing, validation, window, or pointer movement."),
        ],
        "medium": [
            ("trees", "Traversal, depth, ancestor, serialization, or hierarchy reasoning."),
            ("graphs", "BFS/DFS, shortest path basics, connected components, or dependencies."),
            ("heaps or dynamic programming", "Top-k, scheduling, state transitions, or optimization."),
        ],
        "hard": [
            ("graphs", "Weighted paths, cycles, topological ordering, or multi-source traversal."),
            ("dynamic programming", "State design, sequence/grid optimization, memoization, or counting."),
            ("trees or tries", "Advanced traversal, prefix search, range queries, or nested structures."),
        ],
    }

    product = {
        "easy": [
            ("arrays and hash maps", "Metrics, activity grouping, product analytics, or recommendations."),
            ("strings", "Search, slugging, validation, or user-facing formatting."),
            ("stack or queue", "Navigation, undo, notifications, or feed processing."),
        ],
        "medium": [
            ("arrays and intervals", "Availability windows, feeds, ranking, or experiment buckets."),
            ("hash maps and heaps", "Top-k metrics, trending items, personalization, or priority ordering."),
            ("trees or graphs", "Menus, recommendations, entity relationships, or dependency traversal."),
        ],
        "hard": [
            ("graphs", "Recommendations, trust networks, paths, or feature dependencies."),
            ("dynamic programming", "Personalization, sequencing, matching, or optimization."),
            ("heaps and intervals", "Scheduling, ranking, rate limits, or capacity windows."),
        ],
    }

    plans = {
        "startup": startup,
        "enterprise": enterprise,
        "faang": faang,
        "product": product,
    }
    selected = plans.get(style, product).get(level, product["medium"])
    if seed:
        pool = [*selected, *DSA_TOPIC_POOLS.get(level, DSA_TOPIC_POOLS["medium"])]
        unique: dict[str, str] = {}
        for category, focus in pool:
            unique.setdefault(category, focus)
        ordered = _stable_order([{"category": category, "focus": focus} for category, focus in unique.items()], seed, "dsa-topic-plan")
        selected = [(item["category"], item["focus"]) for item in ordered[:3]]
    return [
        {"problem_number": str(index), "category": category, "focus": focus}
        for index, (category, focus) in enumerate(selected, start=1)
    ]


def _section_variation_plan(context: dict[str, Any], section: str) -> dict[str, Any]:
    seed = str(context.get("variation_seed") or _variation_seed(context, section))
    difficulty = str(context.get("difficulty") or "medium").lower()
    plan: dict[str, Any] = {
        "variation_seed": seed,
        "novelty_rule": "Do not reuse recent question wording, stories, numbers, constraints, or topic ordering.",
    }
    if section == "dsa_problems":
        plan["topic_plan"] = _dsa_topic_plan(str(context.get("company_style") or "product"), difficulty, seed)
    elif section == "aptitude_questions":
        categories = [
            "quantitative percentage/change",
            "logical ordering",
            "data interpretation",
            "probability and counting",
            "critical reasoning",
            "pattern recognition",
            "work scheduling",
            "ratio and proportion",
        ]
        plan["category_slate"] = _stable_order(categories, seed, "aptitude-categories")[:5]
    elif section == "technical_questions":
        themes = [
            "resume project deep dive",
            "debugging and incident response",
            "API or data model design",
            "performance and scalability",
            "testing and observability",
            "security or reliability tradeoff",
            "implementation sketch",
            "architecture migration",
        ]
        plan["theme_slate"] = _stable_order(themes, seed, "technical-themes")[:5]
    elif section == "hr_questions":
        themes = [
            "ownership under ambiguity",
            "conflict and collaboration",
            "learning from failure",
            "stakeholder communication",
            "motivation for the role",
            "adaptability",
            "leadership without authority",
            "prioritization under pressure",
            "feedback and growth",
            "values and team fit",
        ]
        plan["theme_slate"] = _stable_order(themes, seed, "hr-themes")[:8]
    return plan


def _normalize_dsa(raw_items: Any, interview_id: str, difficulty: str, topic_plan: list[dict[str, str]]) -> list[dict[str, Any]]:
    items = _list(raw_items)
    problems = []
    for index, raw in enumerate(items[:3], start=1):
        item = _dict(raw)
        planned = topic_plan[index - 1] if index - 1 < len(topic_plan) else {}
        category = _clean_generated_text(planned.get("category") or item.get("category"), f"Problem {index}")
        test_cases = _list(item.get("test_cases"))
        if len(test_cases) < 2:
            raise ValueError("Each DSA problem must include at least two test_cases.")
        normalized_cases = []
        for case_index, case in enumerate(test_cases[:5], start=1):
            case_dict = _dict(case)
            normalized_cases.append(
                {
                    "name": _string(case_dict.get("name"), f"Case {case_index}"),
                    "input": case_dict.get("input", {}),
                    "expected": case_dict.get("expected"),
                }
            )
        examples = []
        for example_index, example in enumerate(_list(item.get("examples"))[:2], start=1):
            example_dict = _dict(example)
            examples.append(
                {
                    "input": example_dict.get("input", normalized_cases[example_index - 1]["input"] if len(normalized_cases) >= example_index else {}),
                    "output": example_dict.get("output", normalized_cases[example_index - 1]["expected"] if len(normalized_cases) >= example_index else None),
                }
            )
        while len(examples) < 2 and len(normalized_cases) > len(examples):
            case = normalized_cases[len(examples)]
            examples.append({"input": case["input"], "output": case["expected"]})
        raw_tags = [_clean_generated_text(tag) for tag in _list(item.get("tags"), [])]
        tags = list(dict.fromkeys([category, *raw_tags]))[:5]
        problems.append(
            {
                "id": new_id(),
                "interview_id": interview_id,
                "problem_number": index,
                "category": category,
                "title": _clean_generated_text(item.get("title"), f"Generated Problem {index}"),
                "description": _clean_generated_text(item.get("description"), "Solve the generated coding problem."),
                "difficulty": _clean_generated_text(item.get("difficulty"), difficulty),
                "examples": examples,
                "test_cases": normalized_cases,
                "constraints": _clean_generated_text(item.get("constraints"), "Explain time and space complexity."),
                "tags": tags,
                "required_signals": [_clean_generated_text(signal).lower() for signal in _list(item.get("required_signals"), [])][:8],
                "resume_context_used": bool(item.get("resume_context_used")),
                "source": "llm-generated",
            }
        )
    if len(problems) != 3:
        raise ValueError("Exactly three DSA problems are required.")
    return problems


def _normalize_aptitude(raw_items: Any, interview_id: str, difficulty: str) -> list[dict[str, Any]]:
    items = _list(raw_items)
    questions = []
    for index, raw in enumerate(items[:5], start=1):
        item = _dict(raw)
        options = _dict(item.get("options"))
        if set(options.keys()) != {"A", "B", "C", "D"}:
            raise ValueError("Aptitude options must be an object with A, B, C, and D.")
        answer = _string(item.get("correct_answer")).upper()
        if answer not in options:
            raise ValueError("Aptitude correct_answer must match one option key.")
        questions.append(
            {
                "id": new_id(),
                "interview_id": interview_id,
                "question_number": index,
                "question_text": _clean_generated_text(item.get("question_text"), f"Generated aptitude question {index}"),
                "options": {key: _clean_generated_text(value) for key, value in options.items()},
                "correct_answer": answer,
                "correct_answer_value": _clean_generated_text(
                    item.get("correct_answer_value") or options.get(answer),
                    options.get(answer),
                ),
                "category": _clean_generated_text(item.get("category"), "reasoning"),
                "difficulty": _clean_generated_text(item.get("difficulty"), difficulty),
                "explanation": _clean_generated_text(item.get("explanation"), f"The correct option is {answer}."),
                "resume_context_used": bool(item.get("resume_context_used")),
                "source": "llm-generated",
            }
        )
    if len(questions) != 5:
        raise ValueError("Exactly five aptitude questions are required.")
    return [normalize_question_answer_key(question) for question in questions]


def _interview_answer_mode(section: str, index: int) -> str:
    if section == "technical" and index >= 4:
        return "code"
    return "spoken"


def _interview_timer_seconds(section: str, difficulty: str, index: int) -> int:
    if _interview_answer_mode(section, index) == "code":
        return 10 * 60
    level = _string(difficulty, "medium").lower()
    if level == "hard":
        return 5 * 60
    if level == "medium":
        return 4 * 60
    return 3 * 60


def _normalize_interview_questions(raw_items: Any, interview_id: str, role: str, difficulty: str, count: int, section: str) -> list[dict[str, Any]]:
    items = _list(raw_items)
    questions = []
    for index, raw in enumerate(items[:count], start=1):
        item = _dict(raw)
        text = _clean_generated_text(item.get("question_text"))
        if len(text) < 20:
            raise ValueError("Interview questions must be substantive.")
        questions.append(
            {
                "id": new_id(),
                "interview_id": interview_id,
                "question_number": index,
                "question_text": text,
                "role": role,
                "difficulty": difficulty,
                "keywords": [str(keyword).lower() for keyword in _list(item.get("keywords"), [])][:10],
                "answer_mode": _interview_answer_mode(section, index),
                "timer_seconds": _interview_timer_seconds(section, difficulty, index),
                "resume_context_used": bool(item.get("resume_context_used")),
                "source": "llm-generated",
            }
        )
    if len(questions) != count:
        raise ValueError(f"Exactly {count} interview questions are required.")
    return questions


def _candidate_context(interview: dict[str, Any], section: str | None = None) -> dict[str, Any]:
    agent = {
        "dsa_problems": "dsa",
        "aptitude_questions": "aptitude",
        "technical_questions": "technical",
        "hr_questions": "hr",
    }.get(section or "", "planning")
    compact_context = compact_agent_context(
        interview,
        agent=agent,
        section=section,
        retrieved_memory=_list(interview.get("_agentic_generation_memory")),
        collaboration_transcript=_list(interview.get("_agentic_collaboration_transcript")),
        generation_history=_list(interview.get("_agentic_generation_history")),
        practice_history=_list(interview.get("_agentic_practice_history")),
        reflection_feedback=_list(interview.get("_agentic_reflection_feedback")),
        interview_plan=_dict(interview.get("_agentic_interview_plan")),
    )
    short_memory = compact_context.get("short_term_memory", {})
    summarized = compact_context.get("summarized_memory", {})
    retrieval = compact_context.get("retrieval_memory", {})
    resume_snips = summarized.get("resume_snippets") or retrieval.get("resume_snippets", [])
    jd_requirements = summarized.get("job_requirements") or retrieval.get("jd_requirements", [])
    context = {
        "interview_id": interview.get("id", ""),
        "created_at": interview.get("createdAt", ""),
        "target_role": short_memory.get("role", "Software Engineer"),
        "difficulty": short_memory.get("difficulty", "medium"),
        "company_style": short_memory.get("company_style", "general"),
        "inferred_domain": short_memory.get("domain", "general"),
        "skills": short_memory.get("skills", []),
        "resume_snippets": resume_snips[:5],
        "resume_text_excerpt": clean_text(str(summarized.get("resume_summary", "")), 900),
        "job_description": clean_text(str(summarized.get("job_summary", " ".join(jd_requirements))), 850),
        "context_cache_key": compact_context.get("cacheKey") or (compact_context.get("shared_memory") or {}).get("cacheKey"),
        "workflow_generation_attempt": interview.get("_workflow_generation_attempt") or interview.get("workflow_generation_attempt") or "",
        "repair_attempt": interview.get("_agentic_repair_attempt") or "",
    }
    context["variation_seed"] = _variation_seed(context, section or "package")
    reflection_feedback = compact_context.get("reflection_feedback")
    if reflection_feedback:
        context["reflection_feedback"] = reflection_feedback
        context["repair_instruction"] = (
            "This is a repair attempt. Address every validation error and reviewer instruction exactly; "
            "do not repeat the invalid structure."
        )
    if compact_context.get("interview_plan"):
        context["interview_plan"] = compact_context.get("interview_plan")
    if compact_context.get("collaboration_summary"):
        context["collaboration_summary"] = compact_context.get("collaboration_summary")
    if retrieval.get("memories"):
        context["generation_memory"] = retrieval.get("memories")
    if compact_context.get("generation_history"):
        context["generation_history"] = compact_context.get("generation_history")
    if compact_context.get("practice_summary"):
        context["practice_history"] = compact_context.get("practice_summary")
    return context


def _compact_section_prompt_context(context: dict[str, Any], section: str) -> dict[str, Any]:
    """Keep section prompts focused; large private traces live in separate guidance blocks."""

    prompt_context = {
        "interview_id": context.get("interview_id"),
        "target_role": context.get("target_role"),
        "difficulty": context.get("difficulty"),
        "company_style": context.get("company_style"),
        "inferred_domain": context.get("inferred_domain"),
        "skills": context.get("skills", [])[:8],
        "variation_plan": _section_variation_plan(context, section),
    }
    if section in {"technical_questions", "hr_questions"}:
        prompt_context["resume_snippets"] = context.get("resume_snippets", [])[:3]
        prompt_context["resume_text_excerpt"] = clean_text(str(context.get("resume_text_excerpt", "")), 500)
        prompt_context["job_description"] = clean_text(str(context.get("job_description", "")), 450)
    else:
        prompt_context["job_description"] = clean_text(str(context.get("job_description", "")), 360)
    if context.get("generation_memory"):
        prompt_context["generation_memory"] = context.get("generation_memory", [])[:2]
    if context.get("generation_history"):
        prompt_context["avoid_recent_questions"] = context.get("generation_history", [])[:5]
    if context.get("practice_history") and section in {"technical_questions", "hr_questions"}:
        prompt_context["practice_history"] = context.get("practice_history", [])[:1]
    if context.get("interview_plan"):
        plan = context.get("interview_plan") or {}
        plan_context = {
            "focus_topics": plan.get("focus_topics", [])[:6],
            "difficulty_distribution": plan.get("difficulty_distribution", {}),
        }
        if section == "technical_questions":
            plan_context["technical_strategy"] = clean_text(str(plan.get("technical_strategy", "")), 260)
        if section == "hr_questions":
            plan_context["hr_strategy"] = clean_text(str(plan.get("hr_strategy", "")), 260)
        if section in {"technical_questions", "hr_questions"}:
            plan_context["adaptation_rules"] = [clean_text(str(item), 160) for item in plan.get("adaptation_rules", [])[:3]]
        prompt_context["interview_plan"] = plan_context
    if context.get("context_cache_key"):
        prompt_context["context_cache_key"] = context.get("context_cache_key")
    return prompt_context


def _section_prompt(interview: dict[str, Any], section: str) -> list[dict[str, str]]:
    candidate_context = _candidate_context(interview, section)
    prompt_context = _compact_section_prompt_context(candidate_context, section)
    difficulty = candidate_context["difficulty"]
    dsa_topic_plan = (prompt_context.get("variation_plan") or {}).get("topic_plan") or _dsa_topic_plan(
        candidate_context["company_style"],
        difficulty,
        candidate_context.get("variation_seed"),
    )
    schemas = {
        "dsa_problems": {
            "count": 3,
            "schema": {
                "category": "exact category from the DSA topic plan for this problem number",
                "title": "string",
                "description": "string",
                "difficulty": difficulty,
                "examples": [{"input": "string", "output": "string"}],
                "test_cases": [{"name": "string", "input": {}, "expected": "any JSON value"}],
                "constraints": "string",
                "tags": ["string"],
                "required_signals": ["algorithm keyword expected in a plausible solution"],
                "resume_context_used": True,
            },
            "rules": [
                "Generate original coding problems only; do not use stock coding-platform titles.",
                "Avoid any topic/story/constraint that appears in avoid_recent_questions.",
                "Follow the DSA topic plan exactly by problem number. Do not swap, skip, or invent categories.",
                "Each problem must be solved by implementing solve(input). input is one JSON object.",
                "Each problem needs a detailed problem statement, constraints, exactly two sample input/output examples, and at least five executable JSON test cases with expected JSON outputs.",
                "Keep inputs friendly to Python, JavaScript, TypeScript, Java, Go, and Rust JSON parsing.",
                "Match requested difficulty and role domain.",
            ],
        },
        "aptitude_questions": {
            "count": 5,
            "schema": {
                "question_text": "string",
                "options": {"A": "string", "B": "string", "C": "string", "D": "string"},
                "correct_answer": "A|B|C|D",
                "correct_answer_value": "string value of the correct option",
                "category": "string",
                "difficulty": difficulty,
                "explanation": "string",
                "resume_context_used": True,
            },
            "rules": [
                "Generate role-aware reasoning/quant/logic questions.",
                "Use the category_slate in variation_plan and avoid recent question templates.",
                "Each question must have exactly A, B, C, D options, one unambiguous correct value, correct_answer, and correct_answer_value.",
                "The explanation must prove the correct value and must not contradict correct_answer or correct_answer_value.",
                "Do not create equivalent duplicate options such as 1/2 and 3/6 unless the question explicitly accepts both values.",
                "For ordering questions, explicitly state ascending, descending, chronological, priority, or another concrete rule in the question text.",
                "Avoid repeated textbook train/work-rate questions unless the role context makes them relevant.",
            ],
        },
        "technical_questions": {
            "count": 5,
            "schema": {
                "question_text": "string",
                "keywords": ["string"],
                "resume_context_used": True,
            },
            "rules": [
                "Generate video-call technical interview questions.",
                "Use the theme_slate in variation_plan and avoid recent question wording/topics.",
                "If resume text exists, at least two questions must explicitly refer to resume projects/experience.",
                "Questions 1-3 should work as spoken interview answers.",
                "Questions 4-5 should ask for a short code block, pseudocode, or implementation sketch that can be evaluated as written text.",
                "Questions should test reasoning, tradeoffs, debugging, design, and validation.",
            ],
        },
        "hr_questions": {
            "count": 8,
            "schema": {
                "question_text": "string",
                "keywords": ["string"],
                "resume_context_used": True,
            },
            "rules": [
                "Generate video-call behavioral/HR interview questions.",
                "Use the theme_slate in variation_plan and avoid recent question wording/topics.",
                "If resume text exists, at least three questions must explicitly refer to resume projects/experience.",
                "Questions should invite STAR-style answers and role motivation.",
            ],
        },
    }
    config = schemas[section]
    output_shape = {section: [config["schema"]]}
    rules = "\n".join(f"- {rule}" for rule in config["rules"])
    section_guidance = ""
    if section == "dsa_problems":
        section_guidance = (
            "\nDSA topic plan JSON. Problem numbers and categories are mandatory:\n"
            f"{json.dumps(dsa_topic_plan, ensure_ascii=False)}\n"
            "Each generated problem's category field must exactly match the category for its problem_number.\n"
        )
    repair_guidance = ""
    if candidate_context.get("reflection_feedback"):
        repair_guidance = (
            "\nReviewer repair feedback JSON. You must correct these issues before returning output:\n"
            f"{json.dumps(candidate_context['reflection_feedback'], ensure_ascii=False)}\n"
        )
    planning_guidance = ""
    if candidate_context.get("interview_plan"):
        planning_guidance = (
            "\nUse the planning summary fields from candidate context to choose topics, difficulty, and adaptation intent.\n"
        )
    if candidate_context.get("collaboration_transcript"):
        planning_guidance += (
            "\nRecent multi-agent collaboration transcript JSON. Honor accepted critiques without exposing this private trace:\n"
            f"{json.dumps(candidate_context['collaboration_transcript'], ensure_ascii=False)}\n"
        )
    return [
        {
            "role": "system",
            "content": (
                "You are a senior interview assessment designer. "
                "Generate original content tailored to the candidate context. "
                "Treat variation_plan as mandatory novelty guidance for this run. "
                "Return only valid JSON, with no markdown in the response or inside string values."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Generate exactly {config['count']} items for {section}.\n"
                f"Rules:\n{rules}\n\n"
                f"{section_guidance}\n"
                f"{planning_guidance}\n"
                f"{repair_guidance}\n"
                "Use plain text in every string value. Do not include markdown emphasis markers like **, __, or backticks.\n\n"
                f"Candidate context JSON:\n{json.dumps(prompt_context, ensure_ascii=False)}\n\n"
                f"Return JSON with this exact top-level shape:\n{json.dumps(output_shape, ensure_ascii=False)}"
            ),
        },
    ]


def _build_prompt(interview: dict[str, Any]) -> list[dict[str, str]]:
    candidate_context = _candidate_context(interview)
    candidate_context["package_variation_plan"] = {
        section: _section_variation_plan(candidate_context, section)
        for section in ("dsa_problems", "aptitude_questions", "technical_questions", "hr_questions")
    }
    schema = {
        "dsa_problems": [
            {
                "title": "string",
                "description": "string",
                "difficulty": "easy|medium|hard",
                "examples": [{"input": "string", "output": "string"}],
                "test_cases": [{"name": "string", "input": {}, "expected": "any JSON value"}],
                "constraints": "string",
                "tags": ["string"],
                "required_signals": ["algorithm keyword expected in a plausible solution"],
                "resume_context_used": True,
            }
        ],
        "aptitude_questions": [
            {
                "question_text": "string",
                "options": {"A": "string", "B": "string", "C": "string", "D": "string"},
                "correct_answer": "A|B|C|D",
                "correct_answer_value": "string value of the correct option",
                "category": "string",
                "difficulty": "easy|medium|hard",
                "explanation": "string",
                "resume_context_used": True,
            }
        ],
        "technical_questions": [
            {"question_text": "string", "keywords": ["string"], "resume_context_used": True}
        ],
        "hr_questions": [
            {"question_text": "string", "keywords": ["string"], "resume_context_used": True}
        ],
    }
    return [
        {
            "role": "system",
            "content": (
                "You are a senior technical interviewer and assessment designer. "
                "Generate original interview content, not memorized stock questions. "
                "Treat package_variation_plan as mandatory novelty guidance for this run. "
                "Use the candidate resume/JD/role/difficulty. Return only valid JSON with plain-text string values."
            ),
        },
        {
            "role": "user",
            "content": (
                "Create a complete interview package with exactly 3 DSA problems, "
                "5 aptitude questions, 5 technical video-call questions, and 8 HR video-call questions.\n"
                "Rules:\n"
                "- Every item must be original and tailored to the provided context; do not use stock coding-platform-style titles.\n"
                "- If resume text exists, at least 2 technical and 3 HR questions must explicitly refer to resume projects/experience.\n"
                "- DSA difficulty must match the requested difficulty and the role domain.\n"
                "- DSA problems must be solved by implementing solve(input). input is one JSON object.\n"
                "- DSA problems must include a detailed problem statement, constraints, exactly two sample input/output examples, and executable-style JSON test_cases with expected JSON outputs.\n"
                "- Keep DSA inputs friendly to Python and JavaScript JSON parsing.\n"
                "- Aptitude must include correct_answer, correct_answer_value, and explanation.\n"
                "- Aptitude explanations must prove the selected value and must not contradict the option key or value.\n"
                "- Aptitude options must not include equivalent duplicate values unless the question explicitly accepts both values.\n"
                "- Aptitude ordering questions must specify ascending, descending, chronological, priority, or another concrete rule.\n"
                "- Technical/HR keywords should help score relevance.\n\n"
                "- Do not include markdown emphasis markers like **, __, or backticks inside any string value.\n\n"
                f"Candidate context JSON:\n{json.dumps(candidate_context, ensure_ascii=False)}\n\n"
                f"Return JSON with this shape:\n{json.dumps(schema, ensure_ascii=False)}"
            ),
        },
    ]



async def generate_interview_assets_with_llm(interview: dict[str, Any]) -> dict[str, Any]:
    try:
        role = interview.get("target_role", "Software Engineer")
        difficulty = interview.get("difficulty", "medium")
        topic_plan = _dsa_topic_plan(interview.get("company_style", "product"), difficulty, _variation_seed(interview, "dsa_problems"))
        sections: dict[str, Any] = {}
        logs = []
        for section, agent in [
            ("dsa_problems", "dsa"),
            ("aptitude_questions", "aptitude"),
            ("technical_questions", "technical"),
            ("hr_questions", "hr"),
        ]:
            response = await llm_service.invoke_live(_section_prompt(interview, section), agent=agent)
            try:
                payload = _json_from_text(response.content)
            except Exception as parse_error:
                payload = await _repair_json_response(response.content, parse_error, section, agent)
            sections[section] = payload.get(section)
            logs.append(
                {
                    "type": "success",
                    "agent": f"{agent.title()} Agent",
                    "message": f"Generated {section.replace('_', ' ')} with {response.provider} ({response.model}).",
                    "step": "form" if agent == "dsa" else agent,
                }
            )
        return {
            "dsa_problems": _normalize_dsa(sections.get("dsa_problems"), interview["id"], difficulty, topic_plan),
            "aptitude_questions": _normalize_aptitude(sections.get("aptitude_questions"), interview["id"], difficulty),
            "technical_questions": _normalize_interview_questions(sections.get("technical_questions"), interview["id"], role, difficulty, 5, "technical"),
            "hr_questions": _normalize_interview_questions(sections.get("hr_questions"), interview["id"], role, difficulty, 8, "hr"),
            "logs": logs,
        }
    except HTTPException:
        raise
    except Exception as exc:
        error_text = str(exc).lower()
        if any(token in error_text for token in ["api_key_invalid", "api key not valid", "invalid api key", "invalid_api_key"]):
            raise HTTPException(
                status_code=502,
                detail=(
                    "Live AI interview generation failed because the configured Gemini/Groq API key is invalid. "
                    "Update GEMINI_API_KEY or GROQ_API_KEY in interviewos-backend/.env, then restart the backend."
                ),
            ) from exc
        else:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Live AI interview generation failed. No fallback questions were generated. "
                    "Check provider availability, API keys, network access, and model names."
                ),
            ) from exc
