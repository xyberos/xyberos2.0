"""Shared loading for the site's tests.

The site's scripts own the rules — front matter, navigation, the reference render — and these tests
call them rather than restating them, so a rule lives in one place and the suite is its second
reader.

``site/scripts`` is put on ``sys.path`` here rather than in ``pyproject.toml``, because one of those
modules is named ``build`` and the repository's release procedure runs ``python -m build``.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import io
import os
import re
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SITE_ROOT = REPOSITORY_ROOT / "site"
SCRIPTS = SITE_ROOT / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import frontmatter  # noqa: E402
import reference  # noqa: E402
import roadmap  # noqa: E402
import snippets_hook  # noqa: E402

#: The page type, re-exported so a test can annotate with it and a type checker can follow it.
Page = frontmatter.Page

__all__ = ["Page", "frontmatter", "reference", "roadmap", "snippets_hook"]

#: One lesson's claim: the module it documents, and the text it says that module prints.
OUTPUT_BLOCK = re.compile(
    r"<!--\s*output:\s*(?P<module>[^\s>]+)\s*-->\s*\n```text\n(?P<output>.*?)\n```", re.DOTALL
)

#: A fence in a lesson page. A ``python`` fence is what this suite forbids: code is included.
FENCE = re.compile(r"^```([a-zA-Z]*)", re.MULTILINE)

#: The example packages the lessons live in, and the path shape a lesson declares.
LESSON_PACKAGES = re.compile(r"^examples/(?P<package>learn_[a-z_]+)/(?P<module>[a-z0-9_]+)\.py$")


def pages() -> list[frontmatter.Page]:
    """Every page the site owns, excluding the generated reference copy."""
    return list(frontmatter.iter_pages())


def lessons() -> list[frontmatter.Page]:
    """Every lesson page, ordered by path and lesson number."""
    found = [page for page in pages() if page.is_lesson]
    return sorted(found, key=lambda page: (str(page.meta["path"]), int(page.meta["lesson"])))


def lessons_verified_by(mode: str) -> list[frontmatter.Page]:
    """The lessons checked a particular way: ``output``, ``pytest``, or ``command``."""
    return [page for page in lessons() if page.verify == mode]


def lesson_ids(selection: list[frontmatter.Page] | None = None) -> list[str]:
    """Stable test ids, so a failure names the lesson rather than a list index."""
    return [
        f"{page.meta['path']}-{str(page.meta['lesson']).zfill(2)}-{page.source.stem}"
        for page in (lessons() if selection is None else selection)
    ]


def navigation() -> list[str]:
    """The page paths ``mkdocs.yml`` names, flattened."""
    return roadmap.navigation()


def documented_output(page: frontmatter.Page, module: str) -> str:
    """Return the output block ``page`` claims for ``module``.

    The marker names a module by its own name — ``<!-- output: chapter1_first_app -->`` — which is
    the convention ``docs/tutorial.md`` already uses, so a lesson's marker is the last segment of
    its dotted module name rather than the whole path.
    """
    marker = module.rsplit(".", 1)[-1]
    for match in OUTPUT_BLOCK.finditer(page.body):
        if match.group("module") == marker:
            return match.group("output").strip()
    raise AssertionError(f"{page.repository_relative} documents no output for {module!r}")


def output_markers() -> list[str]:
    """Every ``<!-- output: ... -->`` marker the site's pages declare."""
    found: list[str] = []
    for page in pages():
        found.extend(match.group("module") for match in OUTPUT_BLOCK.finditer(page.body))
    return found


def example_modules() -> set[str]:
    """Every lesson module under ``examples/learn_*/``, by dotted name."""
    found: set[str] = set()
    for source in sorted((REPOSITORY_ROOT / "examples").glob("learn_*/**/*.py")):
        relative = source.relative_to(REPOSITORY_ROOT / "examples").as_posix()
        if source.name == "__init__.py":
            continue
        if not LESSON_PACKAGES.match(f"examples/{relative}"):
            continue
        found.add(relative.removesuffix(".py").replace("/", "."))
    return found


def is_lesson_module(dotted: str) -> bool:
    """Whether a dotted module name lives in one of the lesson packages."""
    return LESSON_PACKAGES.match(f"examples/{dotted.replace('.', '/')}.py") is not None


