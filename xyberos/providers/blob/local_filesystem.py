from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from xyberos.subsystems.blob.contracts import BlobContent, BlobInfo, BlobProvider

_BLOB_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class LocalFilesystemBlobProvider(BlobProvider):
    """Atomic local blob storage with generated, traversal-safe identifiers."""

    def __init__(self) -> None:
        self._root: Path | None = None
        self._max_size_bytes: int | None = None

    @property
    def provider_name(self) -> str:
        return "local_filesystem"

    async def initialize(self, config: Mapping[str, object]) -> None:
        root_value = config.get("root", "./data/blobs")
        if not isinstance(root_value, str) or not root_value.strip():
            raise ValueError("Blob storage 'root' must be a non-empty path.")
        max_size = config.get("max_size_bytes")
        if max_size is not None and (
            not isinstance(max_size, int)
            or isinstance(max_size, bool)
            or max_size < 0
        ):
            raise ValueError("'max_size_bytes' must be a non-negative integer.")

        root = Path(root_value).expanduser().resolve()
        await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
        self._root = root
        self._max_size_bytes = max_size

    async def close(self) -> None:
        self._root = None
        self._max_size_bytes = None

    async def put(
        self,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> BlobInfo:
        if not isinstance(data, bytes):
            raise TypeError("Blob data must be bytes.")
        if not isinstance(content_type, str) or not content_type.strip():
            raise ValueError("Blob content_type must be a non-empty string.")
        if len(content_type) > 255 or any(ord(char) < 32 for char in content_type):
            raise ValueError("Blob content_type must be a valid short media type.")
        root = self._require_root()
        if self._max_size_bytes is not None and len(data) > self._max_size_bytes:
            raise ValueError(
                f"Blob size {len(data)} exceeds configured limit "
                f"{self._max_size_bytes}."
            )

        blob_id = uuid.uuid4().hex
        info = BlobInfo(blob_id, len(data), content_type)
        await asyncio.to_thread(self._put_sync, root, info, data)
        return info

    async def get(self, blob_id: str) -> BlobContent:
        path = self._blob_path(blob_id)
        try:
            return await asyncio.to_thread(self._get_sync, path, blob_id)
        except FileNotFoundError:
            raise

    async def delete(self, blob_id: str) -> bool:
        path = self._blob_path(blob_id)
        return await asyncio.to_thread(self._delete_sync, path)

    def _require_root(self) -> Path:
        if self._root is None:
            raise RuntimeError("Local filesystem blob provider is not initialized.")
        return self._root

    def _blob_path(self, blob_id: str) -> Path:
        if not isinstance(blob_id, str) or not _BLOB_ID_PATTERN.fullmatch(blob_id):
            raise ValueError("Blob identifier is invalid.")
        return self._require_root() / blob_id

    @staticmethod
    def _put_sync(root: Path, info: BlobInfo, data: bytes) -> None:
        target = root / info.blob_id
        staging = root / f".staging-{uuid.uuid4().hex}"
        staging.mkdir()
        try:
            (staging / "content.bin").write_bytes(data)
            (staging / "metadata.json").write_text(
                json.dumps(
                    {
                        "blob_id": info.blob_id,
                        "size_bytes": info.size_bytes,
                        "content_type": info.content_type,
                    }
                ),
                encoding="utf-8",
            )
            staging.replace(target)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    @staticmethod
    def _get_sync(path: Path, blob_id: str) -> BlobContent:
        metadata_path = path / "metadata.json"
        content_path = path / "content.bin"
        metadata: dict[str, Any] = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("blob_id") != blob_id:
            raise ValueError(f"Blob metadata does not match identifier '{blob_id}'.")
        data = content_path.read_bytes()
        info = BlobInfo(
            blob_id=blob_id,
            size_bytes=len(data),
            content_type=metadata["content_type"],
        )
        return BlobContent(info, data)

    @staticmethod
    def _delete_sync(path: Path) -> bool:
        if not path.exists():
            return False
        if not path.is_dir():
            raise ValueError("Blob storage path is not a directory.")
        shutil.rmtree(path)
        return True
