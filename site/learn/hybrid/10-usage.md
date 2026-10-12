---
title: Logging usage, cost, and outcomes
path: hybrid
lesson: 10
tier: not-provided
status: verified
verify: output
example: examples/learn_hybrid/hybrid10_usage.py
prerequisites: ["/learn/hybrid/09-background"]
---

# Lesson 10 — logging usage, cost, and outcomes

## What you will build

The report that makes the spend answerable. One row per model call, with the tokens the provider
reported, a price the application owns, and an **outcome** column that is written when a person decides
what became of the reply.

That column is the lesson. A measure you metered but never settled can tell you what you bought but not
whether it was worth anything; here, the tickets that were rejected are in the same report as the ones
that were sent, and they cost the same. Answering "what did triage cost per useful reply" is then a
query rather than a project.

## What you need

Nothing new.

<!-- snippet: examples/support_desk/usage.py -->

<!-- snippet: examples/learn_hybrid/hybrid10_usage.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_hybrid.hybrid10_usage
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_hybrid.hybrid10_usage
    ```

## What it prints

<!-- output: hybrid10_usage -->
```text
step       calls  tokens in  tokens out  cost (micros)
classify       3       3510          54        945000
draft          2       2770          85        798750
outcomes: {'accepted': 2, 'discarded': 1, 'edited': 2}
total cost: 1743750 micros, for 5 calls
a discarded reply cost the same as an accepted one: the outcome column is what
tells the two apart, and it is written when a person decides.
```

Costs are in **millionths of a dollar**, which keeps the arithmetic in integers: a price is per
thousand tokens, so a sum of rounded cents would drift and a sum of floats would disagree with itself.
`PRICES` is the application's table, deliberately — a price is a fact about a contract, and an
application that has to redeploy to learn what it paid has no finance report.

The outcomes count rows, not tickets: one reply costs a classification and a draft, so an accepted
reply is two rows. That is a property of the design worth stating out loud rather than discovering in a
dashboard.

## Common mistakes

- **Metering calls, not outcomes.** Without the outcome column, "accepted" and "thrown away" are the
  same number.
- **Prices inside the application's code paths.** One table, read by the report, so a price change is a
  data change.
- **Floating-point money.** Micros, integers, and one rounding step per row.
- **Recording the provider's model name as yours.** Record what the response reported, so a fallback
  model is visible in the report rather than averaged into the primary one.
- **A report that needs the model to build.** This one is SQL over rows the application already wrote;
  it answers after an incident, when the provider is exactly what is unavailable.

## Where this path leaves you

You have built the desk: tickets, permissions, an audit trail, and a model that classifies, retrieves,
and drafts behind a boundary a person controls. The three halves are the three other paths —
[Fundamentals](../fundamentals/index.md) for the runtime, [Traditional Apps](../traditional/index.md)
for the application around it, and [AI Apps](../ai/index.md) for the capability itself — and
[the roadmap](../../roadmap.md) lists what each one covers.

Next in the plan: the Extend Xyberos section, for writing the providers, plugins, and modules this
application has been consuming all along.
