---
title: An application that answers HTTP
path: traditional
lesson: 1
tier: built-in
status: verified
verify: output
example: examples/learn_traditional/traditional01_http.py
prerequisites: ["/learn/fundamentals/04-your-first-application"]
---

# Lesson 1 — an application that answers HTTP

## What you will build

The application from the Fundamentals path, answering requests. Two routes, one of them using a
service, and the adapter that turns route records into an ASGI application a server can run.

## What you need

Xyberos with the `http` extra, and an ASGI server when you want to run it for real:

=== "PowerShell"

    ```powershell
    python -m pip install "xyberos[http]" uvicorn
    ```

=== "POSIX"

    ```bash
    python -m pip install 'xyberos[http]' uvicorn
    ```

The rule worth remembering before any code: **the runtime owns composition, Starlette owns ASGI
mechanics.** Route records live in core — that is why `@app.get` works with no extra installed — and the
adapter compiles them.

## The code

<!-- snippet: examples/learn_traditional/traditional01_http.py -->

Three things in that file are the whole lesson:

| Part | What it does |
| --- | --- |
| `@app.get("/")` | registers a route record on the application; nothing has been served yet |
| `HttpAdapter(app).asgi_app` | compiles the records into a Starlette application, validating every handler signature |
| `create_test_client(HttpAdapter(...))` | the client the test suite uses, so this lesson needs no running server |

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_traditional.traditional01_http
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_traditional.traditional01_http
    ```

To run it for real, hand the ASGI application to a server:

=== "PowerShell"

    ```powershell
    uvicorn --app-dir examples/learn_traditional --factory traditional01_http:app_factory
    curl "http://127.0.0.1:8000/health"
    ```

=== "POSIX"

    ```bash
    uvicorn --app-dir examples/learn_traditional --factory traditional01_http:app_factory
    curl "http://127.0.0.1:8000/health"
    ```

`--factory` is not decoration: `app_factory` is *called* by the server to build the application, and
that function is the only place in this file that mentions Starlette. The suite checks that the quoted
command names a factory that really builds an ASGI application.

## What it prints

<!-- output: traditional01_http -->
```text
status: 200
json: {'message': 'Hello, world!'}
health: {'status': 'ok'}
correlation id set: True
```

The last line is worth a second look: every response carries an `X-Request-ID`, either the one the
client sent or a new one. It is the first thing to look for in a log — and it is *untrusted display
data*, never an identity.

## A handler's parameters are its whole interface

| Parameter | Where the value comes from |
| --- | --- |
| `Annotated[T, Inject()]` | the provider graph |
| a name that appears in the route path | the URL, converted to the declared type |
| `request: Request` | Starlette |

Anything else is refused when the adapter is constructed, which is why a handler with a mistake fails
at startup rather than on the first request.

## What a handler may return

| Handler returns | The client receives |
| --- | --- |
| a Starlette `Response` | it, unchanged |
| `None` | `204 No Content` |
| anything else | `200` with the value as JSON |

## Common mistakes

- **Forgetting the adapter.** `app.routes` is a list of route records; nothing serves them until
  `HttpAdapter(app).asgi_app` exists. `xyberos check` works without it, which is a useful way to
  separate "my graph is wrong" from "my server is wrong".
- **Importing Starlette in a service.** The adapter is the one module that should mention it; a service
  that does cannot be tested without the extra.
- **Building the adapter once at import time in a test.** `create_test_client` runs the application's
  lifespan, so build the application *inside* the `with` block or pass a freshly built one, as this
  lesson does.

## Exercise

Add a route `/hello/{name}` that greets whoever is in the URL.

<details>
<summary>Show the answer</summary>

<!-- snippet: examples/learn_traditional/traditional01_exercise.py -->

<!-- output: traditional01_exercise -->
```text
{'message': 'Hello, Ada!'}
```

The path parameter `name` is a handler argument whose name appears in the route, and the adapter
converts it to `str` automatically. Declare it as `int` instead and Xyberos converts it to an integer,
or refuses the request if it is not one.
</details>

## Next

Lesson 2 reads more of the request — query strings, bodies, and the errors that say "no" with a status
code. Until it is published, [the roadmap](../../roadmap.md) shows where each lesson stands.
