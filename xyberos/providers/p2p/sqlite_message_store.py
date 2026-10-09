from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime

from xyberos.subsystems.database.contracts import Database, DatabaseTransaction
from xyberos.subsystems.p2p.contracts import PeerMessage, PeerMessageStore

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS xyberos_peer_messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    sender_peer_id TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    content_hash TEXT NOT NULL
)
"""
_INSERT_MESSAGE = """
INSERT INTO xyberos_peer_messages
    (message_id, conversation_id, sender_peer_id, body, created_at, content_hash)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(message_id) DO NOTHING
"""


class SQLitePeerMessageStore(PeerMessageStore):
    """Durable local append-only message log using Xyberos' database contract."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._initialized = False

    @property
    def provider_name(self) -> str:
        return "sqlite_message_store"

    async def initialize(self, config: dict[str, object]) -> None:
        if config:
            raise ValueError("SQLite message store accepts no configuration.")
        await self._database.execute(_CREATE_TABLE)
        self._initialized = True

    async def close(self) -> None:
        self._initialized = False

    async def append(self, message: PeerMessage) -> bool:
        self._require_initialized()
        if not isinstance(message, PeerMessage):
            raise TypeError("Peer message store accepts PeerMessage values.")
        result = await self._database.execute(
            _INSERT_MESSAGE,
            _message_parameters(message),
        )
        if result.rowcount:
            return True
        await self._verify_duplicate(message)
        return False

    async def merge(self, messages: Sequence[PeerMessage]) -> int:
        self._require_initialized()
        if isinstance(messages, (str, bytes)) or not isinstance(messages, Sequence):
            raise TypeError("Peer message merge requires a sequence of messages.")
        merged = 0
        async with self._database.transaction() as transaction:
            for message in messages:
                if not isinstance(message, PeerMessage):
                    raise TypeError("Peer message merge accepts PeerMessage values.")
                result = await transaction.execute(
                    _INSERT_MESSAGE,
                    _message_parameters(message),
                )
                if result.rowcount:
                    merged += 1
                else:
                    await _verify_duplicate_with(transaction, message)
        return merged

    async def list_messages(
        self,
        conversation_id: str,
    ) -> tuple[PeerMessage, ...]:
        self._require_initialized()
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise ValueError("Conversation ID must be non-empty text.")
        rows = await self._database.fetch_all(
            "SELECT message_id, conversation_id, sender_peer_id, body, created_at "
            "FROM xyberos_peer_messages WHERE conversation_id = ? "
            "ORDER BY created_at ASC, message_id ASC",
            (conversation_id,),
        )
        return tuple(_message_from_row(row) for row in rows)

    async def all_messages(self) -> tuple[PeerMessage, ...]:
        self._require_initialized()
        rows = await self._database.fetch_all(
            "SELECT message_id, conversation_id, sender_peer_id, body, created_at "
            "FROM xyberos_peer_messages ORDER BY created_at ASC, message_id ASC"
        )
        return tuple(_message_from_row(row) for row in rows)

    async def _verify_duplicate(self, message: PeerMessage) -> None:
        row = await self._database.fetch_one(
            "SELECT conversation_id, sender_peer_id, body, created_at, content_hash "
            "FROM xyberos_peer_messages WHERE message_id = ?",
            (message.message_id,),
        )
        _assert_duplicate_matches(row, message)

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("SQLite peer message store is not initialized.")


async def _verify_duplicate_with(
    transaction: DatabaseTransaction,
    message: PeerMessage,
) -> None:
    row = await transaction.fetch_one(
        "SELECT conversation_id, sender_peer_id, body, created_at, content_hash "
        "FROM xyberos_peer_messages WHERE message_id = ?",
        (message.message_id,),
    )
    _assert_duplicate_matches(row, message)


def _message_parameters(message: PeerMessage) -> tuple[str, ...]:
    created_at = message.created_at.isoformat()
    return (
        message.message_id,
        message.conversation_id,
        message.sender_peer_id,
        message.body,
        created_at,
        _message_hash(message, created_at),
    )


def _message_hash(message: PeerMessage, created_at: str) -> str:
    canonical = json.dumps(
        [
            message.conversation_id,
            message.sender_peer_id,
            message.body,
            created_at,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _assert_duplicate_matches(
    row: dict[str, object] | None,
    message: PeerMessage,
) -> None:
    created_at = message.created_at.isoformat()
    if row is None or (
        row["conversation_id"] != message.conversation_id
        or row["sender_peer_id"] != message.sender_peer_id
        or row["body"] != message.body
        or row["created_at"] != created_at
        or row["content_hash"] != _message_hash(message, created_at)
    ):
        raise ValueError(
            f"Peer message ID '{message.message_id}' conflicts with existing content."
        )


def _message_from_row(row: dict[str, object]) -> PeerMessage:
    return PeerMessage(
        message_id=row["message_id"],
        conversation_id=row["conversation_id"],
        sender_peer_id=row["sender_peer_id"],
        body=row["body"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )
