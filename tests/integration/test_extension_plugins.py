"""The plugin page's claims are exercised against a plugin written the way the page teaches.

``examples/learn_extend/plugin_audit.py`` is the module behind `site/extend/plugins.md`: two
plugins in one module, typed configuration, routes, lifecycle hooks, and a requirement between
them.
"""

import asyncio
from pathlib import Path

import pytest
from learn_extend.plugin_audit import AuditConfig, AuditLog, AuditPlugin, ReportsPlugin

from xyberos import App, Settings
from xyberos.errors import (
    PluginCompatibilityError,
    PluginConfigurationError,
    PluginDependencyError,
    PluginValidationError,
)
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

#: The distribution the plugins page points at as the packaging pattern to copy.
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "metrics_plugin"


def settings_for(plugin_options: dict[str, object] | None = None) -> Settings:
    """Return settings with an optional ``[plugins.audit]`` section."""
    overrides = {"plugins": {"audit": plugin_options}} if plugin_options else {}
    return Settings.load(environ={}, overrides=overrides)


def test_a_plugin_contributes_a_service_and_routes_and_is_attributed() -> None:
    app = App(settings=settings_for({"prefix": "req", "limit": 2}))
    app.add_plugin(AuditPlugin())

    with create_test_client(HttpAdapter(app)) as client:
        for event in ("ticket-opened", "reply-drafted", "reply-sent"):
            client.post("/audit", json={"event": event})
        assert client.get("/audit").json() == {
            "prefix": "req",
            "events": ["reply-drafted", "reply-sent"],
        }

    providers = app.diagnostics().providers
    assert [(info.contract, info.source) for info in providers] == [("AuditLog", "plugin:audit")]


def test_a_plugin_is_configurable_from_settings_and_from_an_explicit_mapping() -> None:
    configured = AuditPlugin()
    from_settings = App(settings=settings_for({"prefix": "req"}))
    from_settings.add_plugin(configured)

    explicit = App(settings=settings_for({"prefix": "req"}))
    explicit.add_plugin(AuditPlugin(), config={"prefix": "explicit", "limit": 5})

    async def scenario() -> None:
        await from_settings.start()
        await explicit.start()
        from_a_file = await from_settings.resolve(AuditLog)
        from_an_argument = await explicit.resolve(AuditLog)
        await from_settings.stop()
        await explicit.stop()

        assert from_a_file.prefix == "req"
        assert from_an_argument.prefix == "explicit"
        assert configured.started is True
        assert configured.stopped is True

    asyncio.run(scenario())


def test_a_requirement_must_already_be_registered() -> None:
    app = App()
    with pytest.raises(PluginDependencyError, match="requires audit"):
        app.add_plugin(ReportsPlugin())

    app.add_plugin(AuditPlugin())
    app.add_plugin(ReportsPlugin())
    assert [info.name for info in app.diagnostics().plugins] == ["audit", "reports"]
    assert app.diagnostics().plugins[1].requires == ("audit",)


def test_configuration_mistakes_are_refused_before_register_runs() -> None:
    class PlainPlugin(AuditPlugin):
        name = "plain"
        config_type = None

    with pytest.raises(PluginConfigurationError, match="unknown configuration key"):
        App(settings=settings_for({"prefx": "typo"})).add_plugin(AuditPlugin())

    with pytest.raises(PluginConfigurationError, match="declares no config_type"):
        App().add_plugin(PlainPlugin(), config={"prefix": "req"})


def test_plugin_metadata_is_validated() -> None:
    class FuturePlugin(AuditPlugin):
        name = "future"
        api_version = "2"

    with pytest.raises(PluginCompatibilityError, match="this runtime supports"):
        App().add_plugin(FuturePlugin())

    app = App()
    app.add_plugin(AuditPlugin())
    with pytest.raises(PluginValidationError, match="already registered"):
        app.add_plugin(AuditPlugin())


def test_the_summary_plugin_reads_what_the_audit_plugin_registered() -> None:
    app = App(settings=settings_for({"limit": 1}))
    app.add_plugin(AuditPlugin())
    app.add_plugin(ReportsPlugin())

    with create_test_client(HttpAdapter(app)) as client:
        client.post("/audit", json={"event": "first"})
        client.post("/audit", json={"event": "second"})
        assert client.get("/reports").json() == {"count": 1}


def test_the_audit_config_schema_is_the_dataclass_the_page_shows() -> None:
    """The page says configuration arrives as a typed object, not a dictionary."""
    assert AuditConfig() == AuditConfig(prefix="audit", limit=100)
    with pytest.raises(TypeError):
        AuditConfig(prefix="audit", limit=100, unexpected=True)  # type: ignore[call-arg]


def test_the_fixture_distribution_declares_the_plugin_it_ships() -> None:
    """The distribution the page tells a reader to copy is one, and depends only on xyberos."""
    manifest = (FIXTURE / "pyproject.toml").read_text(encoding="utf-8")

    assert 'name = "xyberos-plugin-metrics"' in manifest
    assert 'dependencies = ["xyberos"]' in manifest
    assert 'packages = ["xyberos_plugin_metrics"]' in manifest
