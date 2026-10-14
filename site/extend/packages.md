---
title: The packages beside the framework
status: verified
---

# The packages beside the framework

`pip install xyberos` gives you the runtime: composition, configuration, the HTTP adapter with SQLite,
the workflow engine, the AI facade, object storage, and the MCP client. Everything else that a real
application needs is a **distribution beside this line**, and eight of them are published.

They are separate distributions for a reason that is written down rather than assumed
([ADR 0018](../reference/adr/0018-capability-placement-rule.md)): a capability becomes a package when it
needs a dependency core will not adopt, when it carries policy, or when it has its own release cadence.
That is why `pip install xyberos` does not install Jinja2, an S3 client, or OpenTelemetry — and why the
dependency audit of the framework stays a page long.

Every package below targets **`xyberos>=2`** and is proved against the *published* core by this
repository's compatibility job, which installs the artefacts from the index rather than from a checkout.
Each package's own release is gated on that job passing.

| Package | Version | What it gives you | Install |
| ------- | ------- | ----------------- | ------- |
| [`xyberos-postgres`](https://github.com/xyberos/xyberos-plugins/tree/master/db/xyberos_postgres) | 0.1.0 | a `DatabaseProvider` for PostgreSQL | `pip install xyberos-postgres` |
| [`xyberos-storage-s3`](https://github.com/xyberos/xyberos-plugins/tree/master/storage/xyberos_storage_s3) | 0.1.1 | a `Storage` provider for S3-compatible stores | `pip install xyberos-storage-s3` |
| [`xyberos-openai-compatible`](https://github.com/xyberos/xyberos-plugins/tree/master/llm-providers/xyberos_openai_compatible) | 0.1.1 | a `ModelProvider` for OpenAI-compatible endpoints | `pip install xyberos-openai-compatible` |
| [`xyberos-templates`](https://github.com/xyberos/xyberos-plugins/tree/master/templates/xyberos_templates) | 0.1.0 | an engine-neutral `Templates` contract with Jinja2, a static mount, and form reading | `pip install xyberos-templates` |
| [`xyberos-mcp`](https://github.com/xyberos/xyberos-plugins/tree/master/mcp) | 0.3.1 | exposing an application's tools over MCP | `pip install xyberos-mcp` |
| [`xyberos-auth`](https://github.com/xyberos/xyberos-plugins/tree/master/auth) | 0.2.0 | verifying an assertion, and a `Principal` | `pip install xyberos-auth` |
| [`xyberos-observability`](https://github.com/xyberos/xyberos-plugins/tree/master/observability) | 0.2.0 | a logging handler and OpenTelemetry spans | `pip install xyberos-observability` |
| [`xyberos-crud`](https://github.com/xyberos/xyberos-plugins/tree/master/crud) | 0.1.0 | filtering, sorting, and pagination over the provider contract | `pip install xyberos-crud` |

The catalogue in [the plugin guide](../reference/plugins.md#the-catalogue) is generated from the manifest
this repository checks its own documentation against, so a package cannot be listed here and missing there.

## The shape they all share

A package is supplied at composition time, the way any other service is: the application owns the
instance and its lifecycle. Nothing is discovered by being installed, so what your process does is
readable from your own code ([ADR 0007](../reference/adr/0007-trusted-plugins.md)).

```python
from xyberos import App
from xyberos.database import DatabaseProvider
from xyberos_postgres import PostgresSettings, postgres_provider

app = App()
app.provide(
    DatabaseProvider,
    factory=postgres_provider(PostgresSettings(host="db.internal", database="app", user="app")),
    eager=True,
)
```

Three properties hold for every one of them:

- **One import root of its own.** `xyberos_postgres`, not `xyberos.postgres`, so two distributions never
  share a directory and an uninstall cannot leave stale files behind.
- **Settings are an explicit argument.** A package takes a frozen settings object or reads its own
  environment variable; none of them adds a root key to `Settings`.
- **The core range is a floor, not a formality.** A package that imports a name added in a later release
  declares that release. `xyberos-storage-s3` declares `xyberos>=2.1`, because `xyberos.storage` arrived
  in 2.1.0 and `>=2` alone would let pip install a pair that cannot import.

## PostgreSQL

```python
from xyberos.database import DatabaseProvider
from xyberos_postgres import PostgresSettings, postgres_provider

app.provide(
    DatabaseProvider,
    factory=postgres_provider(PostgresSettings(host="db.internal", database="app")),
    eager=True,
)
```

This is the same `DatabaseProvider` contract the shipped SQLite provider implements, so services do not
change: `transaction()`, `retrying()`, and `health()`. What differs is what the provider guide says
differs between engines — `retrying` retries PostgreSQL's own contention failures (a serialization failure
and a deadlock) and nothing else. The suite that proves it is `assert_provider_contract` from
`xyberos.database.testing`, run against a real server. See
[writing a database provider](../reference/database-providers.md).

## S3-compatible object storage

```python
from xyberos import App
from xyberos.storage import Storage
from xyberos_storage_s3 import S3StorageSettings, s3_storage

app = App()
app.provide(
    Storage,
    factory=s3_storage(S3StorageSettings(bucket="uploads", endpoint_url="https://s3.example")),
    eager=True,
)
```

The provider creates the bucket when it is missing and the settings allow it, and `assert_storage_contract`
proves the contract — including that a key cannot escape its namespace, which is the property
[the storage guide](../reference/storage.md) calls the security boundary. For local work, any
S3-compatible server will do; the compatibility job starts one rather than requiring AWS.

## OpenAI-compatible endpoints

```python
from xyberos import App
from xyberos.ai import ModelProvider
from xyberos_openai_compatible import OpenAICompatibleSettings, openai_compatible_provider

app = App()
app.provide(
    ModelProvider,
    factory=openai_compatible_provider(
        OpenAICompatibleSettings(model="your-model", base_url="https://gateway.internal/v1")
    ),
    eager=True,
)
```

Capabilities are **declared, not guessed**: `chat`, `streaming`, `structured_output`, `tools`, and
`embeddings` are settings, and a request needing one the settings do not claim is refused with
`AIUnsupportedCapabilityError` before any call is made. That is what makes the adapter usable against a
gateway that implements only part of the wire format. `assert_model_provider_contract` checks both sides
of every claim — one that is claimed must work, and one that is not must be refused rather than attempted.

## Server-rendered pages

```python
from starlette.requests import Request
from starlette.responses import Response
from xyberos_templates import Jinja2Templates, TemplatesSettings

templates = Jinja2Templates(TemplatesSettings(directory="templates"))
static_url = templates.mount_static(app, "static")


@app.get("/item")
async def show_item(request: Request) -> Response:
    form = await templates.read_form(request)
    return await templates.render("item.html", {"name": form["name"]})
```

`mount_static` takes the directory to serve and returns the URL path it mounted at, so a page can be
handed the same value it links to instead of repeating a literal in two places.

Two properties are the package's reason to exist, because a bare `Jinja2Templates` provides neither:
**the render happens off the event loop**, so a page that costs real CPU does not hold the loop, and
**autoescape is stated rather than inherited**, so a template named `page.j2` is escaped exactly like
`page.html` — the hole `select_autoescape()` leaves open. The `Templates` contract is engine-neutral, so a
team that would rather write typed components satisfies the same protocol instead of forking the package.
Form reading covers urlencoded and multipart bodies, which is why the package declares `python-multipart`.

## Exposing tools over MCP

```python
from xyberos_mcp import expose

expose(app, tools, path="/mcp")
```

The **client** — consuming another server's tools — is the core module `xyberos.mcp`, so one name answers
one question and this package carries only the server direction. Your already-registered tools are
exposed with their schemas intact, and a tool that raises becomes a JSON-RPC error rather than a `500` that
hides the cause. The **stdio transport is withheld** pending the project owner's decision, because spawning
a process is a policy choice rather than a transport detail, and the package says so plainly. What it does
not provide is an authorization model: [ADR 0014](../reference/adr/0014-no-identity-or-authorization-model.md)
leaves the framework none, so the caller brings one.

## Verifying an assertion

```python
import os

from xyberos_auth import AuthSettings, PrincipalVerifier

verifier = PrincipalVerifier(AuthSettings(audience="checkout", secret=os.environ["AUTH_SECRET"]))
principal = verifier.verify(header.removeprefix("Bearer "))
print(principal.subject)
```

**Verification only.** It answers one question — is this assertion genuine? — and stops. There are no
OAuth2 flows, no OIDC discovery, and no identity-provider presets, and it registers nothing: the
application decides what a principal *means*. Unsigned, expired, and wrong-audience assertions are each
refused, and each has a test. Asymmetric verification through a JWKS is available, with `cryptography`
imported lazily so the shared-secret path needs nothing extra.

## Logging and spans

```python
from xyberos_observability import Observability, ObservabilitySettings

observability = Observability(
    ObservabilitySettings(service="checkout"), exporter=exporter
)
observability.configure_logging()
await workflow.run(on_event=observability.event_sink())
observability.shutdown()
```

One explicit call from the composition root installs a handler, a level, a format, and the runtime's own
`ContextLogFilter`, so **a log line and a span agree on the correlation id** — no monkey-patching, no
hidden thread, and no telemetry the application did not ask for. Spans come from the runtime's own event
sink rather than from patching internals. See [observability](../production/observability.md) for where
the exporter goes.

## Collection queries

```python
from xyberos_crud import CrudSettings, Query, fetch_page

FILTERABLE = {"status": orders.c.status, "created_at": orders.c.created_at}
SETTINGS = CrudSettings(max_limit=100, default_limit=25)


async def list_orders(provider: DatabaseProvider, parameters: dict[str, str]) -> dict[str, object]:
    query = Query.from_parameters(parameters, filterable=FILTERABLE, settings=SETTINGS)
    page = await fetch_page(
        provider, select(orders), query, filterable=FILTERABLE, settings=SETTINGS
    )
    return {
        "items": [dict(row) for row in page.items],
        "has_more": page.has_more,
        "limit": page.limit,
        "offset": page.offset,
    }
```

`from_parameters` takes a mapping rather than a `Request`, so the package needs no HTTP dependency: pass
`dict(request.query_params)`. The query string is `status=open`, `id__gte=10`, `status__in=open,pending`,
`sort=-created_at,name`, `limit=25`, `offset=50`. The excerpt above is the body of a service method that
already holds `provider`, `orders`, and `select`.

The security posture is the package's reason to exist, and it is worth being precise about:

- **A field name is resolved only through the `filterable` mapping you supply.** It is a dictionary key,
  never SQL text and never read off a table with `getattr`, so a name that is not on your list cannot
  reach the database.
- **Operators are an allowlist** (`eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `in`, `contains`, `startswith`,
  `is_null`), configurable per deployment.
- **Values are always bound parameters.** There is no raw-SQL escape hatch anywhere in the package.

It is deliberately **not an ORM**: it takes a table and returns a statement, so it can answer a query
without knowing what a row means. There is also no total count — `has_more` comes from fetching one row
more than the page holds, because a count is a second query whose answer a concurrent write can already
have invalidated. That decision, and the refusals it sits beside, are
[ADR 0023](../reference/adr/0023-crud-package-and-the-dx-refusals.md).

## What is deliberately not here

The same request that produced `xyberos-crud` also asked for an ORM, for CSRF and session middleware, and
for scaffolding that generates resources, routes, forms, and templates. Applying
[ADR 0018](../reference/adr/0018-capability-placement-rule.md)'s rule to them gives three answers rather
than one, and the reasons are recorded rather than implied:

- **CSRF and sessions ship in the framework now.** Both are middleware the application passes
  ([ADR 0024](../reference/adr/0024-sessions-and-csrf-are-middleware-in-the-http-module.md)): the
  mechanism is `xyberos.http`, and the session *store* — which is the policy — is an extension point a
  package beside this line implements.
- **No ORM, no admin UI, no durable session store.** [Where Xyberos fits](../reference/positioning.md)
  lists a batteries-included application as a poor fit *because* those are absent, and points a team
  that wants them at Django, or FastAPI with SQLAlchemy.
- **No scaffolding beyond `xyberos new`.** Generating an application's shape is a decision about that
  application, and a generator would make it the framework's.

[The feature matrix](../feature-support.md) marks every capability above as *Built-in*, *Extension point*,
*You add it*, or *Not provided, and it will not be*, and each row says which package answers it.

## Where the packages live, and how to run one's checks

Source is in [`xyberos/xyberos-plugins`](https://github.com/xyberos/xyberos-plugins), one directory per
distribution, grouped by subject — `db/` holds `db/xyberos_postgres/`, `storage/` holds
`storage/xyberos_storage_s3/`. Each distribution carries its own `pyproject.toml`, version, README, and a
`pyrightconfig.json`, and each is type-checked in strict mode before it can be published.

There are two kinds of check, decided by whether the framework ships a suite for the seam a package
implements:

- **A provider runs the shipped suite** — `assert_provider_contract`, `assert_storage_contract`, or
  `assert_model_provider_contract` — against a real service. That is what makes "we support PostgreSQL" a
  result rather than a claim.
- **A package with no such seam checks what it can**, by importing its own public names against the core
  floor it declares. It is the weaker check, and it is the one that fails when the installed core predates
  a module the package imports.
