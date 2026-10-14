"""The inventory on the feature-support page is derived, so it has to be checked rather than read.

The page is generated from three sources: the modules from `src/xyberos/`, the extras from
`pyproject.toml`, and the packages from `packages.toml`. That makes drift impossible *if* the
generation is right, which is what this file is for — it checks the page against the generator, and
the generator against the tree, so a broken walk cannot quietly produce an inventory that describes
nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import ecosystem
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "site" / "scripts"
if (
    str(SCRIPTS) not in sys.path
):  # `site_pages` does the same for the other checks in this directory.
    sys.path.insert(0, str(SCRIPTS))

import matrix  # noqa: E402 - the path above has to be in place first.

MODULES = matrix.modules()
EXTRAS = matrix.declared_extras()
PACKAGES = ecosystem.packages(ecosystem.load(matrix.MANIFEST))


def test_the_page_is_exactly_what_the_generator_produces() -> None:
    """The drift check: change a module, an extra, or a package, and this test notices."""
    page = matrix.PAGE.read_text(encoding="utf-8")

    assert matrix.render(page) == page


def test_the_inventory_covers_every_module_the_package_ships() -> None:
    listed = {module.path for module in MODULES}
    shipped = {
        f"xyberos.{path.name}"
        for path in matrix.CORE_ROOT.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file() and not path.name.startswith("_")
    }

    assert len(MODULES) >= 11, "the walk found almost nothing, so it is broken rather than the tree"
    assert "xyberos" in listed, "the package's own surface is a row like any other"
    assert shipped <= listed, f"missing: {sorted(shipped - listed)}"


def test_the_needs_column_is_read_from_each_package_s_own_entry_point() -> None:
    """`xyberos.ai` is core while `xyberos.ai.ollama` is not: the difference is the entry point."""
    needs = {module.path: module.extras for module in MODULES}

    assert needs["xyberos.http"] == ("http",)
    assert needs["xyberos.database"] == ("database",)
    assert needs["xyberos.durable"] == ("durable",)
    assert needs["xyberos"] == (), (
        "core imports no optional capability, which the boundary test also says"
    )
    assert needs["xyberos.ai"] == (), "the facade is core; only its Ollama adapter needs httpx"
    assert needs["xyberos.mcp"] == (), "the MCP client is stdlib-only by decision"
    assert needs["xyberos.execution"] == ()


def test_every_extra_lists_the_modules_that_guard_it() -> None:
    guarded = {
        name: sorted({module for seen in MODULES for module in seen.guarded_modules(name)})
        for name in EXTRAS
    }

    assert guarded["ollama"] == ["xyberos.ai.ollama"]
    assert guarded["http"] == [
        "xyberos.http.adapter",
        "xyberos.http.csrf",
        "xyberos.http.metrics",
        "xyberos.http.middleware",
        "xyberos.http.requests",
        "xyberos.http.routing",
        "xyberos.http.sessions",
        "xyberos.http.testing",
    ]
    assert guarded["dev"] == [], "a contributor's toolchain is not guarded for by the runtime"


def test_the_packages_table_is_the_manifest() -> None:
    rendered = matrix.render_region()
    names = [str(entry["name"]) for entry in PACKAGES]

    assert len(names) >= 7, "the manifest reader returned almost nothing"
    for name in names:
        assert f"| `{name}` |" in rendered, f"{name} is missing from the packages table"
    assert ecosystem.published(ecosystem.load(matrix.MANIFEST)) == [
        name for name, entry in zip(names, PACKAGES, strict=True) if entry["status"] == "published"
    ]


def test_a_guard_for_an_undeclared_extra_is_refused() -> None:
    """The regex and the packaging metadata have to agree, or the `Needs` column is a guess."""
    fabricated = (matrix.Module(path="xyberos.test", extras=("nope",), guards=()),)

    with pytest.raises(SystemExit, match="does not declare"):
        matrix.summarize(fabricated, EXTRAS)


def test_a_module_or_extra_without_a_summary_is_refused() -> None:
    fabricated = (matrix.Module(path="xyberos.test", extras=(), guards=()),)

    with pytest.raises(SystemExit, match="no summary for 'xyberos.test'"):
        matrix.summarize(fabricated, EXTRAS)

    with pytest.raises(SystemExit, match="no summary for 'nope'"):
        matrix.summarize((), {"nope": ()})


def test_the_markers_are_required_and_appear_once() -> None:
    with pytest.raises(SystemExit, match="exactly one"):
        matrix.render("# Feature support\n\nnothing to fill in here\n")

    twice = "\n".join(
        [
            matrix.MARKER_OPEN,
            "first",
            matrix.MARKER_CLOSE,
            matrix.MARKER_OPEN,
            "second",
            matrix.MARKER_CLOSE,
        ]
    )
    with pytest.raises(SystemExit, match="exactly one"):
        matrix.render(twice)

    reversed_page = f"{matrix.MARKER_CLOSE}\nbody\n{matrix.MARKER_OPEN}"
    with pytest.raises(SystemExit, match="before it opens it"):
        matrix.render(reversed_page)


def test_rendering_replaces_the_region_and_leaves_the_rest_alone() -> None:
    page = (
        "# Feature support\n\nIntro prose.\n\n"
        f"{matrix.MARKER_OPEN}\nstale table\n{matrix.MARKER_CLOSE}\n\n"
        "## The refusals are features\n\nAnd the tail of the page.\n"
    )

    rendered = matrix.render(page)

    assert "stale table" not in rendered
    assert matrix.render_region() in rendered
    assert rendered.startswith("# Feature support\n\nIntro prose.\n\n")
    assert rendered.endswith("## The refusals are features\n\nAnd the tail of the page.\n")


def test_checking_the_committed_page_reports_it_current() -> None:
    """What the site build runs: a stale page fails the build rather than being repaired by it."""
    assert matrix.main(["--check"]) == 0
