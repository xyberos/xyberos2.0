---
title: The first call
path: ai
lesson: 3
tier: built-in
status: verified
verify: output
example: examples/learn_ai/ai03_first_call.py
prerequisites: ["/learn/ai/02-providers"]
---

# Lesson 3 — the first call

## What you will build

A question, a system prompt, and an answer you can read — plus the three facts that come back with every
response and that a real application needs: which model answered, how many tokens it cost, and how many
calls were made.

## What you need

Nothing new to run this lesson. To point the same code at a local model, install the adapter's extra:

=== "PowerShell"

    ```powershell
    python -m pip install "xyberos[ollama]"
    ```

=== "POSIX"

    ```bash
    python -m pip install 'xyberos[ollama]'
    ```

The lesson itself uses the deterministic provider, so the transcript below is the same on a laptop, in
CI, and in a container with no network.

<!-- snippet: examples/learn_ai/ai03_first_call.py -->

`Message.system(...)` and `Message.user(...)` are the two roles this request uses; a conversation is a
tuple of messages, and the facade does not keep it anywhere. Context is something the caller assembles,
which is lesson 7's subject.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_ai.ai03_first_call
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_ai.ai03_first_call
    ```

## What it prints

<!-- output: ai03_first_call -->
```text
profile: fake - pass 'ollama' to choose_provider to use a local model instead
reply:  Take an umbrella: rain is likely this afternoon.
model:  fake-model
tokens: 27 (in 18)
calls:  1
```

| Line | What it establishes |
| ---- | ------------------- |
| `reply:` | the model's text, as `response.message.content` |
| `model:` | which model answered — the field to log when a provider serves several |
| `tokens: 27 (in 18)` | usage as the provider reported it: the input/output split is what a cost estimate needs |
| `calls: 1` | one request, one provider call — the counter a test uses to prove caching or batching |

## Running against a real model

The provider is chosen in one place, so pointing this lesson at a local model is one branch rather than a
rewrite: `choose_provider` in the module above returns `OllamaProvider(OllamaSettings(model=...))` for
`profile="ollama"`, and imports that adapter only when it is asked for. It needs the `ollama` extra and an
already-pulled model, which is why the live walkthrough is an [appendix](../../appendices/index.md)
rather than a lesson: checked at command level and run by an opt-in workflow, not by every build.

## Common mistakes

- **Assuming the reply is JSON.** It is text unless a schema was requested (lesson 5); parsing it and
  hoping is how a prompt change becomes an outage.
- **Ignoring usage.** A call whose cost nobody records is a bill nobody can explain; the fields exist on
  every response for that reason.
- **Building the conversation in the module.** Messages belong to the request, and the caller owns their
  lifecycle — a global list of messages is a shared-state bug in waiting.
- **Putting secrets in the request.** A prompt sent to a provider leaves your process; the logging policy
  (lesson 17) governs what is recorded, not what is sent.
- **Retrying a refusal.** Lesson 6 draws the line, and a refusal is on the wrong side of it.

## Next

Lesson 4 shows why the seam matters: the same route, two providers, and no change to the handler.
