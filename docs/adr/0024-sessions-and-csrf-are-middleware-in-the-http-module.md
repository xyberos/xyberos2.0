# ADR 0024: Sessions and CSRF are middleware in the HTTP module

**Status:** accepted; supersedes the sessions/CSRF row of [ADR 0018](0018-capability-placement-rule.md)'s
candidate table

> Accepted by the project owner on 2026-10-14, in the same instruction that introduced the capability.

## Context

[ADR 0018](0018-capability-placement-rule.md) refused sessions and CSRF as a class, with an admin UI,
OpenAPI, RAG, job queues, rate limiting, and feature flags, and justified it with one clause:
*"Starlette ships both and the adapter composes with them, so the gap costs a reader an install rather
than a capability."* [ADR 0023](0023-crud-package-and-the-dx-refusals.md) repeated the clause.

The clause is half true, and the half that is false is the half doing the work.

- **Sessions.** `starlette.middleware.sessions.SessionMiddleware` exists. It needs `itsdangerous`,
  which the `http` extra does not install, so the cost is genuinely one install — and it signs the
  *payload* into the cookie, which puts every value a handler stores on the wire and makes the cookie
  the only store there is.
- **CSRF.** Starlette ships **no** CSRF middleware. `import pkgutil; pkgutil.iter_modules(starlette.middleware.__path__)`
  on 0.52.1 lists `authentication`, `base`, `cors`, `errors`, `exceptions`, `gzip`, `httpsredirect`,
  `sessions`, `trustedhost`, `wsgi` — and no `csrf`. There is nothing to install, so the refusal's
  reason is not an understatement; it is wrong for this half of the row.

That matters because the two halves are not the same kind of decision, and the placement rule already
has a word for each:

- **CSRF is a mechanism, not a policy.** Double-submission and a same-origin check are the canonical,
  uncontested defences, and there is no product decision to get wrong — the equivalent of picking an
  authorization model does not arise. It needs no store, no secret, and no third-party dependency.
  By ADR 0018's own rule it is a **module here**.
- **Sessions bundle a policy — where the data lives.** Cookie, signed cookie, or a server-side store,
  and for a server-side store, which one. That is the deployment's decision, exactly as a database
  provider or a storage backend is, so by the same rule it is a **contract here** with the
  implementation **there**.

The "address it with middleware, not with Django" question arrived in the same breath, and the answer
is the same one ADR 0018 already gives: **middleware is not a plugin.** `HttpAdapter(app,
middleware=(...))` is the only shape the adapter offers, so a cross-cutting request concern is a class
the application passes and nothing installs one behind its back. What was missing was not a mechanism
but a class worth passing.

## Decision

**Ship both as middleware classes in `xyberos.http`, and keep the session store an extension point.**

### CSRF: `xyberos.http.CSRFMiddleware`

- **Two checks, and either refuses.** A state-changing request whose `Origin` (or, failing that,
  `Referer`) names another origin is refused with a `403`; a request that presents an `X-CSRF-Token`
  that does not match the issued one is refused as well. A request with **neither** an origin nor a
  token is not a browser cross-site request — a `curl` client cannot be the victim — so the origin
  check judges nothing and the request is allowed. `require_token=True` closes that door for an
  application that wants the stricter rule.
- **The token cookie is readable on purpose.** A script or a template has to echo it back, so it is not
  `HttpOnly`. It carries no authority on its own: the origin check is what makes it meaningful, and the
  token only closes the case where an attacker can attach a cookie it cannot read.
- **The token is issued by the middleware and read with `get_csrf_token(request)`.** An application that
  reaches for the token without the middleware installed is told what to add rather than handed an
  empty string a form would happily submit.
- **It stays out of the body.** The check reads headers only, so it never consumes the request stream
  and a handler still reads its own form or JSON body afterwards.

### Sessions: a contract here, the store there

- `xyberos.http.SessionStore` is a three-member protocol — `load`, `save`, `delete` — and the session
  id is the key. `save` is told its `max_age`, so expiry is the store's discipline rather than a
  framework guess.
