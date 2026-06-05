from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from agents.tools.decision import ToolDecision, ToolExecutionRecord, execute_tool_decision, tool_decision
from agents.tools.registry import ToolRegistry, default_tool_registry
from config import settings
from services.llm import llm_service
from services.security_gateway import security_gateway


@dataclass
class AutonomousToolExecution:
    tool_decisions: list[ToolDecision] = field(default_factory=list)
    tool_results: list[ToolExecutionRecord] = field(default_factory=list)
    provider_metadata: dict[str, Any] = field(default_factory=dict)


async def execute_autonomous_tool_selection(
    *,
    agent: str,
    messages: list[dict[str, Any]],
    available_tools: list[str],
    fallback_decisions: list[ToolDecision] | None = None,
    provider_order: tuple[str, ...] = ("gemini", "groq"),
    registry: ToolRegistry = default_tool_registry,
    max_tool_calls: int = 6,
    max_iterations: int | None = None,
    max_tool_calls_per_iteration: int | None = None,
    max_total_tool_calls: int | None = None,
    max_observation_chars: int = 3000,
) -> AutonomousToolExecution:
    """Run a bounded ReAct tool loop with provider-native calls and deterministic fallback."""

    schemas = registry.provider_schemas(available_tools)
    fallback_decisions = fallback_decisions or []
    max_iterations = max_iterations if max_iterations is not None else int(settings.max_react_iterations)
    max_tool_calls_per_iteration = (
        max_tool_calls_per_iteration
        if max_tool_calls_per_iteration is not None
        else int(settings.max_react_tool_calls_per_iteration)
    )
    max_total_tool_calls = max_total_tool_calls if max_total_tool_calls is not None else int(settings.max_react_total_tool_calls)
    max_total_tool_calls = min(max_total_tool_calls, max_tool_calls)
    if settings.agentic_native_tool_call_enabled:
        max_total_tool_calls = min(max_total_tool_calls, max(0, int(settings.max_remote_calls)))
        max_iterations = min(max_iterations, max(1, int(settings.max_remote_calls)))
    provider_metadata: dict[str, Any] = {
        "mode": "provider_tool_call",
        "afcEnabled": bool(settings.enable_afc),
        "availableTools": available_tools,
        "fallbackUsed": False,
        "reactIterations": 0,
        "maxIterations": max_iterations,
        "maxToolCallsPerIteration": max_tool_calls_per_iteration,
        "maxTotalToolCalls": max_total_tool_calls,
        "maxRemoteCalls": int(settings.max_remote_calls),
        "stopReason": "not_started",
    }

    if not settings.agentic_native_tool_call_enabled or max_total_tool_calls <= 0 or not schemas:
        policy_limit = max_tool_calls if not settings.agentic_native_tool_call_enabled else max(0, max_total_tool_calls)
        provider_metadata.update(
            {
                "mode": "policy",
                "fallbackUsed": True,
                "stopReason": "native_tool_call_disabled_or_not_needed",
            }
        )
        records = [
            await execute_tool_decision(decision, registry)
            for decision in fallback_decisions[: max(0, policy_limit)]
            if decision.get("tool") in available_tools
        ]
        return AutonomousToolExecution(fallback_decisions[: max(0, policy_limit)], records, provider_metadata)

    try:
        loop_messages = list(messages)
        decisions: list[ToolDecision] = []
        records: list[ToolExecutionRecord] = []
        total_calls = 0
        seen_calls: set[str] = set()

        total_timeout = max(1.0, float(settings.agentic_tool_call_total_timeout_seconds))
        iteration_timeout = max(0.5, float(settings.agentic_tool_call_timeout_seconds))
        deadline = asyncio.get_running_loop().time() + total_timeout

        for iteration in range(1, max(0, max_iterations) + 1):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                provider_metadata["stopReason"] = "total_timeout"
                break
            response = await asyncio.wait_for(
                llm_service.invoke_with_tools(
                    loop_messages,
                    schemas,
                    agent=agent,
                    provider_order=provider_order,
                ),
                timeout=min(iteration_timeout, remaining),
            )
            provider_metadata.update(
                {
                    "provider": response.provider,
                    "model": response.model,
                    "providerContent": response.content,
                    "reactIterations": iteration,
                    "toolCallCount": provider_metadata.get("toolCallCount", 0) + len(response.tool_calls),
                }
            )
            if not response.tool_calls:
                provider_metadata["stopReason"] = "provider_final_answer"
                break

            iteration_calls = 0
            for call in response.tool_calls:
                if iteration_calls >= max_tool_calls_per_iteration:
                    provider_metadata["stopReason"] = "iteration_tool_call_cap"
                    break
                if total_calls >= max_total_tool_calls:
                    provider_metadata["stopReason"] = "total_tool_call_cap"
                    break

                name = str(call.get("name") or "")
                if name not in available_tools:
                    loop_messages.append(
                        {
                            "role": "user",
                            "content": f"Tool observation: rejected disallowed tool '{name}'. Use only {available_tools}.",
                        }
                    )
                    continue
                args = call.get("args") if isinstance(call.get("args"), dict) else {}
                call_signature = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
                if call_signature in seen_calls:
                    provider_metadata["stopReason"] = "duplicate_tool_call"
                    loop_messages.append(
                        {
                            "role": "user",
                            "content": f"Tool observation: duplicate tool call for '{name}' with the same arguments was skipped.",
                        }
                    )
                    break
                seen_calls.add(call_signature)

                decision = tool_decision(
                    agent,
                    name,
                    f"Provider-native ReAct tool call selected by {response.provider} on iteration {iteration}.",
                    args,
                    required=False,
                    selection_mode="provider_tool_call",
                )
                record = await execute_tool_decision(decision, registry)
                decisions.append(decision)
                records.append(record)
                iteration_calls += 1
                total_calls += 1

                observation_payload = {
                    "tool": name,
                    "ok": record.get("ok"),
                    "data": record.get("data", {}),
                    "error": record.get("error"),
                    "metadata": record.get("metadata", {}),
                }
                sanitized = security_gateway.sanitize_text(
                    json.dumps(observation_payload, ensure_ascii=False),
                    source=f"react_observation.{agent}.{name}",
                    limit=max_observation_chars,
                )
                loop_messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Tool observation for {name} on iteration {iteration}:\n"
                            f"{sanitized.clean_text}\n"
                            "Decide whether another allowed tool is needed or finish."
                        ),
                    }
                )

            if total_calls >= max_total_tool_calls:
                provider_metadata["stopReason"] = "total_tool_call_cap"
                break
            if provider_metadata.get("stopReason") == "duplicate_tool_call":
                break
            if provider_metadata.get("stopReason") == "iteration_tool_call_cap":
                continue

        if provider_metadata.get("stopReason") == "not_started":
            provider_metadata["stopReason"] = "max_iterations"
        return AutonomousToolExecution(decisions, records, provider_metadata)
    except Exception as exc:
        provider_metadata.update(
            {
                "mode": "policy",
                "fallbackUsed": True,
                "providerError": f"{type(exc).__name__}: {exc}",
                "stopReason": "provider_error_policy_fallback",
            }
        )
        records = [
            await execute_tool_decision(decision, registry)
            for decision in fallback_decisions[: max(0, max_total_tool_calls)]
            if decision.get("tool") in available_tools
        ]
        return AutonomousToolExecution(fallback_decisions, records, provider_metadata)


async def execute_policy_tool_selection(
    *,
    agent: str,
    available_tools: list[str],
    fallback_decisions: list[ToolDecision] | None = None,
    registry: ToolRegistry = default_tool_registry,
    max_tool_calls: int = 3,
    stop_reason: str = "fast_generation_profile_policy",
) -> AutonomousToolExecution:
    """Execute deterministic fallback decisions without an LLM tool-selection call."""

    fallback_decisions = fallback_decisions or []
    selected = [
        decision
        for decision in fallback_decisions[: max(0, max_tool_calls)]
        if decision.get("tool") in available_tools
    ]
    records = [await execute_tool_decision(decision, registry) for decision in selected]
    return AutonomousToolExecution(
        selected,
        records,
        {
            "mode": "policy",
            "fallbackUsed": True,
            "availableTools": available_tools,
            "stopReason": stop_reason,
            "toolCallCount": len(selected),
            "maxTotalToolCalls": max_tool_calls,
        },
    )
