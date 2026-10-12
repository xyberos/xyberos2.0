---
title: Extend Xyberos
status: verified
---

# Extend Xyberos

For experienced developers: the extension points, in the order you meet them — a capability of your own,
a module, a package other people install, and a database behind the same contract the shipped one keeps.

**Every page below is written and verified.** Each one runs the code it shows on this repository's own
toolchain, and the operational side of a deployment — logging, diagnostics, contention, shutdown,
deployment order — lives in [Production](../production/index.md) rather than here.

## Written and verified

| Page | What it answers |
| ---- | --------------- |
| [The provider registry](registry.md) | what a registration says, which scope owns the instance, what is refused at registration, and how a test replaces one answer without restarting the application |
| [Writing a module](modules.md) | the whole convention for a composable unit — one `register(app)` function — and the two properties that make it compose with anything |
| [Writing a plugin](plugins.md) | the trusted-code boundary, metadata and compatibility, configuration precedence, requirement ordering, the eight refusals, and how to test and publish a distribution |
| [Writing a database provider](database-providers.md) | the three-member contract, the semantics behind each promise, error mapping, and the conformance suite that refuses a provider that breaks it even while passing one that does not |
| [Multi-step work that outlives the process](durable.md) | the one experimental surface, and its contract terms rather than caveats |

## Where the topics that used to be planned went

The seven topics this section used to defer are all published now, and each one went to the page whose
subject it is rather than to a subsection here:

| Topic | Home |
| ----- | ---- |
| Advanced configuration and lifecycle hooks | [configuration](../reference/runtime.md#configuration) in the reference, and the state machine in [internals](../production/internals.md) |
| Custom handlers and middleware | [the runtime reference](../reference/runtime.md#routes) for the handler contract, and the [middleware order](../production/internals.md#what-a-request-actually-does) for where yours runs |
| Migrations and transaction boundaries | [deploying it](../production/deploy.md) for the deploy step, and [the database reference](../reference/database.md) for the transaction and retry semantics |
| Custom tools and retrieval that you write | [the AI tools lesson](../learn/ai/11-tools.md), [retrieval over `embed`](../learn/ai/10-retrieval.md), and the [hybrid retrieval lesson](../learn/hybrid/05-retrieval.md) |
| Observability, cost tracking, and troubleshooting | [observability](../production/observability.md), [troubleshooting](../production/troubleshooting.md), and the [usage and cost lesson](../learn/hybrid/10-usage.md) |
| Performance and concurrency | [performance and concurrency](../production/performance.md), with the recorded baselines in [the performance reference](../reference/performance.md) |
| Deployment, security hardening, and internals | [deploying it](../production/deploy.md), [security boundaries](../production/security.md), and [internals](../production/internals.md) |

## The experimental page

Durable execution is the one experimental tier surface, and its limits are contract terms rather than
caveats: **single host, one journal file, at-least-once effects**. A persisted step result proves a step
completed, not that its external effect happened exactly once, and an attempt whose outcome cannot be
established is parked for a decision rather than retried on a guess
([ADR 0011](../reference/adr/0011-durable-executor-contract.md)). It belongs here, behind that
statement, and not on any learning path.

## Where the pieces meet

An extension point is only useful if it composes with the rest of the framework, so each page names the
boundary it stays behind:

- A **provider** is registered before startup and frozen at it, which is what makes a diagnosis about the
  application reproducible.
- A **module** registers providers and routes and takes no decisions about what else exists; composition
  belongs to the application that calls it.
- A **plugin** is a module with a name, a version, and a configuration schema — validated before it runs,
  and attributed in diagnostics afterwards.
- A **database provider** is what a service sees instead of an engine, so the contract is deliberately
  small: transactions, bounded retrying, readiness.
