# Xyberos

Xyberos is an experimental, composable Python application runtime. Its planned stable
surface is application composition, typed dependencies, Starlette-backed HTTP, SQLite,
and explicit in-process Workflow execution. Durable execution and AI adapters are optional.

The project is currently at version `0.0.0`. Phases 0–6 are complete: the architecture baseline, the
application runtime, the Starlette HTTP adapter with the SQLite database provider, the trusted
plugin/capability model, the in-process workflow engine, the provider-neutral AI facade with Ollama
as the first adapter, and the experimental durable executor. Phase 7 (developer experience,
hardening, and release) is in progress: the public surface and its versioning rules are now frozen in
[the stability guide](docs/stability.md) and [ADR 0013](docs/adr/0013-stable-surface-and-versioning.md),
and release engineering is what remains. Breaking changes are expected before `1.0.0`. **Durable
execution is experimental** and is never represented as exactly-once, multi-host, or highly available.

## Runtime

The stable `xyberos` import root exposes the core runtime: application composition, typed
configuration, dependency injection, lifecycle, context/logging helpers, and route records. It
never imports optional capabilities.

```python
from typing import Annotated

from xyberos import App, Inject, Settings


class Repository:
    async def list_users(self) -> list[str]:
        return []


class UserService:
    def __init__(self, repository: Annotated[Repository, Inject()]) -> None:
        self.repository = repository


async def main() -> None:
    app = App(settings=Settings.load())
    app.provide(Repository)
    app.provide(UserService)

    async with app.lifespan():
        service = await app.resolve(UserService)
        print(await service.list_users())
```

See [the runtime guide](docs/runtime.md) for scopes, lifecycle, configuration, and the error
taxonomy, or start from [the getting started guide](docs/getting-started.md) and
[the hello app example](examples/hello_app/README.md).

## HTTP and database

HTTP support is an optional extra over Starlette, and the SQLite provider is an optional extra
over SQLAlchemy Core and `aiosqlite`:

```python
from typing import Annotated

from xyberos import App, Inject
from xyberos.database import DatabaseProvider, SqliteSettings, sqlite_provider
from xyberos.http import HttpAdapter

app = App()
app.provide(DatabaseProvider, factory=sqlite_provider(SqliteSettings()), eager=True)


@app.get("/health")
async def health(database: Annotated[DatabaseProvider, Inject()]) -> dict[str, str]:
    await database.health()
    return {"status": "ready"}


asgi_app = HttpAdapter(app).asgi_app
```

See the [HTTP guide](docs/http.md), the [database operations guide](docs/database.md), and the
[`sqlite_crud` example](examples/sqlite_crud/README.md).

## Plugins

Trusted, in-process capability integrations are added explicitly:

```python
from xyberos import App, Plugin


class GreetingPlugin(Plugin[None]):
    name = "greeting"
    config_type = None

    def register(self, app: App, config: None) -> None:
        app.provide(Greeter, instance=Greeter())


app = App()
app.add_plugin(GreetingPlugin())
```

Plugins are ordinary Python code — there is no sandbox — and `app.diagnostics().render()` reports
where every provider came from and in which order plugins start. See the
[plugin guide](docs/plugins.md) and the [`custom_plugin` example](examples/custom_plugin/README.md).

## Workflows

Multi-step work can be expressed as an immutable, inspectable definition with bounded retries,
conditional branches, per-step timeouts, a whole-run budget, cooperative cancellation, and
structured events. The engine is part of core and imports no optional capability:

```python
from xyberos import Retry, StepContext, Workflow, seconds


async def retrieve(value: str, context: StepContext) -> list[str]:
    return [f"document-for-{value}"]


async def answer(value: list[str], context: StepContext) -> str:
    return f"answer from {len(value)} document(s)"


workflow = (
    Workflow("support", version="1")
    .step("retrieve", retrieve, retry=Retry(max_attempts=3))
    .step("answer", answer, timeout=seconds(30))
    .edge("retrieve", "answer")
)

result = await workflow.run(input="T-1", timeout=seconds(45))
```

In-process execution keeps no state after the process exits and promises no recovery; durable
execution is a separate, experimental phase. See the [workflow guide](docs/workflow.md) and the
[`workflow` example](examples/workflow/README.md).

## AI

The AI facade is provider-neutral and dependency-free, so it ships in core: contracts, structured
output over a closed JSON Schema subset, allowlisted tool invocation, streaming, embeddings, and a
deterministic fake provider are all usable and testable with no SDK and no model service. Only a
vendor adapter needs an extra:

