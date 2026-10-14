"""The sessions recipe holds: a signed-in session, and a state-changing request that has to pass.

The three claims worth testing are the ones the ADR makes: a foreign site cannot post, the session
cookie is not the data a handler stored, and a signed-out request is refused before the body is
read.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sessions.app import create_application

from xyberos.http import CSRF_HEADER
from xyberos.http.testing import create_test_client

SECRET = "test-secret"


@contextmanager
def signed_in() -> Iterator[tuple[Any, str]]:
    """Yield a client holding a session cookie, and the token a page would carry."""
    with create_test_client(create_application(secret=SECRET)) as client:
        assert (
            client.post("/login", json={"user": "ada", "password": "correct-horse"}).status_code
            == 200
        )
        token = client.get("/order-form").json()["csrf_token"]
        yield client, token


def test_a_signed_in_session_is_read_back_by_the_next_request() -> None:
    with signed_in() as (client, _):
        assert client.get("/me").json() == {"user": "ada"}


def test_the_session_cookie_is_an_id_and_not_the_stored_value() -> None:
    with signed_in() as (client, _):
        assert "ada" not in client.cookies.get("xyberos_session", "")


def test_a_same_origin_order_is_accepted() -> None:
    with signed_in() as (client, token):
        response = client.post(
            "/orders",
            json={"item": "printer paper"},
            headers={"Origin": "http://testserver", CSRF_HEADER: token},
        )

        assert response.status_code == 200
        assert response.json() == {"ordered_by": "ada", "item": "printer paper"}


def test_a_cross_site_order_is_refused_with_a_client_safe_body() -> None:
    with signed_in() as (client, token):
        response = client.post(
            "/orders",
            json={"item": "a new sofa"},
            headers={"Origin": "https://evil.example", CSRF_HEADER: token},
        )

        assert response.status_code == 403
        assert response.json()["error"]["type"] == "CSRFError"


def test_a_stale_token_is_refused() -> None:
    with signed_in() as (client, token):
        response = client.post(
            "/orders",
            json={"item": "a new sofa"},
            headers={"Origin": "http://testserver", CSRF_HEADER: token + "x"},
        )

        assert response.status_code == 403


def test_a_bad_password_never_starts_a_session() -> None:
    with create_test_client(create_application(secret=SECRET)) as client:
        response = client.post("/login", json={"user": "ada", "password": "wrong"})

        assert response.status_code == 401
        assert client.get("/me").json() == {"user": None}


def test_signing_out_ends_the_session() -> None:
    with signed_in() as (client, _):
        assert client.post("/logout").status_code == 200
        assert client.get("/me").json() == {"user": None}


def test_a_signed_out_order_is_refused_with_401() -> None:
    with create_test_client(create_application(secret=SECRET)) as client:
        response = client.post("/orders", json={"item": "x"})

        assert response.status_code == 401
        assert response.json()["error"]["type"] == "UnauthenticatedError"
