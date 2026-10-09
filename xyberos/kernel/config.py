from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping


class ConfigurationError(ValueError):
    """Raised when kernel configuration is invalid or incomplete."""


@dataclass
class KernelConfig:
    """Lightweight validated configuration wrapper for runtime bootstrap."""

    raw: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.raw, dict):
            raise ConfigurationError("Kernel configuration must be provided as a dictionary.")
        if "xyberos" in self.raw:
            self._validate_xyberos_keys(self.raw["xyberos"])
        self.subsystems
        self.shutdown_drain_timeout_seconds

    @property
    def shutdown_drain_timeout_seconds(self) -> float | None:
        base = self.raw.get("xyberos", self.raw)
        if not isinstance(base, Mapping):
            return None
        runtime = base.get("runtime", {})
        if not isinstance(runtime, Mapping):
            raise ConfigurationError("'runtime' configuration must be a mapping.")
        timeout = runtime.get("shutdown_drain_timeout_seconds")
        if timeout is None:
            return None
        if not _is_positive_finite_number(timeout):
            raise ConfigurationError(
                "'runtime.shutdown_drain_timeout_seconds' must be a positive finite number."
            )
        return float(timeout)

    @property
    def subsystems(self) -> Dict[str, Dict[str, Any]]:
        base = self.raw
        if "xyberos" in self.raw:
            base = self.raw["xyberos"]
            if not isinstance(base, Mapping):
                raise ConfigurationError("'xyberos' configuration must be a mapping.")

        subsystem_config = base.get("subsystems", {})
        if not isinstance(subsystem_config, Mapping):
            raise ConfigurationError("'subsystems' configuration must be a mapping.")

        validated: Dict[str, Dict[str, Any]] = {}
        for name, config in subsystem_config.items():
            if not isinstance(name, str) or not name.strip():
                raise ConfigurationError("Subsystem names must be non-empty strings.")
            if not isinstance(config, Mapping):
                raise ConfigurationError(
                    f"Configuration for subsystem '{name}' must be a mapping."
                )
            if "enabled" in config and not isinstance(config["enabled"], bool):
                raise ConfigurationError(
                    f"'enabled' for subsystem '{name}' must be a boolean."
                )
            validated[name] = dict(config)
        return validated

    @staticmethod
    def _validate_xyberos_keys(config: Any) -> None:
        if not isinstance(config, Mapping):
            raise ConfigurationError("'xyberos' configuration must be a mapping.")
        unknown = set(config) - {"runtime", "subsystems"}
        if unknown:
            keys = ", ".join(sorted(str(key) for key in unknown))
            raise ConfigurationError(f"Unknown key(s) in 'xyberos' configuration: {keys}.")
        runtime = config.get("runtime", {})
        if not isinstance(runtime, Mapping):
            raise ConfigurationError("'runtime' configuration must be a mapping.")
        unknown_runtime = set(runtime) - {"shutdown_drain_timeout_seconds"}
        if unknown_runtime:
            keys = ", ".join(sorted(str(key) for key in unknown_runtime))
            raise ConfigurationError(f"Unknown key(s) in 'xyberos.runtime' configuration: {keys}.")

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "KernelConfig":
        if not isinstance(config, dict):
            raise ConfigurationError("Kernel configuration must be provided as a dictionary.")
        return cls(raw=dict(config))


def _is_positive_finite_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False
