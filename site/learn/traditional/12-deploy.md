---
title: Deploying it
path: traditional
lesson: 12
tier: built-in
status: verified
verify: output
example: examples/learn_traditional/traditional12_deploy.py
prerequisites: ["/learn/traditional/11-partials"]
---

# Lesson 12 — deploying it

## What you will build

A running application, and the checks that decide whether it stays that way. Everything in this path so
far has run inside a test client; this lesson runs the same object under a server, in the order a
deployment runs it, and shows what happens when the order is wrong.

## What you need

The `database` extra (lesson 3) and a server. `uvicorn` is not part of Xyberos — a framework that
refuses to depend on an HTTP library should not force a server on you either:

=== "PowerShell"

    ```powershell
    python -m pip install uvicorn
    ```

=== "POSIX"

    ```bash
    python -m pip install uvicorn
    ```

## The deploy step

Three commands, in this order, and the order is the lesson:

```powershell
python -m xyberos migrate --url "sqlite:///var/app.db" --migrations examples/user_management/migrations
uvicorn --app-dir examples --factory user_management.app:app_factory
curl http://127.0.0.1:8000/health
```

- **Migrate first.** A deployment that starts before migrating answers its first query with a `500`.
- **Then serve.** `--factory` calls `user_management.app:app_factory`, which composes the application
  and reads the identity secret from the environment *when the server starts* rather than when the
  module is imported.
- **Then check.** `/health` touches the database, so a process that cannot reach it never joins the
  load balancer.

`examples/learn_traditional/traditional12_deploy.py` runs those checks against a temporary database,
including the failure:

<!-- snippet: examples/learn_traditional/traditional12_deploy.py -->

The `500` line prints a traceback on **stderr**, and that division is deliberate: the log is where the
internal message goes, and the client gets a generic error body. That is the error policy from the
fundamentals path doing its job, and it is worth seeing once under a real server.

## What it prints

<!-- output: traditional12_deploy -->
```text
the application validates: yes
it answers on: ['/health', '/me', '/pages/users', '/pages/users/{user_id}/toggle', '/users', '/users/{user_id}']
before migrating, /health answers: 200
before migrating, a query fails: 500
the deploy step migrated: users.db
/users without an assertion: 401
/users as an administrator: 200
an unknown path: 404
every answer carries a request id: True
no secret is echoed: True
a deployment with no secret refuses every request: 401
the secret is read from XYBEROS_IDENTITY_SECRET: yes
```

| Line | Why a deployment cares |
| ---- | ---------------------- |
| `the application validates: yes` | `app.validate()` is the same graph check `xyberos check` runs; a missing provider should be a failed start, not a failed request |
| `it answers on: [...]` | the route table, as the running object sees it — the list a deployment's smoke test can assert |
| `before migrating, /health answers: 200` | health proves the database *answers*; it says nothing about the schema |
| `before migrating, a query fails: 500` | the deploy step is not optional, and this is what forgetting it looks like |
| `/users without an assertion: 401` | the identity check is in the running application, not only in the tests |
| `/users as an administrator: 200` | and the assertion works the way lesson 8 signed it |
| `every answer carries a request id: True` | one correlation id per request, in the response and in the logs |
| `no secret is echoed: True` | the identity secret is configuration, and configuration does not travel back to a client |
| `a deployment with no secret refuses every request: 401` | fail closed: a missing secret is a refusal, not a bypass |

## The checklist, and what is not on it

| Job | What to do | What Xyberos does |
| --- | ---------- | ----------------- |
| Schema | run `xyberos migrate` as a deploy step | nothing at startup — by design ([ADR 0014](../../reference/adr/0014-no-identity-or-authorization-model.md)'s sibling rule in [principles](../../reference/positioning.md)) |
| Configuration | environment variables, one per deployment | reads them; does not fetch, rotate, or audit secrets |
| Identity | the proxy authenticates and **strips** the assertion headers | nothing: header hardening is the adapter's middleware and your proxy |
| TLS, CORS, size and rate limits | at the ASGI server and the proxy | nothing, on purpose ([security guide](../../reference/security.md)) |
| Logs | structured lines with the request's correlation id | the id is bound per request; the sink is yours |
| Readiness | something that reflects *your* dependencies | `/health` is the shape, not the policy |
| Backups | the database file, and its WAL while the process runs | nothing |

The last two rows are where most deployments of this application fail in practice, in opposite
directions: a readiness probe that only checks the process, and a backup that copies a file while WAL
holds the newest writes.

## Common mistakes

- **SQLite with several writers.** WAL lets readers proceed, but writes serialize. Run one worker, or the
  application's database belongs on a provider built for concurrency — which is what lesson 3's
  `DatabaseProvider` seam is for.
- **Migrating on startup.** Every process tries, on every boot, and a slow migration becomes a container
  that never becomes healthy. It is a deploy step because it is a decision.
- **A secret on the command line.** `--url` values are redacted by the `migrate` command, but anything in
  an argument list is visible to `ps` and lands in shell history. The identity secret is read from the
  environment and never printed.
- **Deploying behind a proxy that forwards `X-Authenticated-Subject`.** The assertion becomes forgeable
  and every `401` in this path becomes decoration. Test it by sending the header yourself and expecting
  a refusal.
- **Treating `/health` as readiness.** It answers `200` for a database whose schema is a revision
  behind, which is exactly the state a deploy step exists to prevent. The exercise is the fix.
- **Exposing the database file.** It sits next to the application in this example; in a deployment it
  lives behind filesystem permissions, not behind a URL.

## Exercise

Add `GET /ready`: a readiness check that compares the columns the code reads with the columns the
database has, and answers `503` until they agree. It should say `200` against a database that has been
migrated, and name what is missing against one that has not.

<details>
<summary>Show the answer</summary>

<!-- snippet: examples/learn_traditional/traditional12_exercise.py -->

<!-- output: traditional12_exercise -->
```text
liveness before migrating: 200 (the database answers)
readiness before migrating: 503 {'status': 'not ready', 'missing': ['display_name', 'email', 'enabled', 'external_subject', 'id']}
readiness after migrating: 200 {'status': 'ready'}
and the routes still work: 200
```

Two things in that output are the point of the exercise:

- **`liveness before migrating: 200`** while `readiness before migrating: 503`. Two probes, two
  questions: "is this process alive" and "can this process serve traffic". A platform that asks the first
  one twice will route traffic to a process whose queries fail.
- **The columns are read from the database, not from the model.** `EXPECTED_COLUMNS` is written next to
  the check on purpose: deriving it from `tables.py` would make readiness assert that the code agrees
  with itself, which it always does.
</details>

## Where this path ends

You have an application with a schema it migrated, routes it authorized, an interface it renders, an
assertion it verifies, and a deploy step it documents. The next paths add two things to it:
[AI Apps](../ai/index.md) puts a model behind a facade with a schema and a tool allowlist, and
[Hybrid Apps](../hybrid/index.md) is where the model recommends and the application decides — the same
service, the same rules, and a human in the loop at the one place that matters.
