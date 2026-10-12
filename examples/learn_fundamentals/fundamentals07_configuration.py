"""Lesson 7 — settings from a file, the environment, and arguments.

Run it with:

    python -m learn_fundamentals.fundamentals07_configuration
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from xyberos import Settings

CONFIG_FILE = """\
[app]
name = "tutorial"
environment = "staging"
debug = true
"""


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        (Path(directory) / "xyberos.toml").write_text(CONFIG_FILE, encoding="utf-8")

        settings = Settings.load(environ={}, cwd=Path(directory))
        print("from the file:", settings.app.name, settings.app.environment, settings.app.debug)

        settings = Settings.load(
            environ={"XYBEROS_APP__NAME": "from-the-environment"}, cwd=Path(directory)
        )
        print("the environment wins:", settings.app.name)

        settings = Settings.load(
            environ={"XYBEROS_APP__NAME": "from-the-environment"},
            overrides={"app": {"name": "from-the-arguments"}},
            cwd=Path(directory),
        )
        print("arguments win:", settings.app.name)


if __name__ == "__main__":
    main()
