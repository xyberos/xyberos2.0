---
title: Observability
status: verified
---

# Observability

Three questions a running application has to be able to answer: *what happened*, *to which request*,
and *what does this process contain*. The first two are logging, the third is diagnostics, and the
runtime's position on both is deliberately narrow.

## What the runtime configures: nothing

<!-- snippet: examples/learn_production/observability01_logging.py -->

The first line that module prints is the whole policy:

<!-- output: observability01_logging -->
```text
handlers the framework configured: []
GET /orders/7 -> {'order': 7}
GET /orders/9/cancel -> 410 {'error': {'type': 'OrderGone', 'message': 'order 9 is gone'}}
echoed header: req-1
--- records the application's handler saw ---
INFO orders.api looked up order 7 {'correlation_id': 'req-1'}
INFO xyberos.http request failed with OrderGone: order 9 is gone {'correlation_id': 'req-1'}
```

`handlers the framework configured: []` is a promise, not an omission: **the runtime never installs a
handler, sets a level, or picks a format.** A library that configures logging fights the application
that embeds it, and the fight is invisible until two of them disagree. So the module configures the
*root* logger itself, and the records it collects are the two kinds a real deployment has to
distinguish:

| Record | Namespace | Who writes it |
| ------ | --------- | ------------- |
| `INFO orders.api looked up order 7` | the application's own | the handler, in the application's logger |
| `INFO xyberos.http request failed with OrderGone: order 9 is gone` | the framework's | the error-mapping middleware |

Both carry `{'correlation_id': 'req-1'}` because both went through a handler with a
`ContextLogFilter` attached — that is the filter doing the only job the runtime asks of the
application: `ContextLogFilter` copies the current diagnostic context onto each record, so the *sink*
configuration decides what happens to it, not the framework.

### The namespaces, and why they are namespaces

| Logger | What appears in it |
| ------ | ------------------ |
| `xyberos.http` | request failures as mapped, and unhandled errors with their traceback at the level the handler uses |
| `xyberos.plugins` | plugin registration, start, and stop, attributed to the plugin by name |
| `xyberos.workflow` | workflow validation and execution outcomes |
| `xyberos.ai` | provider calls and their failures, without prompt or completion bodies |
| `xyberos.durable` | lease, recovery, and parked-attempt decisions |

Naming one of them, or all of them with `logging.getLogger("xyberos")`, is a choice you make; nothing
is configured for you, so `xyberos.ai` at `DEBUG` in one environment and `WARNING` in another is a
deployment decision rather than a code change.

## The request pipeline, in order

The adapter builds the middleware stack once, and the order is the design:

1. **correlation id** — reads the incoming header (default `X-Request-ID`), or mints one, and binds it
   to the context before anything else can log.
2. **error mapping** — turns a raised `HttpError` into its status and body, and everything else into a
   generic `500`, logging both.
3. **request scope** — opens the request's dependency and cleanup boundary. Everything resolved for
   this request is created inside it and released when it ends.
4. **your middleware** — the list you passed to `HttpAdapter(..., middleware=[...])`.
5. **the router** — the compiled routes.

`echoed header: req-1` in the transcript is step 1 from the outside: the id the client sent comes back
on the response, which is what makes a client-side trace and a server-side log line the same trace. A
proxy that generates the header itself should *strip* what the client sent, which is the same rule
[the identity lesson](../learn/traditional/08-identity.md) applies to assertion headers.

## The context a log line survives

A correlation id is only useful if it is still there when the work has moved to another task or
thread. The honest answer has two halves, and both are measured:

<!-- snippet: examples/learn_production/observability02_context.py -->

<!-- output: observability02_context -->
```text
before anything is bound: {}
inside the request: {'correlation_id': 'req-7', 'tenant': 'acme'}
a task: {'correlation_id': 'req-7', 'tenant': 'acme'}
create_task_in_context: {'correlation_id': 'req-7', 'tenant': 'acme'}
asyncio.to_thread: {'correlation_id': 'req-7', 'tenant': 'acme'}
run_in_executor, uncarried: {}
capture_context_runner, in that executor: {'correlation_id': 'req-7', 'tenant': 'acme'}
hand-started threads saw: [{}, {'correlation_id': 'req-7', 'tenant': 'acme'}]
a deadline is bound: True
and the deadline afterwards: None
after the block: {}
```

