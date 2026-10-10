"""The AI assistant example runs against the fake provider, with no model or network."""

import asyncio

from ai_assistant.app import app_factory, build_asgi_app, create_app, fake_provider

from xyberos.ai import AIFacade, FakeModelProvider, ModelCapabilities, ModelReply, Usage
from xyberos.http.testing import create_test_client


def client_for(app):
    return create_test_client(build_asgi_app(app))


def test_the_default_profile_answers_every_route() -> None:
    client = client_for(create_app())

    with client:
        health = client.get("/health").json()
        asked = client.post("/ask", json={"question": "Will it rain?"}).json()
        researched = client.post("/research", json={"topic": "rain"}).json()
        triaged = client.post("/triage", json={"ticket": "T-100"}).json()

    assert health == {
        "provider": "fake",
        "model": "fake-model",
        "status": "ready",
        "detail": "",
    }
    assert asked == {
        "answer": "Take an umbrella.",
        "confidence": "high",
        "model": "fake-model",
        "tokens": 27,
    }
    assert researched["reply"] == "Rain is likely this afternoon."
    assert researched["rounds"] == 2
    assert researched["tools"] == ["knowledge"]
    assert triaged["reply"] == "A refund is on its way."
    assert triaged["steps"] == ["answer", "classify"]
    assert triaged["graph"] == "workflow 'ticket-triage' version='1'"


def test_the_plugin_registers_the_facade_so_diagnostics_name_it() -> None:
    app = create_app()

    rendered = app.diagnostics().render()

    assert "AIFacade [app, eager] from plugin:assistant" in rendered
    assert "assistant 1 [registered]" in rendered


def test_the_facade_is_resolvable_from_the_application() -> None:
    async def scenario() -> None:
        app = create_app()

        async with app.lifespan():
            resolved = await app.resolve(AIFacade)

            assert isinstance(resolved, AIFacade)
            assert resolved.name == "fake"

    asyncio.run(scenario())


def test_a_transient_model_failure_is_retried_by_the_workflow() -> None:
    provider = FakeModelProvider(
        [
            ModelReply.transient(),
            ModelReply.json_payload({"category": "refund"}),
            ModelReply.ok("A refund is being arranged."),
        ],
        capabilities=ModelCapabilities(tools=True, structured_output=True),
    )
    client = client_for(create_app(provider=provider))

    with client:
        triaged = client.post("/triage", json={"ticket": "T-200"}).json()

    assert triaged["reply"] == "A refund is being arranged."
    assert provider.calls == 3


def test_a_missing_field_is_a_safe_client_error() -> None:
    client = client_for(create_app())

    with client:
        response = client.post("/ask", json={"question": "   "})
        missing = client.post("/ask", json={})

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "provide a non-empty 'question'"
    assert missing.status_code == 422


def test_a_model_failure_never_leaks_its_message_to_the_client() -> None:
    provider = FakeModelProvider(
        [ModelReply.malformed(content="secret-model-output")],
        capabilities=ModelCapabilities(structured_output=True),
    )
    client = client_for(create_app(provider=provider))

    with client:
        response = client.post("/ask", json={"question": "Will it rain?"})

    assert response.status_code == 500
    assert "secret-model-output" not in response.text
    assert "not JSON" not in response.text


def test_the_example_uses_the_configured_profile() -> None:
    provider = FakeModelProvider([ModelReply.ok("scripted")])

    app = create_app({"provider": "fake", "model": "scripted-model"}, provider=provider)
    client = client_for(app)

    with client:
        assert client.get("/health").json()["model"] == "fake-model"


def test_the_application_closes_the_provider_on_shutdown() -> None:
    closed: list[str] = []

    class OwningProvider(FakeModelProvider):
        async def aclose(self) -> None:
            closed.append("closed")

    async def scenario() -> None:
        app = create_app(provider=OwningProvider([ModelReply.ok("scripted")]))

        async with app.lifespan():
            assert not closed

    asyncio.run(scenario())

    assert closed == ["closed"]


def test_the_factory_returns_an_asgi_application() -> None:
    assert callable(app_factory())


def test_the_scripted_provider_is_deterministic_across_runs() -> None:
    first = fake_provider()
    second = fake_provider()

    assert first.name == second.name == "fake"
    assert first.capabilities == second.capabilities
    assert first.capabilities.tools is True


def test_the_example_reports_token_usage_from_the_provider() -> None:
    provider = FakeModelProvider(
        [ModelReply.json_payload({"answer": "yes", "confidence": "low"}, usage=Usage(5, 5))],
        capabilities=ModelCapabilities(structured_output=True),
    )
    client = client_for(create_app(provider=provider))

    with client:
        asked = client.post("/ask", json={"question": "Anything?"}).json()

    assert asked["tokens"] == 10
