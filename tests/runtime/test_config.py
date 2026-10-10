"""Typed configuration loading, precedence, and validation."""

from pathlib import Path

import pytest

from xyberos import ConfigurationError, Settings


def test_defaults_are_used_when_nothing_is_configured(tmp_path: Path) -> None:
    settings = Settings.load(environ={}, cwd=tmp_path)

    assert settings.schema_version == 1
    assert settings.app.name == "xyberos"
    assert settings.app.environment == "development"
    assert settings.app.debug is False


def test_explicit_arguments_beat_environment_which_beats_file(tmp_path: Path) -> None:
    (tmp_path / "xyberos.toml").write_text(
        '[app]\nname = "from-file"\nenvironment = "staging"\n',
        encoding="utf-8",
    )

    settings = Settings.load(
        environ={"XYBEROS_APP__NAME": "from-environment"},
        overrides={"app": {"name": "from-override"}},
        cwd=tmp_path,
    )

    assert settings.app.name == "from-override"
    assert settings.app.environment == "staging"


def test_environment_beats_file_without_an_override(tmp_path: Path) -> None:
    (tmp_path / "xyberos.toml").write_text('[app]\nname = "from-file"\n', encoding="utf-8")

    settings = Settings.load(environ={"XYBEROS_APP__NAME": "from-environment"}, cwd=tmp_path)

    assert settings.app.name == "from-environment"


def test_boolean_values_accept_documented_environment_spellings(tmp_path: Path) -> None:
    settings = Settings.load(environ={"XYBEROS_APP__DEBUG": "true"}, cwd=tmp_path)

    assert settings.app.debug is True


def test_explicit_config_path_must_exist(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        Settings.load(config_path=tmp_path / "missing.toml", environ={}, cwd=tmp_path)


def test_config_path_can_come_from_the_environment(tmp_path: Path) -> None:
    config = tmp_path / "custom.toml"
    config.write_text('[app]\nname = "custom"\n', encoding="utf-8")

    settings = Settings.load(environ={"XYBEROS_CONFIG": str(config)}, cwd=tmp_path)

    assert settings.app.name == "custom"


def test_unknown_keys_are_rejected_at_every_level(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError) as root:
        Settings.load(environ={}, overrides={"unknown": True}, cwd=tmp_path)
    assert "unknown" in str(root.value)

    with pytest.raises(ConfigurationError) as nested:
        Settings.load(environ={}, overrides={"app": {"unknown": True}}, cwd=tmp_path)
    assert "unknown" in str(nested.value)


def test_unsupported_schema_version_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        Settings.load(environ={}, overrides={"schema_version": 2}, cwd=tmp_path)


def test_invalid_value_types_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        Settings.load(environ={}, overrides={"app": {"debug": "sometimes"}}, cwd=tmp_path)

    with pytest.raises(ConfigurationError):
        Settings.load(environ={}, overrides={"app": {"name": "   "}}, cwd=tmp_path)

    with pytest.raises(ConfigurationError):
        Settings.load(environ={}, overrides={"app": "not-a-table"}, cwd=tmp_path)


def test_invalid_environment_names_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        Settings.load(environ={"XYBEROS_": "value"}, cwd=tmp_path)


def test_conflicting_environment_settings_are_rejected(tmp_path: Path) -> None:
    environ = {"XYBEROS_APP": "value", "XYBEROS_APP__NAME": "name"}

    with pytest.raises(ConfigurationError):
        Settings.load(environ=environ, cwd=tmp_path)


def test_numeric_strings_are_accepted_but_booleans_are_not(tmp_path: Path) -> None:
    settings = Settings.load(environ={"XYBEROS_SCHEMA_VERSION": "1"}, cwd=tmp_path)

    assert settings.schema_version == 1
    with pytest.raises(ConfigurationError):
        Settings.load(environ={}, overrides={"schema_version": True}, cwd=tmp_path)


def test_shutdown_timeout_is_optional_and_validated(tmp_path: Path) -> None:
    assert Settings.load(environ={}, cwd=tmp_path).app.shutdown_timeout is None
    assert (
        Settings.load(
            environ={"XYBEROS_APP__SHUTDOWN_TIMEOUT": "2.5"}, cwd=tmp_path
        ).app.shutdown_timeout
        == 2.5
    )

    for invalid in (0, -1, "soon", True):
        with pytest.raises(ConfigurationError):
            Settings.load(
                environ={}, overrides={"app": {"shutdown_timeout": invalid}}, cwd=tmp_path
            )
