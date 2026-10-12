"""The ticket service: the lifecycle, the permission matrix, and the audit trail.

Three rules are enforced here rather than described, and every one of them is a signature:

* **The principal is a required argument.** There is no method that resolves a caller from a global,
  so forgetting to pass one is a type error and not a silent authorization bypass;
* **the tenant is part of every lookup.** A ticket in another tenant is *not found*, never
  *forbidden*, because a refusal that confirms a ticket exists is a leak;
* **an audit row is written in the same transaction as the change it records.** A trail that can be
  lost separately from the thing it describes is a trail that will be.

The service also never calls a model. It takes a category, a confidence, and a drafted body as
arguments, so what it enforces — who may move a ticket, and from where — is testable without a
provider and reviewable without reading a prompt.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql.elements import ColumnElement

from support_desk.clock import utc_now
from support_desk.errors import (
    ApprovalRequiredError,
    SuggestionNotFoundError,
    TicketNotFoundError,
    TicketValidationError,
    TransitionRefusedError,
)
from support_desk.mail import Mailer
from support_desk.security import STAFF, Principal, require_role
from support_desk.tables import audit_events, suggested_replies, tickets
from xyberos import Inject
from xyberos.database import DatabaseProvider

NEW = "new"
CLASSIFIED = "classified"
AWAITING_APPROVAL = "awaiting_approval"
APPROVED = "approved"
REPLIED = "replied"
CLOSED = "closed"
REJECTED = "rejected"
SPAM = "spam"

#: The lifecycle as the design page states it: which states an action may leave. The roles are in
#: the methods, because each one has a different requirement and a table of them would be a table
#: nobody reads next to the code that enforces it.
TRANSITIONS: Mapping[str, tuple[str, ...]] = {
    "classify": (NEW,),
    "draft": (CLASSIFIED,),
    "approve": (AWAITING_APPROVAL,),
    "send": (APPROVED,),
    "close": (REPLIED,),
    "reject": (NEW, CLASSIFIED),
    "mark_spam": (NEW,),
}

CATEGORIES = ("refund", "question", "complaint", "abuse")
CONFIDENCES = ("low", "medium", "high")

#: What a client may change about a ticket, and nothing else: the state is moved by the transitions.
EDITABLE_FIELDS = ("subject", "body")

MAX_SUBJECT_LENGTH = 200
MAX_BODY_LENGTH = 4000
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class TicketService:
    """Owns ticket rules and keeps every write inside one short transaction."""

    def __init__(
        self,
        database: Annotated[DatabaseProvider, Inject()],
        mailer: Annotated[Mailer, Inject()],
    ) -> None:
        self._database = database
        self._mailer = mailer

    async def open_ticket(
        self, principal: Principal, subject: object, body: object
    ) -> dict[str, object]:
        """Open a ticket for the calling principal, in the calling principal's tenant."""
        values = {
            "tenant": principal.tenant,
            "requester": principal.subject,
            "subject": _validated_text(subject, "subject", MAX_SUBJECT_LENGTH),
            "body": _validated_text(body, "body", MAX_BODY_LENGTH),
            "state": NEW,
        }
        async with self._database.transaction() as connection:
            result = await connection.execute(insert(tickets).values(**values))
            inserted = result.inserted_primary_key
            if inserted is None:
                raise AssertionError("the insert reported no primary key")
            ticket_id = int(inserted[0])
            await _record(connection, principal, ticket_id, "opened", values["subject"])
            return await _row(connection, principal, ticket_id)

    async def list_tickets(
        self, principal: Principal, *, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> dict[str, object]:
        """Return one page of the tickets this principal may read, and how many there are."""
        page_limit = _whole_number(limit, "limit", maximum=MAX_LIMIT)
        page_offset = _whole_number(offset, "offset", maximum=10_000)
        statement = (
            select(tickets)
            .where(_visible(principal))
            .order_by(tickets.c.id)
            .limit(page_limit)
            .offset(page_offset)
        )
        count = select(func.count()).select_from(tickets).where(_visible(principal))
        async with self._database.transaction() as connection:
            rows = (await connection.execute(statement)).mappings().all()
            total = int((await connection.execute(count)).scalar_one())
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "limit": page_limit,
            "offset": page_offset,
        }

    async def get_ticket(self, principal: Principal, ticket_id: int) -> dict[str, object]:
        """Return one ticket this principal may read, or report it as not found."""
        async with self._database.transaction() as connection:
            return await _row(connection, principal, ticket_id)

    async def edit_ticket(
        self, principal: Principal, ticket_id: int, changes: Mapping[str, object]
    ) -> dict[str, object]:
        """Correct a ticket's text, while nobody has worked on it yet.

        The visibility rule already decides who can reach the row — staff read the tenant, everyone
        else reads only their own — so this method adds one condition: a ticket that has been worked
        on is history, and history is not edited. The trail records what changed, not only that
        something changed.
        """
        values = _validated_changes(changes)
        async with self._database.transaction() as connection:
            row = await _row(connection, principal, ticket_id)
            if row["state"] != NEW:
                raise TransitionRefusedError(str(row["state"]), "edit")
            await connection.execute(
                update(tickets).where(tickets.c.id == ticket_id).values(**values)
            )
            await _record(connection, principal, ticket_id, "edited", ", ".join(sorted(values)))
            return await _row(connection, principal, ticket_id)

    async def classify(
        self,
        principal: Principal,
        ticket_id: int,
        *,
        category: object,
        confidence: object,
    ) -> dict[str, object]:
        """Record what a model decided the ticket is about, and move it to ``classified``."""
        require_role(principal, *STAFF)
        if category not in CATEGORIES:
            raise TicketValidationError(f"category must be one of {', '.join(CATEGORIES)}")
        if confidence not in CONFIDENCES:
            raise TicketValidationError(f"confidence must be one of {', '.join(CONFIDENCES)}")
        async with self._database.transaction() as connection:
            row = await _row(connection, principal, ticket_id)
            _may_leave(row["state"], "classify")
            await connection.execute(
                update(tickets)
                .where(tickets.c.id == ticket_id)
                .values(state=CLASSIFIED, category=category, confidence=confidence)
            )
            await _record(
                connection, principal, ticket_id, "classified", f"{category}/{confidence}"
            )
            return await _row(connection, principal, ticket_id)

    async def attach_suggestion(
        self, principal: Principal, ticket_id: int, *, body: object, model: str
    ) -> dict[str, object]:
        """Store a drafted reply: it sends nothing and moves the ticket to ``awaiting_approval``."""
        require_role(principal, *STAFF)
        draft = _validated_text(body, "body", MAX_BODY_LENGTH)
        async with self._database.transaction() as connection:
            row = await _row(connection, principal, ticket_id)
            _may_leave(row["state"], "draft")
            result = await connection.execute(
                insert(suggested_replies).values(ticket_id=ticket_id, body=draft, model=model)
            )
            inserted = result.inserted_primary_key
            if inserted is None:
                raise AssertionError("the insert reported no primary key")
            await connection.execute(
                update(tickets).where(tickets.c.id == ticket_id).values(state=AWAITING_APPROVAL)
            )
            await _record(connection, principal, ticket_id, "drafted", model)
            return await _suggestion(connection, int(inserted[0]))

    async def read_suggestion(self, principal: Principal, ticket_id: int) -> dict[str, object]:
        """Return the newest draft for a ticket, which only staff may read."""
        require_role(principal, *STAFF)
        async with self._database.transaction() as connection:
            await _row(connection, principal, ticket_id)
            row = (
                (
                    await connection.execute(
                        select(suggested_replies)
                        .where(suggested_replies.c.ticket_id == ticket_id)
                        .order_by(suggested_replies.c.id.desc())
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise SuggestionNotFoundError(ticket_id)
        return dict(row)

    async def approve(
        self, principal: Principal, ticket_id: int, *, body: object = None
    ) -> dict[str, object]:
        """Record a person's approval of a draft, and nothing else.

        ``body`` is how an agent sends something they edited: the row keeps the model's draft and
        the approved text side by side, so a review can tell the two apart. Approving changes no
        state outside this application — the reply is sent by ``send_reply``, which is a separate
        step a separate call has to ask for.
        """
        require_role(principal, *STAFF)
        async with self._database.transaction() as connection:
            row = await _row(connection, principal, ticket_id)
            _may_leave(row["state"], "approve")
            suggestion = (
                (
                    await connection.execute(
                        select(suggested_replies)
                        .where(suggested_replies.c.ticket_id == ticket_id)
                        .order_by(suggested_replies.c.id.desc())
                    )
                )
                .mappings()
                .first()
            )
            if suggestion is None:
                raise SuggestionNotFoundError(ticket_id)
            approved = _validated_text(
                suggestion["body"] if body is None else body, "body", MAX_BODY_LENGTH
            )
            await connection.execute(
                update(suggested_replies)
                .where(suggested_replies.c.id == suggestion["id"])
                .values(
                    approved_by=principal.subject, approved_body=approved, approved_at=utc_now()
                )
            )
            await connection.execute(
                update(tickets).where(tickets.c.id == ticket_id).values(state=APPROVED)
            )
            await _record(connection, principal, ticket_id, "approved", approved)
            return await _row(connection, principal, ticket_id)

    async def send_reply(self, principal: Principal, ticket_id: int) -> dict[str, object]:
        """Send the body a person approved, which is the only way a body is ever sent.

        The outbox row, the state change, and the audit row are one transaction. That is the whole
        guarantee: a reply that was sent is a reply the ticket says was sent, and a failure anywhere
        leaves the ticket approved with nothing delivered rather than replied with nothing behind
        it.
        """
        require_role(principal, *STAFF)
        async with self._database.transaction() as connection:
            row = await _row(connection, principal, ticket_id)
            _may_leave(row["state"], "send")
            suggestion = (
                (
                    await connection.execute(
                        select(suggested_replies)
                        .where(suggested_replies.c.ticket_id == ticket_id)
                        .where(suggested_replies.c.approved_body.is_not(None))
                        .order_by(suggested_replies.c.id.desc())
                    )
                )
                .mappings()
                .first()
            )
            if suggestion is None:
                raise ApprovalRequiredError(ticket_id)
            recipient = str(row["requester"])
            await self._mailer.deliver(
                connection,
                tenant=principal.tenant,
                ticket_id=ticket_id,
                recipient=recipient,
                body=str(suggestion["approved_body"]),
            )
            await connection.execute(
                update(tickets).where(tickets.c.id == ticket_id).values(state=REPLIED)
            )
            await _record(connection, principal, ticket_id, "replied", recipient)
            return await _row(connection, principal, ticket_id)

    async def close_ticket(self, principal: Principal, ticket_id: int) -> dict[str, object]:
        """Close a replied ticket: staff may, and a requester may close their own.

        The name is ``close_ticket`` and not ``close`` on purpose: the runtime treats a ``close``
        method on a provided instance as a lifecycle hook and calls it with no arguments, so a
        domain verb borrowed from the lifecycle is a shutdown failure waiting to happen.
        """
        async with self._database.transaction() as connection:
            row = await _row(connection, principal, ticket_id)
            _may_leave(row["state"], "close")
            await connection.execute(
                update(tickets).where(tickets.c.id == ticket_id).values(state=CLOSED)
            )
            await _record(connection, principal, ticket_id, "closed", "")
            return await _row(connection, principal, ticket_id)

    async def reject(self, principal: Principal, ticket_id: int) -> dict[str, object]:
        """Reject a ticket before it was worked on, which only a lead may do."""
        require_role(principal, "support_lead")
        async with self._database.transaction() as connection:
            row = await _row(connection, principal, ticket_id)
            _may_leave(row["state"], "reject")
            await connection.execute(
                update(tickets).where(tickets.c.id == ticket_id).values(state=REJECTED)
            )
            await _record(connection, principal, ticket_id, "rejected", "")
            return await _row(connection, principal, ticket_id)

    async def mark_spam(self, principal: Principal, ticket_id: int) -> dict[str, object]:
        """Mark a new ticket as spam, which an agent may do and a requester may not."""
        require_role(principal, *STAFF)
        async with self._database.transaction() as connection:
            row = await _row(connection, principal, ticket_id)
            _may_leave(row["state"], "mark_spam")
            await connection.execute(
                update(tickets).where(tickets.c.id == ticket_id).values(state=SPAM)
            )
            await _record(connection, principal, ticket_id, "spam", "")
            return await _row(connection, principal, ticket_id)

    async def audit_trail(self, principal: Principal, ticket_id: int) -> list[dict[str, object]]:
        """Return a ticket's trail: staff read the tenant's, a requester reads their own."""
        async with self._database.transaction() as connection:
            await _row(connection, principal, ticket_id)
            statement = (
                select(audit_events)
                .where(audit_events.c.ticket_id == ticket_id)
                .order_by(audit_events.c.id)
            )
            rows = (await connection.execute(statement)).mappings().all()
        return [dict(row) for row in rows]

    async def record_event(
        self, principal: Principal, ticket_id: int, action: str, detail: str = ""
    ) -> None:
        """Record something that happened to a ticket without changing its state.

        A workflow step that decided not to act still has something to say, and an audit trail that
        only records transitions cannot tell "nothing happened" from "nobody looked".
        """
        require_role(principal, *STAFF)
        async with self._database.transaction() as connection:
            await _row(connection, principal, ticket_id)
            await _record(connection, principal, ticket_id, action, detail)

    async def state_of(self, principal: Principal, ticket_id: int) -> str:
        """Return one ticket's state, which is what a caller usually wants after a transition."""
        row = await self.get_ticket(principal, ticket_id)
        return str(row["state"])


def _visible(principal: Principal) -> ColumnElement[bool]:
    """The condition that makes a row readable by this principal.

    Staff read the tenant; everyone else reads their own tickets. It is one expression used by both
    the page query and its count, so a page cannot disagree with the total above it.
    """
    if principal.holds(*STAFF):
        return tickets.c.tenant == principal.tenant
    return and_(tickets.c.tenant == principal.tenant, tickets.c.requester == principal.subject)


async def _row(
    connection: AsyncConnection, principal: Principal, ticket_id: int
) -> dict[str, object]:
    """Load one visible ticket, or report it as not found."""
    statement = select(tickets).where(tickets.c.id == ticket_id, _visible(principal))
    row = (await connection.execute(statement)).mappings().first()
    if row is None:
        raise TicketNotFoundError(ticket_id)
    return dict(row)


async def _suggestion(connection: AsyncConnection, suggestion_id: int) -> dict[str, object]:
    """Load one suggested reply by id."""
    statement = select(suggested_replies).where(suggested_replies.c.id == suggestion_id)
    row = (await connection.execute(statement)).mappings().one()
    return dict(row)


async def _record(
    connection: AsyncConnection,
    principal: Principal,
    ticket_id: int,
    action: str,
    detail: str,
) -> None:
    """Write one audit row, inside the caller's transaction."""
    await connection.execute(
        insert(audit_events).values(
            tenant=principal.tenant,
            ticket_id=ticket_id,
            actor=principal.subject,
            action=action,
            detail=detail,
            recorded_at=utc_now(),
        )
    )


def _may_leave(state: object, action: str) -> None:
    """Refuse an action the ticket's state does not allow."""
    if str(state) not in TRANSITIONS[action]:
        raise TransitionRefusedError(str(state), action)


def _validated_changes(changes: Mapping[str, object]) -> dict[str, object]:
    """Return the fields a client may change, validated, or raise a 422.

    An unknown field is refused rather than ignored, which is the difference between a typo that
    surprises a caller and a typo that silently does nothing.
    """
    values: dict[str, object] = {}
    for field in changes:
        if field not in EDITABLE_FIELDS:
            raise TicketValidationError(f"{field} cannot be changed")
    if "subject" in changes:
        values["subject"] = _validated_text(changes["subject"], "subject", MAX_SUBJECT_LENGTH)
    if "body" in changes:
        values["body"] = _validated_text(changes["body"], "body", MAX_BODY_LENGTH)
    if not values:
        raise TicketValidationError(f"provide one of {', '.join(EDITABLE_FIELDS)}")
    return values


def _validated_text(value: object, field: str, maximum: int) -> str:
    """Return a trimmed, non-empty string within the column's length, or raise a 422."""
    if not isinstance(value, str) or not value.strip():
        raise TicketValidationError(f"{field} is required")
    text = " ".join(value.split())
    if len(text) > maximum:
        raise TicketValidationError(f"{field} must be at most {maximum} characters")
    return text


def _whole_number(value: object, field: str, *, maximum: int) -> int:
    """Return a non-negative whole number within bounds, or raise a 422."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TicketValidationError(f"{field} must be a whole number")
    if not 0 <= value <= maximum:
        raise TicketValidationError(f"{field} must be between 0 and {maximum}")
    return value
