---
title: What a provider declares
path: ai
lesson: 2
tier: built-in
status: verified
verify: output
example: examples/learn_ai/ai02_providers.py
prerequisites: ["/learn/ai/01-ready"]
---

# Lesson 2 — what a provider declares

## What you will build

The difference between "this provider can do structured output" and "this call asked for structured
output": a declaration on the provider, and a facade that refuses a request the provider never claimed it
could serve. It is the cheapest correctness check in the AI stack, and it happens before a token is spent.

## What you need

Nothing new.

<!-- snippet: examples/learn_ai/ai02_providers.py -->

The provider's `capabilities` are not documentation: the facade reads them on every call. Asking a
provider without `structured_output` for a response schema fails immediately, with the reason, instead of
returning a string that the caller then tries to parse as JSON.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_ai.ai02_providers
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_ai.ai02_providers
    ```

## What it prints

<!-- output: ai02_providers -->
```text
declares it: fake fake-model
declares it capabilities: ModelCapabilities(tools=False, structured_output=True, streaming=True, embeddings=False)
declares it answered
does not: fake fake-model
does not capabilities: ModelCapabilities(tools=False, structured_output=False, streaming=True, embeddings=False)
does not refused: the request asks for a response schema but this model does not claim structured output support; declare the capability on the provider before relying on it
```

| Line | What it establishes |
| ---- | ------------------- |
| `declares it capabilities: ModelCapabilities(...)` | what the provider claims, in one object |
| `declares it answered` | a claim that matches the request is served |
| `does not refused: the request asks for a response schema ...` | the mismatch is refused by the facade, not discovered later by the caller |

The four declared capabilities are the ones the facade can act on: `structured_output`, `tools`,
`streaming`, and `embeddings`. A provider that declares none of them is still a provider — it is a
provider you can call for chat and nothing else.

## Common mistakes

- **Declaring a capability you have not implemented.** The declaration is a promise the facade trusts; a
  provider that lies turns a clear refusal into a confusing downstream failure.
- **Skipping the declaration on a real adapter.** A model that supports tools but is configured without
  `tools=True` will refuse tool calls, and the exception will look like a facade bug rather than a
  configuration one.
- **Assuming every model has the same capabilities.** Two models behind the same vendor differ; a
  capability belongs to the provider you configured, which is why the facade asks the provider instead
  of a table it keeps.
- **Treating `streaming` as free.** A streamed answer cannot also ask for a schema or offer tools — the
  facade says so rather than dropping one of the two silently.

## Next

Lesson 3 makes the first real call: a chat request, a chat response, and the metadata that comes back
with it.
