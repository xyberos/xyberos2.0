---
title: Intents
path: ai
lesson: 12
tier: not-provided
status: verified
verify: output
example: examples/learn_ai/ai12_intents.py
prerequisites: ["/learn/ai/05-structured"]
---

# Lesson 12 — intents

## What you will build

Routing: a request goes to a handler, and the model decides only the part that needs deciding. There is no
intent classifier in the package; there is `structured`, and a classification is what you build with it —
plus the rules that answer first because they are cheaper and more certain.

## What you need

Nothing new.

<!-- snippet: examples/learn_ai/ai12_intents.py -->

The order in `route_request` is the lesson, and it is the order most production routers converge on:

1. **A rule, if a rule can decide.** A ticket id in the text routes to tickets with no model call, no
   tokens, and no latency.
2. **`structured`, if it cannot.** The schema is closed (`refund`, `status`, `complaint`, `other`), so the
   model answers with one of four values rather than a sentence to parse.
3. **Confidence, then triage.** `low` is escalated to a human queue instead of being acted on. The enum
   makes the model answer; the confidence makes the *application* decide whether to trust it.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_ai.ai12_intents
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_ai.ai12_intents
    ```

## What it prints

<!-- output: ai12_intents -->
```text
'Ticket t-101 is still broken' -> support.tickets (matched T-101 without a model)
'How long does a refund take?' -> billing.refunds (refund (high))
'This is getting ridiculous' -> support.triage (low confidence for complaint)
model calls: 2
```

Note the last line: **three** requests, **two** model calls. The rule answered one for free, which is the
number to watch when an intent table grows — every classification the model does not have to make is
latency and money the application keeps.

## Common mistakes

- **Classifying what a condition can decide.** An order id, a recipient address, a keyword the business
  already knows: rules are faster, cheaper, and auditable.
- **Free-text intents.** `"Refund, probably"` is a string nobody can branch on; an enum in the schema is
  what makes routing a dictionary lookup.
- **Acting on low confidence.** A low-confidence classification is the model telling you it guessed.
  Route it to a person, or ask a second, different question.
- **One intent per request forever.** Real requests carry two; the first version should pick the dominant
  one and say so, rather than inventing a hierarchy.
- **Letting the router grow into a policy engine.** The routing table is application code: put it in one
  place, test it without a model, and let lesson 16 measure whether the model is helping.

## Next

Lesson 13 makes the sequence explicit: steps, edges, branches, deadlines, and a graph you can render and
review without running it.
