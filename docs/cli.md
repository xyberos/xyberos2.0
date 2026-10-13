# Command-line guide

> Status: Phases 7 and 11. The **command and its options are the promise**; the Python modules
> behind them are internal and may move in any release. See the [stability guide](./stability.md).

The `xyberos` command exists so that things a developer does over and over are one documented line
each: inspecting a composition, starting a project, running a server, applying migrations, and
looking at a durable journal. It is a front door over APIs the runtime already proves — it never
becomes a second implementation of the runtime, never starts an application implicitly, and never
ships a server.

## Install and invoke

```powershell
python -m pip install -e ".[http,dev]"
xyberos --help
```

The console script is installed with the package, and `python -m xyberos` runs the same command for
the case where the script directory is not on `PATH` — an unactivated virtual environment, for
example.

| Command | What it wraps | Needs |
| --- | --- | --- |
| `xyberos check` | `Settings.load`, `App.validate`, `App.diagnostics` | core |
| `xyberos new` | nothing at all; it writes files | core |
| `xyberos run` | an ASGI server's own `run`, handed an import string | an ASGI server |
| `xyberos migrate` | `run_migrations` / `apply_migrations` | the `database` extra |
| `xyberos durable status` | `JournalStats`, `JournalStore` readers | the `durable` extra |

## `xyberos check`

Loads settings and inspects an application **without starting it**. Validation is the same call the
application makes at startup, so a successful check is evidence about the deployment rather than a
second opinion.

```powershell
xyberos check --app myapp.app:create_app --app-dir src
```

```text
settings: myapp (development), schema_version 1, debug False
application: myapp.app:create_app
provider graph: valid
providers:
  ItemService [app] from application
  ItemRepository [request] from application
plugins:
  (none)
routes: 6 (handler signatures valid)
```

- `--config PATH` inspects a specific `xyberos.toml` instead of the discovered one.
- `--app MODULE:ATTRIBUTE` names the application to inspect. A **factory is expected**, because an
  `App` only exists once something constructs it; it is called, and nothing in it is started, so no
  service is constructed and no connection is opened.
- `--app-dir DIR` makes a `src` layout importable without installing it — the same escape hatch the
  ASGI server offers.
- Route handlers are compiled through the adapter when the `http` extra is installed, which is what
  catches a bad handler signature offline. Without the extra, the count is reported as *not
  compiled* rather than as a failure, because an application with no routes is a legitimate
  application.
- It is read-only: nothing is written, started, or imported beyond the target.

### Three outputs for machines

The report is for a person. Three flags produce the same facts in a shape a script or an editor can
consume, and they are mutually exclusive because each answers a different question completely.

```powershell
xyberos check --json --app billing.app:create_app --app-dir src
xyberos check --why ItemRepository
xyberos check --schema --app billing.app:create_app --app-dir src > xyberos.schema.json
```

- **`--json`** emits one document: the settings, the provider graph with scopes and dependencies, the
  route table including whether it compiled, the plugin list with states, and the version of the
  document itself. It is assembled from the same calls the text report uses, so the two cannot
  disagree, and its keys are a contract — [ADR 0020](./adr/0020-introspection-documents.md) records
  why, and a rename fails a test rather than your pipeline. A missing extra is named through the
  same lookup the runtime's own import error uses.
- **`--why CONTRACT`** prints the resolution path for one contract: which provider satisfied it, at
  which scope, from which registration, and which dependency each hop came through. It is the
  sentence `App.validate()` already builds for a failure, asked on purpose, and an unknown name is
  refused with the list of registered ones.
- **`--schema`** emits JSON Schema for `xyberos.toml`, generated from the `Settings` dataclasses, so
  a renamed field cannot leave a stale property behind. It covers `schema_version`, `app`, and — with
  `--app` — **each plugin's declared `config_type` section**, which is the completion a plugin author
  wants for `[plugins.<name>]`. The `[ai.<name>]` channel is described as "an object" on purpose:
  core does not know its keys, and a schema that guessed would validate less than it reads. The same
  schema ships inside the package as `xyberos/config.schema.json` for the case where you would rather
  point an editor at a file than run a command.

## `xyberos new`

Writes a minimal project that already runs: a composition root, one service, two routes, a settings
file, a test, and a `.gitignore`.

```powershell
xyberos new billing
cd billing
python -m pip install -e ".[http,dev]" uvicorn
pytest
xyberos check --app billing.app:create_app --app-dir src
```

- The name must be a valid lower-case Python identifier, because the distribution name and the
  import name are the same here.
- An existing non-empty directory is never overwritten. `--force` writes into one, and is only for
  the case where you have already decided the contents do not matter.
