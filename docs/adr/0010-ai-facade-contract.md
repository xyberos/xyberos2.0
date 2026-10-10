# ADR 0010: Freeze the AI facade contract

**Status:** accepted

## Context

Phase 5 adds model capabilities without letting a provider shape the runtime or the workflow engine.
The facade has to be usable and testable with no SDK, no service, and no model; it has to classify
failures well enough for a retry policy to decide; and it has to keep prompts, completions, and
credentials out of logs by default. The plan also fixed Ollama as the first adapter, with the model
as required configuration and no automatic model downloads.

## Decision

**The facade, the contracts, the tool contract, the schema subset, and the fake provider ship in the
core package and need no third-party dependency.** `xyberos.ai` is therefore importable, and fully
testable, in a core-only installation. Adapters are separate modules behind their own extras:
`xyberos.ai.ollama` requires the `ollama` extra and is never imported by `xyberos.ai`, so importing
the package never imports an SDK. The runtime never imports `xyberos.ai` at all.

**The runtime owns the AI configuration *shape*, not any AI concept.** `Settings` accepts an `ai`
table of named provider sections and exposes `ai_options(name)` with the same precedence,
lowercasing, and environment mapping (`XYBEROS_AI__OLLAMA__MODEL`) as plugin sections. Its contents
stay opaque to the core package; `OllamaSettings.from_mapping` is what interprets them, and it
rejects unknown keys.

**Requests are provider-neutral by construction.** A request describes messages, a model, a budget,
an optional response schema, and optional tools. Provider-specific knobs are *not* settable per
request: they live in adapter settings, and a reserved-key check stops an option from rewriting
`model`, `messages`, `tools`, `format`, or `stream` behind the adapter's back.

**Capabilities are declared, never inferred.** `ModelCapabilities` is conservative by default, the
facade refuses a request the model does not claim to support *before* any call, and an adapter
enforces its own claims too. Allowing a request field is not evidence a model honours it. The Ollama
adapter additionally cross-checks a declared `tools` claim against the capabilities the model itself
reports through the readiness check, because that is the one claim the API exposes.

**Structured output is validated by a closed JSON Schema subset.** Supported keywords are explicit,
and an unsupported keyword is rejected when the schema is *declared* rather than ignored at
validation time, so a schema can never validate more loosely than it reads. The subset is small
enough to implement without a schema library, which keeps the framework dependency-free, and it is
exactly what the Ollama adapter can forward as `format`.

**Failure classification is the retry interface.** `AITransportError` (and its `AITimeoutError` and
`AIRateLimitError` subclasses) derive from `TransientError`, so a workflow step's default
`Retry(max_attempts=...)` already retries them; `AISchemaError`, `AIRefusalError`, and `AIRequestError`
deliberately do not, so retrying a contract violation stays an explicit decision. The facade itself
never retries. A response envelope that is not the documented shape is a transport failure, while a
well-formed payload that fails the requested schema is a schema failure: they are separate classes
because a retry policy should treat them differently.

**A refusal is only reported when the provider reports one.** `FinishReason.REFUSAL` is never
inferred from response text; classifying prose is out of scope and would be a guess presented as a
fact. Ollama reports no refusal signal, which the guide states plainly.

**Tools are allowlisted, validated, and audited.** The tool set *is* the allowlist, a call outside it
raises, arguments are validated against the declared schema, and a handler receives only its
arguments and a context, never a service container. Invalid arguments and handler failures come back
as failed results rather than exceptions, so an agent loop can hand them to the model; only a
policy violation raises. Audit events record the argument *names*, the outcome, and the timing, and
never argument values or failure messages.

**Budgets come from the runtime context.** A request honours its own `timeout` and the absolute
deadline already bound to the context, whichever is sooner, so an AI call inside a workflow step
inherits that step's remaining budget with no extra wiring.

**Logging is metadata-only unless a caller opts in.** The default records provider, model, counts,
timings, and usage. Content capture is an explicit policy that truncates and applies literal
redaction, and a base URL that embeds credentials is rejected outright because it would reach logs
and error messages.

## Consequences

- Phase 6 can persist AI usage metadata, but no durable state may depend on prompt content; the
  default redaction and the metadata-only event shape are the contract it inherits.
- Knowledge/retrieval stays deferred until it has its own storage, chunking, filtering,
  authorization, and evaluation contracts, as the phase plan requires.
- The schema subset is closed: `oneOf`, `$ref`, and `pattern` are unsupported and rejected, so a
  user who needs them must extend the subset through a new ADR rather than pass a schema that would
  silently validate less than it claims.
- Embeddings are configured separately from the chat model (`embedding_model`), because one Ollama
  model does not serve both; an adapter that can serve both is free to default it.
- Streaming carries content only: tools and response schemas are rejected on a streaming request
  because a partially validated structured payload is not actionable. Streaming tool calls would
  need a new ADR.
- Tool declarations are written as explicit schemas; deriving them from type annotations is in the
  deferred backlog rather than part of the frozen contract.
- The Ollama request and response shapes are asserted with `httpx.MockTransport`, so a service is
  never required for CI; live verification is opt-in and operator-supplied, and the owner still owns
  the supported Ollama release range and the model names used in smoke tests.
