import asyncio
import json
import unittest
from types import SimpleNamespace

from starlette.requests import Request
from starlette.testclient import TestClient

from xyberos.kernel.contracts import ExecutionContext, ExecutionContextAccessor
from xyberos.kernel.security import AuthenticatedIdentity
from xyberos.providers.database import SQLiteProvider
from xyberos.providers.p2p import (
    ConfiguredPeerIdentityProvider,
    InMemoryPeerTransport,
    SQLitePeerMessageStore,
)
from xyberos.subsystems.p2p import (
    OfflineMessagingService,
    PeerMessageSubmissionError,
    PeerSyncError,
    TenantScopedMessagingService,
)


class TestP2PTenantScopedApplicationService(unittest.TestCase):
    def test_authorizes_only_same_tenant_and_allowed_peer(self):
        async def scenario():
            database = SQLiteProvider()
            await database.initialize({"path": ":memory:"})
            store = SQLitePeerMessageStore(database)
            await store.initialize({})
            identity = ConfiguredPeerIdentityProvider()
            await identity.initialize({"peer_id": "device-a"})
            transport = InMemoryPeerTransport()
            await transport.initialize({})
            messaging = OfflineMessagingService(identity, store, transport)
            service = TenantScopedMessagingService(
                messaging,
                tenant_peer_map={"tenant-a": ("device-b",), "tenant-b": ("device-c",)},
                allowed_conversations={"tenant-a": ("conversation-1",), "tenant-b": ("conversation-2",)},
            )
            context = ExecutionContext(
                request_id="req-1",
                tenant_id="tenant-a",
                actor_id="actor-a",
            )
            token = ExecutionContextAccessor.set(context)
            try:
                message = await service.send_message("tenant-a", "conversation-1", "hello")
                self.assertEqual(message.conversation_id, "conversation-1")
                self.assertEqual(len(await service.list_messages("tenant-a", "conversation-1")), 1)
                with self.assertRaises(PermissionError):
                    await service.send_message("tenant-b", "conversation-1", "cross-tenant")
                with self.assertRaises(PermissionError):
                    await service.send_message("tenant-a", "conversation-2", "not-allowed")
                with self.assertRaises(PermissionError):
                    await service.synchronize("tenant-a", "conversation-1", "device-c")
            finally:
                ExecutionContextAccessor.reset(token)
                await transport.close()
                await store.close()
                await identity.close()
                await database.close()

        asyncio.run(scenario())

    def test_submission_rejection_reports_partial_sync_result(self):
        from apps.example_p2p_app.app import _sync_messages

        class RejectedSyncService:
            async def synchronize(self, tenant_id, conversation_id, peer_id):
                raise PeerMessageSubmissionError(
                    peer_id,
                    ("message-1", "message-2"),
                    merged_count=3,
                )

        async def scenario():
            context = ExecutionContext(
                request_id="req-rejected",
                tenant_id="tenant-a",
                actor_id="actor-a",
            )
            token = ExecutionContextAccessor.set(context)
            try:
                request = Request(
                    {
                        "type": "http",
                        "method": "POST",
                        "path": "/v1/tenants/tenant-a/conversations/c1/sync/device-b",
                        "headers": [],
                        "query_string": b"",
                        "path_params": {
                            "tenant_id": "tenant-a",
                            "conversation_id": "c1",
                            "peer_id": "device-b",
                        },
                        "app": SimpleNamespace(
                            state=SimpleNamespace(
                                secure_messaging=RejectedSyncService(),
                            )
                        ),
                    }
                )
                response = await _sync_messages(request)
                self.assertEqual(response.status_code, 207)
                self.assertEqual(
                    json.loads(bytes(response.body)),
                    {
                        "detail": (
                            "Peer 'device-b' rejected 2 message submission(s); "
                            "inbound synchronization completed."
                        ),
                        "peer_id": "device-b",
                        "merged": 3,
                        "rejected_message_ids": ["message-1", "message-2"],
                    },
                )

                class FailedSyncService:
                    async def synchronize(self, tenant_id, conversation_id, peer_id):
                        raise PeerSyncError("Relay synchronization failed.")

                request.scope["app"].state.secure_messaging = FailedSyncService()
                response = await _sync_messages(request)
                self.assertEqual(response.status_code, 502)
                self.assertEqual(
                    json.loads(bytes(response.body)),
                    {"detail": "Relay synchronization failed."},
                )
            finally:
                ExecutionContextAccessor.reset(token)

        asyncio.run(scenario())

    def test_rejects_untrusted_tenant_context_and_missing_authorized_peer(self):
        async def scenario():
            database = SQLiteProvider()
            await database.initialize({"path": ":memory:"})
            store = SQLitePeerMessageStore(database)
            await store.initialize({})
            identity = ConfiguredPeerIdentityProvider()
            await identity.initialize({"peer_id": "device-a"})
            transport = InMemoryPeerTransport()
            await transport.initialize({})
            messaging = OfflineMessagingService(identity, store, transport)
            service = TenantScopedMessagingService(
                messaging,
                tenant_peer_map={"tenant-a": ("device-b",)},
                allowed_conversations={"tenant-a": ("conversation-1",)},
            )
            context = ExecutionContext(
                request_id="req-2",
                tenant_id="tenant-b",
                actor_id="actor-b",
            )
            token = ExecutionContextAccessor.set(context)
            try:
                with self.assertRaises(PermissionError):
                    await service.send_message("tenant-a", "conversation-1", "forbidden")
                with self.assertRaises(ValueError):
                    await service.send_message("tenant-b", "conversation-1", "still-forbidden")
            finally:
                ExecutionContextAccessor.reset(token)
                await transport.close()
                await store.close()
                await identity.close()
                await database.close()

        asyncio.run(scenario())

    def test_example_app_enforces_tenant_scoped_routes(self):
        from apps.example_p2p_app.app import create_app

        async def identity_resolver(request):
            return AuthenticatedIdentity(actor_id="actor-a", tenant_id="tenant-a")

        app = create_app(
            identity_resolver=identity_resolver,
            database_path=":memory:",
            peer_id="device-a",
            tenant_peer_map={"tenant-a": ("device-b",)},
            allowed_conversations={"tenant-a": ("conversation-1",)},
        )

        with TestClient(app) as client:
            response = client.post(
                "/v1/tenants/tenant-a/conversations/conversation-1/messages",
                json={"body": "hello from tenant-a"},
            )
            self.assertEqual(response.status_code, 201)
            payload = response.json()
            self.assertEqual(payload["message"]["body"], "hello from tenant-a")

            list_response = client.get(
                "/v1/tenants/tenant-a/conversations/conversation-1/messages"
            )
            self.assertEqual(list_response.status_code, 200)
            self.assertEqual(len(list_response.json()["messages"]), 1)

            forbidden_response = client.post(
                "/v1/tenants/tenant-b/conversations/conversation-1/messages",
                json={"body": "bad tenant"},
            )
            self.assertEqual(forbidden_response.status_code, 403)

            sync_response = client.post(
                "/v1/tenants/tenant-a/conversations/conversation-1/sync/device-c",
                json={"messages": [], "cursor": None},
            )
            self.assertEqual(sync_response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
