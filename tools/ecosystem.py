"""Read `packages.toml`, the manifest of what lives outside this repository.

The compatibility job needs two things from the manifest and nothing else: which core range to
install, and which packages are published enough to install beside it. Both are answered here rather
than in the workflow, so the selection is a tested function instead of a snippet embedded in YAML
that only a
scheduled run would ever exercise.

Usage::

    python tools/ecosystem.py --github-output >> "$GITHUB_OUTPUT"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 uses the tomli fallback.
    import tomli as tomllib

MANIFEST = Path(__file__).resolve().parents[1] / "packages.toml"
SCHEMA_VERSION = 1
STATUSES = ("placeholder", "planned", "written", "published", "retired")


def load(path: Path = MANIFEST) -> dict[str, object]:
    """Return the parsed manifest, refusing a schema version this tool does not understand."""
    with path.open("rb") as stream:
        manifest = cast("dict[str, object]", tomllib.load(stream))
    version = manifest.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SystemExit(
            f"{path} declares schema_version {version!r}; this tool understands {SCHEMA_VERSION}"
        )
    return manifest


def packages(manifest: dict[str, object]) -> list[dict[str, object]]:
    """Return the manifest's entries, in file order."""
    entries = manifest.get("package")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("the manifest declares no [[package]] entries")
    return [entry for entry in entries if isinstance(entry, dict)]


def core_requirement(manifest: dict[str, object]) -> str:
    """Return the core range every package beside this line must declare."""
    requirement = manifest.get("core_requirement")
    if not isinstance(requirement, str) or not requirement.strip():
        raise SystemExit("the manifest declares no core_requirement")
    return requirement


def published(manifest: dict[str, object]) -> list[str]:
    """Return the names the compatibility job should install and exercise.

    A name is here once a release of *this line's* content exists: a reused name that still serves a 1.x
    release is not published by this line and is not installed, because the job proves a pair rather than a
    name. An empty list is a fact about the manifest rather than a failure, which is why the caller checks
    its length instead of treating it as an error.
    """
    return [
        str(entry["name"]) for entry in packages(manifest) if entry.get("status") == "published"
    ]


def published_jobs(manifest: dict[str, object]) -> list[dict[str, str]]:
    """Return the matrix the compatibility job runs: one entry per published package.

    ``conformance`` is Python source the job runs with ``python -c``, and it comes in the two shapes the
    manifest header documents: a provider of a seam this line ships a suite for runs that suite, and a
    package that implements no such seam imports its own public names against the core it declares. An
    entry marked published without one is refused *here*: a package the job installs and does not check is
    worse than a package the job does not install at all.
    """
    jobs: list[dict[str, str]] = []
    for entry in packages(manifest):
        if entry.get("status") != "published":
            continue
        conformance = entry.get("conformance")
        if not isinstance(conformance, str) or not conformance.strip():
            raise SystemExit(
                f"{entry.get('name')!r} is published in the manifest without a conformance target"
            )
        jobs.append({"name": str(entry["name"]), "conformance": conformance})
    return jobs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report what the ecosystem manifest declares.")
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="print core=<requirement> and packages=<json list> on separate lines",
    )
    arguments = parser.parse_args(argv)
    manifest = load()

    if arguments.github_output:
        print(f"core={core_requirement(manifest)}")
        print(f"packages={json.dumps(published_jobs(manifest))}")
        return 0

    for entry in packages(manifest):
        if entry.get("status") not in STATUSES:
            raise SystemExit(f"unknown status {entry.get('status')!r} for {entry.get('name')!r}")
        print(f"{entry.get('name')}\t{entry.get('status')}\t{entry.get('import_root')}")
    return 0


if __name__ == "__main__":  # pragma: no cover - the CLI entry point
    sys.exit(main())
