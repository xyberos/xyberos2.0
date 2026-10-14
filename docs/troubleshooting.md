# Troubleshooting guide

> Status: Phase 7. This guide is organized by the error you are looking at. Every message quoted
> here is real output from the implementation, not a paraphrase: the point is that you can match
> what you see to a cause and a fix without reading the source.

Xyberos errors are namespaced by subsystem and rooted at `XyberosError`, so a bare `except
XyberosError` catches everything this framework raises while nothing else is caught. Each message
carries the facts needed to act on it: the field, the contract, the resolution path, or the release
that removed the API.

## Start here: three commands

```python
app.validate()               # provider graph and handler signatures, without constructing services
print(app.diagnostics().render())
print(app.routes)
```

`validate()` is the check to run when something is wrong before startup. `diagnostics()` answers
"where did this provider come from?", which is the question to ask when a value is not what you
expected. And the output is small enough to paste into a bug report:

```text
providers:
  Repository [app] from application
  Service [app] from application
plugins:
  (none)
```

A provider's `source` is `application`, `test override`, or `plugin:<name>`, so a service registered
by a plugin is never mistaken for one the application registered.

## Core runtime

| Error | Message you will see | Cause and fix |
| --- | --- | --- |
| `MissingProviderError` | `no provider is registered for Repository; required by Service` | A declared dependency has no registration, or the registration happens after the consumer. Register the dependency, or check that a plugin supplying it was actually added. `error.path` lists the chain, outermost first |
| `DependencyCycleError` | names both ends of the cycle | Two services depend on each other. Break the cycle with a factory that resolves lazily, or move the shared part into a third service |
| `ScopeViolationError` | `app-scoped Holder cannot depend on shorter-lived request-scoped RequestThing` | A long-lived service captured a short-lived one. Register the consumer in the shorter scope, or pass the per-request value as an argument instead of injecting it |
| `DependencyResolutionError` | `request-scoped RequestThing requires an active request context` | You resolved a request-scoped service outside a request. Use it from a handler, or open `async with app.request_context():` |
| `LifecycleStateError` | `cannot create a request context while application state is 'new'` | The application was never started. Wrap the work in `async with app.lifespan():`, or start the ASGI application through its lifespan |
| `LifecycleStateError` | names the operation and the current state | Registration or resolution happened too late, or after the application stopped. An `App` is one-shot: create a new one instead of restarting it |
| `ShutdownError` | one message per failure, and `.resources` names them | One or more `close`/`aclose` hooks failed. Every hook still ran; fix them in `error.resources` order, or set `settings.app.shutdown_timeout` if a drain is hanging |
| `ConfigurationError` | names the field, its source, and what was expected | A setting is unknown, has the wrong type, or the `schema_version` is unsupported. The message says which source it came from — file, environment, or argument — so a surprising environment variable is found immediately |

`RegistrationError` reports an ambiguous or frozen registration: two providers for one contract
without `replace=True`, a factory with an unmarked required parameter, or `*args`/`**kwargs` in a
factory. The fix is always to be explicit, never to rename a parameter and hope.

### "My service gets the wrong instance"

Ask `diagnostics()` first. A provider registered twice keeps the first registration unless the second
passes `replace=True`, and a test override outranks both. If the source is `plugin:<name>`, the plugin
registered it during `add_plugin`.

## HTTP

