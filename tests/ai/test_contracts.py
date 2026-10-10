"""The provider-neutral contracts are immutable, validated, and free of vendor concepts."""

import pytest

from xyberos.ai import (
    ChatChunk,
    ChatRequest,
    EmbeddingRequest,
    EmbeddingResponse,
    FinishReason,
    Message,
    ModelCapabilities,
    ModelHealth,
    ModelStatus,
    Role,
    ToolCall,
    ToolSpec,
    Usage,
)
from xyberos.errors import AIRequestError

CONCISE_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}}


def test_message_constructors_cover_the_conversation_roles() -> None:
    assert Message.system("be brief").role is Role.SYSTEM
    assert Message.user("hello").role is Role.USER
    assert Message.assistant("hi").role is Role.ASSISTANT
    assert Message.tool_result("weather", "{}").role is Role.TOOL
    assert Message.tool_result("weather", "{}").tool_name == "weather"


def test_a_tool_result_must_name_its_tool() -> None:
    with pytest.raises(AIRequestError, match="must name the tool it answers"):
        Message(role=Role.TOOL, content="{}")


def test_message_content_must_be_a_string() -> None:
    with pytest.raises(AIRequestError, match="content must be a string"):
        Message(role=Role.USER, content=5)  # type: ignore[arg-type]


def test_a_tool_call_needs_a_name_and_freezes_its_arguments() -> None:
    arguments = {"city": "Oslo"}
    call = ToolCall(name="weather", arguments=arguments)
    arguments["city"] = "mutated"

    assert dict(call.arguments) == {"city": "Oslo"}
    with pytest.raises(TypeError):
        call.arguments["city"] = "nope"  # type: ignore[index]
    with pytest.raises(AIRequestError, match="needs a non-empty tool name"):
        ToolCall(name=" ")
    with pytest.raises(AIRequestError, match="must be a mapping"):
        ToolCall(name="weather", arguments=["oslo"])  # type: ignore[arg-type]


def test_usage_accounts_and_accumulates() -> None:
    usage = Usage(input_tokens=3, output_tokens=4)

    assert usage.total_tokens == 7
    assert (usage + Usage(1, 1)) == Usage(input_tokens=4, output_tokens=5)
    with pytest.raises(AIRequestError, match="cannot be negative"):
        Usage(input_tokens=-1)


def test_capabilities_default_to_the_conservative_side() -> None:
    capabilities = ModelCapabilities()

    assert not capabilities.tools
    assert not capabilities.structured_output
    assert not capabilities.embeddings
    assert capabilities.streaming


def test_health_reports_readiness_without_raising() -> None:
    assert ModelHealth(status=ModelStatus.READY, model="llama3.2").ready
    assert not ModelHealth(status=ModelStatus.UNREACHABLE, model="llama3.2").ready
    assert ModelHealth(status=ModelStatus.MODEL_UNAVAILABLE, model="x").status.value == (
        "model_unavailable"
    )


def test_finish_reasons_are_normalized_names() -> None:
    assert FinishReason.REFUSAL.value == "refusal"
    assert FinishReason.TOOL_CALLS.value == "tool_calls"


def test_a_tool_spec_validates_its_declaration_when_it_is_built() -> None:
    spec = ToolSpec(name="weather", description="look up", parameters=CONCISE_SCHEMA)

    assert dict(spec.parameters)["type"] == "object"
    with pytest.raises(AIRequestError, match="needs a non-empty name"):
        ToolSpec(name="")
    with pytest.raises(AIRequestError, match="description of tool"):
        ToolSpec(name="weather", description=5)  # type: ignore[arg-type]
    with pytest.raises(AIRequestError, match="unsupported keyword"):
        ToolSpec(name="weather", parameters={"type": "object", "oneOf": []})


def test_a_chat_request_validates_its_own_shape() -> None:
    request = ChatRequest(
        messages=(Message.user("hi"),), temperature=0.5, response_schema=CONCISE_SCHEMA
    )

    assert dict(request.response_schema or {})["type"] == "object"
    with pytest.raises(AIRequestError, match="at least one message"):
        ChatRequest(messages=())
    with pytest.raises(AIRequestError, match="messages must be Message values"):
        ChatRequest(messages=("hi",))  # type: ignore[arg-type]
    with pytest.raises(AIRequestError, match="temperature must be between 0 and 2"):
        ChatRequest(messages=(Message.user("hi"),), temperature=3.0)
    with pytest.raises(AIRequestError, match="max_tokens must be at least 1"):
        ChatRequest(messages=(Message.user("hi"),), max_tokens=0)
    with pytest.raises(AIRequestError, match="timeout must be greater than zero"):
        ChatRequest(messages=(Message.user("hi"),), timeout=0)


def test_a_chat_request_rejects_an_unusable_response_schema() -> None:
    with pytest.raises(AIRequestError, match="unsupported keyword"):
        ChatRequest(
            messages=(Message.user("hi"),),
            response_schema={"type": "object", "notAKeyword": True},
        )


def test_an_embedding_request_validates_its_inputs() -> None:
    request = EmbeddingRequest(inputs=("a", "b"))

    assert request.inputs == ("a", "b")
    with pytest.raises(AIRequestError, match="at least one input"):
        EmbeddingRequest(inputs=())
    with pytest.raises(AIRequestError, match="non-empty strings"):
        EmbeddingRequest(inputs=("",))
    with pytest.raises(AIRequestError, match="timeout must be greater than zero"):
        EmbeddingRequest(inputs=("a",), timeout=-1)


def test_an_embedding_response_reports_its_width() -> None:
    response = EmbeddingResponse(model="m", embeddings=((1.0, 2.0), (3.0, 4.0)))

    assert response.dimensions == 2
    assert EmbeddingResponse(model="m", embeddings=()).dimensions is None


def test_a_chat_chunk_carries_content_and_a_final_marker() -> None:
    chunk = ChatChunk(content="Hel", model="llama3.2")

    assert not chunk.done
    assert ChatChunk(content="", done=True, usage=Usage(1, 1)).done
