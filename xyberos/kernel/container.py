from __future__ import annotations

from typing import Any, Dict, Type, TypeVar

T = TypeVar("T")


class DependencyContainer:
    """Simple explicit dependency registry for application services."""

    def __init__(self) -> None:
        self._registry: Dict[Type[Any], Any] = {}

    def register_utility(self, interface: Type[T], instance: T) -> None:
        self._registry[interface] = instance

    def resolve(self, interface: Type[T]) -> T:
        if interface not in self._registry:
            raise KeyError(f"Dependency '{interface.__name__}' is not registered.")
        return self._registry[interface]

    def unregister(self, interface: Type[Any]) -> None:
        self._registry.pop(interface, None)

    def __contains__(self, interface: Type[Any]) -> bool:
        return interface in self._registry
