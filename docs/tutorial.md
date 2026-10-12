# Xyberos tutorial

> **Status:** Phase 7, part-retired. This page is being moved to the documentation site chapter by
> chapter, because a page can only be checked where its code lives.
>
> **Two groups have moved.** The Fundamentals chapters — what Xyberos is, your first application,
> configuration, dependency injection, scopes, your first test, and the command line — are lessons under
> `site/learn/fundamentals/`. The HTTP and database chapters are lessons under `site/learn/traditional/`.
> Each is verified against the file it includes. The four chapters below keep their original numbers so
> existing links, anchors, and output markers stay valid; [the documentation site](../site/index.md)
> and its roadmap track the whole set.
>
> Each remaining chapter's code is a real file under `examples/tutorial/`, and every "Output" block on
> this page is produced by running that file — the suite checks each one
> (`tests/integration/test_tutorial.py`), so nothing here can quietly become wrong.

## What you will learn

| Chapter | Topic | You will run |
| --- | --- | --- |
| 1–4 | Your first application, services, scopes, and settings | **moved to the site** |
| 5–7 | HTTP, requests and errors, and SQLite | **moved to the site** |
| 8 | Writing your first test | **moved to the site** |
| [9](#chapter-9-adding-a-plugin) | Adding a plugin | `chapter9_plugins.py` |
| [10](#chapter-10-doing-several-things-in-order) | Doing several things in order | `chapter10_workflow.py` |
| [11](#chapter-11-asking-a-model-for-something) | Asking a model for something | `chapter11_ai.py` |
| [12](#chapter-12-surviving-a-crash) | Surviving a crash (experimental) | `chapter12_durable.py` |
| 13 | The command line | **moved to the site** |

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

## Exercises wrap-up

If you did the exercises, you have used: routes and path parameters, domain errors, transactions and
rollback, plugin contributions, workflow retries and branches, schema-validated model output, an
allowlisted tool call, and durable steps. The exercises for providers, scopes, configuration
precedence, test overrides, and the command line moved with their chapters to
[the documentation site](../site/index.md).

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
