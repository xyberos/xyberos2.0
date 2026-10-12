---
title: Production
status: verified
---

# Production

For the reader who has an application and has to run it. The lessons teach the framework; these pages
teach the operational surfaces around it — what a deployment has to do in what order, what the runtime
prints while it runs, what each failure is called, which boundaries hold on their own, and which ones
are yours.

**Everything here is measured on this repository's toolchain.** Each page's code is a module under
`examples/learn_production/` that the site's own suite runs, and every output block is that module's
real stdout, compared on every build. Nothing on these pages is a summary of documentation somewhere
else.

| Page | What it answers |
| ---- | --------------- |
| [Deploying it](deploy.md) | the factory contract, the check step, migrations as a deploy step, and the choice between refusing to start and reporting not-ready |
| [Observability](observability.md) | what the runtime logs and what it deliberately does not configure, the request pipeline's order, and the diagnostic context a log line survives |
| [Troubleshooting](troubleshooting.md) | the error taxonomy, the one line that identifies each failure, and what to do about it |
| [Security boundaries](security.md) | what the runtime refuses to leak, what it refuses to import, and the large part of security that is a decision you make |
| [Performance and concurrency](performance.md) | write contention under SQLite, the retry budget that bounds it, and why the numbers on this page are counts |
| [Internals](internals.md) | the lifecycle as a state machine, close ordering, the request path, and the design rules behind them |

## How to read a page here

Each page names the shipped feature it relies on, or says which part is application code you write,
in the three labels the rest of the site uses:

- **Built-in** — the runtime does it, and the page can show it.
- **Built-in (extra)** — a shipped implementation of a capability you opted into by installing an
  extra, such as `xyberos[database]`.
- **Application-side** — the framework provides no such thing on purpose, and the page says what to
  build instead. A framework that imports nothing it does not need cannot also be your job queue,
  your rate limiter, or your secret store.

## What is deliberately absent

Three absences are worth stating before the pages, because each one is a design decision rather than a
gap:

- **No server, and no request handling outside the optional `http` extra.** `uvicorn` is your choice,
  and the adapter compiles the application into a Starlette application; the deploy page below and
  [the traditional path's deploy lesson](../learn/traditional/12-deploy.md) show the whole command.
- **No background worker and no scheduler.** [The hybrid path's background lesson](../learn/hybrid/09-background.md)
  and [the durable page](../extend/durable.md) show the two shapes the framework does support — a job
  row an application's own worker claims, and a journal that outlives the process with its limits
  stated — but neither is a scheduler.
- **No sandbox.** Plugins and providers are trusted, in-process Python code, which is why
  [security](security.md) is a page about your decisions rather than a page about guarantees.
