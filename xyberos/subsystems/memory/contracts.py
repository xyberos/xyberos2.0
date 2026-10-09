from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from xyberos.kernel.contracts import Provider


@dataclass(frozen=True)
class MemoryScope:
    tenant_id: str
    actor_id: str
    conversation_id: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (self.tenant_id, self.actor_id, self.conversation_id)
        ):
            raise ValueError("Memory scope requires non-empty tenant, actor, and conversation IDs.")


@dataclass(frozen=True)
class MemoryMessage:
    role: str
    content: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.role not in {"user", "assistant"}:
            raise ValueError("Memory message role must be user or assistant.")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("Memory message content must be non-empty text.")
        if self.created_at.tzinfo is None:
            raise ValueError("Memory message timestamp must be timezone-aware.")


class MemoryProvider(Provider, ABC):
    @abstractmethod
    async def initialize(self, config: Mapping[str, object]) -> None:
        """Validate provider-specific configuration."""

    @abstractmethod
    async def close(self) -> None:
        """Release provider resources."""

    @abstractmethod
    async def append(self, scope: MemoryScope, message: MemoryMessage) -> None:
        """Append a message under an explicit tenant and actor scope."""

    @abstractmethod
    async def list_messages(self, scope: MemoryScope) -> tuple[MemoryMessage, ...]:
        """Return messages visible only to the exact supplied scope."""