```python
from typing import Annotated

from xyberos import App, Inject
from xyberos.ai import AIFacade, ChatRequest, Message
from xyberos.ai.ollama import OllamaSettings, ollama_provider

provider_factory = ollama_provider(OllamaSettings(model="your-model"))


async def assistant_factory() -> AIFacade:
    return AIFacade(await provider_factory())


app = App()
app.provide(AIFacade, factory=assistant_factory, eager=True)


@app.get("/ask")
async def ask(assistant: Annotated[AIFacade, Inject()]) -> str:
    response = await assistant.chat(ChatRequest(messages=(Message.user("Hello"),)))
    return response.message.content
```

Prompt, completion, and credential content stays out of logs by default; content capture is an
explicit, redacted opt-in, and `Message` content never reaches an event payload. Ollama is never
started, stopped, or downloaded by the framework: a missing model is a configuration error, not
something the framework fixes. See the [AI guide](docs/ai.md) and the
[`ai_assistant` example](examples/ai_assistant/README.md).

## Durable execution (experimental)

Multi-step work can outlive the process that was running it. Progress is persisted in a separate
SQLite journal, so a new worker resumes from the record instead of from memory:

```python
from xyberos.durable import ActivityPolicy, JournalSettings, JournalStore, open_journal
from xyberos.durable.worker import DurableWorker, WorkerSettings

journal = await open_journal(JournalSettings(path="var/journal.db"))
store = JournalStore(journal)

await store.submit(workflow, input={"invoice": "INV-1001"}, execution_id="invoice-1001")

worker = DurableWorker(
    store,
    {"invoice:1": workflow},
    activities={"charge": ActivityPolicy()},
    settings=WorkerSettings(owner="worker-1"),
)
await worker.serve()
```

The limits are part of the contract, not a disclaimer: **single host, one journal file, at-least-once
effects**. A persisted step result proves a step completed, not that its external effect happened
exactly once. An attempt whose outcome cannot be established is recorded as `outcome_unknown` and
parked for a decision rather than retried on a guess. See the
[durable execution guide](docs/durable.md), [ADR 0011](docs/adr/0011-durable-executor-contract.md),
and the [`durable_workflow` example](examples/durable_workflow/README.md).

## Command line

Four commands wrap APIs the runtime already provides — nothing is re-implemented, and no server is
bundled:

```powershell
xyberos new myapp                                   # a minimal project that runs
xyberos check --app myapp.app:create_app --app-dir src   # settings, provider graph, handler signatures
xyberos run --app myapp.app:asgi_app --app-dir src --reload   # delegate to your ASGI server
xyberos migrate --migrations migrations --url "sqlite:///var/app.db"
```

`check` never starts the application, and `run` hands the import string to the ASGI server so
reloading and shutdown stay the server's business. See the
[command-line guide](docs/cli.md).

## Development

Use Python 3.10 or newer. Install the project with development tools and run the quality
suite:

```powershell
python -m pip install -e ".[dev,http,database]"
python -m pytest
ruff check src tests examples
ruff format --check src tests examples
mypy
python -m build
```

Optional capability dependencies are intentionally separate:

```powershell
python -m pip install -e ".[http]"
python -m pip install -e ".[database]"
python -m pip install -e ".[ollama]"
python -m pip install -e ".[durable]"
```

See [the architecture plan](docs/PLAN.md), [the phase-by-phase implementation plan](docs/implementation.md), [the getting started guide](docs/getting-started.md), [the command-line guide](docs/cli.md), [the runtime guide](docs/runtime.md), [the HTTP guide](docs/http.md), [the database operations guide](docs/database.md), [the plugin guide](docs/plugins.md), [the workflow guide](docs/workflow.md), [the AI guide](docs/ai.md), [the durable execution guide](docs/durable.md), [the testing guide](docs/testing.md), [the troubleshooting guide](docs/troubleshooting.md), [the security guide](docs/security.md), [the stability guide](docs/stability.md), [the release guide](docs/release.md), and [the architecture decisions](docs/adr/). Contributors should read [the changelog](CHANGELOG.md) and [the security policy](SECURITY.md).

## Status and compatibility

`0.x` releases are preview releases. The first release intended to provide the stable
runtime and Workflow guarantees described in the implementation plan will be `1.0.0`.

[The stability guide](docs/stability.md) lists which surface is stable, preview, or experimental, and
how each one changes; [ADR 0013](docs/adr/0013-stable-surface-and-versioning.md) records the rules
behind it. A `0.x` minor release may break a stable name with upgrade notes; a patch release does not.

The project is licensed under the [Apache License 2.0](LICENSE), including its express patent
grant. See [ADR 0012](docs/adr/0012-project-licence.md) for why that licence was chosen, and
`CONTRIBUTING.md` for the contributor terms that are still open.

Nothing is released yet: the version is a `0.0.0` placeholder, the first release will be `0.1.0`, and
[the release guide](docs/release.md) is the procedure. Security reports go through
[SECURITY.md](SECURITY.md), and changes are recorded in [the changelog](CHANGELOG.md).
