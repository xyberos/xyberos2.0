# Testing guide

> Status: Phase 7. This guide covers the tests you write against a Xyberos application: what to
> override, which doubles to use, and which habits make a test slow or flaky. Every helper named
> here ships with the package, and the [stability guide](./stability.md) says which tier each one
> is in.

Xyberos adds no test runner, no pytest plugin, and no fixture library. Tests are ordinary pytest
tests. What the package provides is *deterministic doubles*: a virtual clock, a scripted service, a
scripted model provider, and a temporary database, so a test can assert exact timing and exact
retry counts instead of sleeping and hoping.

## The shape of a test

```python
import asyncio

from xyberos import App


class Greeter:
    def greet(self, name: str) -> str:
        return f"hello, {name}"


def test_the_greeter_is_reused_within_an_application() -> None:
    async def scenario() -> None:
        app = App()
        app.provide(Greeter)

        async with app.lifespan():
            assert await app.resolve(Greeter) is await app.resolve(Greeter)

    asyncio.run(scenario())
```

The inner `scenario()` function is the whole convention. There is no `pytest-asyncio` marker and no
`asyncio_mode` setting: an async test is a synchronous test that calls `asyncio.run(...)`. That keeps
the runtime and the test suite dependency-free, and it makes the event-loop boundary explicit — each
scenario gets its own loop, which is the boundary a Xyberos `App` requires anyway (an `App` is bound
to the loop that starts it).

## Replacing a dependency

`app.with_overrides({contract: value})` returns an independent application whose listed contracts
resolve to your values. The original is untouched, so nothing leaks between tests or between
parallel runs.

```python
def test_the_handler_uses_the_overridden_service() -> None:
    app = create_app()
    test_app = app.with_overrides({ItemService: FakeItemService(items=["kept"])})

    with create_test_client(HttpAdapter(test_app)) as client:
        assert client.get("/items").json() == ["kept"]
```

Three rules make it predictable:

- The contract must already be registered; overriding an unknown contract raises
  `MissingProviderError` rather than inventing a provider.
- The override keeps the original's scope and `eager` flag, so overriding does not quietly change a
  lifetime.
- **The clone copies providers and routes, but not plugin registrations.** A plugin's `start()` and
  `stop()` hooks therefore do not run twice across clones — and equally, a clone does not have them
  at all. If a test needs plugin lifecycle behavior, build the application for that test rather than
  cloning one that has plugins.

## HTTP

```python
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client


def test_the_route_answers() -> None:
    with create_test_client(HttpAdapter(create_app())) as client:
        response = client.get("/?name=reader")

        assert response.status_code == 200
        assert response.json()["greeting"] == "hello_app says hello, reader"
```

- **Use the client as a context manager.** Entering it runs the ASGI lifespan, which validates the
  provider graph and starts the application. A request made outside the block gets a `500` with the
  generic error body, because the application is still in the `new` state and a half-started
  application never serves work — that refusal is deliberate, so a test that skips the context
  manager is testing the refusal rather than the route.
- `create_test_client` accepts the adapter or a bare ASGI application, so the same client covers
  `HttpAdapter(app).asgi_app`, a module-level `asgi_app`, and middleware passed to the adapter.
- Assert the error *body shape* as well as the status when testing error handling: a client-safe
  response carries `{"error": {"type": ..., "message": ...}}`, and a `500` never carries the
  internal message.

## SQLite

```python
from xyberos.database import temporary_database


def test_a_write_is_rolled_back_with_the_transaction() -> None:
    async def scenario() -> None:
        async with temporary_database() as database:
            with pytest.raises(RuntimeError):
                async with database.transaction() as connection:
                    await connection.execute(insert(items).values(name="lost"))
                    raise RuntimeError("abort")

    asyncio.run(scenario())
```

`temporary_database()` yields a started provider over a real temporary file, not an in-memory
database, so WAL mode, file locking, and PRAGMA initialization behave exactly as they do in
production. Pass `directory=tmp_path` to keep the file for inspection when a test fails, or to drive
two providers against the same file.

## Workflow

```python
clock = ManualClock()
service = FakeExternalService([Reply.rate_limited(), Reply.ok("done")], clock=clock)
workflow = Workflow("demo").step(
    "fetch", fetch, retry=Retry(max_attempts=3, backoff=Backoff(initial=0.5))
)
task = asyncio.ensure_future(workflow.run(executor=WorkflowExecutor(clock=clock)))

result = await clock.drive(task)

assert result.value == "done"
assert service.calls == 2
assert clock.sleeps == (0.5,)  # exactly one backoff delay was requested
```

