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


def test_the_runtime_does_not_import_the_ai_package() -> None:
    result = run_python(
        "import sys, xyberos, xyberos.app, xyberos.execution; "
        "leaked = [name for name in sys.modules if name.startswith('xyberos.ai')]; "
        "assert not leaked, leaked"
    )

    assert result.returncode == 0, result.stderr


def test_the_ai_package_loads_no_provider_sdk() -> None:
    result = run_python(
        "import sys, xyberos.ai; "
        "optional = ('httpx', 'ollama', 'openai', 'anthropic'); "
        "loaded = [name for name in optional if name in sys.modules]; "
        "assert not loaded, loaded"
    )

    assert result.returncode == 0, result.stderr


def test_the_ai_package_does_not_import_an_adapter() -> None:
    result = run_python(
        "import sys; import xyberos.ai; import xyberos.ai.contracts; import xyberos.ai.facade; "
        "leaked = [name for name in sys.modules if name.startswith('xyberos.ai.ollama')]; "
        "assert not leaked, leaked"
    )

    assert result.returncode == 0, result.stderr


def test_the_ai_package_does_not_import_optional_subsystems() -> None:
    result = run_python(
        "import sys; import xyberos.ai; "
        "leaked = [name for name in sys.modules if name.startswith("
        "('xyberos.http', 'xyberos.database', 'xyberos.durable'))]; "
        "assert not leaked, leaked"
    )

    assert result.returncode == 0, result.stderr


def test_the_execution_layer_loads_no_optional_capability() -> None:
    result = run_python(
        "import sys, xyberos.execution; "
        "optional = ('starlette', 'sqlalchemy', 'aiosqlite', 'alembic', 'httpx'); "
        "loaded = [name for name in optional if name in sys.modules]; "
        "assert not loaded, loaded"
    )

    assert result.returncode == 0, result.stderr


def test_the_execution_layer_does_not_import_optional_subsystems() -> None:
    result = run_python(
        "import sys; import xyberos.execution; import xyberos.execution.executor; "
        "leaked = [name for name in sys.modules if name.startswith("
        "('xyberos.http', 'xyberos.database', 'xyberos.ai', 'xyberos.durable'))]; "
        "assert not leaked, leaked"
    )

    assert result.returncode == 0, result.stderr


def test_importing_core_does_not_import_the_durable_package() -> None:
    result = run_python(
        "import sys, xyberos, xyberos.app; "
        "leaked = [name for name in sys.modules if name.startswith('xyberos.durable')]; "
        "assert not leaked, leaked"
    )

    assert result.returncode == 0, result.stderr


def test_the_durable_package_loads_no_http_or_ai_dependency() -> None:
    result = run_python(
        "import sys; import xyberos.durable; "
        "optional = ('starlette', 'httpx'); "
        "loaded = [name for name in optional if name in sys.modules]; "
        "assert not loaded, loaded; "
        "leaked = [name for name in sys.modules if name.startswith("
        "('xyberos.http', 'xyberos.ai'))]; "
        "assert not leaked, leaked"
    )

    assert result.returncode == 0, result.stderr


def test_the_durable_package_requires_its_extra() -> None:
    result = run_python(
        "import sys\n"
        "BLOCKED = {'sqlalchemy'}\n"
        "class Blocker:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in BLOCKED:\n"
        '            raise ModuleNotFoundError(f"No module named {name!r}", name=name)\n'
        "        return None\n"
        "sys.meta_path.insert(0, Blocker())\n"
        "try:\n"
        "    import xyberos.durable\n"
        "except ModuleNotFoundError as error:\n"
        "    assert 'xyberos[durable]' in str(error), str(error)\n"
        "else:\n"
        "    raise AssertionError('the durable package imported without its extra')\n"
    )

    assert result.returncode == 0, result.stderr
