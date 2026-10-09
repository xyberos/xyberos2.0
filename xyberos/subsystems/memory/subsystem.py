from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from xyberos.kernel.container import DependencyContainer
from xyberos.kernel.contracts import Subsystem

from .contracts import MemoryProvider


class MemorySubsystem(Subsystem):
    def __init__(
        self,
        providers: MemoryProvider | Mapping[str, MemoryProvider],
    ) -> None:
        if isinstance(providers, MemoryProvider):
            self.providers = {providers.provider_name: providers}
        else:
            self.providers = dict(providers)
        if not self.providers:
            raise ValueError("MemorySubsystem requires at least one provider.")
        for name, provider in self.providers.items():
            if not isinstance(provider, MemoryProvider):
                raise TypeError(
                    f"Memory provider '{name}' does not implement MemoryProvider."
                )
            if name != provider.provider_name:
                raise ValueError(
                    f"Memory provider registry key '{name}' does not match "
                    f"provider name '{provider.provider_name}'."
                )
        self._container: DependencyContainer | None = None
        self._active_provider: MemoryProvider | None = None

    async def initialize(
        self,
        config: dict[str, Any],
        container: DependencyContainer,
    ) -> None:
        unknown_keys = set(config) - {"provider", "config"}
        if unknown_keys:
            raise ValueError(
                f"Unknown memory subsystem config keys: {', '.join(sorted(unknown_keys))}."
            )
        provider_name = config.get(
            "provider",
            next(iter(self.providers)) if len(self.providers) == 1 else None,
        )
        if not isinstance(provider_name, str) or provider_name not in self.providers:
            available = ", ".join(sorted(self.providers))
            raise ValueError(
                f"Memory provider '{provider_name}' is not registered. "
                f"Available providers: {available}."
            )
        provider_config = config.get("config", {})
        if not isinstance(provider_config, Mapping):
            raise ValueError("Memory provider config must be a mapping.")
        provider = self.providers[provider_name]
        await provider.initialize(provider_config)
        container.register_utility(MemoryProvider, provider)
        self._container = container
        self._active_provider = provider

    async def shutdown(self) -> None:
        try:
            if self._active_provider is not None:
                await self._active_provider.close()
        finally:
            if self._container is not None:
                self._container.unregister(MemoryProvider)
                self._container = None
            self._active_provider = None
