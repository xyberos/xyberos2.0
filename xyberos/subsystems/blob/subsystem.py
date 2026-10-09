from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from xyberos.kernel.container import DependencyContainer
from xyberos.kernel.contracts import Subsystem

from .contracts import BlobProvider


class BlobSubsystem(Subsystem):
    """Lifecycle adapter that exposes a selected blob provider."""

    def __init__(self, providers: BlobProvider | Mapping[str, BlobProvider]) -> None:
        if isinstance(providers, BlobProvider):
            self.providers = {providers.provider_name: providers}
        else:
            self.providers = dict(providers)
        if not self.providers:
            raise ValueError("BlobSubsystem requires at least one provider.")
        for name, provider in self.providers.items():
            if not isinstance(provider, BlobProvider):
                raise TypeError(f"Blob provider '{name}' does not implement BlobProvider.")
            if name != provider.provider_name:
                raise ValueError(
                    f"Blob provider registry key '{name}' does not match "
                    f"provider name '{provider.provider_name}'."
                )
        self._active_provider: BlobProvider | None = None
        self._container: DependencyContainer | None = None

    async def initialize(
        self,
        config: dict[str, Any],
        container: DependencyContainer,
    ) -> None:
        provider_name = config.get(
            "provider",
            next(iter(self.providers)) if len(self.providers) == 1 else None,
        )
        if not isinstance(provider_name, str) or provider_name not in self.providers:
            available = ", ".join(sorted(self.providers))
            raise ValueError(
                f"Blob provider '{provider_name}' is not registered. "
                f"Available providers: {available}."
            )
        provider_config = config.get("config", {})
        if not isinstance(provider_config, Mapping):
            raise ValueError("Blob provider config must be a mapping.")

        provider = self.providers[provider_name]
        await provider.initialize(provider_config)
        container.register_utility(BlobProvider, provider)
        self._active_provider = provider
        self._container = container

    async def shutdown(self) -> None:
        try:
            if self._active_provider is not None:
                await self._active_provider.close()
        finally:
            if self._container is not None:
                self._container.unregister(BlobProvider)
                self._container = None
            self._active_provider = None
