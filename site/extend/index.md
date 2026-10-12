---
title: Extend Xyberos
status: planned
---

# Extend Xyberos

For experienced developers: the extension points, in the order you meet them — a capability of your own,
a module, a package other people install, and a database behind the same contract the shipped one keeps.

**Four pages are written and verified. The rest lands in phase 7**, so this section is still marked
*planned* in [the plan](https://github.com/xyberos/xyberos2.0/blob/master/site/implementation.md) and is
not yet counted as complete. Every page below runs the code it shows on this repository's own toolchain.

## Written and verified

| Page | What it answers |
| ---- | --------------- |
| [The provider registry](registry.md) | what a registration says, which scope owns the instance, what is refused at registration, and how a test replaces one answer without restarting the application |
| [Writing a module](modules.md) | the whole convention for a composable unit — one `register(app)` function — and the two properties that make it compose with anything |
| [Writing a plugin](plugins.md) | the trusted-code boundary, metadata and compatibility, configuration precedence, requirement ordering, the eight refusals, and how to test and publish a distribution |
| [Writing a database provider](database-providers.md) | the three-member contract, the semantics behind each promise, error mapping, and the conformance suite that refuses a provider that breaks it even while passing one that does not |
| [Multi-step work that outlives the process](durable.md) | the one experimental surface, and its contract terms rather than caveats |

## Still planned

These are phase-7 topics, and each one is a page rather than a section because the subject is large
enough to be wrong in detail:

| Topic | Availability |
| ----- | ------------ |
| Advanced configuration and lifecycle hooks | Built-in |
| Custom handlers and middleware | Built-in (extra) |
| Migrations and transaction boundaries | Built-in (extra) |
| Custom tools and retrieval you write yourself | Built-in and application code |
| Observability, cost tracking, and troubleshooting | Built-in and application code, labelled per page |
| Performance and concurrency | Built-in |
| Deployment, security hardening, and internals | Mixed, labelled per page |

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
