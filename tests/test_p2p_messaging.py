import asyncio
import tempfile
import unittest
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from xyberos.kernel import DependencyContainer
from xyberos.providers.database import SQLiteProvider
from xyberos.providers.p2p import (
    ConfiguredPeerIdentityProvider,
    InMemoryPeerTransport,
    SQLitePeerMessageStore,
)
from xyberos.subsystems.p2p import (
    OfflineMessagingService,
    P2PSubsystem,
    PeerExchangePage,
    PeerMessage,
    PeerMessageSubmissionError,
    PeerSyncError,
    PeerTransportProvider,
)


class TestOfflineMessaging(unittest.TestCase):
    def test_rejected_outbound_messages_are_reported_after_inbound_progress(self):
        async def scenario():
            database = SQLiteProvider()
            await database.initialize({"path": ":memory:"})
            store = SQLitePeerMessageStore(database)
            await store.initialize({})
            identity = ConfiguredPeerIdentityProvider()
            await identity.initialize({"peer_id": "device-a"})

            class RejectingTransport(PeerTransportProvider):
                @property
                def provider_name(self) -> str:
                    return "rejecting_test_transport"

                async def initialize(self, config: dict[str, object]) -> None:
                    del config

                async def close(self) -> None:
                    pass

                async def exchange(
                    self,
                    peer_id: str,
                    messages: Sequence[PeerMessage],
                    cursor: str | None = None,
                ) -> PeerExchangePage:
                    del peer_id, messages, cursor
                    return PeerExchangePage(
                        (),
                        None,
                        False,
                        ("pending-message",),
                    )

                async def acknowledge(
                    self,
                    peer_id: str,
                    cursor: str | None,
                ) -> None:
                    del peer_id, cursor

            transport = RejectingTransport()
            messaging = OfflineMessagingService(identity, store, transport)
            message = await messaging.send("conversation", "retry me")
            with self.assertRaises(PeerMessageSubmissionError) as raised:
                await messaging.synchronize("device-b")
            self.assertEqual(
                raised.exception.rejected_message_ids,
                ("pending-message",),
            )
            self.assertEqual(raised.exception.merged_count, 0)
            self.assertEqual(
                await store.list_messages("conversation"),
                (message,),
            )
            await store.close()
            await identity.close()
            await database.close()

        asyncio.run(scenario())

    def test_messages_are_saved_offline_then_synced_idempotently(self):
        async def scenario():
            database_a = SQLiteProvider()
            database_b = SQLiteProvider()
            await database_a.initialize({"path": ":memory:"})
            await database_b.initialize({"path": ":memory:"})
            store_a = SQLitePeerMessageStore(database_a)
            store_b = SQLitePeerMessageStore(database_b)
            await store_a.initialize({})
            await store_b.initialize({})

            identity_a = ConfiguredPeerIdentityProvider()
            identity_b = ConfiguredPeerIdentityProvider()
            await identity_a.initialize({"peer_id": "device-a"})
            await identity_b.initialize({"peer_id": "device-b"})

            transport = InMemoryPeerTransport()
            await transport.initialize({})
            await transport.attach("device-a", store_a)
            await transport.attach("device-b", store_b)
            await transport.set_online("device-b", False)
            messaging_a = OfflineMessagingService(identity_a, store_a, transport)
            messaging_b = OfflineMessagingService(identity_b, store_b, transport)
            try:
                local_message = await messaging_a.send("conversation-1", "offline note")
                with self.assertRaises(PeerSyncError):
                    await messaging_a.synchronize("device-b")
                self.assertEqual(
                    [item.message_id for item in await messaging_a.messages("conversation-1")],
                    [local_message.message_id],
                )
                self.assertEqual(await messaging_b.messages("conversation-1"), ())
                remote_message = await messaging_b.send(
                    "conversation-1",
                    "reply while offline",
                )

                await transport.set_online("device-b", True)
                self.assertEqual(await messaging_a.synchronize("device-b"), 1)
                self.assertEqual(await messaging_a.synchronize("device-b"), 0)
                self.assertEqual(await messaging_b.synchronize("device-a"), 0)
                self.assertEqual(
                    await messaging_b.messages("conversation-1"),
                    tuple(
                        sorted(
                            (local_message, remote_message),
                            key=lambda message: (
                                message.created_at,
                                message.message_id,
                            ),
                        )
                    ),
                )

                conflicting = replace(local_message, body="changed content")
                with self.assertRaisesRegex(ValueError, "conflicts"):
                    await store_b.merge((conflicting,))
            finally:
                await transport.close()
                await store_a.close()
                await store_b.close()
                await identity_a.close()
                await identity_b.close()
                await database_a.close()
                await database_b.close()

        asyncio.run(scenario())

    def test_local_message_log_survives_provider_restart(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                database_path = str(Path(directory) / "peer.sqlite")
                database = SQLiteProvider()
                await database.initialize({"path": database_path})
                store = SQLitePeerMessageStore(database)
                await store.initialize({})
                identity = ConfiguredPeerIdentityProvider()
                await identity.initialize({"peer_id": "device-local"})
                transport = InMemoryPeerTransport()
                await transport.initialize({})
                messaging = OfflineMessagingService(identity, store, transport)
                message = await messaging.send("conversation", "persist me")
                await transport.close()
                await store.close()
                await database.close()

                reopened_database = SQLiteProvider()
                await reopened_database.initialize({"path": database_path})
                reopened_store = SQLitePeerMessageStore(reopened_database)
                await reopened_store.initialize({})
                self.assertEqual(
                    await reopened_store.list_messages("conversation"),
                    (message,),
                )
                await reopened_store.close()
                await reopened_database.close()
                await identity.close()

        asyncio.run(scenario())

    def test_p2p_subsystem_registers_service_and_releases_providers(self):
        async def scenario():
            database = SQLiteProvider()
            await database.initialize({"path": ":memory:"})
            identity = ConfiguredPeerIdentityProvider()
            store = SQLitePeerMessageStore(database)
            transport = InMemoryPeerTransport()
            subsystem = P2PSubsystem(identity, store, transport)
            container = DependencyContainer()
            await subsystem.initialize(
                {
                    "identity": {"peer_id": "device"},
                    "message_store": {},
                    "transport": {},
                },
                container,
            )
            self.assertIsInstance(
                container.resolve(OfflineMessagingService),
                OfflineMessagingService,
            )
            await subsystem.shutdown()
            with self.assertRaises(KeyError):
                container.resolve(OfflineMessagingService)
            with self.assertRaises(RuntimeError):
                await identity.get_identity()
            with self.assertRaises(RuntimeError):
                await store.all_messages()
            await database.close()

        asyncio.run(scenario())

    def test_message_contract_rejects_naive_timestamps(self):
        from datetime import datetime

        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            PeerMessage(
                "message",
                "conversation",
                "device",
                "body",
                datetime.now(),
            )

    def test_message_contract_normalizes_timezone_and_limits_body(self):
        from datetime import datetime, timedelta, timezone

        message = PeerMessage(
            "message",
            "conversation",
            "device",
            "body",
            datetime(2026, 1, 1, 3, tzinfo=timezone(timedelta(hours=3))),
        )
        self.assertEqual(message.created_at.utcoffset(), timedelta(0))
        with self.assertRaisesRegex(ValueError, "65536"):
            PeerMessage(
                "message",
                "conversation",
                "device",
                "x" * 65_537,
                datetime.now(timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
