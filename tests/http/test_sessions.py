"""Sessions: a signed id in the cookie, the data in the store, and no write without a change.

The three properties worth testing are the ones the module exists for: the cookie carries an opaque
id rather than the values a handler stored, a request that only reads a session writes nothing, and
a cookie this application did not sign is not a session.
"""

from __future__ import annotations

import asyncio

import pytest
from starlette.middleware import Middleware
from starlette.requests import Request

from xyberos import App
from xyberos.errors import ConfigurationError
from xyberos.http import (
    SESSION_COOKIE,
    HttpAdapter,
    InMemorySessionStore,
    Session,
    SessionMiddleware,
    get_session,
)
from xyberos.http.testing import create_test_client

SECRET = "session-secret"


class CountingStore(InMemorySessionStore):
    """An in-memory store that records how many writes and deletes it was asked to make."""

    def __init__(self, *, max_sessions: int = 10_000) -> None:
        super().__init__(max_sessions=max_sessions)
        self.writes = 0
        self.deletes = 0

    async def save(self, session_id: str, data: dict[str, object], *, max_age: int) -> None:
        self.writes += 1
        await super().save(session_id, data, max_age=max_age)

    async def delete(self, session_id: str) -> None:
        self.deletes += 1
        await super().delete(session_id)


def build_app() -> App:
    app = App()

    @app.post("/remember")
    async def remember(request: Request) -> dict[str, str]:
        get_session(request)["user"] = "ada"
        return {"stored": "ada"}

    @app.get("/whoami")
    async def whoami(request: Request) -> dict[str, str | None]:
        return {"user": request.session.get("user")}

    @app.post("/forget")
    async def forget(request: Request) -> dict[str, bool]:
        get_session(request).clear()
        return {"cleared": True}

    return app


def client_for(store: InMemorySessionStore, *, secret: str = SECRET):
    middleware = (Middleware(SessionMiddleware, store=store, secret=secret),)
    return create_test_client(HttpAdapter(build_app(), middleware=middleware))


def test_a_stored_session_is_read_back_by_the_next_request() -> None:
    store = InMemorySessionStore()

    with client_for(store) as client:
        assert client.post("/remember").status_code == 200
        assert client.get("/whoami").json() == {"user": "ada"}

    assert len(store) == 1


def test_the_cookie_is_an_id_and_not_the_values_that_were_stored() -> None:
    """The difference from a signed-payload cookie: a handler's values never reach the client."""
    store = InMemorySessionStore()

    with client_for(store) as client:
        response = client.post("/remember")

    cookie = response.cookies[SESSION_COOKIE]
    assert "ada" not in cookie
    session_id, _, signature = cookie.rpartition(".")
    assert session_id and signature, "the cookie is an id and a signature, not the data"


def test_a_request_that_only_reads_writes_nothing_and_sets_no_cookie() -> None:
    """The property that keeps a read-only page from costing a write and a new cookie."""
    store = CountingStore()

    with client_for(store) as client:
        client.post("/remember")
        writes_after_login = store.writes

        assert client.get("/whoami").status_code == 200
        assert client.get("/whoami").status_code == 200

    assert store.writes == writes_after_login, "reading a session is not a reason to write it"


def test_an_anonymous_request_sets_no_cookie_at_all() -> None:
    store = InMemorySessionStore()

    with client_for(store) as client:
        response = client.get("/whoami")

    assert response.json() == {"user": None}
    assert SESSION_COOKIE not in response.cookies
    assert len(store) == 0


def test_clearing_a_session_deletes_it_and_the_next_request_starts_from_nothing() -> None:
    store = CountingStore()

    with client_for(store) as client:
        client.post("/remember")
        assert client.post("/forget").status_code == 200

        assert store.deletes == 1
        assert client.get("/whoami").json() == {"user": None}


def test_a_cookie_this_application_did_not_sign_is_not_a_session() -> None:
    store = InMemorySessionStore()

    with client_for(store) as client:
        client.cookies.set(SESSION_COOKIE, "made-up-id.made-up-signature")
        assert client.get("/whoami").json() == {"user": None}


def test_a_cookie_signed_with_another_secret_is_not_a_session() -> None:
    store = InMemorySessionStore()

    with client_for(store) as client:
        signed = client.post("/remember").cookies[SESSION_COOKIE]

    other = InMemorySessionStore()
    with client_for(other, secret="a-different-secret") as client:
        client.cookies.set(SESSION_COOKIE, signed)
        assert client.get("/whoami").json() == {"user": None}


def test_get_session_without_the_middleware_names_the_fix() -> None:
    """A composition mistake names what to add, rather than an ``AssertionError`` from Starlette."""
    from types import SimpleNamespace

    with pytest.raises(ConfigurationError, match="SessionMiddleware"):
        get_session(SimpleNamespace(scope={}))  # type: ignore[arg-type]


def test_an_empty_session_secret_is_refused_at_composition_time() -> None:
    with pytest.raises(ConfigurationError, match="secret"):
        SessionMiddleware(_never_called, store=InMemorySessionStore(), secret="")


def test_a_nonsense_max_age_is_refused_at_composition_time() -> None:
    with pytest.raises(ConfigurationError, match="max_age"):
        SessionMiddleware(_never_called, store=InMemorySessionStore(), secret=SECRET, max_age=0)


def test_a_nonsense_store_ceiling_is_refused_at_composition_time() -> None:
    with pytest.raises(ConfigurationError, match="max_sessions"):
        InMemorySessionStore(max_sessions=0)


def test_the_store_forgets_a_session_once_it_has_expired() -> None:
    now = [0.0]
    store = InMemorySessionStore(clock=lambda: now[0])

    async def exercise() -> None:
        await store.save("abc", {"user": "ada"}, max_age=10)
        assert await store.load("abc") == {"user": "ada"}
        now[0] = 11.0
        assert await store.load("abc") is None

    asyncio.run(exercise())


def test_a_store_ceiling_drops_the_oldest_session() -> None:
    store = InMemorySessionStore(max_sessions=1)

    async def exercise() -> None:
        await store.save("first", {"n": 1}, max_age=100)
        await store.save("second", {"n": 2}, max_age=100)
        assert await store.load("first") is None
        assert await store.load("second") == {"n": 2}

    asyncio.run(exercise())


def test_a_session_is_a_mapping_a_handler_can_use_like_a_dictionary() -> None:
    session = Session()
    session["user"] = "ada"
    session.update({"role": "admin"})
    session.setdefault("seen", 0)

    assert session.modified is True
    assert sorted(session) == ["role", "seen", "user"]
    assert dict(session)["role"] == "admin"
    assert session.pop("role") == "admin"


def test_a_session_loaded_from_a_store_is_not_modified_until_a_handler_writes() -> None:
    session = Session({"user": "ada"})
    assert session.modified is False
    assert session.is_new is False
    del session["user"]
    assert session.modified is True


async def _never_called(scope: object, receive: object, send: object) -> None:  # pragma: no cover
    raise AssertionError("middleware must not be called by this test")
