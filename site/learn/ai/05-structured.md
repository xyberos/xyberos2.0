---
title: Structured output
path: ai
lesson: 5
tier: built-in
status: verified
verify: output
example: examples/learn_ai/ai05_structured.py
prerequisites: ["/learn/ai/03-first-call"]
---

# Lesson 5 — structured output

## What you will build

A model answer an application can act on: a payload validated against a schema you wrote, with three
distinct refusals for the three ways it can go wrong. This is the lesson that turns "the model said
something" into a value a program may branch on.

## What you need

Nothing new.

<!-- snippet: examples/learn_ai/ai05_structured.py -->

Three checks are in play, and they happen at different times:

| Check | When | What it prevents |
| ----- | ---- | ---------------- |
| `check_schema(schema, location=...)` | at startup, or in a test | a schema outside the supported subset, discovered at 3am |
| the capability declaration (lesson 2) | before the call | asking a provider for something it cannot do |
| `validate_payload` / `AISchemaError` | on the response | acting on a payload that does not match what you asked for |

The subset is **closed** on purpose. It supports `type`, `properties`, `required`, `enum`, `items`,
`additionalProperties`, the length/range keywords, and `minimum`/`maximum` — and it names the keywords it
does not support in the error rather than approximating them.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_ai.ai05_structured
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_ai.ai05_structured
    ```

## What it prints

<!-- output: ai05_structured -->
```text
the schema is usable: object
accepted: {'category': 'complaint', 'confidence': 'high'}
refused: the model response at $.category must be one of: 'refund', 'question', 'complaint'; got 'banana'
unparseable: AIInvalidPayloadError the model returned content that is not JSON (Expecting value); retry the call or adjust the prompt
a schema outside the subset: AIRequestError lesson at $ uses unsupported keyword(s): oneOf; supported keywords are: additionalProperties, enum, items, maxItems, maxLength, maximum, minItems, minLength, minimum, properties, required, type
```

Four lines, four different outcomes:

- **`accepted:`** the payload satisfied the schema, and the facade returned it as a mapping.
- **`refused:`** valid JSON that breaks the schema — `'banana'` is not one of the three categories — is
  an `AISchemaError`. This is the failure a retry can fix and an `if` cannot.
- **`unparseable:`** text instead of JSON is an `AIInvalidPayloadError`, which the taxonomy treats as
  *transient*: trying again often succeeds, because the model's next answer may be well-formed.
- **`a schema outside the subset:`** `oneOf` is refused at the point you declare it, before a single call.

## Common mistakes

- **Parsing the content yourself.** `json.loads(response.message.content)` throws away the validation and
  the error taxonomy; the facade already did both.
- **Validating with a schema you never checked.** A schema with an unsupported keyword is not a stricter
  schema, it is a different one; `check_schema` at startup is one line.
- **Trusting a valid payload to be a correct one.** A payload can satisfy the schema and still be
  wrong — the model chose a category that passes the enum and is not the right one. Validation buys
  shape, not correctness, which is lesson 16's subject.
- **Adding `additionalProperties: true` to be flexible.** It lets a model invent fields the application
  then ignores; keep schemas closed and version them when they change.
- **Treating a schema error as fatal.** It is a retryable transport failure by construction — retry with
  the same prompt, or with the error appended, before giving up.

## Next

Lesson 6 is about everything that can go wrong on the way to that payload: timeouts, rate limits,
refusals, and which of them are worth retrying.
