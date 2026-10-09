from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import re
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse
from starlette.routing import Route

from xyberos.subsystems.database.contracts import Database
from xyberos.subsystems.p2p.contracts import (
    PeerExchangePage,
    PeerMessage,
    PeerSyncError,
    PeerTransportProvider,
)

from .secure import (
    EncryptedPeerEnvelope,
    PeerEnvelopeCache,
    PeerPublicKeys,
    SodiumPeerIdentityProvider,
    decrypt_message,
    encrypt_message,
)

_MAX_REQUEST_BYTES = 4 * 1024 * 1024
_MAX_ENVELOPES_PER_REQUEST = 100
_MAX_TIMESTAMP_SKEW_SECONDS = 300
_NONCE_PATTERN = re.compile(r"^[A-Fa-f0-9]{32,128}$")
_PEER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _request_signing_bytes(
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body: bytes,
) -> bytes:
    body_hash = hashlib.sha256(body).hexdigest()
    return (
        f"XYBEROS-RELAY-REQUEST-V1\n{method}\n{path}\n"
        f"{timestamp}\n{nonce}\n{body_hash}"
    ).encode("ascii")


def _safe_relay_url(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Relay transport requires a non-empty relay_url.")
    url = value.strip().rstrip("/")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("relay_url must be an HTTP(S) URL without credentials or query.")
    if parsed.scheme == "http" and parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError("Non-loopback relay URLs must use HTTPS.")
    return url


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


class HTTPSRelayTransportProvider(PeerTransportProvider):
    """Signed, encrypted one-to-one exchange over an HTTPS relay endpoint."""

    def __init__(
        self,
        identity: SodiumPeerIdentityProvider,
        trusted_peers: Mapping[str, PeerPublicKeys],
        envelope_cache: PeerEnvelopeCache,
    ) -> None:
        if not isinstance(identity, SodiumPeerIdentityProvider):
            raise TypeError("HTTPS relay transport requires SodiumPeerIdentityProvider.")
        self._identity = identity
        if not isinstance(envelope_cache, PeerEnvelopeCache):
            raise TypeError("HTTPS relay transport requires a PeerEnvelopeCache.")
        self._envelope_cache = envelope_cache
        self._trusted_peers = dict(trusted_peers)
        for peer_id, keys in self._trusted_peers.items():
            if not isinstance(keys, PeerPublicKeys) or keys.peer_id != peer_id:
                raise ValueError(f"Pinned public keys do not match peer '{peer_id}'.")
        self._relay_url: str | None = None
        self._timeout_seconds = 30.0

    @property
    def provider_name(self) -> str:
        return "https_relay"

    async def initialize(self, config: dict[str, object]) -> None:
        unknown = set(config) - {"relay_url", "timeout_seconds"}
        if unknown:
            raise ValueError(
                f"Unknown HTTPS relay config keys: {', '.join(sorted(unknown))}."
            )
        relay_url = _safe_relay_url(config.get("relay_url"))
        timeout = config.get("timeout_seconds", 30)
        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or timeout <= 0
        ):
            raise ValueError("'timeout_seconds' must be a positive number.")
        try:
            finite_timeout = math.isfinite(float(timeout))
        except OverflowError:
            finite_timeout = False
        if not finite_timeout:
            raise ValueError("'timeout_seconds' must be a positive finite number.")
        await self._envelope_cache.initialize({})
        self._relay_url = relay_url
        self._timeout_seconds = float(timeout)

    async def close(self) -> None:
        self._relay_url = None
        await self._envelope_cache.close()

    async def exchange(
        self,
        peer_id: str,
        messages: Sequence[PeerMessage],
        cursor: str | None = None,
    ) -> PeerExchangePage:
        relay_url = self._relay_url
        if relay_url is None:
            raise RuntimeError("HTTPS relay transport is not initialized.")
        if not isinstance(peer_id, str) or peer_id not in self._trusted_peers:
            raise PeerSyncError("Target peer is not in the local pinned-key list.")
        if cursor is None:
            cursor = await self._envelope_cache.get_sync_cursor(peer_id)
        local_peer_id = (await self._identity.get_identity()).peer_id
        recipient = self._trusted_peers[peer_id]
        outgoing: list[dict[str, str]] = []
        for message in messages:
            if message.sender_peer_id != local_peer_id:
                continue
            envelope = await self._envelope_cache.get_or_create(
                peer_id,
                message,
                lambda: encrypt_message(self._identity, recipient, message),
            )
            outgoing.append(envelope.to_dict())
        batches = _batch_envelopes(outgoing, cursor)
        response_body = b""
        for batch in batches:
            response_body = await asyncio.to_thread(
                self._exchange_sync,
                relay_url,
                peer_id,
                batch,
                cursor,
            )
        try:
            payload = json.loads(response_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PeerSyncError("Relay returned invalid JSON.") from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != {"messages", "next_cursor", "has_more"}
            or not isinstance(payload["has_more"], bool)
        ):
            raise PeerSyncError("Relay response has an invalid shape.")
        incoming = payload["messages"]
        next_cursor = payload["next_cursor"]
        if next_cursor is not None and (
            not isinstance(next_cursor, str) or not next_cursor
        ):
            raise PeerSyncError("Relay response cursor is invalid.")
        cursor_values = None
        if next_cursor is not None:
            try:
                cursor_values = _decode_cursor(next_cursor)
            except ValueError as exc:
                raise PeerSyncError("Relay response cursor is malformed.") from exc
        if not isinstance(incoming, list) or len(incoming) > _MAX_ENVELOPES_PER_REQUEST:
            raise PeerSyncError("Relay returned an invalid number of messages.")
        decrypted: list[PeerMessage] = []
        for item in incoming:
            if not isinstance(item, dict):
                raise PeerSyncError("Relay returned a malformed encrypted message.")
            try:
                envelope = EncryptedPeerEnvelope.from_dict(item)
                sender_keys = self._trusted_peers.get(envelope.sender_peer_id)
                if sender_keys is None or envelope.sender_peer_id != peer_id:
                    raise ValueError("Message sender is not the requested pinned peer.")
                decrypted.append(decrypt_message(self._identity, sender_keys, envelope))
            except (TypeError, ValueError, KeyError) as exc:
                raise PeerSyncError("Relay returned an invalid or unauthenticated message.") from exc
        if decrypted:
            if (
                cursor_values is None
                or cursor_values[1] != decrypted[-1].created_at.isoformat()
                or cursor_values[2] != decrypted[-1].message_id
            ):
                raise PeerSyncError(
                    "Relay response cursor does not match its final message."
                )
        try:
            return PeerExchangePage(
                tuple(decrypted),
                next_cursor,
                payload["has_more"],
            )
        except (TypeError, ValueError) as exc:
            raise PeerSyncError("Relay response page metadata is invalid.") from exc

    async def acknowledge(self, peer_id: str, cursor: str | None) -> None:
        if peer_id not in self._trusted_peers:
            raise PeerSyncError("Cannot acknowledge an unpinned peer.")
        await self._envelope_cache.set_sync_cursor(peer_id, cursor)

    def _exchange_sync(
        self,
        relay_url: str,
        peer_id: str,
        outgoing: list[dict[str, str]],
        cursor: str | None,
    ) -> bytes:
        path = f"/v1/peers/{quote(peer_id, safe='')}/sync"
        body = _canonical_json({"messages": outgoing, "cursor": cursor})
        if len(body) > _MAX_REQUEST_BYTES:
            raise PeerSyncError("Synchronization request exceeds the 4 MiB limit.")
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        signing_bytes = _request_signing_bytes(
            "POST",
            path,
            timestamp,
            nonce,
            body,
        )
        headers = {
            "Content-Type": "application/json",
            "X-Peer-ID": (self._identity.public_keys.peer_id),
            "X-Peer-Timestamp": timestamp,
            "X-Peer-Nonce": nonce,
            "X-Peer-Signature": self._identity.sign(signing_bytes).hex(),
        }
        request = Request(
            relay_url + path,
            data=body,
            headers=headers,
            method="POST",
        )
        opener = build_opener(_NoRedirectHandler())
        try:
            with opener.open(request, timeout=self._timeout_seconds) as response:
                response_body = response.read(_MAX_REQUEST_BYTES + 1)
        except HTTPError as exc:
            exc.close()
            raise PeerSyncError(f"Relay rejected synchronization (HTTP {exc.code}).") from exc
        except URLError as exc:
            raise PeerSyncError(f"Could not reach peer relay: {exc.reason}") from exc
        if len(response_body) > _MAX_REQUEST_BYTES:
            raise PeerSyncError("Relay response exceeds the 4 MiB limit.")
        return response_body


