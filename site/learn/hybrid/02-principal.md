---
title: A verified principal, and what it may do
path: hybrid
lesson: 2
tier: not-provided
status: verified
verify: output
example: examples/learn_hybrid/hybrid02_principal.py
prerequisites: ["/learn/hybrid/01-tickets"]
---

# Lesson 2 — a verified principal, and what it may do

## What you will build

Who is calling. Xyberos ships no identity model and no authorization model, and
[ADR 0014](../../reference/adr/0014-no-identity-or-authorization-model.md) says why: a framework cannot
guess what your assertion looks like. What it provides is the shape — a component that *verifies*
rather than believes, a principal that travels as a required argument, and `HttpError` subclasses whose
status codes you choose.

The one thing this lesson adds to the traditional path's version is the **tenant**, and it is here
rather than in the request for a reason: a payload that names a tenant cannot move a lookup, because
the lookup never reads the payload.

## What you need

Nothing new.

<!-- snippet: examples/support_desk/security.py -->

<!-- snippet: examples/learn_hybrid/hybrid02_principal.py -->

`PrincipalVerifier.verify` is the only place a request becomes a fact. Until it returns, nothing in the
request is known: the headers are assertions that arrived, and they are trusted because a shared secret
signed them, not because they said so.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_hybrid.hybrid02_principal
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_hybrid.hybrid02_principal
    ```

## What it prints

<!-- output: hybrid02_principal -->
```text
no assertion -> 401 the request is not authenticated: X-Authenticated-Subject and X-Authenticated-Tenant are both required
a forged signature -> 401 the request is not authenticated: the assertion signature does not match
ada sees: 2 ['Where is my refund?', 'The badge reader is broken']
grace sees: 0
sam (an agent) sees: 2
a requester classifying -> 403 this operation requires support_agent or support_lead
another tenant's agent sees: 0
and reading acme's ticket 1 -> 404 ticket 1 was not found
```

Read the last two lines together. Another tenant's agent sees **nothing** — `0` tickets — and reading
acme's ticket by its id is a `404`, not a `403`. That is deliberate: a `403` would confirm that ticket
1 exists, which is the one thing a caller in another tenant must not learn. The tenant is part of the
query, so there is no row to refuse.

The `403` for the requester who tried to classify is the other half: the subject is known, the answer
is no, and the caller can tell the difference between "authenticate" and "you may not".

## Common mistakes

- **Trusting a header because it is there.** A header is not a fact until something verified it. The
  forged-signature line is what that looks like when it fails closed.
- **A check after the load.** `_row` in `service.py` looks up `id` **and** tenant together, so there is
  no window in which a ticket from another tenant is in memory.
- **Roles from the request body.** Roles come from the verified assertion. A role a client can name is
  not a role.
- **`403` where `404` belongs.** Existence is information. For a resource in another tenant, the honest
  answer is that there is no such resource *for you*.
- **An authorization helper that returns a boolean.** A caller can ignore a boolean. `require_role`
  raises, so the only way past it is through it.

## Next

Lesson 3 writes down what each decision was: an audit trail whose rows are written in the same
transaction as the change they describe.
