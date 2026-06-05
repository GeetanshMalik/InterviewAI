from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from config import settings
from services.embeddings import VECTOR_DIMENSIONS, embed_text, embedding_metadata
from services.store import iso_now


COLLECTION_NAME = "interviewos_agent_memory"


def _embedding(text: str) -> tuple[list[float], dict[str, Any]]:
    result = embed_text(text)
    return result.vector, embedding_metadata(result)


def _json_safe(value: Any) -> str | int | float | bool:
    if isinstance(value, str | int | float | bool):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _metadata(metadata: dict[str, Any] | None, user_id: str, memory_type: str, source_id: str) -> dict[str, str | int | float | bool]:
    cleaned = {str(key): _json_safe(value) for key, value in (metadata or {}).items()}
    cleaned.update(
        {
            "user_id": user_id,
            "memory_type": memory_type,
            "source_id": source_id,
            "created_at": str(cleaned.get("created_at") or iso_now()),
            "privacy_scope": str(cleaned.get("privacy_scope") or "user"),
            "importance": str(cleaned.get("importance") or "medium"),
        }
    )
    return cleaned


def _excerpt(text: str, limit: int = 900) -> str:
    collapsed = re.sub(r"\s+", " ", text or "").strip()
    return collapsed[:limit]


def _recall_score(memory: dict[str, Any]) -> float:
    distance = memory.get("distance")
    if isinstance(distance, int | float):
        distance_score = max(0.0, 1.0 - float(distance))
    else:
        distance_score = 0.25
    metadata = memory.get("metadata") or {}
    importance = str(metadata.get("importance") or "medium").lower()
    importance_score = {"critical": 0.3, "high": 0.22, "medium": 0.12, "low": 0.04}.get(importance, 0.1)
    memory_type = str(metadata.get("memory_type") or metadata.get("type") or "")
    type_score = 0.12 if memory_type in {"weakness", "evaluation", "transcript", "report"} else 0.05
    return round(min(1.0, distance_score + importance_score + type_score), 4)


def _recall_summary(memory: dict[str, Any]) -> str:
    metadata = memory.get("metadata") or {}
    memory_type = str(metadata.get("memory_type") or metadata.get("type") or "memory")
    source_id = str(metadata.get("source_id") or memory.get("document_id") or "")
    excerpt = _excerpt(memory.get("text") or memory.get("excerpt") or "", 220)
    return f"{memory_type} {source_id}: {excerpt}".strip()


