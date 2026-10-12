---
title: Create and list users
path: traditional
lesson: 4
tier: built-in
status: verified
verify: output
example: examples/learn_traditional/traditional04_users.py
prerequisites: ["/learn/traditional/03-database"]
---

# Lesson 4 — create and list users

## What you will build

The application every remaining lesson in this path grows. It is four files, and the point of the
split is that each one owns exactly one thing: the columns, the rules, the responses, and the
composition that ties them together.

Lesson 3 put a service and a route in one file to keep the idea small. This lesson keeps the idea and
gives it a shape you can add to for nine more lessons.

## What you need

The two extras from lessons 1–3, together:

=== "PowerShell"

    ```powershell
    python -m pip install "xyberos[http,database]"
    ```

=== "POSIX"

    ```bash
    python -m pip install 'xyberos[http,database]'
    ```

## The project

| File | Owns | Never contains |
| ---- | ---- | -------------- |
| `tables.py` | the columns, and only the columns | SQL, or a rule |
| `errors.py` | domain errors, each one knowing its status code | a route |
| `service.py` | rules and transaction boundaries | an HTTP type |
| `app.py` | providers, routes, and translation | SQL |
| `migrate.py` + `migrations/` | putting the schema in a database, as a revision | a rule, or a route |

The files below are the project as the path leaves it, so `app.py` already contains the query-string
handling lesson 5 adds, and the schema arrives through the migrations lesson 7 explains. Later lessons
read the earlier pages' code the same way.

`examples/user_management/tables.py` is the whole schema, read in one screen:

<!-- snippet: examples/user_management/tables.py -->

`examples/user_management/errors.py` is the vocabulary the rest of the application speaks. Two of
these are used before the lesson ends; `UserNotFoundError` is waiting for lesson 6:

<!-- snippet: examples/user_management/errors.py -->

`examples/user_management/service.py` is where the rules live. Every method either returns a row or
raises a domain error, and no method knows what a request is:

<!-- snippet: examples/user_management/service.py -->

`examples/user_management/app.py` composes the application: it registers the providers, then the
routes, and hands each request to the service:

<!-- snippet: examples/user_management/app.py -->

The lesson scripts start from an empty file and call `migrate(settings)` first, which applies the
application's revisions to it. That is the same call the deploy step makes — lesson 7 shows the files
it runs — and it is why the temporary database in the script below ends up with a real `users` table:

<!-- snippet: examples/user_management/migrate.py -->

## What the lesson runs

