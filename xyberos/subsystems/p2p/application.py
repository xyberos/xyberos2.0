from __future__ import annotations

from collections.abc import Mapping, Sequence

from xyberos.kernel.contracts import ExecutionContextAccessor

from .contracts import PeerMessage
from .messaging import OfflineMessagingService


class TenantScopedMessagingService:
    """Application boundary that enforces tenant and peer authorization."""

    def __init__(
        self,
        messaging: OfflineMessagingService,
        tenant_peer_map: Mapping[str, Sequence[str]] | None = None,
        allowed_conversations: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        if not isinstance(messaging, OfflineMessagingService):
            raise TypeError("messaging must be an OfflineMessagingService instance.")
        self._messaging = messaging
        self._tenant_peer_map = {
            tenant_id: tuple(sorted(set(str(peer).strip() for peer in peers)))
            for tenant_id, peers in (tenant_peer_map or {}).items()
        }
        self._allowed_conversations = {
            tenant_id: frozenset(str(conversation).strip() for conversation in conversations)
            for tenant_id, conversations in (allowed_conversations or {}).items()
        }

    def _require_same_tenant(self, tenant_id: str) -> None:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Tenant ID must be non-empty text.")
        context = ExecutionContextAccessor.get()
        if context.tenant_id != tenant_id:
            raise PermissionError(
                "Execution context tenant does not match the requested tenant."
            )

    def _require_tenant_configuration(self, tenant_id: str) -> None:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Tenant ID must be non-empty text.")
        if tenant_id not in self._tenant_peer_map and tenant_id not in self._allowed_conversations:
            raise ValueError(
                f"Tenant '{tenant_id}' is not configured for the secure messaging boundary."
            )

    def _require_allowed_conversation(self, tenant_id: str, conversation_id: str) -> None:
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise ValueError("Conversation ID must be non-empty text.")
        allowed = self._allowed_conversations.get(tenant_id)
        if allowed is not None and conversation_id not in allowed:
            raise PermissionError(
                f"Conversation '{conversation_id}' is not allowed for tenant '{tenant_id}'."
            )
        if allowed is None and tenant_id in self._tenant_peer_map:
            raise PermissionError(
                f"Conversation '{conversation_id}' is not allowed for tenant '{tenant_id}'."
            )

    def _require_allowed_peer(self, tenant_id: str, peer_id: str | None) -> str | None:
        peers = self._tenant_peer_map.get(tenant_id, ())
        if peer_id is None:
            if not peers:
                raise ValueError(
                    f"Tenant '{tenant_id}' has no authorized peers configured for secure messaging."
                )
            return peers[0]
        if not isinstance(peer_id, str) or not peer_id.strip():
            raise ValueError("Peer ID must be non-empty text when supplied.")
        if peer_id not in peers:
            raise PermissionError(
                f"Peer '{peer_id}' is not authorized for tenant '{tenant_id}'."
            )
        return peer_id

    async def list_messages(
        self,
        tenant_id: str,
        conversation_id: str,
    ) -> tuple[PeerMessage, ...]:
        self._require_tenant_configuration(tenant_id)
        self._require_same_tenant(tenant_id)
        self._require_allowed_conversation(tenant_id, conversation_id)
        return await self._messaging.messages(conversation_id)

    async def send_message(
        self,
        tenant_id: str,
        conversation_id: str,
        body: str,
        peer_id: str | None = None,
    ) -> PeerMessage:
        self._require_tenant_configuration(tenant_id)
        self._require_same_tenant(tenant_id)
        self._require_allowed_conversation(tenant_id, conversation_id)
        self._require_allowed_peer(tenant_id, peer_id)
        if not isinstance(body, str) or not body.strip():
            raise ValueError("Message body must be non-empty text.")
        return await self._messaging.send(conversation_id, body)

    async def synchronize(
        self,
        tenant_id: str,
        conversation_id: str,
        peer_id: str,
    ) -> int:
        self._require_tenant_configuration(tenant_id)
        self._require_same_tenant(tenant_id)
        self._require_allowed_conversation(tenant_id, conversation_id)
        self._require_allowed_peer(tenant_id, peer_id)
        return await self._messaging.synchronize(peer_id)


SecureReferenceMessagingService = TenantScopedMessagingService
ApplicationMessagingService = TenantScopedMessagingService
