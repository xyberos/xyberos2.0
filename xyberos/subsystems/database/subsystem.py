from collections.abc import Mapping
from typing import Any

from xyberos.kernel.container import DependencyContainer
from xyberos.kernel.contracts import Subsystem

from .contracts import Database, DatabaseProvider


class DatabaseSubsystem(Subsystem):
    """Lifecycle adapter that exposes a configured database provider."""

    def __init__(self, provider: DatabaseProvider) -> None:
        self.provider = provider
        self._container: DependencyContainer | None = None

    async def initialize(
        self,
        config: dict[str, Any],
        container: DependencyContainer,
    ) -> None:
        provider_name = config.get("provider", self.provider.provider_name)
        if provider_name != self.provider.provider_name:
            raise ValueError(
                f"Configured database provider '{provider_name}' does not match "
                f"registered provider '{self.provider.provider_name}'."
            )
        provider_config = config.get("config", {})
        if not isinstance(provider_config, Mapping):
            raise ValueError("Database provider config must be a mapping.")
        await self.provider.initialize(provider_config)
        container.register_utility(Database, self.provider)
        self._container = container

    async def shutdown(self) -> None:
        try:
            await self.provider.close()
        finally:
            if self._container is not None:
                self._container.unregister(Database)
                self._container = None
