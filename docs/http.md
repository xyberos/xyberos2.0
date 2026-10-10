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

## Error policy

| Raised | Response |
| --- | --- |
| `RequestValidationError` | its status (default `422`) with `type`, `message`, and `errors` |
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
