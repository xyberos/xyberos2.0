---
title: Tools
path: ai
lesson: 11
tier: built-in
status: verified
verify: output
example: examples/learn_ai/ai11_tools.py
prerequisites: ["/learn/ai/05-structured"]
---

# Lesson 11 — tools

## What you will build

A way for the model to ask the application to *do* something, with three boundaries around it: an
allowlist that decides what exists, a schema that decides what arguments are acceptable, and a round
limit that decides how long the conversation may go on. The model never runs code; it asks, and the
application decides.

## What you need

Nothing new.

<!-- snippet: examples/learn_ai/ai11_tools.py -->

Both tools are **read-only**. That is not a coincidence: a tool that writes is a tool the model can use to
change the world, and lesson 17's rule — a model may recommend, application code decides — starts with
which tools exist at all.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_ai.ai11_tools
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_ai.ai11_tools
    ```

## What it prints

<!-- output: ai11_tools -->
```text
allowed: ('lookup_ticket', 'count_tickets')
declared: ['lookup_ticket', 'count_tickets']
answer:   Ticket T-100 is 'printer is on fire'. (rounds: 2)
  event: requested lookup_ticket ('ticket',)
  event: succeeded lookup_ticket ('ticket',)
not allowed: the model asked for tool 'refund_customer', which is not allowed for this call; allowed tools: lookup_ticket, count_tickets
bad args:    False AISchemaError arguments of tool 'lookup_ticket' at $ is missing the required property 'ticket'
round limit: AIToolError the model asked for 'count_tickets' after 2 round(s), which is the configured limit; raise max_rounds or move the orchestration into a workflow
```

The last three lines are three different refusals, and the difference between them is the lesson:

| Refusal | What happens | Why |
| ------- | ------------ | --- |
| A tool that is not in the allowlist | `AIToolError` is **raised**, naming what is allowed | the request is not serviceable at all, and the caller should not have to guess |
| Arguments that do not match the schema | a **failed `ToolResult`** is returned, and the loop feeds the error back to the model | the model can correct itself, and one bad call should not end the conversation |
| More rounds than `max_rounds` | `AIToolError` is raised | the limit is a budget, not a suggestion: an unbounded tool loop is a denial-of-service you wrote |

The `ToolEvent` lines are the audit trail: `requested` then `succeeded`, with the argument *keys* and no
values. That is what a log should contain by default — enough to see what happened, nothing that leaks
what a customer typed.

## Common mistakes

- **Building the tool from the model's arguments.** Arguments are schema-checked input, not a command:
  resolve the ticket id, look it up, and let the handler refuse what the schema cannot express.
- **Letting a tool take a principal from its arguments.** The identity comes from the verified principal
  (traditional path, lesson 8), never from a tool argument — otherwise the model can choose whose data it
  reads.
- **Registering a write tool because it is convenient.** A refund, an email, a delete: each one is an
  action that needs approval, which is the hybrid path's subject.
- **Ignoring the errors the loop feeds back.** A `ToolResult` with `ok=False` is information the model can
  use; swallowing it produces a confident answer built on nothing.
- **Logging argument values.** They are user data; log keys, tool names, outcomes, and durations.
- **Setting `max_rounds` high "to be safe".** Safety is the limit, not its absence.

## Next

Lesson 12 uses structured output for routing: an intent, a handler, and the rules that do not need a model
at all.
