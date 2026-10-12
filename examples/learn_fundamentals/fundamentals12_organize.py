"""Lesson 12 — the one convention that decides where code goes.

Only the composition root imports Xyberos. Everything else — services, repositories, formatters — is
ordinary Python, which is what makes it testable without an application. This module checks that
claim against a real service module rather than asserting it in prose: it reads the source and
reports what it finds.
"""

from __future__ import annotations

import inspect

from learn_fundamentals import fundamentals12_service as service


def main() -> None:
    """Report what the service module imports, and use it with no application in sight."""
    source = inspect.getsource(service)
    print("the service module imports xyberos:", "xyberos" in source)

    defined = sorted(
        name
        for name, value in vars(service).items()
        if inspect.isclass(value) and value.__module__ == service.__name__
    )
    print("it defines:", ", ".join(defined))
    print("and it works on its own:", service.InvoiceFormatter().format(1234))


if __name__ == "__main__":
    main()
