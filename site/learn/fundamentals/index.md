---
title: Fundamentals
status: verified
---

# Fundamentals

The runtime, a working application, configuration, dependency injection, and the provider registry.
Read this path first: every other path assumes it, and it is the only one written for someone who has
never opened the framework.

Each lesson has the same shape — what you will build, what you need, the complete code, how to run it,
what it prints, the lines that matter, the usual mistakes, and a small exercise — and each one is
checked before it is published: the code you read is the code the test suite runs, and the output you
see is the output it really produced.

## Lessons

| # | Lesson | You will learn | Availability |
| - | ------ | -------------- | ------------ |
| 1 | [What Xyberos is](01-what-is-xyberos.md) | The runtime's parts, and one service resolved | Built-in |
| 2 | [Install Xyberos](02-install.md) | The Python range, the extras, and what core does not import | Built-in |
| 3 | [Create a project](03-create-a-project.md) | `xyberos new`, and the layout it writes | Built-in |
| 4 | [Your first application](04-your-first-application.md) | The minimum working program | Built-in |
| 5 | [Run your application](05-run-your-application.md) | Startup, configuration, and shutdown | Built-in |
| 6 | [Understand the application lifecycle](06-lifecycle.md) | What happens between `start` and `stop` | Built-in |
| 7 | [Add configuration](07-configuration.md) | `xyberos.toml`, `XYBEROS_*`, and `Settings` | Built-in |
| 8 | [Use dependency injection](08-dependency-injection.md) | How a provider reaches the code that needs it | Built-in |
| 9 | [Choose a scope](09-scopes.md) | App, request, and transient lifetimes | Built-in |
| 10 | [Understand the provider registry](10-registry.md) | `app.provide`, `Inject()`, and `app.diagnostics()` | Built-in |
| 11 | [Read `xyberos check`](11-read-xyberos-check.md) | Settings, the provider graph, and handler signatures | Built-in |
| 12 | [Organize your project](12-organize.md) | Files, folders, imports, and conventions | Built-in |
| 13 | [Write your first test](13-write-your-first-test.md) | Test doubles, and why the AI path needs no model | Built-in |
| 14 | [Handle errors and logging](14-errors-and-logging.md) | The error taxonomy, and diagnosing the usual failures | Built-in |
| 15 | [Use the command line](15-command-line.md) | `new`, `check`, `run`, and `migrate` | Built-in |

All fifteen lessons are written and verified. The [roadmap](../../roadmap.md) is still the authority
on their state, because it is generated from each page's own status rather than typed here — and every
lesson's code, every answer it shows, and every transcript it quotes is checked by
`tests/site/`.

## What you need

- **Python 3.10 or newer.** The tested range is 3.10 through 3.13.
- **Xyberos**, installed with the extras the lesson needs.
- **A terminal.** Commands are shown for PowerShell and for POSIX shells.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install "xyberos[http,database]"
```

The framework never imports an optional capability on its own, so a command that needs HTTP says which
extra it needs rather than failing with an unexplained import error later. That property is enforced by
`tests/test_optional_dependencies.py`.
