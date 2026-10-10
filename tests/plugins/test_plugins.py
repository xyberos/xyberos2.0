"""Plugin registration, ordering, configuration, lifecycle, and diagnostics."""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated

import pytest

from xyberos import (
    App,
    Diagnostics,
    Inject,
    LifecycleState,
    LifecycleStateError,
    Plugin,
    PluginCompatibilityError,
    PluginConfigurationError,
    PluginDependencyError,
    PluginLifecycleError,
    PluginState,
    PluginValidationError,
    RegistrationError,
    Settings,
    ShutdownError,
)


class Recorder:
    """Shared event log so tests can assert plugin ordering."""

    def __init__(self) -> None:
        self.events: list[str] = []


class Service:
    def __init__(self, name: str) -> None:
        self.name = name


@dataclass(frozen=True)
class ServiceConfig:
    name: str = "default"
    retries: int = 1
    enabled: bool = True
    ratio: float = 0.5


def new_app(overrides: Mapping[str, object] | None = None) -> App:
    return App(settings=Settings.load(environ={}, overrides=overrides))


class SimplePlugin(Plugin[ServiceConfig]):
    name = "simple"
    config_type = ServiceConfig

    def __init__(self, recorder: Recorder) -> None:
        self._recorder = recorder
        self.config: ServiceConfig | None = None

    def register(self, app: App, config: ServiceConfig) -> None:
        self.config = config
        self._recorder.events.append("register:simple")
        app.provide(Service, instance=Service(config.name))

    async def start(self) -> None:
        self._recorder.events.append("start:simple")

    async def stop(self) -> None:
        self._recorder.events.append("stop:simple")


class DependentPlugin(Plugin[None]):
    name = "dependent"
    requires = ("simple",)
    config_type = None

    def __init__(self, recorder: Recorder) -> None:
        self._recorder = recorder

    def register(self, app: App, config: None) -> None:
        self._recorder.events.append("register:dependent")

    async def start(self) -> None:
        self._recorder.events.append("start:dependent")

    async def stop(self) -> None:
        self._recorder.events.append("stop:dependent")


class FailingStartPlugin(Plugin[None]):
    name = "failing"
    config_type = None

    def __init__(self, recorder: Recorder, *, fail_stop: bool = False) -> None:
        self._recorder = recorder
        self._fail_stop = fail_stop

    def register(self, app: App, config: None) -> None:
        self._recorder.events.append("register:failing")

    async def start(self) -> None:
        raise RuntimeError("start exploded")

    async def stop(self) -> None:
        if self._fail_stop:
            raise RuntimeError("stop exploded while cleaning up")
        self._recorder.events.append("stop:failing")


class FailingStopPlugin(Plugin[None]):
    name = "failing-stop"
    config_type = None

    def register(self, app: App, config: None) -> None:
        return None

    async def stop(self) -> None:
        raise RuntimeError("stop exploded")


class NoSchemaPlugin(Plugin[None]):
    name = "no-schema"
    config_type = None

    def register(self, app: App, config: None) -> None:
        return None


class LateRoutePlugin(Plugin[None]):
    name = "late"
    config_type = None

    def __init__(self) -> None:
        self._app: App | None = None

    def register(self, app: App, config: None) -> None:
        self._app = app

    async def start(self) -> None:
        assert self._app is not None
        self._app.get("/late")(self._handler)

    async def _handler(self) -> None:
        return None


class DuplicateProviderPlugin(Plugin[None]):
    name = "duplicate-provider"
    config_type = None

    def register(self, app: App, config: None) -> None:
        app.provide(Service, instance=Service("plugin"))


def test_plugin_contributes_a_service() -> None:
    app = new_app()
    plugin = SimplePlugin(Recorder())

    app.add_plugin(plugin)

    assert app.diagnostics().plugins[0].name == "simple"

    async def scenario() -> None:
        await app.start()
        service = await app.resolve(Service)
        assert service.name == "default"
        await app.stop()

    asyncio.run(scenario())


def test_plugin_lifecycle_runs_in_dependency_order() -> None:
    app = new_app()
    recorder = Recorder()
    app.add_plugin(SimplePlugin(recorder))
    app.add_plugin(DependentPlugin(recorder))

    async def scenario() -> None:
        await app.start()
        assert app.diagnostics().plugins[0].state is PluginState.STARTED
        await app.stop()

    asyncio.run(scenario())

    assert recorder.events == [
        "register:simple",
        "register:dependent",
        "start:simple",
        "start:dependent",
        "stop:dependent",
        "stop:simple",
    ]


