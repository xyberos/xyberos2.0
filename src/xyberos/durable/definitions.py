"""Finding the definition an execution was submitted with.

Workflow code is never persisted — the journal stores a name, a version, and a fingerprint — so a
resumed execution has to be handed its definition again and checked against what was recorded. A
definition that no longer matches fails the execution instead of improvising new work.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from xyberos.durable.models import Claim
from xyberos.durable.store import definition_fingerprint
from xyberos.errors import DurableVersionError
from xyberos.execution.models import Workflow

DefinitionLookup = Mapping[str, Workflow] | Callable[[str, str], Workflow | None]


def workflow_key(workflow: Workflow) -> str:
    """Return the journal key for a definition: its name and version."""
    return f"{workflow.name}:{workflow.version}"


def lookup_definition(lookup: DefinitionLookup, name: str, version: str) -> Workflow | None:
    """Return the definition registered for ``name`` at ``version``, if the caller has it."""
    if callable(lookup):
        return lookup(name, version)
    return lookup.get(f"{name}:{version}")


def require_definition(lookup: DefinitionLookup, claim: Claim) -> Workflow:
    """Return the workflow a claimed execution needs, or fail with a specific reason.

    Two different problems are reported separately: nothing registered for that name and version,
    and a definition that is registered but shaped differently from the one already running.
    """
    workflow = lookup_definition(lookup, claim.workflow, claim.version)
    if workflow is None:
        raise DurableVersionError(
            f"execution {claim.execution_id} needs workflow {claim.workflow!r} version "
            f"{claim.version!r}, which this worker does not have registered"
        )
    fingerprint = definition_fingerprint(workflow)
    if fingerprint != claim.fingerprint:
        raise DurableVersionError(
            f"execution {claim.execution_id} was submitted against a different definition of "
            f"workflow {claim.workflow!r} version {claim.version!r}; resume it with the definition "
            "it was submitted with, or submit the change under a new version"
        )
    return workflow
