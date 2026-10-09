from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import Executor
from typing import Any

from xyberos.kernel.container import DependencyContainer
from xyberos.kernel.contracts import Subsystem

from .contracts import FlowEngineContract, TraceObserver
from .engine import FlowEngine


class FlowSubsystem(Subsystem):
    """Kernel lifecycle adapter for a configured FlowEngine."""

    def __init__(
        self,
        process_executor: Executor | None = None,
        trace_observer: TraceObserver | None = None,
    ) -> None:
        self._process_executor = process_executor
        self._trace_observer = trace_observer
        self._container: DependencyContainer | None = None

    async def initialize(
        self,
        config: dict[str, Any],
        container: DependencyContainer,
    ) -> None:
        execution_config = config.get("execution", {})
        if not isinstance(execution_config, Mapping):
            raise ValueError("Flow subsystem 'execution' config must be a mapping.")
        max_concurrent_runs = execution_config.get("max_concurrent_runs", 100)
        engine = FlowEngine(
            self._process_executor,
            max_concurrent_runs=max_concurrent_runs,
            trace_observer=self._trace_observer,
        )
        container.register_utility(FlowEngineContract, engine)
        self._container = container

    async def shutdown(self) -> None:
        if self._container is not None:
            self._container.unregister(FlowEngineContract)
            self._container = None