def test_dependent_plugin_requires_its_dependency_first() -> None:
    app = new_app()

    with pytest.raises(PluginDependencyError) as info:
        app.add_plugin(DependentPlugin(Recorder()))

    assert info.value.plugin == "dependent"
    assert "must be registered first" in str(info.value)


def test_duplicate_plugin_name_is_rejected() -> None:
    recorder = Recorder()
    app = new_app()
    app.add_plugin(SimplePlugin(recorder))

    with pytest.raises(PluginValidationError) as info:
        app.add_plugin(SimplePlugin(recorder))

    assert "already registered" in str(info.value)


def test_incompatible_api_version_is_rejected_before_register() -> None:
    registered: list[str] = []

    class FuturePlugin(Plugin[None]):
        name = "future"
        api_version = "2"
        config_type = None

        def register(self, app: App, config: None) -> None:
            registered.append("called")

    with pytest.raises(PluginCompatibilityError) as info:
        new_app().add_plugin(FuturePlugin())

    assert info.value.plugin == "future"
    assert info.value.phase == "registration"
    assert registered == []


@pytest.mark.parametrize(
    "metadata",
    [
        {"name": ""},
        {"name": "not an identifier"},
        {"name": "ok", "api_version": ""},
        {"name": "ok", "requires": ["ok"]},
    ],
)
def test_malformed_metadata_is_rejected(metadata: dict[str, object]) -> None:
    class Malformed(Plugin[None]):
        config_type = None

        def register(self, app: App, config: None) -> None:
            return None

    for key, value in metadata.items():
        setattr(Malformed, key, value)

    with pytest.raises(PluginValidationError):
        new_app().add_plugin(Malformed())


def test_config_type_must_be_a_dataclass() -> None:
    class BadConfigPlugin(Plugin[object]):
        name = "bad-config"
        config_type = dict

        def register(self, app: App, config: object) -> None:
            return None

    with pytest.raises(PluginValidationError) as info:
        new_app().add_plugin(BadConfigPlugin())

    assert "config_type must be a dataclass" in str(info.value)


def test_config_is_validated_and_never_echoed() -> None:
    app = new_app()

    with pytest.raises(PluginConfigurationError) as unknown:
        app.add_plugin(SimplePlugin(Recorder()), config={"nope": 1})
    assert "unknown configuration key(s): nope" in str(unknown.value)
    assert "1" not in str(unknown.value).split("key(s):")[1]

    with pytest.raises(PluginConfigurationError) as invalid:
        app.add_plugin(SimplePlugin(Recorder()), config={"retries": "many"})
    assert "invalid setting" in str(invalid.value)
    assert "many" not in str(invalid.value)

    with pytest.raises(PluginConfigurationError):
        new_app().add_plugin(SimplePlugin(Recorder()), config={"sub": {"nested": True}})


def test_explicit_config_wins_over_settings() -> None:
    app = new_app({"plugins": {"simple": {"name": "from-settings", "enabled": "true"}}})
    with_settings = SimplePlugin(Recorder())
    app.add_plugin(with_settings)

    assert with_settings.config is not None
    assert with_settings.config.name == "from-settings"
    assert with_settings.config.enabled is True

    app2 = new_app({"plugins": {"simple": {"name": "from-settings"}}})
    explicit = SimplePlugin(Recorder())
    app2.add_plugin(explicit, config={"name": "explicit", "retries": 3, "ratio": 1.5})

    assert explicit.config is not None
    assert (explicit.config.name, explicit.config.retries, explicit.config.ratio) == (
        "explicit",
        3,
        1.5,
    )


def test_config_for_a_plugin_without_a_schema_is_rejected() -> None:
    with pytest.raises(PluginConfigurationError) as info:
        new_app().add_plugin(NoSchemaPlugin(), config={"anything": True})

    assert "declares no config_type" in str(info.value)


