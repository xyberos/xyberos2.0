# Security guide

> Status: Phase 7. This guide states the trust model, the handling rules for secrets and untrusted
> input, and — just as importantly — what Xyberos does not protect you from. The per-subsystem
> policies live in the [AI guide](./ai.md#security-and-operations-policy), the
> [plugin guide](./plugins.md#trust-boundary), and the
> [durable execution guide](./durable.md).

## The trust model, stated once

Xyberos is a **framework for a trusted application, not a sandbox for untrusted code.** Everything
you write runs in one process with the privileges of that process:

- **Trusted:** your application code, plugins, step functions, provider factories, tool handlers, the
  services you register, and anything you deploy alongside them. Adding a plugin is equivalent to
  importing a library — there is no permission model, no isolation, and no attempt to limit what a
  plugin does with the objects it is handed.
- **Untrusted:** HTTP requests, query strings, headers, and bodies; model output of every kind; data
  returned by an external service or a webhook; files and environment variables you do not control;
  and anything a workflow step reads from outside the process.

The framework's job is to keep those two sets apart at the boundaries: it never executes what a model
returns, never echoes an internal message to a client, never logs a prompt unless you ask it to, and
never persists anything you did not hand it as a step output.

## Secrets

- **Keep secrets in the environment, never in `xyberos.toml`.** Settings precedence is explicit
  arguments, then `XYBEROS_`-prefixed environment variables, then the file, then defaults, so
  `XYBEROS_AI__OLLAMA__BASE_URL` or your provider's key can live in the environment while the file
  stays in version control. The examples in this repository contain no credentials.
- **Configuration errors never echo a value.** A `ConfigurationError` names the field, its source, and
  the expected type; it does not print what you configured. Provider diagnostics report a contract
  name, a scope, an `eager` flag, and a source — never a value — and plugin diagnostics report a name,
  an API version, a state, and requirements.
- **A provider URL that embeds credentials is rejected.** An Ollama `base_url` carrying user
  information is refused outright, and the rejection never quotes the value it rejected, because the
  rule exists precisely so a credential cannot reach a log. Keep credentials in whatever the
  provider's own mechanism is (a header, a proxy, an environment variable), not in the URL.
- **Nothing that may contain a secret is interpolated into a message.** The database URL is the other
  place a credential lives: it is escaped before Alembic reads it, and a migration failure reports a
  redacted form with the password scrubbed from the underlying error, because a traceback is the
  ordinary way configuration reaches a log.
- **Model prompts are metadata-only by default.** The `xyberos.ai` logger records provider, model,
  outcome, message and tool counts, durations, and token usage — not content. Capturing content is an
  explicit opt-in (`LoggingPolicy.capturing(...)`) that truncates and applies literal `redact` values
  before logging. If you turn it on, every secret you might send lives in the `redact` tuple or it is
  in your logs.
- **Redact at the boundary your secrets are known.** `LoggingPolicy(redact=(...))` is literal
  replacement; it cannot recognise a secret it was not told about, and it does not reach the HTTP
  server's own access log or your logging stack's retention.

## Untrusted input

| Boundary | What the framework does | What remains yours |
| --- | --- | --- |
| HTTP request bodies | `read_json_object(request)` returns a JSON object or raises a client-safe `RequestValidationError`; a malformed body never reaches your code | Validating the *meaning* of the payload, and the request size limit, which belongs to the ASGI server. Xyberos reads the body you ask it to read |
| HTTP responses | A domain error's message is returned only when it derives from `HttpError`; anything else becomes `500` with a generic body, and the traceback goes to the log | Choosing what a domain error says, because that text is client-visible |
| Correlation IDs | A client-supplied `X-Request-ID` is accepted, echoed, and logged | Treating it as untrusted display data. It is an identifier for correlating logs, not for identity, tenancy, or authorization |
| SQL | `xyberos.database` exposes SQLAlchemy Core; statements are built as expressions, and parameters are bound | Never building SQL by string interpolation. The provider does not parse or sanitize SQL, because expression construction already avoids the problem |
| Filesystem paths | A journal path, a database path, or a migration directory is configuration, resolved at startup | Never deriving a path from request input. A path from a request is the classic traversal bug, and no layer here inspects it for you |
| Model output | Nothing a model returns is executed. A tool call is resolved against the caller's allowlist, validated against the declared schema, and only then run | Treating completion text as data: escape it before a shell, a query, a template, or another model call. Register no tool whose side effects you would not run on model output |
| Tool access | The tool set *is* the allowlist, and a handler receives no container, so tool access is auditable at the call site | Deciding which tools an agent may have, and keeping the number small |
| Durable step output | A step's output is persisted verbatim in the journal | Redacting before you return it. This is the one place prompt text can reach a database |
| Plugin configuration | Config is validated against the plugin's declared `config_type`; unknown keys are rejected | Deciding which plugins are trusted enough to hold a database handle or an API key |

## Resource limits

A denial of service does not need a hostile actor: an unbounded retry, an unbounded queue, or an
unbounded journal will take an application down on its own.

- **Retries are bounded.** A workflow retry policy has a maximum attempt count, `database.retrying`
  has an attempt count and a delay, and neither waits indefinitely for a lock. There is no
  configuration that makes a retry unbounded.
- **Timeouts are explicit.** Workflow steps and workflows have timeouts, AI requests have budgets,
  and `settings.app.shutdown_timeout` bounds the shutdown drain. A missing timeout is a decision, not
  an accident.
- **The journal has a payload ceiling.** `max_payload_bytes` refuses an oversized input or output
  rather than writing it, and terminal executions can be deleted to bound the file
  ([retention](./durable.md#growth-and-retention)). Deleting them destroys the audit trail, so do it
  deliberately.
- **The application database has one writer.** SQLite serialises writers; a transaction held across a
  network call will make every other writer wait. Keep write transactions short and never hold one
  across I/O.
- **Failure is loud, not silent.** A refused write, an expired lease, or an unresolved attempt is
  reported as that specific condition — never as "no rows matched" — so an incident has a named
  cause. See the [troubleshooting guide](./troubleshooting.md).

## What is not protected here

State these to yourself before relying on the framework:

- **No sandbox, ever.** Plugins, step functions, and tool handlers run in your process. Isolation is
  an operating-system or container concern.
- **No authorization or identity model.** Xyberos has no users, roles, sessions, or tenancy. Context
  values are diagnostic only and must never be used for identity, authorization, or transaction
  handles.
- **No secret manager.** The framework reads configuration from the environment and a file. It does
  not fetch, rotate, or audit secrets.
- **No request size or rate limits.** Those belong to the ASGI server and the reverse proxy in front
  of it. Choose them there.
- **No TLS and no header hardening.** An ASGI server terminates TLS; security headers, CORS, and
  trusted-proxy handling are yours to configure in the adapter's middleware.
- **No audit log for ordinary requests.** Nothing records who called what. The durable journal records
  workflow transitions, and that is a different thing.
- **No vulnerability scanner and no SBOM generation in the runtime.** Dependency auditing is a
  build-and-release activity, not a runtime feature.
- **No encryption at rest.** A SQLite file is a plain file; its protection is file permissions, disk
  encryption, and where you put it.

## Reviewing a deployment

A short list that catches most mistakes:

1. Secrets are in environment variables, and nothing secret appears in `xyberos.toml`, in a URL, or
   in a test fixture.
2. Every plugin is one you trust, listed explicitly, with the smallest configuration that works.
3. Every tool an agent can call is intended, and its handler is safe to run on model output.
4. `environment = "production"` and `debug = false`; the internal error message never reaches a
   client, and nothing returns a partial success.
5. Timeouts exist on steps, workflows, and model calls, and a retry policy is bounded.
6. The journal and the application database are separate files, on a local filesystem, with
   permissions appropriate to their contents, and a backup that includes the WAL file.
7. Model prompts are the ones your data policy allows, and AI content capture is off unless someone
   asked for it.
8. The ASGI server, not Xyberos, enforces request size limits, rate limits, and TLS.

## Reporting a vulnerability

If a defect in Xyberos itself has security consequences, report it privately rather than in a public
issue. [SECURITY.md](../SECURITY.md) is the policy: what is in scope, what is not, what to expect, and
what happens to a fix. In short: acknowledge within a few working days, assess within about ten,
ship the fix as a patch release when it is contained, and disclose with the release that carries it.
Do not include live credentials or personal data in a report.
