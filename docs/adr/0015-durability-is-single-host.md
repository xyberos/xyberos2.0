# ADR 0015: Durability is single-host, and the worker role is the integration point

**Status:** accepted

## Context

[ADR 0011](0011-durable-executor-contract.md) froze the durable executor's contract and stated the
limitation — single instance, one journal file, at-least-once effects — but left the *shape of the
refusal* open. In practice the question a team asks is not "is it single-host?" but "then how do I run
this on more than one machine?", and the answer has to be both honest and useful.

The tempting answer is to reach for a distributed scheduler. That would be a different product: a
host-spanning durable executor needs a consensus or queue substrate for ownership, membership,
fencing across machines, and delivery, and doing it with SQLite file locking would produce a system
that *looks* distributed and silently violates its own guarantees under partition. This project's
entire position on failure is that a guarantee you cannot prove is a claim you should not make.

## Decision

**Xyberos will not host durability across machines.** No multi-host ownership, no leader election, no
network filesystem support, no distributed scheduling. The journal is one SQLite file on local
storage, and SQLite write locking is the only coordination there is.

**Work distribution *within* a host is supported and is the intended scale story:** several worker
processes on one machine claim work from one journal, bounded by the lease and fencing rules, and the
retry policy absorbs the write contention. That covers the common case — one box, a handful of worker
processes, a workload measured in thousands of executions a day rather than millions.

**The supported way to run at a larger scale is to let something else own delivery, and let Xyberos own
progress.** A message queue, a broker with at-least-once delivery, or an external scheduler hands out
work items; each item is submitted with a **stable execution id derived from the delivery id**. Because
submission is idempotent for the same id and the same definition, a redelivered message produces one
execution rather than two, and a worker that dies mid-item leaves a journal entry that another worker on
the same host recovers. The queue owns *where* work runs; the journal owns *how far it got*.

The [broker-driven worker example](../../examples/broker_worker/README.md) is this topology, tested,
including redelivery of the same message.

**What to use instead, stated plainly:** for cross-host orchestration with those guarantees, use a
system built for it — Temporal, Argo Workflows, a cloud workflow service, or your own queue plus
idempotent handlers. Naming the alternatives is part of the decision, because "no" without a "use
this instead" is how a project loses a reader.

## Consequences

- **Scale is bounded by one machine's disk and one writer, on purpose.** The limits are documented, and
  the capacity guidance states where the wall is rather than leaving a team to discover it in
  production. A network filesystem stays unsupported: the locking this design relies on is not
  dependable there, and a journal on NFS is a corruption report waiting to happen.
- **The broker integration is only as safe as the delivery id.** A broker that generates a fresh id per
  delivery defeats idempotent submission and will duplicate work. The example and the guide both say
  so, because the failure mode is silent.
- **A redelivered item is not a resumed execution.** Resuming needs the *same* execution id: if a queue
  cannot supply a stable id, the correct pattern is one execution per delivery plus an idempotent
  effect, which is a different design and is the application's responsibility.
- **Nothing here prevents a second durable backend later.** `JournalStore` and the worker talk to a
  journal contract, and a different backend would be a new ADR plus a conformance suite — the same
  route the database provider contract takes ([ADR 0016](0016-database-providers-are-an-extension-point.md)).
- **Promotion out of experimental remains separate.** This ADR does not promote durability; the
  evidence `PLAN.md` §5.4 asks for is still incomplete, and the label stays until it is not.
