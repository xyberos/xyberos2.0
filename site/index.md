---
title: Xyberos documentation
status: verified
---

# Xyberos documentation

Xyberos is a composable Python application runtime: application composition, typed dependency
injection, a lifecycle, Starlette-backed HTTP, SQLite, an in-process workflow engine, and a
provider-neutral AI facade.

This site teaches it in four sections, all of them written to one rule: **a page is a set of claims,
and the build checks them.** A lesson page includes its code from the file the test suite runs, and
every printed output on a lesson page is compared with the real output before that page can be
published. A lesson that has drifted fails the build rather than misleading a reader.

## Where to start

| Section | Read it if |
| ------- | ---------- |
| [Fundamentals](learn/fundamentals/index.md) | you have not used Xyberos before |
| Traditional Apps | you are building a database-backed web application |
| AI Apps | you are calling a model from an application |
| Hybrid Apps | you are putting both in one application |
| [Extend Xyberos](extend/index.md) | you are writing a provider, a plugin, or a module |
| [Reference](reference/index.md) | you want one specific API, parameter, or exception |

The [roadmap](roadmap.md) lists every lesson and its status, and it is generated from the pages
themselves rather than typed by hand.

## How each page is labelled

Every lesson declares who provides the capability it teaches, and the label is not decoration: there is
a test that compares it with [the stability guide](reference/stability.md), so a lesson cannot claim
the framework provides something it does not.

| Label | What it means |
| ----- | ------------- |
| **Built-in** | The framework ships it. An `(extra)` note means it needs an optional install. |
| **Extension point** | The framework defines a contract you implement, and ships a conformance suite for it. |
| **You add it** | A third-party library or a server that the framework does not depend on. |
| **You build it** | Nothing ships. The lesson teaches you to write it, and says so on the page. |

[Feature support](feature-support.md) is the complete matrix, and it is the source the labels come
from. [Terminology](terminology.md) maps the words this site uses onto the names in the code.

## How these pages are verified

Two commands, both of which run in CI:

```powershell
python site/scripts/build.py --check     # generate the pages, then check and build them strictly
python -m pytest tests/site              # run the assertions described above
```

`roadmap.md` and everything under `reference/` are generated, so a fresh clone does not contain them
and a bare `mkdocs build` fails on the navigation. `site/scripts/build.py` is the entry point, and
`reference/` is a copy of the repository's `docs/` directory — a correction belongs there, never here.
