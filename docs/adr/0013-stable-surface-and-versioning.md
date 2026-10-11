# ADR 0013: Freeze the stable surface and its versioning rules

**Status:** accepted

## Context

[ADR 0003](0003-versions-and-experimental-scope.md) deferred one consequence to this phase: "Public
contracts require explicit compatibility/versioning decisions before `1.0.0`." Phases 1–6 built six
documented surfaces and froze each one's *behaviour* in an ADR, but never answered the question a
user actually has before adopting any of it: which names are promised, and what happens when one has
to change?

An audit of the surface found the answer was partly accidental. Five documented modules declared no
`__all__`, so their public surface was whatever their imports left behind — `Mapping`, `dataclass`,
`json`, `sys`, and a private type variable were importable as API. Two package surfaces advertised
internals (`xyberos.http` exported `PATH`, `REQUEST`, `HandlerParameter`, and the error payload
helpers; `xyberos.plugins` exported `PLUGIN_API_MAJOR`). None of that was decided; it was drift, and
an internal refactor could have changed the public API without anyone noticing.

## Decision

**The public surface is what a guide names, or what a module's `__all__` declares, and nothing else.**
Every documented module declares `__all__`, and `tests/test_public_surface.py` freezes the exact set
per module. Adding or removing a name is therefore an edit to that file — a deliberate act with a
diff — rather than a consequence of moving an import.

**Names that were never promised are removed from `__all__`** rather than frozen for compatibility:
the handler-compilation internals in `xyberos.http`, `PLUGIN_API_MAJOR` in `xyberos.plugins`. They
remain importable from the module that defines them, which is what internal code and tests use. This
is a `0.x` change and is recorded as such.

**Three tiers, defined by what is promised rather than by quality.** *Stable* is the contract the
project intends to keep. *Preview* is shipped, documented, and tested but may still move as real use
reveals the right shape. *Experimental* carries stated non-guarantees that are part of its contract
and warns at its entry point. The tier of every surface is listed in
[`docs/stability.md`](../stability.md), which is the user-facing version of this decision; this ADR
records the rules behind it.

**Versioning follows PEP 440 spelling of SemVer concepts, starting at `0.0.0`.** A `0.x` minor
release may break a stable name with upgrade notes; a patch release does not. `1.0.0` is reserved for
the first release that promises the stable tier. Four things are versioned independently of the
package and are surfaced in error messages rather than in the version number: the plugin API, the
configuration schema, Workflow definition versions, and the journal schema.

> **Later decision (release preparation).** The rules above stand; the numbers they hang on changed.
> This line publishes as `2.0.0` and its version base is `2.x`, because the `xyberos` name is held on
> the package index by the already-published 1.x line.
> [ADR 0017](./0017-release-identity-and-lineage.md) records why, and `2.0.0` takes over the role this
> ADR gives to `1.0.0` below. The distinction drawn here — that the leading digit is a promise about
> compatibility while the tier table is a promise about change — is unchanged, except that the leading
> digit now encodes lineage rather than maturity.

**Deprecation is a process with mechanics, not an improvisation.** A deprecated path warns, names its
replacement, and states the release that will remove it; it keeps working for at least one minor
release after the announcement. `xyberos.deprecation` provides `warn_deprecated` and a `deprecated`
decorator, and the warning class derives from `DeprecationWarning` so standard warning filters apply.
It ships before the first deprecation exists on purpose: inventing a warning style at the moment of
the first break is how inconsistent warnings happen.

**Compatibility is tested, not asserted in prose.** Four surfaces are pinned by tests: public
imports, configuration fields, the plugin protocol, and serialized Workflow metadata. The fingerprint
test is the sharpest, because the durable journal persists a definition fingerprint that gates
resumption of in-flight executions: changing how it is computed invalidates work already in a
journal, so a golden value turns that into a reviewed diff.

## Consequences

- `1.0.0` now means something specific: the release that starts promising the stable tier. Until
  then, "stability" is this project's declared intent plus tested pinning, not a release guarantee.
- The tier of a surface is a promise about *change*, so it must be revisited when a preview surface
  becomes depended upon. Promoting a preview surface to stable is a deliberate decision, not a
  natural consequence of time passing.
- Freezing `__all__` makes intentional additions slightly noisier (one test edit per change) and makes
  accidental ones impossible. That trade is the point.
- The `deprecated` decorator wraps a callable, so it is appropriate for functions and methods. A
  removed *attribute*, a changed *default*, or a changed *exception type* cannot be deprecated by
  warning and must be documented as a breaking change instead.
- Compatibility tests for configuration and the plugin protocol assert shapes, not behaviour; they
  cannot detect a change that keeps the same field names but alters their meaning.
- Two module-level constants remain in `xyberos.runtime.context` (`CORRELATION_ID_KEY`,
  `DEADLINE_KEY`) that nothing outside the module uses. They are not public surface, and renaming
  them would be churn without benefit; they are recorded here so the next audit does not re-litigate
  it.
- Phase 7's release notes and changelog now have a defined shape to write into: added, changed,
  deprecated, removed, fixed, and security. *Satisfied: `CHANGELOG.md` uses exactly those sections,
  and [`docs/release.md`](../release.md) names them as the shape of a release entry.*
