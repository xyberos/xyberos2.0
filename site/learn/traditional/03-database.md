---
title: Store data in SQLite
path: traditional
lesson: 3
tier: built-in
status: verified
verify: output
example: examples/learn_traditional/traditional03_database.py
prerequisites: ["/learn/traditional/02-requests-and-errors"]
---

# Lesson 3 — store data in SQLite

## What you will build

A service that owns its SQL, and the transaction boundary that decides what survives. The service
contains no HTTP type at all, which is the convention from
[lesson 12 of the Fundamentals path](../fundamentals/12-organize.md) — and the reason it can be tested
without a request.

## What you need

Xyberos with the `database` extra:

=== "PowerShell"

    ```powershell
    python -m pip install "xyberos[database]"
    ```

=== "POSIX"

    ```bash
    python -m pip install 'xyberos[database]'
    ```

That extra brings SQLAlchemy Core, `aiosqlite`, and Alembic. The provider is SQLite-specific, but the
contract it satisfies — `transaction()`, `retrying()`, `health()` — is the seam another database would
implement ([ADR 0016](../../reference/adr/0016-database-providers-are-an-extension-point.md)).

## The code

<!-- snippet: examples/learn_traditional/traditional03_database.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_traditional.traditional03_database
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_traditional.traditional03_database
    ```

## What it prints

<!-- output: traditional03_database -->
```text
rows: [{'id': 1, 'name': 'notebook'}]
rows after the rollback: 1
```

The second line is the whole lesson. The module inserts `lost` inside a transaction and then raises; the
count is still `1` afterwards, because the transaction rolled back rather than leaving a half-written
row.

## The transaction is the unit of work

| Task | How |
| --- | --- |
| Read or write | `async with database.transaction() as connection:` |
| Retry a locked write | `await database.retrying(operation, attempts=5, base_delay=0.05)` |
| Create the schema | a migration, not `metadata.create_all` — the lesson does the latter to stay short |
| Test against SQLite | `async with temporary_database() as database:` |

Two facts explain almost everything about working with SQLite here:

- **A transaction commits on success and rolls back when the body raises.** That is why the failed
  insert left nothing behind, and why the service never needs its own `try`/`except` to stay consistent.
- **SQLite allows one writer at a time.** Keep write transactions short and never hold one across a
  network call — a held lock is a stalled deployment, not a slow query.

`retrying` is opt-in and bounded, because only you know whether an operation is safe to run twice. If it
is not, give it an idempotency key rather than hoping.

## Common mistakes

- **Holding a transaction across other work.** The body of the `with` block is the transaction; a model
  call or an HTTP request inside it serializes every other writer behind it.
- **Swallowing the error inside the transaction.** `try: ... except: pass` around a failing write
  commits the transaction, because nothing raised out of the body. Let it raise, or the rollback never
  happens.
- **Using `metadata.create_all` in an application.** It is in this lesson only to keep the file short; a
  real application applies a migration at deploy time, which is lesson 7.
- **Assuming the provider is the database.** `SqliteSettings` and its PRAGMAs are SQLite-specific;
  a service that depends on `DatabaseProvider` is portable, and one that depends on `SqliteSettings` is
  not.

## Exercise

Add a `rename` method, and a route that calls it.

<details>
<summary>Show the answer</summary>

<!-- snippet: examples/learn_traditional/traditional03_exercise.py -->

<!-- output: traditional03_exercise -->
```text
after the rename: [{'id': 1, 'name': 'diary'}]
```

The route is the same shape as lesson 2's: read the id from the path, read the body with
`read_json_object`, and call the service. Nothing about the store changes, which is the payoff of
keeping HTTP out of it.
</details>

## Next

Lesson 4 puts this store behind routes — creating and listing users — and moves the SQL into a
service the handlers only call.
