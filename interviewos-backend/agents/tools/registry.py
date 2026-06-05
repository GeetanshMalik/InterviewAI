from __future__ import annotations

import asyncio
import inspect
from typing import Any

from agents.tools.base import RegisteredTool, ToolCallable, ToolResult, tool_error, tool_success


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        name: str,
        handler: ToolCallable,
        *,
        description: str = "",
        tags: list[str] | None = None,
        replace: bool = False,
    ) -> None:
        if name in self._tools and not replace:
            raise ValueError(f"Tool '{name}' is already registered.")
        self._tools[name] = RegisteredTool(
            name=name,
            handler=handler,
            description=description,
            tags=tags or [],
        )

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        return [tool.public_schema() for tool in self._tools.values()]

    def provider_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        allowed = set(names or self._tools)
        schemas = []
        for tool in self._tools.values():
            if tool.name not in allowed:
                continue
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema(),
                    },
                }
            )
        return schemas

    async def arun(self, name: str, **kwargs: Any) -> ToolResult:
        tool = self.get(name)
        if not tool:
            return tool_error(name, f"Tool '{name}' is not registered.")

        validation_errors = tool.validate_inputs(kwargs)
        if validation_errors:
            return tool_error(
                name,
                "Tool argument validation failed: " + " ".join(validation_errors),
                {"validation_errors": validation_errors},
            )

        try:
            if inspect.iscoroutinefunction(tool.handler):
                result = await tool.handler(**kwargs)
            else:
                result = await asyncio.to_thread(tool.handler, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, ToolResult):
                return result
            if isinstance(result, dict):
                return tool_success(name, result)
            return tool_success(name, {"result": result})
        except Exception as exc:
            return tool_error(name, f"{type(exc).__name__}: {exc}")


default_tool_registry = ToolRegistry()


def register_default_tools(registry: ToolRegistry = default_tool_registry) -> ToolRegistry:
    from agents.evaluation_agent import evaluate_dsa_reasoning_tool, evaluate_round_answer_tool
    from agents.tools.code import evaluate_submission, run_code
    from agents.tools.retrieval import (
        retrieve_generation_history,
        retrieve_memory_context,
        retrieve_practice_history,
        retrieve_reports,
        retrieve_resume,
        retrieve_roadmap,
        write_memory,
    )

    registry.register(
        "run_code",
        run_code,
        description="Execute candidate code against generated test cases through the internal multi-language execution engine.",
        tags=["code", "execution", "evaluation"],
        replace=True,
    )
    registry.register(
        "evaluate_submission",
        evaluate_submission,
        description="Evaluate a DSA submission for a specific generated problem and return score/test evidence.",
        tags=["code", "dsa", "evaluation"],
        replace=True,
    )
    registry.register(
        "retrieve_resume",
        retrieve_resume,
        description="Retrieve uploaded resume records for a user.",
        tags=["retrieval", "resume", "memory"],
        replace=True,
    )
    registry.register(
        "retrieve_reports",
        retrieve_reports,
        description="Retrieve historical interview reports for a user.",
        tags=["retrieval", "report", "memory"],
        replace=True,
    )
    registry.register(
        "retrieve_roadmap",
        retrieve_roadmap,
        description="Retrieve active or historical personalized roadmaps for a user.",
        tags=["retrieval", "roadmap", "memory"],
        replace=True,
    )
    registry.register(
        "retrieve_practice_history",
        retrieve_practice_history,
        description="Retrieve previous practice sessions for a user.",
        tags=["retrieval", "practice", "memory"],
        replace=True,
    )
    registry.register(
        "retrieve_generation_history",
        retrieve_generation_history,
        description="Retrieve previously generated interview questions for a user so generation agents can avoid repetition.",
        tags=["retrieval", "generation", "memory"],
        replace=True,
    )
    registry.register(
        "retrieve_memory_context",
        retrieve_memory_context,
        description="Run semantic memory retrieval over resumes, reports, transcripts, weaknesses, roadmaps, practice, and bot memory.",
        tags=["retrieval", "semantic-memory", "vector"],
        replace=True,
    )
    registry.register(
        "write_memory",
        write_memory,
        description="Write a structured semantic memory record with metadata through the configured memory backend.",
        tags=["memory", "semantic-memory", "write"],
        replace=True,
    )
    registry.register(
        "evaluate_round_answer",
        evaluate_round_answer_tool,
        description="Evaluate Technical or HR answers with structured rubric scores, evidence, safety guardrails, and communication signals.",
        tags=["evaluation", "rubric", "technical", "hr"],
        replace=True,
    )
    registry.register(
        "evaluate_dsa_reasoning",
        evaluate_dsa_reasoning_tool,
        description="Augment DSA execution results with complexity, code quality, and edge-case reasoning analysis.",
        tags=["evaluation", "rubric", "dsa"],
        replace=True,
    )
    return registry


register_default_tools()
