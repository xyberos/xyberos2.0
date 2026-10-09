from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from .container import DependencyContainer
from .contracts import (
    Capability,
    ExecutionContext,
    ExecutionContextAccessor,
    PolicyEngine,
)
from .registry import CapabilityRegistry

CapabilityHandler = Callable[..., Any]


class CapabilityExecutor:
    """Invoke registered capability handlers only after policy approval."""

    def __init__(
        self,
        capabilities: CapabilityRegistry,
        container: DependencyContainer,
    ) -> None:
        self._capabilities = capabilities
        self._container = container
        self._handlers: dict[str, CapabilityHandler] = {}

    def register_handler(
        self,
        capability: Capability,
        handler: CapabilityHandler,
    ) -> None:
        registered = self._capabilities.get(capability.name)
        if registered != capability:
            raise ValueError(
                f"Handler descriptor does not match registered capability "
                f"'{capability.name}'."
            )
        if not callable(handler):
            raise TypeError("Capability handler must be callable.")
        if capability.name in self._handlers:
            raise ValueError(
                f"A handler is already registered for capability '{capability.name}'."
            )
        self._handlers[capability.name] = handler

    async def execute(
        self,
        capability_name: str,
        *args: Any,
        resource: Any = None,
        **kwargs: Any,
    ) -> Any:
        capability = self._capabilities.get(capability_name)
        handler = self._handlers.get(capability_name)
        if handler is None:
            raise RuntimeError(
                f"No handler is registered for capability '{capability_name}'."
            )

        try:
            context = ExecutionContextAccessor.get()
        except RuntimeError as exc:
            raise PermissionError(
                "Capability execution requires a trusted execution context."
            ) from exc
        if not isinstance(context, ExecutionContext):
            raise PermissionError(
                "Capability execution requires a valid execution context."
            )
        if capability.requires_authentication and (
            not isinstance(context.actor_id, str)
            or not context.actor_id.strip()
            or not isinstance(context.tenant_id, str)
            or not context.tenant_id.strip()
        ):
            raise PermissionError(
                "Capability execution requires an authenticated actor and tenant."
            )

        try:
            policy_engine = self._container.resolve(PolicyEngine)
        except KeyError as exc:
            raise PermissionError(
                "Capability execution requires a registered PolicyEngine."
            ) from exc

        allowed = await policy_engine.authorize(context, capability, resource)
        if not isinstance(allowed, bool):
            raise TypeError("PolicyEngine.authorize must return a boolean.")
        if not allowed:
            raise PermissionError(
                f"Policy denied capability '{capability.name}'."
            )

        result = handler(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
