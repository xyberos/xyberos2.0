from __future__ import annotations

from typing import Dict, Iterator

from .contracts import Capability, Provider, Subsystem


class SubsystemRegistry:
    """Explicit, insertion-ordered subsystem registry."""

    def __init__(self) -> None:
        self._items: Dict[str, Subsystem] = {}

    def register(self, name: str, subsystem: Subsystem) -> None:
        if not name or not name.strip():
            raise ValueError("Subsystem name must be a non-empty string.")
        if name in self._items:
            raise ValueError(f"Subsystem '{name}' is already registered.")
        self._items[name] = subsystem

    def get(self, name: str) -> Subsystem:
        try:
            return self._items[name]
        except KeyError as exc:
            raise KeyError(f"Subsystem '{name}' is not registered.") from exc

    def items(self) -> Iterator[tuple[str, Subsystem]]:
        return iter(self._items.items())

    def __contains__(self, name: str) -> bool:
        return name in self._items


class ProviderRegistry:
    """Provider registry indexed by subsystem and stable provider name."""

    def __init__(self) -> None:
        self._items: Dict[str, Dict[str, Provider]] = {}

    def register(self, subsystem_name: str, provider: Provider) -> None:
        if not subsystem_name or not subsystem_name.strip():
            raise ValueError("Subsystem name must be a non-empty string.")
        name = provider.provider_name
        if not name or not name.strip():
            raise ValueError("Provider name must be a non-empty string.")
        subsystem_providers = self._items.setdefault(subsystem_name, {})
        if name in subsystem_providers:
            raise ValueError(
                f"Provider '{name}' is already registered for subsystem "
                f"'{subsystem_name}'."
            )
        subsystem_providers[name] = provider

    def get(self, subsystem_name: str, provider_name: str) -> Provider:
        try:
            return self._items[subsystem_name][provider_name]
        except KeyError as exc:
            raise KeyError(
                f"Provider '{provider_name}' is not registered for subsystem "
                f"'{subsystem_name}'."
            ) from exc


class CapabilityRegistry:
    """Registry for named, explicitly exposed capabilities."""

    def __init__(self) -> None:
        self._items: Dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        if not capability.name or not capability.name.strip():
            raise ValueError("Capability name must be a non-empty string.")
        if capability.name in self._items:
            raise ValueError(f"Capability '{capability.name}' is already registered.")
        self._items[capability.name] = capability

    def get(self, name: str) -> Capability:
        try:
            return self._items[name]
        except KeyError as exc:
            raise KeyError(f"Capability '{name}' is not registered.") from exc
