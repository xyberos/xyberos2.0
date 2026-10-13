# ADR 0020: Serialized introspection output is a versioned contract

**Status:** accepted

## Context

`xyberos check` began as a human report: it prints the settings it loaded, the providers in the graph,
the routes it compiled, and the plugins it registered, and exits non-zero when any of those is wrong.
Two kinds of caller wanted a different shape of the same answers:

1. **A deployment pipeline** wants to assert something about a built application — that a contract is
   provided, that a route exists, that a plugin registered — without parsing prose. Scraping a report
   means every reworded sentence is a breaking change, and the person who reworded it had no way to
   know.
2. **An editor** wants to complete and validate `xyberos.toml`, which means a machine-readable
   description of the configuration, not a table in a document.

Both are the same underlying problem: a description of a deployment that outlives the process that
printed it. The moment someone's script reads a key, that key is an interface — the same reason the
frozen `__all__` of [ADR 0005](0005-phase-1-runtime-contract.md) and the persisted fingerprint of
[ADR 0011](0011-durable-executor-contract.md) are pinned by tests rather than by convention.

There is a tension to resolve. A document assembled for humans changes freely; a document assembled
for programs cannot. And a schema that ships as a file can drift from the code that is supposed to
produce it — a stale schema is worse than no schema, because an editor then validates against a
description of a *different* application.

## Decision

**`xyberos check` grows three machine-facing modes, each generated from the same objects the runtime
uses, each either versioned or proven equal to its generator.**

1. **`check --json` emits one document with a `document` version.** It carries `xyberos_version`, the
   configuration file it read, the resolved settings, and — when an application is given — the
   provider graph, the plugins, and the route table. `DOCUMENT_VERSION` is `1`;
   `tests/test_compatibility.py` pins the version and the top-level keys, and
   `tests/cli/test_introspection.py` pins the nested shape beside the code that builds it, so
   removing or renaming a key fails a test rather than a pipeline.
2. **The document and the text report are built from the same calls.** Both read `App.diagnostics()`
   and `App.routes`; neither re-derives anything from the settings object. `tests/cli/` asserts the
   two describe the same application, which is what makes "the document cannot disagree with the
   report" a property rather than an intention.
3. **`check --why CONTRACT` prints the resolution path, not the graph.** The whole document answers
   "what is here"; diagnosing a failing lookup needs "why is *this* one here" — which provider
   satisfied the contract, at which scope, from which registration, and which hop each dependency
   came through. It accepts a bare name or a qualified one and refuses an unknown contract by listing
   the registered ones, because the error message is the interface for a typo.
4. **`check --schema` emits JSON Schema draft 2020-12, generated from the dataclasses.** Field
   properties and `required` come from `dataclasses.fields` and `typing.get_type_hints`, so a renamed
   setting cannot leave a stale property behind. Two channels are described differently on purpose: a
   plugin's `config_type` is a dataclass, so its section gets real properties and
   `additionalProperties: false`; `[ai.<name>]` is opaque to core, so the schema says "an object" and
   stops rather than guessing at keys core does not read.
5. **The shipped file is proven equal to the generator.** `src/xyberos/config.schema.json` is
   committed and included in the wheel, and `tests/test_config_schema.py` fails when it differs from
   `settings_schema()`. `--schema --app` additionally types the sections of that application's
   plugins, which is the version no file can ship, because the sections depend on what the
   application registers.
6. **The generator refuses what it cannot describe.** A `Settings` field whose annotation the
   generator does not understand raises instead of degrading to `{}`: a schema that describes nothing
   is an editor that silently completes nothing, which is the failure mode hardest to notice.

**What this contract does not promise.** Not a stable *ordering* of JSON keys — the document is
compared as a mapping, and consumers must not depend on position. Not that every key is present in
every mode: `application` is `null` when no `--app` was given, and `--why` and `--schema` are not
documents at all. And not `document: 1` forever: adding a key is additive within a version, while
removing, renaming, or changing the type of one bumps `DOCUMENT_VERSION`, which is exactly the
distinction the pinning test enforces.

## Consequences

- **A pipeline can assert on a deployment.** `check --json` exits non-zero on an invalid graph before
  printing, so a build step gets both a signal and, when it succeeds, a description it can query for
  the provider graph, the plugin list, and the routes — including whether the route table compiled.
- **`xyberos.toml` gets completion without an extension.** `--schema` writes a schema pointing at a
  published `$id`; unpacking the wheel gives the same file, and the drift test is what makes the
  static copy trustworthy. This is the concrete win of ADR 0018's rule that a capability needing
  nothing from PyPI is a module: describing a dataclass needs `dataclasses` and `typing`, so no
  schema library is added to a framework whose selling point is a small dependency set.
- **Providers and plugins gained two fields to make this honest.** `ProviderInfo.dependencies` records
  the edges `--why` walks, and `PluginInfo.config_type` is what `--schema --app` types a section
  from. Both are additive dataclass fields with defaults, so `PLUGIN_INFO_FIELDS` in
  `tests/test_compatibility.py` was widened as a deliberate, reviewed edit — which is the point of
  that test.
- **`cli/schema.py` is the second place the configuration shape is declared.** `config.py` remains the
  only place it is *read*; the generator is a projection of it, and the drift test is the guard. A
  hand-written schema was rejected for exactly the reason configuration is a dataclass: two
  declarations of one format diverge, and the divergence is invisible until a deployment reads the
  wrong key.
- **`--json`, `--why`, and `--schema` are mutually exclusive.** They answer three different questions
  and each prints a complete answer; allowing combinations would mean defining a fourth shape for the
  combination, which no caller asked for.
