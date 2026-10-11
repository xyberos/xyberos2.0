"""The tutorial tells the truth.

`docs/tutorial.md` shows an "Output" block for each chapter with the output that chapter produces,
and each block is marked with an HTML comment naming the chapter. This file runs every chapter and
compares its real output with the documented one, so a tutorial that has drifted fails the suite
instead of misleading a reader.

Two consequences worth knowing, because both are intended:

- Changing a chapter's output means editing `docs/tutorial.md` in the same commit. That is the
  point: the page is a set of claims, not prose that happens to be nearby.
- The `chapter8` transcript is a sample run with a machine-dependent timing, so it is not compared
  here. Its code *is* the test file `tests/tutorial/test_chapter8_testing.py`, which the suite runs.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import io
import re
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TUTORIAL_PATH = REPOSITORY_ROOT / "docs" / "tutorial.md"
TUTORIAL_EXAMPLES = REPOSITORY_ROOT / "examples" / "tutorial"

CHAPTERS = [
    "chapter1_first_app",
    "chapter2_injection",
    "chapter3_scopes",
    "chapter4_config",
    "chapter5_http",
    "chapter6_requests_and_errors",
    "chapter7_database",
    "chapter9_plugins",
    "chapter10_workflow",
    "chapter11_ai",
    "chapter12_durable",
]


def documented_output(name: str) -> str:
    """Return the output block the tutorial claims for ``name``."""
    pattern = re.compile(
        r"<!-- output: " + re.escape(name) + r" -->\n```text\n(.*?)\n```", re.DOTALL
    )
    match = pattern.search(TUTORIAL_PATH.read_text(encoding="utf-8"))
    assert match is not None, f"docs/tutorial.md has no output block for {name!r}"
    return match.group(1).strip()


def run_chapter(name: str) -> str:
    """Run one chapter and return what it printed."""
    module = importlib.import_module(f"tutorial.{name}")
    entry = module.main
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        if inspect.iscoroutinefunction(entry):
            asyncio.run(entry())
        else:
            entry()
    return buffer.getvalue().strip()


def test_every_chapter_module_has_a_documented_output() -> None:
    """A new chapter must be added to the page as well as to the directory."""
    modules = sorted(
        path.stem
        for path in TUTORIAL_EXAMPLES.glob("chapter*.py")
        if path.stem != "chapter8_testing"
    )

    assert modules == sorted(CHAPTERS)


@pytest.mark.parametrize("name", CHAPTERS)
def test_the_chapter_prints_what_the_tutorial_says(name: str) -> None:
    assert run_chapter(name) == documented_output(name)


def test_the_cli_transcript_matches_the_documented_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI chapter quotes real output, so it is checked like the rest.

    The environment is emptied of `XYBEROS_` variables and the working directory is the repository
    root, so the settings the command reports are the documented defaults rather than a developer's.
    """
    from xyberos.cli.main import main

    for key in [key for key in __import__("os").environ if key.startswith("XYBEROS_")]:
        monkeypatch.delenv(key)
    monkeypatch.chdir(REPOSITORY_ROOT)

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(["check"])

    assert code == 0
    assert buffer.getvalue().strip() == documented_output("cli-check")


def test_the_tutorial_links_only_to_files_that_exist() -> None:
    """A tutorial is read by newcomers, who will click the links."""
    text = TUTORIAL_PATH.read_text(encoding="utf-8")
    targets = re.findall(r"\]\((?!https?:)([^)#]+)", text)

    missing = sorted(
        target for target in set(targets) if not (TUTORIAL_PATH.parent / target).exists()
    )

    assert not missing, missing


def test_the_server_command_in_the_tutorial_points_at_a_real_asgi_application() -> None:
    """The chapter quotes a `uvicorn --factory` command, so the factory has to exist and work."""
    from starlette.applications import Starlette

    module = importlib.import_module("tutorial.chapter5_http")

    assert isinstance(module.app_factory(), Starlette)
