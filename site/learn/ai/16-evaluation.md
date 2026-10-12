---
title: Evaluating quality
path: ai
lesson: 16
tier: not-provided
status: verified
verify: output
example: examples/learn_ai/ai16_evaluation.py
prerequisites: ["/learn/ai/15-testing"]
---

# Lesson 16 — evaluating quality

## What you will build

The half of quality that tests cannot reach. A test asserts that your code did what you wrote; an
evaluation measures whether the answers were any **good**, against a set of examples somebody labelled.
The runtime provides nothing here on purpose — an evaluation is a harness tuned to your product, and a
framework that guessed at "good" would be guessing for you.

## What you need

The `database` extra, because results that are not stored are opinions.

<!-- snippet: examples/learn_ai/ai16_evaluation.py -->

Five columns carry the whole report, and each one answers a different question:

| Column | The question it answers |
| ------ | ----------------------- |
| `expected`, `actual`, `correct` | did the classification land where a human said it should? |
| `grounded` | did the citation name a passage that was actually retrieved? |
| `latency_ms` | how long did the call take — recorded per run, reported as percentiles over many |
| `tokens` | what did it cost, in the unit the bill is written in |

`Case` is the labelled example, and the honest part of evaluation is admitting where the labels come
from: somebody read real requests and decided. Ten labelled cases tell you more than a thousand
unlabelled ones and a feeling.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_ai.ai16_evaluation
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_ai.ai16_evaluation
    ```

## What it prints

<!-- output: ai16_evaluation -->
```text
cases:      3
accuracy:   2/3
grounded:   2/3
tokens:     81
measured latency: recorded per row, reported as percentiles over many runs
  refund -> refund  correct=True grounded=True
  status -> status  correct=True grounded=True
  complaint -> refund  correct=False grounded=False
```

`accuracy: 2/3` is the number to look at, and the third case is the reason this lesson exists: the model
classified a complaint as a refund. Nothing crashed, no test failed, and the schema was satisfied — the
answer was simply **wrong**, and only a labelled case can see it. `grounded: 2/3` catches the other
failure: an answer that invented a citation (`none`) instead of citing a passage it was given.

## What to evaluate, in order

1. **Correctness on a labelled set.** The first number, and the only one that tells you whether the
   feature works.
2. **Grounding.** For anything that reads documents: does the answer cite what it was given?
3. **Refusals.** The cases where the right answer is "I cannot help" — measure them, because a model that
   never refuses is a model that guesses.
4. **Cost and latency.** Only meaningful once the first three are acceptable; a fast wrong answer is
   cheap and useless.
5. **Prompt changes.** Keep the labelled set in version control, and run it on every prompt change — this
   is the AI equivalent of a regression suite.

## Common mistakes

- **Calling a demo run an evaluation.** Three cases you wrote after seeing the answers is a smoke test;
  say so, and label the rest later.
- **Measuring only the happy path.** Refusals, empty retrievals, and adversarial inputs belong in the set;
  they are where regressions hide.
- **Comparing models on one number.** Cost and latency move in opposite directions from quality; a report
  with one number has already decided what you care about.
- **Letting the set rot.** Prompts change the distribution of requests; a labelled set from six months ago
  measures a product you no longer ship.
- **Judging by hand and storing nothing.** A human review that leaves no rows cannot be compared with the
  next one.

## Next

Lesson 17 is the last one: what an attacker does with all of this — untrusted text, tool permissions, and
what a log is allowed to keep.
