"""Walkthrough — logging: the application owns the configuration, the framework owns the names.

Run it with:

    python -m learn_production.observability01_logging
"""

from __future__ import annotations

import logging
from io import StringIO

from xyberos import App
from xyberos.errors import HttpError
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client
from xyberos.runtime.context import ContextLogFilter

#: The header the adapter echoes, and the ID this walkthrough sends so the transcript is stable.
REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID = "req-1"

#: What the application's own reference to a log record looks like: its namespace, then its view.
FORMAT = "%(levelname)s %(name)s %(message)s %(xyberos_context)s"


class OrderGone(HttpError):
    """A client mistake the application reports about, which the adapter logs on its way out."""

    def __init__(self, order_id: int) -> None:
        super().__init__(f"order {order_id} is gone", status_code=410)


def build_app() -> App:
    """Compose a two-route application: one that logs, and one that fails in a reportable way."""
    app = App()
    app.get("/orders/{order_id}")(read_order)
    app.get("/orders/{order_id}/cancel")(cancel_order)
    return app


async def read_order(order_id: int) -> dict[str, object]:
    """Log at the application's own logger, which is the only place a business event belongs."""
    logging.getLogger("orders.api").info("looked up order %s", order_id)
    return {"order": order_id}


async def cancel_order(order_id: int) -> dict[str, object]:
    """Fail in a way the adapter maps to a response, and logs on the way out."""
    raise OrderGone(order_id)


def main() -> None:
    """Serve the application with its own logging configuration, and read the records."""
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(FORMAT))
    # The filter is what puts the current context on every record: without it a log line cannot say
    # which request it belongs to, and with it the correlation ID arrives from the adapter.
    handler.addFilter(ContextLogFilter())

    framework = logging.getLogger("xyberos")
    print("handlers the framework configured:", framework.handlers)

    # Configure the root logger, not `xyberos`: that catches the application's own lines
    # (`orders.api`) as well as the framework's (`xyberos.http`).
    root = logging.getLogger()
    previous_level = root.level
    # The test client is not part of a deployment, and its request lines are not the application's.
    noisy = logging.getLogger("httpx")
    noisy_level = noisy.level
    noisy.setLevel(logging.WARNING)
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        app = build_app()
        with create_test_client(HttpAdapter(app)) as client:
            path = "/orders/7"
            print(
                "GET", path, "->", client.get(path, headers={REQUEST_ID_HEADER: REQUEST_ID}).json()
            )
            gone = client.get("/orders/9/cancel", headers={REQUEST_ID_HEADER: REQUEST_ID})
            print("GET /orders/9/cancel ->", gone.status_code, gone.json())
            print("echoed header:", gone.headers[REQUEST_ID_HEADER])
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)
        noisy.setLevel(noisy_level)

    print("--- records the application's handler saw ---")
    for line in stream.getvalue().splitlines():
        print(line)


if __name__ == "__main__":
    main()
