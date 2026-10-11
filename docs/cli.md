# Command-line guide

> Status: Phase 7. The **command and its options are the promise**; the Python modules behind them
> are internal and may move in any release. See the [stability guide](./stability.md).

The `xyberos` command exists so that four things a developer does over and over are one documented
line each: inspecting a composition, starting a project, running a server, and applying migrations.
It is a front door over APIs the runtime already proves — it never becomes a second implementation
of the runtime, never starts an application implicitly, and never ships a server.

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
  whatever your ASGI server already does.
