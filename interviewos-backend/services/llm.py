from dataclasses import dataclass
import asyncio
import json
import logging
import time
from typing import Any

from config import settings
from services.llm_optimization import (
    LLMCallMetric,
    estimate_tokens,
    is_non_retryable_llm_error,
    llm_usage_metrics,
    normalize_agent_name,
    prepare_messages_for_budget,
    prompt_cache,
    prompt_cache_key,
    provider_circuit_breaker,
    provider_request_scheduler,
)


logger = logging.getLogger("interviewos.llm")


def _configured_provider_order(value: str | None) -> tuple[str, ...]:
    providers = []
    for raw in str(value or "").split(","):
        provider = raw.strip().lower()
        if provider in {"gemini", "groq"} and provider not in providers:
            providers.append(provider)
    return tuple(providers or ["gemini", "groq"])


DEFAULT_PROVIDER_ORDER = _configured_provider_order(settings.llm_provider_order)


@dataclass
class LLMResponse:
    content: str
    provider: str
    model: str
    input_tokens: int = 0
    cache_hit: bool = False
    truncated: bool = False
    request_count: int = 0


@dataclass
class LLMStreamChunk:
    event: str
    content: str
    provider: str
    model: str


@dataclass
class LLMToolResponse:
    content: str
    provider: str
    model: str
    tool_calls: list[dict[str, Any]]
    input_tokens: int = 0
    cache_hit: bool = False
    truncated: bool = False
    request_count: int = 0


