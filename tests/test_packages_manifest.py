"""`packages.toml` is the single source for the packages that live outside this repository.

Three documents are checked against it — the plugin guide's catalogue, the feature matrix, and the
release guide — because a hand-maintained list is what Phase 8 shipped for a repository with no
packages in it, and a published ecosystem needs a checked one. The rules ADR 0018 states are
asserted here rather than left to review: an import root is the package's own top-level module, and
every published name is this project's own.
"""

from __future__ import annotations

import re
from pathlib import Path

import ecosystem
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "packages.toml"
CATALOGUE = ROOT / "docs" / "plugins.md"
FEATURE_MATRIX = ROOT / "site" / "feature-support.md"
RELEASE_GUIDE = ROOT / "docs" / "release.md"

MANIFEST_DATA = ecosystem.load(MANIFEST)
ENTRIES = ecosystem.packages(MANIFEST_DATA)
LIVE = [entry for entry in ENTRIES if entry.get("status") != "retired"]


def names() -> set[str]:
    return {str(entry["name"]) for entry in ENTRIES}


def test_the_manifest_declares_a_schema_version_this_tool_understands() -> None:
    assert MANIFEST_DATA["schema_version"] == ecosystem.SCHEMA_VERSION


def test_every_entry_declares_what_a_reader_and_the_job_need() -> None:
    for entry in ENTRIES:
        for field in ("name", "import_root", "status", "summary", "rationale"):
            assert entry.get(field), f"{entry.get('name')!r} declares no {field}"
        # Not truthiness: a retired name's empty dependency list *is* the statement that it pulls
        # nothing.
        assert "dependencies" in entry, f"{entry['name']!r} declares no dependencies"
        assert entry["status"] in ecosystem.STATUSES, f"{entry['name']!r} has an unknown status"
        if entry["status"] == "retired":
            assert entry.get("replaced_by"), f"{entry['name']!r} is retired and points nowhere"


def test_every_status_the_manifest_may_use_is_defined_where_the_manifest_is_read() -> None:
    """The vocabulary is code and the definitions are prose, so the two have to be kept in step.

    A status is a claim about the index — written, published, retired — and a reader who has to
    guess what one means is reading a word rather than a fact. The count in the same sentence is
    checked too, because "one of four values" left standing beside five of them is how this drifted
    the first time.
    """
    header = MANIFEST.read_text(encoding="utf-8")

    for status in ecosystem.STATUSES:
        assert f"`{status}`" in header, f"packages.toml never defines {status!r}"

    counted = re.search(r"`status` is one of (\w+) values", header)
    assert counted, "packages.toml does not say how many statuses there are"
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
    declared = words[counted.group(1)]
    assert declared == len(ecosystem.STATUSES), (
        f"the header says {counted.group(1)} statuses "
        f"and the tool defines {len(ecosystem.STATUSES)}"
    )


def test_a_package_owns_its_own_import_root_and_never_a_path_inside_the_core() -> None:
    """ADR 0018, and the reason it is a rule: two distributions under `xyberos/` cannot be
    uninstalled.
    The rule is about the *package* `xyberos`, not about the prefix: `xyberos_mcp` is a separate
    top-level module, which is exactly what is wanted, while `xyberos.mcp` would be a path inside a
    directory two distributions would then share.
    """
    for entry in ENTRIES:
        root = str(entry["import_root"])
        assert root.isidentifier(), (
            f"{entry['name']!r} declares {root!r}, which is not an import name"
        )
        assert root != "xyberos" and not root.startswith("xyberos."), (
            f"{entry['name']!r} claims {root!r}, which is inside the core package's namespace"
        )


def test_every_name_this_line_publishes_is_recognizably_this_project_s_own() -> None:
    for entry in ENTRIES:
        assert str(entry["name"]).startswith("xyberos-"), str(entry["name"])


def test_every_package_beside_this_line_declares_the_same_core_range() -> None:
    requirement = ecosystem.core_requirement(MANIFEST_DATA)
    assert requirement.startswith("xyberos>=2,<3"), requirement


def test_the_compatibility_job_installs_exactly_what_the_manifest_publishes() -> None:
    """Published is a status in the manifest, not a guess: the job installs exactly this list.

    Deliberately silent about how long the list is. Its earlier form asserted the list was *empty*, which
    was true before the first release and became the reason nothing noticed when seven landed.
    """
    published = ecosystem.published(MANIFEST_DATA)
    jobs = ecosystem.published_jobs(MANIFEST_DATA)

    assert published == [str(entry["name"]) for entry in ENTRIES if entry["status"] == "published"]
    assert [job["name"] for job in jobs] == published, "the matrix is the published list, in order"


