---
title: Protected endpoints
path: traditional
lesson: 9
tier: not-provided
status: verified
verify: output
example: examples/learn_traditional/traditional09_protected.py
prerequisites: ["/learn/traditional/08-identity"]
---

# Lesson 9 — protected endpoints

## What you will build

The other half of lesson 8. Knowing who is calling is not the same as knowing what they may do, and
this lesson is where the application starts refusing people it has successfully identified: `403`,
roles, and the deployment obligation that keeps an assertion from being forgeable.

Nothing in the framework changes. Authorization is a product decision
([ADR 0014](../../reference/adr/0014-no-identity-or-authorization-model.md)), so what this lesson
shows is a shape you can keep in a route table and audit in a review.

## What you need

Nothing new.

## Two refusals, two questions

| Status | Class | The question it answers | What a client does next |
| ------ | ----- | ----------------------- | ----------------------- |
| `401` | `UnauthenticatedError` | *I do not know who you are* | authenticate, then retry |
| `403` | `ForbiddenError` | *I know who you are, and no* | nothing: retrying will not help |

A client that cannot tell them apart retries forever or gives up too early. Both classes are in
`identity.py`, next to the verifier that produces the principal they are about:

<!-- snippet: examples/user_management/identity.py -->

## The route table is the policy

`examples/user_management/app.py` gains one nested function and one call at the top of every
administrative route:

<!-- snippet: examples/user_management/app.py -->

The whole policy is now readable in one place:

| Route | Requirement |
| ----- | ----------- |
| `GET /health` | nothing — a health check that needs identity is a health check a load balancer cannot run |
| `GET /users`, `GET /users/{user_id}`, `POST /users`, `PATCH /users/{user_id}`, `DELETE /users/{user_id}` | the `admin` role |
| `GET /me`, `POST /me`, `PATCH /me` | any verified principal, and only about itself |

That table is the audit surface. `administrator(request, verifier)` is one line, and its cost is that a
new administrative route can forget it — which is why the route table, not the handler, is what a
reviewer reads. A framework that owned authorization would give you a decorator and the same
obligation; it would also own the security of the decision, which is the trade the ADR refuses.

## Every earlier script changed, and nothing they print did

