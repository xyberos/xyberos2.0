"""The security page's claims, held where a transcript cannot hold them.

Three of the page's boundaries are properties of the package rather than of one run: importing the
core pulls in no adapter, a configuration failure never echoes the value it refused, and an error
that is not an ``HttpError`` is replaced in the response while its message goes to the log.
"""

import logging
import subprocess
import sys
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse

from xyberos import App, Settings
from xyberos.errors import ConfigurationError, HttpError
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

#: The packages an adapter brings in, and therefore the ones the core must not import on its own.
ADAPTER_PACKAGES = ("sqlalchemy", "aiosqlite", "alembic", "starlette", "httpx")

#: A value that must never appear in a message about the setting that carries it.
SECRET = "sk-live-0123456789"

MISSING_PACKAGE = "this module is not installed"


class LeakingError(Exception):
    """An error carrying something a client must not see."""

    def __init__(self) -> None:
        super().__init__(f"upstream refused the token {SECRET}")


class NotAllowed(HttpError):
    """An error the application has decided is safe to expose."""

    def __init__(self) -> None:
        super().__init__("you may not read that order", status_code=403)


class Records(logging.Handler):
    """An in-memory handler, so a record can be inspected without a sink."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_importing_the_core_imports_no_adapter() -> None:
    script = (
        "import sys\n"
        "import xyberos\n"
        f"names = {ADAPTER_PACKAGES!r}\n"
        "print(','.join(sorted(name for name in names if name in sys.modules)))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert completed.stdout.strip() == ""


def test_a_configuration_failure_names_the_setting_and_never_the_value() -> None:
    with pytest.raises(ConfigurationError) as raised:
        Settings.load(environ={"XYBEROS_APP__SIGNING_KEY": SECRET})

    message = str(raised.value)
    assert "signing_key" in message
    assert SECRET not in message

    with pytest.raises(ConfigurationError) as wrong_type:
        Settings.load(environ={"XYBEROS_APP__DEBUG": SECRET})
    assert SECRET not in str(wrong_type.value)


def test_an_internal_error_is_replaced_in_the_body_and_kept_in_the_log() -> None:
    async def leaky() -> JSONResponse:
        raise LeakingError

    app = App()
    app.get("/leak")(leaky)

    handler = Records()
    logger = logging.getLogger("xyberos.http")
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.INFO)
    try:
        with create_test_client(HttpAdapter(app)) as client:
            response = client.get("/leak")
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)

    assert response.status_code == 500
    assert response.json() == {
        "error": {"type": "InternalServerError", "message": "the request could not be completed"}
    }
    assert SECRET not in response.text
    logged = [record for record in handler.records if record.exc_info]
    assert [str(record.exc_info[1]) for record in logged if record.exc_info] == [
        f"upstream refused the token {SECRET}"
    ]


def test_an_http_error_message_is_the_one_that_reaches_the_client() -> None:
    async def refused() -> JSONResponse:
        raise NotAllowed

    app = App()
    app.get("/refused")(refused)

    with create_test_client(HttpAdapter(app)) as client:
        response = client.get("/refused")

    assert response.status_code == 403
    assert response.json() == {
        "error": {"type": "NotAllowed", "message": "you may not read that order"}
    }


def test_the_endpoint_is_a_starlette_application_so_middleware_is_yours_to_add() -> None:
    app = App()
    assert isinstance(HttpAdapter(app).asgi_app, Starlette)
