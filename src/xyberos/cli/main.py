"""The command line: argument parsing, dispatch, and the exit code.

The parser is ``argparse`` from the standard library, because a framework that refuses to depend on
an HTTP stack should not depend on a CLI framework either. Each command is a thin wrapper around an
API the runtime already proves; the work lives in the command's own module so it can be tested
without a subprocess.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from xyberos import __version__
from xyberos.cli.check import check
from xyberos.cli.errors import CliError
from xyberos.cli.migrations import DEFAULT_DIRECTORY, migrate
from xyberos.cli.project import new
from xyberos.cli.server import DEFAULT_HOST, DEFAULT_PORT, run
from xyberos.errors import XyberosError

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["main"]

EXIT_OK = 0
EXIT_FAILURE = 1

PROGRAM = "xyberos"

DESCRIPTION = """\
Developer experience for a Xyberos application: check a composition, scaffold a project, run an
ASGI server, and apply migrations. Each command wraps an API the runtime already provides.
"""


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for ``xyberos``, with one subcommand per documented capability."""
    parser = argparse.ArgumentParser(prog=PROGRAM, description=DESCRIPTION)
    parser.add_argument("--version", action="version", version=f"{PROGRAM} {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    checker = commands.add_parser(
        "check",
        help="load settings and inspect a composed application without running it",
        description=check.__doc__,
    )
    checker.add_argument("--config", type=Path, help="path to xyberos.toml (default: discovered)")
    checker.add_argument(
        "--app",
        metavar="MODULE:ATTRIBUTE",
        help="the App to validate, for example myapp.app:create_app",
    )
    checker.add_argument(
        "--app-dir",
        type=Path,
        help="directory to import the target from, for example src in a src layout",
    )

    creator = commands.add_parser(
        "new",
        help="scaffold a minimal project that runs",
        description=new.__doc__,
    )
    creator.add_argument("name", help="project and package name, lower case")
    creator.add_argument("--directory", type=Path, default=Path.cwd(), help="where to create it")
    creator.add_argument(
        "--force", action="store_true", help="write into a non-empty directory that already exists"
    )

    runner = commands.add_parser(
        "run",
        help="run an ASGI server on an application",
        description=run.__doc__,
    )
    runner.add_argument("--app", required=True, metavar="MODULE:ATTRIBUTE", help="the ASGI app")
    runner.add_argument("--factory", action="store_true", help="call the target to get the app")
    runner.add_argument("--host", default=DEFAULT_HOST, help=f"default: {DEFAULT_HOST}")
    runner.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"default: {DEFAULT_PORT}")
    runner.add_argument("--reload", action="store_true", help="restart when a source file changes")
    runner.add_argument(
        "--app-dir",
        type=Path,
        help="directory to import the target from, passed to the ASGI server",
    )

    migrator = commands.add_parser(
        "migrate",
        help="apply database migrations with Alembic",
        description=migrate.__doc__,
    )
    migrator.add_argument(
        "--migrations",
        type=Path,
        default=Path(DEFAULT_DIRECTORY),
        help=f"directory of revisions (default: {DEFAULT_DIRECTORY})",
    )
    migrator.add_argument("--url", required=True, help="synchronous SQLAlchemy database URL")
    migrator.add_argument(
        "--async", dest="use_asyncio", action="store_true", help="apply inside an event loop"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = _dispatch(parser, args)
    except CliError as error:
        print(f"{PROGRAM}: error: {error}", file=sys.stderr)
        return error.exit_code
    except XyberosError as error:
        print(f"{PROGRAM}: error: {type(error).__name__}: {error}", file=sys.stderr)
        return EXIT_FAILURE
    except ModuleNotFoundError as error:
        # An optional capability reports the extra to install; repeating it verbatim is the whole
        # point, so it is printed rather than replaced.
        print(f"{PROGRAM}: error: {error}", file=sys.stderr)
        return EXIT_FAILURE
    if report:
        print(report)
    return EXIT_OK


def _dispatch(parser: argparse.ArgumentParser, args: argparse.Namespace) -> str | None:
    """Run the parsed command and return what it wants printed, if anything."""
    if args.command == "check":
        return check(config_path=args.config, target=args.app, app_dir=args.app_dir)
    if args.command == "new":
        written = new(args.name, directory=args.directory, force=args.force)
        return _describe_new(args.directory / args.name, written)
    if args.command == "migrate":
        return migrate(args.migrations, url=args.url, use_asyncio=args.use_asyncio)
    if args.command == "run":
        run(
            target=args.app,
            factory=args.factory,
            host=args.host,
            port=args.port,
            reload=args.reload,
            app_dir=args.app_dir,
        )
        return None
    parser.error(f"unknown command {args.command!r}")
    return None


def _describe_new(root: Path, written: Sequence[Path]) -> str:
    files = "\n".join(f"  {path.relative_to(root).as_posix()}" for path in written)
    return (
        f"created {root}:\n{files}\n\n"
        f'next:\n  cd {root.name}\n  python -m pip install -e ".[http,dev]" uvicorn\n'
        f"  pytest\n  xyberos check --app {root.name}.app:create_app --app-dir src"
    )
