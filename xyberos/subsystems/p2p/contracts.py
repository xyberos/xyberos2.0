from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from xyberos.kernel.contracts import Provider


@dataclass(frozen=True)
class PeerIdentity:
    peer_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.peer_id, str) or not self.peer_id.strip():
            raise ValueError("Peer ID must be non-empty text.")


@dataclass(frozen=True)
class PeerMessage:
    message_id: str
    conversation_id: str
    sender_peer_id: str
    body: str
    created_at: datetime

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (
                self.message_id,
                self.conversation_id,
                self.sender_peer_id,
                self.body,
            )
        ):
            raise ValueError("Peer message fields must be non-empty text.")
        if any(
            len(value) > 256
            for value in (
                self.message_id,
                self.conversation_id,
                self.sender_peer_id,
            )
        ):
            raise ValueError("Peer message identifiers must not exceed 256 characters.")
        if len(self.body) > 65_536:
            raise ValueError("Peer message body must not exceed 65536 characters.")
        if self.created_at.tzinfo is None:
            raise ValueError("Peer message timestamp must be timezone-aware.")
        object.__setattr__(self, "created_at", self.created_at.astimezone(timezone.utc))


class PeerIdentityProvider(Provider, ABC):
    @abstractmethod
    async def initialize(self, config: dict[str, object]) -> None:
        """Load or provision the local device identity."""

    @abstractmethod
    async def close(self) -> None:
        """Release identity resources."""

    @abstractmethod
    async def get_identity(self) -> PeerIdentity:
        """Return the local peer identity."""


class PeerMessageStore(Provider, ABC):
    @abstractmethod
    async def initialize(self, config: dict[str, object]) -> None:
        """Create or open local message storage."""

    @abstractmethod
    async def close(self) -> None:
        """Release local storage resources."""

    @abstractmethod
    async def append(self, message: PeerMessage) -> bool:
        """Store a message; return false for an identical already-stored message."""

    @abstractmethod
    async def merge(self, messages: Sequence[PeerMessage]) -> int:
        """Idempotently merge messages, rejecting conflicting reused IDs."""

    @abstractmethod
    async def list_messages(
        self,
        conversation_id: str,
    ) -> tuple[PeerMessage, ...]:
        """List a conversation in deterministic order."""

    @abstractmethod
    async def all_messages(self) -> tuple[PeerMessage, ...]:
        """Return the local replication log in deterministic order."""


class PeerTransportProvider(Provider, ABC):
    @abstractmethod
    async def initialize(self, config: dict[str, object]) -> None:
        """Configure transport resources."""

    @abstractmethod
    async def close(self) -> None:
        """Release transport resources."""

    @abstractmethod
    async def exchange(
        self,
        peer_id: str,
        messages: Sequence[PeerMessage],
    ) -> tuple[PeerMessage, ...]:
        """Exchange append-only messages with a peer and return its log."""


class PeerSyncError(RuntimeError):
    """Peer synchronization could not complete."""


class P2PShutdownError(RuntimeError):
    def __init__(self, failures: Sequence[Exception]) -> None:
        self.failures = tuple(failures)
        super().__init__(
            "P2P provider shutdown failures: "
            + "; ".join(str(failure) for failure in self.failures)
        )
