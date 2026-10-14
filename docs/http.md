# HTTP guide

> Status: Phase 2. The adapter is preview API and lives in the optional `http` extra.

Install it with `pip install "xyberos[http]"`, which provides Starlette and `httpx` (the Starlette
test client is built on `httpx`). Importing an adapter module without the extra fails with that
command, not a bare `ModuleNotFoundError`.

Xyberos owns the runtime — configuration, dependency resolution, lifecycle, and route records.
Starlette owns ASGI mechanics: routing internals, request/response types, middleware plumbing,
and the test client. Importing `xyberos` never imports Starlette.

## Wiring the adapter

```python
from xyberos import App
from xyberos.http import HttpAdapter

app = App()
# ... provide dependencies and register routes ...
asgi_app = HttpAdapter(app).asgi_app
```

`HttpAdapter(app)` validates handler signatures immediately, so a bad handler fails before the
application is ever served. The ASGI application is cached and rebuilt only when routes change.

## Registering routes

```python
from typing import Annotated

from xyberos import Inject


class ItemService:
    async def list_items(self) -> list[str]:
        return []


@app.get("/items")
async def list_items(items: Annotated[ItemService, Inject()]) -> list[str]:
    return await items.list_items()


@app.get("/items/{item_id}")
async def get_item(item_id: int) -> dict[str, int]:
    return {"item_id": item_id}
```

`get`, `post`, `put`, `patch`, and `delete` are decorators. `app.route(method, path, handler,
name=...)` registers a handler directly. Registration is rejected after `app.start()`.

Route records are dependency-free (`xyberos.Route`), and the registry rejects a duplicate
method+path, a duplicate route name, an unsupported method, a malformed path template, or a
non-callable handler.

## Handler parameters

Every parameter must be exactly one of these, or registration fails:

| Parameter | Sourced from |
| --- | --- |
| `Annotated[T, Inject()]` | the dependency graph, resolved inside the request scope |
| a name that appears in the route template | the path segment, converted to `str` or `int` |
| `request: Request` | the Starlette request |

Read query strings, headers, and bodies from the `Request`. `read_json_object(request)` returns
a JSON object or raises a client-safe validation error, and is the recommended way to read a
JSON body. A required parameter that cannot be supplied is never silently invented.

## Validating a body or a form

There is no validation library to install, because the framework already ships a JSON Schema subset for
the AI facade: [`validate_payload`](./ai.md) is exported from `xyberos.ai` and validates any
value, not only a model's reply. It raises `AISchemaError` rather than a `HttpError`, so the mapping
below is the whole recipe — translate it and the adapter answers `422` with the shape the error table
describes.

```python
from starlette.requests import Request
from starlette.responses import JSONResponse

from xyberos import RequestValidationError
from xyberos.ai import validate_payload
from xyberos.errors import AISchemaError
from xyberos.http import read_json_object

NEW_ITEM = {
    "type": "object",
    "properties": {"name": {"type": "string", "minLength": 1}, "quantity": {"type": "integer", "minimum": 1}},
    "required": ["name"],
    "additionalProperties": False,
}


@app.post("/items")
async def create_item(request: Request) -> JSONResponse:
    body = await read_json_object(request)  # a body that is not a JSON object is already a 422
    try:
        validate_payload(body, NEW_ITEM, location="the create-item body")
    except AISchemaError as error:
        raise RequestValidationError("the request body is invalid", errors=[str(error)]) from error
    return JSONResponse({"created": body["name"]}, status_code=201)
```

Verified against the adapter's test client: a valid body answers `201`, a missing required property and a
misspelled field both answer `422`, and `errors` carries the failing location —
`"the create-item body at $ is missing the required property 'name'"`. `read_json_object` raises a
`RequestValidationError` too, so a body that is not JSON, or is JSON but not an object, is a `422` from the
same code path rather than a `500`.

Two properties of that shape are worth keeping. `additionalProperties: False` is what makes a typo in a
field name a `422` rather than a silently ignored key, and the schema is declared once at module level,
so `check_schema` runs on the same object every request instead of validating a schema built per call. A
form submission is read the same way — `xyberos-templates` gives you `read_form(request)` — and the
object it returns goes through the same `validate_payload` call.

## Responses

| Handler returns | Response |
| --- | --- |
| a `Response` | sent unchanged |
| `None` | `204 No Content` |
| anything else | `200` JSON, via Starlette's `JSONResponse` |

A value that cannot be serialized becomes a `500`, never a partial success.

## Lifespan

`HttpAdapter` runs the runtime inside the ASGI lifespan: `App.validate()` (provider graph and
handler signatures) then `App.start()` complete before any request is accepted, and
`App.stop()` releases resources after the server stops taking work. A request that arrives
before startup completes is rejected with a `500` rather than being served by a half-started
application.

## Middleware order

Outermost to innermost:

1. **Correlation ID** — binds the request ID so every log line and error response carries it.
2. **Error normalization** — converts failures into responses (below).
3. **Dependency request scope** — one `RequestContext` per request, closed after the response.
4. **Application middleware** — the `middleware=[...]` sequence passed to `HttpAdapter`, in order.
5. **Router and endpoint** — handler injection and response conversion.

