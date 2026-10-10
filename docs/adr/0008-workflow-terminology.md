# ADR 0008: Name the in-process execution unit *Workflow*

**Status:** accepted

## Context

Phase 4 introduces the first stable multi-step execution contract, and it needs a name that appears
in the public API, the plan, the guides, and the durable-execution design. The documentation used
two: the stable layer described an in-process **Flow**, while the durable-execution design
described persisted **workflow definitions**, `workflow_definitions` tables, and workflow
versions — the same artifact under two names, and the durable executor was specified to persist
*Flow* definitions under the name "workflow definitions".

Three further facts shaped the decision:

- `flow` is heavily overloaded: Python control flow, flow control, Prefect's `Flow`, and graph
  libraries all compete for the word, so searching a codebase or the web for it is noisy.
- `Workflow` is the domain term for this artifact, used by Argo, Temporal, Airflow, and Step
  Functions, and it matches the vocabulary the durable design had already adopted.
- Timing: the rename was nearly free *before* Phase 4 shipped its contract — the term appeared only
  in documentation — and would have been a breaking change afterwards.

## Decision

**The in-process multi-step execution unit is `Workflow`,** with `Step` and `Edge` as its parts,
living in `xyberos.execution` and re-exported from the core package. There is no extra to install.

**One definition format, two executors.** A workflow definition is the same artifact whether the
in-process engine (Phase 4) or the experimental durable executor (Phase 6) runs it, so the stable
layer and the durable layer now share one vocabulary. Persistence remains a property of the
*executor*, not of the name.

**The name carries no durability promise.** `Workflow` says what the artifact is; the
`xyberos.durable` package and its documentation say whether progress survives a restart. The guide
and the type docstrings state explicitly that ordinary in-process execution loses state when the
process exits and that execution events are not a journal.

**Prior documents were updated rather than left to drift.** Text written before this ADR was
rewritten to the new term, including inside accepted ADRs, because a half-renamed document set
defeats the greppability that motivated the change. This is a terminology substitution only: no
earlier decision is amended, and the decisions recorded in ADRs 0001, 0003, 0005, and 0007 are
unchanged.

## Consequences

- Searching for `workflow` finds the concept; `flow` survives only as ordinary English, such as
  "control flow" and "the whole flow".
- Phase 6's vocabulary — workflow definition, workflow version, `workflow_definitions` — is now
  consistent with Phase 4 instead of contradicting it.
- The deferred imperative surface is now the *decorator Workflow API* in the Phase 7 backlog.
- A reader who assumes Temporal-style durability from the word *workflow* must be corrected by
  documentation, not by the name. `docs/workflow.md` states the absence of persistence in three
  places, and `Workflow.run` documents that state is lost on process exit.
- Any future rename of the execution unit is a public breaking change and requires a new ADR.
