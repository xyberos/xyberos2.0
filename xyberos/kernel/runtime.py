from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .config import KernelConfig
from .capability_executor import CapabilityExecutor
from .container import DependencyContainer
from .contracts import Capability, Provider, Subsystem
from .errors import (
    KernelNotReadyError,
    ShutdownDrainTimeoutError,
    SubsystemShutdownError,
)
from .events import InProcessEventBus
from .lifecycle import LifecycleState
from .observability import KernelEvent, KernelHealth, KernelObserver
from .registry import CapabilityRegistry, ProviderRegistry, SubsystemRegistry

logger = logging.getLogger("xyberos.kernel")


class XyberosKernel:
    """Central orchestrator for lifecycle, registry, and subsystem startup."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        *,
        observer: KernelObserver | None = None,
        shutdown_drain_timeout: float | None = None,
    ) -> None:
        if shutdown_drain_timeout is not None:
            _validate_timeout(shutdown_drain_timeout)
        self.container = DependencyContainer()
        self._subsystems = SubsystemRegistry()
        self._providers = ProviderRegistry()
        self.capabilities = CapabilityRegistry()
        self._capability_executor = CapabilityExecutor(
            self.capabilities,
            self.container,
        )
        self.events = InProcessEventBus()
        self._initialized_subsystems: list[str] = []
        self._state = LifecycleState.NEW
        self._lifecycle_lock = asyncio.Lock()
        self._work_condition = asyncio.Condition()
        self._active_work = 0
        self._observer = observer
        self._observer_failure_count = 0
        self._config = KernelConfig.from_dict(config if config is not None else {})
        configured_timeout = self._config.shutdown_drain_timeout_seconds
        self._shutdown_drain_timeout = (
            shutdown_drain_timeout
            if shutdown_drain_timeout is not None
            else configured_timeout if configured_timeout is not None else 30.0
        )
        self._shutdown_drain_timeout_override = shutdown_drain_timeout

    def register_subsystem(self, name: str, subsystem: Subsystem) -> None:
        if self._state is not LifecycleState.NEW:
            raise RuntimeError("Subsystems can only be registered before kernel startup.")
        self._subsystems.register(name, subsystem)

    def register_provider(self, subsystem_name: str, provider: Provider) -> None:
        if self._state is not LifecycleState.NEW:
            raise RuntimeError("Providers can only be registered before kernel startup.")
        self._providers.register(subsystem_name, provider)

    def register_capability(
        self,
        capability: Capability,
        handler: Callable[..., Any] | None = None,
    ) -> None:
        if self._state is not LifecycleState.NEW:
            raise RuntimeError("Capabilities can only be registered before kernel startup.")
        if handler is not None and not callable(handler):
            raise TypeError("Capability handler must be callable.")
        self.capabilities.register(capability)
        if handler is not None:
            self._capability_executor.register_handler(capability, handler)

    def register_capability_handler(
        self,
        capability_name: str,
        handler: Callable[..., Any],
    ) -> None:
        if self._state is not LifecycleState.NEW:
            raise RuntimeError(
                "Capability handlers can only be registered before kernel startup."
            )
        capability = self.capabilities.get(capability_name)
        self._capability_executor.register_handler(capability, handler)

    async def execute_capability(
        self,
        capability_name: str,
        *args: Any,
        resource: Any = None,
        **kwargs: Any,
    ) -> Any:
        async with self.work():
            return await self._capability_executor.execute(
                capability_name,
                *args,
                resource=resource,
                **kwargs,
            )

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
            configured_timeout = runtime_config.shutdown_drain_timeout_seconds
            self._shutdown_drain_timeout = (
                self._shutdown_drain_timeout_override
                if self._shutdown_drain_timeout_override is not None
                else configured_timeout if configured_timeout is not None else 30.0
            )
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
                    started_at = time.perf_counter()
                    subsystem_runtime_config = {
                        key: value for key, value in sub_config.items()
                        if key != "enabled"
                    }
                    try:
                        await self._subsystems.get(name).initialize(
                            subsystem_runtime_config,
                            self.container,
                        )
                    except BaseException as exc:
                        self._observe(
                            KernelEvent(
                                "subsystem.initialize",
                                name,
                                "failed",
                                datetime.now(timezone.utc),
                                time.perf_counter() - started_at,
                                type(exc).__name__,
                            )
                        )
                        raise
                    self._initialized_subsystems.append(name)
                    self._observe(
                        KernelEvent(
                            "subsystem.initialize",
                            name,
                            "succeeded",
                            datetime.now(timezone.utc),
                            time.perf_counter() - started_at,
                        )
                    )
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
            if self._state not in {LifecycleState.RUNNING, LifecycleState.STOPPING}:
                raise RuntimeError(
                    f"Cannot shut down kernel while it is {self._state.value}."
                )

            if self._state is LifecycleState.RUNNING:
                async with self._work_condition:
                    self._state = LifecycleState.STOPPING
                    self._work_condition.notify_all()
            await self._drain_active_work()
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

    @property
    def health(self) -> KernelHealth:
        return KernelHealth(
            live=self._state not in {LifecycleState.FAILED, LifecycleState.STOPPED},
            ready=self._state is LifecycleState.RUNNING,
            state=self._state,
            active_work=self._active_work,
        )

    @property
    def observer_failure_count(self) -> int:
        return self._observer_failure_count

    @asynccontextmanager
    async def work(self):
        """Track admitted work so shutdown can stop admission and drain safely."""
        async with self._work_condition:
            if self._state is not LifecycleState.RUNNING:
                raise KernelNotReadyError(
                    f"Kernel is not accepting work while it is {self._state.value}."
                )
            self._active_work += 1
        try:
            yield
        finally:
            async with self._work_condition:
                self._active_work -= 1
                if self._active_work == 0:
                    self._work_condition.notify_all()

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
            started_at = time.perf_counter()
            try:
                await self._subsystems.get(name).shutdown()
                logger.info("Subsystem cleanly halted: [%s]", name)
                self._observe(
                    KernelEvent(
                        "subsystem.shutdown",
                        name,
                        "succeeded",
                        datetime.now(timezone.utc),
                        time.perf_counter() - started_at,
                    )
                )
            except Exception as exc:
                logger.exception("Error handling teardown logic on [%s]", name)
                failures.append((name, exc))
                self._observe(
                    KernelEvent(
                        "subsystem.shutdown",
                        name,
                        "failed",
                        datetime.now(timezone.utc),
                        time.perf_counter() - started_at,
                        type(exc).__name__,
                    )
                )
        return failures

    async def _drain_active_work(self) -> None:
        async with self._work_condition:
            if self._active_work == 0:
                return
            try:
                await asyncio.wait_for(
                    self._work_condition.wait_for(
                        lambda: self._active_work == 0
                    ),
                    timeout=self._shutdown_drain_timeout,
                )
            except asyncio.TimeoutError as exc:
                raise ShutdownDrainTimeoutError(
                    self._active_work,
                    self._shutdown_drain_timeout,
                ) from exc

    def _observe(self, event: KernelEvent) -> None:
        if self._observer is None:
            return
        try:
            self._observer(event)
        except Exception as exc:
            self._observer_failure_count += 1
            logger.error(
                "Kernel observer failed while handling event '%s' for '%s' (%s).",
                event.name,
                event.component,
                type(exc).__name__,
            )


def _validate_timeout(timeout_seconds: float) -> None:
    if (
        not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or timeout_seconds <= 0
    ):
        raise ValueError("shutdown_drain_timeout must be a positive finite number.")
    try:
        finite = math.isfinite(float(timeout_seconds))
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError("shutdown_drain_timeout must be a positive finite number.")
