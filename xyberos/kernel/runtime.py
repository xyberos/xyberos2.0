from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from .config import KernelConfig
from .container import DependencyContainer
from .contracts import Capability, Provider, Subsystem
from .errors import SubsystemShutdownError
from .events import InProcessEventBus
from .lifecycle import LifecycleState
from .registry import CapabilityRegistry, ProviderRegistry, SubsystemRegistry

logger = logging.getLogger("xyberos.kernel")


class XyberosKernel:
    """Central orchestrator for lifecycle, registry, and subsystem startup."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.container = DependencyContainer()
        self._subsystems = SubsystemRegistry()
        self._providers = ProviderRegistry()
        self.capabilities = CapabilityRegistry()
        self.events = InProcessEventBus()
        self._initialized_subsystems: list[str] = []
        self._state = LifecycleState.NEW
        self._lifecycle_lock = asyncio.Lock()
        self._config = KernelConfig.from_dict(config if config is not None else {})

    def register_subsystem(self, name: str, subsystem: Subsystem) -> None:
        if self._state is not LifecycleState.NEW:
            raise RuntimeError("Subsystems can only be registered before kernel startup.")
        self._subsystems.register(name, subsystem)

    def register_provider(self, subsystem_name: str, provider: Provider) -> None:
        if self._state is not LifecycleState.NEW:
            raise RuntimeError("Providers can only be registered before kernel startup.")
        self._providers.register(subsystem_name, provider)

    def register_capability(self, capability: Capability) -> None:
        if self._state is not LifecycleState.NEW:
            raise RuntimeError("Capabilities can only be registered before kernel startup.")
        self.capabilities.register(capability)

    async def bootstrap(self, config: Optional[Dict[str, Any]] = None) -> None:
        async with self._lifecycle_lock:
            if self._state is LifecycleState.RUNNING:
                return
            if self._state is not LifecycleState.NEW:
                raise RuntimeError(
                    f"Cannot bootstrap kernel while it is {self._state.value}."
                )

            runtime_config = KernelConfig.from_dict(
                config if config is not None else self._config.raw
            )
            subsystem_configs = runtime_config.subsystems
            self._config = runtime_config
            self._state = LifecycleState.STARTING

            logger.info("Bootstrapping Xyberos 2.0 kernel runtime...")
            try:
                for name, sub_config in subsystem_configs.items():
                    if not sub_config.get("enabled", False):
                        continue
                    if name not in self._subsystems:
                        raise ValueError(
                            f"Subsystem runtime config targets missing module: {name}"
                        )

                    logger.info("Initializing configured subsystem: [%s]", name)
                    await self._subsystems.get(name).initialize(
                        sub_config,
                        self.container,
                    )
                    self._initialized_subsystems.append(name)
            except BaseException:
                await self._rollback_startup()
                self._state = LifecycleState.FAILED
                raise

            self._state = LifecycleState.RUNNING

    async def shutdown(self) -> None:
        async with self._lifecycle_lock:
            if self._state is LifecycleState.STOPPED:
                return
            if self._state in {LifecycleState.NEW, LifecycleState.FAILED}:
                self._state = LifecycleState.STOPPED
                return
            if self._state is not LifecycleState.RUNNING:
                raise RuntimeError(
                    f"Cannot shut down kernel while it is {self._state.value}."
                )

            self._state = LifecycleState.STOPPING
            failures = await self._shutdown_initialized()
            self._state = LifecycleState.STOPPED
            if failures:
                raise SubsystemShutdownError(failures)

    @property
    def is_initialized(self) -> bool:
        return self._state is LifecycleState.RUNNING

    @property
    def state(self) -> LifecycleState:
        return self._state

    def get_provider(self, subsystem_name: str, provider_name: str) -> Provider:
        return self._providers.get(subsystem_name, provider_name)

    async def _rollback_startup(self) -> None:
        failures = await self._shutdown_initialized()
        for name, exc in failures:
            logger.error(
                "Failed to shut down subsystem [%s] after startup failure: %s",
                name,
                exc,
                exc_info=exc,
            )

    async def _shutdown_initialized(self) -> list[tuple[str, Exception]]:
        failures: list[tuple[str, Exception]] = []
        names = list(reversed(self._initialized_subsystems))
        self._initialized_subsystems.clear()
        for name in names:
            try:
                await self._subsystems.get(name).shutdown()
                logger.info("Subsystem cleanly halted: [%s]", name)
            except Exception as exc:
                logger.exception("Error handling teardown logic on [%s]", name)
                failures.append((name, exc))
        return failures
