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

> Status: planned, never performed. The metadata and README changes below are already in the source;
> what remains before the first upload is the repository replacement, an index credential, and the two
> open rows in the preconditions table. Nothing here reopens the number:
> [ADR 0017](./adr/0017-release-identity-and-lineage.md) decides that, and this section exists so the
> decision survives contact with the index.

### Preconditions

The distribution name is not a choice to be made. `xyberos` is held on PyPI by this project's 1.x
line — 16 releases from `0.4.0` to `1.0.3`, the newest uploaded 2026-08-17 — and an index does not
re-register a name that has releases. The first upload is therefore not a new project but a release of
an existing one, which is why these four things come first.

| # | Precondition | Why it blocks | How to confirm |
| --- | --- | --- | --- |
| 1 | The uploading account owns or maintains the PyPI project `xyberos` | An upload from any other account is refused as "not allowed to upload to this project", and there is no second name to fall back to | Sign in to PyPI and read the project's *Collaborators* and *Publishing* settings; the account behind the credential must be listed |
| 2 | The repository this line publishes from — **decided: `https://github.com/xyberos/xyberos2.0`** | The declared project URLs, the README's links, and a trusted publisher all bind to it, and it currently holds unrelated commits, so the local line still has to replace them | See [Preparing the repository](#preparing-the-repository) |
| 3 | The upload mechanism and its credential exist | Publishing is manual by design, so the token or the index-side publisher has to be created before the first attempt rather than during it | See [Choosing the upload mechanism](#choosing-the-upload-mechanism) |
| 4 | The fate of `https://docs.xyberos.com` — **still open** | The 1.x page publishes it as its Documentation link, and it documents the 1.x line; after the upload the project page is this line's while that link still points at the other one | A decision, not a check. Until it is made, the declared `Documentation` URL is the repository's own `docs/` directory |

### Preparing the repository

The URL the release declares is `https://github.com/xyberos/xyberos2.0`, and it is not empty. It holds
an unrelated codebase — `README.md`, `ARCHITECTURE.md`, `REVIEW.md`, `TUTORIAL.md`, an `apps/`
directory, and a `xyberos/` package at the root instead of `src/xyberos` — with five commits of its
own. The two histories share no ancestor, so this line cannot be pushed onto it as a fast-forward, and
a merge would produce a tree that is neither project.

1. **Archive what is there first, if it is worth keeping.** Clone it, or push its `master` to a branch
   or tag within the same repository. The next step replaces it, and the index is not a backup.
2. **Add the remote and replace the content.** `git remote add origin` with the declared URL, then
   `git push --force origin master`. A force push is the right tool exactly here: the histories are
   unrelated and there is nothing to preserve by merging.
3. **Confirm the declared links resolve.** The default branch is `master`, and the `Repository`,
   `Issues`, and documentation URLs declared below, plus every link in the README, point at it. A URL
   that 404s is worse than an absent one, because the page still shows the link.

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
  from this line's page is worse than linking the source tree, so the value moves when precondition 4
  is settled.
- **Absolute links in the long description.** `readme = "README.md"` ships as
  `Description-Content-Type: text/markdown`, and a relative target in it resolves against
  `https://pypi.org/project/xyberos/` rather than the repository, so each one becomes a dead link on
  the page most readers arrive at. Thirty-five targets used to be relative — `docs/release.md`,
  `examples/hello_app/README.md`, `LICENSE`, `CHANGELOG.md` — and all of them are absolute now. The
  release-artefact test fails the build if one becomes relative again.
- **`keywords`, which were also absent.** They are an indexed search field, and the same edit fills
  them.

### Choosing the upload mechanism

| Mechanism | What it needs | What it costs |
| --- | --- | --- |
| Project-scoped API token, with `twine` | A token created on the project and stored outside the checkout; `python -m pip install twine`, which the `dev` extra does not include | Nothing configured on the index and no workflow to maintain; a long-lived secret to rotate and to keep out of the repository |
| Trusted publishing, with `pypa/gh-action-pypi-publish` | A publisher on the project bound to the repository, the workflow file, and an environment, plus a `workflow_dispatch` job | No long-lived secret, and provenance attestations come with it; a workflow that exists to upload an artefact some other run built |

Both keep publishing a decision, which is what [What is deliberately not
automated](#what-is-deliberately-not-automated) requires: a tag starts a build, never an upload. The
first release is the one case where the token path is simpler, because there is no pipeline yet for an
attestation to attach to.

### The first upload

1. **Rehearse on TestPyPI.** `xyberos` is unclaimed there, so it is free to use, and the rehearsal
   covers the mechanics:

   ```powershell
   python -m build
   python -m pip install --upgrade twine
   python -m twine check dist/*
   python -m twine upload --repository testpypi dist/*
   ```

   It does not cover the thing that matters most here: TestPyPI has no `1.0.3`, so it cannot show that
   `2.0.0` outranks the published line. Only the real index can answer that.
2. **Upload the sdist and the wheel together.** `python -m twine upload dist/*`, after the version is
   bumped in all six places and the changelog is renamed. Uploading one without the other leaves the
   index able to resolve a version for which only half an artefact exists.
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
- **No provenance attestation yet.** It is worth adding when the release actually happens and there is
  a publishing pipeline to attach to; stating it here keeps it from being quietly assumed.
