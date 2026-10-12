---
title: Memory
path: ai
lesson: 8
tier: not-provided
status: verified
verify: output
example: examples/learn_ai/ai08_memory.py
prerequisites: ["/learn/ai/07-history"]
---

# Lesson 8 — memory

## What you will build

Memory, which in this path means three ordinary things: a table, a query, and a decision about which
rows belong in the next request. There is no framework memory layer, no embedding store, and no
automatic recall — and the code below is what a memory looks like when you need one.

## What you need

The `database` extra, because memory that survives the process is a database:

=== "PowerShell"

    ```powershell
    python -m pip install "xyberos[database]"
    ```

=== "POSIX"

    ```bash
    python -m pip install 'xyberos[database]'
    ```

<!-- snippet: examples/learn_ai/ai08_memory.py -->

`MemoryStore` is a service with two methods, and `as_system_message` is where the interesting decision
lives: it *chooses* a representation. The rows are facts; the prompt is a sentence. Turning one into the
other is application policy, and it is the part that changes when the model changes.

The recall is a `SELECT ... WHERE subject = ? ORDER BY id LIMIT 5`. Lesson 10 replaces that `WHERE` with
a similarity query over `embed`; the shape of the store, the insert, and the prompt-building step do not
change.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_ai.ai08_memory
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_ai.ai08_memory
    ```

## What it prints

<!-- output: ai08_memory -->
```text
remembered: [('preference', 'prefers email over phone'), ('fact', 'is on the enterprise plan')]
the model saw: What you remember about acme: preference=prefers email over phone; fact=is on the enterprise plan
answer: A refund takes three business days.
```

| Line | What it establishes |
| ---- | ------------------- |
| `remembered: [...]` | two rows, in the order they were written, read back with one query |
| `the model saw: What you remember about acme: ...` | the system message `as_system_message` built — recall becomes context here and nowhere else |
| `answer:` | the provider's reply, which is unaffected by any of it |

## What memory is not

| Not this | Because |
| -------- | ------- |
| A bigger conversation window | a window is bounded by cost, and it forgets; a memory row is chosen |
| A vector index | similarity is lesson 10, and it is a *query strategy* over rows like these |
| A framework feature | anything that decided what to remember for you would be making a product decision |
| Always on | recall costs a query and a prompt; a fact nobody needs is tokens and a distraction |

## Common mistakes

- **Remembering everything.** A memory store that grows without a retention rule turns into a slower,
  more expensive prompt; the useful half of memory is what you choose to *forget*.
- **Recalling without a subject.** `WHERE subject = ?` is the whole scoping mechanism — the same lesson
  as the traditional path's tenant, and the reason a memory key belongs to a principal rather than to a
  request body.
- **Putting recalled text in the user turn.** A memory is an instruction *by the application*; putting it
  in a user message lets a stored sentence argue with the system prompt.
- **Storing model output as fact.** A summary of a conversation is a summary; write it as one, with its
  source, or the next caller will treat a guess as data.
- **Skipping the retention index.** `ORDER BY id LIMIT 5` is fine for two rows and wrong for two million;
  the table needs the index its query needs.

## Next

Lesson 9 loads documents: text you did not write, split into passages, stored so lesson 10 can retrieve
them.