<!-- snippet: examples/learn_traditional/traditional04_users.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_traditional.traditional04_users
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_traditional.traditional04_users
    ```

The script borrows the trick from lesson 3 — a database in a temporary directory, created and thrown
away — and drives the application through `create_test_client`, so nothing is typed into a terminal
that the suite does not also run.

## What it prints

<!-- output: traditional04_users -->
```text
health: {'status': 'ready'}
POST /users -> 200 {'id': 1, 'email': 'ada@example.com', 'display_name': 'Ada Lovelace', 'enabled': True, 'external_subject': None}
POST /users -> 409 {'error': {'type': 'DuplicateEmailError', 'message': 'ada@example.com is already registered'}}
POST /users -> 422 {'error': {'type': 'UserValidationError', 'message': 'email must look like name@example.com'}}
POST /users -> 200 {'id': 2, 'email': 'grace@example.com', 'display_name': 'Grace Hopper', 'enabled': True, 'external_subject': None}
GET /users -> 200
{'items': [{'id': 1, 'email': 'ada@example.com', 'display_name': 'Ada Lovelace', 'enabled': True, 'external_subject': None}, {'id': 2, 'email': 'grace@example.com', 'display_name': 'Grace Hopper', 'enabled': True, 'external_subject': None}], 'total': 2, 'limit': 20, 'offset': 0}
```

Four requests, four answers, and three of them are the lesson:

- **The first `POST` sends `"  ADA@Example.com "` and `"Ada   Lovelace"`.** The stored row is
  `ada@example.com` and `Ada Lovelace`, because normalising input is the service's job and not the
  caller's good manners. A client that sends `ada@example.com` later is the same user.
- **The second `POST` is that same address again, and it is refused with `409`.** The check happens
  inside the write transaction, and the column is `unique` as well: the first is the rule, the second
  is what happens when two requests race and both pass the check.
- **The third `POST` is not an email, and it is refused with `422`.** Both refusals come back in the
  shape lesson 2 taught: an `error` object with a `type` and a `message`.
- **The fourth `POST` succeeds, and `GET /users` returns both rows.**

## Where each rule lives

| Input | Rule | Result |
| ----- | ---- | ------ |
| `"  ADA@Example.com "` | trim, then lowercase | stored as `ada@example.com` |
| `"not-an-email"` | one `@`, a local part, a dotted domain | `422` |
| `"Ada   Lovelace"` | collapse runs of whitespace | stored as `Ada Lovelace` |
| a taken address | `select` inside the write transaction | `409` |
| `limit=0` | between 1 and 100 | `422` |

Three of these rules are one line of code each, and they are all in
`examples/user_management/service.py` rather than in the route. That is not tidiness: the rules belong
to the operation, so the same method can be called from a CLI, a background job, or a test without a
request existing.

## Why the collection is a page, not a list

`GET /users` returns `items`, `total`, `limit`, and `offset`, and the limit defaults to 20. The
alternative — returning a bare list — is the shape that quietly works until a table grows, and then
becomes a response nobody planned for. A collection endpoint that cannot be bounded is a bug waiting
for data.

Lesson 5 accepts `?limit=` and `?offset=` from the client, which means turning untrusted text into
integers and refusing the values that make no sense. Until then the defaults apply.

## Common mistakes

- **Validating in the route.** The route's job is to read a request and call the service. Once a rule
  is in the route, the CLI cannot reuse it and the test has to build a request to check a rule.
- **Checking for a duplicate outside the transaction.** `select` outside the `with` block, then
  `insert` inside it, is a race: two requests can both find nothing and both insert. Do both inside
  one transaction, and keep the `unique` constraint as the backstop.
- **Trusting `payload.get("email")` to be a string.** It is whatever the JSON body held — a number, a
  list, `None` — which is why the service takes `object` and checks with `isinstance` before it
  touches it.
- **Leaving the service to raise an HTTP-shaped error.** `UserValidationError` is a
  `RequestValidationError` and `DuplicateEmailError` is an `HttpError`, but the service only raises
  them; the adapter turns them into `422` and `409`. A service that builds responses cannot be called
  from a job.
- **Creating the schema in the application.** The tables arrive from `migrations/` (lesson 7), applied
  by a command someone ran against the database, not by the application as it starts.

## Exercise

Add `set_enabled(user_id, enabled)` to the service and a route that calls it —
`POST /users/{user_id}/deactivate`. A user that does not exist must be a `404`, and the response must
be the updated row.

<details>
<summary>Show the answer</summary>

<!-- snippet: examples/learn_traditional/traditional04_exercise.py -->

<!-- output: traditional04_exercise -->
```text
created: 200 {'id': 1, 'email': 'ada@example.com', 'display_name': 'Ada Lovelace', 'enabled': True, 'external_subject': None}
deactivated: 200 {'id': 1, 'email': 'ada@example.com', 'display_name': 'Ada Lovelace', 'enabled': False, 'external_subject': None}
missing: 404 {'error': {'type': 'UserNotFoundError', 'message': 'user 99 was not found'}}
```

The `update` reports how many rows it touched, and `rowcount == 0` is the only trustworthy way to
learn that the user was not there: a `select` first and an `update` second is the same race as the
duplicate check. `UserNotFoundError` is raised inside the transaction, so a missing user costs one
round trip and no partial write.
</details>

## Next

Lesson 5 takes the page apart: `?limit=` and `?offset=` from the query string, what a bad value gets,
and why the bound is enforced twice.