Read that as three rows of a table rather than a list of prints:

| Boundary | Does the context arrive? | Why |
| -------- | ------------------------ | --- |
| `asyncio.create_task` | yes | Python 3.11+ copies the context into a new task. On 3.10 it does not, which is why `create_task_in_context` exists and is used explicitly above |
| `asyncio.to_thread` | yes | it copies the context into the worker thread itself |
| `loop.run_in_executor`, a hand-started `threading.Thread` | **no** | the executor's threads start from an empty context and the call does not wrap the function |

The last row is the boundary that actually loses work's identity, and `capture_context_runner(func,
*args)` is the answer: called in the originating context it returns a runner bound to a copy of that
context, so a blocking library call or a worker thread keeps the request's id and its deadline. Note
the deadline in the transcript — `bind_deadline` is scoped, so it is present inside the block and
`None` immediately after; a context that leaked would be worse than one that is lost, because the next
request would inherit it.

## Asking a process what it contains

`app.diagnostics()` is the third question, and it answers with *sources* rather than values:

<!-- snippet: examples/learn_production/observability03_diagnostics.py -->

<!-- output: observability03_diagnostics -->
```text
state before start: new
providers:
  Prices [app] from a deployment override
  Quote [app] from the pricing module
plugins:
  (none)
state while serving: ready
the service resolved: Quote
records: Prices (app), Quote (app)
request scope exists too: request
state after stop: stopped
starting it again: LifecycleStateError - cannot start an application in 'stopped' state
```

The interesting line is the first provider: `Prices [app] from a deployment override`. The module
registers `Prices` twice — once as itself, then again with `replace=True` and a `source` — and the
record names the *later* registration, which is exactly the question an operator asks when a value is
not what they deployed. Sources are filled in as `application`, `a test override`, `plugin:<name>`, or
whatever string a module passes, and `xyberos check` prints the same field
([deploying it](deploy.md) shows the report).

`plugins: (none)` is not a failure: a plugin declares its own metadata, and this application has none.
A plugin's line reads `audit 1 [registered] requires: -`, so a diagnosis includes what was loaded and
in what order.

## What to hook up

| Signal | Where it comes from | What to do with it |
| ------ | ------------------- | ------------------ |
| one id per request | the adapter's correlation middleware | log it on every line (`ContextLogFilter`), return it (`X-Request-ID`), and let the proxy strip what the client sent |
| request outcomes | `xyberos.http` records | alert on the *rate* of `unhandled error while serving a request`, not on one line |
| errors a client sees | the error body's `type` | the type is stable and public; the message is the mapped one, and internal detail is not in it ([security](security.md)) |
| readiness | your `/health` route | a load balancer wants the database, not the event loop ([deploying it](deploy.md)) |
| what is registered | `app.diagnostics()` | log it once at startup, so a diff between two deployments is a text comparison |
| cost and outcome per unit of work | your own usage rows | the [hybrid path's usage lesson](../learn/hybrid/10-usage.md) builds the table; the framework does not |

## Common mistakes

- **Configuring the `xyberos` logger and nothing else.** An application's own lines and the framework's
  live under different names; the root logger is the one that catches both.
- **Attaching the context filter to the formatter instead of the handler.** The filter belongs on the
  handler; a formatter receives only what it was given.
- **Assuming a task inherits the context without checking the Python version.** On 3.10 you need
  `create_task_in_context`.
- **Losing the id at an executor boundary and reconstructing it from timestamps later.** The transcript
  above is that failure mode, in one line: `run_in_executor, uncarried: {}`.
- **Logging prompt or completion bodies to make a model call debuggable.** The AI namespace logs calls
  and failures, not payloads; whatever you add is yours to redact
  ([the AI security lesson](../learn/ai/17-security.md)).
