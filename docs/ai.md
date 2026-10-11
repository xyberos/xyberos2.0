# AI guide

> Status: Phase 5. The facade, the contracts, the tool contract, the schema subset, and the fake
> provider are preview API in the core package. The Ollama adapter is preview API behind the
> `ollama` extra.

## What ships where

| Piece | Where | Needs |
| --- | --- | --- |
| `AIFacade`, contracts, tools, schema subset, `FakeModelProvider` | `xyberos.ai` (core) | nothing beyond core |
| Ollama adapter | `xyberos.ai.ollama` | `xyberos[ollama]` (`httpx`) |

The runtime never imports `xyberos.ai`, and `xyberos.ai` never imports an adapter, so `import
xyberos` and `import xyberos.ai` both work with no AI SDK installed. Importing the adapter without
its extra fails with the command that fixes it, not a bare `ModuleNotFoundError`:

```text
ModuleNotFoundError: the 'ollama' extra cannot be imported: install it with 'pip install "xyberos[ollama]"' (No module named 'httpx')
```

## Supported Ollama releases and models

**Supported: Ollama 0.5.0 or newer.** The floor is set by the newest feature the adapter depends on,
not by the oldest one it can reach:

| What the adapter uses | First available in |
| --- | --- |
| `/api/chat`, `/api/version` | 0.1.14 |
| `done_reason` | 0.1.35 |
| `/api/embed` (batch embeddings) | 0.2.6 |
| Tool calling (`tools`, `tool_calls`) | 0.3.0 |
| **JSON-schema `format` (structured output)** | **0.5.0** |

A floor that is only documented is not a floor, so the adapter enforces it. A health check compares
the service's reported release and reports `unhealthy` with the reason; once the version is known, a
later `chat`, `stream`, or `embed` call is refused with `AIConfigurationError` instead of failing
confusingly inside Ollama. A service the adapter has not measured is never refused, and a version it
cannot compare — a pre-release such as `0.5.9-rc2`, or a development build reporting `dev` — is
treated as unknown rather than as too old, because refusing work you cannot measure is worse than
the risk it guards. To run deliberately below the floor, set `minimum_version` (`[ai.ollama]
minimum_version = "0.4.0"`) and accept that Xyberos does not test against it.

**Models are yours to choose.** The adapter has no default model: production configuration must name
one, and Xyberos never pulls, starts, stops, or upgrades a model or a service. A missing model is a
configuration error that names the fix (`ollama pull <model>`), and capabilities are claims you
declare rather than something the framework infers.

For local smoke runs the opt-in live tests default to `llama3.2:3b` (about 1.9 GB), which is small
enough for a laptop and genuinely reports tool support. `llama3.2:1b` (about 1.3 GB) also reports
tool support and is the minimal alternative, though it is noticeably less reliable at tool calling,
which makes the tool test flaky rather than fast. Embeddings are configured separately
(`embedding_model`, for example `nomic-embed-text` at 768 dimensions) because one Ollama model does
not serve both, and the embedding smoke test has no default at all.

Tool-specific live tests have their own gate (`XYBEROS_OLLAMA_LIVE_TOOLS=1`) so that pointing the
suite at a model without tool support skips them rather than failing a suite that is otherwise fine.

## Using a model provider

A provider is an ordinary service, so it is registered the same way as anything else:

```python
from typing import Annotated

from xyberos import App, Inject, Scope
from xyberos.ai import AIFacade, ChatRequest, Message
from xyberos.ai.ollama import OllamaSettings, ollama_provider

provider_factory = ollama_provider(OllamaSettings(model="llama3.2"))


async def assistant_factory() -> AIFacade:
    return AIFacade(await provider_factory())


async def ask(assistant: Annotated[AIFacade, Inject()]) -> str:
    response = await assistant.chat(ChatRequest(messages=(Message.user("Hello"),)))
    return response.message.content


app = App()
app.provide(AIFacade, factory=assistant_factory, eager=True, scope=Scope.APP)
```

`ollama_provider(settings)` returns a factory suitable for `App.provide(..., eager=True)`, and the
facade closes the provider it wraps when the application shuts down, so a connection pool is
released with the rest of the application. Register with `eager=True` if you want that release to be
deterministic: the application closes the providers it *resolved*, so a lazily resolved facade is
released only if a call actually went through it. A client you pass in is never closed by the
adapter, which is how tests drive it with `httpx.MockTransport`.

