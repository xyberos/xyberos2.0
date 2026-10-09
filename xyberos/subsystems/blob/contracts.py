from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping

from xyberos.kernel.contracts import Provider


@dataclass(frozen=True)
class BlobInfo:
    blob_id: str
    size_bytes: int
    content_type: str


@dataclass(frozen=True)
class BlobContent:
    info: BlobInfo
    data: bytes


class BlobProvider(Provider, ABC):
    @abstractmethod
    async def initialize(self, config: Mapping[str, object]) -> None:
        """Validate configuration and prepare provider resources."""

    @abstractmethod
    async def close(self) -> None:
        """Release provider resources."""

    @abstractmethod
    async def put(
        self,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> BlobInfo:
        """Persist a blob and return its generated identifier and metadata."""

    @abstractmethod
    async def get(self, blob_id: str) -> BlobContent:
        """Retrieve blob content and metadata."""

    @abstractmethod
    async def delete(self, blob_id: str) -> bool:
        """Delete a blob; return false if it did not exist."""
