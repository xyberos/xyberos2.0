---
title: Retrieval over embed
path: ai
lesson: 10
tier: not-provided
status: verified
verify: output
example: examples/learn_ai/ai10_retrieval.py
prerequisites: ["/learn/ai/09-knowledge"]
---

# Lesson 10 — retrieval over `embed`

## What you will build

Retrieval: the passages from lesson 9, a question, and a ranking that decides what the model will read.
The runtime gives you `embed` and nothing else — no vector index, no similarity function, no reranker —
so this lesson is the strategy, written out.

## What you need

Nothing new.

<!-- snippet: examples/learn_ai/ai10_retrieval.py -->

Four decisions are visible in that module, and each one is yours to make:

- **Batch the inputs.** One `EmbeddingRequest` with every passage is one call; a request per passage is
  N calls for the same result.
- **Store vectors as JSON text.** Honest and portable for a few thousand passages, and 25 characters per
  vector at four dimensions — the same column holds kilobytes at 1536, which is where a real deployment
  starts thinking about a dedicated index.
- **Rank in Python.** Cosine similarity over a list is fine for a corpus you can hold in a query; past
  that, the ranking belongs in the database, not in the application.
- **Use the same model for passages and question.** Vectors from two models are not comparable, and the
  failure is silent: every score looks plausible and none of them mean anything.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_ai.ai10_retrieval
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_ai.ai10_retrieval
    ```

## What it prints

<!-- output: ai10_retrieval -->
```text
passages stored: 5
vector width:   4
question: How long does a refund take?
  1.0  pricing.md#1  Seats can be added at any time during the term.
  1.0  policy.md#1  A refund takes three business days to appear on a statement.
  1.0  policy.md#2  Orders older than ninety days are handled by the billing team.
one stored vector: 25 characters of JSON
this order is procedural, not semantic: the deterministic provider hashes text instead of
representing meaning, so every passage scores the same - with a real embedding model the
refund passage ranks first, and lesson 16 is how you measure that rather than assume it.
```

Read the last four lines together, because they are the most honest thing in this lesson. The
deterministic provider derives its vectors from a **hash**, not from meaning, so every passage scores
`1.0` and the order is procedural. The code is right; the *model* is a stand-in. That gap is the subject
of lesson 16: retrieval quality is measured against a labelled set, and a ranking nobody measured is a
guess with a number attached.

With a real embedding model the same module returns the refund passage first — same storage, same query,
same cosine — which is the part you take with you.

## What you do not get

| Not shipped | What that means for you |
| ----------- | ----------------------- |
| A vector index | choose one when the corpus outgrows the working set; until then, a column and a loop |
| A similarity function | cosine, dot product, or distance — and know which your index uses |
| A reranker | a second model or a rule that reorders the top-k; optional, and measurable |
| Chunking, loading, deduplication | lesson 9's decisions, not the framework's |

## Common mistakes

- **Embedding the question and the passages with different models.** The scores are not comparable, and
  nothing warns you.
- **Forgetting that similarity is not relevance.** The closest passage can be the wrong one; the metric
  answers "what is near", and only evaluation answers "what helps".
- **Sending every passage to the model.** Retrieval exists to *reduce* what the model reads; a top-k of
  fifty is a prompt nobody measured.
- **Ranking without showing the source.** A retrieval that cannot cite is a retrieval nobody can check,
  and lesson 16 has nothing to measure.
- **Embedding on every request.** Passages change rarely and questions change constantly; embed the
  corpus once, and store it.

## Next

Lesson 11 gives the model a way to act — through an allowlist, with arguments checked against a schema.