| Error | Cause and fix |
| --- | --- |
| `RouteRegistrationError` at startup | A duplicate method+path, a duplicate route name, a malformed path template, an unsupported method, or a handler parameter that is neither injected, a path parameter, nor `Request`. The message names the parameter or the route |
| A `500` with `{"error": {"type": "InternalServerError", ...}}` | An unhandled exception reached the adapter, *or* the request arrived before startup finished. Check the log: the traceback is logged, never returned |
| A `500` on every request in a test | The test client was used outside its context manager, so the ASGI lifespan never ran. See the [testing guide](./testing.md) |
| A domain error returned as `500` | The error does not derive from `HttpError`. Subclass it and pass `status_code=` to control the response |
| A `403` with `{"error": {"type": "CSRFError", ...}}` | `CSRFMiddleware` refused a state-changing request: its `Origin` (or `Referer`) named another site, or the presented `X-CSRF-Token` did not match the issued one. A proxy that rewrites `Host` needs `trusted_origins` ([the HTTP guide](./http.md#sessions-and-csrf)) |
| `get_session` raises `ConfigurationError`, or `request.session` raises `AssertionError` | `SessionMiddleware` is not in the stack. Pass it in `HttpAdapter(app, middleware=(...))` ([the HTTP guide](./http.md#sessions-and-csrf)) |
| A response never arrives | If the response had already started when the error happened, the adapter re-raises instead of corrupting the stream, so the failure appears in the log rather than in the body |

## Database

| Error | Cause and fix |
| --- | --- |
| `DatabaseConfigurationError` | An unsupported PRAGMA value or a missing path. The message names the setting |
| `DatabaseConnectionError` | The file is not writable, the directory does not exist, or a path points at a network filesystem, where SQLite locking is not dependable |
| `TransientDatabaseError` | A write could not take the lock within `busy_timeout_ms` and the bounded retry budget ran out. Shorten transactions, keep a write transaction away from network calls, or raise `busy_timeout_ms`. It is never an unbounded wait |
| `TransactionError` | A commit failed for a reason other than lock contention, or the body raised. The original SQLAlchemy error is preserved as the cause |

## Plugins

| Error | Cause and fix |
| --- | --- |
| `PluginValidationError` | A duplicate plugin name, a missing or duplicated API version, or a `register` hook that failed. The message names the plugin |
| `PluginCompatibilityError` | The plugin's `api_version` is not the one this package implements. Compare the plugin's declaration with `xyberos.plugins.PLUGIN_API_VERSION` |
| `PluginConfigurationError` | A required configuration key is missing, or an unknown key was supplied. Plugin configuration is validated against the plugin's `config_type`, so the message names the key |
| `PluginDependencyError` | A declared requirement was not registered first, or requirements form a cycle. Plugin order is explicit: reorder `add_plugin` calls |
| `PluginLifecycleError` | A `start` or `stop` hook raised. The application still attempts the remaining hooks and reports every failure |

## Workflow

| Error | Cause and fix |
| --- | --- |
| `WorkflowValidationError` | The definition cannot be compiled: a cycle, a missing start step, an unreachable step, an ambiguous merge, or two edges leaving one step. `workflow.render()` shows what was built |
| Synchronous step function rejected | A blocking or CPU-bound function would stall the loop and could not be cancelled. Wrap it in `await asyncio.to_thread(...)` inside an async step |
| `RetryExhaustedError` | The step's retry policy ran out. The message reports every fact you need: `RetryExhaustedError: step 'fetch' failed after 3 attempt(s) with RateLimitError`. Raise the budget, or let it out as `WorkflowExecutionError` |
| `StepTimeoutError` / `WorkflowTimeoutError` | One attempt exceeded its timeout, or the whole workflow exceeded its deadline. Both are deterministic under a `ManualClock` |
| `WorkflowCancelledError` | Cancellation was requested before or during execution, including via a deadline |
| A missing or duplicated event | Events are structured and ordered; assert on them rather than on log output |

## AI

| Error | Cause and fix |
| --- | --- |
| `AIConfigurationError` naming the version floor | The provider reports a version below `MINIMUM_SUPPORTED_VERSION`. Upgrade the service, or set `minimum_version` deliberately — the message states the floor and the version it saw |
| `AIConfigurationError` naming an unknown key | The adapter validates its own configuration and rejects keys it does not implement, so a typo fails at startup instead of silently doing nothing |
| `AIModelNotFoundError` | The model is not available. The message includes the `ollama pull` command; Xyberos never downloads models for you |
| `AIUnsupportedCapabilityError` | The request needs a capability the model or adapter does not declare — tools, embeddings, or a schema. Declared capabilities are checked before the call, so this fails without a round trip |
| `AIToolError` | A tool call was unknown, not in the allowlist, carried invalid arguments, or exceeded the loop limit. The message names the allowed tools |
| `AISchemaError` | Structured output did not validate against the schema. Model output is untrusted input; keep the schema closed |
| `AIRateLimitError` / `AITransportError` / `AITimeoutError` | Retryable by default, because they derive from `TransientError`. `AIInvalidPayloadError` is not: a broken response envelope means a version or contract problem |
| The stream ends without content | `chat()` turns a reported refusal into `AIRefusalError`, but `stream()` yields chunks and leaves the decision to the caller: inspect `finish_reason` on the last chunk. The Ollama adapter maps `done_reason` `stop` and `length` exactly and everything else to `FinishReason.OTHER`, so a provider-specific stop reason is not a refusal |

## Durable execution

| Error | Cause and fix |
| --- | --- |
| `DurableSchemaError` | The journal file is older or newer than the package, or is not a journal. A newer file is refused rather than opened at the older worker's risk |
| `DurableLeaseError` | A worker tried to write after losing its lease, or with a stale fence. This is the fencing token doing its job; the write is refused, not applied |
| `DurableVersionError` | A resumable execution references a definition whose fingerprint no longer matches. Either keep the definition or start a new execution id |
| `DurableConflictError` | The same submission id or execution id was used for different work. Execution ids are identity, not a retry mechanism |
| `DurablePayloadError` | An input or output exceeds `max_payload_bytes` or is not JSON-serializable. Persist a reference, or raise the limit deliberately |
| `DurableOutcomeUnknownError` | An attempt was interrupted and its external effect cannot be established. Reconcile the effect and record a decision; see [what happens after a crash](./durable.md#what-happens-after-a-crash) |
| `DurableStateError` | A transition was requested that the persisted state does not allow. Re-read the execution rather than forcing the write |
| An execution is never picked up | An unresolved attempt is never handed out as work. Check `stats.expired_leases` and the parked executions: something must decide, and that decision is yours |

## Warnings

Xyberos warns rather than fails in two situations, both of which are easy to misread in a test run:

- **`ExperimentalWarning`** is emitted by an unstable entry point before it does anything — the
  durable package, for example. It derives from `UserWarning`, so `-W error::UserWarning` turns it
  into a failure on whichever test happens to use it first. It is emitted once per process; filter it
  in `pyproject.toml` and assert the emission in a subprocess if you need to test it.
- **`XyberosDeprecationWarning`** is a `DeprecationWarning`: silent by default, visible under
  `-W default`, and an error under `-W error`. A deprecation states the replacement and the release
  that will remove it, so the fix is in the message. See the [stability guide](./stability.md).

## When you need more than the message

- **Set the level to see the runtime's own logging.** `xyberos.http` logs a request failure at
  `INFO` and an unhandled exception at `ERROR`; `xyberos.ai` logs one metadata-only line per call at
  `DEBUG`; the durable worker passes a logger named `xyberos.durable` to each step through
  `StepContext.logger`, so a step's own diagnostics land in the same place as the rest. The
  authoritative record of durable state transitions is not a log line: it is the journal's event
  timeline, which survives the process that wrote it.
- **Attach `ContextLogFilter`** to a handler to get the current context values on every record as
  `xyberos_context`, which is how a log line is tied to a correlation ID and a request.
- **Remember what context is not.** Context values are diagnostic only: never use them for identity,
  tenancy, authorization, or transaction handles, and do not expect them to survive into a plain
  thread. Use `capture_context_runner(...)` when you need to cross that boundary deliberately.
- **Read the contract, not the behavior.** Every message here comes from a decision recorded in an
  [ADR](./adr/), and the guide for the subsystem states the limits on purpose — including the ones
  that are permanent, such as durable execution being single-instance.

If an error message does not tell you what to do, that is a defect worth reporting: the message is
part of the public surface, and the [contributing guide](../CONTRIBUTING.md) says how to report it.
