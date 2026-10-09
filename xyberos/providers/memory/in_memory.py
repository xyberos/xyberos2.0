from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from collections.abc import Mapping
from datetime import datetime, timezone

from xyberos.kernel.contracts import ExecutionContext, ExecutionContextAccessor
from xyberos.subsystems.memory.contracts import (
    MemoryMessage,
    MemoryProvider,
    MemoryScope,
)


class InMemoryMemoryProvider(MemoryProvider):
    """Process-local conversation history with exact tenant/actor scoping."""

    def __init__(self) -> None:
        self._messages: OrderedDict[MemoryScope, deque[MemoryMessage]] = OrderedDict()
        self._max_messages = 50
        self._max_conversations = 100
        self._max_message_chars = 10_000
        self._lock = asyncio.Lock()
        self._initialized = False

    @property
    def provider_name(self) -> str:
        return "in_memory"

    async def initialize(self, config: Mapping[str, object]) -> None:
        unknown_keys = set(config) - {
            "max_messages",
            "max_conversations",
            "max_message_chars",
        }
        if unknown_keys:
            raise ValueError(
                f"Unknown memory provider config keys: {', '.join(sorted(unknown_keys))}."
            )
        max_messages = _positive_integer(config, "max_messages", 50)
        max_conversations = _positive_integer(config, "max_conversations", 100)
        max_message_chars = _positive_integer(config, "max_message_chars", 10_000)
        async with self._lock:
            self._max_messages = max_messages
            self._max_conversations = max_conversations
            self._max_message_chars = max_message_chars
            self._messages.clear()
            self._initialized = True

    async def close(self) -> None:
        async with self._lock:
            self._messages.clear()
            self._initialized = False

    async def append(self, scope: MemoryScope, message: MemoryMessage) -> None:
        if not isinstance(scope, MemoryScope) or not isinstance(message, MemoryMessage):
            raise TypeError("Memory append requires a scope and MemoryMessage.")
        _require_current_scope(scope)
        async with self._lock:
            self._require_initialized()
            if len(message.content) > self._max_message_chars:
                raise ValueError("Memory message exceeds configured max_message_chars.")
            messages = self._messages.get(scope)
            if messages is None:
                if len(self._messages) >= self._max_conversations:
                    self._messages.popitem(last=False)
                messages = deque(maxlen=self._max_messages)
                self._messages[scope] = messages
            self._messages.move_to_end(scope)
            messages.append(message)

    async def list_messages(self, scope: MemoryScope) -> tuple[MemoryMessage, ...]:
        if not isinstance(scope, MemoryScope):
            raise TypeError("Memory listing requires a MemoryScope.")
        _require_current_scope(scope)
        async with self._lock:
            self._require_initialized()
            messages = self._messages.get(scope)
            if messages is None:
                return ()
            self._messages.move_to_end(scope)
            return tuple(messages)

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("In-memory memory provider is not initialized.")


def _positive_integer(config: Mapping[str, object], key: str, default: int) -> int:
    value = config.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"'{key}' must be a positive integer.")
    return value


def _require_current_scope(scope: MemoryScope) -> ExecutionContext:
    try:
        context = ExecutionContextAccessor.get()
    except RuntimeError as exc:
        raise PermissionError(
            "Memory operations require a trusted execution context."
        ) from exc
    if (
        context.tenant_id != scope.tenant_id
        or context.actor_id != scope.actor_id
    ):
        raise PermissionError("Memory scope does not match the current principal.")
    return context


def new_memory_message(role: str, content: str) -> MemoryMessage:
    """Create a message timestamped in UTC."""
    return MemoryMessage(role, content, datetime.now(timezone.utc))