AI calls use direct execution by default. Wrap them in a workflow when the work is multi-step,
needs bounded retries, or should be observable — the [workflow guide](workflow.md) covers that, and
the `triage` route in `examples/ai_assistant` shows a model call inside a step whose retry policy
already covers transient AI failures.

## Capabilities are declared, not inferred

An API accepting a request field does not mean a model honours it, so a capability is a claim:

```python
from xyberos.ai import ModelCapabilities

capabilities = ModelCapabilities(tools=False, structured_output=False, streaming=True, embeddings=False)
```

The defaults are conservative. The facade refuses a request that needs an undeclared capability
*before* any call is made, and the adapter refuses it too, so a misconfiguration fails fast with an
actionable `AIUnsupportedCapabilityError` naming the capability. The Ollama adapter also cross-checks
a declared `tools` claim against what the model itself reports during the readiness check, because
that is the one claim the API exposes; `structured_output` has no reported capability and is
therefore only validated at runtime, by validating the response.

## Structured output

Ask for a schema and the facade parses and validates the response before you see it:

```python
from xyberos.ai import ChatRequest, Message, validate_payload

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["answer", "confidence"],
    "additionalProperties": False,
}

response = await assistant.chat(
    ChatRequest(messages=(Message.user("Will it rain?"),), response_schema=ANSWER_SCHEMA)
)
payload = response.structured  # the validated object; response.message.content keeps the raw text
```

Supported keywords: `type`, `properties`, `required`, `additionalProperties`, `items`, `enum`,
`minimum`, `maximum`, `minLength`, `maxLength`, `minItems`, `maxItems`, plus the documentation-only
`description`, `title`, `default`, `examples`, and `format`. Supported types: `object`, `array`,
`string`, `number`, `integer`, `boolean`, `null`.

The subset is deliberately **closed**: an unsupported keyword such as `oneOf` is rejected when the
schema is declared, rather than ignored at validation time. A closed subset means a schema can never
validate more loosely than it reads. Validation failures name the first failing location:

```text
the model response at $.confidence must be one of: 'low', 'medium', 'high'; got 'certain'
```

## Tools

A tool is a declaration plus a handler, and the tool set *is* the allowlist:

```python
from collections.abc import Mapping

from xyberos.ai import Tool, ToolCall, ToolSet, ToolSpec

WEATHER_SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
    "additionalProperties": False,
}


async def look_up(arguments: Mapping[str, object], context) -> dict[str, object]:
    return {"city": arguments["city"], "celsius": 11}


tools = ToolSet.of(
    Tool(spec=ToolSpec(name="weather", description="Look up weather", parameters=WEATHER_SCHEMA),
         handler=look_up)
)

response = await assistant.chat_with_tools(request, tools=tools, max_rounds=3)
```

What the framework guarantees:

- **Nothing a model returns is executed directly.** A call is resolved against the allowlist,
  validated against the declared schema, and only then run. A call outside the allowlist raises
  `AIToolError` naming the allowed tools; an empty tool set means no tool can run.
- **A handler receives its validated arguments and a context, never a service container.** A tool can
  only reach dependencies its author closed over, so adding a tool cannot expose the application.
- **Invalid arguments and handler failures are results, not exceptions**, so an agent loop can hand
  them back to the model: `result.ok`, `result.error_type`, `result.error`, and `result.render()`
  for JSON text to send back. Only a policy violation raises.
- **Audit events record names, not values.** `ToolEvent` reports the tool, the argument *names*, the
  outcome, the duration, and the correlation ID:

  ```text
  #1 requested tool=knowledge arguments=topic
  #2 succeeded tool=knowledge arguments=topic duration=0.000000
  ```

- **The loop is bounded.** `chat_with_tools(..., max_rounds=3)` stops with `AIToolError` rather than
  looping forever. Longer orchestration belongs in a workflow, where each round is a step with its
  own policy.

A tool stores only ordinary data: a `Mapping[str, object]` that has to be JSON-serializable, which
keeps a declaration portable across providers.

## Failure classification

Classification is the retry interface. A workflow step's default `Retry(max_attempts=3)` retries
everything that derives from `TransientError`, and nothing else:

