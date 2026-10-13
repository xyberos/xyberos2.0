"""Test utilities for the storage contract.

Two things live here: a double that behaves like a provider, and the suite a provider author outside
this project runs against their own implementation. Both are dependency-free, so importing this
module costs nothing and needs no extra.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from xyberos.errors import StorageError, StorageNotFoundError, StorageSizeLimitError
from xyberos.storage.contracts import (
    DEFAULT_MAX_OBJECT_BYTES,
    MAX_KEY_LENGTH,
    Storage,
    StoredObject,
    validate_key,
)

__all__ = ["InMemoryStorage", "assert_storage_contract"]


class InMemoryStorage:
    """A provider that keeps objects in a dictionary.

    It enforces the same key rules and the same ceiling as the shipped provider, so a test that
    passes against the double is a test about the contract rather than about the double. It is also
    the reference for which behaviours the contract owns: it has no filesystem, no directory pruning,
    and no atomic rename, and it still satisfies everything the suite checks.
    """

    def __init__(
        self,
        *,
        max_object_bytes: int = DEFAULT_MAX_OBJECT_BYTES,
        max_key_length: int = MAX_KEY_LENGTH,
    ) -> None:
        self._objects: dict[str, bytes] = {}
        self._max_object_bytes = max_object_bytes
        self._max_key_length = max_key_length

    @property
    def max_object_bytes(self) -> int:
        """The largest object this provider accepts; ``put`` refuses anything larger."""
        return self._max_object_bytes

    async def put(self, key: str, data: bytes) -> StoredObject:
        """Store ``data`` under ``key``, replacing what was there, and report what was stored."""
        validate_key(key, max_length=self._max_key_length)
        payload = bytes(data)
        if len(payload) > self._max_object_bytes:
            raise StorageSizeLimitError(
                f"{key!r} is {len(payload)} bytes, over this provider's "
                f"{self._max_object_bytes}-byte ceiling"
            )
        self._objects[key] = payload
        return StoredObject(key=key, size=len(payload))

    async def get(self, key: str) -> bytes:
        """Return the bytes stored under ``key``, or raise :class:`StorageNotFoundError`."""
        validate_key(key, max_length=self._max_key_length)
        try:
            return self._objects[key]
        except KeyError as error:
            raise StorageNotFoundError(f"no object is stored under {key!r}") from error

    async def delete(self, key: str) -> bool:
        """Remove ``key`` and report whether an object was there."""
        validate_key(key, max_length=self._max_key_length)
        return self._objects.pop(key, None) is not None

    async def list_keys(self, prefix: str = "") -> AsyncIterator[str]:
        """Yield the keys under ``prefix`` in ascending order."""
        for key in sorted(self._objects):
            if key.startswith(prefix):
                yield key

    async def health(self) -> None:
        """Return normally: the double is always usable, and says so rather than pretending."""


async def assert_storage_contract(
    storage: Storage,
    *,
    prefix: str = "xyberos-conformance",
) -> tuple[str, ...]:
    """Check that ``storage`` behaves the way :class:`Storage` says, and report what ran.

    This is the suite a provider author outside this project runs against their own implementation —
    the same claims are checked here as against the shipped local-filesystem provider, so "we support
    an S3-compatible backend" means evidence rather than intent. It raises ``AssertionError`` naming
    the check that failed, so it is usable from pytest, an ordinary script, or another test runner.

    The caller supplies a ``prefix``, so the suite touches one namespace and removes what it created
    even after a failure: it can run again against the same provider. The checks are about the
    contract — correctness, key safety, and the ceiling. They are not about performance, durability
    against power loss, or operational maturity, and a provider that passes can still be wrong for a
    workload.
    """
    inside = f"{prefix}/inside"
    sibling = f"{prefix}-sibling"
    ordered = f"{prefix}/ordered"
    created: list[str] = []
    checked: list[str] = []

    async def store(key: str, data: bytes) -> StoredObject:
        stored = await storage.put(key, data)
        created.append(key)
        return stored

    async def listed(match: str) -> list[str]:
        return [key async for key in storage.list_keys(match)]

    async def expect_not_found(key: str, because: str) -> None:
        try:
            await storage.get(key)
        except StorageNotFoundError:
            return
        raise AssertionError(f"{because}: get() returned an object for {key!r}")

    async def expect_refused(key: str, data: bytes) -> None:
        try:
            await storage.put(key, data)
        except StorageError:
            return
        created.append(key)
        raise AssertionError(f"put() accepted {key!r}, which the contract refuses")

    try:
        await storage.health()
        checked.append("health() succeeds for a working provider")

        payload = b"\x00binary\xff\xfe payload"
        stored = await store(f"{inside}/round-trip", payload)
        if stored.key != f"{inside}/round-trip" or stored.size != len(payload):
            raise AssertionError(f"put() reported {stored!r} for a {len(payload)}-byte object")
        if await storage.get(stored.key) != payload:
            raise AssertionError("get() did not return the bytes put() stored, byte for byte")
        checked.append("put() reports what it stored and get() returns it unchanged")

        await store(f"{inside}/replaced", b"first")
        await store(f"{inside}/replaced", b"second and longer")
        if await storage.get(f"{inside}/replaced") != b"second and longer":
            raise AssertionError("put() onto an existing key did not replace the object")
        checked.append("put() onto an existing key replaces the object")

        await expect_not_found(f"{inside}/never-stored", "a key that was never stored")
        checked.append("get() raises StorageNotFoundError for a key that was never stored")

        await store(f"{inside}/deleted", b"gone soon")
        if await storage.delete(f"{inside}/deleted") is not True:
            raise AssertionError("delete() did not report removing an object that was there")
        await expect_not_found(f"{inside}/deleted", "a key that was deleted")
        checked.append("delete() removes the object and reports that it did")

        if await storage.delete(f"{inside}/deleted") is not False:
            raise AssertionError("delete() reported removing an object that was never there")
        checked.append("delete() reports False for a key that is not there")

        for name in ("c", "a", "b"):
            await store(f"{ordered}/{name}", name.encode())
        await store(f"{sibling}/outside", b"a different namespace")

        if f"{sibling}/outside" in await listed(f"{ordered}/"):
            raise AssertionError("list(prefix) yielded a key outside the prefix it was given")
        if await listed(f"{ordered}/a") != [f"{ordered}/a"]:
            raise AssertionError("list(prefix) does not match its prefix as a literal string")
        if len(await listed(f"{ordered}/")) != 3:
            raise AssertionError("list(prefix) yielded a different set on a second call")
        checked.append("list(prefix) filters by literal prefix and does not leak neighbours")

        keys = await listed(f"{ordered}/")
        if keys != [f"{ordered}/a", f"{ordered}/b", f"{ordered}/c"]:
            raise AssertionError(f"list() did not yield keys in ascending order: {keys!r}")
        checked.append("list() yields keys in ascending order")

        ceiling = storage.max_object_bytes
        await expect_refused(f"{inside}/too-large", bytes(ceiling + 1))
        await expect_not_found(f"{inside}/too-large", "an object refused for exceeding the ceiling")
        checked.append("put() refuses an object one byte over the ceiling and stores nothing")

        for bad_key in ("", "/absolute", f"{inside}/../escaped", "trailing/"):
            await expect_refused(bad_key, b"refused")
        checked.append("put() refuses an empty key, an absolute key, and a '..' segment")
    finally:
        # Cleanup is best-effort: a suite that raised must report *its* failure, not one produced by
        # the teardown of a provider that is already misbehaving.
        for key in reversed(created):
            try:
                await storage.delete(key)
            except StorageError:
                pass

    return tuple(checked)
