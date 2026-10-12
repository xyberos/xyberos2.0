---
title: Deploying it
status: verified
---

# Deploying it

A deployment is a sequence, and most of what goes wrong is the sequence rather than the code. This
page is the sequence: build the application from configuration, check it, migrate the database, serve
it, and answer readiness honestly — with the two choices that are actually choices marked as such.

The application is `examples/learn_production/deploy01_app.py`. It is small on purpose: two routes,
one service, one database. What makes it deployable is not its size.

## The factory contract

<!-- snippet: examples/learn_production/deploy01_app.py -->

Three properties carry the weight, and all three are checkable rather than aspirational:

- **`create_app` takes no required arguments.** Both `xyberos check` and a server call a factory *by
  name*, so a factory that needed an argument could not be named in the first place. Everything the
  application needs arrives from `Settings.load`, which reads the file below and then the environment.
- **`create_asgi` is the second entry point, and it exists for a different caller.** A server needs
  something to serve, so `create_asgi` compiles the same runtime into a Starlette application through
  `HttpAdapter`; `xyberos check` needs the runtime itself, so it names `create_app`. One factory and
  two names beats one factory that guesses who is calling.
- **The database is opened at *startup*, not on the first request.** That is what `eager=True` does,
  and it changes what a broken database *is*: a failed start rather than a failed request. The
  `eager=False` variant further down is the other posture, and the difference between them is a
  deployment decision with an operational consequence.

### Configuration, in the order it is read

```toml title="examples/learn_production/deploy.toml"
[app]
name = "xyberos"
environment = "development"
debug = false
```

The file states the deployment's defaults; the environment overrides them, which is how the same
artifact runs in two places without being rebuilt:

| Source | Example | Precedence |
| ------ | ------- | ---------- |
| explicit `overrides` passed to `Settings.load` | `environ={"ORDERS_DATABASE": ":memory:"}` | highest |
| environment variables | `XYBEROS_APP__DEBUG=true`, `XYBEROS_CONFIG=/etc/app.toml` | above the file |
| the TOML file | `deploy.toml` above | above the defaults |
| typed defaults | `app.environment = "development"`, `app.debug = false` | lowest |

`ORDERS_DATABASE` in that table is not a runtime setting: it is the one thing this application reads
itself, with a name of its own, because "where the orders live" is the application's business rather
than the framework's. Nested settings use `__`, and a key the runtime does not know is refused rather
than ignored — [security](security.md) shows what that refusal prints, which is the setting's name and
never its value. The whole configuration surface is in
[the runtime reference](../reference/runtime.md).

## Check it before you run it

```powershell
python -m xyberos check --app learn_production.deploy01_app:create_app --app-dir examples
```

`check` composes the application without starting it, then inspects what it composed: the provider
graph, the plugins, and every route's handler signature. It is the cheapest failure you can have,
because it happens before a server binds a port. The same call, in-process:

<!-- snippet: examples/learn_production/deploy02_check.py -->

<!-- output: deploy02_check -->
```text
settings: xyberos (development), schema_version 1, debug False
application: learn_production.deploy01_app:create_app
provider graph: valid
providers:
  DatabaseProvider [app, eager] from application
  OrderService [app] from application
plugins:
  (none)
routes: 2 (handler signatures valid)
xyberos check exited with 0
```

Five lines, five questions answered before the process serves anything:

| Line | What a deployment learns |
| ---- | ------------------------ |
| `settings: xyberos (development), schema_version 1, debug False` | which configuration was actually loaded, including the schema version the runtime understands — the two things that differ first when two deployments disagree |
| `application: ...:create_app` | the factory the CLI resolved, so a typo is a reported unresolvable target rather than a crash loop |
| `provider graph: valid` | every declared dependency has a provider, no cycle, no scope violation — the checks [troubleshooting](troubleshooting.md) prints one at a time |
| `DatabaseProvider [app, eager] from application` | the scope, whether it is eager, and **who registered it**: the `source` field that makes an unexpected override traceable |
| `routes: 2 (handler signatures valid)` | the handler signatures the adapter will inject into are valid, which is a different question from the graph being valid |

The `environment` on that line is worth dwelling on: it is how the *same artifact* says which
deployment it believes it is in, and a staging process reporting `production` is one line away from
being spotted. The command's own reference is [the CLI guide](../reference/cli.md).

## Migrate before you serve

The deploy step that decides whether the first request works:

```powershell
python -m xyberos migrate --url "sqlite:///var/orders.db" --migrations examples/learn_production/migrations
```

Nothing migrates at startup, and that is deliberate: every replica would try, on every boot, and a slow
migration would be a container that never becomes healthy. The application ships the migrations next to
the tables they create:

<!-- snippet: examples/learn_production/orders_tables.py -->

<!-- snippet: examples/learn_production/migrations/versions/0001_create_orders.py -->

The revision imports the same `metadata` object the application's models use, so a schema drift between
the two is not possible to write by accident. The `env.py` that Alembic runs is where the one real
gotcha lives:

<!-- snippet: examples/learn_production/migrations/env.py -->

