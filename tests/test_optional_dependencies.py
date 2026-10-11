"""A missing optional dependency names the extra that provides it.

Without the extra, the import of an optional module is supposed to fail with the command that
fixes it, not a bare ``ModuleNotFoundError`` naming a package the user never asked for by name.
Each check runs in a subprocess with the dependency blocked, so the real installed extras cannot
hide the behavior.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from xyberos._extras import extra_error, suggest_extra

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"

BLOCKED_IMPORT = """
import sys

BLOCKED = {blocked!r}


class Blocker:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ModuleNotFoundError(f"No module named {{name!r}}", name=name)
        return None


sys.meta_path.insert(0, Blocker())
import {module}
"""


def run_python(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=SOURCE_ROOT,
        check=False,
    )


def test_the_error_names_the_extra_and_keeps_the_original_message() -> None:
    error = extra_error("ollama", ModuleNotFoundError("No module named 'httpx'"))

    assert isinstance(error, ModuleNotFoundError)
    assert "xyberos[ollama]" in str(error)
    assert "No module named 'httpx'" in str(error)


@pytest.mark.parametrize(
    ("missing", "expected"),
    [
        ("starlette", "http"),
        ("starlette.applications", "http"),
        ("sqlalchemy", "database"),
        ("alembic", "database"),
        ("not_an_extra_dependency", None),
        (None, None),
    ],
)
def test_the_reverse_lookup_names_an_extra_only_when_one_provides_it(
    missing: str | None, expected: str | None
) -> None:
    error = ModuleNotFoundError(f"No module named {missing!r}", name=missing)

    assert suggest_extra(error) == expected


@pytest.mark.parametrize(
    ("module", "blocked", "extra"),
    [
        ("xyberos.http", {"starlette"}, "http"),
        ("xyberos.http.testing", {"starlette"}, "http"),
        ("xyberos.database", {"sqlalchemy"}, "database"),
        ("xyberos.database.migrations", {"alembic"}, "database"),
        ("xyberos.ai.ollama", {"httpx"}, "ollama"),
    ],
)
def test_missing_optional_dependency_points_at_the_extra(
    module: str, blocked: set[str], extra: str
) -> None:
    result = run_python(BLOCKED_IMPORT.format(blocked=blocked, module=module))

    assert result.returncode != 0, f"importing {module} without {blocked} unexpectedly worked"
    assert f'pip install "xyberos[{extra}]"\'' in result.stderr, result.stderr


def test_installed_extras_still_import_normally() -> None:
    result = run_python(
        "import xyberos, xyberos.ai, xyberos.ai.ollama, xyberos.http, xyberos.database; print('ok')"
    )

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