| Error | Raised for | Retried by default |
| --- | --- | --- |
| `AITransportError` | the service is unreachable, or its response envelope is not the documented shape | **yes** |
| `AITimeoutError` | the request budget ran out, or the provider reported a timeout | **yes** |
| `AIRateLimitError` | the provider asked the client to slow down | **yes** |
| `AISchemaError` | a well-formed payload did not validate against the declared schema | no |
| `AIRefusalError` | the provider reported a refusal | no |
| `AIRequestError` | the request cannot be sent as built, or the provider rejected it | no |
| `AIUnsupportedCapabilityError` | the model does not claim what the request needs | no |
| `AIConfigurationError` | configuration is missing or unusable | no |
| `AIToolError` | a tool call is unknown, not allowed, invalid, or over the loop limit | no |

Two distinctions matter. A malformed response *envelope* is a service fault and therefore transient;
a well-formed payload that fails the schema is a contract problem, so retrying it — which is often
worth doing with a stochastic model — is a deliberate `retry_on=(AISchemaError,)`. And a provider
timeout is retryable, unlike a workflow step timeout, because it reports a slow *service* rather than
the engine's verdict on a stuck step.

The facade itself never retries, so retry behavior stays in one place: the caller's policy.

## Timeouts, deadlines, and cancellation

- `ChatRequest(timeout=...)` bounds one call. The facade also honours the absolute deadline already
  bound to the runtime context, so a model call inside a workflow step inherits that step's remaining
  budget without extra wiring — whichever limit is sooner wins.
- The Ollama adapter additionally configures connect and overall HTTP timeouts on its client.
- Cancelling the calling task cancels the provider call: the facade awaits the provider in the
  caller's task, so `asyncio.CancelledError` propagates and a cooperative provider observes it.
- Streaming enforces the same budget between chunks, so a stalled stream cannot hang a request.

## Security and operations policy

- **Credentials never reach logs.** The facade logs metadata only. An Ollama `base_url` that embeds
  credentials is rejected outright, because it would end up in logs and error messages.
- **Metadata-only logging is the default.** The `xyberos.ai` logger records provider, model, outcome,
  message and tool counts, durations, and token usage:

  ```text
  xyberos.ai DEBUG ai chat provider=fake model=fake-model outcome=ok messages=2 tools=1 schema=False tool_calls=1 duration=0.000000 input_tokens=14 output_tokens=5
  ```

- **Prompt and completion capture is an explicit, redacted opt-in.** `LoggingPolicy.capturing(...)`
  truncates to `max_content_length` and applies literal `redact` secrets before logging:

  ```text
  ai prompt role=user content=token [redacted] rain?
  ```

- **Tool permissions are the allowlist.** A model can only run tools the caller put in the set, and a
  handler gets no container, so tool access is auditable at the call site. Never register a tool
  whose side effects you are not prepared to run on model output.
- **Model output is untrusted input.** Validate structured output against a schema, validate tool
  arguments, and treat text destined for a shell, a query, or a template as data to escape.
- **Provider data handling is your decision.** Ollama is local by default, but any provider sees the
  prompts you send it. Do not send data your deployment policy does not allow.
