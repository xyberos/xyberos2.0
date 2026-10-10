"""Build a plugin's typed configuration from validated settings.

Plugin configuration follows the same precedence as core settings: an explicit mapping passed to
``App.add_plugin``, then the environment, then ``[plugins.<name>]`` in the configuration file, then
the dataclass defaults. Error messages name the plugin and the offending key and never echo the
configured value.
"""

from __future__ import annotations

import dataclasses
import types
import typing
from collections.abc import Callable, Mapping
from typing import TypeVar, get_args, get_origin, get_type_hints

from xyberos.config import _as_bool, _as_float, _as_int
from xyberos.errors import ConfigurationError, PluginConfigurationError, PluginValidationError

T = TypeVar("T")


def build_plugin_config(
    config_type: type[object] | None,
    values: Mapping[str, object],
    *,
    plugin: str,
) -> object | None:
    """Return a plugin's typed configuration object, or ``None`` when it declares no schema."""
    if config_type is None:
        if values:
            listed = ", ".join(sorted(values))
            raise PluginConfigurationError(
                f"plugin {plugin!r} received configuration but declares no config_type: {listed}",
                plugin=plugin,
            )
        return None
    if not dataclasses.is_dataclass(config_type):
        raise PluginValidationError(
            f"plugin {plugin!r} config_type must be a dataclass", plugin=plugin
        )

    fields = {field.name: field for field in dataclasses.fields(config_type)}
    unknown = sorted(set(values) - set(fields))
    if unknown:
        listed = ", ".join(unknown)
        raise PluginConfigurationError(
            f"plugin {plugin!r} received unknown configuration key(s): {listed}", plugin=plugin
        )

    annotations = get_type_hints(config_type)
    arguments: dict[str, object] = {}
    for name, field in fields.items():
        location = f"plugins.{plugin}.{name}"
        if name in values:
            arguments[name] = _coerce(values[name], annotations.get(name), location, plugin=plugin)
        elif field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING:
            raise PluginConfigurationError(
                f"plugin {plugin!r} is missing the required setting {location!r}", plugin=plugin
            )

    try:
        return config_type(**arguments)
    except (TypeError, ValueError) as error:
        raise PluginConfigurationError(
            f"plugin {plugin!r} configuration could not be built", plugin=plugin
        ) from error


def _coerce(value: object, annotation: object, location: str, *, plugin: str) -> object:
    optional, inner = _unwrap_optional(annotation)
    if value is None:
        if optional:
            return None
        raise PluginConfigurationError(f"{location} must not be null", plugin=plugin)
    if inner is str:
        if not isinstance(value, str):
            raise PluginConfigurationError(f"{location} must be a string", plugin=plugin)
        return value
    if inner is bool:
        return _translate(_as_bool, value, location, plugin=plugin)
    if inner is int:
        return _translate(_as_int, value, location, plugin=plugin)
    if inner is float:
        return _translate(_as_float, value, location, plugin=plugin)
    raise PluginValidationError(
        f"plugin {plugin!r} setting {location} uses an unsupported type {inner!r}; "
        "use str, int, float, or bool",
        plugin=plugin,
    )


def _translate(
    convert: Callable[[object, str], T], value: object, location: str, *, plugin: str
) -> T:
    try:
        return convert(value, location)
    except ConfigurationError as error:
        raise PluginConfigurationError(
            f"plugin {plugin!r} has an invalid setting: {error}", plugin=plugin
        ) from error


def _unwrap_optional(annotation: object) -> tuple[bool, object]:
    origin = get_origin(annotation)
    if origin is types.UnionType or origin is typing.Union:
        arguments = get_args(annotation)
        if len(arguments) == 2 and type(None) in arguments:
            inner = arguments[0] if arguments[1] is type(None) else arguments[1]
            return True, inner
    return False, annotation
