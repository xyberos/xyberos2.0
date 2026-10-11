"""The ``xyberos`` command.

The promise of this package is the **command and its documented options**, not the Python modules
behind it: they are internal and may move in any release, which is why they are not part of the
frozen surface in [`docs/stability.md`](docs/stability.md). Nothing here imports an optional
capability at import time, so ``xyberos check`` works with the core package alone; a command that
needs an extra imports it when it runs and reports the extra to install if it is absent.

Every command wraps an API the runtime already proves: this is a front door, not a second
implementation of anything.
"""
