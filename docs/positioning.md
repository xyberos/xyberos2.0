# Where Xyberos fits

> Status: Phase 8. This page exists so that a team can decide in ten minutes whether they are in or
> out, rather than discovering the boundary in week three. It is deliberately blunt: the fastest way
> to lose a reader is to let them adopt something that cannot do what they need, and the second
> fastest is to explain it only after they have.

## In one sentence

Xyberos is a thin, auditable application runtime: composition, typed dependencies, lifecycle,
configuration, and optional subsystems you can swap — with a stable tier that installs nothing from
PyPI, and a durable executor that is experimental and single-host on purpose.

It is for a team that would rather assemble known parts than adopt a platform, and that values being
able to read the whole dependency surface in an afternoon.

## Is it for you?

| You are building | Verdict | Because |
| --- | --- | --- |
| An internal tool, back-office app, or admin API | **Good fit** | one host, one team, SQLite, configuration from the environment, tests without infrastructure |
| An on-premise or local-first AI assistant | **Good fit** | provider-neutral facade, allowlisted tools, no vendor SDK, no prompt retention, runs against a local model |
| Batch or ETL orchestration on one machine | **Good fit** | bounded retries, deadlines, structured events, and a journal you can audit |
| An appliance, edge service, or embedded deployment | **Good fit** | ~2 600 lines of core, one conditional dependency (`tomli`, and only below Python 3.11), no bundled server |
| Something in a regulated or air-gapped environment | **Good fit** | the dependency audit is a page long and every licence is permissive; see the [release guide](./release.md) |
| A public API at traffic | **Poor fit** | SQLite allows one writer; see [capacity](#capacity-honestly) |
| A multi-tenant SaaS | **Poor fit** | no identity, session, or authorization model, by decision ([ADR 0014](./adr/0014-no-identity-or-authorization-model.md)) |
| A distributed, queue-driven platform | **Poor fit** | durability is single-host, by decision ([ADR 0015](./adr/0015-durability-is-single-host.md)) |
| A batteries-included application | **Poor fit** | no ORM, admin, session store, or plugin ecosystem; assemble those yourself |
| A multi-replica Kubernetes deployment | **Poor fit as shipped** | one writer means one replica, unless you supply a database provider ([ADR 0016](./adr/0016-database-providers-are-an-extension-point.md)) |

## If you need X, use Y

Naming the alternative is part of the decision. None of these are criticisms of this project; they are
the tools built for the job.

| You need | Reach for | Xyberos still helps with |
| --- | --- | --- |
| A public API at volume | a Postgres- or MySQL-backed framework, or a provider package for `DatabaseProvider` | everything above the database: composition, config, workflow, tests |
| Multi-tenant identity, roles, sessions | your identity provider plus a proxy, or Django's auth if you want it in-process | the sanctioned pattern in [the tenancy example](../examples/tenancy/README.md) |
| Cross-host orchestration with exactly-once effects | Temporal, Argo Workflows, a managed workflow service | the *worker role*: it runs one item well, with an audit trail ([broker-driven worker](../examples/broker_worker/README.md)) |
| An ORM, an admin UI, sessions, migrations that generate themselves | Django, or FastAPI plus SQLAlchemy and your own choices | the runtime around them; recipes are in the [database guide](./database.md) |
| A plugin ecosystem with discovery | a framework where plugins are the product | an explicit, ordered, typed plugin contract ([plugin guide](./plugins.md)) |
| A server, TLS, rate limits, request size limits | any ASGI server and your reverse proxy | nothing — that boundary is deliberately not ours |

## Supported topologies

| Topology | Supported | Notes |
| --- | --- | --- |
| One process, one host | **Yes** | the default, and what the examples run |
| Several worker processes, one host, one journal | **Yes** | claims are fenced; the retry policy absorbs write contention |
| One ASGI server behind a proxy, one host | **Yes** | identity, TLS, and rate limits belong to the proxy ([security guide](./security.md)) |
| Several ASGI replicas | **Only with a different database provider** | SQLite is one writer; reads scale under WAL, writes do not |
| Several worker hosts, one journal | **No** | SQLite locking is not dependable over a network filesystem; use a queue as the delivery layer and stay single-host per journal |
| Multi-host durable execution | **No, and not planned** | it needs a consensus substrate; using one is the integration, not the framework |

## Capacity, honestly

The recorded baselines are in [performance.md](./performance.md), measured on one machine for
comparison against themselves. Three numbers decide most capacity questions:

- **A single writer does about 2 000 writes per second** — 0.47 ms per write per transaction, with WAL
  and `synchronous=NORMAL`. Reads continue in parallel under WAL, so read volume is a different
  question from write volume.
- **Under contention the retry backoff sets the pace, not the disk.** Twenty concurrent writers take
  about 120 ms in total — roughly 170 writes per second — because each contended writer sleeps its
  `base_delay` before retrying. Contention is a design smell to remove by batching or serialising, not
  a throughput lever to tune.
- **Requests are cheap.** A route round trip in process is well under a millisecond of framework work,
  so the framework is rarely the bottleneck; the database, the network, and a model provider are.

The practical rule: if your write volume fits one box's single writer, this is enough; if it does not,
the problem is the database engine, not the runtime, and the answer is a different provider
([writing a database provider](./database-providers.md)).

## The defaults are swappable

This is the property that makes the boundary livable rather than a wall. Every default below is
replaceable through a documented seam, and the seam's tier says how much you can rely on it.

| Default | Replace it with | How | Tier of the seam |
| --- | --- | --- | --- |
| SQLite database provider | any async SQLAlchemy dialect | implement `DatabaseProvider`, pass it with `app.provide(DatabaseProvider, instance=...)`, run `assert_provider_contract` | preview |
| `Settings.load()` / TOML | explicit arguments, environment, or your own `Settings` | `Settings.load(config_path=, environ=, overrides=)`; `App(settings=...)` | stable |
| The clock the workflow executor uses | any `Clock` | `WorkflowExecutor(clock=...)` — the test doubles do exactly this | stable |
| The wall clock the durable worker uses | any `WallClock` | worker settings; `SystemWallClock` is the default | experimental |
| Model provider | any `ModelProvider` | `AIFacade(provider)` — Ollama is one adapter, the fake is another | preview |
| ASGI server | anything that speaks ASGI | not bundled; `uvicorn`, `hypercorn`, `granian`, or your platform's | — |
| The correlation-id header name | any header | `HttpAdapter(app, request_id_header="...")` | preview |
| Provider instances in tests | any double that satisfies the contract | `app.with_overrides({Contract: double})` | stable |
| Plugin configuration source | TOML section, environment, or an explicit mapping | `app.add_plugin(plugin, config=...)` | stable |
| The durable journal's storage settings | path, lease TTL, payload ceiling, synchronous mode | `JournalSettings(...)` | experimental |
| Application logging | your own handlers and filters | standard `logging`; `ContextLogFilter` attaches context | stable |

Nothing in core is a singleton you cannot replace, and no default requires editing the framework to
change.

## What is deliberately absent

Each of these is a decision with a reason, not an unfinished edge. The ADR that records it is the
place to argue with it.

| Absent | Recorded in |
| --- | --- |
| Identity, sessions, tenancy, authorization | [ADR 0014](./adr/0014-no-identity-or-authorization-model.md) |
| Multi-host durability and distributed scheduling | [ADR 0015](./adr/0015-durability-is-single-host.md), [ADR 0011](./adr/0011-durable-executor-contract.md) |
| A second database provider in core | [ADR 0016](./adr/0016-database-providers-are-an-extension-point.md) |
| An ORM, an admin UI, a session store | this page, and [ADR 0001](./adr/0001-runtime-boundaries.md) |
| A sandbox for untrusted code | [plugin guide](./plugins.md), [security guide](./security.md) |
| Plugin discovery through entry points | [ADR 0007](./adr/0007-trusted-plugins.md) |
| Desktop, mobile, or edge-function packaging | this page — the target is a long-lived server process |

## The honest summary

Xyberos is a good fit for a team that wants a small, legible runtime and is willing to own the
subsystems it does not ship — identity, scale-out, and the product decisions around them. It is a bad
fit for anyone who wants those subsystems to come in the box, and no amount of documentation will
change that, because shipping them is a different product.

If you are still unsure, [the tutorial](./tutorial.md) takes about an hour and answers most of what a
prose description cannot.
