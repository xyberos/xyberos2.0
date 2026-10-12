---
title: Conversation history
path: ai
lesson: 7
tier: not-provided
status: verified
verify: output
example: examples/learn_ai/ai07_history.py
prerequisites: ["/learn/ai/03-first-call"]
---

# Lesson 7 — conversation history

## What you will build

Context. The facade sends the messages it is given and remembers nothing, so a conversation is an object
the application owns: it records turns, decides what the next request may contain, and keeps that window
bounded. This is the first lesson in the path the runtime does **not** provide, and the page says so
rather than leaving you to discover it.

`xyberos.ai` is preview tier ([stability guide](../../reference/stability.md)).

## What you need

Nothing new.

<!-- snippet: examples/learn_ai/ai07_history.py -->

`Conversation.request` is the method that matters. It appends the new question, then sends
`(system, *self._messages[-window:])` — and that slice *is* the context policy. Two consequences follow,
and both are decisions rather than defaults:

- **A window is a truncation.** Something falls out of it. If the dropped turns matter, something has to
  remember them (lesson 8) or summarise them; if nothing does, forget them deliberately.
- **The model does not know what it said earlier** unless the request contains it. A conversation that
  "forgets" is a request that did not include the earlier turns.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_ai.ai07_history
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_ai.ai07_history
    ```

## What it prints

<!-- output: ai07_history -->
```text
turn 1: A refund takes three business days.
turn 2: Yes - that three-day window still stands.
the second request carried:
  system: You are a concise support assistant.
  user: How long does a refund take?
  assistant: A refund takes three business days.
  user: Does that still hold today?
```

The last block is the whole lesson: the second request carried **four** messages — the system prompt,
the first user turn, the assistant's answer, and the new question. Nothing was stored by the facade; the
provider simply received what the conversation handed it, and `provider.requests` shows exactly that.

## Common mistakes

- **Expecting the facade to remember.** It has no session, no store, and no notion of a conversation id;
  a second call with one message is a second call with one message.
- **Growing the window without a bound.** Cost grows with every turn you send, so a conversation left
  alone becomes the most expensive request in the system. Bound the window, and decide what the bound
  costs.
- **Keeping history in a module-level list.** Two users, one list: history belongs to a key the
  application owns — a conversation id, a ticket id, a principal.
- **Replaying untrusted turns as instructions.** A user's earlier message is data you are about to send
  as a message; prompt injection (lesson 17) is about exactly this boundary.
- **Forgetting that the window is not a cache.** Caching saves tokens; a window changes *what the model
  knows*. They are different decisions, and only one of them is about money.

## Next

Lesson 8 keeps what the window drops: durable facts, in a table you own, recalled into the prompt on
purpose.
