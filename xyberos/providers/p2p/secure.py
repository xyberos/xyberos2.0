from __future__ import annotations

import base64
import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from xyberos.subsystems.p2p.contracts import (
    PeerIdentity,
    PeerIdentityProvider,
    PeerMessage,
)


def _nacl():
    try:
        from nacl.exceptions import BadSignatureError, CryptoError
        from nacl.public import PrivateKey, PublicKey, SealedBox
        from nacl.signing import SigningKey, VerifyKey
    except ImportError as exc:
        raise RuntimeError(
            "Secure peer messaging requires the optional 'p2p-crypto' extra "
            "(PyNaCl/libsodium)."
        ) from exc
    return (
        BadSignatureError,
        CryptoError,
        PrivateKey,
        PublicKey,
        SealedBox,
        SigningKey,
        VerifyKey,
    )


@dataclass(frozen=True)
class PeerPublicKeys:
    peer_id: str
    signing_key: bytes
    encryption_key: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.peer_id, str) or not self.peer_id.strip():
            raise ValueError("Peer public keys require a non-empty peer ID.")
        if (
            not isinstance(self.signing_key, bytes)
            or not isinstance(self.encryption_key, bytes)
            or len(self.signing_key) != 32
            or len(self.encryption_key) != 32
        ):
            raise ValueError("Peer public keys must each be 32 bytes.")

    def to_dict(self) -> dict[str, str]:
        return {
            "peer_id": self.peer_id,
            "signing_key": self.signing_key.hex(),
            "encryption_key": self.encryption_key.hex(),
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            b"XYBEROS-PEER-KEYS-V1\0"
            + self.peer_id.encode("utf-8")
            + b"\0"
            + self.signing_key
            + self.encryption_key
        ).hexdigest()

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> PeerPublicKeys:
        if set(value) != {"peer_id", "signing_key", "encryption_key"}:
            raise ValueError("Peer public key bundle has an invalid shape.")
        peer_id = value["peer_id"]
        signing_key = value["signing_key"]
        encryption_key = value["encryption_key"]
        if not all(isinstance(item, str) for item in (peer_id, signing_key, encryption_key)):
            raise ValueError("Peer public key bundle fields must be text.")
        try:
            return cls(
                peer_id,
                bytes.fromhex(signing_key),
                bytes.fromhex(encryption_key),
            )
        except ValueError as exc:
            raise ValueError("Peer public key bundle contains invalid hex keys.") from exc


