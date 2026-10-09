from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from xyberos.kernel.container import DependencyContainer
from xyberos.kernel.contracts import Subsystem

from .contracts import KnowledgeProvider


class KnowledgeSubsystem(Subsystem):
    def __init__(
        self,
        providers: KnowledgeProvider | Mapping[str, KnowledgeProvider],
    ) -> None:
        if isinstance(providers, KnowledgeProvider):
            self.providers = {providers.provider_name: providers}
        else:
            self.providers = dict(providers)
        if not self.providers:
            raise ValueError("KnowledgeSubsystem requires at least one provider.")
        for name, provider in self.providers.items():
            if not isinstance(provider, KnowledgeProvider):
                raise TypeError(
                    f"Knowledge provider '{name}' does not implement KnowledgeProvider."
                )
            if name != provider.provider_name:
                raise ValueError(
                    f"Knowledge provider registry key '{name}' does not match "
                    f"provider name '{provider.provider_name}'."
                )
        self._container: DependencyContainer | None = None
        self._active_provider: KnowledgeProvider | None = None

    async def initialize(
        self,
        config: dict[str, Any],
        container: DependencyContainer,
    ) -> None:
        unknown_keys = set(config) - {"provider", "config"}
        if unknown_keys:
            raise ValueError(
                "Unknown knowledge subsystem config keys: "
                f"{', '.join(sorted(unknown_keys))}."
            )
        provider_name = config.get(
            "provider",
            next(iter(self.providers)) if len(self.providers) == 1 else None,
        )
        if not isinstance(provider_name, str) or provider_name not in self.providers:
            available = ", ".join(sorted(self.providers))
            raise ValueError(
                f"Knowledge provider '{provider_name}' is not registered. "
                f"Available providers: {available}."
            )
        provider_config = config.get("config", {})
        if not isinstance(provider_config, Mapping):
            raise ValueError("Knowledge provider config must be a mapping.")
        provider = self.providers[provider_name]
        await provider.initialize(provider_config)
        container.register_utility(KnowledgeProvider, provider)
        self._container = container
        self._active_provider = provider

    async def shutdown(self) -> None:
        try:
            if self._active_provider is not None:
                await self._active_provider.close()
        finally:
            if self._container is not None:
                self._container.unregister(KnowledgeProvider)
                self._container = None
            self._active_provider = None