def test_partial_startup_cleanup_stops_started_plugins() -> None:
    recorder = Recorder()
    app = new_app()
    app.add_plugin(SimplePlugin(recorder))
    app.add_plugin(FailingStartPlugin(recorder))

    async def scenario() -> None:
        with pytest.raises(PluginLifecycleError) as info:
            await app.start()

        assert app.state is LifecycleState.FAILED
        assert info.value.plugin == "failing"
        assert info.value.phase == "start"
        assert isinstance(info.value.__cause__, RuntimeError)

    asyncio.run(scenario())

    assert recorder.events == [
        "register:simple",
        "register:failing",
        "start:simple",
        "stop:simple",
    ]


def test_startup_cleanup_reports_a_failing_stop_hook() -> None:
    recorder = Recorder()
    app = new_app()
    app.add_plugin(SimplePlugin(recorder))
    app.add_plugin(FailingStopPlugin())
    app.add_plugin(FailingStartPlugin(recorder))

    async def scenario() -> None:
        with pytest.raises(PluginLifecycleError) as info:
            await app.start()

        assert "cleanup also failed for" in str(info.value)
        assert "plugin:failing-stop" in str(info.value)

    asyncio.run(scenario())


def test_stop_failures_are_aggregated_into_shutdown_error() -> None:
    app = new_app()
    app.add_plugin(FailingStopPlugin())

    async def scenario() -> None:
        await app.start()
        with pytest.raises(ShutdownError) as info:
            await app.stop()

        assert info.value.resources == ("plugin:failing-stop",)
        assert app.state is LifecycleState.STOPPED

    asyncio.run(scenario())


def test_plugin_registration_is_rejected_after_start() -> None:
    app = new_app()
    app.add_plugin(SimplePlugin(Recorder()))

    async def scenario() -> None:
        await app.start()
        with pytest.raises(LifecycleStateError):
            app.add_plugin(DependentPlugin(Recorder()))
        await app.stop()

    asyncio.run(scenario())


def test_plugins_cannot_mutate_routes_after_readiness() -> None:
    app = new_app()
    app.add_plugin(LateRoutePlugin())

    async def scenario() -> None:
        with pytest.raises(PluginLifecycleError) as info:
            await app.start()

        assert isinstance(info.value.__cause__, LifecycleStateError)
        assert app.state is LifecycleState.FAILED

    asyncio.run(scenario())


def test_duplicate_provider_registration_from_a_plugin_fails() -> None:
    app = new_app()
    app.provide(Service, instance=Service("application"))

    with pytest.raises(PluginValidationError) as info:
        app.add_plugin(DuplicateProviderPlugin())

    assert isinstance(info.value.__cause__, RegistrationError)
    assert "duplicate-provider" in str(info.value)


def test_diagnostics_show_provider_sources_and_plugin_order() -> None:
    recorder = Recorder()
    app = new_app()
    app.provide(Recorder, instance=recorder)
    app.add_plugin(SimplePlugin(recorder), config={"name": "from-plugin"})

    diagnostics = app.diagnostics()

    assert isinstance(diagnostics, Diagnostics)
    sources = {provider.contract: provider.source for provider in diagnostics.providers}
    assert sources["Recorder"] == "application"
    assert sources["Service"] == "plugin:simple"
    assert [plugin.name for plugin in diagnostics.plugins] == ["simple"]
    assert "plugin:simple" in diagnostics.render()
    assert "simple 1 [registered]" in diagnostics.render()


def test_diagnostics_make_test_overrides_visible() -> None:
    app = new_app()
    app.provide(Service, instance=Service("application"))

    clone = app.with_overrides({Service: Service("override")})

    sources = {provider.contract: provider.source for provider in clone.diagnostics().providers}
    assert sources["Service"] == "test override"


def test_test_clones_start_without_plugin_registrations() -> None:
    recorder = Recorder()
    app = new_app()
    app.add_plugin(SimplePlugin(recorder))

    clone = app.with_overrides({})

    assert {provider.contract for provider in clone.diagnostics().providers} == {"Service"}
    assert [plugin.name for plugin in clone.diagnostics().plugins] == []


def test_plugin_provided_service_is_injectable() -> None:
    app = new_app()
    app.add_plugin(SimplePlugin(Recorder()))

    class Consumer:
        def __init__(self, service: Annotated[Service, Inject()]) -> None:
            self.service = service

    app.provide(Consumer)

    async def scenario() -> None:
        await app.start()
        consumer = await app.resolve(Consumer)
        assert consumer.service.name == "default"
        await app.stop()

    asyncio.run(scenario())
