from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from xyberos.kernel.contracts import Provider


@dataclass(frozen=True)
class ModelMessage:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant"}:
            raise ValueError("Model message role must be system, user, or assistant.")
        if not isinstance(self.content, str):
            raise TypeError("Model message content must be text.")


@dataclass(frozen=True)
class ModelResponse:
    content: str
    model: str
    provider: str
    finish_reason: str | None = None
    usage: Mapping[str, int] = field(default_factory=dict)


class ModelProvider(Provider, ABC):
    """Provider contract for text and structured-output model requests."""

    @abstractmethod
    async def initialize(self, config: Mapping[str, object]) -> None:
        """Validate configuration and prepare provider resources."""

    @abstractmethod
    async def close(self) -> None:
        """Release provider resources."""

    @abstractmethod
    async def generate(
        self,
        messages: Sequence[ModelMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: Mapping[str, Any] | None = None,
    ) -> ModelResponse:
        """Generate a response without performing application side effects."""
