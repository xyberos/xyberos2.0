---
title: Classification with structured output
path: hybrid
lesson: 4
tier: built-in
status: verified
verify: output
example: examples/learn_hybrid/hybrid04_classification.py
prerequisites: ["/learn/hybrid/03-audit"]
---

# Lesson 4 — classification with structured output

## What you will build

The first model call, and the smallest one that is useful: a category and a confidence, over the closed
schema subset the AI path's lesson 5 describes. The model answers; the **service** decides whether the
answer may move a ticket. That order is the whole design in one sentence.

Two things in the transcript are the lesson:

- a reply that is valid JSON but the wrong shape leaves the ticket exactly where it was, and the client
  is told nothing about what the model said;
- every provider failure looks the same from outside. The typed error is for the application, not for
  the caller.

## What you need

Nothing new: the AI facade is built into the package, and the fake provider is what these lessons use.

The classification request carries `response_schema`, and `check_schema` accepts only the keywords the
package implements: `type`, `properties`, `required`, and `additionalProperties`. `oneOf`, `$ref`, and
the rest of the JSON Schema vocabulary are refused at build time rather than half-honoured at runtime.

<!-- snippet: examples/support_desk/triage.py -->

<!-- snippet: examples/learn_hybrid/hybrid04_classification.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_hybrid.hybrid04_classification
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_hybrid.hybrid04_classification
    ```

## What it prints

<!-- output: hybrid04_classification -->
```text
accepted keywords: ['additionalProperties', 'properties', 'required', 'type']
categories:        ['refund', 'question', 'complaint', 'abuse'] confidences: ['low', 'medium', 'high']
a valid answer   200 ticket=classified leaked the model's text: False
  -> refund/high
the wrong shape  500 ticket=new        leaked the model's text: False
not JSON at all  500 ticket=new        leaked the model's text: False
every provider failure looks the same to a client: True
inside the application: AISchemaError - the model response at $.category must be one of: 'refund', 'question', 'complaint', 'abuse'; got 'banana'
a model without structured output -> 500
  and the ticket is still: new
the call is recorded: classify 31 tokens in
```

The `422`'s absence is the point: a model's bad answer is not the client's mistake, so it is a `500`
whose message says only that the request could not be completed. The model's text does not reach the
caller — `leaked the model's text: False` — because a response body is a place secrets and prompt
content travel by accident.

Read the `inside the application` line next to it: the same failure, seen where it matters, is a typed
`AISchemaError` that names the path (`$.category`) and the value that failed. An application logs that;
a client never sees it.

## Common mistakes

- **Treating a model's answer as input to validate.** It is output to *check*: the schema is the
  contract, and a wrong shape is a failure of the dependency, not of the caller.
- **Letting the model perform the transition.** `classify` asks for a value; `TicketService.classify`
  writes the row. If the model could write, there would be no place to enforce the matrix.
- **`structured()` when you also need the usage.** `AIFacade.structured` returns the payload alone.
  `chat` with a `response_schema` returns the payload *and* the tokens, which is what the usage row in
  lesson 10 needs.
- **A free-text prompt for a category.** An enum in the schema is cheaper than parsing prose, and it
  fails loudly instead of silently inventing a category.
- **Catching the provider's error and returning it to the client.** Log the type; answer generically.

## Next

Lesson 5 gives the draft something to quote: passages you store, vectors you compute, and a similarity
query you write.
