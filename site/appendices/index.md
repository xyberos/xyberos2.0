---
title: Appendices
status: verified
---

# Appendices

Pages that document a real service rather than a mechanism: a walkthrough against a running Ollama, a
run against a real PostgreSQL, anything that cannot execute in continuous integration.

## Why these are not lessons

A lesson on this site has to run offline, because that is the only way its output can be verified
before the page is published — a lesson whose output block says "your output will differ" is a page
that is not checked. So the mechanism is taught as a lesson with a fake provider, and the real service
appears here, where the assertion is command-level instead of output-level: the module imports, the
factory constructs a real object, and every quoted command names a target that exists.

## What an appendix must satisfy

- It is **outside every learning path**, so no lesson depends on a service to be readable.
- It contains no output block, because its output cannot be reproduced. It may quote real output in
  prose, clearly labelled as a transcript from one machine.
- Its commands are checked, and its module is exercised by an opt-in workflow that sets
  `XYBEROS_OLLAMA_LIVE=1` — the same gate `tests/ai/test_live_ollama.py` already uses, so a missing
  service can never fail a pull request.

There are no appendices yet. The first will be the live Ollama walkthrough for the AI path, and the
lesson that teaches the same mechanism without a service is
[the AI path overview](../learn/ai/index.md).