Application middleware therefore sees a bound correlation ID and can resolve request-scoped
services, because both happen further out.

### Counting requests

Request metrics ship as a middleware class, not as an installed feature: Xyberos configures nothing
behind an application's back, so the application passes it and holds the counters
([ADR 0018](adr/0018-capability-placement-rule.md)).

```python
from starlette.middleware import Middleware

from xyberos.http import HttpAdapter, RequestMetrics, RequestMetricsMiddleware

metrics = RequestMetrics()
adapter = HttpAdapter(
    app, middleware=(Middleware(RequestMetricsMiddleware, metrics=metrics),)
)

# after serving:
for row in metrics.snapshot():
    print(row.route, row.status, row.count)
```

The counters are keyed by the **route template**, not the raw path: a request for `/users/1234` is
counted under `/users/{user_id}`, because a counter keyed by the path itself grows without bound. A
request that matched no route is counted under `<unmatched>` for the same reason, and once
`max_routes` distinct routes have been seen the rest are folded into `<other>`. Nothing is exported
and nothing runs in the background — read `snapshot()` on a schedule the deployment owns.

Because the middleware sits *inside* error normalization, a failure is counted at the status the
client will receive: a handler raising a 404 `HttpError` is one 404, not a 500. A request that
produced no response at all is counted as 500, which is what reaches a client unless an outer
middleware maps it.

### Sessions and CSRF

Both ship as middleware classes the application passes and owns ([ADR 0024](adr/0024-sessions-and-csrf-are-middleware-in-the-http-module.md)),
because each bundles a policy that belongs to the deployment: where session data lives, and which
origins may post to it.

```python
import os

from starlette.middleware import Middleware

from xyberos.http import (
    HttpAdapter,
    InMemorySessionStore,
    SessionMiddleware,
    CSRFMiddleware,
    get_csrf_token,
)

store = InMemorySessionStore()   # one process, and tests; a durable store is a package beside this line

adapter = HttpAdapter(
    app,
    middleware=(
        Middleware(SessionMiddleware, store=store, secret=os.environ["SESSION_SECRET"]),
        Middleware(CSRFMiddleware),
    ),
)

@app.post("/login")
async def login(request: Request) -> dict[str, str]:
    request.session["user"] = "ada"        # `scope["session"]`, so `request.session` is the spelling
    return {"user": "ada"}

@app.get("/form")
async def form(request: Request) -> dict[str, str]:
    return {"csrf_token": get_csrf_token(request)}
```

**Sessions.** `SessionMiddleware` signs a session **id** into the cookie with the standard library, so
the module needs no `itsdangerous` and a handler's values never leave the store. The store is a
three-member protocol — `load`, `save`, `delete` — and `InMemorySessionStore` is the shipped
implementation: correct for one process and for tests, and not durable. A session is written **only
when a handler changed it**, so a request that reads one costs a load and no write, and an anonymous
request that stores nothing sets no cookie at all. `get_session(request)` is the same object as
`request.session`, with a type a checker can use and an error that names the missing middleware.

**CSRF.** `CSRFMiddleware` refuses a state-changing request whose `Origin` (or `Referer`) names another
site, and one that presents an `X-CSRF-Token` that does not match the token issued to the browser. A
request with neither header is not a browser cross-site request — `curl` cannot be the victim — so it
is allowed; set `require_token=True` to demand the token anyway, and `trusted_origins` when a proxy
rewrites `Host`. The token cookie is readable on purpose, because a page has to echo it back, and it
carries no authority on its own.

Neither middleware is installed for you, and neither is on by default — the same rule the counters
above follow.

## Error policy

| Raised | Response |
| --- | --- |
| `RequestValidationError` | its status (default `422`) with `type`, `message`, and `errors` |
| `CSRFError` (from `CSRFMiddleware`) | `403` with `type` and `message` |
| any other `HttpError` subclass | its declared `status_code` with `type` and `message` |
| any other exception | `500` with a generic body; the traceback is logged, never returned |

Define domain errors by subclassing `HttpError` and choosing a status:

```python
from xyberos import HttpError


class ItemNotFoundError(HttpError):
    def __init__(self, item_id: int) -> None:
        super().__init__(f"item {item_id} was not found", status_code=404)
```

A programmer error is never translated into a successful response, and internal messages are
never sent to a client. If a response has already started, a later failure is re-raised instead
of corrupting the stream.

Error bodies are shaped as:

```json
{"error": {"type": "ItemNotFoundError", "message": "item 7 was not found"}}
```

## Correlation IDs

The adapter reads `X-Request-ID` or generates one, binds it as the runtime's correlation ID
(available through `get_correlation_id()`), and echoes it on every response, including errors.
Override the header name with `HttpAdapter(app, request_id_header="...")`.

## Testing

```python
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

with create_test_client(HttpAdapter(app)) as client:
    assert client.get("/items").json() == []
```

Use the client as a context manager so the lifespan runs. `create_test_client` also accepts a
bare ASGI application. `app.with_overrides({...})` gives you an isolated application whose
registered services resolve to test values.
