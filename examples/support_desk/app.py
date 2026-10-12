"""Compose the support desk and expose it as an ASGI app.

Two things are worth noticing here. First, the model is provided like any other dependency, so
a route never constructs one and a test never mocks one: it hands over a different provider.
Second, there is **no route that sends a reply on the model's behalf** — the ones that exist are
the ones a person uses, and each names the principal the service will check.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.templating import Jinja2Templates

from support_desk.errors import TicketValidationError
from support_desk.jobs import TriageJobs
from support_desk.knowledge import KnowledgeBase
from support_desk.mail import Mailer
from support_desk.security import Principal, PrincipalVerifier, require_role
from support_desk.service import DEFAULT_LIMIT, TicketService
from support_desk.triage import Triage
from support_desk.usage import ACCEPTED, DISCARDED, EDITED, UsageLog
from xyberos import App, Inject, Settings
from xyberos.ai import AIFacade, FakeModelProvider, ModelProvider, ModelReply, Usage
from xyberos.database import DatabaseProvider, SqliteSettings, sqlite_provider
from xyberos.http import HttpAdapter, read_json_object

#: Where the pages live. Templates are application code: the framework routes and serializes.
TEMPLATES = Path(__file__).parent / "templates"

#: Who may read the aggregate numbers. Cost is a management view, not an agent's.
LEAD = "support_lead"


def fake_provider() -> FakeModelProvider:
    """Return the deterministic provider this path runs against.

    The script follows the order the desk calls the model in — a classification, then a draft,
    twice — so a demo ticket and a second one both get an answer. A real deployment passes a
    provider built from its own configuration; nothing else in the application changes.
    """
    return FakeModelProvider(
        [
            ModelReply.json_payload(
                {"category": "refund", "confidence": "high"}, usage=Usage(24, 6)
            ),
            ModelReply.ok("A refund takes three business days to appear.", usage=Usage(31, 12)),
            ModelReply.json_payload(
                {"category": "complaint", "confidence": "medium"}, usage=Usage(22, 6)
            ),
            ModelReply.ok("A replacement badge is on its way.", usage=Usage(28, 9)),
        ]
    )


def create_app(
    *,
    settings: SqliteSettings | None = None,
    database: DatabaseProvider | None = None,
    secret: str | None = None,
    provider: ModelProvider | None = None,
) -> App:
    """Compose the application.

    Pass ``settings`` to let the application own and start its database, or ``database`` to supply a
    provider that is already started, which the application then owns and closes. ``secret`` is the
    identity provider's shared secret; without one the verifier refuses every request.
    """
    app = App(settings=Settings.load(environ={}, overrides={"app": {"name": "support_desk"}}))
    if database is None:
        app.provide(DatabaseProvider, factory=sqlite_provider(settings), eager=True)
    else:
        app.provide(DatabaseProvider, instance=database)
    app.provide(Mailer)
    app.provide(UsageLog)
    app.provide(TicketService)
    app.provide(PrincipalVerifier, instance=PrincipalVerifier(secret))
    app.provide(AIFacade, instance=AIFacade(provider or fake_provider()))
    app.provide(KnowledgeBase)
    app.provide(Triage)
    app.provide(TriageJobs)

    def staff(request: Request, verifier: PrincipalVerifier) -> Principal:
        """Establish who is calling and that they work here, before anything else happens."""
        principal = verifier.verify(request)
        require_role(principal, "support_agent", LEAD)
        return principal

    @app.get("/health")
    async def health(
        database: Annotated[DatabaseProvider, Inject()],
        assistant: Annotated[AIFacade, Inject()],
    ) -> dict[str, str]:
        await database.health()
        return {"status": "ready", "model": assistant.model}

    @app.post("/tickets")
    async def open_ticket(
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        tickets: Annotated[TicketService, Inject()],
    ) -> dict[str, object]:
        principal = verifier.verify(request)
        payload = await read_json_object(request)
        return await tickets.open_ticket(principal, payload.get("subject"), payload.get("body"))

    @app.get("/tickets")
    async def list_tickets(
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        tickets: Annotated[TicketService, Inject()],
    ) -> dict[str, object]:
        principal = verifier.verify(request)
        query = request.query_params
        return await tickets.list_tickets(
            principal,
            limit=_whole_number(query.get("limit"), "limit", default=DEFAULT_LIMIT),
            offset=_whole_number(query.get("offset"), "offset", default=0),
        )

    @app.get("/tickets/{ticket_id}")
    async def get_ticket(
        ticket_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        tickets: Annotated[TicketService, Inject()],
    ) -> dict[str, object]:
        return await tickets.get_ticket(verifier.verify(request), ticket_id)

    @app.patch("/tickets/{ticket_id}")
    async def edit_ticket(
        ticket_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        tickets: Annotated[TicketService, Inject()],
    ) -> dict[str, object]:
        principal = verifier.verify(request)
        payload = await read_json_object(request)
        return await tickets.edit_ticket(principal, ticket_id, payload)

    @app.post("/tickets/{ticket_id}/classify")
    async def classify_ticket(
        ticket_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        triage: Annotated[Triage, Inject()],
    ) -> dict[str, object]:
        return await triage.classify(staff(request, verifier), ticket_id)

    @app.get("/tickets/{ticket_id}/draft")
    async def read_draft(
        ticket_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        tickets: Annotated[TicketService, Inject()],
    ) -> dict[str, object]:
        return await tickets.read_suggestion(staff(request, verifier), ticket_id)

    @app.post("/tickets/{ticket_id}/draft")
    async def draft_reply(
        ticket_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        triage: Annotated[Triage, Inject()],
    ) -> dict[str, object]:
        principal = staff(request, verifier)
        return await triage.draft(
            principal, ticket_id, grounding=await triage.ground(principal, ticket_id)
        )

    @app.post("/tickets/{ticket_id}/triage")
    async def start_triage(
        ticket_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        jobs: Annotated[TriageJobs, Inject()],
    ) -> Response:
        principal = staff(request, verifier)
        return JSONResponse(await jobs.submit(principal, ticket_id), status_code=202)

    @app.get("/jobs/{job_id}")
    async def read_job(
        job_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        jobs: Annotated[TriageJobs, Inject()],
    ) -> dict[str, object]:
        return await jobs.job(staff(request, verifier), job_id)

    @app.post("/tickets/{ticket_id}/approve")
    async def approve_reply(
        ticket_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        tickets: Annotated[TicketService, Inject()],
        usage: Annotated[UsageLog, Inject()],
    ) -> dict[str, object]:
        principal = staff(request, verifier)
        # The body is optional: approving a draft unchanged is the common case, and a request that
        # says nothing is not the same as a malformed one.
        payload = await read_json_object(request) if await request.body() else {}
        edited = payload.get("body")
        approved = await tickets.approve(principal, ticket_id, body=edited)
        await usage.settle(ticket_id=ticket_id, outcome=EDITED if edited else ACCEPTED)
        return approved

    @app.post("/tickets/{ticket_id}/send")
    async def send_reply(
        ticket_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        tickets: Annotated[TicketService, Inject()],
    ) -> dict[str, object]:
        return await tickets.send_reply(staff(request, verifier), ticket_id)

    @app.post("/tickets/{ticket_id}/close")
    async def close_ticket(
        ticket_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        tickets: Annotated[TicketService, Inject()],
    ) -> dict[str, object]:
        return await tickets.close_ticket(verifier.verify(request), ticket_id)

    @app.post("/tickets/{ticket_id}/reject")
    async def reject_ticket(
        ticket_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        tickets: Annotated[TicketService, Inject()],
        usage: Annotated[UsageLog, Inject()],
    ) -> dict[str, object]:
        principal = verifier.verify(request)
        rejected = await tickets.reject(principal, ticket_id)
        await usage.settle(ticket_id=ticket_id, outcome=DISCARDED)
        return rejected

    @app.post("/tickets/{ticket_id}/spam")
    async def mark_spam(
        ticket_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        tickets: Annotated[TicketService, Inject()],
    ) -> dict[str, object]:
        return await tickets.mark_spam(staff(request, verifier), ticket_id)

    @app.get("/tickets/{ticket_id}/sent")
    async def sent_messages(
        ticket_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        tickets: Annotated[TicketService, Inject()],
        mailer: Annotated[Mailer, Inject()],
    ) -> dict[str, object]:
        """Return what was actually sent for one ticket, which is the receipt for an approval.

        Reading it is an act of reading the ticket, so the visibility rule decides, and the reply
        bodies are the ones the mailer was handed rather than the ones a model wrote.
        """
        principal = staff(request, verifier)
        await tickets.get_ticket(principal, ticket_id)
        messages = await mailer.messages(tenant=principal.tenant, ticket_id=ticket_id)
        return {"messages": messages, "count": len(messages)}

    @app.get("/tickets/{ticket_id}/audit")
    async def audit_trail(
        ticket_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        tickets: Annotated[TicketService, Inject()],
    ) -> dict[str, object]:
        principal = verifier.verify(request)
        return {"events": await tickets.audit_trail(principal, ticket_id)}

    @app.post("/knowledge")
    async def index_knowledge(
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        knowledge: Annotated[KnowledgeBase, Inject()],
    ) -> dict[str, object]:
        require_role(verifier.verify(request), LEAD)
        return {"passages": await knowledge.index()}

    @app.get("/usage")
    async def read_usage(
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        usage: Annotated[UsageLog, Inject()],
    ) -> dict[str, object]:
        principal = verifier.verify(request)
        require_role(principal, LEAD)
        return await usage.summary(tenant=principal.tenant)

    templates = Jinja2Templates(directory=str(TEMPLATES))

    @app.get("/tickets/{ticket_id}/page")
    async def ticket_page(
        ticket_id: int,
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        tickets: Annotated[TicketService, Inject()],
    ) -> Response:
        """Render one ticket and its trail, which is the interface an agent actually uses.

        The page reads; approving and sending are the routes above, so a browser can never send a
        reply by rendering one. Who may read it is the same rule as everywhere else — the service
        decides — so a requester sees their own ticket and nothing more.
        """
        principal = verifier.verify(request)
        ticket = await tickets.get_ticket(principal, ticket_id)
        return templates.TemplateResponse(
            request,
            "ticket.html",
            {"ticket": ticket, "events": await tickets.audit_trail(principal, ticket_id)},
        )

    return app


def build_asgi_app(app: App) -> object:
    """Wrap the application in the HTTP adapter, for a deployment or a test client."""
    return HttpAdapter(app).asgi_app


def _whole_number(value: object, field: str, *, default: int) -> int:
    """Return a whole number from a query string, or the default when the parameter is absent."""
    if value is None or value == "":
        return default
    try:
        return int(str(value))
    except ValueError:
        raise TicketValidationError(f"{field} must be a whole number") from None
