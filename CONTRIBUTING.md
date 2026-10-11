# Contributing to Xyberos

## Licensing of contributions

Xyberos is licensed under the [Apache License 2.0](LICENSE). By contributing, you agree that your
contribution is licensed under the same terms (inbound equals outbound), which is the minimum needed
for the project to distribute it.

**No Contributor License Agreement or copyright assignment is in place yet.** That has a consequence
worth knowing before you contribute: without one, the project cannot change its license later without
the consent of every copyright holder. If you are contributing on behalf of an employer, check that
you may, and tell us if your employer's policy requires a signed agreement — that is the signal that
this decision needs revisiting. It is recorded as open in
[ADR 0012](docs/adr/0012-project-licence.md).

Do not copy code into this project that you cannot license under these terms. If you adapt code from
another project, its license must be compatible and the provenance must be stated in the commit
message and, where the license requires it, in the repository.

## Development rules

- Target Python 3.10 or newer and keep the public package fully typed.
- Keep optional capabilities out of `xyberos` core imports.
- Import an extra's dependencies only inside the module of that extra, wrapped so a missing package
  names the extra to install (`src/xyberos/_extras.py`). A bare `ModuleNotFoundError` for a package
  the user never asked for by name is a bug, not a configuration error.
- Add or update tests and tested documentation examples with every behavior change.
- Do not add an abstraction until the public contract and a concrete use case justify it.
- Keep secrets, prompts, and unbounded payloads out of logs and test fixtures.

## Before submitting a change

Run the commands in the README. New stable public APIs require an architecture decision
record or an update to an existing one, an API-contract example, type coverage, and a
compatibility/release-note entry when applicable.

## Compatibility

The package starts at `0.0.0`; breaking changes may occur in a `0.x` minor release only
with upgrade notes. Do not describe a preview API as stable. Follow the versioning policy
in `docs/implementation.md`.
