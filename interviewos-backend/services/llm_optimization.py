from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import logging
import re
import time
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass
from typing import Any

from config import settings


logger = logging.getLogger("interviewos.llm.optimization")


class LLMBudgetExceeded(RuntimeError):
    pass


AGENT_ALIASES = {
    "ai consultant bot agent": "bot",
    "aptitude agent": "aptitude",
    "bot": "bot",
    "critic agent": "evaluation",
    "dsa agent": "dsa",
    "evaluation agent": "evaluation",
    "hr agent": "hr",
    "hr interview agent": "hr",
    "memory agent": "memory",
    "planning": "planning",
    "planning agent": "planning",
    "practice agent": "practice",
    "report agent": "report",
    "resume agent": "resume",
    "reviewer agent": "reviewer",
    "roadmap agent": "roadmap",
    "technical agent": "technical",
    "technical interview agent": "technical",
    "workflow orchestrator agent": "planning",
}


@dataclass
class PromptBudgetResult:
    messages: list[dict[str, Any]]
    original_tokens: int
    final_tokens: int
    budget_tokens: int
    truncated: bool


@dataclass
class CacheEntry:
    value: dict[str, Any]
    expires_at: float


@dataclass
class ProviderFailure:
    failures: int = 0
    cooldown_until: float = 0
    last_error: str = ""


@dataclass
class LLMCallMetric:
    timestamp: float
    agent: str
    operation: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cache_hit: bool = False
    fallback_used: bool = False
    truncated: bool = False
    error_type: str = ""
    request_count: int = 0
    afc_calls: int = 0
    cooldown_active: bool = False
    retry_avoided: bool = False
    queued_ms: float = 0.0


def normalize_agent_name(agent: str | None) -> str:
    if not agent:
        return "default"
    normalized = re.sub(r"\s+", " ", str(agent).replace("_", " ").replace("-", " ")).strip().lower()
    normalized = normalized.removesuffix(" provider")
    return AGENT_ALIASES.get(normalized, normalized.replace(" ", "_"))


def estimate_tokens(text: Any) -> int:
    if text is None:
        return 0
    if not isinstance(text, str):
        try:
            text = json.dumps(text, ensure_ascii=False, default=str)
        except Exception:
            text = str(text)
    if not text:
        return 0
    # Conservative enough for quota protection without pulling in provider tokenizers.
    wordish = len(re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE))
    charish = max(1, len(text) // 4)
    return max(charish, int(wordish * 1.25))


def estimate_messages_tokens(messages: list[dict[str, Any]] | str) -> int:
    if isinstance(messages, str):
        return estimate_tokens(messages)
    return sum(estimate_tokens(message.get("content", "")) + 4 for message in messages)


def truncate_text_to_tokens(text: str, max_tokens: int) -> str:
    if estimate_tokens(text) <= max_tokens:
        return text
    max_chars = max(240, int(max_tokens * 3.6))
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.72)
    tail = max_chars - head - 120
    return (
        text[:head].rstrip()
        + "\n\n[...context compressed by InterviewOS token guard...]\n\n"
        + text[-tail:].lstrip()
    )


def agent_context_budget(agent: str | None) -> int:
    alias = normalize_agent_name(agent)
    specific = getattr(settings, f"llm_max_input_tokens_{alias}", None)
    if isinstance(specific, int) and specific > 0:
        return specific
    return int(settings.llm_max_input_tokens_default)


