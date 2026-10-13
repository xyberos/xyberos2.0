"""Object storage, installed with the core package.

The contract, the shipped local-filesystem provider, and the double all need nothing beyond the
standard library, so this module is importable without an extra — the same rule ``xyberos.ai``
follows. A remote backend (S3-compatible or otherwise) is a provider package that runs
``assert_storage_contract``, in the shape ADR 0016 already set for databases.

Configuration is the application's: build :class:`FilesystemStorageSettings` and either hand
``filesystem_storage(settings)`` to ``app.provide`` as an eager factory, or construct
:class:`FilesystemStorage` yourself.
"""

from xyberos.storage.contracts import (
    DEFAULT_MAX_OBJECT_BYTES,
    MAX_KEY_LENGTH,
    RESERVED_SEGMENT_PREFIX,
    Storage,
    StoredObject,
    validate_key,
)
from xyberos.storage.filesystem import (
    FilesystemStorage,
    FilesystemStorageSettings,
    filesystem_storage,
    open_filesystem_storage,
)

__all__ = [
    "DEFAULT_MAX_OBJECT_BYTES",
    "MAX_KEY_LENGTH",
    "RESERVED_SEGMENT_PREFIX",
    "FilesystemStorage",
    "FilesystemStorageSettings",
    "Storage",
    "StoredObject",
    "filesystem_storage",
    "open_filesystem_storage",
    "validate_key",
]
