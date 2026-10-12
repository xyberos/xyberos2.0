---
title: Bounded agent behaviour
path: ai
lesson: 14
tier: not-provided
status: verified
verify: output
example: examples/learn_ai/ai14_agent.py
prerequisites: ["/learn/ai/11-tools", "/learn/ai/13-workflows"]
---

# Lesson 14 — bounded agent behaviour

## What you will build

The thing this path has been walking towards, stated plainly: a loop that calls a model, lets it ask for
tools, and stops. **There is no agent loop in the runtime.** What exists is `chat_with_tools` — a bounded
tool loop with a round limit — and the workflow engine, which supplies the deadline and the escalation
path. An agent here is those two things composed, plus a budget someone chose.

## What you need

Nothing new.

<!-- snippet: examples/learn_ai/ai14_agent.py -->

`Budget` is a dataclass with two numbers, and it is the most important object on this page: a round limit
and a deadline. Every agent story that goes wrong goes wrong by removing one of them.

The step's error handling is the second decision: an `AIError` — a round limit, a refusal, a timeout, a
provider that is down — becomes an **escalation**, not a retry and not an invented answer.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_ai.ai14_agent
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_ai.ai14_agent
    ```

## What it prints

<!-- output: ai14_agent -->
```text
asked once:    T-100 is 'printer is on fire'.
asked forever: escalated: AIToolError
refused:       escalated: AIRefusalError
the loop is chat_with_tools, bounded by max_rounds; the runtime has no agent loop
```

Three runs, three answers, and two of them are escalations for *different* reasons:

| Run | Outcome | Why escalating is right |
| --- | ------- | ---------------------- |
| answers with a tool | `T-100 is 'printer is on fire'.` | the loop finished inside its budget |
| asks forever | `escalated: AIToolError` | the model kept asking; the round limit is what stopped it |
| refuses | `escalated: AIRefusalError` | the model declined; retrying would cost tokens and refuse again |

The last line printed is the honest description of the architecture: the loop lives in
`chat_with_tools`, the budget lives in your code, and the sequencing lives in a workflow. Nothing in the
runtime decides for you how long an agent may think.

## Common mistakes

- **Removing the round limit because it was inconvenient.** The limit is the difference between an agent
  and a runaway loop that bills by the minute.
- **Letting the agent decide when to escalate.** Escalation is a policy: an error class, a confidence, a
  budget — decided by the application, and testable without a model.
- **Giving the loop a write tool.** With tools, the model's output becomes actions; every action needs an
  approval boundary, which is the hybrid path's whole subject.
- **Treating the model's summary as the record.** The tool events and the step outcomes are the record;
  the answer is what the user was told.
- **An unbounded conversation as "context".** A tool loop plus an unbounded window is the most expensive
  request in the system; bound both, and say what the bound costs.

## Next

Lesson 15 turns everything so far into tests that run with no model service — which is how this path
itself is verified.
