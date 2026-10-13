"""The local-filesystem provider: what it refuses, what it bounds, and what it leaves behind.

Key rules are tested in `test_keys.py`; this file is about the provider's own promises — the root it
will not escape, the device names it will not write, the ceiling it enforces before touching the disk,
and the publish that must never leave a half-written object or a temporary file behind.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from xyberos import App
from xyberos.errors import (
    StorageConfigurationError,
    StorageError,
    StorageKeyError,
    StorageNotFoundError,
    StorageSizeLimitError,
)
from xyberos.storage import (
    FilesystemStorage,
    FilesystemStorageSettings,
    Storage,
    filesystem_storage,
    open_filesystem_storage,
)

CEILING = 1024


def settings(tmp_path: Path, **overrides: Any) -> FilesystemStorageSettings:
    return FilesystemStorageSettings(
        root=tmp_path / "objects", max_object_bytes=CEILING, **overrides
    )


def test_a_key_that_escapes_the_root_is_refused_and_plants_nothing(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = await open_filesystem_storage(settings(tmp_path))
        for key in ("../escape.txt", "/etc/passwd", "a/../../escape.txt", "../.."):
            with pytest.raises(StorageKeyError):
                await storage.put(key, b"planted")

        assert not (tmp_path / "escape.txt").exists()
        assert not (tmp_path.parent / "escape.txt").exists()
        assert not (tmp_path / "objects").parent.joinpath("escape.txt").exists()

    asyncio.run(scenario())


@pytest.mark.skipif(
    sys.platform != "win32", reason="a drive-absolute key is only absolute on Windows"
)
def test_a_windows_absolute_key_is_refused_by_the_containment_check(tmp_path: Path) -> None:
    """``C:/x`` is a legal *relative* key on POSIX and an absolute one on Windows."""

    async def scenario() -> None:
        storage = await open_filesystem_storage(settings(tmp_path))
        with pytest.raises(StorageKeyError, match="resolves outside"):
            await storage.put("C:/escape.txt", b"planted")
        with pytest.raises(StorageKeyError, match="resolves outside"):
            await storage.get("C:/escape.txt")

    asyncio.run(scenario())


def test_a_symlink_out_of_the_root_is_refused_by_both_reads_and_writes(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "objects"
    root.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - platform privilege, not logic
        pytest.skip("this platform does not allow creating a symlink without elevation")

    async def scenario() -> None:
        storage = await open_filesystem_storage(settings(tmp_path))
        with pytest.raises(StorageKeyError, match="resolves outside"):
            await storage.put("link/planted.txt", b"planted")
        with pytest.raises(StorageKeyError, match="resolves outside"):
            await storage.get("link/planted.txt")
        assert not (outside / "planted.txt").exists()
        assert [key async for key in storage.list_keys()] == []

    asyncio.run(scenario())


def test_a_key_that_names_a_device_is_refused_without_over_refusing(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = await open_filesystem_storage(settings(tmp_path))
        for key in ("con", "CON.txt", "a/nul", "lpt1", "com9.tar.gz", "aux "):
            with pytest.raises(StorageKeyError, match="must not name a device"):
                await storage.put(key, b"device")

        stored = await storage.put("con-artist.txt", b"a file whose name merely starts the same")
        assert stored.key == "con-artist.txt"
        assert stored.size == len(b"a file whose name merely starts the same")

    asyncio.run(scenario())


def test_the_ceiling_is_enforced_before_the_disk_is_touched(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = await open_filesystem_storage(settings(tmp_path))

        assert (await storage.put("exactly.bin", bytes(CEILING))).size == CEILING

        with pytest.raises(StorageSizeLimitError, match="ceiling"):
            await storage.put("over.bin", bytes(CEILING + 1))

        with pytest.raises(StorageNotFoundError):
            await storage.get("over.bin")
        assert [key async for key in storage.list_keys()] != []

    asyncio.run(scenario())


def test_put_stores_bytes_and_says_so_when_it_is_handed_something_else(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = await open_filesystem_storage(settings(tmp_path))

        with pytest.raises(StorageError, match="encode"):
            await storage.put("text.txt", "text")  # type: ignore[arg-type]
        with pytest.raises(StorageError, match="stores bytes"):
            await storage.put("number.bin", 5)  # type: ignore[arg-type]

        assert [key async for key in storage.list_keys()] == []

    asyncio.run(scenario())


def test_put_publishes_atomically_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = await open_filesystem_storage(settings(tmp_path))
        await storage.put("reports/q1.txt", b"quarter one")

        leftovers = [path.name for path in (tmp_path / "objects").rglob(".xyberos-*")]
        assert leftovers == []
        assert (tmp_path / "objects" / "reports" / "q1.txt").read_bytes() == b"quarter one"

    asyncio.run(scenario())


def test_overwriting_replaces_the_bytes_rather_than_appending(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = await open_filesystem_storage(settings(tmp_path))
        await storage.put("a.txt", b"x" * 100)
        await storage.put("a.txt", b"y")

        assert await storage.get("a.txt") == b"y"
        assert (tmp_path / "objects" / "a.txt").stat().st_size == 1

    asyncio.run(scenario())


def test_delete_prunes_the_directories_it_emptied_but_never_the_root(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = await open_filesystem_storage(settings(tmp_path))
        await storage.put("a/b/c.txt", b"data")
        await storage.put("a/keep/other.txt", b"data")

        assert await storage.delete("a/b/c.txt") is True

        assert not (tmp_path / "objects" / "a" / "b").exists()
        assert (tmp_path / "objects" / "a" / "keep").is_dir()
        assert (tmp_path / "objects").is_dir()

    asyncio.run(scenario())


def test_list_yields_files_only_and_hides_provider_scratch_space(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = await open_filesystem_storage(settings(tmp_path))
        await storage.put("dir/file.txt", b"x")

        (tmp_path / "objects" / "empty-dir").mkdir()
        (tmp_path / "objects" / ".xyberos-leftover").write_bytes(b"scratch")

        assert [key async for key in storage.list_keys()] == ["dir/file.txt"]

    asyncio.run(scenario())


def test_create_root_off_refuses_a_missing_root_instead_of_making_it(tmp_path: Path) -> None:
    missing = FilesystemStorageSettings(root=tmp_path / "not-mounted", create_root=False)

    with pytest.raises(StorageConfigurationError, match="does not exist"):
        asyncio.run(open_filesystem_storage(missing))

    assert not (tmp_path / "not-mounted").exists()


def test_the_factory_provides_through_the_registry_under_an_explicit_settings_object(
    tmp_path: Path,
) -> None:
    """The configuration path a package proves: the application composes, the module provides."""

    async def scenario() -> bytes:
        app = App()
        app.provide(Storage, factory=filesystem_storage(settings(tmp_path)), eager=True)
        async with app.lifespan():
            storage = await app.resolve(Storage)
            await storage.put("reports/q1.txt", b"quarter one")
            return await storage.get("reports/q1.txt")

    assert asyncio.run(scenario()) == b"quarter one"
    assert (tmp_path / "objects" / "reports" / "q1.txt").read_bytes() == b"quarter one"


def test_the_provider_records_the_settings_it_was_given(tmp_path: Path) -> None:
    configured = settings(tmp_path)
    storage = FilesystemStorage(configured)

    assert storage.settings is configured
    assert storage.max_object_bytes == CEILING
    assert storage.root == (tmp_path / "objects").resolve()