- The generated project is the same shape the [getting started guide](./getting-started.md)
  describes, so the code you read while scaffolding is the code you keep.

## `xyberos run`

Hands an import string to an ASGI server and owns nothing else.

```powershell
xyberos run --app billing.app:asgi_app --app-dir src --reload
xyberos run --app sqlite_crud.app:app_factory --factory --app-dir examples --port 9000
```

- **The server is not a dependency.** If none is installed, the command says so and names the
  install; it will not choose one for you.
- The target is passed to the server as an import string, so the server keeps ownership of
  reloading, workers, and graceful shutdown. `--reload` therefore works exactly as it does without
  this command, and `--app-dir` means the same thing it means there.
- `--factory` is for a target that builds the application when called.
- Nothing is imported on the application's behalf, which is precisely what keeps `--reload` correct.

## `xyberos migrate`

Applies Alembic revisions from a directory to a database URL, at deploy time, explicitly.

```powershell
xyberos migrate --migrations migrations --url "sqlite:///var/app.db"
```

- The URL is the **synchronous** one, because Alembic's engine is synchronous.
- `--async` applies inside an event loop, for a caller that is already there.
- A password in the URL is never printed. The success line quotes a redacted form, and a failure is
  reported as this command's own message with the URL and every encoding of its password scrubbed
  out — because a traceback is the ordinary way a configured value ends up in a CI log. A URL
  containing a percent sign works rather than failing, which it did not always.
- Migrations are never applied at application startup, and this command does not change that: it is
  the explicit deploy step, not an implicit one.

## `xyberos durable status`

Reports what a durable journal holds, **without changing it**. The durable executor is experimental,
and its journal is a SQLite file you could read by hand with SQL; this is that reading, without the
SQL and without the risk of getting a statement wrong.

```powershell
xyberos durable status
xyberos durable status --journal var/journal.db --json
```

```text
journal: var/journal.db
schema version: 1
size: 81920 bytes
queued: 1  running: 0  retrying: 0  waiting: 1
completed: 0  failed: 0  cancelled: 0  timed out: 0
expired leases: 0
incompatible definitions: 0
oldest unfinished: 54dce55f… (orders v1, waiting, submitted 2026-05-01T09:00:00+00:00)
parked: 1
  - 54dce55f… (orders v1, waiting, submitted 2026-05-01T09:00:00+00:00): the step declares no retry policy
read-only: opened mode=ro, never migrated, no journal byte written
```

- **It cannot write.** The file is opened through SQLite's `mode=ro` URI, so the driver refuses a
  write rather than this command promising not to attempt one, and the schema is never migrated. A
  journal written by a newer package is reported as the refusal `xyberos.durable` already raises —
  with the `upgrade xyberos` sentence — and is left exactly as it was.
- **It never creates the journal.** A missing file is reported, not initialized: pointing at the
  wrong path must not quietly start a new history.
- **SQLite still creates its own sidecars.** Opening a WAL database creates `-shm` and an empty
  `-wal` beside it; those are SQLite's bookkeeping, and the journal's bytes are unchanged.
- `--journal PATH` points at a specific file; the default is the same `var/journal.db` a worker uses.
- `--json` emits the same snapshot as one document, with the counters, the lease facts, the oldest
  unfinished execution, and each parked execution with the reason it was parked. The document is
  versioned like `check --json`, for the same reason.
- It exits `0` whenever the journal is readable. A status is a report; a pipeline that needs a
  verdict reads the JSON and decides.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | the command did what it said |
| `1` | the command failed — invalid configuration, a missing server, a failed migration |
| `2` | what you asked for is wrong — an unimportable target, a missing attribute, a bad name |

The distinction is there so a script can tell a typo from a broken deployment without parsing the
message. Failures are printed to standard error as `xyberos: error: ...`; a command's report goes to
standard output.

## What the CLI will not do

- **It will not import your application to run it.** Only `check` imports the target, and only to
  validate it; the server does its own importing so reloading works.
- **It will not start an application implicitly.** There is no command that starts an `App` and
  serves it through a Xyberos-owned server, because a second serving path is a second set of bugs.
- **It will not manage your environment.** No dependency resolution, no model downloads, no
  service installation.
- **It is not the only way to do anything.** Every command has a documented equivalent that does not
  involve the CLI at all; `check` is `App.validate()` plus `App.diagnostics()`, and `run` is
  whatever your ASGI server already does. `durable status` is `JournalStore.stats()`,
  `oldest_non_terminal()`, and `list_executions(status="waiting")` — the CLI only formats them.
