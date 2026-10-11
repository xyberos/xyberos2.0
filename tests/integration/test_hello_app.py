"""The hello app example runs, reads its own settings, and reports what it composed."""

from hello_app.app import CONFIG_DIRECTORY, Greeter, GreetingLog, create_app
from starlette.applications import Starlette

from xyberos import Scope, Settings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client


def test_the_example_reads_the_settings_file_next_to_it() -> None:
    settings = Settings.load(cwd=CONFIG_DIRECTORY)

    assert settings.app.name == "hello_app"


def test_the_example_answers_a_request() -> None:
    with create_test_client(HttpAdapter(create_app())) as client:
        response = client.get("/?name=reader")

        assert response.status_code == 200
        assert response.json()["greeting"] == "hello_app says hello, reader"


def test_the_example_echoes_the_correlation_id_it_was_given() -> None:
    with create_test_client(HttpAdapter(create_app())) as client:
        response = client.get("/", headers={"X-Request-ID": "trace-1"})

        assert response.headers["X-Request-ID"] == "trace-1"
        assert response.json()["correlation_id"] == "trace-1"


def test_the_example_reports_health_without_touching_a_service() -> None:
    with create_test_client(HttpAdapter(create_app())) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_the_example_scopes_its_services_and_can_be_inspected() -> None:
    app = create_app()

    scopes = {provider.contract: provider.scope for provider in app.diagnostics().providers}

    assert scopes[Greeter.__name__] == Scope.APP.value
    assert scopes[GreetingLog.__name__] == Scope.REQUEST.value
    assert "from application" in app.diagnostics().render()


def test_the_example_uses_the_name_its_settings_give_it() -> None:
    app = create_app(Settings.load(environ={}, overrides={"app": {"name": "renamed"}}))

    with create_test_client(HttpAdapter(app)) as client:
        assert client.get("/").json()["greeting"] == "renamed says hello, world"


def test_the_example_exposes_a_ready_asgi_application() -> None:
    from hello_app.app import asgi_app

    assert isinstance(asgi_app, Starlette)
    with create_test_client(asgi_app) as client:
        assert client.get("/health").json() == {"status": "ok"}
