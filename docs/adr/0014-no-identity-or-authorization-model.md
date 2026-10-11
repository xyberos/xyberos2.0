# ADR 0014: No identity, tenancy, or authorization model

**Status:** accepted

## Context

Every "application framework" a reader has used before ships *something* here: Django has users and
permissions, Flask has sessions through extensions, FastAPI has dependency-injected security
schemes. A reader arriving at Xyberos therefore expects to find an identity story, and finding none
they will assume either that it is unfinished or that it was forgotten. Neither is true, and an
unexplained absence is worse than a stated refusal.

The pressure to build one is real: multi-tenant applications are where the framework is used most,
and "no auth" reads as a gap in the first five minutes of evaluation. So the refusal has to be a
decision with reasons rather than an omission.

## Decision

**Xyberos ships no identity, tenancy, session, or authorization model, and will not.** Three reasons,
in order of weight:

1. **Authorization is a product decision, not a framework decision.** Roles versus scopes versus
   relationship-based access, row-level versus service-level enforcement, delegation, impersonation,
   break-glass — a framework that picks one gets it wrong for most users and becomes responsible for
   security it does not own. Being wrong here is not an inconvenience; it is a breach.
2. **A partial implementation is the worst option available.** A half-built auth layer invites people
   to build on it and then discover its holes, while destroying the one property this project sells to
   regulated users: an auditable surface with nothing unexplained in it.
3. **The correct boundary is upstream.** Identity is usually established by a proxy, an ingress, or an
   identity provider, and it arrives as a signed assertion. Re-implementing that inside an application
   runtime duplicates a system that already has the operational maturity and the audit trail.

**The sanctioned shape when you need tenancy** is explicit, verified, and argument-passed:

- A component that **verifies** the incoming assertion — a signature, a shared secret, a token — and
  returns a principal. A header that is merely *present* is not trusted; what makes it trusted is that
  something checked it.
- The verified principal is **passed to the service as an argument**, and the tenant it carries is
  used to scope queries. The tenant never travels in the request payload, and the service signature
  requires it, so forgetting to pass it is a type error rather than a silent cross-tenant read.
- Context values are **not** an authorization mechanism. `bind_context` and friends are diagnostic
  only, which the [security guide](../security.md) already states; a tenant in `contextvars` is
  ambient authority, and ambient authority is how one request reads another tenant's rows.

The [tenancy example](../../examples/tenancy/README.md) is this pattern, tested, including the case
that matters most: a payload that *claims* a different tenant changes nothing.

**What the framework does provide** is everything the pattern needs and nothing more: an `HttpError`
with the status you choose (`401`, `403`), request-scoped providers for a verifier that caches its
work per request, `app.with_overrides` to fake a principal in tests, and an error policy that never
leaks an internal message to a client.

## Consequences

- **The adopter owns authorization, explicitly.** A deployment that forgets to verify its assertion
  has no authorization at all, and nothing will warn it. The example and this ADR exist to make that
  obligation impossible to miss.
- **The framework cannot enforce tenancy for you**, only make the correct shape the easy one. Code
  review, not the runtime, is what keeps a query scoped — which is also true of every alternative that
  is not a database-per-tenant policy engine.
- **`X-Request-ID` is not an identity.** It is untrusted display data, echoed for log correlation. A
  deployment that treats it as a subject identifier has invented ambient authority out of a
  convenience header.
- Deployments behind a proxy must ensure the assertion header is **stripped from client requests** at
  the edge, or a client can supply its own. This is the one operational failure mode that turns the
  sanctioned pattern into a vulnerability, so it appears in the [security guide](../security.md) and
  the derived checklist in the [positioning page](../positioning.md).
- If a future owner decides to ship an auth subsystem, it needs a new ADR that supersedes this one and
  states which model it chose and why — which is the point of recording the refusal.
