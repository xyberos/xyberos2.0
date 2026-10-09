from __future__ import annotations

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
        self.subsystems

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

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "KernelConfig":
        if not isinstance(config, dict):
            raise ConfigurationError("Kernel configuration must be provided as a dictionary.")
        return cls(raw=dict(config))