- **Retention, stated precisely.** The framework persists no AI content anywhere: not in logs, not in
  events, and not in the durable journal by construction. AI *usage metadata* (provider, model,
  counts, timings) is the only thing that may be retained, and it is retained only for as long as the
  execution that produced it — deleting a terminal execution deletes its records
  ([journal retention](durable.md#growth-and-retention)). Log retention belongs to your logging
  stack. Nothing here needs your own policy to be written down first, which is why the default is the
  conservative one.
- **The one place prompt text can land in the journal.** A durable step's *output* is persisted
  verbatim, so a step that returns a model completion stores that completion. Redaction is therefore
  the step's job: filter the payload before returning it. This is the only intersection of the two
  policies, and it is worth knowing before you persist a step that returns raw model output.
- **Xyberos never downloads models.** The adapter calls documented endpoints only: it does not pull,
  start, stop, or upgrade a model, and a missing model fails with an actionable error. The model is
  required configuration in production; `llama3.2:3b` appears only in the opt-in smoke tests, and
  `examples/ai_assistant` names a model for convenience rather than as a recommendation. Running the
  service — container, port, GPU, image, and any model distribution policy — is entirely the
  operator's.

## The Ollama adapter

```python
from xyberos.ai.ollama import OllamaProvider, OllamaSettings

settings = OllamaSettings(
    model="llama3.2",                 # required: Xyberos never picks a model
    base_url="http://127.0.0.1:11434",
    embedding_model="nomic-embed-text",
    timeout=60.0,
    connect_timeout=5.0,
    tools=True,
    structured_output=True,
    streaming=True,
    options={"num_ctx": 4096},
)
provider = OllamaProvider(settings)
```

| Setting | Default | Notes |
| --- | --- | --- |
| `model` | — | **required**; chat and tool calls use it |
| `base_url` | `http://127.0.0.1:11434` | http(s) only, no credentials, a trailing `/` is stripped |
| `embedding_model` | `None` | needed for `embed()`; embeddings use their own model |
| `timeout` | `60.0` | overall HTTP timeout |
| `connect_timeout` | `5.0` | connection timeout |
| `tools` | `False` | a declared capability |
| `structured_output` | `False` | a declared capability |
| `streaming` | `True` | a declared capability |
| `options` | `{}` | passed through as Ollama options; reserved keys are rejected |

The same settings come from configuration, with the usual precedence and environment mapping:

```toml
# xyberos.toml
[ai.ollama]
model = "llama3.2"
base_url = "http://127.0.0.1:11434"
embedding_model = "nomic-embed-text"
tools = true
structured_output = true

[ai.ollama.options]
num_ctx = 4096
```

```powershell
$env:XYBEROS_AI__OLLAMA__MODEL = "llama3.2"
```

```python
from xyberos import Settings
from xyberos.ai.ollama import OllamaSettings

settings = OllamaSettings.from_mapping(Settings.load().ai_options("ollama"))
```

Endpoints used: `POST /api/chat` (streaming and non-streaming), `POST /api/embed`,
`POST /api/show`, and `GET /api/version`. Ollama request and response shapes are asserted with
`httpx.MockTransport`, so CI never needs a service.

`health()` reports readiness instead of raising, distinguishing an unreachable service
(`UNREACHABLE`), an unavailable model (`MODEL_UNAVAILABLE`), a service that answers but cannot be
used (`UNHEALTHY`, including a capability mismatch), and a usable model (`READY`).

## Testing

`FakeModelProvider` implements the whole provider contract deterministically, and `ModelReply`
scripts every scenario the facade must survive:

```python
from xyberos.ai import AIFacade, ChatRequest, FakeModelProvider, Message, ModelReply, Usage

provider = FakeModelProvider(
    [
        ModelReply.rate_limited(),                        # a retryable transport failure
        ModelReply.json_payload({"answer": "Take one"}, usage=Usage(11, 4)),
    ]
)
response = await AIFacade(provider).chat(
    ChatRequest(messages=(Message.user("?"),), response_schema=ANSWER_SCHEMA)
)

assert provider.calls == 2
assert response.structured == {"answer": "Take one"}
```

Available replies: `ok`, `json_payload`, `wrong_shape`, `malformed`, `refusal`, `tools`, `failing`,
`rate_limited`, `transient`, `timeout`, and `slow`. Replies play in order and the last one repeats.
The fake enforces declared capabilities exactly as a real adapter must, so a test cannot rely on a
request a real model would refuse.

Live Ollama verification is opt-in and never part of normal CI:

```powershell
ollama pull llama3.2
$env:XYBEROS_OLLAMA_LIVE = "1"
$env:XYBEROS_OLLAMA_LIVE_MODEL = "llama3.2"
python -m pytest tests/ai/test_live_ollama.py
```

## Deliberate limitations

- **No knowledge/retrieval subsystem.** It needs its own storage, chunking, filtering,
  authorization, and evaluation contracts before it can be useful or safe.
- **No vendor SDK.** Adapters speak documented HTTP through an internal client, so no provider
  library becomes part of the framework contract.
- **No schema generation from type annotations.** Tool arguments and response schemas are written out
  explicitly, which keeps the model-visible contract readable.
- **Streaming carries content only.** Tools and response schemas are rejected on a streaming request.
- **Text only.** Multimodal content parts are out of scope.
- **Refusals are only reported when a provider reports one.** Classifying prose is a guess, so
  Xyberos does not do it.
