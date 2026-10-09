from __future__ import annotations

import asyncio
from collections.abc import Sequence

from xyberos.subsystems.p2p.contracts import (
    PeerExchangePage,
    PeerMessage,
    PeerMessageStore,
    PeerSyncError,
    PeerTransportProvider,
)


class InMemoryPeerTransport(PeerTransportProvider):
    """Test-only peer transport for deterministic multi-device sync tests."""

    def __init__(self) -> None:
        self._stores: dict[str, PeerMessageStore] = {}
        self._online: set[str] = set()
        self._lock = asyncio.Lock()
        self._initialized = False

    @property
    def provider_name(self) -> str:
        return "in_memory_test_transport"

    async def initialize(self, config: dict[str, object]) -> None:
        if config:
            raise ValueError("In-memory peer transport accepts no configuration.")
        self._initialized = True

    async def close(self) -> None:
        async with self._lock:
            self._stores.clear()
            self._online.clear()
            self._initialized = False

    async def attach(
        self,
        peer_id: str,
        store: PeerMessageStore,
    ) -> None:
        self._require_initialized()
        if not peer_id.strip():
            raise ValueError("Peer ID must be non-empty text.")
        async with self._lock:
            self._stores[peer_id] = store
            self._online.add(peer_id)

    async def set_online(self, peer_id: str, online: bool) -> None:
        self._require_initialized()
        async with self._lock:
            if peer_id not in self._stores:
                raise PeerSyncError(f"Peer '{peer_id}' is not registered.")
            if online:
                self._online.add(peer_id)
            else:
                self._online.discard(peer_id)

    async def exchange(
        self,
        peer_id: str,
        messages: Sequence[PeerMessage],
        cursor: str | None = None,
    ) -> PeerExchangePage:
        if cursor is not None:
            raise PeerSyncError("In-memory peer transport does not support cursors.")
        self._require_initialized()
        async with self._lock:
            if peer_id not in self._online:
                raise PeerSyncError(f"Peer '{peer_id}' is offline or unavailable.")
            store = self._stores[peer_id]
        await store.merge(messages)
        return PeerExchangePage(await store.all_messages(), None, False)

    async def acknowledge(self, peer_id: str, cursor: str | None) -> None:
        del peer_id
        if cursor is not None:
            raise PeerSyncError("In-memory peer transport does not support cursors.")

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("In-memory peer transport is not initialized.")
