"""``python -m xyberos`` runs the same command as the console script.

Two entry points rather than one, because ``python -m`` is the only form that works when the
script directory is not on ``PATH`` — inside a virtual environment that has not been activated,
for example.
"""

from __future__ import annotations

import sys

from xyberos.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
