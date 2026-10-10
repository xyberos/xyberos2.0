"""Typed core configuration loading for Xyberos."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from xyberos.errors import ConfigurationError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 uses the tomli fallback.
    import tomli as tomllib


_CONFIG_ENVIRONMENT_VARIABLE = "XYBEROS_CONFIG"
_CONFIG_PREFIX = "XYBEROS_"
_SUPPORTED_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AppSettings:
    """Configuration owned by the core application runtime."""

    name: str = "xyberos"
    environment: str = "development"
    debug: bool = False
    shutdown_timeout: float | None = None


@dataclass(frozen=True)
class Settings:
    """The validated settings available to an application instance."""

    schema_version: int = _SUPPORTED_SCHEMA_VERSION
    app: AppSettings = field(default_factory=AppSettings)

    @classmethod
    def load(
        cls,
        *,
        config_path: str | Path | None = None,
        environ: Mapping[str, str] | None = None,
        overrides: Mapping[str, object] | None = None,
        cwd: Path | None = None,
    ) -> Settings:
        """Load settings using explicit values, environment, TOML, then defaults."""
        return load_settings(
            config_path=config_path,
            environ=environ,
            overrides=overrides,
            cwd=cwd,
        )


def load_settings(
    *,
    config_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    overrides: Mapping[str, object] | None = None,
    cwd: Path | None = None,
) -> Settings:
    """Load core settings without accepting unknown or untyped configuration."""
    active_environment = os.environ if environ is None else environ
    base_directory = Path.cwd() if cwd is None else cwd
    file_path, file_is_explicit = _select_config_path(
        config_path, active_environment, base_directory
    )

    values: dict[str, object] = {}
    if file_path is not None:
        if not file_path.exists():
            if file_is_explicit:
                raise ConfigurationError(f"configuration file does not exist: {file_path}")
        else:
            values = _load_toml(file_path)

    values = _deep_merge(values, _environment_values(active_environment))
    if overrides is not None:
        values = _deep_merge(values, overrides)
    return _settings_from_mapping(values)


def _select_config_path(
    config_path: str | Path | None,
    environ: Mapping[str, str],
    cwd: Path,
) -> tuple[Path | None, bool]:
    if config_path is not None:
        return _resolve_path(config_path, cwd), True
    if configured_path := environ.get(_CONFIG_ENVIRONMENT_VARIABLE):
        return _resolve_path(configured_path, cwd), True
    return cwd / "xyberos.toml", False


def _resolve_path(value: str | Path, cwd: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else cwd / path


def _load_toml(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as file:
            contents = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(f"unable to read configuration file: {path}") from error
    return cast(dict[str, object], contents)


def _environment_values(environ: Mapping[str, str]) -> dict[str, object]:
    values: dict[str, object] = {}
    for name, value in environ.items():
        if name == _CONFIG_ENVIRONMENT_VARIABLE or not name.startswith(_CONFIG_PREFIX):
            continue
        parts = name.removeprefix(_CONFIG_PREFIX).lower().split("__")
        if not all(parts):
            raise ConfigurationError(f"invalid environment setting name: {name}")
        cursor = values
        for part in parts[:-1]:
            existing = cursor.setdefault(part, {})
            if not isinstance(existing, dict):
                raise ConfigurationError(f"conflicting environment setting: {name}")
            cursor = existing
        cursor[parts[-1]] = value
    return values


def _deep_merge(base: Mapping[str, object], override: Mapping[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key, override_value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, Mapping) and isinstance(override_value, Mapping):
            merged[key] = _deep_merge(
                cast(Mapping[str, object], base_value),
                cast(Mapping[str, object], override_value),
            )
        else:
            merged[key] = override_value
    return merged


def _settings_from_mapping(values: Mapping[str, object]) -> Settings:
    _reject_unknown_keys(values, {"schema_version", "app"}, "root")
    schema_version = _as_int(
        values.get("schema_version", _SUPPORTED_SCHEMA_VERSION), "schema_version"
    )
    if schema_version != _SUPPORTED_SCHEMA_VERSION:
        raise ConfigurationError(
            f"unsupported configuration schema_version: {schema_version}; "
            f"expected {_SUPPORTED_SCHEMA_VERSION}"
        )

    app_values = values.get("app", {})
    if not isinstance(app_values, Mapping):
        raise ConfigurationError("app must be a table/object")
    typed_app_values = cast(Mapping[str, object], app_values)
    _reject_unknown_keys(
        typed_app_values,
        {"name", "environment", "debug", "shutdown_timeout"},
        "app",
    )
    return Settings(
        schema_version=schema_version,
        app=AppSettings(
            name=_as_non_empty_string(typed_app_values.get("name", "xyberos"), "app.name"),
            environment=_as_non_empty_string(
                typed_app_values.get("environment", "development"), "app.environment"
            ),
            debug=_as_bool(typed_app_values.get("debug", False), "app.debug"),
            shutdown_timeout=_as_optional_timeout(
                typed_app_values.get("shutdown_timeout"), "app.shutdown_timeout"
            ),
        ),
    )


def _reject_unknown_keys(values: Mapping[str, object], allowed: set[str], location: str) -> None:
    unknown_keys = sorted(set(values) - allowed)
    if unknown_keys:
        joined_keys = ", ".join(unknown_keys)
        raise ConfigurationError(f"unknown setting(s) at {location}: {joined_keys}")


def _as_non_empty_string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{location} must be a non-empty string")
    return value


def _as_optional_timeout(value: object, location: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ConfigurationError(f"{location} must be a positive number of seconds")
    if isinstance(value, int | float):
        timeout = float(value)
    elif isinstance(value, str):
        try:
            timeout = float(value.strip())
        except ValueError as error:
            raise ConfigurationError(f"{location} must be a positive number of seconds") from error
    else:
        raise ConfigurationError(f"{location} must be a positive number of seconds")
    if timeout <= 0:
        raise ConfigurationError(f"{location} must be greater than zero")
    return timeout


def _as_bool(value: object, location: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ConfigurationError(f"{location} must be a boolean")


def _as_int(value: object, location: str) -> int:
    if isinstance(value, bool):
        raise ConfigurationError(f"{location} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as error:
            raise ConfigurationError(f"{location} must be an integer") from error
    raise ConfigurationError(f"{location} must be an integer")
