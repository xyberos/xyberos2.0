import asyncio
import importlib.util
import json
import tempfile
import socket
import time
import unittest
from unittest.mock import patch
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn
from starlette.applications import Starlette

from xyberos.providers.database import SQLiteProvider
from xyberos.providers.p2p.https_relay import (
    HTTPSRelayService,
    HTTPSRelayTransportProvider,
    _canonical_json,
    _request_signing_bytes,
)
from xyberos.providers.p2p.secure import (
    SodiumPeerIdentityProvider,
    decrypt_message,
    encrypt_message,
)
from xyberos.providers.p2p.sqlite_envelope_cache import SQLitePeerEnvelopeCache
from xyberos.providers.p2p.sqlite_message_store import SQLitePeerMessageStore
from xyberos.subsystems.p2p import OfflineMessagingService, PeerMessage, PeerSyncError


@unittest.skipUnless(
    importlib.util.find_spec("nacl"),
    "Install the optional p2p-crypto extra to run secure relay tests.",
)
class TestHTTPSRelay(unittest.TestCase):
    def test_identity_requires_paired_keys_and_public_bundle_has_fingerprint(self):
        async def scenario():
            identity = SodiumPeerIdentityProvider()
            with self.assertRaisesRegex(ValueError, "both private keys"):
                await identity.initialize(
                    {
                        "peer_id": "device",
                        "signing_private_key": "00" * 32,
                    }
                )

            await identity.initialize({"peer_id": "device"})
            restored = type(identity.public_keys).from_dict(
                identity.public_keys.to_dict()
            )
            self.assertEqual(restored, identity.public_keys)
            self.assertEqual(restored.fingerprint, identity.public_keys.fingerprint)
            await identity.close()

        asyncio.run(scenario())

    def test_concurrent_duplicate_nonce_is_rejected_atomically(self):
        async def scenario():
            relay_database = SQLiteProvider()
            await relay_database.initialize({"path": ":memory:"})
            sender = SodiumPeerIdentityProvider()
            recipient = SodiumPeerIdentityProvider()
            await sender.initialize({"peer_id": "sender"})
            await recipient.initialize({"peer_id": "recipient"})
            relay = HTTPSRelayService(
                relay_database,
                {
                    "sender": sender.public_keys,
                    "recipient": recipient.public_keys,
                },
                {"sender": ("recipient",), "recipient": ("sender",)},
            )
            await relay.initialize()
            app = Starlette(routes=relay.routes)
            responses = await asyncio.gather(
                _post_sync(
                    app,
                    sender,
                    "recipient",
                    {"messages": [], "cursor": None},
                    nonce="d" * 32,
                ),
                _post_sync(
                    app,
                    sender,
                    "recipient",
                    {"messages": [], "cursor": None},
                    nonce="d" * 32,
                ),
            )
            self.assertEqual(sorted(status for status, _ in responses), [200, 409])
            await relay.close()
            await sender.close()
            await recipient.close()
            await relay_database.close()

        asyncio.run(scenario())

    def test_relay_requires_mutual_known_peer_pairs(self):
        identity_a = SodiumPeerIdentityProvider()
        identity_b = SodiumPeerIdentityProvider()

        async def initialize():
            await identity_a.initialize({"peer_id": "device-a"})
            await identity_b.initialize({"peer_id": "device-b"})

        asyncio.run(initialize())
        with self.assertRaisesRegex(ValueError, "must be known and mutual"):
            HTTPSRelayService(
                SQLiteProvider(),
                {
                    "device-a": identity_a.public_keys,
                    "device-b": identity_b.public_keys,
                },
                {"device-a": ("device-b",)},
            )

        async def close():
            await identity_a.close()
            await identity_b.close()

        asyncio.run(close())

    def test_relay_paginates_large_inbox_with_stable_cursors(self):
        async def scenario():
            relay_database = SQLiteProvider()
            await relay_database.initialize({"path": ":memory:"})
            sender = SodiumPeerIdentityProvider()
            recipient = SodiumPeerIdentityProvider()
            await sender.initialize({"peer_id": "sender"})
            await recipient.initialize({"peer_id": "recipient"})
            relay = HTTPSRelayService(
                relay_database,
                {
                    "sender": sender.public_keys,
                    "recipient": recipient.public_keys,
                },
                {"sender": ("recipient",), "recipient": ("sender",)},
            )
            await relay.initialize()
            now = datetime.now(timezone.utc)
            envelopes = tuple(
                encrypt_message(
                    recipient,
                    sender.public_keys,
                    PeerMessage(
                        f"message-{index}",
                        "conversation",
                        "recipient",
                        "body",
                        now,
                    ),
                )
                for index in range(205)
            )
            await relay._store_envelopes(envelopes)

            app = Starlette(routes=relay.routes)
            cursor = None
            received = []
            for index in range(3):
                status, response = await _post_sync(
                    app,
                    sender,
                    "recipient",
                    {"messages": [], "cursor": cursor},
                    nonce=hex(index + 12)[2:] * 32,
                )
                self.assertEqual(status, 200)
                received.extend(response["messages"])
                cursor = response["next_cursor"]
                self.assertEqual(response["has_more"], index < 2)
                if index < 2:
                    self.assertIsNotNone(cursor)
            self.assertEqual(len(received), 205)
            self.assertEqual(len({item["message_id"] for item in received}), 205)
            late_envelope = encrypt_message(
                recipient,
                sender.public_keys,
                PeerMessage(
                    "late-clock-skewed-message",
                    "conversation",
                    "recipient",
                    "accepted after the cursor with an older device timestamp",
                    now - timedelta(days=1),
                ),
            )
            await relay._store_envelopes((late_envelope,))
            status, response = await _post_sync(
                app,
                sender,
                "recipient",
                {"messages": [], "cursor": cursor},
                nonce="f" * 32,
            )
            self.assertEqual(status, 200)
            self.assertEqual(
                [item["message_id"] for item in response["messages"]],
                ["late-clock-skewed-message"],
            )
            self.assertFalse(response["has_more"])
            self.assertNotEqual(response["next_cursor"], cursor)
            await relay.close()
            await sender.close()
            await recipient.close()
            await relay_database.close()

        asyncio.run(scenario())

    def test_relay_rejects_replayed_proofs_and_conflicting_message_ids(self):
        async def scenario():
            relay_database = SQLiteProvider()
            await relay_database.initialize({"path": ":memory:"})
            sender = SodiumPeerIdentityProvider()
            recipient = SodiumPeerIdentityProvider()
            await sender.initialize({"peer_id": "sender"})
            await recipient.initialize({"peer_id": "recipient"})
            relay = HTTPSRelayService(
                relay_database,
                {
                    "sender": sender.public_keys,
                    "recipient": recipient.public_keys,
                },
                {"sender": ("recipient",), "recipient": ("sender",)},
            )
            await relay.initialize()
            app = Starlette(routes=relay.routes)

            first_message = PeerMessage(
                "message-id",
                "private-conversation",
                "sender",
                "first body",
                datetime.now(timezone.utc),
            )
            first_envelope = encrypt_message(
                sender,
                recipient.public_keys,
                first_message,
            )
            status, _ = await _post_sync(
                app,
                sender,
                "recipient",
                {"messages": [first_envelope.to_dict()]},
                nonce="a" * 32,
            )
            self.assertEqual(status, 200)

            status, _ = await _post_sync(
                app,
                sender,
                "recipient",
                {"messages": [first_envelope.to_dict()]},
                nonce="a" * 32,
            )
            self.assertEqual(status, 409)

            conflicting = PeerMessage(
                "message-id",
                "private-conversation",
                "sender",
                "changed body",
                first_message.created_at,
            )
            conflicting_envelope = encrypt_message(
                sender,
                recipient.public_keys,
                conflicting,
            )
            status, _ = await _post_sync(
                app,
                sender,
                "recipient",
                {"messages": [conflicting_envelope.to_dict()]},
                nonce="b" * 32,
            )
            self.assertEqual(status, 400)

            stored = await relay_database.fetch_all(
                "SELECT payload FROM xyberos_relay_envelopes"
            )
            self.assertEqual(len(stored), 1)
            self.assertNotIn("first body", stored[0]["payload"])
            await relay.close()
            await sender.close()
            await recipient.close()
            await relay_database.close()

        asyncio.run(scenario())

    def test_https_transport_round_trips_opaque_signed_messages(self):
        async def scenario():
            database_a = SQLiteProvider()
            database_b = SQLiteProvider()
            relay_database = SQLiteProvider()
            await database_a.initialize({"path": ":memory:"})
            await database_b.initialize({"path": ":memory:"})
            await relay_database.initialize({"path": ":memory:"})

            identity_a = SodiumPeerIdentityProvider()
            identity_b = SodiumPeerIdentityProvider()
            await identity_a.initialize({"peer_id": "device-a"})
            await identity_b.initialize({"peer_id": "device-b"})
            store_a = SQLitePeerMessageStore(database_a)
            store_b = SQLitePeerMessageStore(database_b)
            await store_a.initialize({})
            await store_b.initialize({})

            relay = HTTPSRelayService(
                relay_database,
                {
                    "device-a": identity_a.public_keys,
                    "device-b": identity_b.public_keys,
                },
                {
                    "device-a": ("device-b",),
                    "device-b": ("device-a",),
                },
            )
            await relay.initialize()
            app = Starlette(routes=relay.routes)
            port = _unused_port()
            server = uvicorn.Server(
                uvicorn.Config(
                    app,
                    host="127.0.0.1",
                    port=port,
                    log_config=None,
                    access_log=False,
                    lifespan="off",
                )
            )
            server_task = asyncio.create_task(server.serve())
            try:
                for _ in range(200):
                    if server.started:
                        break
                    if server_task.done():
                        await server_task
                    await asyncio.sleep(0.01)
                self.assertTrue(server.started)

                transport_a = HTTPSRelayTransportProvider(
                    identity_a,
                    {"device-b": identity_b.public_keys},
                    SQLitePeerEnvelopeCache(database_a),
                )
                transport_b = HTTPSRelayTransportProvider(
                    identity_b,
                    {"device-a": identity_a.public_keys},
                    SQLitePeerEnvelopeCache(database_b),
                )
                relay_url = f"http://127.0.0.1:{port}"
                await transport_a.initialize({"relay_url": relay_url})
                await transport_b.initialize({"relay_url": relay_url})
                messaging_a = OfflineMessagingService(identity_a, store_a, transport_a)
                messaging_b = OfflineMessagingService(identity_b, store_b, transport_b)

                await messaging_a.send("one-to-one", "secret from A")
                await messaging_b.send("one-to-one", "secret from B")
                for index in range(205):
                    await messaging_b.send("one-to-one", f"bulk message {index}")
                self.assertEqual(await messaging_a.synchronize("device-b"), 0)
                self.assertEqual(await messaging_b.synchronize("device-a"), 1)
                async def fail_cursor_persistence_once(peer_id, cursor):
                    if peer_id != "device-b" or not cursor:
                        raise AssertionError("Unexpected synchronization cursor.")
                    raise OSError("simulated cursor persistence failure")

                with patch.object(
                    transport_a._envelope_cache,
                    "set_sync_cursor",
                    side_effect=fail_cursor_persistence_once,
                ):
                    with self.assertRaisesRegex(PeerSyncError, "persist"):
                        await messaging_a.synchronize("device-b")
                self.assertEqual(len(await store_a.all_messages()), 101)
                self.assertIsNone(
                    await transport_a._envelope_cache.get_sync_cursor("device-b")
                )
                self.assertEqual(await messaging_a.synchronize("device-b"), 106)
                self.assertIsNotNone(
                    await transport_a._envelope_cache.get_sync_cursor("device-b")
                )
                self.assertEqual(await messaging_a.synchronize("device-b"), 0)
                self.assertEqual(
                    len(await messaging_a.messages("one-to-one")),
                    207,
                )
                self.assertEqual(
                    len(await messaging_b.messages("one-to-one")),
                    207,
                )
                self.assertIn(
                    "secret from A",
                    {message.body for message in await messaging_b.messages("one-to-one")},
                )
                cursor = await database_a.fetch_one(
                    "SELECT cursor FROM xyberos_peer_sync_cursors WHERE peer_id = ?",
                    ("device-b",),
                )
                self.assertIsNotNone(cursor)

                stored = await relay_database.fetch_all(
                    "SELECT payload FROM xyberos_relay_envelopes"
                )
                self.assertEqual(len(stored), 207)
                for row in stored:
                    self.assertNotIn("secret from A", row["payload"])
                    self.assertNotIn("secret from B", row["payload"])
                await transport_a.close()
                await transport_b.close()
            finally:
                server.should_exit = True
                await asyncio.wait_for(server_task, timeout=5)
                await relay.close()
                await store_a.close()
                await store_b.close()
                await identity_a.close()
                await identity_b.close()
                await database_a.close()
                await database_b.close()
                await relay_database.close()

        asyncio.run(scenario())

    def test_sealed_box_envelopes_hide_content_and_authenticate_sender(self):
        async def scenario():
            sender = SodiumPeerIdentityProvider()
            recipient = SodiumPeerIdentityProvider()
            await sender.initialize({"peer_id": "sender"})
            await recipient.initialize({"peer_id": "recipient"})

            message = PeerMessage(
                "fixed-message-id",
                "conversation",
                "sender",
                "same content",
                datetime.now(timezone.utc),
            )
            first = encrypt_message(sender, recipient.public_keys, message)
            self.assertNotIn("same content", str(first.to_dict()))
            self.assertEqual(
                decrypt_message(recipient, sender.public_keys, first),
                message,
            )
            with self.assertRaisesRegex(ValueError, "signature"):
                decrypt_message(
                    recipient,
                    sender.public_keys,
                    replace(first, ciphertext=first.ciphertext[:-1] + b"x"),
                )
            await sender.close()
            await recipient.close()

        asyncio.run(scenario())

    def test_envelope_cache_persists_exact_ciphertext_across_restart(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                database = SQLiteProvider()
                await database.initialize(
                    {"path": str(Path(directory) / "cache.sqlite")}
                )
                sender = SodiumPeerIdentityProvider()
                recipient = SodiumPeerIdentityProvider()
                await sender.initialize({"peer_id": "sender"})
                await recipient.initialize({"peer_id": "recipient"})
                signing_key = sender.signing_private_key.hex()
                encryption_key = sender.encryption_private_key.hex()
                message = PeerMessage(
                    "stable-id",
                    "conversation",
                    "sender",
                    "retry after restart",
                    datetime.now(timezone.utc),
                )
                cache = SQLitePeerEnvelopeCache(database)
                await cache.initialize({})
                original = await cache.get_or_create(
                    "recipient",
                    message,
                    lambda: encrypt_message(sender, recipient.public_keys, message),
                )
                await cache.close()
                await sender.close()

                restarted_sender = SodiumPeerIdentityProvider()
                await restarted_sender.initialize(
                    {
                        "peer_id": "sender",
                        "signing_private_key": signing_key,
                        "encryption_private_key": encryption_key,
                    }
                )
                restarted_cache = SQLitePeerEnvelopeCache(database)
                await restarted_cache.initialize({})
                restored = await restarted_cache.get_or_create(
                    "recipient",
                    message,
                    lambda: self.fail("cached envelope should be reused"),
                )
                self.assertEqual(restored, original)
                self.assertEqual(
                    decrypt_message(recipient, restarted_sender.public_keys, restored),
                    message,
                )
                await restarted_cache.close()
                await restarted_sender.close()
                await recipient.close()
                await database.close()

        asyncio.run(scenario())


def _unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


async def _post_sync(app, sender, recipient_peer_id, payload, nonce):
    if "cursor" not in payload:
        payload = {**payload, "cursor": None}
    path = f"/v1/peers/{recipient_peer_id}/sync"
    body = _canonical_json(payload)
    timestamp = str(int(time.time()))
    signature = sender.sign(
        _request_signing_bytes("POST", path, timestamp, nonce, body)
    )
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", b"application/json"),
            (b"x-peer-id", sender.public_keys.peer_id.encode("ascii")),
            (b"x-peer-timestamp", timestamp.encode("ascii")),
            (b"x-peer-nonce", nonce.encode("ascii")),
            (b"x-peer-signature", signature.hex().encode("ascii")),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("localhost", 80),
    }
    sent = []
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    status = next(
        message["status"]
        for message in sent
        if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    )
    return status, json.loads(response_body)


if __name__ == "__main__":
    unittest.main()
