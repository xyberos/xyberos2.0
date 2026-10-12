---
title: Use the command line
path: fundamentals
lesson: 15
tier: built-in
status: verified
verify: command
command: xyberos check
prerequisites: ["/learn/fundamentals/04-your-first-application"]
---

# Lesson 15 — use the command line

## What you will build

Nothing new: four commands, each a thin wrapper over an API you have already met. The reason to learn
them is that `check` answers the question every wiring mistake raises — *is this application composed
correctly?* — without starting it.

## What you need

Xyberos installed, so the `xyberos` command exists. `migrate` additionally needs the `database` extra,
and `run` needs an ASGI server; neither is required for this lesson.

## The four commands

| Command | What it does | Needs |
| --- | --- | --- |
| `xyberos check` | loads settings and validates a composed application *without starting it* | core |
| `xyberos new` | writes a project that runs | core |
| `xyberos run` | hands an import string to your ASGI server | an ASGI server |
| `xyberos migrate` | applies Alembic revisions | the `database` extra |

## What it prints

<!-- output: cli-check -->
```text
settings: xyberos (development), schema_version 1, debug False
application: not inspected (pass --app module:attribute)
```

That is `check` with no application: it reports the settings it resolved, and says plainly that it has
nothing else to look at. The transcript is the command's real output — the suite runs this command and
compares it with the block above.

## Checking a real application

`--app` takes a *factory* that returns an `App` — not a `main()` function, and not a bare module. The
lesson modules here are scripts rather than projects, so the honest example is the one `xyberos new`
writes, which is the exercise below:

=== "PowerShell"

    ```powershell
    xyberos new myapp
    xyberos check --app myapp.app:create_app --app-dir myapp/src
    ```

=== "POSIX"

    ```bash
    xyberos new myapp
    xyberos check --app myapp.app:create_app --app-dir myapp/src
    ```

| Option | Why it exists |
| --- | --- |
| `--app module:attribute` | a *factory* that returns an `App`; it is called, and nothing is started |
| `--app-dir DIR` | makes a `src` layout importable without installing it |
| `--config PATH` | checks a specific settings file instead of the discovered one |

## Exit codes are part of the contract

| Code | Meaning |
| --- | --- |
| `0` | the command did what it said |
| `1` | it failed — invalid configuration, a missing server, a failed migration |
| `2` | what you asked for is wrong — an unimportable target, an invalid project name |

That is why `check` is worth running in continuous integration: a wiring mistake becomes a failed
build rather than a failed first request.

## Common mistakes

- **Expecting `check` to start the application.** It does not, which is the point: no port is bound,
  no model is called, no migration runs.
- **Pointing `--app` at a function that returns something else.** The target must be a factory that
  returns an `App`; anything else is a configuration error, not a crash.
- **Forgetting `--app-dir` for a `src` layout.** Without it the import fails, and the message tells
  you the module could not be imported rather than pretending the application is broken.

## Exercise

Create a project, run its test, and check it — without reading any other lesson.

<details>
<summary>Show the answer</summary>

=== "PowerShell"

    ```powershell
    xyberos new myapp
    cd myapp
    python -m pip install -e ".[http,dev]" uvicorn
    pytest
    xyberos check --app myapp.app:create_app --app-dir src
    ```

=== "POSIX"

    ```bash
    xyberos new myapp
    cd myapp
    python -m pip install -e '.[http,dev]' uvicorn
    pytest
    xyberos check --app myapp.app:create_app --app-dir src
    ```

The scaffold writes the same shape you built by hand: a composition root, one service, two routes, a
settings file, and a test that passes before you change anything.
</details>

## Next

That is the Fundamentals path as far as it is written. [The roadmap](../../roadmap.md) shows the
lessons still in progress, and which of them come next.
