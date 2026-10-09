from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from xyberos.subsystems.database.contracts import Database
from xyberos.subsystems.p2p.contracts import PeerMessage

from .secure import EncryptedPeerEnvelope, PeerEnvelopeCache


class SQLitePeerEnvelopeCache(PeerEnvelopeCache):
    """Persist exact encrypted envelopes so retries remain idempotent after restart."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._initialized = False
        self._lock = asyncio.Lock()

    async def initialize(self, config: dict[str, object]) -> None:
        if config:
            raise ValueError("SQLite peer envelope cache accepts no configuration.")
        await self._database.execute(
            """
            CREATE TABLE IF NOT EXISTS xyberos_peer_envelopes (
                recipient_peer_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                sender_peer_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (recipient_peer_id, message_id)
            )
            """
        )
        await self._database.execute(
            """
            CREATE TABLE IF NOT EXISTS xyberos_peer_sync_cursors (
                peer_id TEXT PRIMARY KEY,
                cursor TEXT NOT NULL
            )
            """
        )
        self._initialized = True

    async def close(self) -> None:
        self._initialized = False

    async def get_or_create(
        self,
        recipient_peer_id: str,
        message: PeerMessage,
        envelope_factory: Callable[[], EncryptedPeerEnvelope],
    ) -> EncryptedPeerEnvelope:
        self._require_initialized()
        async with self._lock:
            row = await self._database.fetch_one(
                "SELECT payload FROM xyberos_peer_envelopes "
                "WHERE recipient_peer_id = ? AND message_id = ?",
                (recipient_peer_id, message.message_id),
            )
            if row is not None:
                envelope = self._deserialize(row["payload"])
                if (
                    envelope.sender_peer_id != message.sender_peer_id
                    or envelope.recipient_peer_id != recipient_peer_id
                    or envelope.message_id != message.message_id
                    or envelope.created_at != message.created_at
                ):
                    raise ValueError(
                        "Cached peer envelope conflicts with the local message."
                    )
                return envelope

            envelope = envelope_factory()
            if (
                envelope.sender_peer_id != message.sender_peer_id
                or envelope.recipient_peer_id != recipient_peer_id
                or envelope.message_id != message.message_id
                or envelope.created_at != message.created_at
            ):
                raise ValueError("Envelope factory returned mismatched message metadata.")
            serialized = json.dumps(
                envelope.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
            )
            await self._database.execute(
                "INSERT INTO xyberos_peer_envelopes "
                "(recipient_peer_id, message_id, sender_peer_id, payload) "
                "VALUES (?, ?, ?, ?)",
                (
                    recipient_peer_id,
                    message.message_id,
                    message.sender_peer_id,
                    serialized,
                ),
            )
            return envelope

    async def get_sync_cursor(self, peer_id: str) -> str | None:
        self._require_initialized()
        row = await self._database.fetch_one(
            "SELECT cursor FROM xyberos_peer_sync_cursors WHERE peer_id = ?",
            (peer_id,),
        )
        if row is None:
            return None
        cursor = row["cursor"]
        if not isinstance(cursor, str) or not cursor:
            raise ValueError("Cached peer sync cursor must be non-empty text.")
        return cursor

    async def set_sync_cursor(self, peer_id: str, cursor: str | None) -> None:
        self._require_initialized()
        if cursor is None:
            await self._database.execute(
                "DELETE FROM xyberos_peer_sync_cursors WHERE peer_id = ?",
                (peer_id,),
            )
            return
        if not isinstance(cursor, str) or not cursor:
            raise ValueError("Peer sync cursor must be non-empty text when supplied.")
        await self._database.execute(
            """
            INSERT INTO xyberos_peer_sync_cursors (peer_id, cursor)
            VALUES (?, ?)
            ON CONFLICT(peer_id) DO UPDATE SET cursor = excluded.cursor
            """,
            (peer_id, cursor),
        )

    @staticmethod
    def _deserialize(value: object) -> EncryptedPeerEnvelope:
        if not isinstance(value, str):
            raise ValueError("Cached peer envelope must be serialized text.")
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("Cached peer envelope is invalid JSON.") from exc
        if not isinstance(decoded, dict):
            raise ValueError("Cached peer envelope must be a JSON object.")
        return EncryptedPeerEnvelope.from_dict(decoded)

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("SQLite peer envelope cache is not initialized.")
