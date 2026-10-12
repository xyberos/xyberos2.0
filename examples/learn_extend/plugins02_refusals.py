"""Walkthrough — the seven refusals a plugin author meets, and what each one means.

Run it with:

    python -m learn_extend.plugins02_refusals
"""

from __future__ import annotations

from dataclasses import dataclass

from learn_extend.plugin_audit import AuditPlugin, ReportsPlugin
from xyberos import App, Plugin, Settings
from xyberos.errors import (
    PluginCompatibilityError,
    PluginConfigurationError,
    PluginDependencyError,
    PluginValidationError,
)


class FuturePlugin(Plugin[None]):
    """A plugin written against a later plugin API version."""

    name = "future"
    api_version = "2"
    config_type = None

    def register(self, app: App, config: None) -> None: ...


class PunctuatedPlugin(Plugin[None]):
    """A plugin whose name is not an identifier, so ``[plugins.<name>]`` cannot address it."""

    name = "audit.log"
    api_version = "1"
    config_type = None

    def register(self, app: App, config: None) -> None: ...


@dataclass(frozen=True)
class WebhookConfig:
    """A configuration schema with one setting that has no default."""

    url: str


class WebhookPlugin(Plugin[WebhookConfig]):
    """A plugin that cannot work without the required setting."""

    name = "webhook"
    api_version = "1"
    config_type = WebhookConfig

    def register(self, app: App, config: WebhookConfig) -> None: ...


class PlainPlugin(Plugin[None]):
    """A plugin that declares no ``config_type``: passing it a mapping is a mistake, not a no-op."""

    name = "plain"
    api_version = "1"
    config_type = None

    def register(self, app: App, config: None) -> None: ...


class ExplodingPlugin(Plugin[None]):
    """A plugin whose ``register`` raises: the application is left exactly as it was."""

    name = "exploding"
    api_version = "1"
    config_type = None

    def register(self, app: App, config: None) -> None:
        raise RuntimeError("the plugin could not reach its database")


def main() -> None:
    """Try each mistake on a fresh application, and print what the runtime says about it."""
    app = App()
    try:
        app.add_plugin(ReportsPlugin())
    except PluginDependencyError as error:
        print("requirement registered second:", error)

    app = App()
    try:
        app.add_plugin(FuturePlugin())
    except PluginCompatibilityError as error:
        print("plugin from a later API:", error)

    app = App()
    try:
        app.add_plugin(PunctuatedPlugin())
    except PluginValidationError as error:
        print("name that is not an identifier:", error)

    app = App()
    app.add_plugin(AuditPlugin())
    try:
        app.add_plugin(AuditPlugin())
    except PluginValidationError as error:
        print("name registered twice:", error)

    settings = Settings.load(environ={}, overrides={"plugins": {"audit": {"prefx": "typo"}}})
    app = App(settings=settings)
    try:
        app.add_plugin(AuditPlugin())
    except PluginConfigurationError as error:
        print("misspelled setting in [plugins.audit]:", error)

    app = App()
    try:
        app.add_plugin(WebhookPlugin(), config={})
    except PluginConfigurationError as error:
        print("required setting with no value:", error)

    app = App()
    try:
        app.add_plugin(PlainPlugin(), config={"url": "x"})
    except PluginConfigurationError as error:
        print("configuration without a schema:", error)

    app = App()
    try:
        app.add_plugin(ExplodingPlugin())
    except PluginValidationError as error:
        print("register hook that raised:", error)

    print("the app that met the last refusal still has", len(app.diagnostics().plugins), "plugins")


if __name__ == "__main__":
    main()