def test_every_conformance_target_has_one_of_the_two_documented_shapes() -> None:
    """A provider runs a suite this line ships; a package with no seam checks what it can."""
    for job in ecosystem.published_jobs(MANIFEST_DATA):
        snippet = job["conformance"]
        provider = "import sys; from" in snippet and "sys.exit(main())" in snippet
        self_check = "import xyberos" in snippet and "assert " in snippet
        assert provider or self_check, (
            f"{job['name']} declares neither documented shape: {snippet!r}"
        )


def test_a_published_package_without_a_conformance_target_is_refused() -> None:
    """Published plus installed plus unchecked is worse than not published at all."""
    fabricated = {
        "core_requirement": "xyberos>=2,<3",
        "package": [{"name": "xyberos-x", "status": "published"}],
    }
    with pytest.raises(SystemExit, match="without a conformance target"):
        ecosystem.published_jobs(fabricated)


def test_the_compatibility_workflow_gates_its_matrix_instead_of_writing_one_out() -> None:
    """A matrix cannot be empty: GitHub Actions errors on one rather than skipping it."""
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "compatibility.yml").read_text("utf-8")
    )
    jobs = workflow["jobs"]
    manifest = jobs["manifest"]

    echoed = [step.get("run", "") for step in manifest["steps"]]
    assert any("tools/ecosystem.py --github-output" in run for run in echoed), (
        "the matrix is derived from the manifest, not from a list in the workflow"
    )
    assert any("Nothing published yet" in run for run in echoed), (
        "an empty package list has to be announced rather than skipped in silence"
    )

    packages = jobs["packages"]
    assert packages["if"].strip() == "needs.manifest.outputs.packages != '[]'"
    assert "fromJSON(needs.manifest.outputs.packages)" in packages["strategy"]["matrix"]["package"]
    assert any("matrix.package.conformance" in step.get("run", "") for step in packages["steps"])

    # The core leg is what runs today: the published core, from the index, not from a checkout.
    core_installs = [step.get("run", "") for step in jobs["core"]["steps"]]
    assert any(
        "pip install" in run and "needs.manifest.outputs.core" in run for run in core_installs
    ), "the core leg installs what the index serves"
    assert not any("pip install -e" in run or "dist/" in run for run in core_installs), (
        "installing a local build here would duplicate the installed-artefact job and prove nothing"
    )


def test_the_plugin_guide_catalogue_names_every_package_and_invents_none() -> None:
    catalogue = CATALOGUE.read_text(encoding="utf-8")
    for name in sorted(names()):
        assert f"`{name}`" in catalogue, f"{name} is missing from the catalogue"

    mentioned = set(re.findall(r"`(xyberos-[a-z0-9-]+)`", catalogue))
    assert mentioned <= names(), (
        f"the catalogue names packages the manifest does not know: {mentioned - names()}"
    )


def test_the_feature_matrix_says_where_each_package_lives() -> None:
    matrix = FEATURE_MATRIX.read_text(encoding="utf-8")
    for name in sorted(names()):
        assert f"`{name}`" in matrix, f"{name} is not placed anywhere in the feature matrix"


def test_the_release_guide_points_every_retired_name_at_its_replacement() -> None:
    guide = RELEASE_GUIDE.read_text(encoding="utf-8")
    for entry in ENTRIES:
        if entry["status"] != "retired":
            continue
        assert f"`{entry['name']}`" in guide, (
            f"{entry['name']} is not discussed in the release guide"
        )
        assert str(entry["replaced_by"]) in guide, (
            f"the release guide does not say what replaced {entry['name']!r}"
        )


def test_the_catalogue_tells_a_reader_which_packages_are_the_project_s_own() -> None:
    """A curated list is not an endorsement, so the page has to say which rows are ours."""
    catalogue = CATALOGUE.read_text(encoding="utf-8").lower()
    assert "published by this project" in catalogue
    assert "community" in catalogue


def test_no_package_is_marked_published_before_it_has_a_conformance_story() -> None:
    """A published row is what the compatibility job installs, so it must not be aspirational."""
    for entry in ENTRIES:
        if entry["status"] != "published":
            continue
        assert entry.get("conformance"), (
            f"{entry['name']!r} is published without a conformance target for the job to run"
        )
