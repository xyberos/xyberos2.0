"""The ``check`` command: load settings, inspect a composed application, report what it found.

It is read-only and starts nothing. Validation is the same call the application makes at startup
(``App.validate()``), so a successful check is evidence about the deployment rather than a second
opinion, and route compilation reuses the adapter's own signature check when the HTTP extra is
installed.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from xyberos import App, Settings, __version__
from xyberos._extras import suggest_extra
from xyberos.cli.errors import CliError
from xyberos.cli.schema import settings_schema
from xyberos.cli.targets import load_target
from xyberos.diagnostics import ProviderInfo

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["check", "config_schema", "document", "explain"]

DOCUMENT_VERSION = 1
"""The version of the `check --json` document itself. ADR 0020 records why it is a contract."""


def check(
    *,
    config_path: Path | None = None,
    target: str | None = None,
    app_dir: Path | None = None,
) -> str:
    """Return the report for ``config_path`` and the optional application target."""
    settings = _load_settings(config_path)
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


def document(
    *,
    config_path: Path | None = None,
    target: str | None = None,
    app_dir: Path | None = None,
) -> str:
    """Return ``check --json``: one machine-readable description of this deployment.

    The document is a contract rather than a debug dump, because a script that reads a key is as
    bound to it as a caller is to a name: [ADR 0020](../adr/0020-introspection-documents.md) records
    the shape, `tests/test_compatibility.py` pins the version and the top-level keys, and
    `tests/cli/test_introspection.py` pins the nested ones — so a rename fails a test instead of
    someone's pipeline. It is also assembled from the same calls the text report uses —
    `Diagnostics` for providers and plugins, `App.routes` for routes — so the two cannot disagree.
    """
    settings = _load_settings(config_path)
    body: dict[str, object] = {
        "document": DOCUMENT_VERSION,
        "xyberos_version": __version__,
        "config_file": str(config_path) if config_path is not None else None,
        "settings": _settings_document(settings),
        "application": None,
    }
    if target is None:
        return json.dumps(body, indent=2, sort_keys=True)

    app = _require_app(load_target(target, app_dir=app_dir))
    app.validate()
    diagnostics = app.diagnostics()
    body["application"] = {
        "target": target,
        "provider_graph": "valid",
        "providers": [
            {
                "contract": provider.contract,
                "scope": provider.scope,
                "eager": provider.eager,
                "source": provider.source,
                "dependencies": list(provider.dependencies),
            }
            for provider in diagnostics.providers
        ],
        "plugins": [
            {
                "name": plugin.name,
                "api_version": plugin.api_version,
                "requires": list(plugin.requires),
                "state": plugin.state.value,
            }
            for plugin in diagnostics.plugins
        ],
        "routes": _routes_document(app),
    }
    return json.dumps(body, indent=2, sort_keys=True)


def explain(
    contract: str,
    *,
    config_path: Path | None = None,
    target: str | None = None,
    app_dir: Path | None = None,
) -> str:
    """Return ``check --why``: where one contract comes from, what it needs, and at which scope.

    The provider descriptions are the same ones a validation failure is built from, so this prints
    the path the runtime would print rather than a second opinion about it.
    """
    _load_settings(config_path)
    if target is None:
        raise CliError(
            "--why needs an application to explain: pass --app module:attribute", exit_code=2
        )
    app = _require_app(load_target(target, app_dir=app_dir))
    app.validate()
    providers = {info.contract: info for info in app.diagnostics().providers}
    if not providers:
        raise CliError(
            f"{target} registers no providers, so there is nothing to explain", exit_code=2
        )
    matched = _match_provider(contract, providers)
    lines = [_describe_provider(matched)]
    _describe_dependencies(matched, providers, lines, depth=1, remaining=len(providers))
    return "\n".join(lines)


def config_schema(
    *,
    target: str | None = None,
    app_dir: Path | None = None,
) -> str:
    """Return ``check --schema``: the JSON Schema for ``xyberos.toml``.

    Without ``--app`` this is byte-for-byte the schema that ships in the wheel, which an editor can
    read with no extension installed. With ``--app`` each declared plugin's ``config_type`` becomes
    a typed section, so completion and validation cover ``[plugins.<name>]`` as well. The opaque
    ``[ai.<name>]`` sections stay described as objects, because core does not know their keys.
    """
    sections: dict[str, object] = {}
    if target is not None:
        app = _require_app(load_target(target, app_dir=app_dir))
        sections = {
            plugin.name: plugin.config_type
            for plugin in app.diagnostics().plugins
            if plugin.config_type is not None
        }
    return json.dumps(settings_schema(plugin_sections=sections), indent=2, sort_keys=True)


def _load_settings(config_path: Path | None) -> Settings:
    return Settings.load() if config_path is None else Settings.load(config_path=config_path)


def _settings_document(settings: Settings) -> dict[str, object]:
    """Describe the loaded settings, including which sections were configured at all."""
    return {
        "schema_version": settings.schema_version,
        "app": {
            "name": settings.app.name,
            "environment": settings.app.environment,
            "debug": settings.app.debug,
            "shutdown_timeout": settings.app.shutdown_timeout,
        },
        "plugins": {name: dict(section) for name, section in sorted(settings.plugins.items())},
        "ai": {name: dict(section) for name, section in sorted(settings.ai.items())},
    }


def _routes_document(app: App) -> dict[str, object]:
    """Describe the route table, and say which extra is missing when it cannot be compiled.

    The extra is not hard-coded: it comes from ``suggest_extra``, which reads the same
    ``PACKAGE_EXTRAS`` map the runtime's own import errors use, so this document and an
    ``ImportError`` message can never name two different extras.
    """
    document_routes: dict[str, object] = {
        "registered": [
            {
                "method": route.method,
                "path": route.path,
                "name": route.name,
                "parameters": list(route.path_parameters),
            }
            for route in app.routes
        ],
        "count": len(app.routes),
        "compiled": not app.routes,
    }
    if not app.routes:
        return document_routes
    try:
        from xyberos.http import HttpAdapter
    except ModuleNotFoundError as error:
        extra = suggest_extra(error)
        missing: dict[str, object] = {"module": error.name or ""}
        if extra is not None:
            missing["extra"] = extra
            missing["install"] = f'pip install "xyberos[{extra}]"'
        document_routes["missing"] = missing
        return document_routes
    HttpAdapter(app)
    document_routes["compiled"] = True
    return document_routes


def _match_provider(contract: str, providers: dict[str, ProviderInfo]) -> ProviderInfo:
    """Return the provider the caller asked about, or explain what is registered instead."""
    if contract in providers:
        return providers[contract]
    suffix = f".{contract}"
    matches = [info for name, info in providers.items() if name.endswith(suffix)]
    if len(matches) == 1:
        return matches[0]
    known = ", ".join(sorted(providers))
    if matches:
        raise CliError(
            f"{contract!r} matches more than one provider; name it in full. Registered: {known}",
            exit_code=2,
        )
    raise CliError(
        f"no provider is registered for {contract!r}; registered contracts are: {known}",
        exit_code=2,
    )


def _describe_provider(provider: ProviderInfo) -> str:
    eager = ", eager" if provider.eager else ""
    return f"{provider.contract} [{provider.scope}{eager}] from {provider.source}"


def _describe_dependencies(
    provider: ProviderInfo,
    providers: dict[str, ProviderInfo],
    lines: list[str],
    *,
    depth: int,
    remaining: int,
) -> None:
    """Append one line per declared dependency, then recurse.

    ``remaining`` bounds the walk: a provider graph is acyclic by validation, so this is a guard
    against a snapshot that somehow is not rather than a normal case, and it costs nothing.
    """
    if remaining <= 0:
        return
    for dependency in provider.dependencies:
        info = providers.get(dependency)
        if info is None:
            lines.append(f"{'  ' * depth}{dependency} [not registered]")
            continue
        lines.append(f"{'  ' * depth}{_describe_provider(info)}")
        _describe_dependencies(info, providers, lines, depth=depth + 1, remaining=remaining - 1)


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