**Alembic's engine is synchronous, so it needs the synchronous URL.** `SqliteSettings` keeps both forms
for the same file: `url` is `sqlite+aiosqlite://` for the application, `sync_url` is `sqlite://` for the
migration. Passing the async URL to `apply_migrations` is the mistake this page exists to prevent, and
it fails loudly rather than halfway. The proof, run against a temporary database:

<!-- snippet: examples/learn_production/deploy03_migrations.py -->

<!-- output: deploy03_migrations -->
```text
schema version: 0001_create_orders
tables: alembic_version, orders
```

The check asks the *database* where it landed rather than trusting the migration command's exit code:
`alembic_version` holds the revision, and `orders` either exists or does not. A deployment's own smoke
test should do the same thing — a migration process that reported success and a schema that is not
there is exactly the failure a status code cannot see.

## Refusing to start, or reporting not-ready

This is the one genuine choice on the page, and the two options are not equivalent:

| Posture | What happens with an unreachable database | When it is right |
| ------- | ----------------------------------------- | ---------------- |
| `eager=True` (the default) | the process fails to start; the orchestrator sees a crash loop | a fresh deployment with no traffic to lose, and a database that should be there |
| `eager=False` | the process starts, `/health` answers `503` until the database answers | a rolling deployment, where a crash loop would take every replica down together |

Both, in one transcript:

<!-- snippet: examples/learn_production/deploy04_readiness.py -->

<!-- output: deploy04_readiness -->
```text
eager=False -> 503 {'error': {'type': 'NotReadyError', 'message': 'the database is not reachable'}}
eager=True  -> DependencyResolutionError caused by DatabaseConnectionError
and the application is left in state: failed
readiness -> {'ready': True}
GET /orders/1 -> {'order': 1, 'total': 42.5}
GET /orders/7 -> 404 {'error': {'type': 'OrderNotFoundError', 'message': 'order 7 does not exist'}}
```

Four things about those six lines:

- **`503` with a typed body.** Readiness is a route that asks the database, and its failure is an
  `HttpError` subclass, so the client gets the status a load balancer understands and a message that
  says nothing about why — no path, no driver, no connection string.
- **`DependencyResolutionError caused by DatabaseConnectionError` and `state: failed`.** Under the other
  posture the same database is a failed *start*, and the state is observable afterwards rather than
  guessed at. [Internals](internals.md) walks the states.
- **A handler's dependencies are resolved *before* its body runs.** This is why the tolerant
  `UnavailableDatabase` provider exists in the module: a provider whose *construction* raises cannot be
  caught by a route, because the route never runs. If you want to report a broken dependency instead
  of refusing to start, the dependency has to be able to construct and fail on use.
- **`404` is a route's own decision.** `OrderNotFoundError` is an `HttpError` with a status code, so the
  adapter maps it; anything that is *not* an `HttpError` becomes a generic `500` and keeps its message
  in the log ([security](security.md) shows both halves of that in one transcript).

## The deploy sequence

```powershell
python -m pip install "xyberos[http,database]" uvicorn
python -m xyberos check --app learn_production.deploy01_app:create_app --app-dir examples
python -m xyberos migrate --url "sqlite:///var/orders.db" --migrations examples/learn_production/migrations
uvicorn --app-dir examples --factory learn_production.deploy01_app:create_asgi
curl http://127.0.0.1:8000/health
```

Five steps, and the order is the content: install, check the graph, migrate, serve, then let the
readiness endpoint decide whether this process joins the rotation.

## What the deployment still owns

| Job | What to do | What Xyberos does |
| --- | ---------- | ----------------- |
| TLS, CORS, body and rate limits | at the server and the proxy | nothing, on purpose ([security reference](../reference/security.md)) |
| Secrets | environment or a secret manager, never the image | reads the environment; does not fetch, rotate, or audit |
| Identity | the proxy authenticates and strips its own assertion headers | nothing: [the traditional path's identity lesson](../learn/traditional/08-identity.md) shows the application-side shape |
| Backups | the database file **and its WAL** while the process runs | nothing |
| Shutdown | send `SIGTERM` and wait for the drain | stops accepting new work, drains in-flight request contexts, then closes in reverse order ([internals](internals.md)). Set `app.shutdown_timeout` to bound the drain: `None`, the default, waits as long as it takes |
| Log shipping | configure a root handler | binds a correlation id per request and logs nothing to a sink of its own ([observability](observability.md)) |

## Common mistakes

- **Serving before migrating.** The first request that touches the new column is a `500`, and the deploy
  that "worked" is the one that never exercised it.
- **A readiness check that only proves the process is alive.** `{"ready": true}` is a claim about the
  database, not about the event loop; the route above asks the provider for that reason.
- **`--factory` pointing at the runtime factory instead of the ASGI one.** `create_app` returns an
  `App`, which is not an ASGI application; `create_asgi` is the one a server can call.
- **Passing the async URL to Alembic.** See `sync_url` above: the failure is loud, but only if you look.
- **`debug=True` in production.** It changes how internal errors are reported, and it is printed by
  `xyberos check`, which is one command.
- **Restarting a stopped application instead of replacing the process.** `App` does not start again once
  stopped, by design; the orchestrator's job is to start a new process. [Internals](internals.md) shows
  the refusal.
