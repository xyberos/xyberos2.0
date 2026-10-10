"""Startup recovery: decide what an interrupted attempt means, and record the decision.

Recovery never guesses. When a worker's lease expired with a step still ``RUNNING``, exactly three
honest answers exist, and each one is a declaration the caller makes in advance:

* the step is **idempotent** — running it again is harmless, so the step returns to ``PENDING``;
* the step has a **reconciler** — something outside can be asked what happened, and the answer
  decides the step's state;
* neither — the attempt's outcome is **unknown**, the step is recorded as ``OUTCOME_UNKNOWN``, and
  the execution is parked in ``WAITING`` until a person or a policy resolves it.

Every decision becomes a journal event, so an operator can reconstruct why an execution resumed,
retried, or stopped.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from xyberos.durable.definitions import DefinitionLookup, require_definition
from xyberos.durable.models import ActivityPolicy, Claim, FailureKind, Reconciliation, StepState
from xyberos.durable.scheduler import Plan, PlanKind, plan_next
from xyberos.durable.store import JournalStore
from xyberos.errors import DurableStateError, DurableVersionError


@dataclass(frozen=True)
class RecoveryReport:
    """What a recovery pass found and decided."""

    expired: tuple[str, ...] = ()
    resumed: tuple[str, ...] = ()
    parked: tuple[str, ...] = ()
    stopped: tuple[str, ...] = ()
    decisions: Mapping[str, str] = field(default_factory=dict)

    @property
    def examined(self) -> int:
        """How many interrupted executions were examined."""
        return len(self.expired)


async def resolve_interrupted_attempt(
    store: JournalStore,
    claim: Claim,
    *,
    activities: Mapping[str, ActivityPolicy],
    step_id: str,
    step_input: object,
) -> StepState:
    """Decide what an interrupted attempt means and record it.

    Returns the state the step ended up in. A step that cannot be decided is parked and reported as
    ``OUTCOME_UNKNOWN``; that is a decision too, and the only one that cannot repeat a side effect
    nobody can observe.
    """
    policy = activities.get(step_id, ActivityPolicy())
    if policy.idempotent:
        await store.resolve_step(
            claim,
            step_id,
            state=StepState.PENDING,
            detail="idempotent: the attempt is repeated",
        )
        return StepState.PENDING
    if policy.reconcile is not None:
        decision = policy.reconcile(step_id, step_input)
        if not isinstance(decision, Reconciliation):
            raise DurableStateError(
                f"the reconciler for step {step_id!r} returned "
                f"{type(decision).__name__} instead of a Reconciliation"
            )
        if decision.state is StepState.OUTCOME_UNKNOWN:
            await store.mark_step_outcome_unknown(
                claim,
                step_id,
                reason=decision.detail or "the reconciler could not decide what happened",
            )
            return StepState.OUTCOME_UNKNOWN
        await store.resolve_step(
            claim,
            step_id,
            state=decision.state,
            output=decision.output,
            detail=decision.detail or "reconciled",
        )
        return decision.state
    await store.mark_step_outcome_unknown(
        claim,
        step_id,
        reason=(
            "the worker stopped during this attempt and the step declares neither idempotency nor "
            "a reconciler, so whether its effect happened cannot be proven"
        ),
    )
    return StepState.OUTCOME_UNKNOWN


async def recover(
    store: JournalStore,
    *,
    definitions: DefinitionLookup,
    activities: Mapping[str, ActivityPolicy] | None = None,
    owner: str,
    ttl: float | None = None,
    limit: int = 100,
) -> RecoveryReport:
    """Examine every execution whose lease expired, and report what was decided.

    Recovery claims each execution it looks at, so the same fencing rules apply to it as to any
    other worker: what it decides is recorded under a fresh token, and a worker that comes back to
    life cannot overwrite the decision. A definition that is missing or changed stops the execution
    as an incompatible definition rather than letting recovery invent work.
    """
    policies = activities or {}
    expired = (await store.expired_leases())[:limit]
    resumed: list[str] = []
    parked: list[str] = []
    stopped: list[str] = []
    decisions: dict[str, str] = {}
    for execution_id in expired:
        claim = await store.claim_next(owner, ttl=ttl)
        if claim is None or claim.execution_id != execution_id:
            # Another worker reached it first, or it is no longer recoverable: this pass must not
            # act on information it can no longer verify.
            break
        try:
            decision = await _recover_one(store, claim, policies=policies, definitions=definitions)
        except DurableVersionError as error:
            await store.fail_execution(
                claim, kind=FailureKind.INCOMPATIBLE_DEFINITION, message=str(error)
            )
            stopped.append(execution_id)
            decisions[execution_id] = "incompatible definition"
            continue
        if decision.action == "parked":
            parked.append(execution_id)
            decisions[execution_id] = "outcome_unknown"
        elif decision.action == "cancelled":
            stopped.append(execution_id)
            decisions[execution_id] = "cancelled"
        else:
            resumed.append(execution_id)
            decisions[execution_id] = f"resolved {decision.state.value}"
    return RecoveryReport(
        expired=expired,
        resumed=tuple(resumed),
        parked=tuple(parked),
        stopped=tuple(stopped),
        decisions=decisions,
    )


@dataclass(frozen=True)
class _Decision:
    """What recovery decided about one execution: ``resumed``, ``parked``, or ``cancelled``."""

    action: str
    state: StepState


async def _recover_one(
    store: JournalStore,
    claim: Claim,
    *,
    policies: Mapping[str, ActivityPolicy],
    definitions: DefinitionLookup,
) -> _Decision:
    if claim.cancellation_requested:
        await store.acknowledge_cancellation(claim, reason="cancellation requested earlier")
        return _Decision("cancelled", StepState.FAILED)
    running = await store.running_steps(claim.execution_id)
    if not running:
        # The worker stopped between steps, so the journal is consistent and the execution is
        # simply ready to advance again.
        await store.yield_execution(claim, reason="recovered after an expired lease")
        return _Decision("resumed", StepState.PENDING)
    workflow = require_definition(definitions, claim)
    states = await store.step_states(claim.execution_id)
    outputs = await store.completed_outputs(claim.execution_id)
    plan = plan_next(workflow, states, outputs)
    state = StepState.PENDING
    for step_id in running:
        state = await resolve_interrupted_attempt(
            store,
            claim,
            activities=policies,
            step_id=step_id,
            step_input=_input_for(plan, step_id, claim),
        )
    action = "parked" if state is StepState.OUTCOME_UNKNOWN else "resumed"
    return _Decision(action, state)


def _input_for(plan: Plan, step_id: str, claim: Claim) -> object:
    """Return the input the interrupted step received, reconstructed from persisted state."""
    if plan.kind is PlanKind.RUN_STEP and plan.step is not None and plan.step.id == step_id:
        if not plan.sources:
            return claim.input
        return plan.value
    return claim.input
