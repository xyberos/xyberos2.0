"""Appendices document a real service, so they are checked differently from lessons.

An appendix cannot make an output claim — its output depends on a machine — so instead its commands
are checked to name targets that exist, and the module it runs is exercised by an opt-in workflow
gated on ``XYBEROS_OLLAMA_LIVE``, the same gate `tests/ai/test_live_ollama.py` already uses, so a
missing service can never fail a pull request.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest
import site_pages as site

APPENDICES = [
    page
    for page in site.pages()
    if page.repository_relative.startswith("site/appendices/") and page.source.name != "index.md"
]
IDS = [page.source.stem for page in APPENDICES]

LIVE = os.environ.get("XYBEROS_OLLAMA_LIVE") == "1"

#: ``python -m package.module``, and ``python path/to/file.py``.
MODULE_COMMAND = re.compile(r"^python\s+-m\s+([a-zA-Z_][\w.]*)\s*$", re.MULTILINE)
FILE_COMMAND = re.compile(r"^python\s+(\S+\.py)\s*$", re.MULTILINE)


def test_no_appendix_documents_an_output_block() -> None:
    """An appendix may quote a transcript, but not claim an output the suite can reproduce."""
    problems = [page.repository_relative for page in APPENDICES if page.outputs]
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("page", APPENDICES, ids=IDS)
def test_appendix_commands_name_real_targets(page: site.Page) -> None:
    """Every ``python -m`` and ``python file.py`` the page quotes has to resolve."""
    problems: list[str] = []
    for module_name in MODULE_COMMAND.findall(page.body):
        try:
            __import__(module_name)
        except ModuleNotFoundError as error:
            problems.append(f"{page.repository_relative} quotes `python -m {module_name}`: {error}")
    for target in FILE_COMMAND.findall(page.body):
        if not (site.REPOSITORY_ROOT / target).exists():
            problems.append(
                f"{page.repository_relative} quotes `python {target}`, which does not exist"
            )
    assert problems == [], "\n".join(problems)


@pytest.mark.skipif(
    not LIVE, reason="set XYBEROS_OLLAMA_LIVE=1 and a pulled model to run appendices"
)
@pytest.mark.parametrize("page", APPENDICES, ids=IDS)
def test_the_live_appendix_runs(page: site.Page) -> None:
    """Run the appendix's own commands against the real service."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(site.REPOSITORY_ROOT / "src"), str(site.REPOSITORY_ROOT / "examples")]
    )
    commands = [
        [sys.executable, "-m", module_name] for module_name in MODULE_COMMAND.findall(page.body)
    ]
    assert commands, f"{page.repository_relative} documents no module to run"
    for command in commands:
        result = subprocess.run(
            command,
            cwd=site.REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, result.stderr
