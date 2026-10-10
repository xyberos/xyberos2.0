# ADR 0004: Use Ollama as the first AI provider

**Status:** accepted

## Decision

The first AI adapter will target Ollama through its HTTP API and will be installed only by
the `xyberos[ollama]` extra. The core package neither imports the adapter nor starts,
stops, downloads, or upgrades models.

The adapter will normalize chat, streaming, embeddings, structured output, tool-call
payloads, timeouts, cancellation, and errors behind provider-neutral contracts. Model
capabilities remain runtime-validated because not every model supports every Ollama API
feature.

## Consequences

- Unit tests can use an HTTP mock or fake provider without a local Ollama daemon. *Satisfied in
  Phase 5: `xyberos.ai.testing.FakeModelProvider` and `httpx.MockTransport` cover the adapter; the
  suite runs with no service, and live checks are opt-in.*
- Examples may name a model but production applications must configure one explicitly. *Satisfied in
  Phase 5: `OllamaSettings.model` is required and unknown keys are rejected, so the adapter has no
  default; only `examples/ai_assistant` ships a default model name for convenience.*
- Prompts, completions, and credentials are excluded from logs by default. *Satisfied in Phase 5:
  `LoggingPolicy.metadata_only()` is the default, content capture is opt-in with truncation and
  redaction, and a credential-bearing base URL is rejected; Phase 7 re-audits redaction.*
