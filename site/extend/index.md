---
title: Extend Xyberos
status: planned
---

# Extend Xyberos

For experienced developers: the provider registry in detail, writing a module, writing a plugin,
writing a database provider, the durable executor, and the runtime's internals.

**This section is not written yet.** It lands in phases 6 and 7 of
[the plan](https://github.com/xyberos/xyberos2.0/blob/master/site/implementation.md).

## What it will cover

| Topic | Availability |
| ----- | ------------ |
| Custom providers, factories, scopes, and `with_overrides` | Built-in |
| Advanced configuration and lifecycle hooks | Built-in |
| Custom handlers and middleware | Built-in (extra) |
| Migrations and transaction boundaries | Built-in (extra) |
| Writing a database provider, and passing the conformance suite | Extension point |
| Custom tools | Built-in |
| Retrieval you write yourself | You build it |
| Observability, cost tracking, and troubleshooting | Built-in and application code, labelled per page |
| Performance and concurrency | Built-in |
| Deployment, security hardening, and internals | Mixed, labelled per page |
| Multi-step work that outlives the process | **Experimental** |

## The experimental page

Durable execution is the one experimental tier surface, and its limits are contract terms rather than
caveats: **single host, one journal file, at-least-once effects**. A persisted step result proves a step
completed, not that its external effect happened exactly once, and an attempt whose outcome cannot be
established is parked for a decision rather than retried on a guess
([ADR 0011](../reference/adr/0011-durable-executor-contract.md)). It belongs here, behind that
statement, and not on any learning path.
