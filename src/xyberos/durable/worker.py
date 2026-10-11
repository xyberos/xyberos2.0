"""The single worker loop: claim, advance one step, commit, and let go.

The worker is deliberately small in what it promises. It holds a lease, runs at most one step, and
commits the outcome under its fencing token; whether the work continues is decided by the journal,
not by anything this process remembers. That is what makes a crash cheap: the next claim re-derives
what to do from the definition and the persisted step states.

While a step runs, a heartbeat task renews the lease and watches for a cancellation request, so a
long step neither loses its lease to a healthier worker nor ignores a request to stop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from logging import Logger, getLogger
from random import Random
from uuid import uuid4

from xyberos.durable.contracts import SystemWallClock, WallClock
from xyberos.durable.definitions import DefinitionLookup, require_definition
from xyberos.durable.models import (
    ActivityPolicy,
    Claim,
    ExecutionStatus,
    FailureKind,
    StepState,
)
from xyberos.durable.recovery import RecoveryReport, recover, resolve_interrupted_attempt
from xyberos.durable.scheduler import Plan, PlanKind, plan_next
from xyberos.durable.store import JournalStore
from xyberos.errors import (
    DurableLeaseError,
    DurableStateError,
    DurableVersionError,
    StepTimeoutError,
    WorkflowCancelledError,
    WorkflowTimeoutError,
)
from xyberos.execution.models import Step, Workflow
from xyberos.execution.policies import CancellationToken, Clock, StepContext, SystemClock
from xyberos.runtime.context import create_task_in_context

DEFAULT_LOGGER_NAME = "xyberos.durable"


@dataclass(frozen=True)
class WorkerSettings:
    """How one worker behaves: its identity, its lease, and how it waits for work."""

    owner: str | None = None
    lease_ttl: float | None = None
    heartbeat_seconds: float | None = None
    poll_interval: float = 0.05
    max_poll_interval: float = 1.0
    poll_backoff: float = 2.0

    def __post_init__(self) -> None:
        for name in ("poll_interval", "max_poll_interval", "poll_backoff"):
            if getattr(self, name) <= 0:
                raise DurableStateError(f"{name} must be greater than zero")
        if self.owner is not None and not self.owner.strip():
            raise DurableStateError("a worker name must not be blank")
        if self.lease_ttl is not None and self.lease_ttl <= 0:
            raise DurableStateError("lease_ttl must be greater than zero")
        if self.heartbeat_seconds is not None and self.heartbeat_seconds <= 0:
            raise DurableStateError("heartbeat_seconds must be greater than zero")


@dataclass(frozen=True)
class WorkOutcome:
    """What one claim accomplished."""

    execution_id: str
    action: str
    step_id: str | None = None
    attempt: int | None = None
    detail: str = ""


class DurableWorker:
    """Claims durable executions and advances them one step at a time."""

    def __init__(
        self,
        store: JournalStore,
        definitions: DefinitionLookup,
        *,
        activities: Mapping[str, ActivityPolicy] | None = None,
        settings: WorkerSettings | None = None,
        clock: WallClock | None = None,
        step_clock: Clock | None = None,
        random: Random | None = None,
        logger: Logger | None = None,
    ) -> None:
        from xyberos.durable import warn_experimental

        warn_experimental("xyberos.durable")
        self._store = store
        self._definitions = definitions
        self._activities = dict(activities or {})
        self._settings = settings or WorkerSettings()
        self._clock: WallClock = clock if clock is not None else SystemWallClock()
        self._step_clock: Clock = step_clock if step_clock is not None else SystemClock()
        self._random = random if random is not None else Random()
        self._logger = logger or getLogger(DEFAULT_LOGGER_NAME)
        self._owner = self._settings.owner or f"worker-{uuid4().hex[:12]}"

    @property
    def owner(self) -> str:
        """This worker's identity in the journal."""
        return self._owner

    @property
    def lease_ttl(self) -> float:
        """The lease lifetime this worker claims and renews."""
        return self._settings.lease_ttl or self._store.lease_ttl

    @property
    def heartbeat_seconds(self) -> float:
        """How often the lease is renewed while a step runs."""
        configured = self._settings.heartbeat_seconds
        return configured if configured is not None else max(self.lease_ttl / 3.0, 0.01)

    async def recover(self) -> RecoveryReport:
        """Run the startup recovery pass over executions whose lease expired."""
        return await recover(
            self._store,
            definitions=self._definitions,
            activities=self._activities,
            owner=f"{self._owner}:recovery",
            ttl=self.lease_ttl,
        )

    async def run_once(self) -> WorkOutcome | None:
        """Claim one execution and advance it by one step.

        ``None`` means there was nothing to claim. Every other answer names what happened, so a
        caller (or a test) can drive the worker deterministically without a loop.
        """
        claim = await self._store.claim_next(self._owner, ttl=self.lease_ttl)
        if claim is None:
            return None
        if claim.cancellation_requested:
            await self._store.acknowledge_cancellation(
                claim, reason="cancellation was requested before this worker started the step"
            )
            return WorkOutcome(claim.execution_id, "cancelled", detail="requested before the step")
        try:
            workflow = require_definition(self._definitions, claim)
        except DurableVersionError as error:
            await self._store.fail_execution(
                claim, kind=FailureKind.INCOMPATIBLE_DEFINITION, message=str(error)
            )
            return WorkOutcome(claim.execution_id, "failed", detail="incompatible definition")
        if self._deadline_passed(claim):
            await self._store.time_out_execution(
                claim, message="the execution deadline passed before the step started"
            )
            return WorkOutcome(claim.execution_id, "timed_out", detail="deadline passed")
        states = await self._store.step_states(claim.execution_id)
        outputs = await self._store.completed_outputs(claim.execution_id)
        interrupted = await self._store.running_steps(claim.execution_id)
        if interrupted:
            outcomes = []
            plan = plan_next(workflow, states, outputs)
            for step_id in interrupted:
                outcomes.append(
                    await resolve_interrupted_attempt(
                        self._store,
                        claim,
                        activities=self._activities,
                        step_id=step_id,
                        step_input=self._input_for(plan, step_id, claim),
                    )
                )
            if StepState.OUTCOME_UNKNOWN in outcomes:
                return WorkOutcome(
                    claim.execution_id,
                    "parked",
                    step_id=interrupted[0],
                    detail="outcome_unknown",
                )
            states = await self._store.step_states(claim.execution_id)
        # At most one step runs per claim, but skips cost nothing external, so they are applied
        # here until something has to run.
        for _ in range(len(workflow.steps) + 1):
            plan = plan_next(workflow, states, outputs)
            if plan.kind is PlanKind.COMPLETE:
                await self._store.complete_execution(claim, plan.outputs)
                return WorkOutcome(claim.execution_id, "completed", detail=plan.reason)
            if plan.kind is PlanKind.CONFLICT:
                await self._store.fail_execution(
                    claim, kind=FailureKind.DEFINITION_CONFLICT, message=plan.reason
                )
                return WorkOutcome(
                    claim.execution_id,
                    "failed",
                    step_id=plan.step.id if plan.step else None,
                    detail="definition conflict",
                )
            if plan.kind is PlanKind.NEEDS_DECISION:
                await self._store.mark_waiting(claim, reason=plan.reason)
                return WorkOutcome(
                    claim.execution_id,
                    "parked",
                    step_id=plan.step.id if plan.step else None,
                    detail="needs_decision",
                )
            step = plan.step
            if step is None:  # pragma: no cover - a plan always names a step
                raise DurableStateError("a scheduling plan named no step")
            if plan.kind is PlanKind.SKIP_STEP:
                await self._store.skip_step(claim, step.id, reason=plan.reason)
                states[step.id] = StepState.SKIPPED
                continue
            value = claim.input if not plan.sources else plan.value
            return await self._run_step(claim, workflow, step.id, value)
        raise DurableStateError(  # pragma: no cover - the loop is bounded by the step count
            f"execution {claim.execution_id} made no progress"
        )

    async def serve(
        self,
        *,
        stop: asyncio.Event | None = None,
        max_iterations: int | None = None,
        recover_first: bool = True,
    ) -> int:
        """Work until ``stop`` is set (or ``max_iterations`` claims have been attempted).

        An idle worker backs off up to ``max_poll_interval`` instead of spinning on the journal.
        """
        if recover_first:
            await self.recover()
        halt = stop if stop is not None else asyncio.Event()
        delay = self._settings.poll_interval
        iterations = 0
        while not halt.is_set():
            outcome = await self.run_once()
            if outcome is None:
                try:
                    await asyncio.wait_for(halt.wait(), timeout=delay)
                    return iterations
                except asyncio.TimeoutError:
                    delay = min(
                        delay * self._settings.poll_backoff, self._settings.max_poll_interval
                    )
                continue
            delay = self._settings.poll_interval
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                return iterations
        return iterations

    async def _run_step(
        self, claim: Claim, workflow: Workflow, step_id: str, value: object
    ) -> WorkOutcome:
        """Run one step attempt and commit what happened."""
        step = workflow.step_by_id(step_id)
        idempotency_key = f"{claim.execution_id}:{step.id}"
        attempt = await self._store.start_step(claim, step.id, idempotency_key=idempotency_key)
        token = CancellationToken()
        budget = self._attempt_budget(claim, step.timeout)
        if budget is not None and budget <= 0:
            await self._store.time_out_execution(
                claim, message=f"step {step.id!r} started with no time left"
            )
            return WorkOutcome(claim.execution_id, "timed_out", step_id=step.id, attempt=attempt)
        context = StepContext(
            workflow=workflow.name,
            version=workflow.version,
            step=step.id,
            attempt=attempt,
            cancellation=token,
            clock=self._step_clock,
            deadline=None if budget is None else self._step_clock.monotonic() + budget,
            logger=self._logger,
        )
        heartbeat = create_task_in_context(self._watch(claim, token))
        try:
            output = await asyncio.wait_for(step.run(value, context), timeout=budget)
        except asyncio.TimeoutError:
            timeout_error = StepTimeoutError(
                f"step {step.id!r} exceeded its {budget}s budget",
                workflow=workflow.name,
                step=step.id,
            )
            return await self._record_failure(
                claim, step, attempt, timeout_error, retry_at=None, detail="step timeout"
            )
        except WorkflowCancelledError as error:
            await self._store.acknowledge_cancellation(claim, reason=str(error))
            return WorkOutcome(
                claim.execution_id, "cancelled", step_id=step.id, attempt=attempt, detail=str(error)
            )
        except WorkflowTimeoutError as error:
            await self._store.time_out_execution(claim, message=str(error))
            return WorkOutcome(
                claim.execution_id, "timed_out", step_id=step.id, attempt=attempt, detail=str(error)
            )
        except Exception as error:  # noqa: BLE001 - every step failure is classified, not swallowed
            retry_at = self._retry_at(claim, step, attempt, error)
            return await self._record_failure(
                claim, step, attempt, error, retry_at=retry_at, detail=type(error).__name__
            )
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
        await self._store.complete_step(claim, step.id, output)
        return await self._after_step(claim, workflow, step.id, attempt)

    async def _record_failure(
        self,
        claim: Claim,
        step: Step,
        attempt: int,
        error: BaseException,
        *,
        retry_at: datetime | None,
        detail: str,
    ) -> WorkOutcome:
        state = await self._store.fail_step(
            claim,
            step.id,
            error_type=type(error).__name__,
            error_message=str(error),
            retry_at=retry_at,
            reason=detail,
        )
        view = await self._store.inspect(claim.execution_id)
        if view.status is ExecutionStatus.TIMED_OUT:
            return WorkOutcome(claim.execution_id, "timed_out", step_id=step.id, attempt=attempt)
        if state is StepState.PENDING:
            return WorkOutcome(
                claim.execution_id,
                "retry_scheduled",
                step_id=step.id,
                attempt=attempt,
                detail=detail,
            )
        return WorkOutcome(
            claim.execution_id, "failed", step_id=step.id, attempt=attempt, detail=detail
        )

    async def _after_step(
        self, claim: Claim, workflow: Workflow, step_id: str, attempt: int
    ) -> WorkOutcome:
        """Complete the run or yield it, depending on what the journal says is left."""
        states = await self._store.step_states(claim.execution_id)
        outputs = await self._store.completed_outputs(claim.execution_id)
        plan = plan_next(workflow, states, outputs)
        if plan.kind is PlanKind.COMPLETE:
            await self._store.complete_execution(claim, plan.outputs)
            return WorkOutcome(
                claim.execution_id,
                "completed",
                step_id=step_id,
                attempt=attempt,
                detail=plan.reason,
            )
        if plan.kind is PlanKind.CONFLICT:
            await self._store.fail_execution(
                claim, kind=FailureKind.DEFINITION_CONFLICT, message=plan.reason
            )
            return WorkOutcome(
                claim.execution_id, "failed", step_id=step_id, attempt=attempt, detail="conflict"
            )
        await self._store.yield_execution(
            claim, reason=f"step {step_id!r} recorded; ready for the next step"
        )
        return WorkOutcome(
            claim.execution_id, "ran_step", step_id=step_id, attempt=attempt, detail="yielded"
        )

    async def _watch(self, claim: Claim, token: CancellationToken) -> None:
        """Renew the lease and watch for a cancellation request while a step runs."""
        while True:
            await self._clock.sleep(self.heartbeat_seconds)
            try:
                if await self._store.cancellation_requested(claim.execution_id):
                    token.cancel("cancellation was requested while the step was running")
                    return
                await self._store.renew_lease(claim, ttl=self.lease_ttl)
            except DurableLeaseError:
                token.cancel("the lease was lost while the step was running")
                return

    def _attempt_budget(self, claim: Claim, step_timeout: float | None) -> float | None:
        """Return the seconds this attempt may take, from the step and the run deadline."""
        budget = step_timeout
        if claim.deadline_at is not None:
            remaining = (claim.deadline_at - self._clock.now()).total_seconds()
            budget = remaining if budget is None else min(budget, remaining)
        return budget

    def _deadline_passed(self, claim: Claim) -> bool:
        return claim.deadline_at is not None and claim.deadline_at <= self._clock.now()

    def _retry_at(
        self, claim: Claim, step: Step, attempt: int, error: BaseException
    ) -> datetime | None:
        """Return when the next attempt may run, or ``None`` when it must not be retried."""
        policy = step.retry
        if policy is None or attempt >= policy.max_attempts or not policy.allows(error):
            return None
        delay = policy.backoff.delay_for(attempt, random=self._random)
        return self._clock.now() + timedelta(seconds=delay)

    def _input_for(self, plan: Plan, step_id: str, claim: Claim) -> object:
        if plan.kind is PlanKind.RUN_STEP and plan.step is not None and plan.step.id == step_id:
            return claim.input if not plan.sources else plan.value
        return claim.input
