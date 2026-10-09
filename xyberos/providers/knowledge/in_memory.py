from __future__ import annotations

import asyncio
import re
from collections.abc import Collection, Mapping

from xyberos.kernel.contracts import ExecutionContextAccessor
from xyberos.subsystems.knowledge.contracts import (
    KnowledgeCitation,
    KnowledgeDocument,
    KnowledgeProvider,
)

_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


class InMemoryKnowledgeProvider(KnowledgeProvider):
    """Tenant- and actor-scoped keyword retrieval for tests and small demos."""

    def __init__(self) -> None:
        self._documents: dict[tuple[str, str], KnowledgeDocument] = {}
        self._lock = asyncio.Lock()
        self._initialized = False
        self._max_documents = 1_000
        self._max_document_chars = 100_000

    @property
    def provider_name(self) -> str:
        return "in_memory_keyword"

    async def initialize(self, config: Mapping[str, object]) -> None:
        unknown_keys = set(config) - {"max_documents", "max_document_chars"}
        if unknown_keys:
            raise ValueError(
                f"Unknown knowledge provider config keys: {', '.join(sorted(unknown_keys))}."
            )
        max_documents = _positive_integer(config, "max_documents", 1_000)
        max_document_chars = _positive_integer(config, "max_document_chars", 100_000)
        async with self._lock:
            self._documents.clear()
            self._max_documents = max_documents
            self._max_document_chars = max_document_chars
            self._initialized = True

    async def close(self) -> None:
        async with self._lock:
            self._documents.clear()
            self._initialized = False

    async def put(self, document: KnowledgeDocument) -> None:
        if not isinstance(document, KnowledgeDocument):
            raise TypeError("Knowledge provider accepts KnowledgeDocument values.")
        stored = KnowledgeDocument(
            source_id=document.source_id,
            tenant_id=document.tenant_id,
            content=document.content,
            allowed_actor_ids=(
                frozenset(document.allowed_actor_ids)
                if document.allowed_actor_ids is not None
                else None
            ),
            metadata=dict(document.metadata),
        )
        async with self._lock:
            self._require_initialized()
            if len(stored.content) > self._max_document_chars:
                raise ValueError(
                    "Knowledge document exceeds configured max_document_chars."
                )
            key = (stored.tenant_id, stored.source_id)
            if key not in self._documents and len(self._documents) >= self._max_documents:
                raise ValueError("Knowledge provider reached configured max_documents.")
            self._documents[key] = stored

    async def delete(self, tenant_id: str, source_id: str) -> bool:
        if (
            not isinstance(tenant_id, str)
            or not tenant_id.strip()
            or not isinstance(source_id, str)
            or not source_id.strip()
        ):
            raise ValueError("Knowledge tenant_id and source_id are required.")
        async with self._lock:
            self._require_initialized()
            return self._documents.pop((tenant_id, source_id), None) is not None

    async def search(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        query: str,
        limit: int = 5,
        allowed_sources: Collection[str] | None = None,
    ) -> tuple[KnowledgeCitation, ...]:
        if (
            not isinstance(tenant_id, str)
            or not tenant_id.strip()
            or not isinstance(actor_id, str)
            or not actor_id.strip()
        ):
            raise ValueError("Knowledge retrieval requires tenant_id and actor_id.")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Knowledge search query must be non-empty text.")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 100
        ):
            raise ValueError("Knowledge search limit must be between one and 100.")
        if isinstance(allowed_sources, (str, bytes)):
            raise ValueError("Allowed sources must be a collection of source IDs.")
        if allowed_sources is not None and not all(
            isinstance(source_id, str) and source_id.strip()
            for source_id in allowed_sources
        ):
            raise ValueError("Allowed source IDs must be non-empty strings.")
        try:
            context = ExecutionContextAccessor.get()
        except RuntimeError as exc:
            raise PermissionError(
                "Knowledge retrieval requires a trusted execution context."
            ) from exc
        if context.tenant_id != tenant_id or context.actor_id != actor_id:
            raise PermissionError(
                "Knowledge retrieval scope does not match the current principal."
            )
        query_tokens = set(_TOKEN_PATTERN.findall(query.casefold()))
        if not query_tokens:
            return ()
        source_filter = (
            frozenset(allowed_sources) if allowed_sources is not None else None
        )
        async with self._lock:
            self._require_initialized()
            documents = tuple(self._documents.values())

        matches: list[tuple[float, KnowledgeDocument]] = []
        for document in documents:
            if document.tenant_id != tenant_id:
                continue
            if (
                document.allowed_actor_ids is not None
                and actor_id not in document.allowed_actor_ids
            ):
                continue
            if source_filter is not None and document.source_id not in source_filter:
                continue
            document_tokens = set(_TOKEN_PATTERN.findall(document.content.casefold()))
            overlap = len(query_tokens & document_tokens)
            if overlap:
                matches.append((overlap / len(query_tokens), document))
        matches.sort(key=lambda match: (-match[0], match[1].source_id))
        return tuple(
            KnowledgeCitation(
                source_id=document.source_id,
                excerpt=document.content[:500],
                score=score,
                metadata=dict(document.metadata),
            )
            for score, document in matches[:limit]
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("In-memory knowledge provider is not initialized.")


def _positive_integer(config: Mapping[str, object], key: str, default: int) -> int:
    value = config.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"'{key}' must be a positive integer.")
    return value
