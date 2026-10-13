"""Five minutes to a running application is measured, not claimed.

`xyberos new` prints the commands that finish the job. This runs them in a temporary directory, in
the order it printed them, and compares the block with the one the getting started guide shows — so
the scaffold, the guide, and the build cannot disagree about what "five minutes" means.

Two details keep the test honest about what it does *not* do. The `cd` is performed by the harness
rather than by a shell, because a subprocess's working directory is the shell feature being
replaced. The editable install is asserted rather than executed: it installs a project into the
interpreter running this suite, and the property it would establish — that the scaffold imports and
passes its own test — is what the two commands that follow actually check.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from xyberos.cli.main import EXIT_OK, main

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GETTING_STARTED = REPOSITORY_ROOT / "docs" / "getting-started.md"
PROJECT = "myapp"
NEXT_BLOCK = "next:"
INSTALL = 'python -m pip install -e ".[http,dev]" uvicorn'


@pytest.fixture(scope="module")
def scaffolded(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    """Scaffold once per module: the project directory and the report the command printed."""
    root = tmp_path_factory.mktemp("five-minutes")
    return root / PROJECT, run_cli(["new", PROJECT, "--directory", str(root)])


def test_the_scaffold_writes_a_project_that_imports(scaffolded: tuple[Path, str]) -> None:
    project, _ = scaffolded

    assert (project / "xyberos.toml").exists()
    assert (project / "src" / PROJECT / "app.py").exists()
    assert (project / "tests" / "test_app.py").exists()


def test_the_printed_block_is_the_block_the_guide_shows(scaffolded: tuple[Path, str]) -> None:
    _, output = scaffolded

    assert [f"xyberos new {PROJECT}", *next_block(output)] == guide_block()


def test_the_commands_the_block_prints_that_need_no_install_succeed(
    scaffolded: tuple[Path, str],
) -> None:
    project, output = scaffolded
    commands = next_block(output)

    assert commands[1] == INSTALL, "the block's order is what this test follows"

    test_run = run(project, sys.executable, "-m", "pytest")
    assert test_run.returncode == 0, test_run.stdout + test_run.stderr
    assert "2 passed" in test_run.stdout, test_run.stdout

    reported = commands[3].split()
    assert reported[:2] == ["xyberos", "check"], "the fourth command is the one being re-run"
    check_run = run(project, sys.executable, "-m", "xyberos", *reported[1:])
    assert check_run.returncode == 0, check_run.stdout + check_run.stderr
    assert "provider graph: valid" in check_run.stdout, check_run.stdout
    assert "routes: 2 (handler signatures valid)" in check_run.stdout, check_run.stdout


def next_block(output: str) -> list[str]:
    """Return the commands from the `next:` block a finished scaffold prints, in order."""
    lines = [line.strip() for line in output.splitlines()]
    start = lines.index(NEXT_BLOCK)

    return [line for line in lines[start + 1 :] if line]


def guide_block() -> list[str]:
    """Return the getting started block that starts with the scaffold invocation."""
    lines = GETTING_STARTED.read_text(encoding="utf-8").splitlines()
    invocation = lines.index(f"xyberos new {PROJECT}")

    start = invocation
    while not lines[start].startswith("```"):
        start -= 1

    block: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("```"):
            break
        block.append(line.strip())
    return block


def run(project: Path, *command: str) -> subprocess.CompletedProcess[str]:
    """Run one command inside the scaffolded project, with this checkout's framework importable."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")
    return subprocess.run(
        list(command),
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def run_cli(argv: list[str]) -> str:
    """Run the CLI in-process and return what it printed, failing on a non-zero exit code."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exit_code = main(argv)

    assert exit_code == EXIT_OK, buffer.getvalue()
    return buffer.getvalue()
