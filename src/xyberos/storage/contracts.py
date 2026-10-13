"""The storage contract a service depends on, and the rules every key obeys.

The protocol is the boundary a service depends on: put, get, delete, list, and a health check over an
opaque byte payload. It deliberately says nothing about content types, versions, multipart uploads,
or signed URLs, so a provider cannot smuggle a backend-specific API into application code.

Key validation lives here rather than in each provider. A key that escapes the space it was given is
the one mistake every backend can make — ``../`` reaches a parent directory on a filesystem and is
wrong-but-harmless in an object store's namespace — so the rule is stated once, called by every
provider, and tested once.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from xyberos.errors import StorageKeyError

__all__ = [
    "DEFAULT_MAX_OBJECT_BYTES",
    "MAX_KEY_LENGTH",
    "RESERVED_SEGMENT_PREFIX",
    "Storage",
    "StoredObject",
    "validate_key",
]

MAX_KEY_LENGTH = 1024
"""The longest key the contract accepts, in characters."""

DEFAULT_MAX_OBJECT_BYTES = 64 * 1024 * 1024
"""The default ceiling on one object, in bytes. A provider may configure its own."""

RESERVED_SEGMENT_PREFIX = ".xyberos-"
"""The segment prefix a provider reserves for its own bookkeeping.

A provider needs scratch space — a temporary file that a rename publishes, a probe object that a
health check removes — and that scratch space must never be confusable with a stored key. Reserving
one prefix is cheaper to explain than a listing rule that silently hides whatever happens to be
there.
"""

_REFUSED_SEGMENTS = frozenset({"", ".", ".."})


def validate_key(key: str, *, max_length: int = MAX_KEY_LENGTH) -> str:
    """Return ``key`` if it is a usable storage key, or raise :class:`StorageKeyError`.

    A key is a *relative path*: ``/`` separates segments, there is no leading or trailing separator,
    and no segment is empty, ``.``, or ``..``. A backslash, a control character, or the reserved
    segment prefix is refused rather than normalized, because a key is data that reaches a
    filesystem, a URL, and a log line, and the one thing it must never do is name something outside
    the space it was given.
    """
    if not isinstance(key, str):
        raise StorageKeyError(f"a storage key must be a string, not {type(key).__name__}")
    if not key:
        raise StorageKeyError("a storage key must not be empty")
    if len(key) > max_length:
        raise StorageKeyError(
            f"a storage key must be at most {max_length} characters, not {len(key)}"
        )
    if "\\" in key:
        raise StorageKeyError(f"a storage key must use '/' as its separator, not '\\': {key!r}")
    if any(ord(character) < 32 or ord(character) == 127 for character in key):
        raise StorageKeyError(f"a storage key must not contain a control character: {key!r}")
    if key.startswith("/") or key.endswith("/"):
        raise StorageKeyError(f"a storage key must not start or end with '/': {key!r}")
    for segment in key.split("/"):
        if segment in _REFUSED_SEGMENTS:
            raise StorageKeyError(
                f"a storage key must not contain an empty, '.' or '..' segment: {key!r}"
            )
        if segment.startswith(RESERVED_SEGMENT_PREFIX):
            raise StorageKeyError(
                f"a storage key segment must not start with {RESERVED_SEGMENT_PREFIX!r}, which is "
                f"reserved for provider bookkeeping: {key!r}"
            )
    return key


@dataclass(frozen=True)
class StoredObject:
    """What a provider reports about an object it has just accepted."""

    key: str
    size: int


class Storage(Protocol):
    """The minimal object-storage surface a service may depend on."""

    @property
    def max_object_bytes(self) -> int:
        """The largest object this provider accepts; ``put`` refuses anything larger."""
        ...

    async def put(self, key: str, data: bytes) -> StoredObject:
        """Store ``data`` under ``key``, replacing what was there, and report what was stored."""
        ...

    async def get(self, key: str) -> bytes:
        """Return the bytes stored under ``key``, or raise ``StorageNotFoundError``."""
        ...

    async def delete(self, key: str) -> bool:
        """Remove ``key`` and report whether an object was there; deleting nothing is not an error."""
        ...

    def list_keys(self, prefix: str = "") -> AsyncIterator[str]:
        """Yield the keys under ``prefix`` in ascending order. ``prefix`` is a literal string."""
        ...

    async def health(self) -> None:
        """Raise a ``StorageError`` when the space cannot be read or written at all."""
        ...
