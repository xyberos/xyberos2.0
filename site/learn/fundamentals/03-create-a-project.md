---
title: Create a project
path: fundamentals
lesson: 3
tier: built-in
status: verified
verify: scaffold
command: xyberos new myapp
prerequisites: ["/learn/fundamentals/02-install"]
---

# Lesson 3 — create a project

## What you will build

A project that already runs, written by the command line rather than by hand. The scaffold is the
smallest thing worth calling a project — a composition root, one service, two routes, a settings file,
and a test — and every later lesson adds to this shape rather than replacing it.

## What you need

Xyberos, so that the `xyberos` command exists. The generated project asks for the `http` extra and
pytest when you install it.

## The command

=== "PowerShell"

    ```powershell
    xyberos new myapp
    ```

=== "POSIX"

    ```bash
    xyberos new myapp
    ```

## The files it writes

<!-- output: xyberos-new-myapp -->
```text
myapp/.gitignore
myapp/README.md
myapp/pyproject.toml
myapp/src/myapp/__init__.py
myapp/src/myapp/app.py
myapp/tests/test_app.py
myapp/xyberos.toml
```

The suite verifies this list by running the command in a throwaway directory and comparing the files
on disk, so the block above is a checked claim rather than a transcript — the paths are relative to
where you ran the command. The command also prints the absolute path it wrote to, which is why the
*files* are the claim and the printed path is not.

## What each file is for

| File | Why it exists |
| --- | --- |
| `src/myapp/app.py` | the composition root: `create_app()` builds the application, and `asgi_app` exposes it to a server |
| `tests/test_app.py` | one test that passes before you change anything |
| `xyberos.toml` | the settings file, holding the application name and environment |
| `pyproject.toml` | the distribution, with `http` and `dev` as extras |
| `.gitignore` | includes `var/` and `*.db`, because the scaffold expects a database sooner or later |
| `README.md` | the four commands that run and check the project |

## Run it

=== "PowerShell"

    ```powershell
    cd myapp
    python -m pip install -e ".[http,dev]" uvicorn
    pytest
    xyberos check --app myapp.app:create_app --app-dir src
    ```

=== "POSIX"

    ```bash
    cd myapp
    python -m pip install -e '.[http,dev]' uvicorn
    pytest
    xyberos check --app myapp.app:create_app --app-dir src
    ```

`pytest` passes immediately, and `xyberos check` reports the settings, the provider graph, and the
handler signatures without starting anything. Lesson 15 covers what `check` tells you; lesson 11 in
the traditional path uses the same command on a bigger application.

## Common mistakes

- **Renaming the package directory without renaming the distribution.** The scaffold makes them the
  same on purpose: an import name that differs from its directory is a source of confusion, which is
  why `xyberos new MyApp` is refused.
- **Scaffolding into a directory that already has work in it.** The command refuses rather than
  overwrite; `--force` exists, and is a decision rather than a convenience.
- **Deleting `tests/test_app.py` because it "tests nothing".** It is the shape of a test for this
  project — a service, a request, and a wiring check — and it is cheaper to extend than to rewrite.

## Exercise

Create a project, run its test, and check it — without reading any other lesson.

<details>
<summary>Show the answer</summary>

The four commands under [Run it](#run-it), in order. If `pytest` fails after you edited nothing, the
fault is the environment rather than the scaffold: check that you installed with `.[http,dev]`, which
is what supplies Starlette and pytest.

Then open `src/myapp/app.py`. It is deliberately short enough to read in one sitting, and lesson 4
walks through it line by line.
</details>

## Next

Lesson 4 opens the generated `app.py` and explains each line of it. Until it is published,
[the roadmap](../../roadmap.md) shows where each lesson stands.