| Helper | Use it to |
| --- | --- |
| `ManualClock` | Control time. `pending` and `sleeps` report what was requested; `advance` and `advance_to_next` move time; `wait_for_sleepers` reaches the moment the executor is waiting on a deadline; `drive(task)` runs to completion whenever nothing else can progress |
| `FakeExternalService` + `Reply` | Script a dependency: `Reply.ok`, `slow`, `rate_limited`, `transient`, `malformed`, `failing`, each with optional latency |
| `pending_tasks()` | Assert an execution left no task behind, which is how a leak is caught before it becomes a hanging test |

Replies play in order and the last one repeats, so "fails twice, then succeeds" is one line. Use
`wait_for_sleepers`/`advance` — not `drive` — whenever the test asserts *exactly* how much virtual
time passed.

## AI

```python
provider = FakeModelProvider(
    [
        ModelReply.rate_limited(),
        ModelReply.json_payload({"answer": "Take one"}, usage=Usage(11, 4)),
    ]
)
response = await AIFacade(provider).chat(
    ChatRequest(messages=(Message.user("?"),), response_schema=ANSWER_SCHEMA)
)

assert provider.calls == 2
assert response.structured == {"answer": "Take one"}
```

`FakeModelProvider` implements the whole provider contract and enforces declared capabilities the
way a real adapter must, so a test cannot accidentally rely on a request a real provider would
refuse. `ModelReply` has a classmethod per scenario: `ok`, `json_payload`, `wrong_shape`, `malformed`,
`refusal`, `tools`, `failing`, `rate_limited`, `transient`, `timeout`, and `slow`.

Live-model verification exists but is never part of the normal suite; it is gated behind
`XYBEROS_OLLAMA_LIVE`, `XYBEROS_OLLAMA_LIVE_MODEL`, and `XYBEROS_OLLAMA_LIVE_EMBEDDING_MODEL` so a
machine with no model skips rather than fails. See the [AI guide](./ai.md).

## Durable execution

| Helper | Use it to |
| --- | --- |
| `ManualWallClock` | Control wall-clock time, including lease expiry, inside the process |
| `expire_leases(journal)` | Backdate live leases so recovery sees them as expired — the same thing as time passing with no heartbeat, and the only way to expire a lease *across* a process boundary |
| `idempotent_activity()` | Declare a step safe to run again, so recovery replays it instead of parking it |

Crash recovery is tested with a real subprocess that kills itself at a documented boundary
(`tests/crash_recovery/`), because a durable guarantee that is only simulated in-process is not
evidence. The pattern is worth copying: a child script that calls `os._exit(...)` at one boundary,
and a parent test that asserts what the journal contains afterwards. `os._exit` skips cleanup, so
only committed state survives — exactly the condition being tested. A child process does not inherit
pytest's import path, so the child adds the repository's `src` and `tests` directories itself.

## Warnings in the suite

Two warnings matter when you write tests for a subsystem that warns:

- **`ExperimentalWarning` is emitted once per process.** The durable package warns on first use, so a
  suite that runs several durable tests sees it once, and a suite configured with
  `-W error::UserWarning` fails on whichever test happens to be first. This repository filters it in
  `pyproject.toml` and asserts the emission explicitly in a subprocess, which tests the behavior
  instead of the side effect. Do the same rather than relying on ordering.
- **Deprecations are `DeprecationWarning`s.** They are silent by default, visible under `-W default`,
  and errors under `-W error`, which is what makes them usable in a `0.x` release. If you deprecate
  something, test the warning with `pytest.warns`.

## Habits worth keeping

- **Never wait on a real clock.** A `sleep` in a test is a slow machine's flake. Inject a clock and
  move it.
- **Never call a live provider in the default suite.** Gate it behind an environment variable and
  skip cleanly, so the suite is green on a machine with nothing installed.
- **Never share a module-level `App` between tests.** An `App` is one-shot: it cannot be restarted
  after `stop()`, and its locks are bound to the loop that started it. Build one per test.
- **Assert the composition, not only the behavior.** `app.diagnostics().render()` proves where each
  provider came from, which is how a test distinguishes a provider the application registered from
  one a plugin contributed.
- **Test a separately distributed plugin as a separate package.** The fixture at
  `tests/fixtures/metrics_plugin/` is an example, and `tests/integration/test_plugin_packages.py`
  asserts that it imports only public `xyberos` names — the check that catches a plugin depending on
  an internal module.
