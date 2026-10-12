"""Background triage: the request returns a job, and the work outlives the request.

A model call can take seconds. Holding an HTTP connection open for it is how a support desk
becomes unavailable when a provider gets slow, so the route submits the work and answers `202`,
and a job row is what a client polls.

``create_task_in_context`` is the runtime's contribution: the task carries the caller's context,
so the job's log lines and its correlation id belong to the request that started it. The
application owns everything else — the row, the states, and the fact that shutdown waits for work
in flight rather than abandoning it half-written.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from sqlalchemy import insert, select, update

from support_desk.errors import TicketNotFoundError
from support_desk.security import STAFF, Principal, require_role
from support_desk.service import TicketService
from support_desk.tables import jobs
from support_desk.triage import Triage
from xyberos import Inject, create_task_in_context
from xyberos.database import DatabaseProvider
from xyberos.errors import XyberosError

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


class TriageJobs:
    """Submits triage as a background task, and reports where each one got to."""

    def __init__(
        self,
        database: Annotated[DatabaseProvider, Inject()],
        tickets: Annotated[TicketService, Inject()],
        triage: Annotated[Triage, Inject()],
    ) -> None:
        self._database = database
        self._tickets = tickets
        self._triage = triage
        self._tasks: set[asyncio.Task[None]] = set()

    async def submit(self, principal: Principal, ticket_id: int) -> dict[str, object]:
        """Accept the work and return the job, before any model has been called.

        The ticket is loaded first, so a ticket in another tenant is refused with the same 404 every
        other route gives rather than becoming a failing background job.
        """
        require_role(principal, *STAFF)
        await self._tickets.get_ticket(principal, ticket_id)
        async with self._database.transaction() as connection:
            result = await connection.execute(
                insert(jobs).values(
                    tenant=principal.tenant,
                    ticket_id=ticket_id,
                    submitted_by=principal.subject,
                    state=QUEUED,
                )
            )
            inserted = result.inserted_primary_key
            if inserted is None:
                raise AssertionError("the insert reported no primary key")
            job_id = int(inserted[0])
        task = create_task_in_context(
            self._run(job_id, principal, ticket_id), name=f"triage-{job_id}"
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return {"job": job_id, "state": QUEUED, "ticket": ticket_id}

    async def job(self, principal: Principal, job_id: int) -> dict[str, object]:
        """Return one job in the caller's tenant, or report it as not found."""
        require_role(principal, *STAFF)
        async with self._database.transaction() as connection:
            row = (
                (
                    await connection.execute(
                        select(jobs).where(jobs.c.id == job_id, jobs.c.tenant == principal.tenant)
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise TicketNotFoundError(job_id)
        return dict(row)

    async def wait(self) -> None:
        """Wait for the work in flight, which is what shutdown has to do to be honest."""
        while self._tasks:
            tasks = list(self._tasks)
            self._tasks.clear()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def aclose(self) -> None:
        """Close the component the way the runtime closes a provided resource."""
        await self.wait()

    async def _run(self, job_id: int, principal: Principal, ticket_id: int) -> None:
        """Run the workflow and record the outcome on the job row, whatever it was."""
        await self._set(job_id, RUNNING, "")
        try:
            result = await self._triage.run(principal, ticket_id)
        except XyberosError as error:
            # A model failure is the job's failure, not the request's: the row names the error
            # class, and the message stays on the server rather than travelling to a client.
            await self._set(job_id, FAILED, type(error).__name__)
        else:
            await self._set(job_id, DONE, str(result["state"]))

    async def _set(self, job_id: int, state: str, detail: str) -> None:
        async with self._database.transaction() as connection:
            await connection.execute(
                update(jobs).where(jobs.c.id == job_id).values(state=state, detail=detail)
            )
