from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import math
import re
import time
from typing import Any

from config import settings


VECTOR_DIMENSIONS = 384
_SENTENCE_TRANSFORMER_MODELS: dict[tuple[str, bool], Any] = {}
_CURRENT_GEMINI_EMBEDDING_MODEL = "models/gemini-embedding-001"
_LEGACY_GEMINI_EMBEDDING_MODELS = {"text-embedding-004", "models/text-embedding-004"}
_GEMINI_EMBEDDING_WORKING_MODEL: str | None = None
_GEMINI_EMBEDDING_UNAVAILABLE_UNTIL = 0.0
_GEMINI_EMBEDDING_COOLDOWN_SECONDS = 300.0
logger = logging.getLogger("interviewos.embeddings")


@dataclass
class EmbeddingResult:
    vector: list[float]
    provider: str
    model: str
    fallback_used: bool = False
    error: str = ""


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9_+#.-]{2,}", value.lower())


def _normalize(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(float(value) * float(value) for value in vector)) or 1.0
    return [float(value) / magnitude for value in vector]


def _fit_dimensions(vector: list[float], dimensions: int = VECTOR_DIMENSIONS) -> list[float]:
    fitted = [0.0] * dimensions
    if not vector:
        return fitted
    for index, value in enumerate(vector):
        fitted[index % dimensions] += float(value)
    return _normalize(fitted)


def _hash_embedding(text: str) -> list[float]:
    vector = [0.0] * VECTOR_DIMENSIONS
    tokens = _tokens(text)
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % VECTOR_DIMENSIONS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    return _normalize(vector)


def _normalize_gemini_embedding_model(model: str | None) -> str:
    normalized = str(model or "").strip()
    if not normalized:
        return ""
    return normalized if normalized.startswith("models/") else f"models/{normalized}"


def _gemini_embedding_model_candidates() -> list[str]:
    configured = _normalize_gemini_embedding_model(settings.gemini_embedding_model)
    candidates: list[str] = []

    def add(model: str | None) -> None:
        normalized = _normalize_gemini_embedding_model(model)
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    add(_GEMINI_EMBEDDING_WORKING_MODEL)
    if configured not in _LEGACY_GEMINI_EMBEDDING_MODELS:
        add(configured)
    add(_CURRENT_GEMINI_EMBEDDING_MODEL)
    add("models/embedding-001")
    return candidates


def _google_embedding_client(model: str):
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    try:
        return GoogleGenerativeAIEmbeddings(
            model=model,
            google_api_key=settings.gemini_api_key,
        )
    except TypeError:
        return GoogleGenerativeAIEmbeddings(
            model=model,
            api_key=settings.gemini_api_key,
        )


def _gemini_embedding(text: str) -> EmbeddingResult | None:
    global _GEMINI_EMBEDDING_UNAVAILABLE_UNTIL
    global _GEMINI_EMBEDDING_WORKING_MODEL

    if not settings.gemini_api_key:
        return None
    if time.time() < _GEMINI_EMBEDDING_UNAVAILABLE_UNTIL:
        return EmbeddingResult(
            vector=_hash_embedding(text),
            provider="hash",
            model="deterministic-token-hash",
            fallback_used=True,
            error="Gemini embedding provider is cooling down after recent failures; used hash fallback.",
        )

    errors: list[str] = []
    for model in _gemini_embedding_model_candidates():
        try:
            client = _google_embedding_client(model)
            vector = client.embed_query(text)
            _GEMINI_EMBEDDING_WORKING_MODEL = model
            _GEMINI_EMBEDDING_UNAVAILABLE_UNTIL = 0.0
            return EmbeddingResult(
                vector=_fit_dimensions(vector),
                provider="gemini",
                model=model,
                fallback_used=False,
            )
        except Exception as exc:
            if _GEMINI_EMBEDDING_WORKING_MODEL == model:
                _GEMINI_EMBEDDING_WORKING_MODEL = None
            errors.append(f"{model}: {type(exc).__name__}: {exc}")

    _GEMINI_EMBEDDING_UNAVAILABLE_UNTIL = time.time() + _GEMINI_EMBEDDING_COOLDOWN_SECONDS
    logger.warning("Gemini embedding provider unavailable; using hash fallback. %s", " | ".join(errors[-2:]))
    return EmbeddingResult(
        vector=_hash_embedding(text),
        provider="hash",
        model="deterministic-token-hash",
        fallback_used=True,
        error=" | ".join(errors),
    )


def _sentence_transformer_embedding(text: str) -> EmbeddingResult | None:
    try:
        from sentence_transformers import SentenceTransformer

        model_name = settings.sentence_transformer_embedding_model
        local_files_only = bool(settings.sentence_transformer_local_files_only)
        cache_key = (model_name, local_files_only)
        if cache_key not in _SENTENCE_TRANSFORMER_MODELS:
            try:
                _SENTENCE_TRANSFORMER_MODELS[cache_key] = SentenceTransformer(
                    model_name,
                    local_files_only=local_files_only,
                )
            except TypeError:
                _SENTENCE_TRANSFORMER_MODELS[cache_key] = SentenceTransformer(model_name)
        model = _SENTENCE_TRANSFORMER_MODELS[cache_key]
        vector = model.encode(text).tolist()
        return EmbeddingResult(
            vector=_fit_dimensions(vector),
            provider="sentence-transformers",
            model=model_name,
            fallback_used=False,
        )
    except Exception as exc:
        return EmbeddingResult(
            vector=_hash_embedding(text),
            provider="hash",
            model="deterministic-token-hash",
            fallback_used=True,
            error=f"{type(exc).__name__}: {exc}",
        )


def embed_text(text: str) -> EmbeddingResult:
    provider = str(settings.semantic_embedding_provider or "hash").lower().strip()
    if provider == "gemini":
        result = _gemini_embedding(text)
        if result is not None:
            return result
    if provider in {"sentence-transformers", "sentence_transformers", "local"}:
        result = _sentence_transformer_embedding(text)
        if result is not None:
            return result
    return EmbeddingResult(
        vector=_hash_embedding(text),
        provider="hash",
        model="deterministic-token-hash",
        fallback_used=provider not in {"", "hash"},
        error="" if provider in {"", "hash"} else f"Embedding provider '{provider}' unavailable; used hash fallback.",
    )


def embedding_metadata(result: EmbeddingResult) -> dict[str, Any]:
    return {
        "embedding_provider": result.provider,
        "embedding_model": result.model,
        "embedding_fallback_used": result.fallback_used,
        "embedding_error": result.error,
        "embedding_dimensions": len(result.vector),
    }
