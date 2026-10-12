---
title: View, edit, and delete
path: traditional
lesson: 6
tier: built-in
status: verified
verify: output
example: examples/learn_traditional/traditional06_crud.py
prerequisites: ["/learn/traditional/05-pagination"]
---

# Lesson 6 — view, edit, and delete

## What you will build

The three routes that finish CRUD: read one user, change one, remove one. The rules are not new — the
service has known them since lesson 4 — but three questions arrive with them that a collection endpoint
never has to answer: what a missing row looks like, what a partial edit means, and whether a repeated
delete is an error.

## What you need

Nothing new. `examples/user_management/service.py` grows three methods and
`examples/user_management/app.py` grows three routes:

<!-- snippet: examples/user_management/service.py -->

<!-- snippet: examples/user_management/app.py -->

Look at the order inside `update_user`. The row is looked up first, so a missing user is a `404` even
when the body also names an email somebody else already has: two errors are true at once, and the one
that describes the resource the request named wins. Only then is the address checked for a collision —
and the check excludes the row being edited, because otherwise every edit of a user's own address would
report a duplicate of itself.

The lesson's own module drives all three:

<!-- snippet: examples/learn_traditional/traditional06_crud.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_traditional.traditional06_crud
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_traditional.traditional06_crud
    ```

## What it prints

<!-- output: traditional06_crud -->
```text
GET /users/1 -> 200 {'id': 1, 'email': 'ada@example.com', 'display_name': 'Ada', 'enabled': True, 'external_subject': None}
GET /users/99 -> 404 {'error': {'type': 'UserNotFoundError', 'message': 'user 99 was not found'}}
GET /users/abc -> 422 {'error': {'type': 'RequestValidationError', 'message': "the path parameter 'user_id' is not valid"}}
PATCH /users/1 {'display_name': '  Ada,   Countess of Lovelace '} -> 200 {'id': 1, 'email': 'ada@example.com', 'display_name': 'Ada, Countess of Lovelace', 'enabled': True, 'external_subject': None}
PATCH /users/1 {'enabled': 'yes'} -> 422 {'error': {'type': 'UserValidationError', 'message': 'enabled must be a boolean'}}
PATCH /users/1 {'nickname': 'Ada'} -> 422 {'error': {'type': 'UserValidationError', 'message': 'unknown field: nickname'}}
PATCH /users/1 {'email': 'ada@example.com'} -> 200 {'id': 1, 'email': 'ada@example.com', 'display_name': 'Ada, Countess of Lovelace', 'enabled': True, 'external_subject': None}
PATCH /users/2 {'email': 'ada@example.com'} -> 409 {'error': {'type': 'DuplicateEmailError', 'message': 'ada@example.com is already registered'}}
DELETE /users/3 -> 204 None
DELETE /users/3 again -> 404 {'error': {'type': 'UserNotFoundError', 'message': 'user 3 was not found'}}
GET /users -> ['ada@example.com', 'grace@example.com'] of 2
```

Eleven requests, and the interesting ones are the refusals:

| Request | Status | Why |
| ------- | ------ | --- |
| `GET /users/99` | `404` | the service raised `UserNotFoundError`, and the adapter turned it into a response |
| `GET /users/abc` | `422` | the path parameter is annotated `int`, so the framework refused it before the service was called |
| `PATCH` with `enabled: "yes"` | `422` | JSON has a boolean; a string that looks like one is not it |
| `PATCH` with `nickname` | `422` | an unknown field is refused rather than ignored |
| `PATCH /users/2` with user 1's email | `409` | the collision check, excluding the row being edited |
| `DELETE /users/3` twice | `204`, then `404` | the second delete reported that the row was already gone |

Note the two different `422`s. `GET /users/abc` never reached the service — the path parameter is typed
as `int`, so the framework caught it. The `PATCH` refusals did reach it: they are rules about users, and
rules about users live in the service.

## What `PATCH` means here

`PATCH` replaces the fields it names and leaves the rest alone. Three consequences follow, and all three
are deliberate:

- **An empty body is refused**, not treated as "change nothing", because a request that asks for nothing
  is more likely to be a client bug than an intent.
- **A field the service does not know is refused.** Accepting `{"nickname": "Ada"}` silently would mean a
  client that misspelled `display_name` would get `200` and no change.
- **Only the named fields are validated.** `{"display_name": "Ada"}` does not have to carry a valid
  email, because it is not changing one.

`PUT` is the other half of that idea — a replacement that must carry every field — and it is this
lesson's exercise.

## `DELETE` twice: 204 or 404?

Both answers are defensible, and the choice is about what the client needs to hear.

| Choice | Second `DELETE` | What the client learns |
| ------ | --------------- | ---------------------- |
| **Strict** — what this lesson does | `404` | whether *this* request removed the row, which is what an audit trail or a retry loop usually wants |
| **Idempotent** | `204` | that the row is gone, which is all a client that only wants it gone needs |

The lesson picks strict because it composes with the rest of the API: a `404` already means "no such
user" here, and answering `204` for a user that never existed would make `/users/999` a route that
reports success. Whichever you pick, pick it for every delete in the application, and say so on the
page a client reads.

## Common mistakes

- **Returning `None` from a handler and expecting `200`.** `None` becomes `204 No Content`, which is why
  `DELETE` is one line long. Returning a body from a `204` is itself a protocol error.
- **Deciding `404` from the update's row count when the body can also fail validation.** The order of the
  checks decides which error a client sees, so put the existence check first and the collision second.
- **Forgetting that the collision check must exclude the row being edited.** Without `users.c.id !=
  user_id`, saving a user without changing its email returns `409`, and the client cannot fix it.
- **Coercing a JSON string into a boolean.** `"yes"`, `"true"`, and `1` are not `True`; accepting them
  means a client sending `"false"` eventually enables an account.
- **Deleting the row the client is about to need.** A `DELETE` that reports `204` and then removes a user
  the client still references is a data-model question, not an HTTP one: soft-delete (`enabled = 0`) is
  what the `enabled` column is for when records have to survive.

## Exercise

Add `PUT /users/{user_id}`: a full replacement that requires `email`, `display_name`, and `enabled`,
refuses a body that leaves one out, reuses the same collision check, and still answers `404` for a user
that does not exist.

<details>
<summary>Show the answer</summary>

<!-- snippet: examples/learn_traditional/traditional06_exercise.py -->

<!-- output: traditional06_exercise -->
```text
PUT /users/1 -> 200 {'id': 1, 'email': 'ada@example.com', 'display_name': 'Ada Lovelace', 'enabled': False, 'external_subject': None}
PUT /users/1 without enabled -> 422 {'error': {'type': 'UserValidationError', 'message': 'a replacement needs email, display_name, enabled'}}
PUT /users/99 -> 404 {'error': {'type': 'UserNotFoundError', 'message': 'user 99 was not found'}}
PATCH /users/2 -> 200 {'id': 2, 'email': 'grace@example.com', 'display_name': 'Rear Admiral Grace Hopper', 'enabled': True, 'external_subject': None}
```

The replacement is three lines because the write itself is not new: it calls the same `update_user`, so
the collision rule, the normalisation, and the `404` are shared rather than copied. What `PUT` adds is
the *contract* — every field must be present — and that belongs at the edge of the operation, before
anything is read or written. The last line is the contrast worth keeping: `PATCH` still edits one field
on its own, and the same user comes back with only the name changed.
</details>

## Next

Lesson 7 takes the schema away from `metadata.create_all`. Migrations: writing a revision, running it at
deploy time, and why the file this lesson's code relies on is a stand-in that has to go.
