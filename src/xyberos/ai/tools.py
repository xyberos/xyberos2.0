"""The tool contract: explicit registration, allowlists, validation, and audit events.

A model can only *ask* for a tool. Nothing a model returns is ever executed directly: a call is
resolved against the explicit allowlist it was invoked with, its arguments are validated against the
declared schema, and only then does the handler run. A handler receives its validated arguments and
a context — never a service container — so a tool can only reach the dependencies its author gave
it explicitly.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import TypeAlias

from xyberos.ai.contracts import ToolCall, ToolSpec
from xyberos.ai.schema import validate_payload
from xyberos.errors import AISchemaError, AITimeoutError, AIToolError
from xyberos.runtime.context import get_correlation_id, get_deadline

ToolHandler: TypeAlias = Callable[[Mapping[str, object], "ToolContext"], Awaitable[object]]
"""A tool handler: validated arguments plus an execution context, and nothing else."""


class ToolEventType(str, Enum):
    """What happened to one requested tool call."""

    REQUESTED = "requested"
    DENIED = "denied"
    INVALID = "invalid"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class ToolEvent:
    """One audited tool event.

    Events record the *names* of the arguments that were supplied and never their values, because
    tool arguments routinely carry personal data. The tool, the outcome, and the timing are the
    audit trail.
    """

    type: ToolEventType
    tool: str
    sequence: int
    argument_keys: tuple[str, ...] = ()
    duration: float | None = None
    error_type: str | None = None
    correlation_id: str | None = None

    def render(self) -> str:
        """Return a single-line description for logs and diagnostics."""
        parts = [f"#{self.sequence}", self.type.value, f"tool={self.tool}"]
        if self.argument_keys:
            parts.append(f"arguments={','.join(self.argument_keys)}")
        if self.duration is not None:
            parts.append(f"duration={self.duration:.6f}")
        if self.error_type is not None:
            parts.append(f"error={self.error_type}")
        return " ".join(parts)


ToolEventSink: TypeAlias = Callable[[ToolEvent], None]
"""A synchronous audit sink. Sinks must not block: they run on the execution path."""


@dataclass(frozen=True)
class ToolContext:
    """What a tool handler is given besides its validated arguments."""

    call_id: str | None = None
    deadline: float | None = None
    correlation_id: str | None = None

    def remaining(self) -> float | None:
        """Return the seconds left before the deadline, or ``None`` when unbounded."""
        if self.deadline is None:
            return None
        return max(self.deadline - time.monotonic(), 0.0)

    def expired(self) -> bool:
        """Whether the deadline has been reached."""
        remaining = self.remaining()
        return remaining is not None and remaining <= 0.0

    def check(self) -> None:
        """Raise if the deadline passed, so a long tool can stop between steps."""
        if self.expired():
            raise AITimeoutError("the tool ran out of time before it finished")


@dataclass(frozen=True)
class Tool:
    """A registered tool: the declaration a model sees plus the handler that runs.

    The declaration and the handler are kept apart so a declaration can be sent to a provider
    without exposing anything callable.
    """

    spec: ToolSpec
    handler: ToolHandler

    def __post_init__(self) -> None:
        if not callable(self.handler):
            raise AIToolError(
                f"tool {self.spec.name!r} needs a callable handler", tool=self.spec.name
            )

    @property
    def name(self) -> str:
        """Return the tool name."""
        return self.spec.name


@dataclass(frozen=True)
class ToolResult:
    """The outcome of one tool invocation.

    Invalid arguments and handler failures are *results*, not exceptions, so an agent loop can hand
    them back to the model. Only a call outside the allowlist raises, because that is a policy
    boundary rather than something the model can correct.
    """

    tool: str
    ok: bool
    value: object = None
    error_type: str | None = None
    error: str | None = None
    duration: float = 0.0

    def render(self) -> str:
        """Return the result as JSON text, ready to send back to a model."""
        if self.ok:
            return json.dumps(self.value, default=str, sort_keys=True)
        return json.dumps({"error_type": self.error_type, "error": self.error}, sort_keys=True)


class ToolSet:
    """The tools one call may use.

    The set *is* the allowlist: an empty set means no tool can run. Register tools explicitly with
    :meth:`add`, and pass the set to the facade for the calls that are allowed to use them.
    """

    def __init__(
        self, tools: Iterable[Tool] = (), *, on_event: ToolEventSink | None = None
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._sink = on_event
        self._sequence = 0
        for tool in tools:
            self.add(tool)

    @classmethod
    def of(cls, *tools: Tool, on_event: ToolEventSink | None = None) -> ToolSet:
        """Return a set containing ``tools``."""
        return cls(tools, on_event=on_event)

    def add(self, tool: Tool) -> None:
        """Add one tool, rejecting a duplicate name."""
        if not isinstance(tool, Tool):
            raise AIToolError(f"expected a Tool, got {type(tool).__name__}", tool="<unknown>")
        if tool.name in self._tools:
            raise AIToolError(f"tool {tool.name!r} is already registered", tool=tool.name)
        self._tools[tool.name] = tool

    @property
    def names(self) -> tuple[str, ...]:
        """Return the allowed tool names in registration order."""
        return tuple(self._tools)

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        """Return the provider-visible declarations of the allowed tools."""
        return tuple(tool.spec for tool in self._tools.values())

    def get(self, name: str) -> Tool | None:
        """Return one tool, or ``None`` when it is not allowed."""
        return self._tools.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    async def invoke(self, call: ToolCall, *, call_id: str | None = None) -> ToolResult:
        """Validate and run one requested call.

        Raises :class:`~xyberos.errors.AIToolError` when the tool is not in this set.
        """
        keys = tuple(sorted(str(name) for name in call.arguments))
        self._emit(ToolEventType.REQUESTED, call.name, argument_keys=keys)
        tool = self._tools.get(call.name)
        if tool is None:
            self._emit(ToolEventType.DENIED, call.name, argument_keys=keys)
            allowed = ", ".join(self.names) or "none"
            raise AIToolError(
                f"the model asked for tool {call.name!r}, which is not allowed for this call; "
                f"allowed tools: {allowed}",
                tool=call.name,
            )
        try:
            validate_payload(
                dict(call.arguments),
                tool.spec.parameters,
                location=f"arguments of tool {tool.name!r}",
            )
        except AISchemaError as error:
            self._emit(
                ToolEventType.INVALID, tool.name, argument_keys=keys, error_type="AISchemaError"
            )
            return ToolResult(
                tool=tool.name, ok=False, error_type="AISchemaError", error=str(error)
            )
        context = ToolContext(
            call_id=call_id or call.call_id,
            deadline=get_deadline(),
            correlation_id=get_correlation_id(),
        )
        started = time.monotonic()
        try:
            value = await tool.handler(MappingProxyType(dict(call.arguments)), context)
        except Exception as error:  # cancellation must propagate, so Exception is deliberate
            duration = time.monotonic() - started
            self._emit(
                ToolEventType.FAILED,
                tool.name,
                argument_keys=keys,
                duration=duration,
                error_type=type(error).__name__,
            )
            return ToolResult(
                tool=tool.name,
                ok=False,
                error_type=type(error).__name__,
                error=str(error),
                duration=duration,
            )
        duration = time.monotonic() - started
        self._emit(ToolEventType.SUCCEEDED, tool.name, argument_keys=keys, duration=duration)
        return ToolResult(tool=tool.name, ok=True, value=value, duration=duration)

    async def invoke_all(self, calls: Iterable[ToolCall]) -> tuple[ToolResult, ...]:
        """Validate and run several requested calls in order."""
        results = []
        for call in calls:
            results.append(await self.invoke(call))
        return tuple(results)

    def _emit(
        self,
        event_type: ToolEventType,
        tool: str,
        *,
        argument_keys: tuple[str, ...] = (),
        duration: float | None = None,
        error_type: str | None = None,
    ) -> None:
        if self._sink is None:
            return
        self._sequence += 1
        self._sink(
            ToolEvent(
                type=event_type,
                tool=tool,
                sequence=self._sequence,
                argument_keys=argument_keys,
                duration=duration,
                error_type=error_type,
                correlation_id=get_correlation_id(),
            )
        )
