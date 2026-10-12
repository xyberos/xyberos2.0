"""Walkthrough — the preflight a deployment runs before it serves anything.

Run it with:

    python -m learn_production.deploy02_check
"""

from __future__ import annotations

from xyberos.cli.main import main as cli

#: The factory a deployment names, in the `module:attribute` form the CLI and an ASGI server share.
TARGET = "learn_production.deploy01_app:create_app"


def main() -> None:
    """Check the application offline, and report what the check decided."""
    code = cli(["check", "--app", TARGET, "--app-dir", "examples"])
    print("xyberos check exited with", code)


if __name__ == "__main__":
    main()