Four earlier lessons drive these routes without an assertion, so each of their scripts needed the same
two lines: a `SECRET` constant, and
`ADMIN_HEADERS = PrincipalVerifier(SECRET).headers("admin@idp", "admin")` — which every request in those
scripts now carries through `client.headers.update(ADMIN_HEADERS)`. The lesson modules on
[lesson 4's page](04-users.md) and the pages after it show the lines in place.

Every transcript in lessons 4–8 is otherwise **byte-identical**, including lesson 7's migration run.
That is checked rather than claimed: the suite runs each lesson module and compares its output with the
block on the page, so a change that quietly altered a documented result would fail the build. Lesson 8's
own script is the one that already had an assertion; it keeps working because the roles it sends have
not changed.

## The edge obligation

Everything in this lesson depends on one operational fact, and it is the one the framework cannot
enforce for you: **the assertion headers must be stripped from client requests at the edge**. If your
proxy forwards a client-supplied `X-Authenticated-Subject` or `X-Authenticated-Roles`, a client chooses
their own identity and every check above becomes decoration.

- The proxy removes those headers from inbound requests, and sets them only after authenticating.
- The secret lives in the deployment's environment, not in the repository, and never in a URL: the
  signature is what makes the header a fact.
- Nothing here is durable. A verified principal is per request, which is why nothing is cached in a
  session, a cookie, or `contextvars` ([security guide](../../reference/security.md)).

## What the lesson runs

<!-- snippet: examples/learn_traditional/traditional09_protected.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_traditional.traditional09_protected
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_traditional.traditional09_protected
    ```

## What it prints

<!-- output: traditional09_protected -->
```text
no assertion -> 401 {'error': {'type': 'UnauthenticatedError', 'message': 'the request is not authenticated: X-Authenticated-Subject is required'}}
a member asks for the collection -> 403 {'error': {'type': 'ForbiddenError', 'message': 'this operation requires the admin role'}}
a member editing the roles header -> 401 {'error': {'type': 'UnauthenticatedError', 'message': 'the request is not authenticated: the assertion signature does not match'}}
an administrator creates a user -> 200 {'id': 1, 'email': 'grace@example.com', 'display_name': 'Grace Hopper', 'enabled': True, 'external_subject': None}
an administrator sees 1 of 1
a member claims an account -> 200 {'id': 2, 'email': 'ada@example.com', 'display_name': 'Ada Lovelace', 'enabled': True, 'external_subject': 'ada@idp'}
a member reads their own account -> 200 {'id': 2, 'email': 'ada@example.com', 'display_name': 'Ada Lovelace', 'enabled': True, 'external_subject': 'ada@idp'}
a member reads the admin's account -> 403 {'error': {'type': 'ForbiddenError', 'message': 'this operation requires the admin role'}}
```

Three of those lines are the lesson:

- **`a member asks for the collection -> 403`.** The caller is known and the collection is not theirs.
- **`a member editing the roles header -> 401`, not `403`.** The signature covers the subject *and* the
  roles, so an edited header is not a member who overreached: it is an assertion that failed. This is
  the difference between an authorization bug and a broken client, and the status says which happened.
- **`a member reads the admin's account -> 403`.** `GET /users/{user_id}` is an administrative route
  whoever you are; owning an account never grants it.

## Common mistakes

- **Answering `404` where you mean `403`.** Replacing a refusal with "not found" hides existence, which
  is sometimes the right call and always a decision — make it deliberately, as the exercise does.
- **Letting a client supply a role.** A role in a header is only a role because the signature covered
  it. Roles from a query parameter, a body, or a cookie are a client asserting its own permissions.
- **Checking the role in the service.** The service should not know what a route is: keep the refusal at
  the edge of the operation and pass a principal that already satisfies it. When a rule is genuinely
  about the data — "this record belongs to that subject" — it belongs in the service, scoped by the
  principal it is given.
- **Auditing only the happy path.** The routes that need a check are the ones that change state, and the
  ones that leak data are the ones that read. Both lists belong in the review.
- **Assuming the gateway stripped the headers.** Verify it in a test, or in staging, by sending
  `X-Authenticated-Subject` yourself and expecting a `401`. A deployment that forwards it looks exactly
  like a deployment that works.

## Exercise

Add `GET /accounts/{user_id}` with the rule nearly every application ends up needing: a caller may read
their own account, an administrator may read anybody's, and everybody else is refused. Pay attention to
what the refusal says and to *when* it happens.

<details>
<summary>Show the answer</summary>

<!-- snippet: examples/learn_traditional/traditional09_exercise.py -->

<!-- output: traditional09_exercise -->
```text
the member's own id: 1
their own account -> 200 {'id': 1, 'email': 'ada@example.com', 'display_name': 'Ada Lovelace', 'enabled': True, 'external_subject': 'ada@idp'}
somebody else's account -> 403 {'error': {'type': 'ForbiddenError', 'message': 'this operation requires the admin role or your own account'}}
an administrator reads account 99 -> 404 {'error': {'type': 'UserNotFoundError', 'message': 'user 99 was not found'}}
an administrator reads account 1 -> 200 {'id': 1, 'email': 'ada@example.com', 'display_name': 'Ada Lovelace', 'enabled': True, 'external_subject': 'ada@idp'}
```

The last four lines are the rule, and the third is the one to think about:

- **`their own account -> 200`**, because the account is theirs.
- **`somebody else's account -> 403`**, and the message is the *requirement*, not a fact about the
  account. Refusing before the lookup is deliberate: a `404` for somebody else's record would let a
  member walk the id space and learn which accounts exist.
- **`an administrator reads account 99 -> 404`.** The administrator passes the authorization check, so
  they get the honest answer: no such user. Adding the admin rule did not change lesson 6's error, which
  is what "authorization is a separate decision from lookup" looks like in practice.
</details>

## Next

Lesson 10 gives the application an interface: server-rendered pages over the same handlers, and the
first lesson where the reader supplies a piece of the stack.
