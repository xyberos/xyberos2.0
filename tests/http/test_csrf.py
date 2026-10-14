"""CSRF: the origin check refuses a foreign site, the token check refuses a forged one.

A request with neither an ``Origin`` nor a ``Referer`` is not a browser cross-site request, so the
tests that matter are the ones where one of those headers says the request came from somewhere else.
"""

from __future__ import annotations

import pytest
from starlette.middleware import Middleware
from starlette.requests import Request

from xyberos import App
from xyberos.errors import ConfigurationError
from xyberos.http import (
    CSRF_COOKIE,
    CSRF_HEADER,
    CSRFMiddleware,
    HttpAdapter,
    get_csrf_token,
)
from xyberos.http.testing import create_test_client


def build_app() -> App:
    app = App()

    @app.get("/token")
    async def token(request: Request) -> dict[str, str]:
        return {"token": get_csrf_token(request)}

    @app.post("/transfer")
    async def transfer() -> dict[str, bool]:
        return {"transferred": True}

    return app


def client_for(**options: object):
    middleware = (Middleware(CSRFMiddleware, **options),)
    return create_test_client(HttpAdapter(build_app(), middleware=middleware))


def test_a_safe_request_issues_a_token_and_the_handler_can_read_it() -> None:
    with client_for() as client:
        response = client.get("/token")

        assert response.status_code == 200
        assert response.json()["token"] == response.cookies[CSRF_COOKIE]


def test_a_state_changing_request_without_an_origin_is_allowed() -> None:
    """A command-line client is not a browser and cannot be the victim of a cross-site request."""
    with client_for() as client:
        assert client.post("/transfer").status_code == 200


def test_a_cross_origin_state_changing_request_is_refused() -> None:
    with client_for() as client:
        response = client.post("/transfer", headers={"Origin": "https://evil.example"})

        assert response.status_code == 403
        assert response.json()["error"]["type"] == "CSRFError"


def test_a_same_origin_state_changing_request_is_allowed() -> None:
    with client_for() as client:
        assert client.post("/transfer", headers={"Origin": "http://testserver"}).status_code == 200


def test_a_referer_is_used_when_the_origin_header_is_absent() -> None:
    with client_for() as client:
        response = client.post("/transfer", headers={"Referer": "https://evil.example/package"})
        assert response.status_code == 403

        allowed = client.post("/transfer", headers={"Referer": "http://testserver/package"})
        assert allowed.status_code == 200


def test_a_presented_token_that_does_not_match_is_refused() -> None:
    with client_for() as client:
        response = client.post("/transfer", headers={CSRF_HEADER: "not-the-issued-token"})
        assert response.status_code == 403


def test_a_presented_token_that_matches_is_allowed() -> None:
    with client_for() as client:
        issued = client.get("/token").json()["token"]
        assert client.post("/transfer", headers={CSRF_HEADER: issued}).status_code == 200


def test_requiring_a_token_refuses_a_request_that_presents_none() -> None:
    with client_for(require_token=True) as client:
        response = client.post("/transfer")
        assert response.status_code == 403

        issued = client.get("/token").json()["token"]
        assert client.post("/transfer", headers={CSRF_HEADER: issued}).status_code == 200


def test_a_trusted_origin_is_allowed_when_the_application_says_so() -> None:
    with client_for(trusted_origins=("https://app.example",)) as client:
        allowed = client.post("/transfer", headers={"Origin": "https://app.example"})
        refused = client.post("/transfer", headers={"Origin": "https://evil.example"})

        assert allowed.status_code == 200
        assert refused.status_code == 403


def test_a_safe_request_is_never_refused_however_it_arrives() -> None:
    with client_for(require_token=True) as client:
        assert client.get("/token", headers={"Origin": "https://evil.example"}).status_code == 200


def test_get_csrf_token_without_the_middleware_names_the_fix() -> None:
    """A composition mistake is told what to add rather than handing a form an empty token."""
    from types import SimpleNamespace

    with pytest.raises(ConfigurationError, match="CSRFMiddleware"):
        get_csrf_token(SimpleNamespace(scope={}))  # type: ignore[arg-type]


def test_a_nonsense_max_age_is_refused_at_composition_time() -> None:
    with pytest.raises(ConfigurationError, match="max_age"):
        CSRFMiddleware(_never_called, max_age=0)


async def _never_called(scope: object, receive: object, send: object) -> None:
    raise AssertionError("a middleware built only to fail composition is never awaited")
