# ADR 0017: Publish this line as `xyberos` 2.0.0

**Status:** accepted

## Context

[ADR 0003](0003-versions-and-experimental-scope.md) decided that the package would begin at `0.0.0`,
and [ADR 0013](0013-stable-surface-and-versioning.md) reserved `1.0.0` for the first release that
promises the stable tier. Both assumed the number was free. It is not.

The name is already held on the package index by the previous line of this project:

| | Published `xyberos` 1.0.3 | this repository |
| --- | --- | --- |
| Last upload | 2026-08-17; 16 releases from `0.4.0` | never |
| Declared maturity | `Development Status :: 5 - Production/Stable` | `Development Status :: 2 - Pre-Alpha` |
| Import root | `xyberos` — 22 subpackages, 127 modules | `xyberos` — 8 subpackages |
| Ecosystem | 23 satellite distributions (`xyberos-auth`, `-db`, `-queues`, `-redis`, `-mcp`, …), a documentation site, an organisation | none |

Both lines install a top-level `xyberos` package, and both define `xyberos.runtime` and
`xyberos.plugins` with unrelated contents. Three consequences follow, and each is a fact about the
index rather than a preference:

1. **A `0.1.0` upload would be unreachable.** An index accepts it, but `pip install xyberos` resolves
   the highest version — `1.0.3` — so the new runtime would be invisible to exactly the audience the
   release exists for.
2. **Two environments, not one.** The two lines can never be installed together, because they collide
   on the import root and on two submodule names.
3. **The identity is already in use, by this project.** The documentation domain, the organisation,
   and 23 published satellite packages describing a much larger surface already point at the name.

An earlier attempt at this rewrite lived in a sibling directory under the working name
`xyberos-minimal` at `2.0.0`, and was never published; that name is still free. The plan calls this
work "version 3.0" (`PLAN.md` section 11), which counts internal attempts, not published lines.

## Decision

**The first published release of this line is `xyberos` `2.0.0`, and the version base for this line
is `2.x`.**

1. **The leading digit encodes lineage, not maturity.** `2.0.0` says "the line after the published
   `1.0.3`, and not compatible with it". It does not claim parity with 1.x, battle-testing, or an
   unchanged API. Maturity is stated by the `Development Status` classifier and by
   [the tier table](../stability.md), which is the only thing that answers "can I rely on this?".
2. **Because of (1), the classifier becomes `Development Status :: 4 - Beta`.** `2 - Pre-Alpha` beside
   a `2.0.0` major is a contradiction a reader has to resolve, and `5 - Production/Stable` is what the
   previous line claims and this one cannot. Beta is what the evidence supports: a declared and frozen
   stable tier, roughly 790 tests, an enforced quality gate, documented preview and experimental
   tiers, and no external users yet.
3. **`1.0.0` is not a milestone here.** It is behind this line and belongs to the other one. `2.0.0`
   takes over ADR 0013's role as *the release that first promises the stable tier*; from it, breaking
   a documented stable name requires a major release.
4. **`0.0.0` keeps its meaning as the working placeholder** for "the next release has not been cut",
   and stays in `pyproject.toml` and `__version__` until the release commit. Staging forms are spelled
   against the real base: `2.0.0.dev1`, `2.0.0rc1`.
5. **The 1.x line stays published and installable, and its users are told what changed.** The changelog
   entry for `2.0.0` states the break in its first line, and the release procedure tells a 1.x user to
   pin `xyberos<2` if they depend on the 1.x API.

## Consequences

- **The upgrade from 1.x is a break, and it is voluntary.** Nothing is yanked or edited: `1.0.3`
  remains downloadable, so an existing pin keeps working and no installed environment is changed by
  publishing. What cannot happen is an upgrade that preserves behaviour, and the documentation says so
  rather than letting a user discover it.
- **This supersedes the versioning clause of ADR 0003 and re-bases the numbering in ADR 0013.** ADR
  0003's other decision — that AI and durable execution are optional *installations*, with
  experimental scope labelled — is unaffected and remains in force. ADR 0013's rules for tiers,
  deprecation, and pinned compatibility are unaffected; only the number they hang on changes.
- **The two names still collide, and that is now a documented boundary rather than a discovery.** One
  environment holds either line, never both; a project that needs both runs two environments.
- **The number now carries less information than ADR 0013 intended.** `1.0.0` used to mean "the release
  that starts promising the stable tier", which is a strong claim a reader could act on. The leading
  digit is spent on lineage instead, so the promises a reader needs are carried by the tier table, the
  classifier, and the changelog. The trade is deliberate: a version number that resolves to the wrong
  codebase is worse than a version number that is only a lineage marker.
- **The release diff touches six files, not two.** `pyproject.toml` and `src/xyberos/__init__.py`
  carry the version, and four tests pin the placeholder literally (`tests/test_package.py`,
  `tests/test_public_api.py`, `tests/test_compatibility.py`, `tests/cli/test_cli.py`). Those four pins
  are deliberate — they make a version bump a reviewed diff rather than a silent string change — and
  [the release procedure](../release.md) now names all six.
- **A 2.x line invites the question "what happened to 1.x?"** A reader who knows the published package
  will ask, so the answer is written where they arrive — the README, the changelog, and this ADR —
  rather than left to inference.
- **Choosing the lineage number does not make the release reachable.** Publishing is still gated on the
  project owner's sign-off, and `pip install xyberos` resolves to `2.0.0` only after the upload.
- **This does not settle whether `xyberos.ai` ships in the core distribution.** That is a separate
  question about what a stable package contains, and it remains open.
