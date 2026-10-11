# Release guide

> Status: Phase 7. Nothing has been released yet. This page is the procedure for the first release
> and for every one after it, the deployment plan for the index it publishes to, and the audit results
> it rests on.

The project is at `0.0.0`, which is a placeholder: the first release of this line will be
**`2.0.0`**, because the `xyberos` name is held on the package index by the already-published 1.x line.
The versioning rules that make that the right number are in [the stability guide](./stability.md), and
the decision itself is [ADR 0017](./adr/0017-release-identity-and-lineage.md).

## What a release is, here

A release is a tag, an artefact, a changelog entry, and evidence that the artefact installs and runs.
Nothing is published automatically: the [release decision gate](./implementation.md#phase-7---developer-experience-hardening-and-release)
is signed off by the project owner first, and a release that fails an artefact check is not published
at all rather than published with a caveat.

## Before the tag

1. **Move the changelog.** `CHANGELOG.md` has an `Unreleased` section. Rename it to the version and
   date (`2.0.0` for the first release of this line), and open a new empty `Unreleased` section above
   it. The entry's first line states that `2.0.0` is not compatible with the published 1.x line, so a
   reader learns that before they read the features.
2. **Bump the version in all six places.** Two carry it — `version` in
   [pyproject.toml](../pyproject.toml) and `__version__` in
   [src/xyberos/\_\_init\_\_.py](../src/xyberos/__init__.py) — and four tests pin the placeholder
   literally: `tests/test_package.py`, `tests/test_public_api.py`, `tests/test_compatibility.py`, and
   `tests/cli/test_cli.py`. The four pins are deliberate: they make the bump a reviewed diff instead
   of a silent string change, and they fail loudly when one of the first two is missed.
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

6. **Update what publication makes false.** Three places say the framework is not published: the
   prerequisites note in [the tutorial](./tutorial.md), the install section in
   [getting started](./getting-started.md), and the comment above the generated project's dependency
   in [src/xyberos/cli/scaffold.py](../src/xyberos/cli/scaffold.py). Replace the checkout instructions
   with the published command, then run the gate below, because the tutorial's output blocks and
   `tests/integration/test_tutorial.py` are what keep that page honest.
7. **Confirm the gate.** Every row of the release decision gate in
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

The upload itself, and the checks that only make sense once a release is on the index, are below.

## Deploying to PyPI

> Status: planned, never performed. The source changes, the repository, and the publishing workflow are
> in place; what remains before the first upload is a trusted publisher registered on the index, which
> only a project owner can do. Nothing here reopens the number:
> [ADR 0017](./adr/0017-release-identity-and-lineage.md) decides that, and this section exists so the
> decision survives contact with the index.

### Preconditions

The distribution name is not a choice to be made. `xyberos` is held on PyPI by this project's 1.x
line — 16 releases from `0.4.0` to `1.0.3`, the newest uploaded 2026-08-17 — and an index does not
re-register a name that has releases. The first upload is therefore not a new project but a release of
an existing one, which is why these four things come first.

| # | Precondition | Why it blocks | How to confirm |
| --- | --- | --- | --- |
| 1 | An owner of the PyPI project `xyberos` registers the trusted publisher below | Only a project owner can add one, and without it the publish job fails on authentication with nothing to fall back on: there is no second name, and no token is kept | Sign in to PyPI, open the project's *Publishing* settings, and add the publisher with the exact values in [The publishing workflow](#the-publishing-workflow) |
| 2 | The repository this line publishes from — **`https://github.com/xyberos/xyberos2.0`**, default branch `master` | The declared project URLs, the README's links, and a trusted publisher all bind to it, so the URL and the branch name have to be settled before the metadata is written | `git rev-parse master origin/master` matches, and every declared URL resolves — see [Preparing the repository](#preparing-the-repository) |
| 3 | The publication path — **decided: trusted publishing from `.github/workflows/publish.yml`**, started by hand | The workflow authenticates with an OIDC identity and keeps no secret, so the index-side publisher has to exist before the first attempt rather than during it | See [The publishing workflow](#the-publishing-workflow) |
| 4 | The `Documentation` URL — **decided for now: the repository's own `docs/` directory** | `https://docs.xyberos.com` documents the 1.x line, so pointing this line's page at it would advertise the wrong codebase | The declared value in `[project.urls]`; it moves when the documentation site carries content for this line |

### Preparing the repository

The URL the release declares is `https://github.com/xyberos/xyberos2.0`, and it began empty. The first
plan was to overwrite the unrelated codebase that held that name; instead it was renamed to
`https://github.com/xyberos/xyberos3.0`, where it is preserved, and the name was recreated empty. That
is the better of the two: nothing is destroyed, the redirect from the old name still resolves, and this
line's history contains only its own commits — which is what a provenance attestation describes.

| | |
| --- | --- |
| Repository | `https://github.com/xyberos/xyberos2.0` |
| Default branch | `master`, which is also the local branch and the one every declared link names |
| First push | `5ebef0a`, a normal push into an empty repository rather than a force push |
| Displaced codebase | `https://github.com/xyberos/xyberos3.0`, preserved |

Two properties of that arrangement are load-bearing, and both are easy to undo by accident:

- **The branch name is load-bearing.** The README's links and the `Documentation` URL name `master`
  explicitly. Renaming the default branch to `main` later breaks all of them at once, and the project
  page keeps showing the links it can no longer resolve.
- **An empty repository is not a valid target for the declared URLs.** Until the first push lands, the
  `Repository`, `Issues`, and `Documentation` links and every link in the README resolve to a
  repository with no content, which is worse than declaring nothing at all. The push is part of
  preparing the release rather than an afterthought. All 38 URLs that the metadata and the long
  description declare were requested after the first push, and all of them resolve.

### What the upload declares

The project page is rendered from the newest release's metadata, so what the wheel carries is what
readers see. The evidence is the wheel built in [Before the tag](#before-the-tag), and
`tests/test_release_artefacts.py` is what holds the artefact to it.

- **`Project-URL` headers, which the artefact did not have.** `pyproject.toml` declares them now:
  `Repository` `https://github.com/xyberos/xyberos2.0`, and `Issues`
  `https://github.com/xyberos/xyberos2.0/issues`. Without them the Documentation, Homepage,
  Repository, and Issues links that `1.0.3` supplies are not replaced by this release — a page carries
  the newest release's metadata, so they are dropped by it.
- **`Documentation` is the one interim value.** It points at the repository's `docs/` directory rather
  than at `https://docs.xyberos.com`, which documents the 1.x line. Advertising the other line's site
  from this line's page is worse than linking the source tree, so the value moves once that site has
  content for this line.
- **Absolute links in the long description.** `readme = "README.md"` ships as
  `Description-Content-Type: text/markdown`, and a relative target in it resolves against
  `https://pypi.org/project/xyberos/` rather than the repository, so each one becomes a dead link on
  the page most readers arrive at. Thirty-five targets used to be relative — `docs/release.md`,
  `examples/hello_app/README.md`, `LICENSE`, `CHANGELOG.md` — and all of them are absolute now. The
  release-artefact test fails the build if one becomes relative again.
- **`keywords`, which were also absent.** They are an indexed search field, and the same edit fills
  them.

### The publishing workflow

Publication runs through [.github/workflows/publish.yml](../.github/workflows/publish.yml) and uses
trusted publishing: the run authenticates with GitHub's OIDC token and stores no credential, so there
is no token to rotate and none to leak. A project-scoped API token would work too and needs no
index-side configuration, but it buys nothing this pipeline needs in exchange for a long-lived secret
to protect.

The workflow is started by hand and takes two inputs: the version that is already tagged `v<version>`,
and the index. It checks out the tag, refuses to continue unless the request, the source, and the
changelog all name the same version, verifies the metadata with `twine check --strict`, installs the
built wheel and asks it its version, and only then uploads — with a signed provenance attestation for
each file, which the publisher produces by default under trusted publishing. It does not repeat the
test suite, because `ci.yml` already runs it on every push to the default branch; the gate this
workflow adds is that the artefact agrees with what it claims to be.

**The publisher registered on the index has to match this file exactly.** A mismatch is the failure
that looks like a broken login rather than a configuration error:

| Field | PyPI | TestPyPI |
| --- | --- | --- |
| Project name | `xyberos` | `xyberos` |
| Owner | `xyberos` | `xyberos` |
| Repository | `xyberos2.0` | `xyberos2.0` |
| Workflow | `publish.yml` | `publish.yml` |
| Environment | `pypi` | `testpypi` |

PyPI already has the project, so the publisher is added to it. TestPyPI does not, so it takes a
*pending* publisher — the same form, which creates the project on the first successful upload.

Two settings outside the repository are what make "publishing is a decision" something the pipeline
enforces rather than something everyone has to remember:

- **Required reviewers on the `pypi` environment.** The run pauses for a person, which is the release
  gate expressed in the pipeline instead of in a document.
- **`id-token: write` on the publishing job alone.** The build job holds `contents: read` and no token
  permission, so a compromised build step cannot mint an upload identity for itself.

### The first upload

1. **Rehearse on TestPyPI.** Start `Publish` with `version` set to the version and `index` set to
   `testpypi`. `xyberos` is unclaimed there, so it is free to use, and the run covers the mechanics end
   to end: build from the tag, the consistency checks, `twine check`, the wheel install, the upload, and
   the attestation.

   It does not cover the thing that matters most here: TestPyPI has no `1.0.3`, so it cannot show that
   `2.0.0` outranks the published line. Only the real index can answer that.
2. **Publish.** Start the workflow again with `index` set to `pypi`; this is the run the environment's
   reviewer approves. The build job uploads the sdist and the wheel together, so no index state can
   resolve a version for which only half an artefact exists.
3. **Check resolution, not just installation.** From an empty environment:

   ```powershell
   python -m pip index versions xyberos
   python -m pip install xyberos
   ```

   `2.0.0` must be the newest version listed and the install must land on it rather than on `1.0.3`.
   An unconstrained install is the only check that distinguishes "published" from "reachable", and it
   is the check a name collision breaks silently.
4. **Re-run the clean-install smoke test against the index** rather than against a local wheel, with
   the same expectation: `xyberos --version` reports `2.0.0`, and installing the extras resolves the
   optional dependencies from the published metadata.
5. **Record the resolution check in the release notes** as the evidence that the collision resolved
   the intended way, and attach the SBOM alongside the artefacts.

## Releasing beside the published 1.x line

`xyberos` is already published at `1.0.3` by this project, and it is a different codebase
([ADR 0017](./adr/0017-release-identity-and-lineage.md)). Publishing `2.0.0` changes nothing about it:
the old release is neither edited nor yanked, and an environment that pins it keeps working.

- **What a 1.x user sees.** Their next unconstrained upgrade moves them to a rewrite. The changelog
  entry says so in its first line, and the README says it where they arrive.
- **What the satellite distributions are told by their own metadata.** The 23 satellites named in
  [ADR 0017](./adr/0017-release-identity-and-lineage.md) require the core with an open upper bound:
  `xyberos-auth` `0.1.1`, `xyberos-db` `0.1.1`, and `xyberos-mcp` `0.2.1` all declare `xyberos>=1.0`.
  After the upload, `pip install xyberos-auth` resolves the core to `2.0.0`, whose `xyberos.runtime`
  and `xyberos.plugins` are unrelated to what those packages were written against, and the install
  breaks with no version conflict to warn anyone. Repin them to `xyberos>=1.0,<2` and publish those
  patches in the same window as the upload. This is the part of the upgrade that documentation cannot
  fix, because a resolver is not a reader.
- **What to tell them.** A project that depends on the 1.x API should pin `xyberos<2`; a project that
  wants this line installs `xyberos>=2` into a clean environment rather than upgrading in place.
- **What could soften the upgrade instead of only documenting it.** A final patch on the 1.x line — a
  new upload rather than an edit to a published release — that warns on import and points at this line
  would reach users who never read a changelog. It is optional, it belongs to the other repository,
  and it works against the frozen state ADR 0017 records for that line.
- **What cannot be fixed.** The two lines install the same import root (`xyberos`) and define
  `xyberos.runtime` and `xyberos.plugins` differently, so one environment holds one or the other. No
  packaging trick changes that; a project that needs both runs two environments.
- **What the index does with the name.** The project page, its description, and its classifiers become
  this line's. That is intended: one name, one current line, with the previous one still installable.
  The Documentation link is the exception, and it is the one part of the page this release does not
  improve — see precondition 4 above.

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
- **No separate attestation step.** `pypa/gh-action-pypi-publish` signs an attestation for every file it
  uploads, using the same OIDC identity it authenticates with, so provenance comes from the publish run
  rather than from a job this repository has to maintain. What it does not replace is the human gate: an
  attestation says where an artefact came from, not that anyone checked the release rows.
