"""Plugin configuration sections follow the same precedence as core settings."""

from pathlib import Path

import pytest

from xyberos import ConfigurationError, Settings


def test_plugin_sections_come_from_the_configuration_file(tmp_path: Path) -> None:
    (tmp_path / "xyberos.toml").write_text(
        '[plugins.metrics]\nprefix = "req"\nlimit = 5\n', encoding="utf-8"
    )

    settings = Settings.load(environ={}, cwd=tmp_path)

    assert settings.plugin_options("metrics") == {"prefix": "req", "limit": 5}


def test_plugin_sections_come_from_the_environment(tmp_path: Path) -> None:
    settings = Settings.load(environ={"XYBEROS_PLUGINS__METRICS__LIMIT": "7"}, cwd=tmp_path)

    assert settings.plugin_options("metrics") == {"limit": "7"}


def test_environment_overrides_the_configuration_file(tmp_path: Path) -> None:
    (tmp_path / "xyberos.toml").write_text("[plugins.metrics]\nlimit = 5\n", encoding="utf-8")

    settings = Settings.load(environ={"XYBEROS_PLUGINS__METRICS__LIMIT": "9"}, cwd=tmp_path)

    assert settings.plugin_options("metrics") == {"limit": "9"}


def test_plugin_lookup_is_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "xyberos.toml").write_text("[plugins.Metrics]\nlimit = 5\n", encoding="utf-8")

    settings = Settings.load(environ={}, cwd=tmp_path)

    assert settings.plugins == {"metrics": {"limit": 5}}
    assert settings.plugin_options("Metrics") == {"limit": 5}


def test_unknown_and_absent_plugin_sections_are_tolerated(tmp_path: Path) -> None:
    settings = Settings.load(environ={}, overrides={"plugins": {"unused": {"a": 1}}}, cwd=tmp_path)

    assert settings.plugin_options("unused") == {"a": 1}
    assert settings.plugin_options("absent") == {}


def test_malformed_plugin_sections_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        Settings.load(environ={}, overrides={"plugins": "not-a-table"}, cwd=tmp_path)

    with pytest.raises(ConfigurationError):
        Settings.load(environ={}, overrides={"plugins": {"metrics": 5}}, cwd=tmp_path)