- `xyberos.http.InMemorySessionStore` ships as the dependency-free implementation, is correct for one
  process and for tests, and says in its own docstring that a restart signs everyone out. A durable
  store — a table, a cache — is a **package there**, the same placement as an object-store backend, and
  the protocol is the seam it arrives through.
- `xyberos.http.SessionMiddleware` signs a **session id**, not the payload: the cookie is an opaque id
  and an HMAC built from the standard library, so the module needs no `itsdangerous` and a handler's
  values never leave the store.
- **A session is written only when a handler changed it.** The loaded session is a mapping that records
  its own mutation, so a request that reads a session costs a load and no write, and an anonymous
  request that stores nothing sets no cookie at all. `Session` makes that observable: `modified`,
  `is_new`, and `is_empty` are the three facts the middleware decides on.
- **The session is exposed where Starlette already looks for one.** It is stored under `scope["session"]`,
  so `request.session` works without this module teaching a second spelling, and `get_session(request)`
  is the same object with a type and a failure message that names the fix.

### What does not change

- **Authorization is still absent, and so is identity** ([ADR 0014](0014-no-identity-or-authorization-model.md)).
  A session is a place to remember a decision, not a decision: this ADR ships the mechanism and leaves
  *who is allowed to do what* exactly where it was, with the verified principal passed as an argument.
- **No durable session store ships in this repository.** `InMemorySessionStore` is a development and
  single-process default, not a promise of persistence.
- **Nothing is installed behind the application's back.** Both classes are passed to
  `HttpAdapter(middleware=(...))` and neither has an on-by-default setting.
- **The refusals that were not about these mechanisms stand.** An admin UI, OpenAPI, RAG, job queues,
  rate limiting, and feature flags are refused as they were; this ADR takes the word "sessions" out of
  that row and nothing else.

## Consequences

- **ADR 0018's justification for this row is corrected, not merely narrowed.** "Starlette ships both" is
  false for CSRF and misleading for sessions, and a refusal whose reason is a factual claim has to be
  re-decided when the claim does not hold. The placement of everything else in that ADR's table is
  untouched, and the four constraints in its Decision section bind this ADR exactly as they bind the
  other placements: `xyberos.http` is an extra's path, the store protocol is a contract core may carry,
  and a durable store owns a top-level import root of its own.
- **The capability-placement rule survives its first real test.** This is the first time a *refusal* has
  been revisited without the mechanism changing, and the split above — mechanism here, policy there —
  is the rule applied rather than an exception to it. A future refusal should be re-read the same way:
  a refusal resting on "the dependency already provides it" is a claim about a dependency, and a claim
  about a dependency is checked.
- **`xyberos.http` grows two modules and eight public names** — `CSRFMiddleware`, `CSRF_COOKIE`,
  `CSRF_HEADER`, `SAFE_METHODS`, `get_csrf_token`, `SessionMiddleware`, `Session`, `SessionStore`,
  `InMemorySessionStore`, `SESSION_COOKIE`, `DEFAULT_SESSION_MAX_AGE` — and one error, `CSRFError`, in
  `xyberos.errors`. They are preview API, like the rest of the module, so a minor release may move them
  with upgrade notes ([ADR 0013](0013-stable-surface-and-versioning.md)).
- **A session store is now a named extension point with no shipped backend.** A store with a client
  library, a store that survives a restart, and a store shared between workers are each a package there.
  The in-memory store is deliberately not the answer to "where do sessions live in production".
- **The interesting failure mode is the origin check behind a proxy.** A deployment that rewrites `Host`
  has to pass `trusted_origins` rather than rely on the request's own host, and the module says so where
  a reader configuring the middleware will see it. This is the same class of operational caveat as
  "strip the assertion header at the edge" in [ADR 0014](0014-no-identity-or-authorization-model.md),
  and it belongs in the guide rather than in the code.
- **The example is the acceptance test.** [`examples/sessions`](../../examples/sessions/README.md) is a
  login, a protected route, and a form post, and its suite proves the three properties that make the
  capability worth shipping rather than merely present: a cross-origin post is refused, the session
  cookie is not the data, and a read does not write.
