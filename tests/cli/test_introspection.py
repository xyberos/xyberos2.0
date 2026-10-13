"""`check --json`, `--why`, and `--schema`: what a script and an editor consume.

The documents are contracts (ADR 0020), so these tests are about facts rather than wording: which
keys exist, what can be null, that the same facts appear in the text report and in the JSON
document, and that the CLI reads its answers from the runtime's own snapshot instead of rebuilding
them. The document *version* and the top-level keys are pinned in `tests/test_compatibility.py`,
which is where a rename has to be argued for; the nested shape is pinned here, beside the code that
builds it.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Annotated, ClassVar

import pytest

from xyberos import PLUGIN_API_VERSION, App, Inject, Plugin, Settings
from xyberos.cli.check import check, config_schema, document, explain
from xyberos.cli.errors import CliError
from xyberos.cli.schema import SCHEMA_PATH, settings_schema

CONFIG = """\
schema_version = 1

[app]
name = "introspection"
environment = "testing"
debug = true
"""

# The shape ADR 0020 freezes. A key removed here breaks a consuming script, not just this test.
DOCUMENT_KEYS = {"document", "xyberos_version", "config_file", "settings", "application"}
APPLICATION_KEYS = {"target", "provider_graph", "providers", "plugins", "routes"}
PROVIDER_KEYS = {"contract", "scope", "eager", "source", "dependencies"}
PLUGIN_KEYS = {"name", "api_version", "requires", "state"}
ROUTES_KEYS = {"count", "compiled", "registered"}


class Database:
    """A dependency of the service, so `--why` has a path to print."""


class UserService:
    def __init__(self, database: Annotated[Database, Inject()]) -> None:
        self.database = database


@dataclasses.dataclass(frozen=True)
class AuditConfig:
    destination: str = "stdout"


class Audited(Plugin[AuditConfig]):
    """A plugin that registers nothing: this fixture exists for its metadata."""

    name = "audit"
    api_version = PLUGIN_API_VERSION
    requires: ClassVar[tuple[str, ...]] = ()
    config_type = AuditConfig

    def register(self, app: App, config: AuditConfig) -> None:
        """Register nothing, because the plugin's *section* is what this test is about."""


def create_app() -> App:
    """A composition root with one dependency, one eager provider, and one route."""
    app = App(settings=Settings.load())
    app.provide(Database, scope="app", eager=True)
    app.provide(UserService, scope="app", source="test_introspection")

    @app.get("/users/{user_id}")
    async def show_user(user_id: int) -> dict[str, str]:
        return {"user_id": str(user_id)}

    return app


def create_audited_app() -> App:
    """The same application with a plugin that declares a typed configuration section."""
    app = create_app()
    app.add_plugin(Audited())
    return app


def write_config(tmp_path: Path) -> Path:
    path = tmp_path / "xyberos.toml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


def test_the_document_without_an_application_still_describes_the_settings(tmp_path: Path) -> None:
    path = write_config(tmp_path)

    body = json.loads(document(config_path=path))

    assert body["document"] == 1
    assert body["config_file"] == str(path)
    assert body["settings"]["app"] == {
        "name": "introspection",
        "environment": "testing",
        "debug": True,
        "shutdown_timeout": None,
    }
    assert body["application"] is None, "nothing was inspected, so nothing is claimed"


def test_the_document_keys_are_the_versioned_contract(tmp_path: Path) -> None:
    """ADR 0020: a key added is additive, a key removed or renamed is a new document version."""
    body = json.loads(
        document(config_path=write_config(tmp_path), target="test_introspection:create_app")
    )
    application = body["application"]

    assert set(body) == DOCUMENT_KEYS
    assert set(application) == APPLICATION_KEYS
    assert set(application["providers"][0]) == PROVIDER_KEYS
    assert set(application["routes"]) == ROUTES_KEYS

    audited = json.loads(
        document(config_path=write_config(tmp_path), target="test_introspection:create_audited_app")
    )
    assert set(audited["application"]["plugins"][0]) == PLUGIN_KEYS


def test_the_document_reports_the_provider_graph_from_the_runtime_s_own_snapshot(
    tmp_path: Path,
) -> None:
    path = write_config(tmp_path)

    body = json.loads(document(config_path=path, target="test_introspection:create_app"))
    providers = {entry["contract"]: entry for entry in body["application"]["providers"]}

    assert body["application"]["provider_graph"] == "valid"
    assert providers["Database"]["scope"] == "app"
    assert providers["Database"]["eager"] is True
    assert providers["Database"]["source"] == "application"
    assert providers["UserService"]["source"] == "test_introspection"
    assert providers["UserService"]["dependencies"] == ["Database"]


def test_the_document_reports_the_route_table_and_whether_it_compiled(tmp_path: Path) -> None:
    body = json.loads(
        document(config_path=write_config(tmp_path), target="test_introspection:create_app")
    )
    routes = body["application"]["routes"]

    assert routes["count"] == 1
    assert routes["compiled"] is True
    assert routes["registered"] == [
        {
            "method": "GET",
            "path": "/users/{user_id}",
            "name": "show_user",
            "parameters": ["user_id"],
        }
    ]


def test_the_document_and_the_text_report_describe_the_same_application(tmp_path: Path) -> None:
    """Two renderings of one snapshot: a fact in one and not the other is a bug, not a style."""
    path = write_config(tmp_path)
    target = "test_introspection:create_app"

    text = check(config_path=path, target=target)
    body = json.loads(document(config_path=path, target=target))

    for provider in body["application"]["providers"]:
        assert provider["contract"] in text
        assert provider["source"] in text
    assert "provider graph: valid" in text
    assert f"routes: {body['application']['routes']['count']}" in text


def test_why_prints_the_resolution_path_and_the_scope_of_each_hop(tmp_path: Path) -> None:
    path = write_config(tmp_path)

    report = explain("UserService", config_path=path, target="test_introspection:create_app")

    lines = report.splitlines()
    assert lines[0] == "UserService [app] from test_introspection"
    assert lines[1].strip() == "Database [app, eager] from application"
    assert lines[1].startswith("  "), "a dependency is indented under the contract that needs it"


def test_why_accepts_a_bare_name_and_refuses_an_unknown_one_with_the_registered_list(
    tmp_path: Path,
) -> None:
    path = write_config(tmp_path)

    with pytest.raises(
        CliError, match="no provider is registered for 'Nope'.*Database, UserService"
    ):
        explain("Nope", config_path=path, target="test_introspection:create_app")


def test_why_without_an_application_says_what_to_pass(tmp_path: Path) -> None:
    with pytest.raises(CliError, match="--why needs an application"):
        explain("UserService", config_path=write_config(tmp_path))


def test_the_schema_without_an_application_is_the_file_that_ships() -> None:
    assert json.loads(config_schema()) == json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert json.loads(config_schema()) == settings_schema()


def test_the_schema_with_an_application_learns_its_plugins_sections() -> None:
    """The extension-point win: a plugin author gets completion for `[plugins.<name>]`."""
    schema = json.loads(config_schema(target="test_introspection:create_audited_app"))
    section = schema["properties"]["plugins"]["properties"]["audit"]

    assert section["additionalProperties"] is False
    assert section["properties"]["destination"]["type"] == "string"
