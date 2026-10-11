# tenancy example

How to build multi-tenant access on a framework that deliberately ships **no** identity or
authorization model ([ADR 0014](../../docs/adr/0014-no-identity-or-authorization-model.md)).

## Run it

```powershell
python examples/tenancy/app.py
```

```text
acme sees: {'tenant': 'acme', 'tickets': ['printer is on fire']}
globex sees: {'tenant': 'globex', 'tickets': ['badge reader is broken']}
acme still sees: {'tenant': 'acme', 'tickets': ['printer is on fire']}
unsigned status: 401
unsigned body: UnauthenticatedError
```

`pytest tests/integration/test_tenancy_example.py`

## The four rules this example follows

| Rule | Why |
| --- | --- |
| A header is trusted only because something **verified** it | `PrincipalVerifier` checks an HMAC; a header that merely arrived proves nothing |
| The verified principal is passed to the service **as an argument** | `TicketStore.titles(tenant)` cannot be called without a tenant, so a cross-tenant read is a type error rather than a quiet bug |
| The tenant **never** comes from the request payload | The third line of the transcript is the proof: `globex` posts `"tenant": "acme"` and `acme` sees nothing new |
| Context values are **not** used for identity | They are diagnostic only ([security guide](../../docs/security.md)); a tenant in `contextvars` is ambient authority, which is how one request reads another tenant's rows |

## Adapting it to your deployment

1. **Replace the HMAC with your identity provider.** Verify a token signature, or call an
   introspection endpoint, inside `PrincipalVerifier.verify`. The rest of the example does not change.
2. **Strip the assertion headers at the edge.** If your proxy forwards a client-supplied `X-Tenant`,
   a client can choose its own tenant. The proxy must remove these headers from inbound requests and
   set them only after authenticating.
3. **Scope at the query, not in the response.** Here the tenant is a dictionary key; with a database
   it is a `WHERE tenant_id = :tenant` in every statement, from the verified principal.
4. **Decide your authorization model separately.** This example answers "which tenant", not "may this
   subject do this". Roles, scopes, or policy checks are your design; a framework that guessed would
   be responsible for security it cannot own.

## What the framework provides here

`HttpError` with your status (`401`, `403`), request-scoped providers if a verifier should cache its
work within one request, `app.with_overrides` to fake a principal in tests, and an error policy that
never leaks an internal message to a client. That is the whole list, on purpose.
