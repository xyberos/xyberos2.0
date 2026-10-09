from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
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
_MAILBOX_USAGE_BATCH_SIZE = 500
logger = logging.getLogger("xyberos.p2p.relay")


def _positive_integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer.")
    return value


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
        self._protocol_version = 2

    @property
    def provider_name(self) -> str:
        return "https_relay"

    async def initialize(self, config: dict[str, object]) -> None:
        unknown = set(config) - {"relay_url", "timeout_seconds", "protocol_version"}
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
        protocol_version = config.get("protocol_version", 2)
        if (
            not isinstance(protocol_version, int)
            or isinstance(protocol_version, bool)
            or protocol_version not in {1, 2}
        ):
            raise ValueError("'protocol_version' must be 1 or 2.")
        await self._envelope_cache.initialize({})
        self._relay_url = relay_url
        self._timeout_seconds = float(timeout)
        self._protocol_version = protocol_version

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
        payload: dict[str, object] | None = None
        has_more: bool | None = None
        rejected_message_ids: list[str] = []
        for batch in batches:
            response_body = await asyncio.to_thread(
                self._exchange_sync,
                relay_url,
                peer_id,
                batch,
                cursor,
                self._protocol_version,
            )
            try:
                batch_payload = json.loads(response_body)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PeerSyncError("Relay returned invalid JSON.") from exc
            expected_keys = (
                {"messages", "next_cursor", "has_more"}
                if self._protocol_version == 1
                else {
                    "messages",
                    "next_cursor",
                    "has_more",
                    "rejected_message_ids",
                }
            )
            if not isinstance(batch_payload, dict) or set(batch_payload) != expected_keys:
                raise PeerSyncError("Relay response has an invalid shape.")
            batch_has_more = batch_payload["has_more"]
            if not isinstance(batch_has_more, bool):
                raise PeerSyncError("Relay response has an invalid shape.")
            if self._protocol_version == 2:
                rejected_value = batch_payload["rejected_message_ids"]
                if (
                    not isinstance(rejected_value, list)
                    or not all(
                        isinstance(message_id, str) and message_id
                        for message_id in rejected_value
                    )
                ):
                    raise PeerSyncError("Relay rejection list is invalid.")
                rejected_message_ids.extend(rejected_value)
            payload = batch_payload
            has_more = batch_has_more
        if payload is None or has_more is None:
            raise PeerSyncError("Relay returned no synchronization response.")
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
                has_more,
                tuple(dict.fromkeys(rejected_message_ids)),
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
        protocol_version: int = 2,
    ) -> bytes:
        path = f"/v{protocol_version}/peers/{quote(peer_id, safe='')}/sync"
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
        *,
        requests_per_minute: int = 60,
        request_burst: int = 10,
        mailbox_max_envelopes: int = 10_000,
        mailbox_max_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        self._requests_per_minute = _positive_integer(
            requests_per_minute,
            "requests_per_minute",
        )
        self._request_burst = _positive_integer(request_burst, "request_burst")
        self._mailbox_max_envelopes = _positive_integer(
            mailbox_max_envelopes,
            "mailbox_max_envelopes",
        )
        self._mailbox_max_bytes = _positive_integer(
            mailbox_max_bytes,
            "mailbox_max_bytes",
        )
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
                self.handle_sync_v1,
                methods=["POST"],
            ),
            Route(
                "/v2/peers/{recipient_peer_id}/sync",
                self.handle_sync_v2,
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
            CREATE TABLE IF NOT EXISTS xyberos_relay_mailbox_usage (
                recipient_peer_id TEXT PRIMARY KEY,
                envelope_count INTEGER NOT NULL,
                payload_bytes INTEGER NOT NULL
            )
            """
        )
        await self._database.execute(
            """
            CREATE TABLE IF NOT EXISTS xyberos_relay_rate_buckets (
                peer_id TEXT PRIMARY KEY,
                tokens REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        await self._database.execute(
            """
            CREATE TABLE IF NOT EXISTS xyberos_relay_state (
                name TEXT PRIMARY KEY,
                value TEXT NOT NULL
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
        await self._initialize_mailbox_usage()
        now = time.time()
        for peer_id in self._trusted_peers:
            await self._database.execute(
                """
                INSERT INTO xyberos_relay_rate_buckets (peer_id, tokens, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(peer_id) DO NOTHING
                """,
                (peer_id, float(self._request_burst), now),
            )
        self._initialized = True

    async def close(self) -> None:
        self._initialized = False

    async def _initialize_mailbox_usage(self) -> None:
        state = await self._database.fetch_one(
            "SELECT value FROM xyberos_relay_state WHERE name = ?",
            ("mailbox-usage-v1",),
        )
        if state is not None and state["value"] != "complete":
            raise RuntimeError("Relay mailbox usage migration state is invalid.")
        if state is None:
            recipient_rows = await self._database.fetch_all(
                "SELECT DISTINCT recipient_peer_id FROM xyberos_relay_envelopes"
            )
            recipients = set(self._trusted_peers)
            for row in recipient_rows:
                recipient_peer_id = row["recipient_peer_id"]
                if not isinstance(recipient_peer_id, str):
                    raise TypeError("Relay mailbox recipient ID must be text.")
                recipients.add(recipient_peer_id)

            for recipient_peer_id in sorted(recipients):
                message_id = ""
                envelope_count = 0
                payload_bytes = 0
                while True:
                    rows = await self._database.fetch_all(
                        """
                        SELECT message_id, payload
                        FROM xyberos_relay_envelopes
                        WHERE recipient_peer_id = ? AND message_id > ?
                        ORDER BY message_id
                        LIMIT ?
                        """,
                        (
                            recipient_peer_id,
                            message_id,
                            _MAILBOX_USAGE_BATCH_SIZE,
                        ),
                    )
                    if not rows:
                        break
                    for row in rows:
                        message_id_value = row["message_id"]
                        payload_value = row["payload"]
                        if not isinstance(message_id_value, str) or not isinstance(
                            payload_value,
                            str,
                        ):
                            raise TypeError("Stored relay envelope fields must be text.")
                        envelope_count += 1
                        payload_bytes += len(payload_value.encode("utf-8"))
                        message_id = message_id_value
                await self._database.execute(
                    """
                    INSERT INTO xyberos_relay_mailbox_usage
                        (recipient_peer_id, envelope_count, payload_bytes)
                    VALUES (?, ?, ?)
                    ON CONFLICT(recipient_peer_id) DO UPDATE SET
                        envelope_count = excluded.envelope_count,
                        payload_bytes = excluded.payload_bytes
                    """,
                    (recipient_peer_id, envelope_count, payload_bytes),
                )
            await self._database.execute(
                "INSERT INTO xyberos_relay_state (name, value) VALUES (?, ?)",
                ("mailbox-usage-v1", "complete"),
            )
        else:
            for peer_id in self._trusted_peers:
                await self._database.execute(
                    """
                    INSERT INTO xyberos_relay_mailbox_usage
                        (recipient_peer_id, envelope_count, payload_bytes)
                    VALUES (?, 0, 0)
                    ON CONFLICT(recipient_peer_id) DO NOTHING
                    """,
                    (peer_id,),
                )

    async def handle_sync_v1(self, request: StarletteRequest) -> JSONResponse:
        return await self._handle_sync(request, protocol_version=1)

    async def handle_sync_v2(self, request: StarletteRequest) -> JSONResponse:
        return await self._handle_sync(request, protocol_version=2)

    async def _handle_sync(
        self,
        request: StarletteRequest,
        *,
        protocol_version: int,
    ) -> JSONResponse:
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
            if protocol_version == 1:
                await self._consume_nonce(request, sender_peer_id)
            else:
                retry_after = await self._consume_rate_and_nonce(
                    request,
                    sender_peer_id,
                )
                if retry_after is not None:
                    logger.warning(
                        "P2P relay rejected a peer request at its configured rate limit.",
                        extra={"event": "p2p.relay.rate_limited"},
                    )
                    return JSONResponse(
                        {"detail": "Peer request rate limit exceeded."},
                        status_code=429,
                        headers={"retry-after": str(retry_after)},
                    )
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
            rejected_message_ids: tuple[str, ...] = ()
            if protocol_version == 1:
                await self._store_envelopes(envelopes)
            else:
                rejected_message_ids = await self._store_envelopes(
                    envelopes,
                    enforce_quota=True,
                )
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
            response_body: dict[str, object] = {
                "messages": inbox,
                "next_cursor": next_cursor,
                "has_more": has_more,
            }
            if protocol_version == 2:
                response_body["rejected_message_ids"] = list(rejected_message_ids)
            response = JSONResponse(response_body)
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

    async def _consume_rate_and_nonce(
        self,
        request: StarletteRequest,
        sender_peer_id: str,
    ) -> int | None:
        now = time.time()
        refill_per_second = self._requests_per_minute / 60
        async with self._database.transaction() as transaction:
            lock_result = await transaction.execute(
                "UPDATE xyberos_relay_rate_buckets "
                "SET tokens = tokens WHERE peer_id = ?",
                (sender_peer_id,),
            )
            if lock_result.rowcount != 1:
                raise RuntimeError("Relay rate-limit state is missing for a trusted peer.")
            row = await transaction.fetch_one(
                "SELECT tokens, updated_at FROM xyberos_relay_rate_buckets "
                "WHERE peer_id = ?",
                (sender_peer_id,),
            )
            if row is None:
                raise RuntimeError("Relay rate-limit state disappeared during request.")
            current_tokens = row["tokens"]
            updated_at = row["updated_at"]
            if not isinstance(current_tokens, (int, float)) or not isinstance(
                updated_at,
                (int, float),
            ):
                raise TypeError("Relay rate-limit state fields must be numeric.")
            elapsed = max(0.0, now - float(updated_at))
            available_tokens = min(
                float(self._request_burst),
                float(current_tokens) + elapsed * refill_per_second,
            )
            if available_tokens < 1.0:
                retry_after = max(
                    1,
                    math.ceil((1.0 - available_tokens) / refill_per_second),
                )
                await transaction.execute(
                    "UPDATE xyberos_relay_rate_buckets "
                    "SET tokens = ?, updated_at = ? WHERE peer_id = ?",
                    (available_tokens, now, sender_peer_id),
                )
                return retry_after

            nonce = request.headers["x-peer-nonce"]
            nonce_result = await transaction.execute(
                "INSERT INTO xyberos_relay_nonces (peer_id, nonce, seen_at) "
                "VALUES (?, ?, ?) ON CONFLICT(peer_id, nonce) DO NOTHING",
                (sender_peer_id, nonce, int(now)),
            )
            if nonce_result.rowcount == 0:
                raise _ReplayError
            await transaction.execute(
                "DELETE FROM xyberos_relay_nonces WHERE seen_at < ?",
                (int(now) - _MAX_TIMESTAMP_SKEW_SECONDS * 2,),
            )
            await transaction.execute(
                "UPDATE xyberos_relay_rate_buckets "
                "SET tokens = ?, updated_at = ? WHERE peer_id = ?",
                (available_tokens - 1.0, now, sender_peer_id),
            )
        return None

    async def _store_envelopes(
        self,
        envelopes: Sequence[EncryptedPeerEnvelope],
        *,
        enforce_quota: bool = False,
    ) -> tuple[str, ...]:
        rejected_message_ids: list[str] = []
        for envelope in envelopes:
            serialized = _canonical_json(envelope.to_dict()).decode("utf-8")
            serialized_bytes = len(serialized.encode("utf-8"))
            async with self._database.transaction() as transaction:
                lock_result = await transaction.execute(
                    "UPDATE xyberos_relay_mailbox_usage "
                    "SET envelope_count = envelope_count "
                    "WHERE recipient_peer_id = ?",
                    (envelope.recipient_peer_id,),
                )
                if lock_result.rowcount != 1:
                    raise RuntimeError("Relay mailbox usage state is missing.")
                existing = await transaction.fetch_one(
                    "SELECT payload FROM xyberos_relay_envelopes "
                    "WHERE recipient_peer_id = ? AND message_id = ?",
                    (envelope.recipient_peer_id, envelope.message_id),
                )
                if existing is not None:
                    if existing["payload"] != serialized:
                        raise ValueError("Message ID conflicts with a stored envelope.")
                    continue
                usage = await transaction.fetch_one(
                    "SELECT envelope_count, payload_bytes "
                    "FROM xyberos_relay_mailbox_usage "
                    "WHERE recipient_peer_id = ?",
                    (envelope.recipient_peer_id,),
                )
                if usage is None:
                    raise RuntimeError("Relay mailbox usage state disappeared.")
                envelope_count = usage["envelope_count"]
                payload_bytes = usage["payload_bytes"]
                if (
                    not isinstance(envelope_count, int)
                    or isinstance(envelope_count, bool)
                    or not isinstance(payload_bytes, int)
                    or isinstance(payload_bytes, bool)
                ):
                    raise TypeError("Relay mailbox usage fields must be integers.")
                if enforce_quota and (
                    envelope_count >= self._mailbox_max_envelopes
                    or payload_bytes + serialized_bytes > self._mailbox_max_bytes
                ):
                    rejected_message_ids.append(envelope.message_id)
                    continue
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
                    raise RuntimeError(
                        "Relay envelope changed concurrently outside mailbox locking."
                    )
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
                await transaction.execute(
                    "UPDATE xyberos_relay_mailbox_usage "
                    "SET envelope_count = envelope_count + 1, "
                    "payload_bytes = payload_bytes + ? "
                    "WHERE recipient_peer_id = ?",
                    (serialized_bytes, envelope.recipient_peer_id),
                )
        if rejected_message_ids:
            logger.warning(
                "P2P relay rejected envelopes because a mailbox reached its configured quota.",
                extra={"event": "p2p.relay.mailbox_quota_rejected"},
            )
        return tuple(rejected_message_ids)


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
