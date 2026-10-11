# Release guide

> Status: Phase 7. Nothing has been released yet. This page is the procedure for the first release
> and for every one after it, plus the audit results it rests on.

The project is at `0.0.0`, which is a placeholder: the first release will be **`0.1.0`**, and the
versioning rules that make that the right number are in [the stability guide](./stability.md).

## What a release is, here

A release is a tag, an artefact, a changelog entry, and evidence that the artefact installs and runs.
Nothing is published automatically: the [release decision gate](./implementation.md#phase-7---developer-experience-hardening-and-release)
is signed off by the project owner first, and a release that fails an artefact check is not published
at all rather than published with a caveat.

## Before the tag

1. **Move the changelog.** `CHANGELOG.md` has an `Unreleased` section. Rename it to the version and
   date, and open a new empty `Unreleased` section above it.
2. **Bump the version in both places.** There are exactly two, and both are checked by tests:
   `version` in [pyproject.toml](../pyproject.toml), and `__version__` in
   [src/xyberos/\_\_init\_\_.py](../src/xyberos/__init__.py). `tests/test_compatibility.py` pins the
   second one, so bumping only one of them fails the suite rather than shipping a lie.
3. **Run the full gate.** From a clean environment:

   ```powershell
   python -m pip install -e ".[dev,http,database]"
   python -m pip install --no-deps -e tests/fixtures/metrics_plugin
   python -m pytest
   ruff check src tests examples
   ruff format --check src tests examples
   mypy
   python -m build
   ```

4. **Run the artefact checks.** `tests/test_release_artefacts.py` builds the wheel and sdist and
   asserts what they must contain, so step 3 already covers this. The assertions are about things
   that have gone wrong here before: missing `py.typed`, stale text embedded in `METADATA`, a licence
   file that does not ship, an entry point that is not declared, and paths that are wrong for a
   `src` layout.
5. **Run the clean-install smoke test**, which is the one check that must happen *outside* the
   checkout:

   ```powershell
   python -m build
   python -m venv .smoke
   .smoke\Scripts\python -m pip install dist\xyberos-<version>-py3-none-any.whl
   .smoke\Scripts\xyberos --version
   .smoke\Scripts\xyberos check
   .smoke\Scripts\xyberos new smoke --directory .
   .smoke\Scripts\xyberos check --app smoke.app:create_app --app-dir smoke\src
   .smoke\Scripts\python -m pip install "starlette>=0.40,<1" "httpx>=0.27,<1"
   .smoke\Scripts\xyberos check --app smoke.app:create_app --app-dir smoke\src
   ```

   The step before the extras are installed must fail with a message naming `xyberos[http]`; the step
   after must report `provider graph: valid` and a route count. That pair is the check that the
   optional-dependency story is true for an artefact, not only for a checkout. CI runs the same
   sequence in the `installed-artefact` job.

6. **Confirm the gate.** Every row of the release decision gate in
   [implementation.md](./implementation.md) has evidence, and the open owner decisions listed under
   "Remaining owner decisions" are either decided or explicitly deferred with a trigger.

## Dependency and licence audit

The framework's only unconditional requirement is `tomli` on Python 3.10, and the standard library's
`tomllib` above it. Everything else is an extra, and the closures below were computed from installed
distribution metadata rather than from the declarations alone, because a transitive dependency is
still a dependency. To reproduce one, install the extra into an empty environment and list what
arrived:

```powershell
python -m venv .audit
.audit\Scripts\python -m pip install -e ".[http,database]"
.audit\Scripts\python -m pip list
```

| Extra | Installed closure | Licences |
| --- | --- | --- |
| core | *(none beyond the package; `tomli` on 3.10)* | — |
| `http` | `starlette`, `httpx`, `anyio`, `certifi`, `h11`, `httpcore`, `idna`, `typing_extensions` | BSD-3-Clause, MIT, MPL-2.0, PSF-2.0 |
| `database` | `sqlalchemy`, `aiosqlite`, `alembic`, `Mako`, `MarkupSafe`, `greenlet`, `typing_extensions` | MIT, BSD-3-Clause, PSF-2.0 |
| `ollama` | `httpx`, `anyio`, `certifi`, `h11`, `httpcore`, `idna`, `typing_extensions` | BSD-3-Clause, MIT, MPL-2.0, PSF-2.0 |
| `durable` | the `database` closure | as `database` |

Every licence is permissive or weak-copyleft and compatible with distributing Xyberos under
Apache-2.0. Two details are worth knowing rather than assuming:

- **`certifi` is MPL-2.0**, a file-level copyleft. It is a transitive dependency of `httpx` and is not
  modified here, which is what MPL-2.0 requires; it is listed because it is the one licence in the
  set that is not permissive.
- **The floors are what move.** Every range has a floor, and only two have a ceiling
  (`sqlalchemy>=2.0,<2.1`, `httpx>=0.27,<1`, because the next major is where a breaking change lands).
  A newer release inside a range is reachable by resolution, so fixing a vulnerable dependency means
  moving its floor, not rewriting the cap.

There is no `NOTICE` file: nothing in the dependency set requires one, and Apache-2.0 requires it only
when the work itself carries notices.

### Software bill of materials

Xyberos does not generate an SBOM at build time, because an SBOM describes *an installed
environment*, not a wheel, and pinning one into the artefact would be a snapshot that goes stale
immediately. Generate it where the environment is known, with whatever supply-chain tooling the
deployment already uses — for example `pip install cyclonedx-bom` and
`cyclonedx-py environment --output-format json --outfile sbom.json` in the release environment — and
attach it to the release. The table above is the minimum evidence and is regenerated by the command
above.

## Publishing

1. Tag the commit `v<version>` and push the tag.
2. Attach the wheel, the sdist, and the SBOM to the release, with the changelog section as the
   release notes and the gate reference linking back to the evidence.
3. Verify the published artefact by installing *it* rather than the checkout, in a clean environment,
   one last time.
4. If a package index is used, confirm from a clean environment that resolution picks the release
   rather than a newer pre-release.

## Rollback and withdrawal

A release is withdrawn, never edited: an artefact that has been installed anywhere cannot be corrected
in place.

- **Nothing is broken, but the release should not be the default.** Mark it as a pre-release or yank
  it on the index so new installs do not select it, and leave it downloadable so existing pins keep
  working. Then publish a patch release with the fix.
- **A release is broken in a way that makes it unsafe to run.** Yank it, publish a patch release with
  the fix, and say so in the changelog under "Security" or "Fixed" — with the impact and the affected
  versions, not just the change.
- **A release is broken in a way that cannot be fixed forward quickly.** The rollback instruction to
  users is to pin the previous version, and the changelog entry states that pin explicitly. Every
  release keeps the previous artefact available for exactly this case; that is a reason not to delete
  old releases.
- **A durable journal was written by a newer build.** Rolling the *package* back is not enough if the
  journal schema moved: the journal refuses a file newer than the package, on purpose, rather than
  opening it at the older worker's risk. In that case the rollback is a restore from the backup taken
  before the upgrade — see the journal's [backup and restore](./durable.md#backup-and-restore)
  section.

## What is deliberately not automated

- **No publish-on-tag job.** Publishing is a decision, and the evidence for it is a person confirming
  the gate rows rather than a green build.
- **No automatic version bump from commit messages.** The version number is a promise about
  compatibility, and this project's rules for it are not derivable from a commit prefix.
- **No provenance attestation yet.** It is worth adding when the release actually happens and there is
  a publishing pipeline to attach to; stating it here keeps it from being quietly assumed.
