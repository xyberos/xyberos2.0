---
title: Knowledge retrieval you build
path: hybrid
lesson: 5
tier: not-provided
status: verified
verify: output
example: examples/learn_hybrid/hybrid05_retrieval.py
prerequisites: ["/learn/hybrid/04-classification"]
---

# Lesson 5 — knowledge retrieval you build

## What you will build

The part of retrieval the framework does not ship, because no amount of framework can decide it for
you: where documents are cut, what a passage is, where vectors live, and what a score means. The
package gives `embed` and nothing else — no loader, no chunker, no index, no vector store.

This lesson is deliberately the same material as the AI path's lessons 9 and 10, applied to the desk's
own articles. If you have read those, the only new thing here is that the passages live in the same
database as the tickets, in a table this application owns.

## What you need

Nothing new.

<!-- snippet: examples/support_desk/knowledge.py -->

<!-- snippet: examples/learn_hybrid/hybrid05_retrieval.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_hybrid.hybrid05_retrieval
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_hybrid.hybrid05_retrieval
    ```

## What it prints

<!-- output: hybrid05_retrieval -->
```text
passages indexed: 7
question: How long does a refund take?
  1.0000  accounts.md#0  Seats can be added at any time during the term of an enterprise plan.
  1.0000  refunds.md#1  A refund takes three business days to appear on a statement.
  1.0000  accounts.md#1  An account is closed when its last administrator asks for it to be closed.
vector width: 4
one vector: 24 characters of JSON
every score above is the same because the deterministic provider hashes text
instead of representing meaning, so the ranking is procedural. A real embedding
model is what makes the refund passage win - and lesson 16 of the AI path is how
you measure that instead of assuming it.
```

Every score is `1.0000`, and the refund passage is not first. That is the truth about the deterministic
provider, not a bug: it hashes text into a vector, so every vector points the same way and the ordering
you see is the tie-break in `search`. **A retrieval test that passes against this provider proves the
plumbing and nothing about relevance.**

That is why the transcript says so out loud, and why the AI path's lesson 16 exists: measure retrieval
against labelled questions, with the model you will actually run, and treat the score as evidence only
then.

The one thing this lesson does prove is the arithmetic and the cut: seven passages from three
documents, four-number vectors, cosine similarity over them, and a ranking function whose tie-breaks are
deterministic so a test can read it.

## Common mistakes

- **Treating a similarity score as relevance.** It is a distance in whatever space the model learned.
  Order by it, then measure whether the order is any good.
- **One passage per document.** A whole article dilutes what it matches; a sentence loses the context
  that made it true. Cut on structure (paragraphs, headings) and keep the source and ordinal.
- **A vector store before you have an index problem.** A text column and a Python sort is honest for
  hundreds of passages. Reach for the store when the arithmetic says so.
- **Forgetting `limit`.** Retrieval that returns everything is a context window waiting to overflow,
  and a bill to match.
- **Indexing inside a request.** Indexing is a deployment step with its own cadence; the route here
  exists so the desk has one, not so a request can trigger one.

## Next

Lesson 6 drafts a reply that quotes a passage — and sends nothing.
