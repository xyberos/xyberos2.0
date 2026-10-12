---
title: Human approval before sending
path: hybrid
lesson: 7
tier: not-provided
status: verified
verify: output
example: examples/learn_hybrid/hybrid07_approval.py
prerequisites: ["/learn/hybrid/06-draft"]
---

# Lesson 7 — human approval before sending

## What you will build

The boundary, enforced: **a model recommends, a person decides.** Sending requires an `approve`
transition, the approval records the principal, the time, and the exact body that was approved, and
the send path reads that column and nothing else. The three tickets in the transcript are the three
outcomes a review can find afterwards — sent as drafted, sent after an edit, and thrown away.

The permission matrix decides who may approve: an agent or a lead, never the requester. The transcript
starts with a requester's `403`, because that refund is the most expensive bug in this kind of
application: a customer, or a prompt, granting itself the right to reply on the company's behalf.

## What you need

Nothing new.

<!-- snippet: examples/support_desk/errors.py -->

<!-- snippet: examples/learn_hybrid/hybrid07_approval.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_hybrid.hybrid07_approval
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_hybrid.hybrid07_approval
    ```

## What it prints

<!-- output: hybrid07_approval -->
```text
a requester approving -> 403 this operation requires support_agent or support_lead
approve ticket 1 -> approved
send ticket 1 -> replied
the outbox has 1 message: A refund takes three business days (refund).
approve ticket 2 with an edit -> approved
what was sent: A replacement badge shipped this morning.
and what the model wrote is still there: A refund takes three business days (complaint).
  the approver: lee@desk
a lead rejecting ticket 3 -> rejected (nothing was drafted)
ticket 3 sent: 0
ticket 1 trail: ['opened', 'classified', 'drafted', 'approved', 'replied']
ticket 2 trail: ['opened', 'classified', 'drafted', 'approved', 'replied']
ticket 3 trail: ['opened', 'classified', 'rejected']
```

Read ticket 2's two lines together: what was sent is the edited sentence, and what the model wrote is
still in the row beside it. That pair is what makes an incident review possible — you can see both the
suggestion and the decision, and the `approved_by` column names the person who made it.

The last three lines are the audit trail per ticket. Note that `send` records `replied` and that the
state moved only because a body had been approved; the code that reads the approved body is the same
code that refuses when there is none.

## Common mistakes

- **Approving being the same call as sending.** Two steps, two decisions, two audit rows: one person
  may read and approve, and the send is what actually leaves the building.
- **Recording only that approval happened.** Without the body, an edit is invisible, and the trail
  cannot answer the only question that matters after a bad reply.
- **Letting the requester approve.** The role check is on the transition, so there is exactly one place
  it can be wrong.
- **Making the draft read-only to the approver.** Agents edit. Keep the model's text and the approved
  text apart, and let the audit row carry the one that was sent.
- **A cancel that leaves the draft pending forever.** Rejection is a transition with an outcome, which
  is what lesson 10 reads.

## Next

Lesson 8 writes the three steps down as a workflow: classify, ground, draft — with a branch for the
tickets nobody is sure about.
