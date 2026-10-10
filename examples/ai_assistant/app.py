"""An AI assistant wired through a plugin, dependency injection, and a workflow.

The default profile runs entirely against the deterministic fake provider, so running and testing
the example needs no model, no service, and no network. The Ollama profile is selected explicitly
and needs the ``ollama`` extra plus an already-pulled model.

Run it from the ``examples`` directory::

    python -m ai_assistant.app
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated

from starlette.applications import Starlette
from starlette.requests import Request

from xyberos import (
    App,
    Inject,
    Plugin,
    RequestValidationError,
    Retry,
    Settings,
    StepContext,
    Workflow,
    seconds,
)
from xyberos.ai import (
    AIFacade,
    ChatRequest,
    FakeModelProvider,
    LoggingPolicy,
    Message,
    ModelCapabilities,
    ModelReply,
    Tool,
    ToolCall,
    ToolSet,
    ToolSpec,
    Usage,
)
from xyberos.errors import AIConfigurationError
from xyberos.http import HttpAdapter, read_json_object

SYSTEM_PROMPT = "You are a concise support assistant. Answer in one sentence."

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["answer", "confidence"],
    "additionalProperties": False,
}
CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {"category": {"type": "string", "enum": ["refund", "question", "complaint"]}},
    "required": ["category"],
    "additionalProperties": False,
}
KNOWLEDGE_SCHEMA = {
    "type": "object",
    "properties": {"topic": {"type": "string"}},
    "required": ["topic"],
    "additionalProperties": False,
}


def fake_provider() -> FakeModelProvider:
    """Return a provider scripted for the order the demo calls it in.

    The script covers: a structured answer, a tool request plus its final answer, and a triage
    classification plus its reply. The last reply repeats, so extra calls still succeed.
    """
    return FakeModelProvider(
        [
            ModelReply.json_payload(
                {"answer": "Take an umbrella.", "confidence": "high"}, usage=Usage(18, 9)
            ),
            ModelReply.tools(
                ToolCall(name="knowledge", arguments={"topic": "rain"}), usage=Usage(14, 5)
            ),
            ModelReply.ok("Rain is likely this afternoon.", usage=Usage(21, 8)),
            ModelReply.json_payload({"category": "refund"}, usage=Usage(12, 4)),
            ModelReply.ok("A refund is on its way.", usage=Usage(20, 7)),
        ],
        capabilities=ModelCapabilities(tools=True, structured_output=True),
    )


def build_provider(config: AssistantConfig) -> object:
    """Return the provider the configured profile asks for."""
    if config.provider == "fake":
        return fake_provider()
    if config.provider == "ollama":
        from xyberos.ai.ollama import OllamaProvider, OllamaSettings

        return OllamaProvider(
            OllamaSettings(
                model=config.model,
                base_url=config.base_url,
                tools=config.tools,
                structured_output=config.structured_output,
            )
        )
    raise AIConfigurationError(
        f"unknown assistant provider {config.provider!r}; use 'fake' or 'ollama'"
    )


def knowledge_tool() -> Tool:
    """Return a tool whose dependency is closed over, never resolved from a container."""

    async def look_up(arguments: Mapping[str, object], context: object) -> dict[str, object]:
        return {"topic": arguments["topic"], "note": "the forecast says rain is likely"}

    return Tool(
        spec=ToolSpec(
            name="knowledge",
            description="Look up an internal note about a topic",
            parameters=KNOWLEDGE_SCHEMA,
        ),
        handler=look_up,
    )


def build_triage_workflow(assistant: AIFacade) -> Workflow:
    """Triage one ticket: classify it, then answer it.

    The classify step retries by default policy, which already covers ``AITransportError`` — a slow
    or unreachable provider is a transient failure — so an AI call inside a workflow inherits the
    engine's retry, deadline, and cancellation semantics without any extra wiring.
    """

    async def classify(value: dict[str, str], context: StepContext) -> dict[str, str]:
        structured = await assistant.structured(
            ChatRequest(
                messages=(
                    Message.system(SYSTEM_PROMPT),
                    Message.user(f"Classify ticket {value['ticket']}."),
                ),
                response_schema=CLASSIFY_SCHEMA,
            )
        )
        assert isinstance(structured, Mapping)
        return {"ticket": value["ticket"], "category": str(structured["category"])}

    async def answer(value: dict[str, str], context: StepContext) -> str:
        response = await assistant.chat(
            ChatRequest(
                messages=(
                    Message.system(SYSTEM_PROMPT),
                    Message.user(f"Reply to a customer about a {value['category']}."),
                )
            )
        )
        return response.message.content

    return (
        Workflow("ticket-triage", version="1", input_type=dict)
        .step("classify", classify, retry=Retry(max_attempts=2))
        .step("answer", answer, timeout=seconds(10))
        .edge("classify", "answer")
    )


@dataclass(frozen=True)
class AssistantConfig:
    """Typed configuration for :class:`AssistantPlugin`."""

    provider: str = "fake"
    model: str = "llama3.2"
    base_url: str = "http://127.0.0.1:11434"
    tools: bool = False
    structured_output: bool = True


class AssistantPlugin(Plugin[AssistantConfig]):
    """Contributes the AI facade, its routes, and the triage workflow."""

    name = "assistant"
    config_type = AssistantConfig

    def __init__(self, provider: object | None = None) -> None:
        """Pass ``provider`` to inject one, which is how tests script model responses."""
        self._provider = provider

    def register(self, app: App, config: AssistantConfig) -> None:
        facade = AIFacade(
            self._provider if self._provider is not None else build_provider(config),
            logging_policy=LoggingPolicy.metadata_only(),
        )
        # The plugin builds the facade, so the application owns it: resolving eagerly is free (no
        # I/O) and guarantees the provider is released at shutdown even if no route was called.
        app.provide(AIFacade, instance=facade, eager=True)
        app.get("/health")(self._health)
        app.post("/ask")(self._ask)
        app.post("/research")(self._research)
        app.post("/triage")(self._triage)

    async def _health(self, assistant: Annotated[AIFacade, Inject()]) -> dict[str, object]:
        health = await assistant.health()
        return {
            "provider": assistant.name,
            "model": health.model,
            "status": health.status.value,
            "detail": health.detail,
        }

    async def _ask(
        self, request: Request, assistant: Annotated[AIFacade, Inject()]
    ) -> dict[str, object]:
        question = _required_text(await read_json_object(request), "question")
        response = await assistant.chat(
            ChatRequest(
                messages=(Message.system(SYSTEM_PROMPT), Message.user(question)),
                response_schema=SUMMARY_SCHEMA,
            )
        )
        structured = response.structured
        assert isinstance(structured, Mapping)
        return {
            "answer": structured["answer"],
            "confidence": structured["confidence"],
            "model": response.model,
            "tokens": response.usage.total_tokens,
        }

    async def _research(
        self, request: Request, assistant: Annotated[AIFacade, Inject()]
    ) -> dict[str, object]:
        topic = _required_text(await read_json_object(request), "topic")
        tools = ToolSet.of(knowledge_tool())
        response = await assistant.chat_with_tools(
            ChatRequest(
                messages=(
                    Message.system(SYSTEM_PROMPT),
                    Message.user(f"What should I know about {topic}?"),
                )
            ),
            tools=tools,
            max_rounds=3,
        )
        return {
            "reply": response.message.content,
            "rounds": response.rounds,
            "tools": list(tools.names),
            "tokens": response.usage.total_tokens,
        }

    async def _triage(
        self, request: Request, assistant: Annotated[AIFacade, Inject()]
    ) -> dict[str, object]:
        ticket = _required_text(await read_json_object(request), "ticket")
        workflow = build_triage_workflow(assistant)

        result = await workflow.run(input={"ticket": ticket}, timeout=seconds(30))

        return {
            "ticket": ticket,
            "reply": result.value,
            "steps": sorted(result.steps),
            "graph": workflow.render().splitlines()[0],
        }


def _required_text(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise RequestValidationError(f"provide a non-empty {name!r}")
    return value


def create_app(
    config: Mapping[str, object] | None = None, *, provider: object | None = None
) -> App:
    """Compose the example application.

    ``config`` is the plugin's configuration section, so the profile can be selected the same way
    any other setting is. ``provider`` injects a model provider directly, which tests use to script
    responses.
    """
    app = App(settings=Settings.load(environ={}))
    app.add_plugin(AssistantPlugin(provider), config=config)
    app.validate()
    return app


def build_asgi_app(app: App) -> Starlette:
    """Return the ASGI application for the composed app."""
    return HttpAdapter(app).asgi_app


def app_factory() -> Starlette:
    """Return the ASGI application for the default profile, for ``uvicorn --factory``."""
    return build_asgi_app(create_app())


def main() -> None:
    """Run every route against the deterministic fake provider through the real ASGI stack."""
    from xyberos.http.testing import create_test_client

    client = create_test_client(build_asgi_app(create_app()))
    with client:
        print("health:  ", client.get("/health").json())
        print("ask:     ", client.post("/ask", json={"question": "Will it rain?"}).json())
        print("research:", client.post("/research", json={"topic": "rain"}).json())
        print("triage:  ", client.post("/triage", json={"ticket": "T-100"}).json())
    print()
    print("Set the plugin configuration to provider = 'ollama' with model = 'llama3.2' to run the")
    print("same routes against a local Ollama service. See README.md.")


if __name__ == "__main__":
    main()
