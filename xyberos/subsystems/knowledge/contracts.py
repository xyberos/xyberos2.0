from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from xyberos.kernel.contracts import Provider


@dataclass(frozen=True)
class KnowledgeDocument:
    source_id: str
    tenant_id: str
    content: str
    allowed_actor_ids: frozenset[str] | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (self.source_id, self.tenant_id, self.content)
        ):
            raise ValueError("Knowledge document source, tenant, and content are required.")
        if self.allowed_actor_ids is not None and not all(
            isinstance(actor_id, str) and actor_id.strip()
            for actor_id in self.allowed_actor_ids
        ):
            raise ValueError("Allowed actor IDs must be non-empty strings.")
        if not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in self.metadata.items()
        ):
            raise ValueError("Knowledge document metadata must contain string keys and values.")


@dataclass(frozen=True)
class KnowledgeCitation:
    source_id: str
    excerpt: str
    score: float
    metadata: Mapping[str, str]


class KnowledgeProvider(Provider, ABC):
    @abstractmethod
    async def initialize(self, config: Mapping[str, object]) -> None:
        """Validate provider-specific configuration."""

    @abstractmethod
    async def close(self) -> None:
        """Release provider resources."""

    @abstractmethod
    async def put(self, document: KnowledgeDocument) -> None:
        """Add or replace a tenant-scoped document."""

    @abstractmethod
    async def delete(self, tenant_id: str, source_id: str) -> bool:
        """Remove a document from one tenant's index."""

    @abstractmethod
    async def search(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        query: str,
        limit: int = 5,
        allowed_sources: Collection[str] | None = None,
    ) -> tuple[KnowledgeCitation, ...]:
        """Retrieve authorized citations within an explicit trusted principal scope."""
