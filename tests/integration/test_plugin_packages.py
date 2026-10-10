"""A separately packaged plugin and the custom-plugin example work through the public API."""

import asyncio
import re
from pathlib import Path

import pytest
from xyberos_plugin_metrics import Metrics, MetricsPlugin, SummaryPlugin

import xyberos
from xyberos import App, Settings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

PACKAGE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "metrics_plugin" / "xyberos_plugin_metrics"
)
PUBLIC_IMPORT = re.compile(r"^\s*(?:from|import)\s+(xyberos[\w.]*)", re.MULTILINE)
PUBLIC_NAMES = re.compile(r"from xyberos import ([^\n]+)")


def plugin_app(**plugin_settings: object) -> App:
    overrides = {"plugins": {"metrics": plugin_settings}} if plugin_settings else {}
    app = App(settings=Settings.load(environ={}, overrides=overrides))
    return app


def test_fixture_plugin_supplies_a_service_and_routes() -> None:
    app = plugin_app(prefix="req")
    plugin = MetricsPlugin()
    app.add_plugin(plugin)
    app.add_plugin(SummaryPlugin())

    with create_test_client(HttpAdapter(app)) as client:
        assert client.get("/metrics").json() == {"prefix": "req", "events": []}
        assert client.get("/metrics/summary").json() == {"count": 0}

    assert plugin.started is True
    assert plugin.stopped is True


def test_fixture_plugin_order_is_deterministic_and_visible() -> None:
    app = plugin_app()
    app.add_plugin(MetricsPlugin())
    app.add_plugin(SummaryPlugin())

    plugins = app.diagnostics().plugins

    assert [info.name for info in plugins] == ["metrics", "summary"]
    assert plugins[0].state.value == "registered"
    assert plugins[1].requires == ("metrics",)
    assert "summary 1 [registered] requires: metrics" in app.diagnostics().render()


def test_fixture_plugin_uses_only_public_xyberos_api() -> None:
    modules: set[str] = set()
    names: set[str] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        modules.update(match.group(1) for match in PUBLIC_IMPORT.finditer(text))
        for match in PUBLIC_NAMES.finditer(text):
            names.update(part.strip() for part in match.group(1).split(","))

    assert modules == {"xyberos"}, "a plugin must not import runtime internals"
    assert names, "the fixture should import public plugin API"
    assert names <= set(xyberos.__all__)


def test_fixture_plugin_provides_an_injectable_service() -> None:
    app = plugin_app(limit=2)
    app.add_plugin(MetricsPlugin())

    async def scenario() -> None:
        await app.start()
        metrics = await app.resolve(Metrics)
        metrics.record("a")
        metrics.record("b")
        metrics.record("c")
        assert metrics.events == ["b", "c"]
        await app.stop()

    asyncio.run(scenario())


def test_custom_plugin_example_serves_a_route() -> None:
    from custom_plugin.app import create_app

    app = create_app({"greeting": "hey", "excited": True})

    with create_test_client(HttpAdapter(app)) as client:
        assert client.get("/greet").json() == {"message": "hey, world!"}


def test_custom_plugin_example_reads_plugin_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_plugin.app import create_app

    monkeypatch.setenv("XYBEROS_PLUGINS__GREETING__GREETING", "hi")
    monkeypatch.setenv("XYBEROS_PLUGINS__GREETING__EXCITED", "true")
    app = create_app()

    with create_test_client(HttpAdapter(app)) as client:
        assert client.get("/greet").json() == {"message": "hi, world!"}
