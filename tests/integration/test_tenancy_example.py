"""The tenancy recipe holds: a verified principal scopes every read, not the payload."""

from __future__ import annotations

from tenancy.app import (
    PrincipalVerifier,
    TicketStore,
    create_app,
    signed_headers,
)

from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

SECRET = "example-secret"


def verifier() -> PrincipalVerifier:
    return PrincipalVerifier(SECRET)


def test_a_verified_principal_sees_only_its_own_tenants_rows() -> None:
    app = create_app(secret=SECRET)
    signer = verifier()
    acme = signed_headers(signer, "acme", "ada")
    globex = signed_headers(signer, "globex", "linus")

    with create_test_client(HttpAdapter(app)) as client:
        client.post("/tickets", json={"title": "printer is on fire"}, headers=acme)
        client.post("/tickets", json={"title": "badge reader is broken"}, headers=globex)

        assert client.get("/tickets", headers=acme).json() == {
            "tenant": "acme",
            "tickets": ["printer is on fire"],
        }
        assert client.get("/tickets", headers=globex).json() == {
            "tenant": "globex",
            "tickets": ["badge reader is broken"],
        }


def test_a_payload_claiming_another_tenant_changes_nothing() -> None:
    """The claim that matters: the tenant comes from the verified assertion, never from the body."""
    app = create_app(secret=SECRET)
    signer = verifier()
    acme = signed_headers(signer, "acme", "ada")
    globex = signed_headers(signer, "globex", "linus")

    with create_test_client(HttpAdapter(app)) as client:
        client.post(
            "/tickets",
            json={"title": "pretending to be acme", "tenant": "acme"},
            headers=globex,
        )

        assert client.get("/tickets", headers=acme).json()["tickets"] == []
        assert client.get("/tickets", headers=globex).json()["tickets"] == ["pretending to be acme"]


def test_an_unsigned_assertion_is_refused_with_a_client_safe_body() -> None:
    app = create_app(secret=SECRET)

    with create_test_client(HttpAdapter(app)) as client:
        response = client.get("/tickets", headers={"X-Tenant": "acme", "X-Subject": "ada"})

        assert response.status_code == 401
        assert response.json()["error"]["type"] == "UnauthenticatedError"
        assert "signature" in response.json()["error"]["message"]


def test_a_signature_from_another_secret_is_refused() -> None:
    app = create_app(secret=SECRET)
    headers = signed_headers(PrincipalVerifier("a-different-secret"), "acme", "ada")

    with create_test_client(HttpAdapter(app)) as client:
        assert client.get("/tickets", headers=headers).status_code == 401


def test_a_missing_subject_is_refused_before_any_lookup() -> None:
    app = create_app(secret=SECRET)
    signer = verifier()
    headers = signed_headers(signer, "acme", "ada")
    del headers["X-Subject"]

    with create_test_client(HttpAdapter(app)) as client:
        response = client.get("/tickets", headers=headers)

        assert response.status_code == 401
        assert "X-Subject" in response.json()["error"]["message"]


def test_the_store_cannot_be_asked_for_rows_without_naming_a_tenant() -> None:
    """The service signature is part of the safety: there is no tenant-free read to forget."""
    store = TicketStore()
    store.add("acme", "one")

    assert store.titles("acme") == ["one"]
    assert store.titles("globex") == []
    assert "titles" in TicketStore.__dict__
    assert list(TicketStore.titles.__annotations__) == ["tenant", "return"]
