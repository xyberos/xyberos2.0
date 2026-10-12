---
title: AI Apps
status: verified
---

# Build AI Apps

An AI Assistant, built one capability at a time. Every lesson is labelled with **who provides the
capability**, because the most expensive assumption a reader can make is that the framework ships the
part they are about to write: `xyberos.ai` is a provider-neutral facade, a closed JSON Schema subset, an
allowlisted tool layer, and a deterministic fake provider. There is no memory store, no document loader,
no vector index, no intent classifier, and no agent loop in the package, and the lessons that need one
say so and build it.

Each lesson runs with **no model service and no network**: the code you read is the code the suite runs,
against `FakeModelProvider`, and the output you see is the output it really produced. A live model is an
opt-in appendix rather than a lesson.

## Lessons

| # | Lesson | You will learn | Provided by |
| - | ------ | -------------- | ----------- |
| 1 | [An application that is AI-ready](01-ready.md) | A model behind a seam, and an app that runs without one | Built-in |
| 2 | [What a provider declares](02-providers.md) | Capabilities, checked before the call rather than after | Built-in |
| 3 | [The first call](03-first-call.md) | Messages, responses, model names, and token usage | Built-in |
| 4 | [Switch providers without touching the application](04-switch.md) | Why the facade exists, and what it costs | Built-in |
| 5 | [Structured output](05-structured.md) | A closed schema subset, and three distinct refusals | Built-in |
| 6 | [Failures, timeouts, and retries](06-errors.md) | The error taxonomy, and which failures are transient | Built-in |
| 7 | [Conversation history](07-history.md) | Context the caller assembles, and the window it sends | You build it |
| 8 | [Memory](08-memory.md) | A table, a query, and a decision about the next request | You build it |
| 9 | [Knowledge](09-knowledge.md) | Loading documents, and where a passage is cut | You build it |
| 10 | [Retrieval over `embed`](10-retrieval.md) | A similarity query you build, and why it must be measured | You build it (over `embed`) |
| 11 | [Tools](11-tools.md) | An allowlist, arguments checked against a schema, and events | Built-in |
| 12 | [Intents](12-intents.md) | Classification with `structured`, and the rules that come first | You build it (over `structured`) |
| 13 | [Workflows](13-workflows.md) | Explicit steps, branches, deadlines, and a renderable graph | Built-in |
| 14 | [Bounded agent behaviour](14-agent.md) | Tools plus a window, a budget, and the escalation path | You build it (tools + workflow) |
| 15 | [Testing the AI path](15-testing.md) | Every prompt, tool, and failure with no model service | Built-in (`FakeModelProvider`) |
| 16 | [Evaluating quality](16-evaluation.md) | Accuracy, grounding, cost, and latency as rows | You build it |
| 17 | [Securing AI applications](17-security.md) | Prompt injection, tool permissions, and redaction | Built-in boundaries, application code |

**All seventeen lessons are written.** The [roadmap](../../roadmap.md) is generated from each page's own
status, so it is the authority on what has landed rather than this table.

## What you need

The core package, and nothing else:
[the setup from fundamentals lesson 1](../fundamentals/index.md). To point any lesson at a real local
model, add the one adapter that ships:

=== "PowerShell"

    ```powershell
    python -m pip install "xyberos[ollama]"
    ```

=== "POSIX"

    ```bash
    python -m pip install 'xyberos[ollama]'
    ```

## Two things to know before it starts

**Preview means preview.** [`xyberos.ai`](../../reference/stability.md) is preview tier: the contract is
settled and the surface may still change in a minor release. Every page repeats the tier of what it
teaches.

**The fake provider is not a stub.** `FakeModelProvider` implements the provider contract, records the
requests it received, and answers deterministically from a script. That is why the AI path is testable in
CI, and lesson 15 is about using it rather than about avoiding it.
