"""Build the site: the generated pages first, then MkDocs.

One command rather than three, because the navigation names two generated pages — ``roadmap.md`` and
everything under ``reference/`` — and a bare ``mkdocs build`` in a fresh clone would fail on files
that are not supposed to exist yet.

    python site/scripts/build.py            # build
    python site/scripts/build.py --serve    # build, then serve with reload
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import matrix
import reference
import roadmap
import snippets_hook

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

#: The schema the package ships, and the address its own `$id` names. The site publishes a copy so
#: an editor handed the `$id` can fetch it; the copy is made from the shipped file rather than
#: regenerated, so there is one source and the test that pins the shipped file covers both.
SCHEMA_SOURCE = REPOSITORY_ROOT / "src" / "xyberos" / "config.schema.json"
SCHEMA_PUBLISHED = REPOSITORY_ROOT / "site" / "schema" / "xyberos-config-1.json"


def publish_schema() -> int:
    """Copy the configuration schema to the URL its `$id` names, and report a missing one."""
    if not SCHEMA_SOURCE.exists():
        print(f"site: {SCHEMA_SOURCE.name} is missing; run `xyberos check --schema > it` first")
        return 1
    SCHEMA_PUBLISHED.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PUBLISHED.write_bytes(SCHEMA_SOURCE.read_bytes())
    print(f"site: published {SCHEMA_PUBLISHED.relative_to(REPOSITORY_ROOT).as_posix()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Generate, then build or serve."""
    parser = argparse.ArgumentParser(description="Generate the site's pages and build it.")
    parser.add_argument(
        "--serve", action="store_true", help="serve with reload instead of building"
    )
    parser.add_argument("--check", action="store_true", help="validate the pages before building")
    parser.add_argument(
        "--site-url",
        default=None,
        help="override `site_url` for one build, which is how a preview publishes under its URL",
    )
    args = parser.parse_args(argv)

    if args.check:
        # Before anything writes: a stale inventory has to fail the build, not be repaired by it.
        for check in (matrix.main, roadmap.main):
            code = check(["--check"])
            if code != 0:
                return code

    for step in (matrix.main, roadmap.main):
        code = step([])
        if code != 0:
            return code

    code = reference.main()
    if code != 0:
        return code

    code = publish_schema()
    if code != 0:
        return code

    command = ["mkdocs", "serve" if args.serve else "build", "--strict"]
    environment = dict(os.environ)
    if args.site_url is not None:
        # `mkdocs.yml` reads `SITE_URL`, so one build can publish under a preview URL without a
        # second configuration file drifting from the first.
        environment["SITE_URL"] = args.site_url
    print(f"site: {' '.join(command)}")
    code = subprocess.call(command, cwd=REPOSITORY_ROOT, env=environment)
    if code != 0 or args.serve:
        return code

    unrendered = snippets_hook.unrendered_pages(snippets_hook.output_directory())
    for page in unrendered:
        print(f"site: {page.relative_to(REPOSITORY_ROOT).as_posix()} keeps a snippet marker")
    if unrendered:
        return 1
    print("site: every snippet marker rendered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
