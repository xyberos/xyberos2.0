"""The ``check`` command: load settings, inspect a composed application, report what it found.

It is read-only and starts nothing. Validation is the same call the application makes at startup
(``App.validate()``), so a successful check is evidence about the deployment rather than a second
opinion, and route compilation reuses the adapter's own signature check when the HTTP extra is
installed.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from xyberos import App, Settings
from xyberos.cli.errors import CliError
from xyberos.cli.targets import load_target

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["check"]


def check(
    *,
    config_path: Path | None = None,
    target: str | None = None,
    app_dir: Path | None = None,
) -> str:
    """Return the report for ``config_path`` and the optional application target."""
    settings = Settings.load() if config_path is None else Settings.load(config_path=config_path)
    lines = [
        f"settings: {settings.app.name} ({settings.app.environment}), "
        f"schema_version {settings.schema_version}, debug {settings.app.debug}"
    ]
    if config_path is not None:
        lines.append(f"config file: {config_path}")
    if target is None:
        lines.append("application: not inspected (pass --app module:attribute)")
        return "\n".join(lines)

    lines.append(f"application: {target}")
    app = _require_app(load_target(target, app_dir=app_dir))
    app.validate()
    lines.append("provider graph: valid")
    report = app.diagnostics().render()
    lines.extend(report.splitlines())
    lines.append(_describe_routes(app))
    return "\n".join(lines)


def _require_app(target: object) -> App:
    """Return the application to inspect, calling the target when it builds one.

    A target is usually a factory, because an `App` only exists once something constructs it. The
    factory runs — a composition root is expected to be side-effect free until ``start()`` — but
    nothing is started, so no service is constructed by this command.
    """
    if isinstance(target, App):
        return target
    if not callable(target):
        raise CliError(
            f"the target is {type(target).__name__}, not an App or a function that builds one",
            exit_code=2,
        )
    if _looks_like_asgi_application(target):
        raise CliError(
            f"the target is {type(target).__name__}, which is an ASGI application, not an App. "
            "An ASGI application is built from one with HttpAdapter(app).asgi_app, so point --app "
            "at the App or at the function that builds it",
            exit_code=2,
        )
    try:
        resolved = target()
    except TypeError as error:
        raise CliError(
            f"calling the target failed: {error}. Point --app at a target that takes no arguments",
            exit_code=2,
        ) from error
    if isinstance(resolved, App):
        return resolved
    raise CliError(
        f"the target returned {type(resolved).__name__}, not an App; an ASGI application is built "
        "from an App with HttpAdapter(...).asgi_app, so point --app at the App or at the function "
        "that builds it",
        exit_code=2,
    )


def _looks_like_asgi_application(target: object) -> bool:
    """Report whether ``target`` is callable with exactly ``(scope, receive, send)``.

    ASGI applications are callables, so ``check`` cannot tell one from a factory by ``callable()``
    alone. The signature is the distinguishing fact, and asking for it produces a far better message
    than calling the object and reporting whatever the ASGI server would have said.
    """
    try:
        parameters = inspect.signature(cast(Callable[..., Any], target)).parameters
    except (TypeError, ValueError):
        return False
    required = [
        parameter
        for parameter in parameters.values()
        if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
        and parameter.default is parameter.empty
    ]
    return len(required) == 3


def _describe_routes(app: App) -> str:
    """Compile the registered routes through the adapter, when the HTTP extra is installed.

    The extra is optional, so its absence is reported rather than treated as a failure: an
    application with no routes is a legitimate application, and it does not need the extra to be
    checked. Route records themselves are dependency-free, which is why an application with routes
    can still be described without one.
    """
    if not app.routes:
        return "routes: 0"
    try:
        from xyberos.http import HttpAdapter
    except ModuleNotFoundError:
        return (
            f"routes: {len(app.routes)} (not compiled: install xyberos[http] to check handler "
            "signatures)"
        )
    HttpAdapter(app)
    return f"routes: {len(app.routes)} (handler signatures valid)"
