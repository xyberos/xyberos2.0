# Contributing to Xyberos

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
