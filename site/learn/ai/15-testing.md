---
title: Testing the AI path
path: ai
lesson: 15
tier: built-in
status: verified
verify: output
example: examples/learn_ai/ai15_testing.py
prerequisites: ["/learn/ai/14-agent"]
---

# Lesson 15 — testing the AI path

## What you will build

Tests for code that calls a model, running with no model service, no network, and no API key. Not because
a service is inconvenient, but because a test that needs one is a test that fails for reasons that have
nothing to do with the code: a pulled model, a weekend, a rate limit.

Every lesson in this path is verified this way, including this one.

## What you need

Nothing new: `FakeModelProvider` ships with the core package.

<!-- snippet: examples/learn_ai/ai15_testing.py -->

Four checks, and each one asserts something a live model cannot offer deterministically:

| Check | What it pins down |
| ----- | ----------------- |
| the prompt | the exact messages the provider received — a prompt is a contract, and the assertion is the review |
| a transient failure | `calls == 2`: the retry happened, inside the step, without the test sleeping |
| a capability refusal | `calls == 0`: the refusal happened *before* the call, so no tokens were spent |
| tool events | `requested` then `succeeded`, with argument *keys* and no values |

The scripted provider is not a mock of the facade: it implements the provider contract, enforces
capabilities, records requests, and answers from a list. That is why `provider.requests[0]` is worth
asserting against — it is what a real provider would have received.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_ai.ai15_testing
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_ai.ai15_testing
    ```

## What it prints

<!-- output: ai15_testing -->
```text
ok - check_the_prompt_is_what_you_wrote - the provider received 2 messages, system first
ok - check_a_transient_failure_is_retried - succeeded on attempt 2 with 2 calls
ok - check_capabilities_are_enforced - refused before any call: AIUnsupportedCapabilityError
ok - check_tool_calls_are_observable - events observed: ['requested', 'succeeded']
4 checks passed with no model service
```

## What to test, and what not to

| Test | Because |
| ---- | ------- |
| The prompt you send | it is your code, and it changes most often |
| The schema and the refusal paths | they are boundaries the application depends on |
| Retries, limits, and deadlines | they are budgets, and budgets regress silently |
| Tool allowlists and argument validation | they are permissions |
| A live model's prose | it is not your code, and it will change without you |

The last row is the honest boundary. A test that asserts a sentence a model wrote is a test that fails on
a provider's Tuesday. Assert your code, script the model, and measure the model's *quality* separately —
which is lesson 16.

## Common mistakes

- **Mocking the facade instead of the provider.** The facade is the layer under test; replacing it tests
  nothing about how your code uses it.
- **Forgetting `provider.reset()`.** One fake serving several scenarios keeps its counters and its
  recorded requests; reset between them or read the wrong call.
- **Asserting on text a model would produce.** Script the reply you need, then assert what your code did
  with it.
- **Leaving the live test in the default suite.** A test that needs `XYBEROS_OLLAMA_LIVE` belongs behind
  an opt-in flag, like this repository's own live tests and its [appendices](../../appendices/index.md).
- **No assertion on the prompt.** Prompt drift is the most common AI regression and the cheapest to
  catch.

## Next

Lesson 16 measures what the tests cannot: whether the model's answers are any *good*.
