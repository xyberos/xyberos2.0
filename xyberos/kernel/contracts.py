from __future__ import annotations

from abc import ABC, abstractmethod
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, TypeVar

if TYPE_CHECKING:
    from .container import DependencyContainer

T = TypeVar("T")


@dataclass(frozen=True)
class ExecutionContext:
    """Immutable request-scoped execution metadata."""

    request_id: str
    tenant_id: str
    actor_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)


_CURRENT_CONTEXT: ContextVar[ExecutionContext | None] = ContextVar(
    "xyberos_context",
    default=None,
)


class ExecutionContextAccessor:
    """Propagates execution metadata safely across async task boundaries."""

    @staticmethod
    def get() -> ExecutionContext:
        ctx = _CURRENT_CONTEXT.get()
        if not ctx:
            raise RuntimeError(
                "Access Denied: Operational ExecutionContext missing in this scope."
            )
        return ctx

    @staticmethod
    def set(ctx: ExecutionContext) -> Any:
        return _CURRENT_CONTEXT.set(ctx)

    @staticmethod
    def reset(token: Any) -> None:
        _CURRENT_CONTEXT.reset(token)


class Subsystem(ABC):
    """Lifecycle contract for a runtime capability group."""

    @abstractmethod
    async def initialize(
        self,
        config: Dict[str, Any],
        container: DependencyContainer,
    ) -> None:
        """Initialize the subsystem, cleaning up partial resources if it fails."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Release subsystem resources during application teardown."""


class Provider(ABC):
    """Replaceable implementation contract for a subsystem."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Stable provider identifier used during registration."""


@dataclass(frozen=True)
class Capability:
    """Named capability descriptor used for authorization checks."""

    name: str
    description: str = ""
    requires_authentication: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Capability name must be non-empty text.")
        if not isinstance(self.description, str):
            raise ValueError("Capability description must be text.")
        if not isinstance(self.requires_authentication, bool):
            raise ValueError("'requires_authentication' must be a boolean.")


class PolicyEngine(ABC):
    """Contract for authorization and execution policy decisions."""

    @abstractmethod
    async def authorize(
        self,
        context: ExecutionContext,
        capability: Capability,
        resource: Any = None,
    ) -> bool:
        """Return whether the context may execute a capability on a resource."""


EventHandler = Callable[[Any], Awaitable[None] | None]


class EventBus(ABC):
    """Contract for in-process application event dispatch."""

    @abstractmethod
    def subscribe(self, event_type: type[Any], handler: EventHandler) -> None:
        """Subscribe a handler to instances of an event type."""

    @abstractmethod
    async def publish(self, event: Any) -> None:
        """Publish an event to its registered handlers."""
