"""Every lesson is a claim, and this file checks them.

The rule the site is built on: the code a lesson shows is the code the suite runs, and the claim a
lesson makes — its output, its test, or its transcript — is checked rather than trusted. A lesson
whose code is retyped instead of included fails here too.

Three ways to be checked, declared in the page's front matter:

* ``verify: output`` — run the example and compare what it printed (the default);
* ``verify: pytest`` — run the example as a test, because the lesson's subject *is* testing;
* ``verify: command`` — run the command the page quotes and compare its transcript.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import site_pages as site

LESSONS = site.lessons()
IDS = site.lesson_ids()

OUTPUT_LESSONS = site.lessons_verified_by("output")
TEST_LESSONS = site.lessons_verified_by("pytest")
COMMAND_LESSONS = site.lessons_verified_by("command")
SCAFFOLD_LESSONS = site.lessons_verified_by("scaffold")
CLAIMS = site.output_claims()


def test_the_run_guards_its_own_environment() -> None:
    """The guard is the reason a version mismatch reports as a failure and not as drift."""
    site.assert_the_checkout_under_test()


def test_there_is_at_least_one_lesson() -> None:
    """A suite over an empty set passes for the wrong reason."""
    assert LESSONS
    assert OUTPUT_LESSONS or TEST_LESSONS or COMMAND_LESSONS or SCAFFOLD_LESSONS


def test_every_example_module_is_claimed_by_a_lesson() -> None:
    """Both directions: no lesson module without a page, and no page inventing a module."""
    assert site.claimed_modules() == site.example_modules()


def test_every_output_marker_is_used_once() -> None:
    """A marker names the module it documents, so two pages claiming one name is a mistake."""
    markers = site.output_markers()
    assert len(markers) == len(set(markers)), f"an output marker is used twice: {sorted(markers)}"


def test_a_lesson_runs_its_own_example() -> None:
    """A lesson's own module is the subject of an output block, not merely included by it."""
    problems = []
    for page in OUTPUT_LESSONS:
        module = page.module
        marker = module.rsplit(".", 1)[-1] if module else ""
        if marker not in page.outputs:
            problems.append(
                f"{page.repository_relative} documents no output for its own {marker!r}"
            )
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("page,marker", CLAIMS, ids=site.output_claim_ids())
def test_every_documented_output_is_produced_by_its_module(page: site.Page, marker: str) -> None:
    """Every output block, an exercise answer's included, is compared with a real run."""
    assert site.documented_output(page, marker) == site.run(site.module_for_marker(marker))


@pytest.mark.parametrize("page", TEST_LESSONS, ids=site.lesson_ids(TEST_LESSONS))
def test_a_testing_lesson_passes_as_a_test(page: site.Page) -> None:
    result = site.run_test_module(page)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("page", COMMAND_LESSONS, ids=site.lesson_ids(COMMAND_LESSONS))
def test_a_command_lesson_prints_what_the_page_says(page: site.Page) -> None:
    """A command lesson documents the command's real transcript, not a transcript someone typed."""
    markers = page.outputs
    assert len(markers) == 1, f"{page.repository_relative} documents {len(markers)} outputs"
    assert site.documented_output(page, markers[0]) == site.run_command(page)


@pytest.mark.parametrize("page", SCAFFOLD_LESSONS, ids=site.lesson_ids(SCAFFOLD_LESSONS))
def test_a_scaffold_lesson_writes_what_the_page_says(page: site.Page, tmp_path: Path) -> None:
    """A scaffolding command's claim is the files it writes, not the absolute paths it prints."""
    markers = page.outputs
    assert len(markers) == 1, f"{page.repository_relative} documents {len(markers)} outputs"
    assert site.documented_output(page, markers[0]) == site.run_scaffold(page, tmp_path)


@pytest.mark.parametrize("page", LESSONS, ids=IDS)
def test_lesson_snippet_includes_resolve(page: site.Page) -> None:
    snippets = page.snippets
    if page.verify == "scaffold":
        assert not snippets, f"{page.repository_relative} has no Python to include"
        return
    if page.verify != "command":
        assert snippets, f"{page.repository_relative} includes no code"
    for snippet in snippets:
        assert snippet.startswith("examples/"), (
            f"{page.repository_relative} includes {snippet}: lesson code lives under examples/"
        )
        assert (site.REPOSITORY_ROOT / snippet).exists(), (
            f"{page.repository_relative} includes {snippet}, which does not exist"
        )


@pytest.mark.parametrize("page", LESSONS, ids=IDS)
def test_a_lesson_page_contains_no_hand_written_python(page: site.Page) -> None:
    """Python shown on a lesson page must arrive by include, so the page cannot disagree with CI."""
    languages = site.fences(page)
    assert "python" not in languages and "py" not in languages, (
        f"{page.repository_relative} has a hand-written Python block; include the example instead"
    )
