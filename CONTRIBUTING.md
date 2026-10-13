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

Run the same loop CI runs, in the same order. `tests/test_contributor_loop.py` compares this list
with the workflow, so a step added to one and not the other fails a test rather than the build.

```powershell
python site/scripts/build.py --check
python -m pytest
ruff check src tests examples site/scripts tools
ruff format --check src tests examples site/scripts tools
mypy
python -m build
```

Installing is the two lines the workflow runs before the loop:

```powershell
python -m pip install -e ".[dev,http,database]"
python -m pip install --no-deps -e tests/fixtures/metrics_plugin
```

`pre-commit install` enables the hooks in your clone, which is why the container does it for you.
From then on the two `ruff` commands in the loop run before each commit, where they are cheapest.

The site build comes first on purpose: two pages under `site/` are generated from `docs/`, and
`tests/site/` verifies the rendered reference against `docs/`, so building after the tests would
report a failure from the previous run's output. `tests/fixtures/metrics_plugin` is installed without
dependencies so that the local copy, rather than a published one, is what the tests import.
New stable public APIs require an architecture decision record or an update to an existing one, an
API-contract example, type coverage, and a compatibility/release-note entry when applicable.

## Compatibility

The package is at `2.0.0`; a change to a documented stable name requires a major release. Do
not describe a preview API as stable. The tiers and the rules are in
[`docs/stability.md`](docs/stability.md) and [ADR 0013](docs/adr/0013-stable-surface-and-versioning.md).

Adding or removing a public name is a visible change to `tests/test_public_surface.py`, and a change
to configuration fields, the plugin protocol, or serialized Workflow metadata is a visible change to
`tests/test_compatibility.py`. If you meant it, edit those tests in the same change; if you did not,
the test is telling you that you have altered the public API by accident.

Prefer deprecating over removing. Use `xyberos.deprecation.warn_deprecated` or the `deprecated`
decorator, name the replacement, and state the release that will remove it. A deprecated path keeps
working for at least one minor release after the announcement.
