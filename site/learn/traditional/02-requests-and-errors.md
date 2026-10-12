---
title: Read a request, and say no to one
path: traditional
lesson: 2
tier: built-in
status: verified
verify: output
example: examples/learn_traditional/traditional02_requests_and_errors.py
prerequisites: ["/learn/traditional/01-http"]
---

# Lesson 2 — read a request, and say no to one

## What you will build

Three routes that read different parts of a request — a path parameter, a query string, and a JSON body
— and the errors that refuse one. A handler either returns a value or raises; the useful part is that an
error knows which HTTP status it means.

## What you need

Xyberos with the `http` extra, from [lesson 1](01-http.md).

## The code

<!-- snippet: examples/learn_traditional/traditional02_requests_and_errors.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_traditional.traditional02_requests_and_errors
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_traditional.traditional02_requests_and_errors
    ```

## What it prints

<!-- output: traditional02_requests_and_errors -->
```text
found: {'item_id': 1, 'name': 'notebook'}
query: {'query': 'book'}
missing status: 404
missing body: {'error': {'type': 'ItemNotFoundError', 'message': 'item 99 was not found'}}
created: {'created': 'pen', 'id': 2}
broken body status: 422
broken body type: RequestValidationError
```

Read the pairs. `missing status` and `missing body` are the same response: a `404` whose body names the
error type and its message. `broken body status` and `broken body type` are another: a `422` from
`read_json_object`, reported as `RequestValidationError` because the *client* sent something wrong.

## Reading input, and refusing it

| You raise | The client receives |
| --- | --- |
| a subclass of `HttpError` | its `status_code` and `{"error": {"type", "message"}}` |
| `RequestValidationError` | `422`, named as a validation failure |
| anything else | `500` with a generic message — the traceback goes to the log, never to the client |

There is one recommended way to read a body: **`payload = await read_json_object(request)`**. It
returns a dictionary or raises `RequestValidationError`, so a handler never parses `bytes` and decides
for itself what a malformed body means. Everything else you read from `request` directly:
`request.query_params`, `request.headers`, `request.path_params`.

## The rule that matters

**A request failed because of the client only when you say so.** A `500` is your bug, and the client
learns nothing about it beyond the status code. That is why the exception above is a `404` with a
message written for a person, and why an unexpected error never leaks its traceback.

## Common mistakes

- **Raising `HTTPException` from Starlette.** It works, because the adapter maps it, but it puts a web
  framework's type in your service layer. A domain error that derives from `HttpError` keeps the
  status code where the domain decision is.
- **Returning an error instead of raising it.** A handler that returns `{"error": ...}` sends `200`,
  and every client-side retry policy is now wrong.
- **Treating `X-Request-ID` as identity.** It is echoed for log correlation and is supplied by the
  client, so anything security-related must not read it — lesson 8 is where a real principal arrives.

## Exercise

Return `409 Conflict` when an item is created twice.

<details>
<summary>Show the answer</summary>

<!-- snippet: examples/learn_traditional/traditional02_exercise.py -->

<!-- output: traditional02_exercise -->
```text
created: {'created': 'pen', 'id': 2}
conflict status: 409
conflict type: ItemAlreadyExistsError
```

Two details are easy to miss. The store lives *inside* `create_app`, so each application starts from
the same state and the example is repeatable. And the error class is defined by the application: the
framework supplies `HttpError`, and the application supplies the meaning of `409` here.
</details>

## Next

Lesson 3 stores the items in SQLite instead of a dictionary, and introduces the transaction that makes
"write, then fail" safe. Until it is published, [the roadmap](../../roadmap.md) shows where each lesson
stands.
