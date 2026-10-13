"""A local-filesystem storage provider: regular files under one root, and nothing else.

The key rules from the contract are enforced twice. The key is validated before it is used, and the
resolved path is checked to be inside the root afterwards — and because ``resolve()`` follows
symlinks, that second check is what makes a link pointing out of the root fail loudly instead of
being read or written through.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from xyberos.errors import (
    StorageConfigurationError,
    StorageError,
    StorageKeyError,
    StorageNotFoundError,
    StorageSizeLimitError,
)
from xyberos.storage.contracts import (
    DEFAULT_MAX_OBJECT_BYTES,
    MAX_KEY_LENGTH,
    RESERVED_SEGMENT_PREFIX,
    StoredObject,
    validate_key,
)

__all__ = [
    "FilesystemStorage",
    "FilesystemStorageSettings",
    "filesystem_storage",
    "open_filesystem_storage",
]

# Windows resolves these names to devices rather than files, with or without an extension and after
# trailing dots and spaces are trimmed, so a key that is legal on one platform would open a console
# on another. Refusing them keeps one key from meaning two things; the rule belongs to the provider
# rather than to the contract, because only a provider backed by a filesystem has the problem.
_DEVICE_NAMES = frozenset(
    ["con", "prn", "aux", "nul"]
    + [f"com{index}" for index in range(1, 10)]
    + [f"lpt{index}" for index in range(1, 10)]
)

_HEALTH_PAYLOAD = b"xyberos-storage-health"


@dataclass(frozen=True)
class FilesystemStorageSettings:
    """Explicit settings for :class:`FilesystemStorage`.

    ``root`` is created when ``create_root`` is true. Nothing is trimmed, versioned, or encrypted:
    the provider writes the bytes it is given, under the key it is given, and the deployment owns
    the directory's permissions and its backup.
    """

    root: str | Path = "var/storage"
    max_object_bytes: int = DEFAULT_MAX_OBJECT_BYTES
    max_key_length: int = MAX_KEY_LENGTH
    create_root: bool = True

    def __post_init__(self) -> None:
        if not str(self.root):
            raise StorageConfigurationError("root must not be empty")
        if self.max_object_bytes < 1:
            raise StorageConfigurationError("max_object_bytes must be at least 1")
        if self.max_key_length < 1:
            raise StorageConfigurationError("max_key_length must be at least 1")

    @property
    def directory(self) -> Path:
        """The absolute root directory, with ``~`` expanded and a relative path resolved from cwd."""
        path = Path(self.root).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()


class FilesystemStorage:
    """Store objects as regular files under one root directory.

    The provider owns no resource that has to be released — there is no connection, handle, or
    thread — so it exposes no close hook, and ``app.provide`` may construct it eagerly or lazily
    without a shutdown step. A remote provider with a connection pool would expose ``aclose()``,
    which the runtime closes because it is present, not because the contract demands it.
    """

    def __init__(self, settings: FilesystemStorageSettings) -> None:
        self._settings = settings
        self._root = settings.directory

    @property
    def settings(self) -> FilesystemStorageSettings:
        """The settings this provider was built with."""
        return self._settings

    @property
    def root(self) -> Path:
        """The directory objects are stored under."""
        return self._root

    @property
    def max_object_bytes(self) -> int:
        """The largest object this provider accepts; ``put`` refuses anything larger."""
        return self._settings.max_object_bytes

    async def put(self, key: str, data: bytes) -> StoredObject:
        """Store ``data`` under ``key``, replacing what was there, and report what was stored."""
        if isinstance(data, str):
            raise StorageError(
                "storage holds bytes, not text: encode the payload first, for example "
                "data.encode('utf-8')"
            )
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise StorageError(f"put() stores bytes, and received {type(data).__name__}")
        target = self._path_for(key)
        payload = bytes(data)
        if len(payload) > self._settings.max_object_bytes:
            raise StorageSizeLimitError(
                f"{key!r} is {len(payload)} bytes, over this provider's "
                f"{self._settings.max_object_bytes}-byte ceiling"
            )
        try:
            self._ensure_root()
            target.parent.mkdir(parents=True, exist_ok=True)
            _publish(target, payload)
        except OSError as error:
            raise StorageError(
                f"{key!r} could not be stored under {self._root}: {error}"
            ) from error
        return StoredObject(key=key, size=len(payload))

    async def get(self, key: str) -> bytes:
        """Return the bytes stored under ``key``, or raise :class:`StorageNotFoundError`."""
        target = self._path_for(key)
        try:
            return target.read_bytes()
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError) as error:
            raise StorageNotFoundError(f"no object is stored under {key!r}") from error
        except OSError as error:
            raise StorageError(f"{key!r} could not be read from {self._root}: {error}") from error

    async def delete(self, key: str) -> bool:
        """Remove ``key`` and report whether an object was there, pruning any directory it emptied."""
        target = self._path_for(key)
        try:
            target.unlink()
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            return False
        except OSError as error:
            raise StorageError(
                f"{key!r} could not be removed from {self._root}: {error}"
            ) from error
        self._prune(target.parent)
        return True

    async def list_keys(self, prefix: str = "") -> AsyncIterator[str]:
        """Yield the keys under ``prefix`` in ascending order.

        ``prefix`` is matched as a literal string, not as a directory: ``list_keys("a/b")`` also yields
        ``a/bc``. Only regular files are listed, so a directory, a temporary file left by an
        interrupted write, or a symlink never appears as an object.
        """
        for key in self._keys():
            if key.startswith(prefix):
                yield key

    async def health(self) -> None:
        """Probe the root by publishing, reading back, and removing one object.

        Existence alone is not enough: a filesystem that has gone read-only still reports a directory
        that is there. The probe carries the reserved segment prefix, so it can never collide with a
        stored key, and it is removed whether or not the read succeeded.
        """
        probe = self._root / f"{RESERVED_SEGMENT_PREFIX}health"
        try:
            self._ensure_root()
            _publish(probe, _HEALTH_PAYLOAD)
            if probe.read_bytes() != _HEALTH_PAYLOAD:
                raise StorageError(f"the storage root {self._root} did not return what was written")
        except OSError as error:
            raise StorageError(f"the storage root {self._root} is not usable: {error}") from error
        finally:
            with contextlib.suppress(OSError):
                probe.unlink(missing_ok=True)

    def _ensure_root(self) -> None:
        """Make the root usable, or explain why it is not.

        ``create_root`` is the difference between a deployment that may materialise its own directory
        and one that must find a mounted volume where it expects it: with the setting off, a missing
        root is a configuration failure at startup rather than a directory the process quietly makes.
        """
        if self._root.is_dir():
            return
        if not self._settings.create_root:
            raise StorageConfigurationError(
                f"the storage root {self._root} does not exist and create_root is false"
            )
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise StorageConfigurationError(
                f"the storage root {self._root} could not be created: {error}"
            ) from error

    def _path_for(self, key: str) -> Path:
        """Return the absolute path for ``key``, refusing anything that leaves the root.

        The contract's key rules already make an escape impossible on paper; this is the check that
        makes it impossible in practice. It is a containment test on the *resolved* path rather than
        a prefix test on the joined string, because only the first one notices a symlink.
        """
        validate_key(key, max_length=self._settings.max_key_length)
        self._refuse_device_name(key)
        target = (self._root / key).resolve()
        if target != self._root and self._root not in target.parents:
            raise StorageKeyError(
                f"{key!r} resolves outside the storage root {self._root}, so it is refused: "
                f"{target}"
            )
        return target

    @staticmethod
    def _refuse_device_name(key: str) -> None:
        for segment in key.split("/"):
            stem = segment.rstrip(" .").split(".", 1)[0].lower()
            if stem in _DEVICE_NAMES:
                raise StorageKeyError(
                    f"a storage key segment must not name a device, and {segment!r} does: on "
                    f"Windows it resolves to a device rather than a file, so one key would mean two "
                    f"things"
                )

    def _keys(self) -> list[str]:
        keys: list[str] = []
        for directory, _, filenames in os.walk(self._root, followlinks=False):
            for filename in filenames:
                if filename.startswith(RESERVED_SEGMENT_PREFIX):
                    continue
                path = Path(directory) / filename
                if path.is_symlink() or not path.is_file():
                    continue
                keys.append(path.relative_to(self._root).as_posix())
        keys.sort()
        return keys

    def _prune(self, directory: Path) -> None:
        """Remove the directories a delete emptied, up to but never including the root."""
        while directory != self._root and self._root in directory.parents:
            try:
                directory.rmdir()
            except OSError:
                return
            directory = directory.parent


def _publish(target: Path, payload: bytes) -> None:
    """Write ``payload`` beside ``target`` and rename it into place.

    A reader must never observe a half-written object, so the bytes land in a temporary file that
    ``os.replace`` publishes atomically within the filesystem. The temporary file carries the
    reserved segment prefix, so no key a caller can name collides with it.

    The bytes reach the disk on the operating system's schedule: this provider guarantees that a
    reader sees either the previous object or the new one, not that a power loss cannot lose the
    new one. A deployment that needs the stronger guarantee uses a database, not this provider.
    """
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=RESERVED_SEGMENT_PREFIX)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, target)
    finally:
        with contextlib.suppress(OSError):
            Path(temporary).unlink(missing_ok=True)


async def open_filesystem_storage(settings: FilesystemStorageSettings) -> FilesystemStorage:
    """Return a storage whose root is ready to use, or fail with the reason it is not.

    Readiness is proved by a probe write rather than by a directory test, so a root that exists but
    cannot be written is refused at startup instead of at the first upload. The root is created only
    when the settings allow it, which is why this is not a context manager: there is nothing to
    release afterwards.
    """
    storage = FilesystemStorage(settings)
    await storage.health()
    return storage


def filesystem_storage(
    settings: FilesystemStorageSettings,
) -> Callable[[], Awaitable[FilesystemStorage]]:
    """Return a zero-argument async factory, in the shape ``sqlite_provider`` already uses.

    The application owns configuration, so it composes the settings; the provider records them and
    hands ``app.provide(Storage, factory=filesystem_storage(settings), eager=True)`` the callable
    that opens the space. Nothing here reads the environment or a configuration file.
    """

    async def factory() -> FilesystemStorage:
        return await open_filesystem_storage(settings)

    return factory