class HTTPSRelayService:
    """ASGI endpoint for a configured one-to-one opaque ciphertext relay."""

    def __init__(
        self,
        database: Database,
        trusted_peers: Mapping[str, PeerPublicKeys],
        allowed_pairs: Mapping[str, Sequence[str]],
    ) -> None:
        self._database = database
        self._trusted_peers = dict(trusted_peers)
        for peer_id, keys in self._trusted_peers.items():
            if (
                not _PEER_ID_PATTERN.fullmatch(peer_id)
                or not isinstance(keys, PeerPublicKeys)
                or keys.peer_id != peer_id
            ):
                raise ValueError(f"Invalid trusted peer key registration for '{peer_id}'.")
        self._allowed_pairs = {
            peer_id: frozenset(peers) for peer_id, peers in allowed_pairs.items()
        }
        for peer_id, peers in self._allowed_pairs.items():
            if peer_id not in self._trusted_peers:
                raise ValueError(f"Allowed-pair list references unknown peer '{peer_id}'.")
            for target in peers:
                if (
                    target == peer_id
                    or target not in self._trusted_peers
                    or peer_id not in self._allowed_pairs.get(target, ())
                ):
                    raise ValueError(
                        f"Relay pair '{peer_id}' and '{target}' must be known and mutual."
                    )
        self._initialized = False

    @property
    def routes(self) -> list[Route]:
        return [
            Route(
                "/v1/peers/{recipient_peer_id}/sync",
                self.handle_sync,
                methods=["POST"],
            )
        ]

    async def initialize(self) -> None:
        await self._database.execute(
            """
            CREATE TABLE IF NOT EXISTS xyberos_relay_envelopes (
                recipient_peer_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                sender_peer_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (recipient_peer_id, message_id)
            )
            """
        )
        await self._database.execute(
            """
            CREATE TABLE IF NOT EXISTS xyberos_relay_nonces (
                peer_id TEXT NOT NULL,
                nonce TEXT NOT NULL,
                seen_at INTEGER NOT NULL,
                PRIMARY KEY (peer_id, nonce)
            )
            """
        )
        await self._database.execute(
            """
            CREATE TABLE IF NOT EXISTS xyberos_relay_sequences (
                recipient_peer_id TEXT PRIMARY KEY,
                sequence INTEGER NOT NULL
            )
            """
        )
        await self._database.execute(
            """
            CREATE TABLE IF NOT EXISTS xyberos_relay_envelope_order (
                recipient_peer_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (recipient_peer_id, message_id)
            )
            """
        )
        await self._database.execute(
            """
            INSERT INTO xyberos_relay_envelope_order
                (recipient_peer_id, message_id, sequence, created_at)
            SELECT recipient_peer_id, message_id, 0, created_at
            FROM xyberos_relay_envelopes
            WHERE 1 = 1
            ON CONFLICT(recipient_peer_id, message_id) DO NOTHING
            """
        )
        self._initialized = True

    async def close(self) -> None:
        self._initialized = False

    async def handle_sync(self, request: StarletteRequest) -> JSONResponse:
        if not self._initialized:
            return JSONResponse({"detail": "Relay is not ready."}, status_code=503)
        recipient_peer_id = request.path_params["recipient_peer_id"]
        sender_peer_id = request.headers.get("x-peer-id", "")
        if sender_peer_id not in self._trusted_peers:
            return JSONResponse({"detail": "Unknown peer identity."}, status_code=401)
        if (
            recipient_peer_id not in self._allowed_pairs.get(sender_peer_id, ())
            or sender_peer_id not in self._allowed_pairs.get(recipient_peer_id, ())
        ):
            return JSONResponse({"detail": "Peer pair is not authorized."}, status_code=403)
        if not _PEER_ID_PATTERN.fullmatch(recipient_peer_id):
            return JSONResponse({"detail": "Invalid recipient peer ID."}, status_code=400)
        try:
            body = await _read_limited_body(request)
            self._verify_request(request, sender_peer_id, body)
            await self._consume_nonce(request, sender_peer_id)
            payload = json.loads(body)
            envelopes, cursor = _parse_request_messages(payload)
            for envelope in envelopes:
                if (
                    envelope.sender_peer_id != sender_peer_id
                    or envelope.recipient_peer_id != recipient_peer_id
                ):
                    raise ValueError("Envelope sender/recipient does not match the route.")
                public_keys = self._trusted_peers[sender_peer_id]
                if not _verify_envelope(envelope, public_keys):
                    raise ValueError("Envelope signature is invalid.")
            await self._store_envelopes(envelopes)
            cursor_values = _decode_cursor(cursor) if cursor is not None else None
            cursor_sql = ""
            cursor_parameters: tuple[object, ...] = ()
            if cursor_values is not None:
                sequence, created_at, message_id = cursor_values
                cursor_sql = (
                    "AND (relay_order.sequence > ? OR "
                    "(relay_order.sequence = ? AND "
                    "(xyberos_relay_envelopes.created_at > ? OR "
                    "(xyberos_relay_envelopes.created_at = ? "
                    "AND xyberos_relay_envelopes.message_id > ?)))) "
                )
                cursor_parameters = (
                    sequence,
                    sequence,
                    created_at,
                    created_at,
                    message_id,
                )
            inbox_rows = await self._database.fetch_all(
                "SELECT xyberos_relay_envelopes.message_id, "
                "xyberos_relay_envelopes.sender_peer_id, "
                "xyberos_relay_envelopes.recipient_peer_id, "
                "xyberos_relay_envelopes.created_at, "
                "xyberos_relay_envelopes.payload, relay_order.sequence "
                "FROM xyberos_relay_envelopes "
                "JOIN xyberos_relay_envelope_order AS relay_order "
                "ON relay_order.recipient_peer_id = "
                "xyberos_relay_envelopes.recipient_peer_id "
                "AND relay_order.message_id = xyberos_relay_envelopes.message_id "
                "WHERE xyberos_relay_envelopes.recipient_peer_id = ? "
                "AND xyberos_relay_envelopes.sender_peer_id = ? "
                f"{cursor_sql}ORDER BY relay_order.sequence, "
                "xyberos_relay_envelopes.created_at, "
                "xyberos_relay_envelopes.message_id LIMIT ?",
                (
                    sender_peer_id,
                    recipient_peer_id,
                    *cursor_parameters,
                    _MAX_ENVELOPES_PER_REQUEST + 1,
                ),
            )
            has_more = len(inbox_rows) > _MAX_ENVELOPES_PER_REQUEST
            page_rows = inbox_rows[:_MAX_ENVELOPES_PER_REQUEST]
            inbox = [json.loads(row["payload"]) for row in page_rows]
            next_cursor = cursor
            if page_rows:
                last_row = page_rows[-1]
                next_cursor = _encode_cursor(
                    last_row["sequence"],
                    last_row["created_at"],
                    last_row["message_id"],
                )
            response = JSONResponse(
                {
                    "messages": inbox,
                    "next_cursor": next_cursor,
                    "has_more": has_more,
                }
            )
            if len(response.body) > _MAX_REQUEST_BYTES:
                return JSONResponse(
                    {"detail": "Peer inbox exceeds the relay response size limit."},
                    status_code=413,
                )
            return response
        except _PayloadTooLargeError:
            return JSONResponse({"detail": "Request exceeds 4 MiB limit."}, status_code=413)
        except _ReplayError:
            return JSONResponse({"detail": "Request nonce has already been used."}, status_code=409)
        except _InvalidSignatureError:
            return JSONResponse({"detail": "Invalid peer request signature."}, status_code=401)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, KeyError):
            return JSONResponse({"detail": "Invalid relay sync request."}, status_code=400)

    def _verify_request(
        self,
        request: StarletteRequest,
        sender_peer_id: str,
        body: bytes,
    ) -> None:
        timestamp = request.headers.get("x-peer-timestamp", "")
        nonce = request.headers.get("x-peer-nonce", "")
        signature = request.headers.get("x-peer-signature", "")
        if not timestamp.isdecimal() or not _NONCE_PATTERN.fullmatch(nonce):
            raise ValueError("Invalid peer request timestamp or nonce.")
        if abs(int(time.time()) - int(timestamp)) > _MAX_TIMESTAMP_SKEW_SECONDS:
            raise ValueError("Peer request timestamp is outside the allowed window.")
        try:
            signature_bytes = bytes.fromhex(signature)
        except ValueError as exc:
            raise ValueError("Invalid peer request signature encoding.") from exc
        data = _request_signing_bytes(
            request.method,
            request.scope["raw_path"].decode("ascii"),
            timestamp,
            nonce,
            body,
        )
        if not _verify_signature(
            data,
            signature_bytes,
            self._trusted_peers[sender_peer_id].signing_key,
        ):
            raise _InvalidSignatureError

    async def _consume_nonce(
        self,
        request: StarletteRequest,
        sender_peer_id: str,
    ) -> None:
        nonce = request.headers["x-peer-nonce"]
        now = int(time.time())
        async with self._database.transaction() as transaction:
            await transaction.execute(
                "DELETE FROM xyberos_relay_nonces WHERE seen_at < ?",
                (now - _MAX_TIMESTAMP_SKEW_SECONDS * 2,),
            )
            result = await transaction.execute(
                "INSERT INTO xyberos_relay_nonces (peer_id, nonce, seen_at) "
                "VALUES (?, ?, ?) ON CONFLICT(peer_id, nonce) DO NOTHING",
                (sender_peer_id, nonce, now),
            )
            if result.rowcount == 0:
                raise _ReplayError

    async def _store_envelopes(
        self,
        envelopes: Sequence[EncryptedPeerEnvelope],
    ) -> None:
        async with self._database.transaction() as transaction:
            for envelope in envelopes:
                serialized = _canonical_json(envelope.to_dict()).decode("utf-8")
                result = await transaction.execute(
                    "INSERT INTO xyberos_relay_envelopes "
                    "(recipient_peer_id, message_id, sender_peer_id, created_at, payload) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(recipient_peer_id, message_id) DO NOTHING",
                    (
                        envelope.recipient_peer_id,
                        envelope.message_id,
                        envelope.sender_peer_id,
                        envelope.created_at.isoformat(),
                        serialized,
                    ),
                )
                if result.rowcount == 0:
                    existing = await transaction.fetch_one(
                        "SELECT payload FROM xyberos_relay_envelopes "
                        "WHERE recipient_peer_id = ? AND message_id = ?",
                        (envelope.recipient_peer_id, envelope.message_id),
                    )
                    if existing is None or existing["payload"] != serialized:
                        raise ValueError("Message ID conflicts with a stored envelope.")
                    continue
                sequence_row = await transaction.fetch_one(
                    """
                    INSERT INTO xyberos_relay_sequences (recipient_peer_id, sequence)
                    VALUES (?, 1)
                    ON CONFLICT(recipient_peer_id)
                    DO UPDATE SET sequence = sequence + 1
                    RETURNING sequence
                    """,
                    (envelope.recipient_peer_id,),
                )
                if sequence_row is None or not isinstance(sequence_row["sequence"], int):
                    raise RuntimeError("Relay failed to allocate a mailbox sequence.")
                await transaction.execute(
                    "INSERT INTO xyberos_relay_envelope_order "
                    "(recipient_peer_id, message_id, sequence, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        envelope.recipient_peer_id,
                        envelope.message_id,
                        sequence_row["sequence"],
                        envelope.created_at.isoformat(),
                    ),
                )