def prepare_messages_for_budget(
    messages: list[dict[str, Any]] | str,
    *,
    agent: str | None = None,
    operation: str = "invoke",
    budget_tokens: int | None = None,
) -> PromptBudgetResult:
    budget = int(budget_tokens or agent_context_budget(agent))
    if isinstance(messages, str):
        original = estimate_tokens(messages)
        text = truncate_text_to_tokens(messages, budget)
        final = estimate_tokens(text)
        if final > budget:
            raise LLMBudgetExceeded(
                f"{operation} prompt for {normalize_agent_name(agent)} is {final} estimated tokens after truncation; budget is {budget}."
            )
        return PromptBudgetResult(
            messages=[{"role": "user", "content": text}],
            original_tokens=original,
            final_tokens=final,
            budget_tokens=budget,
            truncated=final < original,
        )

    normalized = [
        {"role": str(message.get("role", "user")), "content": str(message.get("content", ""))}
        for message in messages
    ]
    original = estimate_messages_tokens(normalized)
    if original <= budget:
        return PromptBudgetResult(normalized, original, original, budget, False)

    system_messages = [message for message in normalized if message["role"] == "system"]
    non_system = [message for message in normalized if message["role"] != "system"]
    kept: list[dict[str, Any]] = []
    remaining = budget
    truncated = True

    for system in system_messages[:2]:
        allowance = min(900, max(220, remaining // 5))
        content = truncate_text_to_tokens(system["content"], allowance)
        kept.append({"role": "system", "content": content})
        remaining -= estimate_tokens(content) + 4

    compression_note = {
        "role": "system",
        "content": (
            "InterviewOS token guard compressed this request. Use only the retained task-specific context, "
            "summaries, and retrieved memory slices; do not assume omitted raw history."
        ),
    }
    kept.append(compression_note)
    remaining -= estimate_tokens(compression_note["content"]) + 4

    for message in reversed(non_system):
        if remaining <= 120:
            break
        allowance = min(max(120, remaining - 40), max(300, remaining))
        content = truncate_text_to_tokens(message["content"], allowance)
        cost = estimate_tokens(content) + 4
        if cost <= remaining:
            kept.insert(len(system_messages[:2]) + 1, {"role": message["role"], "content": content})
            remaining -= cost
        else:
            content = truncate_text_to_tokens(message["content"], max(80, remaining - 8))
            kept.insert(len(system_messages[:2]) + 1, {"role": message["role"], "content": content})
            remaining = 0
            break

    final = estimate_messages_tokens(kept)
    if final > budget:
        # Last defensive pass keeps the latest user payload and drops any older non-system payload.
        latest_user = next((message for message in reversed(non_system) if message["role"] == "user"), non_system[-1] if non_system else {"role": "user", "content": ""})
        system_text = truncate_text_to_tokens("\n".join(message["content"] for message in system_messages[:2]), min(800, budget // 4))
        latest_text = truncate_text_to_tokens(latest_user["content"], max(120, budget - estimate_tokens(system_text) - 80))
        kept = [
            {"role": "system", "content": system_text},
            compression_note,
            {"role": "user", "content": latest_text},
        ]
        final = estimate_messages_tokens(kept)
    if final > budget:
        raise LLMBudgetExceeded(
            f"{operation} prompt for {normalize_agent_name(agent)} is {final} estimated tokens after truncation; budget is {budget}."
        )
    return PromptBudgetResult(kept, original, final, budget, truncated)


def _stable_payload(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def prompt_cache_key(*, operation: str, agent: str | None, messages: list[dict[str, Any]], tools: Any = None) -> str:
    payload = {
        "operation": operation,
        "agent": normalize_agent_name(agent),
        "messages": messages,
        "tools": tools or [],
    }
    return hashlib.sha256(_stable_payload(payload).encode("utf-8")).hexdigest()


def generic_cache_key(namespace: str, payload: Any) -> str:
    return f"{namespace}:{hashlib.sha256(_stable_payload(payload).encode('utf-8')).hexdigest()}"


class PromptCache:
    def __init__(self, max_items: int = 512) -> None:
        self._items: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max_items = max_items

    async def get(self, key: str) -> dict[str, Any] | None:
        if not settings.llm_prompt_cache_enabled:
            return None
        item = self._items.get(key)
        now = time.time()
        if not item or item.expires_at <= now:
            self._items.pop(key, None)
            return None
        self._items.move_to_end(key)
        return dict(item.value)

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int | None = None) -> None:
        if not settings.llm_prompt_cache_enabled:
            return
        ttl = int(ttl_seconds or settings.llm_prompt_cache_ttl_seconds)
        if ttl <= 0:
            return
        self._items[key] = CacheEntry(dict(value), time.time() + ttl)
        self._items.move_to_end(key)
        while len(self._items) > self._max_items:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()


def is_quota_error(exc: BaseException | str) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in [
            "429",
            "quota",
            "rate limit",
            "rate_limit",
            "resource exhausted",
            "too many requests",
            "tokens per minute",
            "requests per minute",
        ]
    )


def is_context_limit_error(exc: BaseException | str) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ["context length", "token limit", "maximum context", "too many tokens", "128k"])


def is_non_retryable_llm_error(exc: BaseException | str) -> bool:
    text = str(exc).lower()
    return is_quota_error(text) or is_context_limit_error(text) or "llmbudgetexceeded" in text


class ProviderCircuitBreaker:
    def __init__(self) -> None:
        self._state: dict[tuple[str, str], ProviderFailure] = {}

    def _key(self, agent: str | None, provider: str) -> tuple[str, str]:
        return (normalize_agent_name(agent), provider)

    def _cooldown(self, base_seconds: float, failures: int) -> float:
        if base_seconds <= 0:
            return 0.0
        multiplier = 2 ** max(0, failures - 1)
        return min(float(settings.llm_provider_max_cooldown_seconds), base_seconds * multiplier)

    def _record_key_failure(self, key: tuple[str, str], provider: str, exc: BaseException) -> bool:
        state = self._state.get(key, ProviderFailure())
        state.failures += 1
        state.last_error = f"{type(exc).__name__}: {exc}"
        cooldown = 0.0
        if is_quota_error(exc):
            cooldown = self._cooldown(float(settings.llm_provider_quota_cooldown_seconds), state.failures)
        elif is_context_limit_error(exc) or isinstance(exc, LLMBudgetExceeded):
            cooldown = self._cooldown(float(settings.llm_provider_context_cooldown_seconds), state.failures)
        elif state.failures >= int(settings.llm_provider_failure_threshold):
            cooldown = self._cooldown(float(settings.llm_provider_error_cooldown_seconds), state.failures)
        activated = cooldown > 0
        if activated:
            state.cooldown_until = max(state.cooldown_until, time.time() + cooldown)
            logger.warning(
                "provider_cooldown_activated %s",
                json.dumps(
                    {
                        "agent": key[0],
                        "provider": provider,
                        "failures": state.failures,
                        "cooldownSeconds": round(cooldown, 2),
                        "error": state.last_error[:220],
                    },
                    sort_keys=True,
                ),
            )
        self._state[key] = state
        return activated

    def is_available(self, agent: str | None, provider: str) -> bool:
        now = time.time()
        global_state = self._state.get(("*", provider))
        if global_state and global_state.cooldown_until > now:
            return False
        state = self._state.get(self._key(agent, provider))
        return not state or state.cooldown_until <= now

    def cooldown_remaining(self, agent: str | None, provider: str) -> float:
        now = time.time()
        remaining = 0.0
        for key in [("*", provider), self._key(agent, provider)]:
            state = self._state.get(key)
            if state:
                remaining = max(remaining, state.cooldown_until - now)
        return max(0.0, remaining)

    def record_success(self, agent: str | None, provider: str) -> None:
        self._state.pop(self._key(agent, provider), None)
        if provider == "gemini":
            self._state.pop(("*", provider), None)

    def record_failure(self, agent: str | None, provider: str, exc: BaseException) -> None:
        activated = self._record_key_failure(self._key(agent, provider), provider, exc)
        if activated:
            llm_usage_metrics.increment("cooldownActivations")
        if is_quota_error(exc) and settings.llm_provider_quota_global_cooldown_enabled:
            global_activated = self._record_key_failure(("*", provider), provider, exc)
            if global_activated:
                llm_usage_metrics.increment("cooldownActivations")

    def snapshot(self) -> list[dict[str, Any]]:
        now = time.time()
        return [
            {
                "agent": agent,
                "provider": provider,
                "failures": state.failures,
                "cooldownRemainingSeconds": max(0, round(state.cooldown_until - now, 2)),
                "lastError": state.last_error[:300],
            }
            for (agent, provider), state in self._state.items()
            if state.failures or state.cooldown_until > now
        ]

    def clear(self) -> None:
        self._state.clear()


class ProviderRequestScheduler:
    """Central async request queue for provider calls.

    The LLM layer owns provider concurrency so graph nodes can remain autonomous while
    Gemini/Groq request bursts are flattened before they hit provider quotas.
    """

    def __init__(self) -> None:
        self._semaphores: dict[str, tuple[int, asyncio.Semaphore]] = {}

    def _limit(self, provider: str) -> int:
        if provider == "gemini":
            return max(1, int(settings.llm_max_gemini_concurrent_requests))
        if provider == "groq":
            return max(1, int(settings.llm_max_groq_concurrent_requests))
        return 2

    def _semaphore(self, provider: str) -> asyncio.Semaphore:
        limit = self._limit(provider)
        existing = self._semaphores.get(provider)
        if not existing or existing[0] != limit:
            existing = (limit, asyncio.Semaphore(limit))
            self._semaphores[provider] = existing
        return existing[1]

    @asynccontextmanager
    async def slot(self, *, agent: str | None, provider: str, operation: str):
        semaphore = self._semaphore(provider)
        queued_at = time.perf_counter()
        await semaphore.acquire()
        queued_ms = round((time.perf_counter() - queued_at) * 1000, 2)
        if queued_ms > 1:
            llm_usage_metrics.increment("queuedRequests")
            llm_usage_metrics.increment("queuedRequestWaitMs", queued_ms)
            logger.info(
                "llm_provider_request_queued %s",
                json.dumps(
                    {
                        "agent": normalize_agent_name(agent),
                        "provider": provider,
                        "operation": operation,
                        "queuedMs": queued_ms,
                        "limit": self._limit(provider),
                    },
                    sort_keys=True,
                ),
            )
        try:
            yield queued_ms
        finally:
            semaphore.release()


class LLMUsageMetrics:
    def __init__(self) -> None:
        self._records: deque[LLMCallMetric] = deque(maxlen=1000)
        self._counters: dict[str, float] = {
            "cooldownActivations": 0,
            "cooldownSkips": 0,
            "retriesAvoided": 0,
            "afcDisabledSkips": 0,
            "queuedRequests": 0,
            "queuedRequestWaitMs": 0,
        }

    def record(self, metric: LLMCallMetric) -> None:
        self._records.append(metric)
        logger.info("llm_call_metric %s", json.dumps(asdict(metric), sort_keys=True, default=str))

    def increment(self, key: str, amount: float = 1.0) -> None:
        self._counters[key] = self._counters.get(key, 0) + amount

    def snapshot(self) -> dict[str, Any]:
        records = list(self._records)
        totals: dict[str, dict[str, Any]] = {}
        for record in records:
            bucket = totals.setdefault(
                record.agent,
                {
                    "calls": 0,
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "cacheHits": 0,
                    "fallbacks": 0,
                    "retriesPrevented": 0,
                    "actualProviderRequests": 0,
                    "afcCalls": 0,
                    "providers": {},
                },
            )
            bucket["calls"] += 1
            bucket["inputTokens"] += record.input_tokens
            bucket["outputTokens"] += record.output_tokens
            bucket["cacheHits"] += int(record.cache_hit)
            bucket["fallbacks"] += int(record.fallback_used)
            bucket["retriesPrevented"] += int(record.retry_avoided)
            bucket["actualProviderRequests"] += int(record.request_count)
            bucket["afcCalls"] += int(record.afc_calls)
            provider_bucket = bucket["providers"].setdefault(
                record.provider,
                {"calls": 0, "latencyMs": 0, "actualProviderRequests": 0, "cooldownSkips": 0},
            )
            provider_bucket["calls"] += 1
            provider_bucket["latencyMs"] += record.latency_ms
            provider_bucket["actualProviderRequests"] += int(record.request_count)
            provider_bucket["cooldownSkips"] += int(record.cooldown_active and record.request_count == 0)
        provider_request_counts: dict[str, int] = {}
        for record in records:
            if record.request_count:
                provider_request_counts[record.provider] = provider_request_counts.get(record.provider, 0) + record.request_count
        return {
            "totalCalls": len(records),
            "actualProviderRequests": sum(record.request_count for record in records),
            "actualGeminiRequests": provider_request_counts.get("gemini", 0),
            "actualGroqRequests": provider_request_counts.get("groq", 0),
            "requestCountsByProvider": provider_request_counts,
            "totalInputTokens": sum(record.input_tokens for record in records),
            "totalOutputTokens": sum(record.output_tokens for record in records),
            "cacheHits": sum(int(record.cache_hit) for record in records),
            "fallbacks": sum(int(record.fallback_used) for record in records),
            "afcCalls": sum(int(record.afc_calls) for record in records),
            "retriesAvoided": sum(int(record.retry_avoided) for record in records) + int(self._counters.get("retriesAvoided", 0)),
            "cooldownActivations": int(self._counters.get("cooldownActivations", 0)),
            "cooldownSkips": int(self._counters.get("cooldownSkips", 0)),
            "afcDisabledSkips": int(self._counters.get("afcDisabledSkips", 0)),
            "queuedRequests": int(self._counters.get("queuedRequests", 0)),
            "queuedRequestWaitMs": round(self._counters.get("queuedRequestWaitMs", 0), 2),
            "byAgent": totals,
            "recent": [asdict(record) for record in records[-25:]],
            "circuitBreakers": provider_circuit_breaker.snapshot(),
        }

    def clear(self) -> None:
        self._records.clear()
        for key in list(self._counters):
            self._counters[key] = 0


prompt_cache = PromptCache()
provider_circuit_breaker = ProviderCircuitBreaker()
provider_request_scheduler = ProviderRequestScheduler()
llm_usage_metrics = LLMUsageMetrics()
