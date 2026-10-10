"""Core imports stay free of optional capabilities, and the layers stay separate.

Each check runs in a subprocess so that unrelated tests in this session cannot make an optional
module look loaded (or hide a real leak).
"""

import subprocess
import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"


def run_python(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=SOURCE_ROOT,
        check=False,
    )


def test_importing_core_loads_no_optional_capability() -> None:
    result = run_python(
        "import sys, xyberos; "
        "optional = ('starlette', 'sqlalchemy', 'aiosqlite', 'alembic', 'httpx'); "
        "loaded = [name for name in optional if name in sys.modules]; "
        "assert not loaded, loaded"
    )

    assert result.returncode == 0, result.stderr


def test_runtime_does_not_import_http_or_database_modules() -> None:
    result = run_python(
        "import sys; import xyberos; import xyberos.runtime.dependencies; "
        "leaked = [name for name in sys.modules "
        "if name.startswith('xyberos.http') or name.startswith('xyberos.database')]; "
        "assert not leaked, leaked"
    )

    assert result.returncode == 0, result.stderr


def test_database_layer_does_not_depend_on_request_objects() -> None:
    result = run_python(
        "import sys; import xyberos.database; "
        "assert 'starlette' not in sys.modules, 'the database layer imported starlette'"
    )

    assert result.returncode == 0, result.stderr


def test_http_adapter_does_not_import_the_database_extra() -> None:
    result = run_python(
        "import sys; import xyberos.http; "
        "assert 'sqlalchemy' not in sys.modules, 'the http adapter imported sqlalchemy'"
    )

    assert result.returncode == 0, result.stderr
