# Xyberos tutorial

> **Status:** Phase 7. This is the step-by-step tutorial: read it in order, run everything, and you
> will have built an HTTP application, stored data, written tests, added a plugin, run a workflow,
> and called a model. Each chapter's code is a real file under `examples/tutorial/`, and every
> "Output" block on this page is produced by running that file — the suite checks each one
> (`tests/integration/test_tutorial.py`), so nothing here can quietly become wrong.

## What you will learn

| Chapter | Topic | You will run |
| --- | --- | --- |
| [1](#chapter-1--your-first-application) | Your first application | `python examples/tutorial/chapter1_first_app.py` |
| [2](#chapter-2--services-that-need-other-services) | Services that need other services | `chapter2_injection.py` |
| [3](#chapter-3--how-long-a-service-lives) | How long a service lives | `chapter3_scopes.py` |
| [4](#chapter-4--settings) | Settings from a file and the environment | `chapter4_config.py` |
| [5](#chapter-5--an-application-that-answers-http) | An application that answers HTTP | `chapter5_http.py` |
| [6](#chapter-6--reading-a-request-and-saying-no-to-one) | Reading a request, saying no to one | `chapter6_requests_and_errors.py` |
| [7](#chapter-7--storing-data-in-sqlite) | Storing data in SQLite | `chapter7_database.py` |
| [8](#chapter-8--writing-your-first-test) | Writing your first test | `pytest tests/tutorial` |
| [9](#chapter-9--adding-a-plugin) | Adding a plugin | `chapter9_plugins.py` |
| [10](#chapter-10--doing-several-things-in-order) | Doing several things in order | `chapter10_workflow.py` |
| [11](#chapter-11--asking-a-model-for-something) | Asking a model for something | `chapter11_ai.py` |
| [12](#chapter-12--surviving-a-crash) | Surviving a crash (experimental) | `chapter12_durable.py` |
| [13](#chapter-13--the-command-line) | The command line | `xyberos --help` |

## What you need

- **Python 3.10 or newer.**
- **Xyberos**, from PyPI, with the `http` and `database` extras.
- **A terminal.** The examples use PowerShell on Windows; the same commands work in any shell.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install "xyberos[http,database]" uvicorn
```

`uvicorn` is the web server we will use. It is *not* part of Xyberos: a framework that refuses to
depend on an HTTP library should not force a server on you either.

## How to read this

Each chapter has the same shape:

1. A short explanation.
2. **Try it** — the code.
3. **Output** — exactly what you should see.
4. Something to remember, and an exercise.

Type the code rather than copying it. Reading code you have not typed is how you learn to *recognise*
code; typing it is how you learn to *write* it.

---

## Chapter 1 — your first application

An application is a **composition root**: you say which services it has and which routes it answers,
and the runtime owns their lifetimes. Here is the smallest one.

**Try it** — `examples/tutorial/chapter1_first_app.py`:

```python
import asyncio

from xyberos import App


class Greeter:
    """A service: an ordinary class that knows nothing about Xyberos."""

    def greet(self, name: str) -> str:
        return f"Hello, {name}!"


async def main() -> None:
    app = App()
    app.provide(Greeter)

    async with app.lifespan():
        greeter = await app.resolve(Greeter)
        print(greeter.greet("world"))
        print("state:", app.state.value)


if __name__ == "__main__":
    asyncio.run(main())
```

**Output:**

<!-- output: chapter1_first_app -->
```text
Hello, world!
state: ready
```

Three things are happening, and everything later builds on them:

| Line | What it does |
| --- | --- |
| `app.provide(Greeter)` | registers `Greeter` as a service, keyed by its own class |
| `async with app.lifespan()` | starts the application, and stops it when the block ends |
| `await app.resolve(Greeter)` | asks the application for the service |

> **Remember** — `app.resolve` is *asynchronous*, so it needs `await`. Forgetting the `await` is the
> most common first mistake: you get a coroutine instead of a service, and an `AttributeError` such as
> `'coroutine' object has no attribute 'greet'`.

> **Note** — nothing was configured by name. `Greeter` is registered by its own class, and services
> that need it will declare `Annotated[Greeter, Inject()]`. There is no container to look things up
> in, and no way to resolve a service by writing its name in a parameter.

### Exercise 1

Make the greeting say your name instead of `world`.

<details>
<summary>Show the answer</summary>

Change one line:

```python
        print(greeter.greet("Ada"))
```

The output becomes `Hello, Ada!` and the second line is unchanged.
</details>

---

## Chapter 2 — services that need other services

Services normally need other services. You declare that in the constructor, with a type annotation and
an `Inject()` marker.

**Try it** — the important parts of `chapter2_injection.py`:

```python
class UserService:
    """A service that declares what it needs, and nothing else."""

    def __init__(self, repository: Annotated[Repository, Inject()]) -> None:
        self._repository = repository

    def summary(self) -> str:
        return ", ".join(self._repository.names())


async def main() -> None:
    app = App()
    app.provide(Repository)
    app.provide(UserService)
    app.validate()

    async with app.lifespan():
        print("users:", (await app.resolve(UserService)).summary())
```

**Output:**

<!-- output: chapter2_injection -->
```text
users: ada, linus
no provider is registered for Repository; required by UserService
```

The second line of that output is the important one. That is what happens when you forget to register
something, and the same file produced it:

```python
    broken = App()
    broken.provide(UserService)
    broken.validate()   # ← raises MissingProviderError
```

```text
no provider is registered for Repository; required by UserService
```

| Rule | Why it is a rule |
| --- | --- |
| Every required parameter needs `Annotated[T, Inject()]` | dependencies are read from the type, so nothing depends on a parameter's *name* |
| `app.validate()` checks the whole graph without building anything | a wiring mistake is a startup error, not a first-request error |
| The error names the consumer, not just the missing piece | `required by UserService` tells you where to look |

> **Note** — a dependency can also be keyed by an opaque value, such as a string, with
> `Annotated[T, Inject(contract="primary")]`. That matters when two implementations of the same type
> exist. You will meet it again in the [plugin guide](../docs/plugins.md).

### Exercise 2

Add a `Formatter` service that `UserService` depends on, and have `summary()` use it.

<details>
<summary>Show the answer</summary>

```python
class Formatter:
    def format(self, names: list[str]) -> str:
        return ", ".join(names)


class UserService:
    def __init__(
        self,
        repository: Annotated[Repository, Inject()],
        formatter: Annotated[Formatter, Inject()],
    ) -> None:
        self._repository = repository
        self._formatter = formatter

    def summary(self) -> str:
        return self._formatter.format(self._repository.names())
```

Add `app.provide(Formatter)`. The output does not change — which is the point: the graph grew and the
behaviour did not.
</details>

---

## Chapter 3 — how long a service lives

How long should one instance live? Xyberos gives you exactly three answers.

| Scope | Instances | Use it for |
| --- | --- | --- |
| `Scope.APP` *(default)* | one per application | connection pools, clients, configuration-backed services |
| `Scope.REQUEST` | one per request | per-request state, a unit of work |
| `Scope.TRANSIENT` | a new one every time | stateless helpers |

**Try it** — `chapter3_scopes.py`:

```python
app.provide(Cache)                                  # Scope.APP by default
app.provide(RequestState, scope=Scope.REQUEST)
app.provide(Formatter, scope=Scope.TRANSIENT)
```

**Output:**

<!-- output: chapter3_scopes -->
```text
app-scoped gives the same instance: True
transient gives a new instance: False
request-scoped is stable inside one request: True
request-scoped is new in the next request: True
```

> **Remember** — a **longer-lived service may not depend on a shorter-lived one**. An app-scoped
> service cannot hold a request-scoped one, because the request-scoped instance would outlive the
> request it belongs to. If you try, `App.validate()` refuses it:

```text
ScopeViolationError: app-scoped Holder cannot depend on shorter-lived request-scoped RequestThing
```

> **Note** — a transient provider may not own a managed resource (something with a `close` or
> `aclose` method), because nothing would ever close it. If you need cleanup, the service wants a
> real scope.

### Exercise 3

Predict the output before running it, then check.

```python
app.provide(Formatter, scope=Scope.TRANSIENT)
```

```python
first, second = await app.resolve(Formatter), await app.resolve(Formatter)
```

<details>
<summary>Show the answer</summary>

`first is second` is `False`. A transient provider builds a new instance for every resolution — that
is what "transient" means, and it is why the chapter's output says
`transient gives a new instance: False` for that identity check.
</details>

---

## Chapter 4 — settings

Configuration comes from four places. The one that wins is the one highest in this list:

1. **explicit arguments** you pass in code,
2. **environment variables** starting with `XYBEROS_`,
3. **the file** `xyberos.toml`,
4. **defaults**.

**Try it** — `chapter4_config.py` writes this file, then loads it three ways:

```toml
[app]
name = "tutorial"
environment = "staging"
debug = true
```

```python
settings = Settings.load(environ={}, cwd=Path(directory))
print(settings.app.name)                                      # from the file

settings = Settings.load(environ={"XYBEROS_APP__NAME": "from-the-environment"}, cwd=...)
print(settings.app.name)                                      # the environment wins

settings = Settings.load(environ={...}, overrides={"app": {"name": "from-the-arguments"}}, cwd=...)
print(settings.app.name)                                      # arguments win
```

**Output:**

<!-- output: chapter4_config -->
```text
from the file: tutorial staging True
the environment wins: from-the-environment
arguments win: from-the-arguments
```

| You write | You get |
| --- | --- |
| `[app] name = "tutorial"` | `settings.app.name` |
| `XYBEROS_APP__NAME=tutorial` | the same setting, from the environment |
| `XYBEROS_CONFIG=/etc/xyberos.toml` | a different file to read |
| `Settings.load(overrides={"app": {"debug": True}})` | an explicit argument, highest precedence |

Notice the double underscore in `XYBEROS_APP__NAME`: one `_` separates words inside a name, and `__`
walks into a section. So `XYBEROS_APP__SHUTDOWN_TIMEOUT` sets `[app] shutdown_timeout`.

> **Remember** — reading settings is done through the application: `app.settings.app.name`. There is
> no global settings object, and no `app.name` shortcut.

> **Note** — a key you misspell is an error, not a silent default:

```text
ConfigurationError: unknown setting(s) at app: unknown
```

Error messages name the field and where it came from. They never print the value, because values can
be secrets.

### Exercise 4

Set the application name from the environment *without* changing the file.

<details>
<summary>Show the answer</summary>

```powershell
$env:XYBEROS_APP__NAME = "from-the-environment"
python examples/tutorial/chapter4_config.py
```

The file still says `tutorial`; the environment overrides it. That is the point of the precedence
order: a deployment can change configuration without editing anything under version control.
</details>

---

## Chapter 5 — an application that answers HTTP

HTTP support is an optional extra. Install it with `pip install "xyberos[http]"`.

The rule to remember is this: **the runtime owns composition, Starlette owns ASGI mechanics.** Route
records live in core; the adapter compiles them.

**Try it** — `chapter5_http.py`:

```python
def create_app() -> App:
    app = App()
    app.provide(Greeter)

    @app.get("/")
    async def hello(greeter: Annotated[Greeter, Inject()]) -> dict[str, str]:
        return {"message": greeter.greet("world")}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

A handler's parameters are its whole interface: `request: Request` comes from Starlette, a name that
appears in the route path comes from the URL, and anything marked `Inject()` comes from the graph.

**Output** — the chapter uses the same test client the test suite uses, so no server is needed:

<!-- output: chapter5_http -->
```text
status: 200
json: {'message': 'Hello, world!'}
health: {'status': 'ok'}
correlation id set: True
```

To run it for real, use any ASGI server:

```powershell
uvicorn --app-dir examples/tutorial --factory chapter5_http:app_factory
curl "http://127.0.0.1:8000/health"
```

| Handler returns | Response |
| --- | --- |
| a `Response` | sent unchanged |
| `None` | `204 No Content` |
| anything else | `200` with JSON |

> **Note** — `HttpAdapter(app)` validates handler signatures *when it is constructed*, so a handler
> with a mistake fails at startup, not on the first request. `chapter5_http.py` builds the adapter in
> `build_asgi_app`, which is the one place that touches the extra.

### Exercise 5

Add a route `/hello/{name}` that greets whoever is in the URL.

<details>
<summary>Show the answer</summary>

```python
    @app.get("/hello/{name}")
    async def hello_name(name: str, greeter: Annotated[Greeter, Inject()]) -> dict[str, str]:
        return {"message": greeter.greet(name)}
```

```python
print(client.get("/hello/Ada").json())   # {'message': 'Hello, Ada!'}
```

The path parameter `name` is converted to `str` automatically. Declare it as `int` and Xyberos will
convert it to an integer, or refuse the request if it is not one.
</details>

---

## Chapter 6 — reading a request, and saying no to one

A handler either returns a value or raises an error. Errors know which HTTP status they mean.

**Try it** — `chapter6_requests_and_errors.py`:

```python
class ItemNotFoundError(HttpError):
    """A domain error that knows which HTTP status it means."""

    def __init__(self, item_id: int) -> None:
        super().__init__(f"item {item_id} was not found", status_code=404)


@app.get("/items/{item_id}")
async def get_item(item_id: int) -> dict[str, object]:
    if item_id not in ITEMS:
        raise ItemNotFoundError(item_id)
    return {"item_id": item_id, "name": ITEMS[item_id]}
```

**Output:**

<!-- output: chapter6_requests_and_errors -->
```text
found: {'item_id': 1, 'name': 'notebook'}
query: {'query': 'book'}
missing status: 404
missing body: {'error': {'type': 'ItemNotFoundError', 'message': 'item 99 was not found'}}
created: {'created': 'pen', 'id': 2}
broken body status: 422
broken body type: RequestValidationError
```

| You raise | The client receives |
| --- | --- |
| a subclass of `HttpError` | its `status_code` and `{"error": {"type", "message"}}` |
| a bad JSON body | `422` from `read_json_object` |
| anything else | `500` with a generic message — the traceback goes to the log, never to the client |

Reading input has one recommended way:

```python
payload = await read_json_object(request)     # a dict, or a 422
```

Read query strings, headers, and bodies from `request`:

```python
print(request.query_params.get("q", "all"))
print(request.headers.get("X-Request-ID", ""))
```

> **Remember** — a request failed because of the *client* only when you say so by raising
> `RequestValidationError` or an `HttpError`. Everything else is your bug, and the client learns
> nothing about it except that it failed.

> **Note** — every response carries a correlation ID (`X-Request-ID`), either the one the client sent
> or a new one. It is the first thing to look for in a log, and it is also why you should treat it as
> untrusted display data rather than as an identity.

### Exercise 6

Return `409 Conflict` when an item is created twice.

<details>
<summary>Show the answer</summary>

```python
class ItemAlreadyExistsError(HttpError):
    def __init__(self, name: str) -> None:
        super().__init__(f"{name!r} already exists", status_code=409)
```

Raise it from the handler when the name is already in the store. The client sees status `409` and a
body whose `error.type` is `ItemAlreadyExistsError`.
</details>

---

## Chapter 7 — storing data in SQLite

SQLite support is an optional extra: `pip install "xyberos[database]"`. It gives you SQLAlchemy Core
over SQLite, with the PRAGMAs your application needs already set.

**Try it** — the service in `chapter7_database.py`. Note what it does *not* contain: any HTTP type.

```python
metadata = MetaData()

items = Table(
    "items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String, nullable=False),
)


class ItemStore:
    def __init__(self, database: Annotated[DatabaseProvider, Inject()]) -> None:
        self._database = database

    async def add(self, name: str) -> None:
        async with self._database.transaction() as connection:
            await connection.execute(insert(items).values(name=name))
```

**Output:**

<!-- output: chapter7_database -->
```text
rows: [{'id': 1, 'name': 'notebook'}]
rows after the rollback: 1
```

Two rules explain everything about that output:

| Rule | What it means for you |
| --- | --- |
| A transaction commits on success and rolls back when the body raises | a failed write leaves no half-written row, so the second line still says `1` |
| SQLite allows one writer at a time | keep write transactions short, and never hold one across a network call |

| Task | How |
| --- | --- |
| Read or write | `async with database.transaction() as connection:` |
| Retry a locked write | `await database.retrying(operation, attempts=5, base_delay=0.05)` |
| Create the schema | Alembic migrations, run at deploy time — see the [database guide](../docs/database.md) |
| Test against SQLite | `async with temporary_database() as database:` |

> **Note** — `retrying` is opt-in and bounded, because only *you* know whether an operation is safe to
> run twice. If it is not, give it an idempotency key rather than hoping.

### Exercise 7

Add a `rename` method, and a route that calls it.

<details>
<summary>Show the answer</summary>

```python
    async def rename(self, item_id: int, name: str) -> None:
        async with self._database.transaction() as connection:
            await connection.execute(
                update(items).where(items.c.id == item_id).values(name=name)
            )
```

(Add `update` to the imports from `sqlalchemy`.)

```python
    @app.patch("/items/{item_id}")
    async def rename_item(
        item_id: int, request: Request, store: Annotated[ItemStore, Inject()]
    ) -> dict[str, object]:
        payload = await read_json_object(request)
        await store.rename(item_id, str(payload.get("name")))
        return {"renamed": item_id}
```
</details>

---

## Chapter 8 — writing your first test

There is no Xyberos test runner and no plugin to install. A test is a pytest test; what the framework
adds is the doubles that make it fast, and one habit: **a test double must satisfy the contract.**

**Try it** — the chapter *is* a test file. Copy it into your project as `tests/test_app.py`, then run
`pytest`. Here is its shape:

```python
class ItemReader(Protocol):
    """The contract: what a caller needs, not what an implementation is."""

    def all(self) -> list[str]: ...


class ItemStore:
    """The real implementation."""


class FakeItemStore:
    """A test double that satisfies the same contract."""

    def all(self) -> list[str]:
        return ["from the fake"]


def create_app() -> App:
    app = App()
    app.provide(ItemReader, instance=ItemStore())

    @app.get("/items")
    async def list_items(items: Annotated[ItemReader, Inject()]) -> list[str]:
        return items.all()

    return app
```

```python
def test_a_dependency_can_be_replaced() -> None:
    app = create_app().with_overrides({ItemReader: FakeItemStore()})

    with create_test_client(HttpAdapter(app)) as client:
        assert client.get("/items").json() == ["from the fake"]
```

**Output:**

```text
....                                                                     [100%]
4 passed in 0.07s
```

(Your run will show its own timing. What matters is the count: every test in the chapter passes.)

The whole file runs with:

```powershell
python -m pytest tests/tutorial -q
```

| Habit | Why |
| --- | --- |
| Use `create_test_client(...)` as a context manager | entering it runs the lifespan, which validates and starts the application |
| Override the *contract* with `app.with_overrides({...})` | each test gets its own application, so nothing leaks between tests |
| Write `asyncio.run(scenario())` inside a sync test | no `pytest-asyncio` marker and no plugin: each test gets its own event loop, which is what an `App` requires anyway |
| Never sleep | inject a clock and move it — see the [testing guide](../docs/testing.md) |

> **Remember** — the double must satisfy the contract. Override a class contract with something that
> is not an instance of it and you get a resolution error when the service is first used:

```text
DependencyResolutionError: provider for ItemStore returned FakeItemStore
```

> **Note** — a request made *outside* the client's context manager is refused with a `500`, because
> the application has not started. If every request fails in a test, check the `with` block first.

### Exercise 8

Write a test that fails because the application is wired incorrectly, then fix the wiring.

<details>
<summary>Show the answer</summary>

```python
def test_missing_provider_is_a_startup_error() -> None:
    app = App()
    app.provide(ItemStore)          # ItemStore needs a DatabaseProvider
    with pytest.raises(MissingProviderError):
        app.validate()
```

`MissingProviderError` names both the missing piece and the service that needed it, which is usually
enough to fix the wiring without debugging.
</details>

---

## Chapter 9 — adding a plugin

A plugin is a bundle of contributions: services, routes, typed configuration. Plugins are **trusted
code** — adding one is equivalent to importing a library.

**Try it** — `chapter9_plugins.py`:

```python
@dataclass(frozen=True)
class CounterConfig:
    start: int = 0


class CounterPlugin(Plugin[CounterConfig]):
    name = "counter"
    api_version = "1"
    config_type = CounterConfig

    def register(self, app: App, config: CounterConfig) -> None:
        app.provide(Counter, instance=Counter(config.start))
```

```python
app.add_plugin(CounterPlugin(), config={"start": 10})
```

**Output:**

<!-- output: chapter9_plugins -->
```text
{'count': 11}
{'count': 12}
--- who provides what ---
providers:
  Counter [app] from plugin:counter
plugins:
  counter 1 [started] requires: -
```

That last block is `app.diagnostics().render()`, and it is the first thing to run when something is
wired surprisingly:

| Line | Meaning |
| --- | --- |
| `Counter [app] from plugin:counter` | the provider came from a plugin, not from your application code |
| `counter 1 [started] requires: -` | the plugin's name, API version, state, and what it depends on |

| Rule | Why |
| --- | --- |
| A plugin's requirements must be registered **before** it is added | order is explicit, so startup is reproducible |
| Plugin configuration is validated against `config_type` | an unknown key fails at startup instead of being ignored |
| Plugins cannot be added after `app.start()` | a running application never gains new routes |

> **Note** — there is no plugin discovery and no sandbox. Application code chooses plugins explicitly,
> which keeps startup visible, and a plugin runs with the full privileges of your process.

### Exercise 9

Give the plugin a route of its own, instead of the application adding it.

<details>
<summary>Show the answer</summary>

Inside `register`:

```python
    def register(self, app: App, config: CounterConfig) -> None:
        app.provide(Counter, instance=Counter(config.start))

        @app.get("/plugin/count")
        async def count(counter: Annotated[Counter, Inject()]) -> dict[str, int]:
            return {"count": counter.bump()}
```

A plugin that adds routes needs the `http` extra installed; a plugin that adds only services does not.
</details>

---

## Chapter 10 — doing several things in order

A **workflow** is a definition: steps, and the edges between them. It is immutable, it validates
before it runs, and it can be inspected without executing anything.

**Try it** — `chapter10_workflow.py`:

```python
workflow = (
    Workflow("tutorial-triage", version="1", input_type=str)
    .step("fetch", fetch, retry=Retry(max_attempts=3, backoff=Backoff(initial=0.5)))
    .step("classify", classify)
    .step("notify", notify)
    .step("archive", archive)
    .edge("fetch", "classify")
    .edge("classify", "notify", when=lambda value: value == "urgent")
    .edge("classify", "archive")
)
```

**Output:**

<!-- output: chapter10_workflow -->
```text
workflow: tutorial-triage version 1
steps: ['fetch', 'classify', 'notify', 'archive']
result: notified about urgent
service calls: 2
virtual time used: 0.5
events:
   #1 workflow_started workflow=tutorial-triage steps=4
   #2 step_started workflow=tutorial-triage step=fetch attempt=1
   #3 step_failed workflow=tutorial-triage step=fetch attempt=1 duration=0.000000 error=RateLimitError
   #4 step_retried workflow=tutorial-triage step=fetch attempt=1 retrying in 0.5s
   #5 step_started workflow=tutorial-triage step=fetch attempt=2
   #6 step_succeeded workflow=tutorial-triage step=fetch attempt=2 duration=0.000000
   #7 step_started workflow=tutorial-triage step=classify attempt=1
   #8 step_succeeded workflow=tutorial-triage step=classify attempt=1 duration=0.000000
   #9 step_started workflow=tutorial-triage step=notify attempt=1
   #10 step_succeeded workflow=tutorial-triage step=notify attempt=1 duration=0.000000
   #11 step_skipped workflow=tutorial-triage step=archive no branch reached this step
   #12 workflow_succeeded workflow=tutorial-triage duration=0.500000 outputs=1
```

Read the output carefully — it teaches the two semantics that surprise people:

- **An edge carries the source step's output to the target.** `fetch` produced `T-urgent-100`,
  `classify` turned that into `urgent`, and `notify` received `urgent`. That is why the result says
  `notified about urgent` and not the ticket id.
- **A branch that is not taken is skipped, not run.** `archive` never started.

And the retry is visible in the events: attempt 1 failed with `RateLimitError`, waited `0.5s` of
*virtual* time, and attempt 2 succeeded.

| Member | Purpose |
| --- | --- |
| `Workflow(name, version=...)` | the definition; `version` is required because a durable executor records what it ran |
| `.step(id, run, retry=, timeout=)` | one step, with its own policy |
| `.edge(source, target, when=...)` | connect two steps, optionally on a condition |
| `.render()` | describe the definition without running it |
| `on_event=` | a sink for structured events (they never contain step input or output) |

> **Remember** — retries wait on the clock you give the executor. `ManualClock` makes them instant and
> exact, which is why a test can assert `clock.sleeps == (0.5,)` instead of sleeping for half a second.

> **Note** — a step with no outgoing edge is an *exit* step, and its output is part of the result. If
> you forget an edge, you get more outputs than you expected:

```text
WorkflowError: workflow 'tutorial-triage' produced 2 outputs (fetch, notify); use result.outputs
```

That error is the definition telling you the graph is not what you meant.

### Exercise 10

Make `archive` run when the ticket is *not* urgent, and prove it with the output.

<details>
<summary>Show the answer</summary>

Add a condition to the second edge:

```python
        .edge("classify", "archive", when=lambda value: value != "urgent")
```

Now every ticket goes down one branch. Change the fake service's reply to `T-normal-200` and the
result becomes `archived normal`.
</details>

---

## Chapter 11 — asking a model for something

The AI facade is part of core and needs no SDK: an adapter speaks the provider's documented HTTP, and
a fake provider makes every scenario testable without a service.

**Try it** — `chapter11_ai.py` uses the fake provider throughout.

```python
provider = FakeModelProvider([ModelReply.ok("Hello from a fake model.")])
assistant = AIFacade(provider)

response = await assistant.chat(ChatRequest(messages=(Message.user("Say hello"),)))
print(response.message.content)
```

Add a schema, and you get validated structured output back:

```python
response = await AIFacade(provider).chat(
    ChatRequest(messages=(Message.user("How much?"),), response_schema=ANSWER_SCHEMA)
)
print(response.structured)
```

**Output:**

<!-- output: chapter11_ai -->
```text
--- 1. a plain question ---
content: Hello from a fake model.
provider calls: 1
--- 2. an answer with a shape ---
structured: {'answer': 'Take one tablet'}
--- 3. letting the model ask for a tool ---
rounds: 2
final: It is 11 degrees in Bergen.
provider calls: 2
```

The third part is the interesting one: the model asked for a tool, and the framework ran it *because
the caller allowed it*.

```python
tools = ToolSet.of(
    Tool(
        spec=ToolSpec(name="weather", description="...", parameters=WEATHER_SCHEMA),
        handler=look_up_weather,
    )
)

response = await assistant.chat_with_tools(request, tools=tools, max_rounds=3)
```

| Guarantee | What it means |
| --- | --- |
| **The tool set is the allowlist** | a call outside it raises `AIToolError` naming what *is* allowed |
| **Nothing a model returns is executed** | a call is resolved against the allowlist, validated against the schema, then run |
| **A handler gets no container** | it can only reach what its author closed over, so adding a tool cannot expose your application |
| **Capabilities are declared, not guessed** | asking a model for tools it does not declare fails before the call |
| **Prompts are not logged by default** | logging is metadata-only; capturing content is an explicit opt-in with redaction |

> **Note** — to use a real model, install the extra (`pip install "xyberos[ollama]"`) and configure it.
> The code above does not change: swap the provider.

> **Remember** — the framework never downloads, starts, or upgrades a model. A missing model is an
> error naming the command to pull it.

### Exercise 11

Make the facade refuse a tool call, and read the error.

<details>
<summary>Show the answer</summary>

Hand it a tool set that does not contain the tool the model asked for:

```python
    response = await AIFacade(provider).chat_with_tools(request, tools=ToolSet.of(), max_rounds=3)
```

```text
AIToolError: the model asked for tool 'weather', which is not allowed for this call; allowed tools: none
```

An empty tool set means no tool can run — the safest default, and a useful one in production.
</details>

---

## Chapter 12 — surviving a crash

> **This chapter is experimental.** Importing the durable package emits an `ExperimentalWarning`, and
> the promises are narrow on purpose: **single instance, one journal file, at-least-once effects**.
> Read the [durable execution guide](../docs/durable.md) before you rely on it.

```text
ExperimentalWarning: xyberos.durable is experimental: single-host and at-least-once only, with no
exactly-once external effects, no multi-host ownership, and no arbitrary Python checkpointing
```

The idea: write the workflow's progress to a database *between* steps, so a process that dies can be
resumed by another one instead of starting again.

**Try it** — `chapter12_durable.py`:

```python
journal = await open_journal(JournalSettings(path=Path(directory) / "journal.db"))
store = JournalStore(journal)
handle = await store.submit(workflow, input="T-100", execution_id="booking-T-100")

worker = DurableWorker(
    store,
    {"tutorial-booking:1": workflow},
    activities={"reserve": ActivityPolicy(idempotent=True), "confirm": ActivityPolicy(idempotent=True)},
    settings=WorkerSettings(owner="tutorial"),
)
while await worker.run_once() is not None:
    pass
```

**Output:**

<!-- output: chapter12_durable -->
```text
submitted: booking-T-100
before any worker: pending
after the worker: completed
result: {'confirm': 'reserved T-100 and confirmed'}
steps: [('reserve', 'succeeded'), ('confirm', 'succeeded')]
events: 9
timeline:
   1 submitted  steps=2
   2 claimed  owner=tutorial fence=1
   3 step_started reserve 
   4 step_succeeded reserve 
   5 yielded  step 'reserve' recorded; ready for the next step
   6 claimed  owner=tutorial fence=2
   7 step_started confirm 
   8 step_succeeded confirm 
   9 completed
```

Read the timeline: the work happened in two claims, and each step's result was committed before the
next one started. That commit is the crash boundary — a step that completed is never re-run because
its result is already in the journal.

| Setting | What it decides |
| --- | --- |
| `ActivityPolicy(idempotent=True)` | this step is safe to run twice, so recovery may replay it |
| `ActivityPolicy(reconcile=...)` | ask *me* what happened instead of guessing |
| neither | the execution is **parked** as `outcome_unknown` for a human or a reconciler to decide |
| `WorkerSettings(owner=...)` | which worker owns a lease; a stale worker's writes are refused |

> **Remember** — the one rule that explains the whole design: **an attempt whose outcome cannot be
> proven is never retried on a guess.** Retrying an effect of unknown status is how a payment gets
> taken twice, so the framework stops and asks instead.

> **Note** — the journal is a *separate* file from your application database, and it must be on a local
> filesystem. The locking it relies on is not dependable over a network share.

### Exercise 12

Make a step fail, and read where it stopped.

<details>
<summary>Show the answer</summary>

```python
    async def confirm(reservation: str, context: StepContext) -> str:
        raise RuntimeError("the confirmation service is down")
```

The execution ends `failed`, and `store.inspect("booking-T-100")` shows the failing step with its
`error_type`, `error_message`, and `attempts`. Because nothing declared a retry, the failure is
terminal rather than retried — retry policy is a decision, not a default.
</details>

---

## Chapter 13 — the command line

Four commands, each a thin wrapper over an API you have already met.

```powershell
xyberos --help
```

| Command | What it does | Needs |
| --- | --- | --- |
| `xyberos check` | loads settings and validates a composed application *without starting it* | core |
| `xyberos new` | writes a project that runs | core |
| `xyberos run` | hands an import string to your ASGI server | an ASGI server |
| `xyberos migrate` | applies Alembic revisions | the `database` extra |

**Try it:**

```powershell
xyberos check
```

**Output:**

<!-- output: cli-check -->
```text
settings: xyberos (development), schema_version 1, debug False
application: not inspected (pass --app module:attribute)
```

And against a real application:

```powershell
xyberos check --app chapter5_http:create_app --app-dir examples/tutorial
```

| Option | Why it exists |
| --- | --- |
| `--app module:attribute` | a *factory* that returns an `App`; it is called, and nothing is started |
| `--app-dir DIR` | makes a `src` layout importable without installing it |
| `--config PATH` | checks a specific settings file instead of the discovered one |

Exit codes are part of the contract:

| Code | Meaning |
| --- | --- |
| `0` | the command did what it said |
| `1` | it failed — invalid configuration, a missing server, a failed migration |
| `2` | what you asked for is wrong — an unimportable target, a bad name |

> **Note** — `xyberos run` never imports your application itself. It passes the import string to the
> server, which keeps `--reload` working exactly as it does without this command.

### Exercise 13

Create a project, run its test, and check it — without reading the other chapters.

<details>
<summary>Show the answer</summary>

```powershell
xyberos new myapp
cd myapp
python -m pip install -e ".[http,dev]" uvicorn
pytest
xyberos check --app myapp.app:create_app --app-dir src
```

The scaffold writes the same shape you built by hand: a composition root, one service, two routes, a
settings file, and a test.
</details>

---

## Exercises wrap-up

If you did the exercises, you have used: providers and injection, all three scopes, configuration
precedence, routes and path parameters, domain errors, transactions and rollback, test overrides,
plugin contributions, workflow retries and branches, schema-validated model output, an allowlisted
tool call, durable steps, and the CLI.

## Where to go next

| You want to | Read |
| --- | --- |
| The rules behind what you just did | [getting started](../docs/getting-started.md), [runtime guide](../docs/runtime.md) |
| To know what you may rely on | [stability guide](../docs/stability.md) |
| To test something that involves time or a model | [testing guide](../docs/testing.md) |
| To fix an error you are looking at | [troubleshooting guide](../docs/troubleshooting.md) |
| To put this in front of users | [security guide](../docs/security.md) |
| To understand the design | [architecture review](../docs/architecture.md), then the [ADRs](../docs/adr/) |
| Worked examples, bigger than these | [`examples/`](../examples/) |

## Cheat sheet

```python
# compose
app = App(settings=Settings.load())
app.provide(Service)                                  # app-scoped by default
app.provide(Service, instance=Service("x"), eager=True)
app.provide(Service, scope=Scope.REQUEST)
app.add_plugin(Plugin(), config={"key": "value"})
app.validate()

# run
async with app.lifespan():
    service = await app.resolve(Service)
    async with app.request_context() as request:
        service = await request.resolve(Service)

# http
@app.get("/items/{item_id}")
async def get_item(item_id: int, request: Request, store: Annotated[Store, Inject()]) -> dict:
    payload = await read_json_object(request)
    return {"id": item_id}

# data
async with database.transaction() as connection:
    await connection.execute(insert(items).values(name="x"))

# workflow
result = await workflow.run(input=value, executor=WorkflowExecutor(), on_event=events.append)

# tests
with create_test_client(HttpAdapter(app)) as client:
    assert client.get("/items").json() == []
app.with_overrides({Contract: fake})
```
