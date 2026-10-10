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

- Unit tests can use an HTTP mock or fake provider without a local Ollama daemon.
- Examples may name a model but production applications must configure one explicitly.
- Prompts, completions, and credentials are excluded from logs by default.
