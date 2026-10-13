"""The AI provider contract, checked against the fake we ship and against two broken providers.

`assert_model_provider_contract` exists so an adapter author outside this project can prove their
implementation behaves the way `ModelProvider` says. That makes three things worth testing here:
that a provider which declares its capabilities honestly passes, that a provider which overclaims
fails, and that the *refusal* half of each claim is checked rather than assumed.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import pytest

from xyberos.ai import (
    ChatChunk,
    ChatRequest,
    ChatResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    FakeModelProvider,
    Message,
    ModelCapabilities,
    ModelHealth,
    ModelReply,
    ModelStatus,
    ToolCall,
    ToolSpec,
    Usage,
)
from xyberos.ai.testing import (
    assert_embedding_provider_contract,
    assert_model_provider_contract,
)

PERMISSIVE = ModelCapabilities(tools=True, structured_output=True, streaming=True, embeddings=True)
NOTHING = ModelCapabilities(tools=False, structured_output=False, streaming=False, embeddings=False)

TOOL = ToolSpec(
    name="lookup",
    description="Look up a topic.",
    parameters={
        "type": "object",
        "properties": {"topic": {"type": "string"}},
        "required": ["topic"],
        "additionalProperties": False,
    },
)


def honest_provider() -> FakeModelProvider:
    """A fake whose one scripted reply satisfies every claimed capability at once."""

    return FakeModelProvider(
        [
            ModelReply(
                content=json.dumps({"name": "Ada"}),
                tool_calls=(ToolCall(name="lookup", arguments={"topic": "rain"}),),
                usage=Usage(input_tokens=7, output_tokens=5),
            )
        ],
        capabilities=PERMISSIVE,
    )


def test_the_suite_passes_for_a_provider_that_keeps_its_claims() -> None:
    checked = asyncio.run(assert_model_provider_contract(honest_provider(), tool=TOOL))

    assert len(checked) == 8
    assert any("usage is reported" in name for name in checked)
    assert any("exactly one terminal chunk" in name for name in checked)
    assert any("structured output honours" in name for name in checked)
    assert any("names a declared tool" in name for name in checked)
    assert any("cancellation" in name for name in checked)


def test_the_suite_checks_the_refusal_half_of_every_claim() -> None:
    """A provider that claims nothing is checked for refusing, not skipped."""

    provider = FakeModelProvider(
        [ModelReply(content="plain", usage=Usage(input_tokens=1, output_tokens=1))],
        capabilities=NOTHING,
    )

    checked = asyncio.run(assert_model_provider_contract(provider))

    assert len(checked) == 8
    assert sum("refused" in name or "refuses" in name for name in checked) == 3


def test_the_embedding_suite_passes_and_reports_its_width() -> None:
    checked = asyncio.run(assert_embedding_provider_contract(honest_provider()))

    assert checked == ("embed() returns one vector per input, all of one non-zero width",)


def test_the_embedding_suite_checks_the_refusal_half() -> None:
    provider = FakeModelProvider(capabilities=NOTHING)

    checked = asyncio.run(assert_embedding_provider_contract(provider))

    assert checked == ("embed() refuses when embedding support is not claimed",)


def test_the_suite_needs_a_ready_provider_and_says_why_not() -> None:
    provider = FakeModelProvider(
        health=ModelHealth(
            status=ModelStatus.MODEL_UNAVAILABLE,
            model="absent",
            detail="run `ollama pull absent`",
        )
    )

    with pytest.raises(AssertionError, match="ollama pull absent"):
        asyncio.run(assert_model_provider_contract(provider))


class ProseInsteadOfJsonProvider:
    """A provider that claims structured output and answers with prose."""

    def __init__(self, inner: FakeModelProvider) -> None:
        self._inner = inner

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def capabilities(self) -> ModelCapabilities:
        return self._inner.capabilities

    async def health(self) -> ModelHealth:
        return await self._inner.health()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return await self._inner.chat(request)

    def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        return self._inner.stream(request)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return await self._inner.embed(request)


class OverclaimingToolProvider:
    """A provider that returns a tool call for a tool it was never given."""

    def __init__(self, inner: FakeModelProvider) -> None:
        self._inner = inner

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def capabilities(self) -> ModelCapabilities:
        return self._inner.capabilities

    async def health(self) -> ModelHealth:
        return await self._inner.health()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        response = await self._inner.chat(request)
        if not request.tools:
            return response
        return ChatResponse(
            message=Message.assistant(
                response.message.content, tool_calls=(ToolCall(name="undeclared"),)
            ),
            model=response.model,
            usage=response.usage,
            finish_reason=response.finish_reason,
        )

    def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        return self._inner.stream(request)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return await self._inner.embed(request)


def test_the_suite_catches_a_provider_that_overclaims_structured_output() -> None:
    prose = FakeModelProvider(
        [ModelReply(content="the answer is Ada", usage=Usage(input_tokens=3, output_tokens=2))],
        capabilities=PERMISSIVE,
    )

    with pytest.raises(AssertionError, match="not JSON"):
        asyncio.run(
            assert_model_provider_contract(
                ProseInsteadOfJsonProvider(prose),
                schema={"type": "object", "properties": {"name": {"type": "string"}}},
            )
        )


def test_the_suite_catches_a_provider_that_returns_an_undeclared_tool() -> None:
    provider = OverclaimingToolProvider(honest_provider())

    with pytest.raises(AssertionError, match="not the tool it was given"):
        asyncio.run(assert_model_provider_contract(provider, tool=TOOL))


def test_a_structured_reply_that_does_not_match_the_schema_is_caught() -> None:
    mismatched = FakeModelProvider(
        [
            ModelReply(
                content=json.dumps({"nickname": "Ada"}),
                usage=Usage(input_tokens=3, output_tokens=2),
            )
        ],
        capabilities=PERMISSIVE,
    )

    with pytest.raises(AssertionError, match="does not match the schema"):
        asyncio.run(
            assert_model_provider_contract(
                mismatched,
                schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            )
        )
