# ADR 0012: License the project under Apache-2.0

**Status:** accepted

## Context

[ADR 0003](0003-versions-and-experimental-scope.md) recorded that the license was deliberately
undecided and had to be selected before any public distribution. Nothing could be released until
that was settled, and the moment was chosen deliberately: while the project has no outside
contributors, licenses cost nothing to change, and after the first external contribution the choice
is effectively permanent, because every contributor holds copyright in their own work unless a
contributor agreement says otherwise.

Three properties of this project drive the decision. It is a **framework meant to be embedded** in
other people's applications, so a copyleft license would put the linking and derivative-work
question in the path of every user. It ships an **AI provider adapter**, so patent exposure is a
live consideration rather than a theoretical one. And **every dependency is permissively licensed**
(MIT and BSD-3-Clause), so either permissive family is compatible with the stack.

## Decision

**The project is licensed under the Apache License, Version 2.0.**

The choice over MIT is the express patent grant in section 3 and its termination clause: MIT grants
no patent rights at all, and a framework that integrates with model providers is exactly where a
contributor's patent position should be stated rather than implied. Apache-2.0 is also the license
most corporate contribution policies accept without discussion, which matters more for a framework
that wants corporate contributors than the shorter text of MIT would.

**The license is declared in metadata, not only in a file.** `pyproject.toml` carries the SPDX
expression `license = "Apache-2.0"` and `license-files = ["LICENSE"]`, the repository root carries
the verbatim license text, and the built wheel ships the text under `licenses/` with
`License-Expression: Apache-2.0` in its metadata. Verified, not assumed: the metadata is produced
correctly by hatchling 1.25.0, the oldest version `[build-system] requires` allows, so the declared
build floor did not have to move.

**No per-file license headers, and no `NOTICE` file.** The Apache-2.0 appendix suggests a header per
file; with 125 files that is noise, and the license and metadata are the normative record. A `NOTICE`
file exists to carry required attribution, and there is nothing to attribute yet.

**Contributor terms are deliberately still open.** Contributions are accepted on the basis that the
contributor licenses them under Apache-2.0 (inbound equals outbound), which is the minimum needed to
distribute them. A Contributor License Agreement or copyright assignment has **not** been adopted,
and that has a consequence worth stating plainly: without one, the project cannot relicense later
without every contributor's consent. That is an accepted trade-off for now, not an oversight, and it
belongs to the project owner to revisit before outside contributions arrive in volume.

## Consequences

- Distributors must include the license text and state significant modifications, and must not imply
  endorsement; the license grants copyright and patent rights but **no trademark rights**, so
  protecting the project name is a separate policy rather than something Apache-2.0 provides.
- The license classifiers (`License :: OSI Approved :: ...`) are deprecated by PEP 639 in favour of
  the SPDX expression, so none are declared. A `License ::` classifier added alongside
  `license = "Apache-2.0"` would be redundant and is rejected by newer packaging tooling.
- Relicensing requires the consent of every copyright holder. Adopting a CLA later cannot
  retroactively cover contributions already made, so the window in which the license is cheap to
  change closes with the first outside contribution. This is the one consequence with a deadline
  attached.
- Contributions carry no warranty and no support obligation, which matches the project's
  pre-`1.0.0` preview status rather than contradicting it.
- AI-generated and third-party code contributed to the project inherits the same terms; the project
  makes no claim to provenance it cannot verify, and the review convention in `CONTRIBUTING.md` is
  what keeps that honest.
