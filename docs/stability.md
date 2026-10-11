# Stability and versioning

> Status: Phase 7. This page states what you may rely on, what may change, and how a change is
> announced. The decision behind it is [ADR 0013](./adr/0013-stable-surface-and-versioning.md).

Xyberos is at `0.0.0`. Nothing is released yet, so the honest summary is: **the stable tier is
declared and frozen, and it will not promise `1.0.0` compatibility until `1.0.0` exists.**

## The three tiers

| Tier | What it means | How it is marked | Can it change before `1.0.0`? |
| --- | --- | --- | --- |
| **Stable** | The contract this project intends to keep. Changing it requires an ADR, a changelog entry, and a deprecation where one is possible | Nothing extra — a name in the documented import path and in `__all__` is stable | Yes, in a `0.x` minor release, with upgrade notes |
| **Preview** | Shipped, documented, and tested, but the shape may still move as real use reveals the right one | The guide says "preview API" in its status line | Yes, in any `0.x` release |
| **Experimental** | Explicitly narrow, with stated non-guarantees that are part of the contract | `ExperimentalWarning` at the entry point, plus a limits section in the guide | Yes, at any time; the non-guarantees are the contract |

The tiers are about *promises*, not about quality. Every tier is tested; the difference is what
happens when a test is not enough and the shape turns out to be wrong.

## What is in each tier

| Surface | Import path | Tier |
| --- | --- | --- |
| Application runtime: composition, providers, scopes, lifecycle, route records, context and logging | `xyberos` | stable |
| Configuration: TOML, environment mapping, typed sections | `xyberos` | stable |
| Workflow definitions and the in-process executor | `xyberos` / `xyberos.execution` | stable |
| Plugin protocol and registry | `xyberos.plugins` | stable |
| Error taxonomy | `xyberos.errors` | stable |
| Deprecation mechanics | `xyberos.deprecation` | stable |
| HTTP adapter (Starlette) | `xyberos.http` | preview |
| SQLite provider and migrations | `xyberos.database` | preview |
| AI facade, contracts, tools, schema subset, fake provider | `xyberos.ai` | preview |
| Ollama adapter | `xyberos.ai.ollama` | preview |
| Test doubles (`ManualClock`, `FakeExternalService`, `FakeModelProvider`, `temporary_database`, `create_test_client`) | the `*.testing` modules | preview |
| Durable executor | `xyberos.durable` | **experimental** |

A tier applies to a whole surface, not to a version of it: `xyberos.ai` is preview even where it is
built only on stable pieces, because its contracts are newer and less exercised.

### Minimal support range for the stable tier

Concretely, the stable tier covers: an `App` composed from typed providers, configured from TOML and
the environment, started and stopped through `lifespan()`, with providers resolved by declared
annotation and released in reverse dependency order; a `Workflow` definition validated before it
runs and executed with bounded retries, deadlines, cancellation, and structured events; a plugin
implementing the documented class attributes and `register`; and the error types those raise.

## Import paths, and what counts as public

- **A name is public if a guide names it as an import, or it is in the module's `__all__`.**
  Everything else is internal and may move in any release, including a patch.
- **`__all__` is frozen by a test** (`tests/test_public_surface.py`), so a name leaving the surface is
  a deliberate edit to that file rather than a side effect of a refactor. That test is also what
  caught five modules whose surface was accidentally "whatever their imports left behind".
- **Import from the module that defines a name.** A name reachable through a package only because
  something imported it there is not public, which is why `xyberos.http` no longer advertises its
  handler-compilation internals.
- Submodules bound on a package by importing them (`xyberos.app`, `xyberos.errors`) are an
  implementation detail of the import system, not a promise.

## Versioning rules

The package uses PEP 440 spelling for SemVer concepts, starting at `0.0.0`.

- **`0.x` releases are preview releases.** A breaking change may happen in a minor release
  (`0.4` → `0.5`) with upgrade notes. A patch release fixes defects and does not break a documented
  stable name.
- **`1.0.0` is reserved** for the release that first promises the stable tier. From then on, a
  breaking change to a stable name requires a major release.
- **Versioned independently of the package:** the plugin API (`PLUGIN_API_VERSION`), the
  configuration schema (`schema_version`), Workflow definition versions (the `version` you declare),
  and the durable journal schema (`JOURNAL_SCHEMA_VERSION`). Each is a number you will see in an
  error message rather than in the package version.
- **Python support** is `3.10` through `3.13`, tested in CI. Adding a newer Python is a minor
  release; dropping the oldest is a breaking change and is done as a `0.x` minor with upgrade notes
  (or a major release after `1.0.0`).
- **Third-party ranges are floored, not capped** where the dependency is stable: `starlette>=0.40`,
  `sqlalchemy>=2.0,<2.1`, `httpx>=0.27,<1`. A dependency's major release forces a decision rather
  than a surprise.

### The Ollama release floor

One supported external range is a *service* version rather than a package: **Ollama 0.5.0 or newer**,
enforced by the adapter and explained in the [AI guide](./ai.md#supported-ollama-releases-and-models).
It is listed here because it is a compatibility promise in the same sense: the floor is set by the
newest feature the adapter uses, and the adapter refuses to run below it rather than degrading.

## Deprecating something

Deprecation is the mechanism that makes a promise survivable, so it is a documented process rather
than an improvised warning:

1. **Announce it in the changelog** under "Deprecated", naming the replacement.
2. **Warn at runtime** from the deprecated path:

   ```python
   from xyberos.deprecation import warn_deprecated, deprecated

   warn_deprecated(
       "App.provide(instance=...)",
       since="0.2",
       removed_in="1.0",
       alternative="App.provide(factory=...)",
   )


   @deprecated("old_helper", since="0.2", alternative="new_helper")
   def old_helper() -> None: ...
   ```

3. **Keep it working** for at least one minor release after the announcement. A deprecation removed
   in the same release that announced it is not a deprecation.
4. **Remove it in a minor release**, and say so in the changelog under "Removed".

`warn_deprecated` composes its message from the subject, the release it started warning in, the
replacement, and the release that will remove it, so all four facts are stated once and appear
everywhere. The warning class derives from `DeprecationWarning`, which means it is silent by default,
visible under `-W default`, and an error under `-W error` — the behaviour a user expects from a
deprecation, and quiet enough that it does not become noise in a long-lived application.

Deprecation and experimental warnings are deliberately different categories: a deprecation says
"this will stop working, and here is the replacement"; `ExperimentalWarning` says "this may change".
Users filter them differently, so they are different classes.

## What is not promised

- **No stability for internals**, including anything not in `__all__` or not named by a guide.
- **No stable serialization format** except the ones with an explicit version: definition metadata
  (JSON, with a declared `version`) and the journal (a versioned schema that refuses a newer file).
  Do not parse `render()` output; it is for humans and tests.
- **No compatibility promise for the experimental tier**, whose non-guarantees are part of its
  contract: see [the durable guide](./durable.md#deliberate-limitations).
- **No deprecation for a security fix.** A vulnerability may be fixed in a way that changes
  behaviour, and that will be said plainly in the release notes.
