"""The journal store: transactional submission, claims, guarded writes, and inspection.

Three rules hold everywhere in this module:

* **The journal is the truth.** A worker's only authority is a row in ``worker_leases``; every write
  carries the owner and the fencing token and is applied through a conditional ``WHERE`` clause, so
  a worker whose lease expired cannot commit anything, no matter what it believes it did.
* **Transitions are validated before they are written**, against
  :mod:`xyberos.durable.models`, so an illegal transition is a bug in the worker rather than a row
  nobody can interpret.
* **A write that loses its guard explains itself.** A refused write is re-read and reported as a
  lease problem, a cancellation, or a state problem — never as "no rows matched".

Read-modify-write inside one transaction is what makes the decisions correct, and SQLite's write
lock is what makes them atomic; contention is retried by the bounded retry the database layer
already applies.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from typing import TypeVar
from uuid import uuid4

try:
    from sqlalchemy import text
    from sqlalchemy.engine import RowMapping
    from sqlalchemy.ext.asyncio import AsyncConnection
except ModuleNotFoundError as error:
    from xyberos._extras import extra_error

    raise extra_error("durable", error) from error

from xyberos.durable.contracts import SystemWallClock, WallClock
from xyberos.durable.journal import Journal, from_iso, to_iso
from xyberos.durable.models import (
    ActivityPolicy,
    Claim,
    EventKind,
    EventView,
    ExecutionHandle,
    ExecutionStatus,
    ExecutionView,
    FailureKind,
    JournalStats,
    StepState,
    StepView,
    execution_is_terminal,
    require_execution_transition,
    require_step_transition,
)
from xyberos.errors import (
    DurableConflictError,
    DurableLeaseError,
    DurablePayloadError,
    DurableStateError,
    DurableVersionError,
)
from xyberos.execution.models import Workflow

T = TypeVar("T")

_LEASE_GUARD = """
    EXISTS (
        SELECT 1
        FROM worker_leases
        WHERE execution_id = :execution_id
          AND owner = :owner
          AND fence = :fence
          AND expires_at > :now
    )
