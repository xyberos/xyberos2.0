---
title: An application that is AI-ready
path: ai
lesson: 1
tier: built-in
status: verified
verify: output
example: examples/learn_ai/ai01_ready.py
prerequisites: ["/learn/fundamentals/04-your-first-application"]
---

# Lesson 1 — an application that is AI-ready

## What you will build

An application that works, and that has a place for a model without depending on one. That is the whole
lesson: the model is not on the critical path of a support desk, and an application that cannot start
without it is an application whose outage is a model's outage.

`xyberos.ai` is **preview** tier ([stability guide](../../reference/stability.md)): the facade's shape is
settled, and its surface may still move in a minor release.

## What you need

Nothing beyond the core package. The determinism here is not a trick for the lesson — the repository
ships a provider built for exactly this, and the AI path never needs a model service to run:

<!-- snippet: examples/learn_ai/ai01_ready.py -->

Three things in that module are the lesson:

- **`TicketDesk` knows nothing about a model.** It is a service with a method, exactly like the ones in
  the traditional path.
- **The facade is registered behind a contract.** `app.provide(AIFacade, instance=...)` means a route can
  ask for it, and a test can replace it. The provider is a constructor argument of the *composition*,
  not a global.
- **Nothing calls the model.** The route that reports the assistant's status asks the facade for
  `health()`, which is metadata: provider name, model, status. No prompt leaves the process.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_ai.ai01_ready
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_ai.ai01_ready
    ```

## What it prints

<!-- output: ai01_ready -->
```text
tickets:   ['printer is on fire', 'badge reader is broken']
assistant: {'provider': 'fake', 'model': 'fake-model', 'status': 'ready', 'detail': ''}
model calls: 0
```

## What the numbers say

| Line | What it establishes |
| ---- | ------------------- |
| `tickets: [...]` | the application's own work, served with no model involved |
| `assistant: {'provider': 'fake', ...}` | the facade is reachable, and reports what it is connected to |
| `model calls: 0` | and this lesson made none: the seam exists before it is used |

`FakeModelProvider([], capabilities=ModelCapabilities())` is a provider with an empty script and no
declared capabilities. It is a *working* provider — that is why `health()` answers — and it fails loudly
if something asks it for a call it was not scripted for, which is the property a test wants.

## Common mistakes

- **Reaching for a model before the application works.** The first version of a feature is code that
  does not need one; the model is added to a seam that already exists.
- **Constructing a provider inside a service.** A service that builds its own provider cannot be tested
  without one, which is the coupling this lesson's composition avoids.
- **Reading the API key or base URL at import time.** Configuration belongs at composition, so a test
  composes a different provider without touching the process environment.
- **Treating the fake provider as a mock.** It implements the full provider contract and records what it
  was asked, so a test asserts behaviour rather than call counts on a stub.

## Next

Lesson 2 looks at what a provider *declares*, because the facade checks those declarations before it
makes a call rather than discovering the mismatch in production.
