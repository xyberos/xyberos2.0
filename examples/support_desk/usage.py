"""Usage rows: tokens in, tokens out, what it cost, and what happened to the reply.

Cost is a table the application owns, because a price is a fact about a contract rather than about a
provider's API. The outcome column is the one that makes the numbers answerable: a draft nobody
approved and a draft that was sent both cost the same to produce, and only one of them was work.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated

from sqlalchemy import func, insert, select, update

from support_desk.clock import utc_now
from support_desk.tables import usage_events
from xyberos import Inject
from xyberos.database import DatabaseProvider

#: Dollars per thousand tokens, for the models this deployment knows about. A model that is not here
#: costs nothing to record and 0.0 to add up, which is honest: an unknown price is unknown.
PRICES: Mapping[str, tuple[float, float]] = {
    "fake-model": (0.0, 0.0),
    "small-model": (0.25, 1.25),
    "large-model": (3.0, 15.0),
}

PENDING = "pending"
ACCEPTED = "accepted"
EDITED = "edited"
DISCARDED = "discarded"


def cost_micros(model: str, input_tokens: int, output_tokens: int) -> int:
    """Return what one call cost, in millionths of a dollar, rounded to the nearest one."""
    if model not in PRICES:
        return 0
    input_price, output_price = PRICES[model]
    thousands = (input_tokens * input_price + output_tokens * output_price) / 1000
    return round(thousands * 1_000_000)


class UsageLog:
    """Writes one row per model call, and one outcome per draft once a person has decided."""

    def __init__(self, database: Annotated[DatabaseProvider, Inject()]) -> None:
        self._database = database

    async def record(
        self,
        *,
        tenant: str,
        ticket_id: int | None,
        step: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> int:
        """Record one call and return its row id."""
        async with self._database.transaction() as connection:
            result = await connection.execute(
                insert(usage_events).values(
                    tenant=tenant,
                    ticket_id=ticket_id,
                    step=step,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    outcome=PENDING,
                    recorded_at=utc_now(),
                )
            )
            inserted = result.inserted_primary_key
            if inserted is None:
                raise AssertionError("the insert reported no primary key")
            return int(inserted[0])

    async def settle(self, *, ticket_id: int, outcome: str) -> int:
        """Record what became of this ticket's drafts, and return how many rows changed."""
        async with self._database.transaction() as connection:
            result = await connection.execute(
                update(usage_events)
                .where(usage_events.c.ticket_id == ticket_id, usage_events.c.outcome == PENDING)
                .values(outcome=outcome)
            )
            return result.rowcount

    async def rows(self, *, tenant: str, ticket_id: int | None = None) -> list[dict[str, object]]:
        """Return the recorded calls, oldest first."""
        statement = select(usage_events).where(usage_events.c.tenant == tenant)
        if ticket_id is not None:
            statement = statement.where(usage_events.c.ticket_id == ticket_id)
        async with self._database.transaction() as connection:
            found = (
                (await connection.execute(statement.order_by(usage_events.c.id))).mappings().all()
            )
        return [dict(row) for row in found]

    async def summary(self, *, tenant: str) -> dict[str, object]:
        """Return tokens and cost for a tenant, grouped by step, with the outcomes counted."""
        async with self._database.transaction() as connection:
            grouped = (
                (
                    await connection.execute(
                        select(
                            usage_events.c.step,
                            usage_events.c.model,
                            func.count().label("calls"),
                            func.sum(usage_events.c.input_tokens).label("input_tokens"),
                            func.sum(usage_events.c.output_tokens).label("output_tokens"),
                        )
                        .where(usage_events.c.tenant == tenant)
                        .group_by(usage_events.c.step, usage_events.c.model)
                        .order_by(usage_events.c.step)
                    )
                )
                .mappings()
                .all()
            )
            outcomes = (
                (
                    await connection.execute(
                        select(usage_events.c.outcome, func.count().label("calls"))
                        .where(usage_events.c.tenant == tenant)
                        .group_by(usage_events.c.outcome)
                        .order_by(usage_events.c.outcome)
                    )
                )
                .mappings()
                .all()
            )
        return {
            "steps": [_priced(dict(row)) for row in grouped],
            "outcomes": {str(row["outcome"]): int(row["calls"]) for row in outcomes},
        }


def _tokens(value: object) -> int:
    """Return a token count from a row, which arrives as whatever the database stored."""
    if isinstance(value, int):
        return value
    raise AssertionError(f"a recorded token count was not a whole number: {value!r}")


def _priced(row: dict[str, object]) -> dict[str, object]:
    """Add the cost of a grouped row to itself, so a caller never re-does the arithmetic."""
    model = str(row["model"])
    input_tokens = _tokens(row["input_tokens"])
    output_tokens = _tokens(row["output_tokens"])
    return {
        **row,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_micros": cost_micros(model, input_tokens, output_tokens),
    }


def totals(rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    """Return the token totals and the cost of a set of recorded calls."""
    return {
        "input_tokens": sum(_tokens(row["input_tokens"]) for row in rows),
        "output_tokens": sum(_tokens(row["output_tokens"]) for row in rows),
        "cost_micros": sum(
            cost_micros(
                str(row["model"]), _tokens(row["input_tokens"]), _tokens(row["output_tokens"])
            )
            for row in rows
        ),
    }
