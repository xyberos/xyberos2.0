---
title: Draft replies that are never sent
path: hybrid
lesson: 6
tier: built-in
status: verified
verify: output
example: examples/learn_hybrid/hybrid06_draft.py
prerequisites: ["/learn/hybrid/05-retrieval"]
---

# Lesson 6 — draft replies that are never sent

## What you will build

The draft, and the proof that it stays a draft. A generated reply is stored as a **row attached to the
ticket**: it has no send method, no route sends it, and the only code that writes to the outbox is the
one lesson 7 unlocks. The transcript's last two lines are the assertion the whole path exists to make —
the draft is waiting, and `count` is `0`.

This is the lesson to read if you remember one thing: **a model's output is data, and data does not
have side effects.** Everything that makes that true here is ordinary application code: a table, a
state machine, and a mailer nobody can reach.

## What you need

Nothing new.

<!-- snippet: examples/support_desk/mail.py -->

<!-- snippet: examples/learn_hybrid/hybrid06_draft.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_hybrid.hybrid06_draft
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_hybrid.hybrid06_draft
    ```

## What it prints

<!-- output: hybrid06_draft -->
```text
classified as: refund / high
the draft: A refund takes three business days to appear.
  written by: fake-model - approved by: None
  the ticket is: awaiting_approval
messages sent so far: 0
sending the draft -> 409 send is not allowed while a ticket is in 'awaiting_approval'
the trail records the draft, and no send: ['opened', 'classified', 'drafted']
still nothing sent: 0
```

`send` is refused with a `409` that names the state, not a `500` and not a silent success: the request
was well formed, the caller was allowed, and the *ticket* is not in a state where sending is a thing
that can happen. That is what a transition table buys — a refusal a client can act on.

The `trail` line is the second half of the boundary: the draft is recorded, so an incident review can
see that a model wrote something and that nobody sent it.

## Common mistakes

- **Sending "as a convenience" after drafting.** The moment a draft can send itself, the approval
  transition is decoration. Keep the effect in a route a person calls.
- **Storing the draft as an email and hoping.** A draft in a mail queue is a draft that will leave the
  building when the queue is flushed.
- **Letting the model write the state.** `attach_suggestion` writes `awaiting_approval`; the model
  cannot name a state, and the payload cannot either.
- **No record of what the model wrote once it is edited.** Keep the draft and the approved text in
  separate columns, so "what did it say" and "what did we say" stay different questions.
- **A send that succeeds and a commit that fails.** Write the outbox row in the same transaction as the
  state change, which is what `mail.py` does.

## Next

Lesson 7 is the approval itself: who may give it, what it records, and what it unlocks.
