from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .contracts import (
    PeerIdentityProvider,
    PeerMessage,
    PeerMessageStore,
    PeerMessageSubmissionError,
    PeerSyncError,
    PeerTransportProvider,
)


class OfflineMessagingService:
    """Local-first message API with explicit, retryable peer synchronization."""

    def __init__(
        self,
        identity: PeerIdentityProvider,
        store: PeerMessageStore,
        transport: PeerTransportProvider,
    ) -> None:
        self._identity = identity
        self._store = store
        self._transport = transport

    async def send(self, conversation_id: str, body: str) -> PeerMessage:
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise ValueError("Conversation ID must be non-empty text.")
        if not isinstance(body, str) or not body.strip():
            raise ValueError("Message body must be non-empty text.")
        identity = await self._identity.get_identity()
        message = PeerMessage(
            message_id=uuid4().hex,
            conversation_id=conversation_id,
            sender_peer_id=identity.peer_id,
            body=body,
            created_at=datetime.now(timezone.utc),
        )
        await self._store.append(message)
        return message

    async def messages(self, conversation_id: str) -> tuple[PeerMessage, ...]:
        return await self._store.list_messages(conversation_id)

    async def synchronize(self, peer_id: str) -> int:
        identity = await self._identity.get_identity()
        if not isinstance(peer_id, str) or not peer_id.strip():
            raise ValueError("Target peer ID must be non-empty text.")
        if peer_id == identity.peer_id:
            raise ValueError("A peer cannot synchronize with itself.")
        local_log = await self._store.all_messages()
        merged_total = 0
        rejected_message_ids: list[str] = []
        page_cursor: str | None = None
        outbound = local_log
        while True:
            try:
                page = await self._transport.exchange(
                    peer_id,
                    outbound,
                    cursor=page_cursor,
                )
            except Exception as exc:
                raise PeerSyncError(
                    f"Synchronization with peer '{peer_id}' failed."
                ) from exc
            try:
                merged_total += await self._store.merge(page.messages)
            except (TypeError, ValueError) as exc:
                raise PeerSyncError(
                    f"Peer '{peer_id}' returned an invalid or conflicting message log."
                ) from exc
            rejected_message_ids.extend(page.rejected_message_ids)
            try:
                await self._transport.acknowledge(peer_id, page.next_cursor)
            except Exception as exc:
                raise PeerSyncError(
                    f"Could not persist synchronization progress with peer '{peer_id}'."
                ) from exc
            if not page.has_more:
                if rejected_message_ids:
                    raise PeerMessageSubmissionError(
                        peer_id,
                        rejected_message_ids,
                        merged_total,
                    )
                return merged_total
            page_cursor = page.next_cursor
            outbound = ()
