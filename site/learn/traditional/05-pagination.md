---
title: Validation and pagination
path: traditional
lesson: 5
tier: built-in
status: verified
verify: output
example: examples/learn_traditional/traditional05_pagination.py
prerequisites: ["/learn/traditional/04-users"]
---

# Lesson 5 — validation and pagination

## What you will build

The same collection endpoint, one turn of the screw: it now reads `?limit=` and `?offset=` from the
query string. That sounds like two numbers, and it is the first place in this path where text from
outside meets a rule inside, so it is where the *shape* of validation gets decided.

## What you need

Nothing new. The `http` and `database` extras from lesson 4 are all this lesson uses.

## The code

One file changes. `examples/user_management/app.py` grows a private helper and passes two arguments to
the service:

<!-- snippet: examples/user_management/app.py -->

The handler still does not know what a valid page is: it turns two strings into two integers, and the
service refuses the integers that make no sense. `examples/user_management/service.py` did not change —
its bounds were in place from lesson 4, because they are rules about the operation rather than about a
request.

And the lesson's own module drives it:

<!-- snippet: examples/learn_traditional/traditional05_pagination.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_traditional.traditional05_pagination
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_traditional.traditional05_pagination
    ```

## What it prints

<!-- output: traditional05_pagination -->
```text
GET /users?limit=2 -> 200 ['ada@example.com', 'grace@example.com'] of 5
GET /users?limit=2&offset=2 -> 200 ['katherine@example.com', 'marie@example.com'] of 5
GET /users?limit=2&offset=4 -> 200 ['radia@example.com'] of 5
GET /users?limit=abc -> 422 {'type': 'UserValidationError', 'message': 'limit must be a whole number'}
GET /users?limit=0 -> 422 {'type': 'UserValidationError', 'message': 'limit must be between 1 and 100'}
GET /users?limit=101 -> 422 {'type': 'UserValidationError', 'message': 'limit must be between 1 and 100'}
GET /users?offset=-1 -> 422 {'type': 'UserValidationError', 'message': 'offset must not be negative'}
```

Three pages of five users, then four refusals. Look at *why* each refusal happened:

| Request | Refused by | Because |
| ------- | ---------- | ------- |
| `?limit=abc` | the handler, in `app.py` | `"abc"` is not a number, and only the handler knows it was text |
| `?limit=0` | the service, in `service.py` | zero is a number, and no page may be empty |
| `?limit=101` | the service | a page larger than 100 is a client asking for the table |
| `?offset=-1` | the service | an offset before the first row has no meaning |

That split is the lesson. `int()` is not validation — it is *parsing*, and it belongs where the
untrusted text arrives. The bounds are rules about the operation, so they belong where the operation
lives, and that is what keeps them true when the caller is a CLI or a background job instead of a
request.

Both kinds of refusal come back as the same `422` body, because `UserValidationError` is a
`RequestValidationError` whichever layer raised it. A client does not have to care which layer said no.

## Why the last page is not an error

`?offset=4` asks for rows five onwards, and one row is left. That is a correct page, not a problem: the
client asked for up to two rows starting at four, and there were fewer than two. `total` is how it
learns that, because the only alternative is guessing from a short page — and a full last page is
indistinguishable from a page with more behind it.

Three answers are worth having for a collection, and this one is the middle:

- **Return everything.** Fine until it is not, and then a request times out that used to work.
- **Return a page with its total, and let the client ask for more.** What this endpoint does. The
  client can page forwards, jump to an offset, and show "1–2 of 5" without a second request.
- **Return a cursor.** The right answer for a table that changes under the reader, because an offset
  drifts when rows are inserted. It is also more machinery than a first release needs; the pages here
  are small and ordered by `id`.

## Common mistakes

- **Reading `limit` with `request.query_params.get("limit", 20)`.** It returns the *string* `"20"` when
  the parameter is present and an integer when it is not, so the type depends on the client. Default in
  the handler, convert in the handler, and the service gets an integer either way.
- **Validating a query parameter by catching everything.** `except Exception` around the conversion
  turns a typo in the handler into a `422` blaming the client. `int()` raises `ValueError`; catch that.
- **Believing a `422` is enough.** Range checks on `limit` protect the *database*, and the offset still
  needs a bound if the table is large: `?offset=1000000000` is a legitimate-looking request that makes
  SQLite walk a long way. The bigger the table, the more it matters.
- **Making the page size a client-only decision.** A `limit` of ten thousand is a denial-of-service
  request with a friendly name, which is why the maximum lives in the service and not in documentation.
- **Forgetting that the offset is a position, not a page number.** `?limit=2&offset=3` is a page that
  skips a row. Either the client computes `offset = page * limit`, or the API takes a page number and
  converts — but the two must not be mixed.

## Exercise

Add an exact-match `?email=` filter to the collection: absent means no filter, a blank value is refused,
and `total` counts the rows the filter matched rather than the whole table. The match must be normalised
the same way `create_user` normalises what it stores, or `?email=ADA@example.com` finds nothing.

<details>
<summary>Show the answer</summary>

<!-- snippet: examples/learn_traditional/traditional05_exercise.py -->

<!-- output: traditional05_exercise -->
```text
GET /directory -> 200 ['ada@example.com', 'grace@example.com', 'katherine@example.com'] of 3
GET /directory?email=ADA@example.com -> 200 ['ada@example.com'] of 1
GET /directory?email=marie@example.com -> 200 [] of 0
GET /directory?email= -> 422 email must not be blank
```

The answer's route is `/directory` rather than something under `/users/`, because a literal segment
there is matched by the per-user route a later lesson adds: `/users/find` would be read as a user id
and refused as one. Route order is decided by registration, and the application registers its own
routes before an answer can add to them.

Two details carry the lesson forward. The **count is filtered too** — `total` describes the collection
the client is paging through, so a filtered page that reported `3` would make the client keep asking for
pages that cannot exist. And the **filter is normalised at the edge of the service**, next to the rule
it mirrors: the column stores `ada@example.com`, so a filter that compared `ADA@example.com` literally
would return an empty page and look like a missing row rather than a missing `lower()`.
</details>

## Next

Lesson 6 finishes CRUD: reading one user, editing one, deleting one — and the difference between a
write that repeats safely and a write that must not.