class _PayloadTooLargeError(ValueError):
    pass


class _ReplayError(RuntimeError):
    pass


class _InvalidSignatureError(RuntimeError):
    pass


async def _read_limited_body(request: StarletteRequest) -> bytes:
    chunks: list[bytes] = []
    body_size = 0
    async for chunk in request.stream():
        body_size += len(chunk)
        if body_size > _MAX_REQUEST_BYTES:
            raise _PayloadTooLargeError
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_request_messages(
    payload: object,
) -> tuple[tuple[EncryptedPeerEnvelope, ...], str | None]:
    if not isinstance(payload, dict) or set(payload) != {"messages", "cursor"}:
        raise ValueError("Sync payload must contain only 'messages' and 'cursor'.")
    messages = payload["messages"]
    if not isinstance(messages, list) or len(messages) > _MAX_ENVELOPES_PER_REQUEST:
        raise ValueError("Sync payload has an invalid message list.")
    if not all(isinstance(item, dict) for item in messages):
        raise ValueError("Sync payload messages must be objects.")
    cursor = payload["cursor"]
    if cursor is not None and (not isinstance(cursor, str) or not cursor):
        raise ValueError("Sync cursor must be non-empty text when supplied.")
    if cursor is not None:
        _decode_cursor(cursor)
    return tuple(EncryptedPeerEnvelope.from_dict(item) for item in messages), cursor


