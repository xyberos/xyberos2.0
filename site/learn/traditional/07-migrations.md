---
title: Migrations
path: traditional
lesson: 7
tier: built-in
status: verified
verify: output
example: examples/learn_traditional/traditional07_migrations.py
prerequisites: ["/learn/traditional/06-crud"]
---

# Lesson 7 — migrations

## What you will build

The deploy step. Until now the tables arrived because a lesson script asked for them, which is fine for
a temporary database and wrong for every other one: an application cannot create its own schema at
startup, cannot change a table that already holds rows, and cannot tell you what shape the database is
in. A migration is all three answers at once — a versioned change, applied by a command, recorded in
the database itself.

This lesson also removes the last stand-in. `schema.py`, which lessons 4–6 used to make their temporary
databases, is deleted: the application now gets its tables the way yours will.

## What you need

Nothing new. Alembic came with the `database` extra in lesson 3; this lesson is about using it.

## The revision

A migration directory has three parts: `env.py` (how Alembic connects, supplied by the caller so no URL
is committed), `script.py.mako` (the template a new revision is generated from), and `versions/` — the
revisions themselves, one file each, in order. The first one is the schema lesson 4's `tables.py`
described, written out as instructions:

<!-- snippet: examples/user_management/migrations/versions/0001_create_users.py -->

Two attributes make the chain: `revision` is this file's own name, and `down_revision` is the one it
follows. `None` here means it is the first. `upgrade()` is what runs going forwards, `downgrade()` what
runs going back, and a revision without a `downgrade` is a change nobody can undo.

`examples/user_management/migrate.py` is the small entry point the project ships: it builds the
database URL from the same `SqliteSettings` the application uses, and applies every revision up to a
given point:

<!-- snippet: examples/user_management/migrate.py -->

## What the lesson runs

<!-- snippet: examples/learn_traditional/traditional07_migrations.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_traditional.traditional07_migrations
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_traditional.traditional07_migrations
    ```

## What it prints

<!-- output: traditional07_migrations -->
```text
migrated to 0002_add_external_subject
users columns: ['id', 'email', 'display_name', 'enabled', 'external_subject']
created: {'id': 1, 'email': 'ada@example.com', 'display_name': 'Ada Lovelace', 'enabled': True, 'external_subject': None}
the deploy step: migrations: applied <migrations> to <database>, exit 0
migrating again leaves the revision at 0002_add_external_subject
the user that existed before is still there: {'id': 1, 'email': 'ada@example.com', 'display_name': 'Ada Lovelace', 'enabled': True, 'external_subject': None}
```

Read the first two lines as the job: an empty file becomes the `users` table, and the database records
which revision produced it. Then a user is created, and the fourth line is the *deploy step itself* —
this lesson's script calls the command your deployment runs, with the temporary paths replaced so the
output is the same on your machine:

```powershell
python -m xyberos migrate --url "sqlite:///var/app.db" --migrations examples/user_management/migrations
```

The last two lines are why this lesson exists. Migrating again is a no-op — the revision is already
applied, so nothing runs and **the row created before is still there**. That is what `metadata.create_all`
could never give you: it has no idea what has already happened.

## What `metadata.create_all` cannot do

| Job | `metadata.create_all` | Migrations |
| --- | --- | --- |
| Create the schema | yes, if it is missing | yes, as revision `0001` |
| Change a table that has rows | no — it only creates tables it does not find | yes, and the rows are carried across |
| Tell you the current shape | no | `alembic_version` holds the revision |
| Run at the right time | whenever it is called, which is what makes it convenient | as a deploy step, before the new process serves traffic |

Keep `metadata.create_all` for a throwaway database in a test — that is what lessons 3–6 did — and keep
it out of an application. The moment two environments hold different data, "create the tables if they
are missing" is a run that silently does nothing while the code expects a column that is not there.

## Common mistakes

- **Editing a revision that has already run somewhere.** A revision is a name for a change that
  happened; changing it means two databases at the same revision with different shapes. Write `0002`.
- **Leaving out `downgrade`.** It is untested code by definition, but a rollback that does not exist is
  worse: a deploy that has to go back needs a path, even if you never take it.
- **Adding a `NOT NULL` column to a populated table in one step.** SQLite cannot do it in place. Add it
  nullable with a default, backfill, then tighten — or use `batch_alter_table`, which rebuilds the
  table, as the exercise does.
- **Migrating at startup.** Every process would try, on every boot, and a failure becomes a container
  that never becomes healthy. The deploy step runs it once, before the new version takes traffic.
- **Committing the database URL.** `env.py` has none: the caller supplies it, which also means the same
  migrations run in tests, in CI, and in production.
- **Assuming autogenerate is a review.** `alembic revision --autogenerate` compares `tables.py` with a
  live database and proposes a revision; the file is a draft, and the commit is yours.

## Exercise

Add a nullable `nickname` column to `users` as the revision that follows the current head, using batch
mode so the table is rebuilt. Then prove it on a database that already has a user: apply the project's
revisions, then yours, and show the row keeping its `id` and `email` while gaining the new column.

<details>
<summary>Show the answer</summary>

<!-- snippet: examples/learn_traditional/migrations_exercise/0003_add_nickname.py -->

<!-- snippet: examples/learn_traditional/traditional07_exercise.py -->

<!-- output: traditional07_exercise -->
```text
migrated to 0001_create_users
users columns: ['id', 'email', 'display_name', 'enabled']
the row before the change: {'id': 1, 'email': 'ada@example.com', 'display_name': 'Ada Lovelace', 'enabled': 1}
migrated to 0003_add_nickname
users columns: ['id', 'email', 'display_name', 'enabled', 'external_subject', 'nickname']
the same row after the change: {'id': 1, 'email': 'ada@example.com', 'display_name': 'Ada Lovelace', 'enabled': 1, 'external_subject': None, 'nickname': None}
```

The answer copies the project's migration directory to a temporary one and drops the new revision in,
which is what you would do in your project by writing the file into `migrations/versions/`. Three
details in the output are worth reading twice:

- **The revision follows the head, not `0001`.** `down_revision` names the last revision in the
  directory — at this point in the path that is `0002_add_external_subject`, added by lesson 8 — and
  the database jumps from `0001` to `0003` in one command, applying both. A directory with two
  revisions claiming the same predecessor is a branch, and Alembic refuses it rather than guessing.
- **`enabled` arrives as `1`, not `True`.** SQLite stores a boolean as an integer, and it is
  SQLAlchemy's `Boolean` type — the one `tables.py` declares — that turns it back. This answer reads
  `SELECT *` on purpose, to show every column the table has now, and pays for it with SQLite's own
  representation.
- **The row keeps its `id` and `email` and gains `nickname: None`.** That is `batch_alter_table` doing
  the work: create a new table, copy the rows, swap it in. The alternative — dropping and recreating —
  is how a migration loses production data.
</details>

## Next

Lesson 8 is the first lesson about a request that carries something the application must not trust:
identity from upstream. It is also where the migration machinery starts earning its keep, because a
verified principal has to be linked to a local user — and that link is a column.
