---
title: Switch providers without touching the application
path: ai
lesson: 4
tier: built-in
status: verified
verify: output
example: examples/learn_ai/ai04_switch.py
prerequisites: ["/learn/ai/03-first-call"]
---

# Lesson 4 — switch providers without touching the application

## What you will build

Proof that the previous three lessons were not ceremony. One route, two providers, and a handler that
does not know which one answered — the reason to put a facade in front of a model at all.

## What you need

Nothing new.

<!-- snippet: examples/learn_ai/ai04_switch.py -->

The handler asks for `AIFacade` and nothing else. The provider is decided where the application is
composed, so switching from a local model to a hosted one is a change to one function, not to the code
that builds prompts.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_ai.ai04_switch
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_ai.ai04_switch
    ```

## What it prints

<!-- output: ai04_switch -->
```text
{'provider': 'provider-a', 'model': 'model-a', 'answer': 'Short answer.'}
{'provider': 'provider-b', 'model': 'model-b', 'answer': 'A longer answer, from a different provider.'}
```

Two lines with the same shape and different providers: `provider-a`/`model-a` and
`provider-b`/`model-b`. The answer text differs because the providers were scripted to differ, which is
the point of scripting them — a test asserts the *route*, not a model's prose.

## What the seam buys, and what it costs

| It buys | It costs |
| ------- | -------- |
| one place to change when a vendor changes | one abstraction to learn |
| a deterministic provider for tests and CI | capabilities that differ per provider must be declared (lesson 2) |
| a single place to attach logging, redaction, and usage accounting | a facade that is one layer between you and a vendor's newest feature |
| provider selection as configuration rather than as code | the temptation to hide model-specific prompts inside the facade |

The last row of that table is the honest cost. A facade earns its place when an application has more than
one reason to call a model; it stops earning it if it grows a prompt for every vendor quirk.

## Common mistakes

- **Naming a vendor in the application layer.** If a service imports `OllamaSettings`, the seam is
  decoration: the swap still requires editing the service.
- **Putting provider selection in the handler.** Reading an environment variable inside a route makes the
  choice untestable; compose the provider, then inject the facade.
- **Assuming behaviour is identical across providers.** The *contract* is identical; tokenisation,
  refusals, and tool support are not. That is what the capability declaration is for.
- **Hiding prompts in the facade.** A prompt is application policy. The facade sends messages it is
  given; it does not invent them.

## Next

Lesson 5 asks a model for a shape instead of a sentence, and shows what the runtime refuses to accept.