@dataclass(frozen=True)
class EncryptedPeerEnvelope:
    message_id: str
    sender_peer_id: str
    recipient_peer_id: str
    created_at: datetime
    ciphertext: bytes
    signature: bytes

    def __post_init__(self) -> None:
        for field_name in (
            "message_id",
            "sender_peer_id",
            "recipient_peer_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise ValueError(f"Envelope {field_name} must be non-empty text up to 256 characters.")
        if self.created_at.tzinfo is None:
            raise ValueError("Envelope timestamp must be timezone-aware.")
        if not isinstance(self.ciphertext, bytes) or not 1 <= len(self.ciphertext) <= 100_000:
            raise ValueError("Envelope ciphertext must be between 1 and 100000 bytes.")
        if not isinstance(self.signature, bytes) or len(self.signature) != 64:
            raise ValueError("Envelope signature must be 64 bytes.")
        object.__setattr__(self, "created_at", self.created_at.astimezone(timezone.utc))

    def unsigned_dict(self) -> dict[str, str]:
        return {
            "message_id": self.message_id,
            "sender_peer_id": self.sender_peer_id,
            "recipient_peer_id": self.recipient_peer_id,
            "created_at": self.created_at.isoformat(),
            "ciphertext": base64.b64encode(self.ciphertext).decode("ascii"),
        }

    def to_dict(self) -> dict[str, str]:
        return {
            **self.unsigned_dict(),
            "signature": base64.b64encode(self.signature).decode("ascii"),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> EncryptedPeerEnvelope:
        expected_keys = {
            "message_id",
            "sender_peer_id",
            "recipient_peer_id",
            "created_at",
            "ciphertext",
            "signature",
        }
        if set(value) != expected_keys:
            raise ValueError("Encrypted peer envelope has an invalid shape.")
        try:
            fields = (
                value["message_id"],
                value["sender_peer_id"],
                value["recipient_peer_id"],
                value["created_at"],
                value["ciphertext"],
                value["signature"],
            )
            if not all(isinstance(item, str) for item in fields):
                raise ValueError("Encrypted peer envelope fields must be text.")
            return cls(
                message_id=fields[0],
                sender_peer_id=fields[1],
                recipient_peer_id=fields[2],
                created_at=datetime.fromisoformat(fields[3]),
                ciphertext=base64.b64decode(fields[4], validate=True),
                signature=base64.b64decode(fields[5], validate=True),
            )
        except (ValueError, TypeError) as exc:
            raise ValueError("Encrypted peer envelope contains invalid field values.") from exc

    def signing_bytes(self) -> bytes:
        return b"XYBEROS-PEER-ENVELOPE-V1\n" + json.dumps(
            self.unsigned_dict(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


class PeerEnvelopeCache(ABC):
    @abstractmethod
    async def initialize(self, config: dict[str, object]) -> None:
        """Initialize local persistence for encrypted peer envelopes."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources held by the cache."""

    @abstractmethod
    async def get_or_create(
        self,
        recipient_peer_id: str,
        message: PeerMessage,
        envelope_factory: Callable[[], EncryptedPeerEnvelope],
    ) -> EncryptedPeerEnvelope:
        """Return the persisted envelope or create and persist it exactly once."""

    @abstractmethod
    async def get_sync_cursor(self, peer_id: str) -> str | None:
        """Return the last locally committed inbound cursor for this peer."""

    @abstractmethod
    async def set_sync_cursor(self, peer_id: str, cursor: str | None) -> None:
        """Persist the inbound cursor after its page has merged successfully."""


class SodiumPeerIdentityProvider(PeerIdentityProvider):
    """Ed25519-authenticated identity and sealed-box encryption keys.

    Private keys are supplied by the application or generated ephemerally when
    omitted. Persist production keys through an application-owned protected store.
    """

    def __init__(self) -> None:
        self._identity: PeerIdentity | None = None
        self._signing_key: Any = None
        self._encryption_key: Any = None

    @property
    def provider_name(self) -> str:
        return "sodium_peer_identity"

    async def initialize(self, config: dict[str, object]) -> None:
        unknown = set(config) - {
            "peer_id",
            "signing_private_key",
            "encryption_private_key",
        }
        if unknown:
            raise ValueError(
                f"Unknown secure identity config keys: {', '.join(sorted(unknown))}."
            )
        peer_id = config.get("peer_id")
        if not isinstance(peer_id, str) or not peer_id.strip():
            raise ValueError("Secure peer identity requires a non-empty 'peer_id'.")
        (
            _,
            _,
            PrivateKey,
            _,
            _,
            SigningKey,
            _,
        ) = _nacl()
        signing_value = config.get("signing_private_key")
        encryption_value = config.get("encryption_private_key")
        if signing_value is not None and not isinstance(signing_value, str):
            raise ValueError("'signing_private_key' must be hex text when supplied.")
        if encryption_value is not None and not isinstance(encryption_value, str):
            raise ValueError("'encryption_private_key' must be hex text when supplied.")
        if (signing_value is None) != (encryption_value is None):
            raise ValueError(
                "Supply both private keys together, or omit both to generate an ephemeral identity."
            )
        try:
            signing_key = (
                SigningKey(bytes.fromhex(signing_value))
                if signing_value is not None
                else SigningKey.generate()
            )
            encryption_key = (
                PrivateKey(bytes.fromhex(encryption_value))
                if encryption_value is not None
                else PrivateKey.generate()
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Configured private keys must be valid hex strings.") from exc
        self._identity = PeerIdentity(peer_id.strip())
        self._signing_key = signing_key
        self._encryption_key = encryption_key

    async def close(self) -> None:
        self._identity = None
        self._signing_key = None
        self._encryption_key = None

    async def get_identity(self) -> PeerIdentity:
        self._require_initialized()
        return self._identity

    @property
    def public_keys(self) -> PeerPublicKeys:
        identity = self._require_initialized()
        return PeerPublicKeys(
            identity.peer_id,
            bytes(self._signing_key.verify_key),
            bytes(self._encryption_key.public_key),
        )

    @property
    def signing_private_key(self) -> bytes:
        self._require_initialized()
        return bytes(self._signing_key)

    @property
    def encryption_private_key(self) -> bytes:
        self._require_initialized()
        return bytes(self._encryption_key)

    def sign(self, data: bytes) -> bytes:
        self._require_initialized()
        return self._signing_key.sign(data).signature

    def verify(self, data: bytes, signature: bytes, public_key: bytes) -> bool:
        BadSignatureError, _, _, _, _, _, VerifyKey = _nacl()
        try:
            VerifyKey(public_key).verify(data, signature)
            return True
        except BadSignatureError:
            return False

    def encrypt_for_peer(self, plaintext: bytes, recipient_key: bytes) -> bytes:
        _, _, _, PublicKey, SealedBox, _, _ = _nacl()
        self._require_initialized()
        return SealedBox(PublicKey(recipient_key)).encrypt(plaintext)

    def decrypt(
        self,
        ciphertext: bytes,
    ) -> bytes:
        _, CryptoError, PrivateKey, _, SealedBox, _, _ = _nacl()
        try:
            return SealedBox(
                PrivateKey(bytes(self._require_encryption_key()))
            ).decrypt(ciphertext)
        except CryptoError as exc:
            raise ValueError("Message could not be decrypted by this peer.") from exc

    def _require_encryption_key(self):
        self._require_initialized()
        return self._encryption_key

    def _require_initialized(self) -> PeerIdentity:
        if (
            self._identity is None
            or self._signing_key is None
            or self._encryption_key is None
        ):
            raise RuntimeError("Secure peer identity provider is not initialized.")
        return self._identity


def encrypt_message(
    identity: SodiumPeerIdentityProvider,
    recipient: PeerPublicKeys,
    message: PeerMessage,
) -> EncryptedPeerEnvelope:
    if message.sender_peer_id != identity.public_keys.peer_id:
        raise ValueError("Message sender does not match the local cryptographic identity.")
    plaintext = json.dumps(
        {
            "message_id": message.message_id,
            "conversation_id": message.conversation_id,
            "sender_peer_id": message.sender_peer_id,
            "body": message.body,
            "created_at": message.created_at.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    unsigned = EncryptedPeerEnvelope(
        message_id=message.message_id,
        sender_peer_id=message.sender_peer_id,
        recipient_peer_id=recipient.peer_id,
        created_at=message.created_at,
        ciphertext=identity.encrypt_for_peer(plaintext, recipient.encryption_key),
        signature=b"\0" * 64,
    )
    return EncryptedPeerEnvelope(
        message_id=unsigned.message_id,
        sender_peer_id=unsigned.sender_peer_id,
        recipient_peer_id=unsigned.recipient_peer_id,
        created_at=unsigned.created_at,
        ciphertext=unsigned.ciphertext,
        signature=identity.sign(unsigned.signing_bytes()),
    )


def decrypt_message(
    identity: SodiumPeerIdentityProvider,
    sender: PeerPublicKeys,
    envelope: EncryptedPeerEnvelope,
) -> PeerMessage:
    if (
        envelope.sender_peer_id != sender.peer_id
        or envelope.recipient_peer_id != identity.public_keys.peer_id
    ):
        raise ValueError("Encrypted message sender or recipient does not match its key.")
    if not identity.verify(
        envelope.signing_bytes(),
        envelope.signature,
        sender.signing_key,
    ):
        raise ValueError("Encrypted message signature is invalid.")
    try:
        message_value = json.loads(
            identity.decrypt(envelope.ciphertext)
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Decrypted peer message is not valid JSON.") from exc
    if not isinstance(message_value, dict) or set(message_value) != {
        "message_id",
        "conversation_id",
        "sender_peer_id",
        "body",
        "created_at",
    }:
        raise ValueError("Decrypted peer message has an invalid shape.")
    message = PeerMessage(
        message_id=message_value["message_id"],
        conversation_id=message_value["conversation_id"],
        sender_peer_id=message_value["sender_peer_id"],
        body=message_value["body"],
        created_at=datetime.fromisoformat(message_value["created_at"]),
    )
    if (
        message.message_id != envelope.message_id
        or message.sender_peer_id != envelope.sender_peer_id
        or message.created_at != envelope.created_at
    ):
        raise ValueError("Encrypted message metadata does not match its signed envelope.")
    return message
