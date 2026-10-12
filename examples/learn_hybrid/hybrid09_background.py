"""Lesson 9 — background processing: the request returns a job, and the work outlives it.

Run it with:

    python -m learn_hybrid.hybrid09_background
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from support_desk.app import create_app
from support_desk.jobs import DONE, FAILED
from support_desk.migrate import migrate
from support_desk.security import PrincipalVerifier

from xyberos.ai import FakeModelProvider, ModelReply
from xyberos.database import SqliteSettings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

SECRET = "a-secret-the-deployment-keeps"
VERIFIER = PrincipalVerifier(SECRET)
ADA = VERIFIER.headers("ada@example.com", "acme", ["requester"])
SAM = VERIFIER.headers("sam@desk", "acme", ["support_agent"])
LEE = VERIFIER.headers("lee@desk", "acme", ["support_lead"])

#: A slow provider on purpose: the reason this lesson exists is that a model call takes seconds.
SLOW = 0.4

#: How long a client waits for the job, and how often it asks. The budget is a deadline rather than
#: a number of attempts: the work takes real time, so counting polls counts the wrong thing.
POLL_BUDGET = 15.0
POLL_INTERVAL = 0.01


def provider() -> FakeModelProvider:
    """A classification that takes ``SLOW`` seconds, then an instant draft."""
    return FakeModelProvider(
        [
            ModelReply.json_payload({"category": "refund", "confidence": "high"}, delay=SLOW),
            ModelReply.ok("A refund takes three business days to appear."),
        ]
    )


def main() -> None:
    """Submit triage, poll while the model is still thinking, and read where it finished."""
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "support.db")
        migrate(settings)

        app = create_app(settings=settings, secret=SECRET, provider=provider())
        with create_test_client(HttpAdapter(app)) as client:
            client.post("/knowledge", headers=LEE)
            client.post(
                "/tickets",
                json={"subject": "Where is my refund?", "body": "Order 42 came back on Monday."},
                headers=ADA,
            )

            submitted = client.post("/tickets/1/triage", headers=SAM)
            accepted = submitted.json()
            print("POST /tickets/1/triage ->", submitted.status_code, accepted)

            job_id = accepted["job"]
            seen = [str(accepted["state"])]
            job = accepted
            deadline = time.monotonic() + POLL_BUDGET
            while time.monotonic() < deadline:
                job = client.get(f"/jobs/{job_id}", headers=SAM).json()
                if job["state"] not in seen:
                    seen.append(str(job["state"]))
                if job["state"] in {DONE, FAILED}:
                    break
                time.sleep(POLL_INTERVAL)
            print("the job went:", " -> ".join(seen))
            print("it finished as:", job["state"], "with", job["detail"])
            print("the ticket is:", client.get("/tickets/1", headers=SAM).json()["state"])
            print(
                "the draft is waiting for a person:",
                client.get("/tickets/1/draft", headers=SAM).json()["body"],
            )
            print("nothing was sent:", client.get("/tickets/1/sent", headers=SAM).json()["count"])


if __name__ == "__main__":
    main()