"""


def definition_fingerprint(workflow: Workflow) -> str:
    """Return a stable fingerprint of a definition's persisted-relevant shape.

    The fingerprint covers the names, ordering, edges, and conditions that decide which step runs
    next — the things that make an interrupted execution resumable. It deliberately excludes
    callables: the journal stores metadata, never code, and a resumed execution that finds a
    different graph must refuse rather than improvise.
    """
    payload = {
        "name": workflow.name,
        "version": workflow.version,
        "steps": [
            {
                "id": step.id,
                "timeout": step.timeout,
                "sources": sorted(edge.source for edge in workflow.incoming(step.id)),
            }
            for step in workflow.steps
        ],
        "edges": [
            {"source": edge.source, "target": edge.target, "conditioned": edge.when is not None}
            for edge in workflow.edges
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dump(value: object, *, limit: int, what: str) -> str:
    """Serialize a payload, refusing anything the journal could not give back verbatim."""

    def reject(unknown: object) -> object:
        raise DurablePayloadError(
            f"{what} contains {type(unknown).__name__}, which is not JSON-serializable; "
            "durable execution persists inputs, outputs, and results so a run can be resumed"
        )

    text_value = json.dumps(value, sort_keys=True, separators=(",", ":"), default=reject)
    size = len(text_value.encode("utf-8"))
    if size > limit:
        raise DurablePayloadError(
            f"{what} is {size} bytes, over the {limit}-byte journal payload limit"
        )
    return text_value


def _load(value: str | None) -> object:
    return None if value is None else json.loads(value)


class JournalStore:
    """The durable execution store: submission, claims, state transitions, and inspection."""

    def __init__(self, journal: Journal, *, clock: WallClock | None = None) -> None:
        self._journal = journal
        self._clock: WallClock = clock if clock is not None else SystemWallClock()

    @property
    def journal(self) -> Journal:
        """The journal this store writes to."""
        return self._journal

    @property
    def clock(self) -> WallClock:
        """The wall clock this store stamps rows with."""
        return self._clock

    @property
    def lease_ttl(self) -> float:
        """The default lease lifetime in seconds."""
        return self._journal.settings.lease_ttl_seconds

    # -- transactions ---------------------------------------------------------------------

    async def _write(self, operation: Callable[[AsyncConnection], Awaitable[T]]) -> T:
        return await self._journal.database.retrying(operation)

    async def _read(self, operation: Callable[[AsyncConnection], Awaitable[T]]) -> T:
        async with self._journal.database.transaction() as connection:
            return await operation(connection)

    def _now(self) -> datetime:
        return self._clock.now()

    async def _append_event(
        self,
        connection: AsyncConnection,
        execution_id: str,
        kind: EventKind,
        *,
        at: datetime,
        step_id: str | None = None,
        attempt: int | None = None,
        detail: str | None = None,
    ) -> None:
        await connection.execute(
            text(
                "INSERT INTO execution_events (execution_id, kind, step_id, attempt, detail, at)"
                " VALUES (:execution_id, :kind, :step_id, :attempt, :detail, :at)"
            ),
            {
                "execution_id": execution_id,
                "kind": kind.value,
                "step_id": step_id,
                "attempt": attempt,
                "detail": detail,
                "at": to_iso(at),
            },
        )

    async def _explain_refused_write(
        self,
        connection: AsyncConnection,
        claim: Claim,
        *,
        now: datetime,
        expected: str,
        allow_cancelled: bool = False,
    ) -> None:
        """Raise the specific reason a guarded write matched no rows."""
        row = (
            await connection.execute(
                text(
                    "SELECT status, cancellation_requested_at FROM executions"
                    " WHERE execution_id = :execution_id"
                ),
                {"execution_id": claim.execution_id},
            )
        ).first()
        if row is None:
            raise DurableStateError(f"execution {claim.execution_id} is no longer in the journal")
        status = ExecutionStatus(row[0])
        if row[1] is not None and not allow_cancelled:
            raise DurableStateError(
                f"execution {claim.execution_id} was cancelled while in state {status.value!r}; "
                f"{expected} cannot be recorded after a cancellation request"
            )
        lease = (
            await connection.execute(
                text(
                    "SELECT owner, fence, expires_at FROM worker_leases"
                    " WHERE execution_id = :execution_id"
                ),
                {"execution_id": claim.execution_id},
            )
        ).first()
        moment = to_iso(now)
        if lease is None:
            raise DurableLeaseError(
                f"execution {claim.execution_id} has no lease; the claim is no longer valid",
                execution_id=claim.execution_id,
                fence=claim.fence,
            )
        owner, fence, expires_at = lease
        if owner != claim.owner or fence != claim.fence:
            raise DurableLeaseError(
                f"execution {claim.execution_id} is owned by {owner!r} at fence {fence}; "
                f"this worker holds fence {claim.fence}",
                execution_id=claim.execution_id,
                fence=claim.fence,
            )
        raise DurableLeaseError(
            f"the lease for execution {claim.execution_id} expired at {expires_at} "
            f"(now {moment}); the work has been taken over",
            execution_id=claim.execution_id,
            fence=claim.fence,
        )

    async def _release_lease(
        self, connection: AsyncConnection, claim: Claim, *, now: datetime
    ) -> None:
        """Mark the claim's lease as finished.

        An execution that is ready, retrying, or parked is owned by nobody, so it must not carry a
        live lease: a live lease means "a worker is on this right now", and holding one after
        yielding would only delay the next worker and the operator.
        """
        await connection.execute(
            text(
                "UPDATE worker_leases SET expires_at = :now"
                " WHERE execution_id = :execution_id AND owner = :owner AND fence = :fence"
            ),
            {
                "now": to_iso(now),
                "execution_id": claim.execution_id,
                "owner": claim.owner,
                "fence": claim.fence,
            },
        )

    async def _execution_row(self, connection: AsyncConnection, execution_id: str) -> RowMapping:
        row = (
            (
                await connection.execute(
                    text(
                        "SELECT execution_id, workflow, version, fingerprint, status, input,"
                        " result,"
                        " failure_kind, failure_message, current_step, attempts, submitted_at,"
                        " updated_at, deadline_at, cancellation_requested_at, cancellation_reason"
                        " FROM executions WHERE execution_id = :execution_id"
                    ),
                    {"execution_id": execution_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise DurableStateError(f"execution {execution_id} is not in the journal")
        return row

    async def _step_row(
        self, connection: AsyncConnection, execution_id: str, step_id: str
    ) -> RowMapping:
        row = (
            (
                await connection.execute(
                    text(
                        "SELECT step_id, state, state_detail, attempts, output, error_type,"
                        " error_message, started_at, finished_at, idempotency_key"
                        " FROM execution_steps WHERE execution_id = :execution_id"
                        " AND step_id = :step_id"
                    ),
                    {"execution_id": execution_id, "step_id": step_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise DurableStateError(f"step {step_id!r} is not part of execution {execution_id}")
        return row

    async def _set_execution_status(
        self,
        connection: AsyncConnection,
        claim: Claim,
        target: ExecutionStatus,
        *,
        now: datetime,
        extra: str = "",
        params: dict[str, object] | None = None,
        allow_cancelled: bool = False,
    ) -> None:
        """Move the execution to ``target`` under the lease guard, validating the transition.

        The source state is read from the journal, never taken from the caller: a transition is
        validated against what is persisted, which is the only thing a restart can trust.
        """
        row = await self._execution_row(connection, claim.execution_id)
        source = ExecutionStatus(row["status"])
        require_execution_transition(source, target)
        cancellation = "" if allow_cancelled else " AND cancellation_requested_at IS NULL"
        statement = (
            f"UPDATE executions SET status = :status, updated_at = :now{extra}"
            f" WHERE execution_id = :execution_id AND status = :source{cancellation}"
            f" AND {_LEASE_GUARD}"
        )
        values: dict[str, object] = {
            "status": target.value,
            "now": to_iso(now),
            "execution_id": claim.execution_id,
            "source": source.value,
            "owner": claim.owner,
            "fence": claim.fence,
        }
        values.update(params or {})
        result = await connection.execute(text(statement), values)
        if result.rowcount != 1:
            await self._explain_refused_write(
                connection,
                claim,
                now=now,
                expected=target.value,
                allow_cancelled=allow_cancelled,
            )

    async def _set_step_state(
        self,
        connection: AsyncConnection,
        claim: Claim,
        step_id: str,
        target: StepState,
        *,
        now: datetime,
        extra: str = "",
        params: dict[str, object] | None = None,
        allowed_sources: frozenset[StepState] | None = None,
    ) -> None:
        row = await self._step_row(connection, claim.execution_id, step_id)
        source = StepState(row["state"])
        require_step_transition(source, target)
        sources = allowed_sources or frozenset({source})
        ordered = sorted(sources, key=lambda state: state.value)
        placeholders = ", ".join(f":source_{index}" for index, _ in enumerate(ordered))
        statement = (
            f"UPDATE execution_steps SET state = :state{extra}"
            f" WHERE execution_id = :execution_id AND step_id = :step_id"
            f" AND state IN ({placeholders}) AND {_LEASE_GUARD}"
        )
        values: dict[str, object] = {
            "state": target.value,
            "execution_id": claim.execution_id,
            "step_id": step_id,
            "now": to_iso(now),
            "owner": claim.owner,
            "fence": claim.fence,
        }
        for index, source_state in enumerate(sorted(sources, key=lambda state: state.value)):
            values[f"source_{index}"] = source_state.value
        values.update(params or {})
        result = await connection.execute(text(statement), values)
        if result.rowcount != 1:
            await self._explain_refused_write(
                connection, claim, now=now, expected=f"step {step_id!r} transition"
            )

    # -- definitions and submission -------------------------------------------------------

    async def register_definition(self, workflow: Workflow) -> str:
        """Persist a definition's name, version, and fingerprint; return the fingerprint."""
        workflow.validate()
        fingerprint = definition_fingerprint(workflow)
        now = self._now()
        metadata = _dump(
            dict(workflow.metadata),
            limit=self._journal.settings.max_payload_bytes,
            what=f"metadata of workflow {workflow.name!r}",
        )

        async def operation(connection: AsyncConnection) -> str:
            existing = (
                await connection.execute(
                    text(
                        "SELECT fingerprint FROM workflow_definitions"
                        " WHERE workflow = :workflow AND version = :version"
                    ),
                    {"workflow": workflow.name, "version": workflow.version},
                )
            ).first()
            if existing is not None and existing[0] != fingerprint:
                raise DurableVersionError(
                    f"workflow {workflow.name!r} version {workflow.version!r} is already "
                    "registered with a different definition; a definition cannot be changed "
                    "in place, because persisted executions resume against the version they saw"
                )
            if existing is None:
                await connection.execute(
                    text(
                        "INSERT INTO workflow_definitions"
                        " (workflow, version, fingerprint, metadata, registered_at)"
                        " VALUES (:workflow, :version, :fingerprint, :metadata, :at)"
                    ),
                    {
                        "workflow": workflow.name,
                        "version": workflow.version,
                        "fingerprint": fingerprint,
                        "metadata": metadata,
                        "at": to_iso(now),
                    },
                )
            return fingerprint

        return await self._write(operation)

    async def submit(
        self,
        workflow: Workflow,
        *,
        input: object = None,
        timeout: float | None = None,
        execution_id: str | None = None,
        submission_key: str | None = None,
    ) -> ExecutionHandle:
        """Persist a new execution and its starting events, transactionally.

        Submitting twice with the same ``execution_id`` and the same definition is idempotent, so a
        caller that lost the response can safely retry; submitting the same id for different work
        raises :class:`DurableConflictError`.
        """
        if timeout is not None and timeout <= 0:
            raise DurableStateError("timeout must be greater than zero")
        identifier = execution_id or uuid4().hex
        await self.register_definition(workflow)
        fingerprint = definition_fingerprint(workflow)
        payload = _dump(
            input,
            limit=self._journal.settings.max_payload_bytes,
            what=f"input of execution {identifier}",
        )
        now = self._now()
        deadline = None if timeout is None else now + timedelta(seconds=timeout)
        if submission_key is not None and not submission_key.strip():
            raise DurableStateError("submission_key must not be blank")

        async def operation(connection: AsyncConnection) -> ExecutionHandle:
            existing = (
                await connection.execute(
                    text(
                        "SELECT workflow, version, fingerprint, input, status FROM executions"
                        " WHERE execution_id = :execution_id"
                    ),
                    {"execution_id": identifier},
                )
            ).first()
            if existing is not None:
                same = (
                    existing[0] == workflow.name
                    and existing[1] == workflow.version
                    and existing[2] == fingerprint
                    and existing[3] == payload
                )
                if not same:
                    raise DurableConflictError(
                        f"execution {identifier} already exists with different work; "
                        "use a new execution id"
                    )
                return ExecutionHandle(
                    execution_id=identifier,
                    workflow=existing[0],
                    version=existing[1],
                    status=ExecutionStatus(existing[4]),
                )
            await connection.execute(
                text(
                    "INSERT INTO executions (execution_id, workflow, version, fingerprint, status,"
                    " input, attempts, submitted_at, updated_at, deadline_at)"
                    " VALUES (:execution_id, :workflow, :version, :fingerprint, 'pending', :input,"
                    " 0, :now, :now, :deadline)"
                ),
                {
                    "execution_id": identifier,
                    "workflow": workflow.name,
                    "version": workflow.version,
                    "fingerprint": fingerprint,
                    "input": payload,
                    "now": to_iso(now),
                    "deadline": None if deadline is None else to_iso(deadline),
                },
            )
            for step in workflow.steps:
                await connection.execute(
                    text(
                        "INSERT INTO execution_steps (execution_id, step_id, state, attempts)"
                        " VALUES (:execution_id, :step_id, 'pending', 0)"
                    ),
                    {"execution_id": identifier, "step_id": step.id},
                )
            await self._append_event(
                connection,
                identifier,
                EventKind.SUBMITTED,
                at=now,
                detail=f"steps={len(workflow.steps)}"
                + ("" if submission_key is None else f" key={submission_key}"),
            )
            return ExecutionHandle(
                execution_id=identifier,
                workflow=workflow.name,
                version=workflow.version,
                status=ExecutionStatus.PENDING,
            )

        return await self._write(operation)

    # -- claims --------------------------------------------------------------------------

    async def claim_next(self, owner: str, *, ttl: float | None = None) -> Claim | None:
        """Claim the oldest eligible execution, or return ``None`` when there is no work.

        Eligibility is decided in SQL: the status must be claimable, an existing lease must have
        expired, any scheduled retry must be due, and the deadline must not have passed. An
        execution left ``running`` by a worker that stopped heartbeating is eligible too, which is
        what makes a crashed worker recoverable without an operator.

        The claim is a single conditional ``UPDATE`` that re-states every condition, so two workers
        racing for the same row cannot both win — even if one of them read the row before the other
        committed.
        """
        if not owner.strip():
            raise DurableStateError("a worker claims work under a non-empty owner name")
        now = self._now()
        expires = now + timedelta(seconds=self.lease_ttl if ttl is None else ttl)
        moment = to_iso(now)

        async def operation(connection: AsyncConnection) -> Claim | None:
            candidate = (
                await connection.execute(
                    text(
                        "SELECT e.execution_id FROM executions AS e"
                        " LEFT JOIN scheduled_retries AS r ON r.execution_id = e.execution_id"
                        " LEFT JOIN worker_leases AS l ON l.execution_id = e.execution_id"
                        " WHERE (e.cancellation_requested_at IS NULL OR e.status = 'running')"
                        " AND (e.deadline_at IS NULL OR e.deadline_at > :now)"
                        " AND ("
                        "   (e.status IN ('pending', 'retrying')"
                        "     AND (r.due_at IS NULL OR r.due_at <= :now))"
                        "   OR (e.status = 'running'"
                        "     AND (l.execution_id IS NULL OR l.expires_at <= :now))"
                        " )"
                        " ORDER BY e.submitted_at LIMIT 1"
                    ),
                    {"now": moment},
                )
            ).first()
            if candidate is None:
                return None
            execution_id = candidate[0]
            # A ready execution belongs to nobody: the previous owner finished its unit of work and
            # only a worker that is still `running` holds a lease that must be respected. The guard
            # re-states the eligibility conditions so the claim cannot depend on the read above.
            claimed = await connection.execute(
                text(
                    "UPDATE executions SET status = 'running', updated_at = :now"
                    " WHERE execution_id = :execution_id"
                    " AND status IN ('pending', 'retrying', 'running')"
                    " AND (cancellation_requested_at IS NULL OR status = 'running')"
                    " AND ("
                    "   status IN ('pending', 'retrying')"
                    "   OR NOT EXISTS ("
                    "     SELECT 1 FROM worker_leases"
                    "     WHERE execution_id = :execution_id AND expires_at > :now)"
                    " )"
                ),
                {"now": moment, "execution_id": execution_id},
            )
            if claimed.rowcount != 1:
                return None
            await connection.execute(
                text(
                    "INSERT INTO worker_leases"
                    " (execution_id, owner, fence, acquired_at, heartbeat_at, expires_at)"
                    " VALUES (:execution_id, :owner, 1, :now, :now, :expires)"
                    " ON CONFLICT (execution_id) DO UPDATE SET"
                    " owner = excluded.owner,"
                    " fence = worker_leases.fence + 1,"
                    " acquired_at = excluded.acquired_at,"
                    " heartbeat_at = excluded.heartbeat_at,"
                    " expires_at = excluded.expires_at"
                ),
                {
                    "execution_id": execution_id,
                    "owner": owner,
                    "now": to_iso(now),
                    "expires": to_iso(expires),
                },
            )
            lease = (
                await connection.execute(
                    text(
                        "SELECT fence, expires_at FROM worker_leases"
                        " WHERE execution_id = :execution_id"
                    ),
                    {"execution_id": execution_id},
                )
            ).first()
            await connection.execute(
                text("DELETE FROM scheduled_retries WHERE execution_id = :execution_id"),
                {"execution_id": execution_id},
            )
            row = await self._execution_row(connection, execution_id)
            if lease is None:  # pragma: no cover - the upsert above always leaves a row
                raise DurableLeaseError(
                    f"execution {execution_id} lost its lease during the claim",
                    execution_id=execution_id,
                )
            await self._append_event(
                connection,
                execution_id,
                EventKind.CLAIMED,
                at=now,
                detail=f"owner={owner} fence={lease[0]}",
            )
            return Claim(
                execution_id=execution_id,
                owner=owner,
                fence=lease[0],
                workflow=row["workflow"],
                version=row["version"],
                fingerprint=row["fingerprint"],
                input=_load(row["input"]),
                execution_status=ExecutionStatus(row["status"]),
                expires_at=from_iso(lease[1]),
                deadline_at=None if row["deadline_at"] is None else from_iso(row["deadline_at"]),
                cancellation_requested=row["cancellation_requested_at"] is not None,
            )

        return await self._write(operation)

    async def renew_lease(self, claim: Claim, *, ttl: float | None = None) -> Claim:
        """Extend the claim's lease, keeping its fencing token."""
        now = self._now()
        expires = now + timedelta(seconds=self.lease_ttl if ttl is None else ttl)

        async def operation(connection: AsyncConnection) -> Claim:
            result = await connection.execute(
                text(
                    "UPDATE worker_leases SET expires_at = :expires, heartbeat_at = :now"
                    " WHERE execution_id = :execution_id AND owner = :owner AND fence = :fence"
                    " AND expires_at > :now"
                ),
                {
                    "expires": to_iso(expires),
                    "now": to_iso(now),
                    "execution_id": claim.execution_id,
                    "owner": claim.owner,
                    "fence": claim.fence,
                },
            )
            if result.rowcount != 1:
                await self._explain_refused_write(
                    connection, claim, now=now, expected="lease renewal"
                )
            await self._append_event(
                connection, claim.execution_id, EventKind.LEASE_RENEWED, at=now
            )
            return Claim(
                execution_id=claim.execution_id,
                owner=claim.owner,
                fence=claim.fence,
                workflow=claim.workflow,
                version=claim.version,
                fingerprint=claim.fingerprint,
                input=claim.input,
                execution_status=claim.execution_status,
                expires_at=expires,
                deadline_at=claim.deadline_at,
                cancellation_requested=claim.cancellation_requested,
            )

        return await self._write(operation)

    async def release_lease(self, claim: Claim) -> None:
        """Give up the lease now so another worker can take over immediately."""
        now = self._now()

        async def operation(connection: AsyncConnection) -> None:
            result = await connection.execute(
                text(
                    "UPDATE worker_leases SET expires_at = :now"
                    " WHERE execution_id = :execution_id AND owner = :owner AND fence = :fence"
                    " AND expires_at > :now"
                ),
                {
                    "now": to_iso(now),
                    "execution_id": claim.execution_id,
                    "owner": claim.owner,
                    "fence": claim.fence,
                },
            )
            if result.rowcount != 1:
                await self._explain_refused_write(
                    connection, claim, now=now, expected="lease release"
                )

        await self._write(operation)

    async def expire_deadlines(self) -> tuple[str, ...]:
        """Mark executions whose deadline has passed as timed out; return their ids."""
        now = self._now()

        async def operation(connection: AsyncConnection) -> tuple[str, ...]:
            rows = (
                await connection.execute(
                    text(
                        "SELECT execution_id FROM executions"
                        " WHERE status NOT IN ('completed', 'failed', 'cancelled', 'timed_out')"
                        " AND deadline_at IS NOT NULL AND deadline_at <= :now"
                    ),
                    {"now": to_iso(now)},
                )
            ).fetchall()
            for (execution_id,) in rows:
                await connection.execute(
                    text(
                        "UPDATE executions SET status = 'timed_out', failure_kind = :kind,"
                        " failure_message = :message, current_step = NULL, updated_at = :now"
                        " WHERE execution_id = :execution_id"
                        " AND status NOT IN ('completed', 'failed', 'cancelled', 'timed_out')"
                    ),
                    {
                        "kind": FailureKind.TIMED_OUT.value,
                        "message": "the execution deadline passed before it completed",
                        "now": to_iso(now),
                        "execution_id": execution_id,
                    },
                )
                await connection.execute(
                    text("DELETE FROM scheduled_retries WHERE execution_id = :execution_id"),
                    {"execution_id": execution_id},
                )
                await self._append_event(
                    connection,
                    execution_id,
                    EventKind.TIMED_OUT,
                    at=now,
                    detail="the execution deadline passed before it completed",
                )
            return tuple(row[0] for row in rows)

        return await self._write(operation)

    # -- step transitions -----------------------------------------------------------------

    async def start_step(
        self, claim: Claim, step_id: str, *, idempotency_key: str | None = None
    ) -> int:
        """Record the start of one step attempt and return the attempt number."""
        now = self._now()

        async def operation(connection: AsyncConnection) -> int:
            row = await self._step_row(connection, claim.execution_id, step_id)
            attempt = int(row["attempts"]) + 1
            await self._set_step_state(
                connection,
                claim,
                step_id,
                StepState.RUNNING,
                now=now,
                extra=", attempts = :attempt, started_at = :now, finished_at = NULL,"
                " idempotency_key = :key",
                params={"attempt": attempt, "key": idempotency_key},
                allowed_sources=frozenset({StepState.PENDING, StepState.RUNNING}),
            )
            updated = await connection.execute(
                text(
                    "UPDATE executions SET current_step = :step_id, attempts = attempts + 1,"
                    " updated_at = :now WHERE execution_id = :execution_id"
                    f" AND {_LEASE_GUARD}"
                ),
                {
                    "step_id": step_id,
                    "now": to_iso(now),
                    "execution_id": claim.execution_id,
                    "owner": claim.owner,
                    "fence": claim.fence,
                },
            )
            if updated.rowcount != 1:
                await self._explain_refused_write(
                    connection, claim, now=now, expected=f"start of step {step_id!r}"
                )
            await self._append_event(
                connection,
                claim.execution_id,
                EventKind.STEP_STARTED,
                at=now,
                step_id=step_id,
                attempt=attempt,
            )
            return attempt

        return await self._write(operation)

    async def complete_step(self, claim: Claim, step_id: str, output: object) -> None:
        """Record a step's result.

        The execution stays ``RUNNING``: a worker that has finished one step still owns the
        execution and decides what happens next — another step, a terminal state, or a yield.
        """
        payload = _dump(
            output,
            limit=self._journal.settings.max_payload_bytes,
            what=f"output of step {step_id!r}",
        )
        now = self._now()

        async def operation(connection: AsyncConnection) -> None:
            row = await self._step_row(connection, claim.execution_id, step_id)
            await self._set_step_state(
                connection,
                claim,
                step_id,
                StepState.SUCCEEDED,
                now=now,
                extra=", output = :output, finished_at = :now, error_type = NULL,"
                " error_message = NULL, state_detail = NULL",
                params={"output": payload},
            )
            await connection.execute(
                text(
                    "UPDATE executions SET current_step = NULL, updated_at = :now"
                    " WHERE execution_id = :execution_id"
                    f" AND {_LEASE_GUARD}"
                ),
                {
                    "now": to_iso(now),
                    "execution_id": claim.execution_id,
                    "owner": claim.owner,
                    "fence": claim.fence,
                },
            )
            await self._append_event(
                connection,
                claim.execution_id,
                EventKind.STEP_SUCCEEDED,
                at=now,
                step_id=step_id,
                attempt=int(row["attempts"]) + 1,
            )

        await self._write(operation)

    async def yield_execution(
        self, claim: Claim, *, reason: str = "ready for the next step"
    ) -> None:
        """Return the execution to the ready queue without finishing it.

        Yielding is what makes a crash between steps cheap: the next worker re-derives the ready
        step from persisted state instead of trusting a scheduler's in-memory plan.
        """
        now = self._now()

        async def operation(connection: AsyncConnection) -> None:
            await self._set_execution_status(
                connection,
                claim,
                ExecutionStatus.PENDING,
                now=now,
                extra=", current_step = NULL",
            )
            await self._release_lease(connection, claim, now=now)
            await self._append_event(
                connection,
                claim.execution_id,
                EventKind.YIELDED,
                at=now,
                detail=reason,
            )

        await self._write(operation)

    async def skip_step(self, claim: Claim, step_id: str, *, reason: str) -> None:
        """Record that no branch reached a step."""
        now = self._now()

        async def operation(connection: AsyncConnection) -> None:
            await self._set_step_state(
                connection,
                claim,
                step_id,
                StepState.SKIPPED,
                now=now,
                extra=", finished_at = :now, state_detail = :reason",
                params={"reason": reason},
            )
            await self._append_event(
                connection,
                claim.execution_id,
                EventKind.STEP_SKIPPED,
                at=now,
                step_id=step_id,
                detail=reason,
            )

        await self._write(operation)

    async def fail_step(
        self,
        claim: Claim,
        step_id: str,
        *,
        error_type: str,
        error_message: str,
        retry_at: datetime | None,
        reason: str | None = None,
    ) -> StepState:
        """Record a failed attempt, scheduling a retry or failing the execution.

        A retry at or after the execution's deadline is never scheduled: the execution is timed out
        instead, because a retry nobody can run is not a retry.
        """
        now = self._now()
        deadline = claim.deadline_at
        passed = deadline is not None and (
            deadline <= now or (retry_at is not None and retry_at >= deadline)
        )
        if passed:
            return await self.time_out_execution(
                claim, message=f"step {step_id!r} failed with the deadline reached"
            )

        async def operation(connection: AsyncConnection) -> StepState:
            row = await self._step_row(connection, claim.execution_id, step_id)
            attempt = int(row["attempts"])
            if retry_at is None:
                await self._set_step_state(
                    connection,
                    claim,
                    step_id,
                    StepState.FAILED,
                    now=now,
                    extra=", finished_at = :now, error_type = :error_type,"
                    " error_message = :error_message, state_detail = :detail",
                    params={
                        "error_type": error_type,
                        "error_message": error_message,
                        "detail": reason,
                    },
                )
                await self._set_execution_status(
                    connection,
                    claim,
                    ExecutionStatus.FAILED,
                    now=now,
                    extra=", failure_kind = :kind, failure_message = :message, current_step = NULL",
                    params={
                        "kind": FailureKind.STEP_FAILED.value,
                        "message": f"step {step_id!r} failed: {error_type}",
                    },
                )
                await self._append_event(
                    connection,
                    claim.execution_id,
                    EventKind.STEP_FAILED,
                    at=now,
                    step_id=step_id,
                    attempt=attempt,
                    detail=error_type,
                )
                await self._append_event(
                    connection,
                    claim.execution_id,
                    EventKind.FAILED,
                    at=now,
                    step_id=step_id,
                    detail=f"step_failed: {error_type}",
                )
                return StepState.FAILED
            await self._set_step_state(
                connection,
                claim,
                step_id,
                StepState.PENDING,
                now=now,
                extra=", finished_at = :now, error_type = :error_type,"
                " error_message = :error_message, state_detail = :detail",
                params={
                    "error_type": error_type,
                    "error_message": error_message,
                    "detail": reason,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO scheduled_retries (execution_id, step_id, attempt, due_at,"
                    " error_type, reason) VALUES (:execution_id, :step_id, :attempt, :due_at,"
                    " :error_type, :reason)"
                    " ON CONFLICT (execution_id) DO UPDATE SET step_id = excluded.step_id,"
                    " attempt = excluded.attempt, due_at = excluded.due_at,"
                    " error_type = excluded.error_type, reason = excluded.reason"
                ),
                {
                    "execution_id": claim.execution_id,
                    "step_id": step_id,
                    "attempt": attempt + 1,
                    "due_at": to_iso(retry_at),
                    "error_type": error_type,
                    "reason": reason,
                },
            )
            await self._set_execution_status(
                connection,
                claim,
                ExecutionStatus.RETRYING,
                now=now,
                extra=", current_step = NULL",
            )
            await self._append_event(
                connection,
                claim.execution_id,
                EventKind.STEP_FAILED,
                at=now,
                step_id=step_id,
                attempt=attempt,
                detail=error_type,
            )
            await self._release_lease(connection, claim, now=now)
            await self._append_event(
                connection,
                claim.execution_id,
                EventKind.RETRY_SCHEDULED,
                at=now,
                step_id=step_id,
                attempt=attempt + 1,
                detail=f"due={to_iso(retry_at)}",
            )
            return StepState.PENDING

        return await self._write(operation)

    async def mark_step_outcome_unknown(self, claim: Claim, step_id: str, *, reason: str) -> None:
        """Record that an interrupted attempt's external effect cannot be proven either way."""
        now = self._now()

        async def operation(connection: AsyncConnection) -> None:
            row = await self._step_row(connection, claim.execution_id, step_id)
            await self._set_step_state(
                connection,
                claim,
                step_id,
                StepState.OUTCOME_UNKNOWN,
                now=now,
                extra=", state_detail = :reason",
                params={"reason": reason},
            )
            await self._set_execution_status(
                connection,
                claim,
                ExecutionStatus.WAITING,
                now=now,
                extra=", current_step = NULL",
            )
            await self._append_event(
                connection,
                claim.execution_id,
                EventKind.STEP_OUTCOME_UNKNOWN,
                at=now,
                step_id=step_id,
                attempt=int(row["attempts"]),
                detail=reason,
            )
            await self._append_event(
                connection,
                claim.execution_id,
                EventKind.WAITING,
                at=now,
                step_id=step_id,
                detail="outcome_unknown",
            )

        await self._write(operation)

    async def resolve_step(
        self,
        claim: Claim,
        step_id: str,
        *,
        state: StepState,
        output: object = None,
        detail: str | None = None,
    ) -> None:
        """Resolve a step whose outcome was unknown, after a retry or a reconciliation."""
        payload = None
        if state is StepState.SUCCEEDED:
            payload = _dump(
                output,
                limit=self._journal.settings.max_payload_bytes,
                what=f"output of step {step_id!r}",
            )
        now = self._now()

        async def operation(connection: AsyncConnection) -> None:
            await self._set_step_state(
                connection,
                claim,
                step_id,
                state,
                now=now,
                extra=", output = :output, finished_at = :now, state_detail = :detail",
                params={"output": payload, "detail": detail},
            )
            await self._set_execution_status(
                connection,
                claim,
                ExecutionStatus.PENDING,
                now=now,
                extra=", current_step = NULL",
            )
            await self._release_lease(connection, claim, now=now)
            await self._append_event(
                connection,
                claim.execution_id,
                EventKind.RECOVERED,
                at=now,
                step_id=step_id,
                detail=f"resolved {state.value}" + ("" if detail is None else f": {detail}"),
            )

        await self._write(operation)

    # -- terminal transitions --------------------------------------------------------------

    async def complete_execution(self, claim: Claim, outputs: object) -> None:
        """Record a completed execution and its result.

        Completion is refused once cancellation has been requested: the request is durable, and a
        worker that raced the operator does not get to overwrite it.
        """
        payload = _dump(
            outputs,
            limit=self._journal.settings.max_payload_bytes,
            what=f"result of execution {claim.execution_id}",
        )
        now = self._now()

        async def operation(connection: AsyncConnection) -> None:
            await self._set_execution_status(
                connection,
                claim,
                ExecutionStatus.COMPLETED,
                now=now,
                extra=", result = :result, current_step = NULL",
                params={"result": payload},
            )
            await self._append_event(connection, claim.execution_id, EventKind.COMPLETED, at=now)

        await self._write(operation)

    async def fail_execution(self, claim: Claim, *, kind: FailureKind, message: str) -> None:
        """Record a terminal failure that is not a step failure."""
        now = self._now()

        async def operation(connection: AsyncConnection) -> None:
            await self._set_execution_status(
                connection,
                claim,
                ExecutionStatus.FAILED,
                now=now,
                extra=", failure_kind = :kind, failure_message = :message, current_step = NULL",
                params={"kind": kind.value, "message": message},
            )
            await self._append_event(
                connection,
                claim.execution_id,
                EventKind.FAILED,
                at=now,
                detail=f"{kind.value}: {message}",
            )

        await self._write(operation)

    async def time_out_execution(self, claim: Claim, *, message: str) -> StepState:
        """Record a timed-out execution."""
        now = self._now()

        async def operation(connection: AsyncConnection) -> StepState:
            await self._set_execution_status(
                connection,
                claim,
                ExecutionStatus.TIMED_OUT,
                now=now,
                extra=", failure_kind = :kind, failure_message = :message, current_step = NULL",
                params={"kind": FailureKind.TIMED_OUT.value, "message": message},
            )
            await self._append_event(
                connection,
                claim.execution_id,
                EventKind.TIMED_OUT,
                at=now,
                detail=message,
            )
            return StepState.FAILED

        return await self._write(operation)

    async def request_cancellation(
        self, execution_id: str, *, reason: str | None = None
    ) -> ExecutionView:
        """Persist a cancellation request, recording it directly when nobody owns the execution.

        A request is durable before it is acted on: the owner sees it at its next checkpoint, and a
        worker that is no longer the owner cannot complete the execution afterwards.
        """
        now = self._now()

        async def operation(connection: AsyncConnection) -> None:
            row = await self._execution_row(connection, execution_id)
            status = ExecutionStatus(row["status"])
            if execution_is_terminal(status):
                return
            if row["cancellation_requested_at"] is None:
                await connection.execute(
                    text(
                        "UPDATE executions SET cancellation_requested_at = :now,"
                        " cancellation_reason = :reason, updated_at = :now"
                        " WHERE execution_id = :execution_id AND status = :status"
                    ),
                    {
                        "now": to_iso(now),
                        "reason": reason,
                        "execution_id": execution_id,
                        "status": status.value,
                    },
                )
                await self._append_event(
                    connection,
                    execution_id,
                    EventKind.CANCELLATION_REQUESTED,
                    at=now,
                    detail=reason,
                )
            lease = (
                await connection.execute(
                    text("SELECT expires_at FROM worker_leases WHERE execution_id = :execution_id"),
                    {"execution_id": execution_id},
                )
            ).first()
            if lease is not None and lease[0] > to_iso(now):
                return
            await self._finish_cancelled(connection, execution_id, now=now, reason=reason)

        await self._write(operation)
        return await self.inspect(execution_id)

    async def _finish_cancelled(
        self,
        connection: AsyncConnection,
        execution_id: str,
        *,
        now: datetime,
        reason: str | None,
    ) -> None:
        row = await self._execution_row(connection, execution_id)
        status = ExecutionStatus(row["status"])
        if execution_is_terminal(status):
            return
        require_execution_transition(status, ExecutionStatus.CANCELLED)
        await connection.execute(
            text(
                "UPDATE executions SET status = 'cancelled', failure_kind = :kind,"
                " failure_message = :message, current_step = NULL, updated_at = :now,"
                " cancellation_requested_at = COALESCE(cancellation_requested_at, :now)"
                " WHERE execution_id = :execution_id AND status = :status"
            ),
            {
                "kind": FailureKind.CANCELLED.value,
                "message": reason or "cancellation was requested",
                "now": to_iso(now),
                "execution_id": execution_id,
                "status": status.value,
            },
        )
        await connection.execute(
            text("DELETE FROM scheduled_retries WHERE execution_id = :execution_id"),
            {"execution_id": execution_id},
        )
        await self._append_event(
            connection,
            execution_id,
            EventKind.CANCELLED,
            at=now,
            detail=reason,
        )

    async def acknowledge_cancellation(self, claim: Claim, *, reason: str | None = None) -> None:
        """Record cancellation from the worker that holds the lease."""
        now = self._now()

        async def operation(connection: AsyncConnection) -> None:
            cancellation = (
                await connection.execute(
                    text(
                        "SELECT cancellation_requested_at FROM executions"
                        " WHERE execution_id = :execution_id"
                    ),
                    {"execution_id": claim.execution_id},
                )
            ).first()
            if cancellation is None:
                raise DurableStateError(
                    f"execution {claim.execution_id} is no longer in the journal"
                )
            if cancellation[0] is None:
                await connection.execute(
                    text(
                        "UPDATE executions SET cancellation_requested_at = :now,"
                        " cancellation_reason = :reason WHERE execution_id = :execution_id"
                    ),
                    {
                        "now": to_iso(now),
                        "reason": reason,
                        "execution_id": claim.execution_id,
                    },
                )
                await self._append_event(
                    connection,
                    claim.execution_id,
                    EventKind.CANCELLATION_REQUESTED,
                    at=now,
                    detail=reason,
                )
            await self._set_execution_status(
                connection,
                claim,
                ExecutionStatus.CANCELLED,
                now=now,
                extra=", failure_kind = :kind, failure_message = :message, current_step = NULL",
                params={
                    "kind": FailureKind.CANCELLED.value,
                    "message": reason or "cancellation was requested",
                },
                allow_cancelled=True,
            )
            await connection.execute(
                text("DELETE FROM scheduled_retries WHERE execution_id = :execution_id"),
                {"execution_id": claim.execution_id},
            )
            await self._append_event(
                connection,
                claim.execution_id,
                EventKind.CANCELLED,
                at=now,
                detail=reason,
            )

        await self._write(operation)

    async def mark_waiting(self, claim: Claim, *, reason: str) -> None:
        """Park an execution until something outside the worker acts."""
        now = self._now()

        async def operation(connection: AsyncConnection) -> None:
            await self._set_execution_status(
                connection,
                claim,
                ExecutionStatus.WAITING,
                now=now,
                extra=", current_step = NULL",
            )
            await self._append_event(
                connection,
                claim.execution_id,
                EventKind.WAITING,
                at=now,
                detail=reason,
            )

        await self._write(operation)

    async def resume_waiting(self, execution_id: str, *, reason: str | None = None) -> None:
        """Return a parked execution to the ready queue."""
        now = self._now()

        async def operation(connection: AsyncConnection) -> None:
            row = await self._execution_row(connection, execution_id)
            status = ExecutionStatus(row["status"])
            if status is not ExecutionStatus.WAITING:
                raise DurableStateError(
                    f"execution {execution_id} is {status.value!r}, not waiting; "
                    "only a parked execution can be resumed"
                )
            await connection.execute(
                text(
                    "UPDATE executions SET status = 'pending', updated_at = :now"
                    " WHERE execution_id = :execution_id AND status = 'waiting'"
                ),
                {"now": to_iso(now), "execution_id": execution_id},
            )
            await self._append_event(
                connection,
                execution_id,
                EventKind.RECOVERED,
                at=now,
                detail=f"resumed: {reason}" if reason else "resumed",
            )

        await self._write(operation)

    # -- inspection -------------------------------------------------------------------------

    async def step_states(self, execution_id: str) -> dict[str, StepState]:
        """Return each step's persisted state, for scheduling decisions."""

        async def operation(connection: AsyncConnection) -> dict[str, StepState]:
            rows = (
                await connection.execute(
                    text(
                        "SELECT step_id, state FROM execution_steps"
                        " WHERE execution_id = :execution_id"
                    ),
                    {"execution_id": execution_id},
                )
            ).fetchall()
            return {row[0]: StepState(row[1]) for row in rows}

        return await self._read(operation)

    async def running_steps(self, execution_id: str) -> tuple[str, ...]:
        """Return the steps an interrupted worker left mid-attempt.

        A step is here only if a worker stopped between recording its start and recording its
        result, which is exactly the case where nobody can say whether the effect happened.
        """

        async def operation(connection: AsyncConnection) -> tuple[str, ...]:
            rows = (
                await connection.execute(
                    text(
                        "SELECT step_id FROM execution_steps"
                        " WHERE execution_id = :execution_id AND state = 'running'"
                        " ORDER BY rowid"
                    ),
                    {"execution_id": execution_id},
                )
            ).fetchall()
            return tuple(row[0] for row in rows)

        return await self._read(operation)

    async def completed_outputs(self, execution_id: str) -> dict[str, object]:
        """Return the persisted output of every succeeded step, for branch predicates."""

        async def operation(connection: AsyncConnection) -> dict[str, object]:
            rows = (
                await connection.execute(
                    text(
                        "SELECT step_id, output FROM execution_steps"
                        " WHERE execution_id = :execution_id AND state = 'succeeded'"
                        " ORDER BY rowid"
                    ),
                    {"execution_id": execution_id},
                )
            ).fetchall()
            return {row[0]: _load(row[1]) for row in rows}

        return await self._read(operation)

    async def cancellation_requested(self, execution_id: str) -> bool:
        """Whether a cancellation request is persisted for this execution."""

        async def operation(connection: AsyncConnection) -> bool:
            row = (
                await connection.execute(
                    text(
                        "SELECT cancellation_requested_at FROM executions"
                        " WHERE execution_id = :execution_id"
                    ),
                    {"execution_id": execution_id},
                )
            ).first()
            if row is None:
                raise DurableStateError(f"execution {execution_id} is no longer in the journal")
            return row[0] is not None

        return await self._read(operation)

    async def step_output(self, execution_id: str, step_id: str) -> object:
        """Return the persisted output of one step."""

        async def operation(connection: AsyncConnection) -> object:
            row = await self._step_row(connection, execution_id, step_id)
            return _load(row["output"])

        return await self._read(operation)

    async def inspect(self, execution_id: str) -> ExecutionView:
        """Return a read-only view of one execution, its steps, and its timeline."""

        async def operation(connection: AsyncConnection) -> ExecutionView:
            row = await self._execution_row(connection, execution_id)
            steps = (
                (
                    await connection.execute(
                        text(
                            "SELECT step_id, state, attempts, output, error_type, error_message,"
                            " state_detail, started_at, finished_at, idempotency_key"
                            " FROM execution_steps"
                            " WHERE execution_id = :execution_id ORDER BY rowid"
                        ),
                        {"execution_id": execution_id},
                    )
                )
                .mappings()
                .all()
            )
            events = (
                (
                    await connection.execute(
                        text(
                            "SELECT event_id, kind, at, step_id, attempt, detail"
                            " FROM execution_events"
                            " WHERE execution_id = :execution_id ORDER BY event_id"
                        ),
                        {"execution_id": execution_id},
                    )
                )
                .mappings()
                .all()
            )
            retry = (
                await connection.execute(
                    text("SELECT due_at FROM scheduled_retries WHERE execution_id = :execution_id"),
                    {"execution_id": execution_id},
                )
            ).first()
            return ExecutionView(
                execution_id=row["execution_id"],
                workflow=row["workflow"],
                version=row["version"],
                fingerprint=row["fingerprint"],
                status=ExecutionStatus(row["status"]),
                input=_load(row["input"]),
                submitted_at=from_iso(row["submitted_at"]),
                updated_at=from_iso(row["updated_at"]),
                deadline_at=None if row["deadline_at"] is None else from_iso(row["deadline_at"]),
                current_step=row["current_step"],
                result=_load(row["result"]),
                failure_kind=(
                    None if row["failure_kind"] is None else FailureKind(row["failure_kind"])
                ),
                failure_message=row["failure_message"],
                cancellation_requested_at=(
                    None
                    if row["cancellation_requested_at"] is None
                    else from_iso(row["cancellation_requested_at"])
                ),
                steps=tuple(
                    StepView(
                        step_id=step["step_id"],
                        state=StepState(step["state"]),
                        attempts=int(step["attempts"]),
                        output=_load(step["output"]),
                        error_type=step["error_type"],
                        error_message=step["error_message"],
                        state_detail=step["state_detail"],
                        started_at=(
                            None if step["started_at"] is None else from_iso(step["started_at"])
                        ),
                        finished_at=(
                            None if step["finished_at"] is None else from_iso(step["finished_at"])
                        ),
                        idempotency_key=step["idempotency_key"],
                    )
                    for step in steps
                ),
                events=tuple(
                    EventView(
                        sequence=int(event["event_id"]),
                        kind=EventKind(event["kind"]),
                        at=from_iso(event["at"]),
                        step_id=event["step_id"],
                        attempt=event["attempt"],
                        detail=event["detail"],
                    )
                    for event in events
                ),
                retry_due_at=None if retry is None else from_iso(retry[0]),
            )

        return await self._read(operation)

    async def list_executions(
        self, *, status: ExecutionStatus | None = None, limit: int = 50
    ) -> tuple[ExecutionView, ...]:
        """List executions, newest first, optionally filtered by status."""
        if limit <= 0:
            raise DurableStateError("limit must be greater than zero")

        async def operation(connection: AsyncConnection) -> tuple[str, ...]:
            statement = "SELECT execution_id FROM executions"
            params: dict[str, object] = {"limit": limit}
            if status is not None:
                statement += " WHERE status = :status"
                params["status"] = status.value
            statement += " ORDER BY submitted_at DESC, execution_id DESC LIMIT :limit"
            rows = (await connection.execute(text(statement), params)).fetchall()
            return tuple(row[0] for row in rows)

        identifiers = await self._read(operation)
        return tuple([await self.inspect(identifier) for identifier in identifiers])

    async def expired_leases(self) -> tuple[str, ...]:
        """Return executions whose owner stopped heartbeating before finishing."""
        now = to_iso(self._now())

        async def operation(connection: AsyncConnection) -> tuple[str, ...]:
            rows = (
                await connection.execute(
                    text(
                        "SELECT l.execution_id FROM worker_leases AS l"
                        " JOIN executions AS e ON e.execution_id = l.execution_id"
                        " WHERE l.expires_at <= :now"
                        " AND e.status NOT IN ('completed', 'failed', 'cancelled', 'timed_out')"
                        " ORDER BY l.expires_at"
                    ),
                    {"now": now},
                )
            ).fetchall()
            return tuple(row[0] for row in rows)

        return await self._read(operation)

    async def stats(self) -> JournalStats:
        """Return queue, lease, and failure counters for diagnostics."""
        now = self._now()

        async def operation(connection: AsyncConnection) -> JournalStats:
            counts = {
                row[0]: int(row[1])
                for row in (
                    await connection.execute(
                        text("SELECT status, COUNT(*) FROM executions GROUP BY status")
                    )
                ).fetchall()
            }
            expired = (
                await connection.execute(
                    text(
                        "SELECT COUNT(*) FROM worker_leases AS l"
                        " JOIN executions AS e ON e.execution_id = l.execution_id"
                        " WHERE l.expires_at <= :now"
                        " AND e.status NOT IN ('completed', 'failed', 'cancelled', 'timed_out')"
                    ),
                    {"now": to_iso(now)},
                )
            ).scalar_one()
            incompatible = (
                await connection.execute(
                    text("SELECT COUNT(*) FROM executions WHERE failure_kind = :kind"),
                    {"kind": FailureKind.INCOMPATIBLE_DEFINITION.value},
                )
            ).scalar_one()
            oldest = (
                await connection.execute(
                    text(
                        "SELECT MIN(l.acquired_at) FROM worker_leases AS l"
                        " JOIN executions AS e ON e.execution_id = l.execution_id"
                        " WHERE e.status = 'running'"
                    )
                )
            ).scalar_one()
            return JournalStats(
                queued=counts.get(ExecutionStatus.PENDING.value, 0),
                running=counts.get(ExecutionStatus.RUNNING.value, 0),
                retrying=counts.get(ExecutionStatus.RETRYING.value, 0),
                waiting=counts.get(ExecutionStatus.WAITING.value, 0),
                completed=counts.get(ExecutionStatus.COMPLETED.value, 0),
                failed=counts.get(ExecutionStatus.FAILED.value, 0),
                cancelled=counts.get(ExecutionStatus.CANCELLED.value, 0),
                timed_out=counts.get(ExecutionStatus.TIMED_OUT.value, 0),
                expired_leases=int(expired),
                incompatible=int(incompatible),
                oldest_lease_age_seconds=(
                    None if oldest is None else max((now - from_iso(oldest)).total_seconds(), 0.0)
                ),
                detail={"paths": str(self._journal.path)},
            )

        return await self._read(operation)

    def activity_policy(
        self, policies: Mapping[str, ActivityPolicy], step_id: str
    ) -> ActivityPolicy:
        """Return the declared policy for a step, defaulting to the safe one.

        The default is deliberately *not* "retry": a step that says nothing about its side effects
        is treated as unsafe to repeat.
        """
        return policies.get(step_id, ActivityPolicy())
