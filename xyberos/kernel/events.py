from __future__ import annotations

import inspect
from collections import defaultdict
from typing import Any, DefaultDict

from .contracts import EventBus as EventBusContract
from .contracts import EventHandler


class InProcessEventBus(EventBusContract):
    """Simple in-process event bus that awaits async handlers sequentially."""

    def __init__(self) -> None:
        self._handlers: DefaultDict[type[Any], list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: type[Any], handler: EventHandler) -> None:
        if handler in self._handlers[event_type]:
            raise ValueError(f"Handler is already subscribed to '{event_type.__name__}'.")
        self._handlers[event_type].append(handler)

    async def publish(self, event: Any) -> None:
        for event_type, handlers in tuple(self._handlers.items()):
            if isinstance(event, event_type):
                for handler in tuple(handlers):
                    result = handler(event)
                    if inspect.isawaitable(result):
                        await result
