"""The Smart Support Desk, end to end: the boundary the whole path exists to teach.

The four assertions this file makes are the ones `site/hybrid-design.md` fixes under *the approval
boundary*, plus one full workflow run with no model service. The design page and this file are meant
to be read together: a rule stated there appears here as a test, so the path cannot drift into a
description of itself.
"""

from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient
from support_desk.app import create_app
from support_desk.jobs import DONE, FAILED
from support_desk.migrate import migrate
from support_desk.security import PrincipalVerifier

from xyberos.ai import FakeModelProvider, ModelProvider, ModelReply, Usage
from xyberos.database import SqliteSettings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

SECRET = "a-secret-the-deployment-keeps"
VERIFIER = PrincipalVerifier(SECRET)

ADA = VERIFIER.headers("ada@example.com", "acme", ["requester"])
GRACE = VERIFIER.headers("grace@example.com", "acme", ["requester"])
SAM = VERIFIER.headers("sam@desk", "acme", ["support_agent"])
LEE = VERIFIER.headers("lee@desk", "acme", ["support_lead"])
#: The same agent, in somebody else's tenant.
GLOBEX = VERIFIER.headers("sam@desk", "globex", ["support_agent"])

TICKET = {"subject": "Where is my refund?", "body": "Order 42 came back on Monday."}
EDITED = "A replacement badge shipped this morning."


def scripted() -> FakeModelProvider:
    """A classification and a draft per ticket, repeated so a second ticket needs no new script."""
    return FakeModelProvider(
        [
            ModelReply.json_payload(
                {"category": "refund", "confidence": "high"}, usage=Usage(1_240, 18)
            ),
            ModelReply.ok("A refund takes three business days to appear.", usage=Usage(1_410, 46)),
            ModelReply.json_payload(
                {"category": "complaint", "confidence": "high"}, usage=Usage(1_180, 18)
            ),
            ModelReply.ok("A replacement badge is on its way.", usage=Usage(1_360, 39)),
        ]
    )


def client_for(tmp_path: Path, provider: ModelProvider | None = None) -> TestClient:
    """Return a test client over a migrated database of its own."""
    settings = SqliteSettings(path=tmp_path / "support.db")
    migrate(settings)
    app = create_app(settings=settings, secret=SECRET, provider=provider or scripted())
    return create_test_client(HttpAdapter(app))


def draft_a_reply(client: TestClient, *, headers: dict[str, str] = SAM) -> None:
    """Open a ticket, classify it, and draft a reply, which is the state before any decision."""
    client.post("/tickets", json=TICKET, headers=ADA)
    client.post("/tickets/1/classify", headers=headers)
    client.post("/tickets/1/draft", headers=headers)


def test_a_draft_sends_nothing_until_somebody_approves_it(tmp_path: Path) -> None:
    client = client_for(tmp_path)

    with client:
        draft_a_reply(client)

        refused = client.post("/tickets/1/send", headers=SAM)
        sent = client.get("/tickets/1/sent", headers=SAM).json()

    assert refused.status_code == 409
    assert sent["count"] == 0
    assert sent["messages"] == []


def test_an_approval_from_a_principal_without_the_role_is_refused(tmp_path: Path) -> None:
    client = client_for(tmp_path)

    with client:
        draft_a_reply(client)

        refused = client.post("/tickets/1/approve", headers=GRACE)
        suggestion = client.get("/tickets/1/draft", headers=SAM).json()
        ticket = client.get("/tickets/1", headers=SAM).json()

    assert refused.status_code == 403
    assert suggestion["approved_by"] is None
    assert suggestion["approved_body"] is None
    assert ticket["state"] == "awaiting_approval"


def test_a_payload_that_claims_another_tenant_changes_nothing(tmp_path: Path) -> None:
    client = client_for(tmp_path)

    with client:
        client.post("/tickets", json={**TICKET, "tenant": "globex"}, headers=ADA)
        draft_a_reply(client)
        client.post("/tickets/1/approve", json={"body": EDITED}, headers=LEE)

        owner = client.get("/tickets/1", headers=SAM).json()
        suggestion = client.get("/tickets/1/draft", headers=LEE).json()
        stranger = client.get("/tickets/1", headers=GLOBEX)

    assert owner["tenant"] == "acme"
    assert suggestion["approved_body"] == EDITED
    assert stranger.status_code == 404


def test_the_audit_log_records_the_decision_the_principal_and_the_body(tmp_path: Path) -> None:
    client = client_for(tmp_path)

    with client:
        draft_a_reply(client)
        client.post("/tickets/1/approve", json={"body": EDITED}, headers=LEE)
        trail = client.get("/tickets/1/audit", headers=LEE).json()["events"]

    approved = [event for event in trail if event["action"] == "approved"]

    assert [event["action"] for event in trail][:3] == ["opened", "classified", "drafted"]
    assert len(approved) == 1
    assert approved[0]["actor"] == "lee@desk"
    assert approved[0]["detail"] == EDITED
    assert approved[0]["recorded_at"]


def test_one_full_triage_run_against_the_deterministic_provider(tmp_path: Path) -> None:
    client = client_for(tmp_path)

    with client:
        client.post("/tickets", json=TICKET, headers=ADA)
        accepted = client.post("/tickets/1/triage", headers=SAM)
        job_id = accepted.json()["job"]

        for _ in range(200):
            job = client.get(f"/jobs/{job_id}", headers=SAM).json()
            if job["state"] in {DONE, FAILED}:
                break

        ticket = client.get("/tickets/1", headers=SAM).json()
        suggestion = client.get("/tickets/1/draft", headers=SAM).json()
        sent = client.get("/tickets/1/sent", headers=SAM).json()
        usage = client.get("/usage", headers=LEE).json()

    assert accepted.status_code == 202
    assert job["state"] == DONE
    assert job["detail"] == "awaiting_approval"
    assert ticket["category"] == "refund"
    assert ticket["confidence"] == "high"
    assert suggestion["approved_by"] is None
    assert sent["count"] == 0
    assert [step["step"] for step in usage["steps"]] == ["classify", "draft"]
    assert usage["outcomes"] == {"pending": 2}
