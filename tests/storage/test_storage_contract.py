"""The storage contract, checked against the providers we ship.

`assert_storage_contract` exists so a provider author outside this project can prove their
implementation behaves the way the contract says. That makes two things worth testing here: that
both shipped providers pass, and that the suite *fails* for a provider that breaks the contract. A
conformance suite that passes for everything would be worse than none, because it would be evidence
that means nothing.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from xyberos.storage import (
    FilesystemStorageSettings,
    Storage,
    StoredObject,
    open_filesystem_storage,
)
from xyberos.storage.testing import InMemoryStorage, assert_storage_contract

# A small ceiling keeps the boundary check cheap: the suite allocates one byte more than the
# provider accepts, and the shipped default is 64 MiB, which is a lot of zeros to allocate in a unit
# test.
CEILING = 4096


def filesystem_settings(tmp_path: Path) -> FilesystemStorageSettings:
    return FilesystemStorageSettings(root=tmp_path / "objects", max_object_bytes=CEILING)


@pytest.mark.parametrize("provider", ["filesystem", "memory"])
def test_both_shipped_providers_satisfy_the_contract(provider: str, tmp_path: Path) -> None:
    async def scenario() -> tuple[str, ...]:
        storage: Storage
        if provider == "filesystem":
            storage = await open_filesystem_storage(filesystem_settings(tmp_path))
        else:
            storage = InMemoryStorage(max_object_bytes=CEILING)
        return await assert_storage_contract(storage)

    checked = asyncio.run(scenario())

    assert len(checked) == 10
    assert any("ascending order" in name for name in checked)
    assert any("ceiling" in name for name in checked)
    assert any("refuses an empty key" in name for name in checked)


@pytest.mark.parametrize("provider", ["filesystem", "memory"])
def test_the_suite_can_run_twice_against_one_provider(provider: str, tmp_path: Path) -> None:
    """The suite removes what it created, including after a failure, so it is repeatable."""

    async def scenario() -> tuple[tuple[str, ...], tuple[str, ...]]:
        storage: Storage
        if provider == "filesystem":
            storage = await open_filesystem_storage(filesystem_settings(tmp_path))
        else:
            storage = InMemoryStorage(max_object_bytes=CEILING)
        return (
            await assert_storage_contract(storage),
            await assert_storage_contract(storage),
        )

    first, second = asyncio.run(scenario())

    assert first == second


def test_the_suite_leaves_nothing_behind(tmp_path: Path) -> None:
    """Not one object, and not one temporary file the atomic publish might have left."""

    async def scenario() -> list[str]:
        storage = await open_filesystem_storage(filesystem_settings(tmp_path))
        await assert_storage_contract(storage)
        return [key async for key in storage.list_keys()]

    assert asyncio.run(scenario()) == []
    assert sorted(path.name for path in (tmp_path / "objects").iterdir()) == []


class SloppyDeleteStorage:
    """A provider that reports removing an object it never found.

    Nothing is obviously broken at the call site: the caller is told the delete succeeded, and only
    a later `get` — or the contract suite — notices that the answer was not about anything real.
    """

    def __init__(self, inner: Storage) -> None:
        self._inner = inner

    @property
    def max_object_bytes(self) -> int:
        return self._inner.max_object_bytes

    async def put(self, key: str, data: bytes) -> StoredObject:
        return await self._inner.put(key, data)

    async def get(self, key: str) -> bytes:
        return await self._inner.get(key)

    async def delete(self, key: str) -> bool:
        await self._inner.delete(key)
        return True

    async def list_keys(self, prefix: str = "") -> AsyncIterator[str]:
        async for key in self._inner.list_keys(prefix):
            yield key

    async def health(self) -> None:
        await self._inner.health()


class PrefixIgnoringStorage:
    """A provider whose ``list`` yields every key it has, whatever prefix it was given."""

    def __init__(self, inner: Storage) -> None:
        self._inner = inner

    @property
    def max_object_bytes(self) -> int:
        return self._inner.max_object_bytes

    async def put(self, key: str, data: bytes) -> StoredObject:
        return await self._inner.put(key, data)

    async def get(self, key: str) -> bytes:
        return await self._inner.get(key)

    async def delete(self, key: str) -> bool:
        return await self._inner.delete(key)

    async def list_keys(self, prefix: str = "") -> AsyncIterator[str]:
        async for key in self._inner.list_keys():
            yield key

    async def health(self) -> None:
        await self._inner.health()


def test_the_suite_catches_a_provider_that_reports_deleting_nothing() -> None:
    async def scenario() -> None:
        broken = SloppyDeleteStorage(InMemoryStorage(max_object_bytes=CEILING))
        with pytest.raises(AssertionError, match="never there"):
            await assert_storage_contract(broken)

    asyncio.run(scenario())


def test_the_suite_catches_a_provider_that_ignores_the_prefix() -> None:
    async def scenario() -> None:
        broken = PrefixIgnoringStorage(InMemoryStorage(max_object_bytes=CEILING))
        with pytest.raises(AssertionError, match="outside the prefix"):
            await assert_storage_contract(broken)

    asyncio.run(scenario())
