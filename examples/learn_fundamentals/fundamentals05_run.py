"""Lesson 5 — running an application the way a deployment does.

Configuration is read from a file, the application is started and stopped explicitly rather than
through a context manager, and the lifecycle state is visible at each step. The file is written into
a temporary directory: a lesson that leaves a config file behind changes the next lesson's result.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from xyberos import App, Settings

CONFIG = """\
[app]
name = "lesson"
environment = "production"
debug = false
"""


async def main() -> None:
    """Load settings from a file, then start and stop the application by hand."""
    with tempfile.TemporaryDirectory() as directory:
        location = Path(directory) / "xyberos.toml"
        location.write_text(CONFIG, encoding="utf-8")

        settings = Settings.load(environ={}, cwd=Path(directory))
        print("configuration read from:", location.name)
        print("environment:", settings.app.environment)

        app = App(settings=settings)
        print("before start:", app.state.value)
        await app.start()
        print("after start:", app.state.value)
        await app.stop()
        print("after stop:", app.state.value)


if __name__ == "__main__":
    asyncio.run(main())