class LLMService:
    def __init__(self) -> None:
        self._gemini = {}
        self._groq = {}

    def _messages(self, messages: list[dict[str, Any]] | str) -> list[tuple[str, str]]:
        if isinstance(messages, str):
            return [("human", messages)]

        converted = []
        for message in messages:
            role = message.get("role", "user")
            content = str(message.get("content", ""))
            if role == "assistant":
                converted.append(("ai", content))
            elif role == "system":
                converted.append(("system", content))
            else:
                converted.append(("human", content))
        return converted

    def _content_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(item))
            return "\n".join(part for part in parts if part)
        return str(content)

    def _fallback(self, messages: list[dict[str, Any]] | str) -> LLMResponse:
        if isinstance(messages, str):
            prompt = messages
        else:
            prompt = " ".join(str(message.get("content", "")) for message in messages[-3:])

        content = (
            "Based on your InterviewOS history, focus on one measurable weakness, "
            "practice it daily, and review mistakes immediately. "
            f"Context considered: {prompt[:240]}"
        )
        return LLMResponse(content=content, provider="local-fallback", model="deterministic")

    def _extract_tool_calls(self, response: Any) -> list[dict[str, Any]]:
        raw_calls = getattr(response, "tool_calls", None) or []
        additional = getattr(response, "additional_kwargs", {}) or {}
        raw_calls = raw_calls or additional.get("tool_calls", []) or []
        calls: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_calls):
            call_id = None
            name = None
            args: Any = {}
            if isinstance(raw, dict):
                call_id = raw.get("id") or f"tool-call-{index}"
                name = raw.get("name")
                args = raw.get("args") or raw.get("arguments") or {}
                function = raw.get("function")
                if isinstance(function, dict):
                    name = name or function.get("name")
                    args = function.get("arguments", args)
            else:
                call_id = getattr(raw, "id", None) or f"tool-call-{index}"
                name = getattr(raw, "name", None)
                args = getattr(raw, "args", {}) or getattr(raw, "arguments", {}) or {}
                function = getattr(raw, "function", None)
                if function is not None:
                    name = name or getattr(function, "name", None)
                    args = getattr(function, "arguments", args)

            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if name:
                calls.append({"id": str(call_id), "name": str(name), "args": args if isinstance(args, dict) else {}})
        return calls

    def _agent_key(self, agent: str | None, provider: str, *, allow_agent_key: bool = True) -> str | None:
        normalized_agent = normalize_agent_name(agent)
        if normalized_agent and normalized_agent != "default":
            key = getattr(settings, f"{normalized_agent}_{provider}_api_key", None) if allow_agent_key else None
            if key:
                return key
        return getattr(settings, f"{provider}_api_key", None)

    def _gemini_client(self, agent: str | None = None):
        api_key = self._agent_key(agent, "gemini")
        if not api_key:
            return None
        cache_key = (normalize_agent_name(agent), settings.gemini_model, api_key)
        if cache_key not in self._gemini:
            from langchain_google_genai import ChatGoogleGenerativeAI

            self._gemini[cache_key] = ChatGoogleGenerativeAI(
                model=settings.gemini_model,
                api_key=api_key,
                temperature=0.4,
                max_retries=1,
            )
        return self._gemini[cache_key]

    def _groq_client(self, agent: str | None = None):
        api_key = self._agent_key(agent, "groq")
        if not api_key:
            return None
        cache_key = (normalize_agent_name(agent), settings.groq_model, api_key)
        if cache_key not in self._groq:
            from langchain_groq import ChatGroq

            self._groq[cache_key] = ChatGroq(
                model=settings.groq_model,
                api_key=api_key,
                temperature=0.4,
                max_retries=1,
            )
        return self._groq[cache_key]

    def _provider_client(self, provider: str, agent: str | None = None):
        if provider == "gemini":
            return self._gemini_client(agent), settings.gemini_model
        if provider == "groq":
            return self._groq_client(agent), settings.groq_model
        return None, ""

    def _unique_providers(self, provider_order: tuple[str, ...]) -> tuple[str, ...]:
        unique: list[str] = []
        for provider in provider_order:
            if provider not in unique:
                unique.append(provider)
        return tuple(unique)

    def _record_metric(
        self,
        *,
        agent: str | None,
        operation: str,
        provider: str,
        model: str,
        input_tokens: int,
        output: str = "",
        started_at: float,
        cache_hit: bool = False,
        fallback_used: bool = False,
        truncated: bool = False,
        error_type: str = "",
        request_count: int = 0,
        afc_calls: int = 0,
        cooldown_active: bool = False,
        retry_avoided: bool = False,
        queued_ms: float = 0.0,
    ) -> None:
        llm_usage_metrics.record(
            LLMCallMetric(
                timestamp=time.time(),
                agent=normalize_agent_name(agent),
                operation=operation,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=estimate_tokens(output),
                latency_ms=round((time.perf_counter() - started_at) * 1000, 2),
                cache_hit=cache_hit,
                fallback_used=fallback_used,
                truncated=truncated,
                error_type=error_type,
                request_count=request_count,
                afc_calls=afc_calls,
                cooldown_active=cooldown_active,
                retry_avoided=retry_avoided,
                queued_ms=queued_ms,
            )
        )

    def _record_cooldown_skip(
        self,
        *,
        agent: str | None,
        operation: str,
        provider: str,
        model: str,
        input_tokens: int,
        started_at: float,
        truncated: bool,
    ) -> None:
        llm_usage_metrics.increment("cooldownSkips")
        self._record_metric(
            agent=agent,
            operation=operation,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            started_at=started_at,
            truncated=truncated,
            error_type="provider_cooldown",
            cooldown_active=True,
            request_count=0,
        )

    async def invoke(self, messages: list[dict[str, Any]] | str) -> LLMResponse:
        """Configured provider-order LLM call with local fallback."""

        started = time.perf_counter()
        budgeted = prepare_messages_for_budget(messages, operation="invoke")
        cache_key = prompt_cache_key(operation="invoke", agent=None, messages=budgeted.messages)
        cached = await prompt_cache.get(cache_key)
        if cached:
            content = str(cached.get("content", ""))
            self._record_metric(
                agent=None,
                operation="invoke",
                provider=str(cached.get("provider", "cache")),
                model=str(cached.get("model", "cache")),
                input_tokens=budgeted.final_tokens,
                output=content,
                started_at=started,
                cache_hit=True,
                truncated=budgeted.truncated,
            )
            return LLMResponse(
                content=content,
                provider=str(cached.get("provider", "cache")),
                model=str(cached.get("model", "cache")),
                input_tokens=budgeted.final_tokens,
                cache_hit=True,
                truncated=budgeted.truncated,
            )

        lc_messages = self._messages(budgeted.messages)
        call_timeout = max(1.0, float(settings.llm_legacy_call_timeout_seconds))

        for provider in self._unique_providers(DEFAULT_PROVIDER_ORDER):
            client, model = self._provider_client(provider)
            if client is None:
                continue
            if not provider_circuit_breaker.is_available(None, provider):
                logger.warning("%s provider is cooling down; skipping invoke fallback slot.", provider.title())
                self._record_cooldown_skip(
                    agent=None,
                    operation="invoke",
                    provider=provider,
                    model=model,
                    input_tokens=budgeted.final_tokens,
                    started_at=started,
                    truncated=budgeted.truncated,
                )
                continue
            try:
                async with provider_request_scheduler.slot(agent=None, provider=provider, operation="invoke") as queued_ms:
                    response = await asyncio.wait_for(client.ainvoke(lc_messages), timeout=call_timeout)
                content = self._content_text(response.content)
                provider_circuit_breaker.record_success(None, provider)
                await prompt_cache.set(cache_key, {"content": content, "provider": provider, "model": model})
                self._record_metric(
                    agent=None,
                    operation="invoke",
                    provider=provider,
                    model=model,
                    input_tokens=budgeted.final_tokens,
                    output=content,
                    started_at=started,
                    truncated=budgeted.truncated,
                    request_count=1,
                    queued_ms=queued_ms,
                )
                return LLMResponse(
                    content=content,
                    provider=provider,
                    model=model,
                    input_tokens=budgeted.final_tokens,
                    truncated=budgeted.truncated,
                    request_count=1,
                )
            except Exception as exc:
                provider_circuit_breaker.record_failure(None, provider, exc)
                retry_avoided = is_non_retryable_llm_error(exc)
                if retry_avoided:
                    llm_usage_metrics.increment("retriesAvoided")
                self._record_metric(
                    agent=None,
                    operation="invoke",
                    provider=provider,
                    model=model,
                    input_tokens=budgeted.final_tokens,
                    started_at=started,
                    truncated=budgeted.truncated,
                    error_type=type(exc).__name__,
                    request_count=1,
                    retry_avoided=retry_avoided,
                )
                logger.warning("%s provider failed; falling back once. %s: %s", provider.title(), type(exc).__name__, exc)

        fallback = self._fallback(budgeted.messages)
        self._record_metric(
            agent=None,
            operation="invoke",
            provider=fallback.provider,
            model=fallback.model,
            input_tokens=budgeted.final_tokens,
            output=fallback.content,
            started_at=started,
            fallback_used=True,
            truncated=budgeted.truncated,
        )
        return fallback

    async def invoke_live(
        self,
        messages: list[dict[str, Any]] | str,
        agent: str | None = None,
        provider_order: tuple[str, ...] = DEFAULT_PROVIDER_ORDER,
    ) -> LLMResponse:
        """Live LLM call with configurable provider order and no local fake fallback."""

        started = time.perf_counter()
        budgeted = prepare_messages_for_budget(messages, agent=agent, operation="invoke_live")
        cache_key = prompt_cache_key(operation="invoke_live", agent=agent, messages=budgeted.messages)
        cached = await prompt_cache.get(cache_key)
        if cached:
            content = str(cached.get("content", ""))
            self._record_metric(
                agent=agent,
                operation="invoke_live",
                provider=str(cached.get("provider", "cache")),
                model=str(cached.get("model", "cache")),
                input_tokens=budgeted.final_tokens,
                output=content,
                started_at=started,
                cache_hit=True,
                truncated=budgeted.truncated,
            )
            return LLMResponse(
                content=content,
                provider=str(cached.get("provider", "cache")),
                model=str(cached.get("model", "cache")),
                input_tokens=budgeted.final_tokens,
                cache_hit=True,
                truncated=budgeted.truncated,
            )

        lc_messages = self._messages(budgeted.messages)
        errors: list[str] = []
        configured_provider = False
        call_timeout = max(1.0, float(settings.llm_live_call_timeout_seconds))

        for provider in self._unique_providers(provider_order):
            client, model = self._provider_client(provider, agent)
            if not model:
                errors.append(f"Unknown provider: {provider}")
                continue

            if client is None:
                continue

            configured_provider = True
            if not provider_circuit_breaker.is_available(agent, provider):
                remaining = provider_circuit_breaker.cooldown_remaining(agent, provider)
                errors.append(
                    f"{provider.title()} provider is cooling down for {normalize_agent_name(agent)} "
                    f"({round(remaining, 1)}s remaining)."
                )
                self._record_cooldown_skip(
                    agent=agent,
                    operation="invoke_live",
                    provider=provider,
                    model=model,
                    input_tokens=budgeted.final_tokens,
                    started_at=started,
                    truncated=budgeted.truncated,
                )
                continue
            try:
                async with provider_request_scheduler.slot(agent=agent, provider=provider, operation="invoke_live") as queued_ms:
                    response = await asyncio.wait_for(client.ainvoke(lc_messages), timeout=call_timeout)
                content = self._content_text(response.content)
                provider_circuit_breaker.record_success(agent, provider)
                await prompt_cache.set(cache_key, {"content": content, "provider": provider, "model": model})
                self._record_metric(
                    agent=agent,
                    operation="invoke_live",
                    provider=provider,
                    model=model,
                    input_tokens=budgeted.final_tokens,
                    output=content,
                    started_at=started,
                    truncated=budgeted.truncated,
                    request_count=1,
                    queued_ms=queued_ms,
                )
                return LLMResponse(
                    content=content,
                    provider=provider,
                    model=model,
                    input_tokens=budgeted.final_tokens,
                    truncated=budgeted.truncated,
                    request_count=1,
                )
            except Exception as exc:
                provider_circuit_breaker.record_failure(agent, provider, exc)
                retry_avoided = is_non_retryable_llm_error(exc)
                if retry_avoided:
                    llm_usage_metrics.increment("retriesAvoided")
                self._record_metric(
                    agent=agent,
                    operation="invoke_live",
                    provider=provider,
                    model=model,
                    input_tokens=budgeted.final_tokens,
                    started_at=started,
                    truncated=budgeted.truncated,
                    error_type=type(exc).__name__,
                    request_count=1,
                    retry_avoided=retry_avoided,
                )
                logger.warning("%s provider failed. %s: %s", provider.title(), type(exc).__name__, exc)
                errors.append(f"{provider.title()} {type(exc).__name__}: {exc}")
                if is_non_retryable_llm_error(exc):
                    errors.append(f"{provider.title()} marked non-retryable for this attempt.")

        if not configured_provider:
            raise RuntimeError("No live AI provider is configured. Add GEMINI_API_KEY or GROQ_API_KEY.")

        self._record_metric(
            agent=agent,
            operation="invoke_live",
            provider="none",
            model="none",
            input_tokens=budgeted.final_tokens,
            started_at=started,
            truncated=budgeted.truncated,
            error_type="provider_failure",
        )
        raise RuntimeError("Live AI generation failed. " + " | ".join(errors[-2:]))

    async def invoke_with_tools(
        self,
        messages: list[dict[str, Any]] | str,
        tools: list[dict[str, Any]],
        agent: str | None = None,
        provider_order: tuple[str, ...] = DEFAULT_PROVIDER_ORDER,
    ) -> LLMToolResponse:
        """Invoke a provider with native tool schemas and return requested tool calls."""

        if not settings.agentic_native_tool_call_enabled:
            raise RuntimeError("Provider-native tool calling is disabled by AGENTIC_NATIVE_TOOL_CALL_ENABLED=false.")

        started = time.perf_counter()
        budgeted = prepare_messages_for_budget(messages, agent=agent, operation="invoke_with_tools")
        cache_key = prompt_cache_key(operation="invoke_with_tools", agent=agent, messages=budgeted.messages, tools=tools)
        cached = await prompt_cache.get(cache_key)
        if cached:
            content = str(cached.get("content", ""))
            self._record_metric(
                agent=agent,
                operation="invoke_with_tools",
                provider=str(cached.get("provider", "cache")),
                model=str(cached.get("model", "cache")),
                input_tokens=budgeted.final_tokens,
                output=content,
                started_at=started,
                cache_hit=True,
                truncated=budgeted.truncated,
            )
            return LLMToolResponse(
                content=content,
                provider=str(cached.get("provider", "cache")),
                model=str(cached.get("model", "cache")),
                tool_calls=list(cached.get("tool_calls", [])),
                input_tokens=budgeted.final_tokens,
                cache_hit=True,
                truncated=budgeted.truncated,
            )

        lc_messages = self._messages(budgeted.messages)
        errors: list[str] = []
        configured_provider = False

        for provider in self._unique_providers(provider_order):
            client, model = self._provider_client(provider, agent)
            if not model:
                errors.append(f"Unknown provider: {provider}")
                continue

            if client is None:
                continue
            configured_provider = True
            if provider == "gemini" and not settings.enable_afc:
                llm_usage_metrics.increment("afcDisabledSkips")
                errors.append("Gemini AFC/native tool calling is disabled by ENABLE_AFC=false.")
                self._record_metric(
                    agent=agent,
                    operation="invoke_with_tools",
                    provider=provider,
                    model=model,
                    input_tokens=budgeted.final_tokens,
                    started_at=started,
                    truncated=budgeted.truncated,
                    error_type="afc_disabled",
                    request_count=0,
                    afc_calls=0,
                )
                continue
            if not provider_circuit_breaker.is_available(agent, provider):
                remaining = provider_circuit_breaker.cooldown_remaining(agent, provider)
                errors.append(
                    f"{provider.title()} provider is cooling down for {normalize_agent_name(agent)} "
                    f"({round(remaining, 1)}s remaining)."
                )
                self._record_cooldown_skip(
                    agent=agent,
                    operation="invoke_with_tools",
                    provider=provider,
                    model=model,
                    input_tokens=budgeted.final_tokens,
                    started_at=started,
                    truncated=budgeted.truncated,
                )
                continue
            if not hasattr(client, "bind_tools"):
                errors.append(f"{provider.title()} client does not expose bind_tools.")
                continue

            try:
                bound = client.bind_tools(tools)
                async with provider_request_scheduler.slot(agent=agent, provider=provider, operation="invoke_with_tools") as queued_ms:
                    response = await asyncio.wait_for(
                        bound.ainvoke(lc_messages),
                        timeout=max(0.5, float(settings.agentic_tool_call_timeout_seconds)),
                    )
                content = self._content_text(getattr(response, "content", ""))
                tool_calls = self._extract_tool_calls(response)
                provider_circuit_breaker.record_success(agent, provider)
                await prompt_cache.set(
                    cache_key,
                    {"content": content, "provider": provider, "model": model, "tool_calls": tool_calls},
                )
                self._record_metric(
                    agent=agent,
                    operation="invoke_with_tools",
                    provider=provider,
                    model=model,
                    input_tokens=budgeted.final_tokens,
                    output=content,
                    started_at=started,
                    truncated=budgeted.truncated,
                    request_count=1,
                    afc_calls=1 if provider == "gemini" else 0,
                    queued_ms=queued_ms,
                )
                return LLMToolResponse(
                    content=content,
                    provider=provider,
                    model=model,
                    tool_calls=tool_calls,
                    input_tokens=budgeted.final_tokens,
                    truncated=budgeted.truncated,
                    request_count=1,
                )
            except Exception as exc:
                provider_circuit_breaker.record_failure(agent, provider, exc)
                retry_avoided = is_non_retryable_llm_error(exc)
                if retry_avoided:
                    llm_usage_metrics.increment("retriesAvoided")
                self._record_metric(
                    agent=agent,
                    operation="invoke_with_tools",
                    provider=provider,
                    model=model,
                    input_tokens=budgeted.final_tokens,
                    started_at=started,
                    truncated=budgeted.truncated,
                    error_type=type(exc).__name__,
                    request_count=1,
                    afc_calls=1 if provider == "gemini" else 0,
                    retry_avoided=retry_avoided,
                )
                logger.warning("%s provider tool call failed. %s: %s", provider.title(), type(exc).__name__, exc)
                errors.append(f"{provider.title()} {type(exc).__name__}: {exc}")

        if not configured_provider:
            raise RuntimeError("No live AI provider is configured. Add GEMINI_API_KEY or GROQ_API_KEY.")
        self._record_metric(
            agent=agent,
            operation="invoke_with_tools",
            provider="none",
            model="none",
            input_tokens=budgeted.final_tokens,
            started_at=started,
            truncated=budgeted.truncated,
            error_type="provider_tool_failure",
        )
        raise RuntimeError("Live AI tool calling failed. " + " | ".join(errors[-2:]))

    async def stream_live(
        self,
        messages: list[dict[str, Any]] | str,
        agent: str | None = None,
        provider_order: tuple[str, ...] = DEFAULT_PROVIDER_ORDER,
    ):
        """Provider token stream with the same provider ordering as invoke_live."""

        started = time.perf_counter()
        budgeted = prepare_messages_for_budget(messages, agent=agent, operation="stream_live")
        lc_messages = self._messages(budgeted.messages)
        errors: list[str] = []
        configured_provider = False
        call_timeout = max(1.0, float(settings.llm_live_call_timeout_seconds))

        for provider in self._unique_providers(provider_order):
            client, model = self._provider_client(provider, agent)
            if not model:
                errors.append(f"Unknown provider: {provider}")
                continue

            if client is None:
                continue

            configured_provider = True
            if not provider_circuit_breaker.is_available(agent, provider):
                remaining = provider_circuit_breaker.cooldown_remaining(agent, provider)
                errors.append(
                    f"{provider.title()} provider is cooling down for {normalize_agent_name(agent)} "
                    f"({round(remaining, 1)}s remaining)."
                )
                self._record_cooldown_skip(
                    agent=agent,
                    operation="stream_live",
                    provider=provider,
                    model=model,
                    input_tokens=budgeted.final_tokens,
                    started_at=started,
                    truncated=budgeted.truncated,
                )
                continue
            try:
                async with provider_request_scheduler.slot(agent=agent, provider=provider, operation="stream_live") as queued_ms:
                    yield LLMStreamChunk(event="start", content="", provider=provider, model=model)
                    chunks: list[str] = []
                    if hasattr(client, "astream"):
                        async with asyncio.timeout(call_timeout):
                            async for chunk in client.astream(lc_messages):
                                content = self._content_text(getattr(chunk, "content", ""))
                                if not content:
                                    continue
                                chunks.append(content)
                                yield LLMStreamChunk(event="token", content=content, provider=provider, model=model)
                    else:
                        response = await asyncio.wait_for(client.ainvoke(lc_messages), timeout=call_timeout)
                        content = self._content_text(response.content)
                        if content:
                            chunks.append(content)
                            yield LLMStreamChunk(event="token", content=content, provider=provider, model=model)
                yield LLMStreamChunk(event="done", content="".join(chunks), provider=provider, model=model)
                provider_circuit_breaker.record_success(agent, provider)
                self._record_metric(
                    agent=agent,
                    operation="stream_live",
                    provider=provider,
                    model=model,
                    input_tokens=budgeted.final_tokens,
                    output="".join(chunks),
                    started_at=started,
                    truncated=budgeted.truncated,
                    request_count=1,
                    queued_ms=queued_ms,
                )
                return
            except Exception as exc:
                provider_circuit_breaker.record_failure(agent, provider, exc)
                retry_avoided = is_non_retryable_llm_error(exc)
                if retry_avoided:
                    llm_usage_metrics.increment("retriesAvoided")
                self._record_metric(
                    agent=agent,
                    operation="stream_live",
                    provider=provider,
                    model=model,
                    input_tokens=budgeted.final_tokens,
                    started_at=started,
                    truncated=budgeted.truncated,
                    error_type=type(exc).__name__,
                    request_count=1,
                    retry_avoided=retry_avoided,
                )
                logger.warning("%s stream failed. %s: %s", provider.title(), type(exc).__name__, exc)
                errors.append(f"{provider.title()} {type(exc).__name__}: {exc}")

        if not configured_provider:
            raise RuntimeError("No live AI provider is configured. Add GEMINI_API_KEY or GROQ_API_KEY.")

        raise RuntimeError("Live AI streaming failed. " + " | ".join(errors[-2:]))


llm_service = LLMService()
