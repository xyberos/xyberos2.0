"""The loop in CONTRIBUTING is the loop CI runs, and the hooks run the fastest part of it.

Three files describe one workflow: `CONTRIBUTING.md` tells a contributor what to run,
`.github/workflows/ci.yml` runs it, and `.pre-commit-config.yaml` catches the cheapest half before a
commit exists. `.devcontainer/devcontainer.json` reproduces the environment the workflow builds in.
Documentation that drifts from the build is worse than no documentation — a contributor follows it,
gets a green local run, and is surprised by the build — so the agreement is asserted rather than
remembered.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 uses the tomli fallback.
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
HOOKS = ROOT / ".pre-commit-config.yaml"
DEVCONTAINER = ROOT / ".devcontainer" / "devcontainer.json"
PYPROJECT = ROOT / "pyproject.toml"

QUALITY_JOB = "quality"
LOOP_SECTION = "## Before submitting a change"
INSTALL = "python -m pip install"
# The workflow upgrades pip first, which is a property of a fresh runner rather than a step a
# contributor has to remember, so it is not part of the documented installs.
PIP_UPGRADE = "python -m pip install --upgrade pip"
RUFF_RANGE = re.compile(r'"ruff>=([\d.]+),<([\d.]+)"')
LINTED_PATHS = (
    "src/xyberos/app.py",
    "tests/test_contributor_loop.py",
    "examples/tutorial/chapter01_settings.py",
    "site/scripts/build.py",
    "tools/ecosystem.py",
)


def test_contributing_lists_the_loop_the_workflow_runs() -> None:
    assert documented_loop() == [
        command for command in quality_commands() if INSTALL not in command
    ]


def test_contributing_lists_the_installs_the_workflow_runs() -> None:
    installs = [command for command in quality_commands() if command.startswith(INSTALL)]

    assert documented_installs() == [command for command in installs if command != PIP_UPGRADE]


def test_the_hooks_are_the_two_ruff_commands_from_the_loop() -> None:
    """The hook is allowed to fix; what it must not do is apply a different rule set."""
    hooks = hook_config()

    assert [hook["id"] for hook in hooks] == ["ruff", "ruff-format"]
    assert "--fix" in hooks[0]["args"]
    assert hook_repository() == "https://github.com/astral-sh/ruff-pre-commit"

    pattern = re.compile(hooks[0]["files"])
    assert all(pattern.match(path) for path in LINTED_PATHS)
    assert not pattern.match("docs/cli.md"), "the workflow's ruff arguments do not include docs"


def test_the_hook_revision_is_inside_the_range_the_extra_declares() -> None:
    lower, upper = declared_ruff_range()

    assert lower <= version_tuple(hook_revision()) < upper, (
        "the hook would lint with a ruff that CI's install range cannot select"
    )


def test_the_devcontainer_builds_the_environment_the_workflow_installs() -> None:
    document = devcontainer()
    command = document["postCreateCommand"]

    assert isinstance(command, str)
    for install in documented_installs():
        assert install in command, f"the devcontainer does not run {install!r}"

    image = document["image"]
    assert isinstance(image, str)
    assert image.rsplit(":", 1)[1] in quality_matrix(), (
        "the container should track a Python version the quality job actually tests"
    )


def test_pre_commit_is_a_development_dependency() -> None:
    """`pre-commit install` is documented, so the tool it installs has to be installed with it."""
    dev = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["optional-dependencies"][
        "dev"
    ]

    assert any(requirement.startswith("pre-commit") for requirement in dev)


def test_the_loop_stays_first_because_the_site_build_precedes_the_tests() -> None:
    """The ordering is load-bearing, so it is asserted rather than described."""
    loop = documented_loop()

    assert loop.index("python site/scripts/build.py --check") < loop.index("python -m pytest")


def documented_loop() -> list[str]:
    """The commands in the first block of the contributing guide's loop section, in order."""
    return blocks_of(LOOP_SECTION)[0]


def documented_installs() -> list[str]:
    """The commands in the section's second block: how to install what the loop needs."""
    return blocks_of(LOOP_SECTION)[1]


def blocks_of(heading: str) -> list[list[str]]:
    """Return each fenced block under ``heading`` as a list of non-empty lines."""
    text = CONTRIBUTING.read_text(encoding="utf-8")
    start = text.index(heading)
    section = text[start:]
    end = section.find("\n## ")
    if end != -1:
        section = section[:end]

    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in section.splitlines():
        if line.startswith("```"):
            if current is None:
                current = []
            else:
                blocks.append(current)
                current = None
        elif current is not None and line.strip():
            current.append(line.strip())
    return blocks


def quality_commands() -> list[str]:
    """Every `run:` in the quality job, in the order the job runs them."""
    steps = workflow()["jobs"][QUALITY_JOB]["steps"]
    commands = [step["run"].strip() for step in steps if "run" in step]

    assert all("\n" not in command for command in commands), (
        "a multi-line step needs this comparison extended deliberately, not silently skipped"
    )
    return commands


def quality_matrix() -> set[str]:
    return set(workflow()["jobs"][QUALITY_JOB]["strategy"]["matrix"]["python-version"])


def workflow() -> dict[str, object]:
    parsed = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def hook_config() -> list[dict[str, object]]:
    parsed = yaml.safe_load(HOOKS.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return [hook for repository in parsed["repos"] for hook in repository["hooks"]]


def hook_repository() -> str:
    parsed = yaml.safe_load(HOOKS.read_text(encoding="utf-8"))
    return str(parsed["repos"][0]["repo"])


def hook_revision() -> str:
    parsed = yaml.safe_load(HOOKS.read_text(encoding="utf-8"))
    return str(parsed["repos"][0]["rev"]).lstrip("v")


def declared_ruff_range() -> tuple[tuple[int, ...], tuple[int, ...]]:
    match = RUFF_RANGE.search(PYPROJECT.read_text(encoding="utf-8"))

    assert match is not None, "the dev extra no longer declares a ruff range this test can read"
    return version_tuple(match.group(1)), version_tuple(match.group(2))


def version_tuple(text: str) -> tuple[int, ...]:
    """Compare `0.17.0` as `(0, 17, 0)`, so `0.6 <= 0.17.0 < 1` holds without a version library."""
    return tuple(int(part) for part in text.split("."))


def devcontainer() -> dict[str, object]:
    """Parse the devcontainer file, dropping its `//` comments, which `json` does not accept."""
    text = DEVCONTAINER.read_text(encoding="utf-8")
    without_comments = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("//")
    )
    parsed = json.loads(without_comments)
    assert isinstance(parsed, dict)
    return parsed