def _encode_cursor(sequence: int, created_at: str, message_id: str) -> str:
    encoded = _canonical_json([sequence, created_at, message_id])
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[int, str, str]:
    if (
        not isinstance(cursor, str)
        or not cursor
        or len(cursor) > 2048
        or not re.fullmatch(r"[A-Za-z0-9_-]+", cursor)
    ):
        raise ValueError("Invalid relay cursor.")
    try:
        padding = "=" * (-len(cursor) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(cursor + padding))
        if (
            not isinstance(decoded, list)
            or len(decoded) != 3
            or not isinstance(decoded[0], int)
            or isinstance(decoded[0], bool)
            or decoded[0] < 0
            or not isinstance(decoded[1], str)
            or not isinstance(decoded[2], str)
            or not decoded[2]
            or len(decoded[2]) > 256
        ):
            raise ValueError("Invalid relay cursor fields.")
        timestamp = datetime.fromisoformat(decoded[1])
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid relay cursor.") from exc
    if timestamp.tzinfo is None:
        raise ValueError("Relay cursor timestamp must be timezone-aware.")
    return decoded[0], decoded[1], decoded[2]


def _batch_envelopes(
    outgoing: list[dict[str, str]],
    cursor: str | None,
) -> tuple[list[dict[str, str]], ...]:
    if not outgoing:
        return ([],)
    batches: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    for envelope in outgoing:
        candidate = [*current, envelope]
        candidate_body = _canonical_json({"cursor": cursor, "messages": candidate})
        if len(candidate) > _MAX_ENVELOPES_PER_REQUEST or len(candidate_body) > _MAX_REQUEST_BYTES:
            if not current:
                raise PeerSyncError("A single envelope exceeds the 4 MiB request limit.")
            batches.append(current)
            current = [envelope]
            continue
        current = candidate
    if current:
        batches.append(current)
    return tuple(batches)


def _verify_envelope(
    envelope: EncryptedPeerEnvelope,
    keys: PeerPublicKeys,
) -> bool:
    return _verify_signature(
        envelope.signing_bytes(),
        envelope.signature,
        keys.signing_key,
    )


def _verify_signature(data: bytes, signature: bytes, public_key: bytes) -> bool:
    try:
        from nacl.exceptions import BadSignatureError
        from nacl.signing import VerifyKey
    except ImportError as exc:
        raise RuntimeError(
            "Secure peer messaging requires the optional 'p2p-crypto' extra."
        ) from exc
    try:
        VerifyKey(public_key).verify(data, signature)
        return True
    except (BadSignatureError, ValueError):
        return False
