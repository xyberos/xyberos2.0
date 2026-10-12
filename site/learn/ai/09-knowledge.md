---
title: Knowledge
path: ai
lesson: 9
tier: not-provided
status: verified
verify: output
example: examples/learn_ai/ai09_knowledge.py
prerequisites: ["/learn/ai/08-memory"]
---

# Lesson 9 — knowledge

## What you will build

The step before retrieval: documents in, passages out, stored as rows you can query. There is no document
loader in the package and no chunking strategy it recommends, because both are decisions about *your*
documents — and the decision that matters is where you cut.

## What you need

The `database` extra, for the same reason as lesson 8: passages that outlive the process are rows.

<!-- snippet: examples/learn_ai/ai09_knowledge.py -->

Three fields carry the whole design:

| Field | Why it exists |
| ----- | ------------- |
| `source` | a passage nobody can attribute is a passage nobody should trust; the citation starts here |
| `ordinal` | the position in the document, so a passage can be shown with its neighbours |
| `text` | the passage itself, normalised, because whitespace is not information |

`split` cuts on blank lines. That is the simplest rule that keeps a paragraph whole, and it is worth
being explicit about the trade it makes: a passage that is too long dilutes what it matches, one that is
too short loses the sentence that made it true, and overlap between passages buys context at the cost of
duplicates in the prompt.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_ai.ai09_knowledge
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_ai.ai09_knowledge
    ```

## What it prints

<!-- output: ai09_knowledge -->
```text
policy passages: 3
pricing passages: 2
stored: [('policy.md', 0), ('policy.md', 1), ('policy.md', 2), ('pricing.md', 0), ('pricing.md', 1)]
second passage: A refund takes three business days to appear on a statement.
dimensions: 11
```

| Line | What it establishes |
| ---- | ------------------- |
| `policy passages: 3` | one document became three rows, split where the author put a blank line |
| `stored: [...]` | the pairs `(source, ordinal)` — the identity of a passage, and what a citation needs |
| `second passage:` | the text, whitespace-collapsed, ready to be embedded |
| `dimensions: 11` | words in that passage: the count a chunking threshold would act on |

## Common mistakes

- **Chunking by character count alone.** It cuts sentences in half, and a half-sentence embeds as
  something nobody asked. Cut on structure first, then measure.
- **Storing the document and splitting at query time.** The same work on every request, and no way to
  cite which passage answered.
- **Dropping the source.** Grounding (lesson 10) and evaluation (lesson 16) both need to know which
  document a passage came from; a store without it cannot answer either question.
- **Loading once and never again.** Documents change; a reload needs to replace by `source`, which is the
  only reason the column has to be stable.
- **Treating the corpus as trusted text.** Everything here is untrusted input that will later be placed
  in a prompt — lesson 17's subject.

## Next

Lesson 10 gives each passage a vector and ranks them against a question: retrieval you build, over
`embed`, with no index shipped.