def _rank_memories(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for memory in memories:
        item = dict(memory)
        item["recall_score"] = _recall_score(item)
        item["recall_summary"] = _recall_summary(item)
        enriched.append(item)
    enriched.sort(key=lambda item: item.get("recall_score", 0), reverse=True)
    return enriched


class ChromaService:
    """Persistent vector memory service for agent workflows.

    The service keeps the old `add_document` and `query` methods so existing
    routes stay compatible, while exposing explicit memory APIs for the new
    agent architecture.
    """

    def __init__(self) -> None:
        self.persist_dir = settings.chroma_persist_dir
        self._fallback_documents: list[dict[str, Any]] = []
        self._query_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._pending_writes: dict[str, dict[str, Any]] = {}
        self._flush_task: asyncio.Task | None = None
        self._client = None
        self._collection = None
        self._init_client()

    def _init_client(self) -> None:
        try:
            import chromadb

            Path(self.persist_dir).mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=self.persist_dir)
            self._collection = self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            self._client = None
            self._collection = None

    @property
    def available(self) -> bool:
        return self._collection is not None

    def _query_cache_key(
        self,
        user_id: str,
        query: str,
        limit: int,
        memory_types: list[str] | None,
        privacy_scopes: list[str] | None,
    ) -> str:
        return json.dumps(
            {
                "backend": settings.semantic_memory_backend.lower(),
                "embeddingProvider": settings.semantic_embedding_provider,
                "userId": user_id,
                "query": query,
                "limit": max(1, limit),
                "memoryTypes": sorted(memory_types or []),
                "privacyScopes": sorted(privacy_scopes or ["user"]),
            },
            sort_keys=True,
        )

    def _cached_query(self, key: str) -> list[dict[str, Any]] | None:
        cached = self._query_cache.get(key)
        if not cached:
            return None
        expires_at, memories = cached
        if expires_at <= time.time():
            self._query_cache.pop(key, None)
            return None
        return [dict(item) for item in memories]

    def _remember_query(self, key: str, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ttl = int(settings.semantic_memory_query_cache_ttl_seconds)
        if ttl > 0:
            self._query_cache[key] = (time.time() + ttl, [dict(item) for item in memories])
            if len(self._query_cache) > 512:
                for stale_key in list(self._query_cache)[:128]:
                    self._query_cache.pop(stale_key, None)
        return memories

    def _invalidate_user_queries(self, user_id: str) -> None:
        marker = f'"userId": "{user_id}"'
        for key in list(self._query_cache):
            if marker in key:
                self._query_cache.pop(key, None)

    def add_memory(
        self,
        user_id: str,
        memory_type: str,
        source_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
        *,
        defer_indexing: bool = False,
    ) -> dict[str, Any]:
        document_id = f"{user_id}:{memory_type}:{source_id}"
        raw_metadata = dict(metadata or {})
        if defer_indexing:
            embedding_info = {
                "embedding_provider": "deferred",
                "embedding_model": "pending",
                "embedding_fallback_used": False,
                "embedding_error": "",
                "embedding_dimensions": 0,
                "embedding_deferred": True,
            }
            vector = None
        else:
            vector, embedding_info = _embedding(text)
        item_metadata = _metadata({**raw_metadata, **embedding_info}, user_id, memory_type, source_id)
        memory = {
            "id": document_id,
            "user_id": user_id,
            "document_id": source_id,
            "text": text,
            "metadata": item_metadata,
        }
        self._invalidate_user_queries(user_id)

        if defer_indexing:
            self._fallback_documents = [
                item for item in self._fallback_documents if item.get("id") != document_id
            ]
            self._fallback_documents.append(memory)
            self._pending_writes[document_id] = {
                "document_id": document_id,
                "user_id": user_id,
                "memory_type": memory_type,
                "source_id": source_id,
                "text": text,
                "metadata": raw_metadata,
            }
            self._mirror_memory(document_id, user_id, memory_type, source_id, text, item_metadata)
            self._schedule_deferred_flush()
            return memory

        if self._collection is None:
            self._fallback_documents = [
                item for item in self._fallback_documents if item.get("id") != document_id
            ]
            self._fallback_documents.append(memory)
            self._mirror_memory(document_id, user_id, memory_type, source_id, text, item_metadata)
            return memory

        self._collection.upsert(
            ids=[document_id],
            documents=[text],
            embeddings=[vector],
            metadatas=[item_metadata],
        )
        self._mirror_memory(document_id, user_id, memory_type, source_id, text, item_metadata, vector)
        return memory

    def _schedule_deferred_flush(self) -> None:
        if self._flush_task and not self._flush_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._flush_task = loop.create_task(self._flush_deferred_soon())

    async def _flush_deferred_soon(self) -> None:
        await asyncio.sleep(max(0.0, float(settings.semantic_memory_deferred_flush_delay_seconds)))
        try:
            await asyncio.to_thread(
                self.flush_deferred_memory_writes,
                max(1, int(settings.semantic_memory_batch_flush_size)),
            )
        except Exception:
            return

    def flush_deferred_memory_writes(self, limit: int | None = None) -> int:
        limit = max(1, int(limit or settings.semantic_memory_batch_flush_size))
        pending = list(self._pending_writes.items())[:limit]
        written = 0
        for document_id, item in pending:
            text = str(item["text"])
            vector, embedding_info = _embedding(text)
            item_metadata = _metadata(
                {**dict(item.get("metadata") or {}), **embedding_info, "embedding_deferred": False},
                str(item["user_id"]),
                str(item["memory_type"]),
                str(item["source_id"]),
            )
            memory = {
                "id": document_id,
                "user_id": item["user_id"],
                "document_id": item["source_id"],
                "text": text,
                "metadata": item_metadata,
            }
            self._fallback_documents = [
                existing for existing in self._fallback_documents if existing.get("id") != document_id
            ]
            self._fallback_documents.append(memory)
            if self._collection is not None:
                self._collection.upsert(
                    ids=[document_id],
                    documents=[text],
                    embeddings=[vector],
                    metadatas=[item_metadata],
                )
            self._mirror_memory(
                document_id,
                str(item["user_id"]),
                str(item["memory_type"]),
                str(item["source_id"]),
                text,
                item_metadata,
                vector,
            )
            self._pending_writes.pop(document_id, None)
            written += 1
        return written

    def _mirror_memory(
        self,
        document_id: str,
        user_id: str,
        memory_type: str,
        source_id: str,
        text: str,
        metadata: dict[str, Any],
        embedding: list[float] | None = None,
    ) -> None:
        try:
            from services.repositories.manager import persistence_manager

            persistence_manager.upsert_memory(
                memory_id=document_id,
                user_id=user_id,
                memory_type=memory_type,
                source_id=source_id,
                text=text,
                metadata=metadata,
                embedding=embedding,
            )
        except Exception:
            return

    def add_document(self, user_id: str, document_id: str, text: str, metadata: dict | None = None) -> None:
        memory_type = str((metadata or {}).get("type") or "document")
        self.add_memory(user_id, memory_type, document_id, text, metadata)

    def query_memory(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
        memory_types: list[str] | None = None,
        privacy_scopes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        allowed_privacy_scopes = privacy_scopes or ["user"]
        cache_key = self._query_cache_key(user_id, query, limit, memory_types, allowed_privacy_scopes)
        cached = self._cached_query(cache_key)
        if cached is not None:
            return cached

        query_vector, query_embedding_info = _embedding(query)
        if settings.semantic_memory_backend.lower() == "pgvector":
            try:
                from services.repositories.manager import persistence_manager

                if persistence_manager.enabled:
                    return self._remember_query(
                        cache_key,
                        persistence_manager.query_memory(
                            user_id=user_id,
                            query=query,
                            query_embedding=query_vector,
                            limit=limit,
                            memory_types=memory_types,
                            privacy_scopes=allowed_privacy_scopes,
                        ),
                    )
            except Exception:
                if settings.app_env == "production":
                    raise

        if self._collection is None:
            return self._remember_query(
                cache_key,
                _rank_memories(self._query_fallback(user_id, query, limit, memory_types, allowed_privacy_scopes)),
            )

        where_clauses: list[dict[str, Any]] = [
            {"user_id": user_id},
            {"privacy_scope": {"$in": allowed_privacy_scopes}},
        ]
        if memory_types:
            where_clauses.append({"memory_type": {"$in": memory_types}})
        where: dict[str, Any] = where_clauses[0] if len(where_clauses) == 1 else {"$and": where_clauses}

        result = self._collection.query(
            query_embeddings=[query_vector],
            n_results=max(1, limit),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        memories: list[dict[str, Any]] = []
        for index, memory_id in enumerate(ids):
            metadata = metadatas[index] if index < len(metadatas) else {}
            text = documents[index] if index < len(documents) else ""
            memories.append(
                {
                    "id": memory_id,
                    "user_id": metadata.get("user_id", user_id),
                    "document_id": metadata.get("source_id", memory_id),
                    "text": text,
                    "excerpt": _excerpt(text),
                    "metadata": metadata,
                    "distance": distances[index] if index < len(distances) else None,
                }
            )
        for memory in memories:
            memory["query_embedding"] = query_embedding_info
        return self._remember_query(cache_key, _rank_memories(memories))

    def query(self, user_id: str, query: str, limit: int = 5) -> list[dict]:
        return self.query_memory(user_id, query, limit)

    def _query_fallback(
        self,
        user_id: str,
        query: str,
        limit: int,
        memory_types: list[str] | None = None,
        privacy_scopes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        terms = {term.lower() for term in query.split() if len(term) > 2}
        scored = []
        allowed_privacy_scopes = privacy_scopes or ["user"]
        for doc in self._fallback_documents:
            if doc["user_id"] != user_id:
                continue
            if memory_types and doc.get("metadata", {}).get("memory_type") not in memory_types:
                continue
            if str(doc.get("metadata", {}).get("privacy_scope") or "user") not in allowed_privacy_scopes:
                continue
            text = doc["text"].lower()
            score = sum(1 for term in terms if term in text)
            scored.append((score, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                **doc,
                "excerpt": _excerpt(doc.get("text", "")),
                "distance": None if score <= 0 else 1 / (score + 1),
            }
            for score, doc in scored[:limit]
            if score > 0
        ]


chroma_service = ChromaService()


def init_chroma() -> ChromaService:
    return chroma_service