def claimed_modules() -> set[str]:
    """Every lesson module some page shows.

    A module is shown either as a lesson's own example or as a file a page includes, which is how an
    exercise answer stays honest: the answer is a file the suite runs, not a block someone typed
    once and never checked again.

    A page may also include the application the Traditional Apps path builds —
    ``examples/user_management/service.py`` — which is neither a lesson asset nor this check's
    business, so only lesson-package modules are collected here.
    """
    claimed: set[str] = set()
    for page in pages():
        candidates = [page.module, *(frontmatter.module_name(path) for path in page.snippets)]
        claimed.update(
            candidate
            for candidate in candidates
            if candidate is not None and is_lesson_module(candidate)
        )
    return claimed


def output_claims() -> list[tuple[frontmatter.Page, str]]:
    """Every output block a page claims, with the page that claims it.

    A ``command`` or ``scaffold`` lesson is excluded: its block is a transcript or a file list
    checked by running the command, not a module the suite can run.
    """
    claims: list[tuple[frontmatter.Page, str]] = []
    for page in pages():
        if page.verify in {"command", "scaffold"}:
            continue
        claims.extend((page, marker) for marker in page.outputs)
    return claims


def output_claim_ids() -> list[str]:
    """Stable ids for the output claims, naming the page and the block."""
    return [f"{page.source.stem}--{marker}" for page, marker in output_claims()]


def module_for_marker(marker: str) -> str:
    """Return the example module whose own name is ``marker``, which is what a marker names."""
    matches = sorted(name for name in example_modules() if name.rsplit(".", 1)[-1] == marker)
    assert len(matches) == 1, f"no single example module is named {marker!r}: {matches}"
    return matches[0]


def assert_the_checkout_under_test() -> None:
    """Fail loudly if ``xyberos`` resolves to some other line than this checkout.

    A lesson prints the version it was verified against, which is only stable when the import comes
    from ``src/``. Without this guard, an environment with the published 1.x line installed reports
    a lesson as drifted when the real fault is the environment.
    """
    import xyberos

    expected = (REPOSITORY_ROOT / "src" / "xyberos").resolve()
    actual = Path(xyberos.__file__).resolve().parent
    assert actual == expected, (
        f"these tests import xyberos from {actual}, not from this checkout ({expected}); run them "
        "from the repository root, as `python -m pytest` does, so that `src/` is on sys.path"
    )


def run(module_name: str) -> str:
    """Run one lesson module and return what it printed."""
    assert_the_checkout_under_test()
    module = importlib.import_module(module_name)
    entry = module.main
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        if inspect.iscoroutinefunction(entry):
            asyncio.run(entry())
        else:
            entry()
    return buffer.getvalue().strip()


def run_test_module(page: frontmatter.Page) -> subprocess.CompletedProcess[str]:
    """Run a lesson whose example is a pytest module, and return the finished process.

    A lesson about testing is verified by being a test rather than by printing something: its output
    is pytest's own report, timing included, which is not a claim a page can make.
    """
    example = page.example
    assert example is not None
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(REPOSITORY_ROOT / "src"), str(REPOSITORY_ROOT / "examples")]
    )
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(example), "-q"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )


def run_scaffold(page: frontmatter.Page, directory: Path) -> str:
    """Run a scaffolding command in ``directory`` and return the files it wrote, sorted.

    A subprocess, because the command's whole subject is what it writes to disk. The paths it prints
    are absolute and therefore not a claim a page can make; the file list is.
    """
    arguments = page.command.split()[1:]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(REPOSITORY_ROOT / "src"), str(REPOSITORY_ROOT / "examples")]
    )
    result = subprocess.run(
        [sys.executable, "-m", "xyberos", *arguments],
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    created = sorted(
        path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()
    )
    return "\n".join(created)


def run_command(page: frontmatter.Page) -> str:
    """Run the command a lesson quotes, in this process, and return what it printed.

    The transcript a command lesson documents is the *default* output, so the environment loses its
    ``XYBEROS_`` variables and the working directory becomes the repository root — otherwise the
    answer depends on whoever ran the suite.
    """
    assert_the_checkout_under_test()
    from xyberos.cli.main import main

    arguments = page.command.split()[1:]
    saved = {key: value for key, value in os.environ.items() if key.startswith("XYBEROS_")}
    for key in saved:
        del os.environ[key]

    buffer = io.StringIO()
    cwd = os.getcwd()
    try:
        os.chdir(REPOSITORY_ROOT)
        with contextlib.redirect_stdout(buffer):
            code = main(arguments)
    finally:
        os.chdir(cwd)
        os.environ.update(saved)

    assert code == 0, f"{page.repository_relative}: `{page.command}` exited {code}"
    return buffer.getvalue().strip()


def fences(page: frontmatter.Page) -> list[str]:
    """The languages of every fenced block on a page."""
    return FENCE.findall(page.body)
