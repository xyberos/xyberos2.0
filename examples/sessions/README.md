# sessions example

A session and the cross-site check that makes it safe, on a framework that installs neither for you
([ADR 0024](../../docs/adr/0024-sessions-and-csrf-are-middleware-in-the-http-module.md)).

## Run it

```powershell
python examples/sessions/app.py
```

```text
me: {'user': 'ada'}
the cookie is not the data: True
same origin: 200 printer paper
cross-site status: 403
cross-site body: CSRFError
after logout: {'user': None}
signed out status: 401
```

`pytest tests/integration/test_sessions_example.py`

## The wiring, in full

```python
store = InMemorySessionStore()

adapter = HttpAdapter(
    app,
    middleware=(
        Middleware(SessionMiddleware, store=store, secret=os.environ["SESSION_SECRET"]),
        Middleware(CSRFMiddleware),
    ),
)
```

Two classes the application passes. Nothing is installed behind your back, and neither middleware has
an on-by-default setting — which is the same rule the request-metrics middleware follows
(`HttpAdapter(app, middleware=(...))` is the only shape the adapter offers).

## The five rules this example follows

| Rule | Why |
| --- | --- |
| The **store is an argument**, not a framework default | Where sessions live is a deployment decision — memory here, a table or a cache in production. `SessionStore` is the seam a package beside this line implements |
| The cookie carries an **opaque signed id**, not the data | A handler's values never leave the store, and the module needs no `itsdangerous` because the id is signed with the standard library |
| A session is persisted **only when a handler changed it** | A page that only reads the session costs a load and no write, and an anonymous request that stores nothing sets no cookie at all |
| A **state-changing request from another origin is refused** | `Origin` (or `Referer`) names the site that made the request; a browser attaches it and an attacker cannot forge it. A client with neither header is not a browser cross-site request |
| **A session is not an authorization** | It remembers a decision. *Who may do what* is still yours ([ADR 0014](../../docs/adr/0014-no-identity-or-authorization-model.md)), with the verified principal passed as an argument |

## Adapting it to your deployment

1. **Replace the password check with your identity provider.** Verify a token signature, or call an
   introspection endpoint, and store the resulting `subject` — or the principal itself — in the
   session. `xyberos-auth` verifies the assertion; this example stands in for it so it runs with no
   service.
2. **Replace the store before you go to production.** `InMemorySessionStore` is correct for one process
   and for tests, and a restart signs everyone out. Implement the three members of `SessionStore` — or
   install a package that does — and pass it instead.
3. **Set `trusted_origins` behind a proxy.** If a proxy rewrites `Host`, the origin check cannot work
   out its own origin from the request. Name the origins the application is served from.
4. **Keep the session cookie `SameSite=Lax`** (the default) and set `secure=True` behind HTTPS. The
   origin check and `SameSite` together are what make the simple cases impossible rather than unlikely.
5. **Do not put authorization in the session.** Storage is not policy: a session that says
   `{"role": "admin"}` is a claim you made, and every request that trusts it is a request you have to
   review. Scope the query by the verified principal instead.

## What the framework provides here

`SessionMiddleware`, `CSRFMiddleware`, the `SessionStore` protocol, the in-memory store, and a
`CSRFError` with a `403` the adapter already knows how to answer. That is the whole list — the store
policy, the login, and the authorization model stay with the application, on purpose.
