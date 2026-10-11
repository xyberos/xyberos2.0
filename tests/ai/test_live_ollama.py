"""Opt-in integration tests against a real Ollama service.

These tests never run in normal CI. Set ``XYBEROS_OLLAMA_LIVE=1`` to enable them, and optionally
``XYBEROS_OLLAMA_LIVE_MODEL``, ``XYBEROS_OLLAMA_LIVE_BASE_URL``, and
``XYBEROS_OLLAMA_LIVE_EMBEDDING_MODEL`` to point them at a service whose model has already been
pulled. Xyberos never pulls, starts, or upgrades a model, so a missing one fails the test rather
than downloading anything. Prompts and completions are never logged or asserted on.

Two defaults are owner decisions rather than framework opinions:

* ``XYBEROS_OLLAMA_LIVE_MODEL`` defaults to ``llama3.2:3b`` (about 1.9 GB) because it is small
  enough for a laptop and genuinely reports tool support, which the tool tests need. ``llama3.2:1b``
  (about 1.3 GB) also reports tool support and is the minimal alternative, but it is noticeably
  less reliable at tool calling, so it makes the tool test flaky rather than fast.
* ``XYBEROS_OLLAMA_LIVE_EMBEDDING_MODEL`` has **no** default: one Ollama model does not serve both
  chat and embeddings, so the embedding tests stay skipped until an operator names one (for example
  ``nomic-embed-text``, 768 dimensions).

Capability-specific tests have their own gate, so a model without tool support skips them instead of
failing a suite that is otherwise fine.
"""

import asyncio
import os

import pytest

pytest.importorskip("httpx", reason="the Ollama adapter needs the 'ollama' extra")

from xyberos.ai import ChatRequest, EmbeddingRequest, Message, ModelStatus  # noqa: E402
from xyberos.ai.ollama import OllamaProvider, OllamaSettings  # noqa: E402

LIVE = os.environ.get("XYBEROS_OLLAMA_LIVE") == "1"
TOOLS = os.environ.get("XYBEROS_OLLAMA_LIVE_TOOLS") == "1"
MODEL = os.environ.get("XYBEROS_OLLAMA_LIVE_MODEL", "llama3.2:3b")
BASE_URL = os.environ.get("XYBEROS_OLLAMA_LIVE_BASE_URL", "http://127.0.0.1:11434")
EMBEDDING_MODEL = os.environ.get("XYBEROS_OLLAMA_LIVE_EMBEDDING_MODEL")

pytestmark = pytest.mark.skipif(
    not LIVE, reason="set XYBEROS_OLLAMA_LIVE=1 and a pulled model to run live Ollama tests"
)

requires_tools = pytest.mark.skipif(
    not TOOLS,
    reason="set XYBEROS_OLLAMA_LIVE_TOOLS=1 with a tool-capable model to run the tool tests",
)


def live_provider(**settings: object) -> OllamaProvider:
    arguments: dict[str, object] = {"model": MODEL, "base_url": BASE_URL, "timeout": 120.0}
    arguments.update(settings)
    return OllamaProvider(OllamaSettings(**arguments))  # type: ignore[arg-type]


@requires_tools
def test_the_service_and_model_are_ready() -> None:
    async def scenario() -> None:
        provider = live_provider(tools=True)
        try:
            health = await provider.health()
        finally:
            await provider.aclose()

        assert health.status is ModelStatus.READY, health
        assert health.model == MODEL
        assert health.provider_version

    asyncio.run(scenario())


def test_a_chat_call_returns_content_and_usage() -> None:
    async def scenario() -> None:
        provider = live_provider()
        try:
            response = await provider.chat(
                ChatRequest(messages=(Message.user("Reply with the single word: ready"),))
            )
        finally:
            await provider.aclose()

        assert response.message.content.strip()
        assert response.model
        assert response.usage.total_tokens > 0

    asyncio.run(scenario())


def test_streaming_produces_chunks_and_a_final_marker() -> None:
    async def scenario() -> None:
        provider = live_provider()
        try:
            chunks = [
                chunk
                async for chunk in provider.stream(
                    ChatRequest(messages=(Message.user("Count from one to five."),))
                )
            ]
        finally:
            await provider.aclose()

        assert len(chunks) > 1
        assert chunks[-1].done
        assert "".join(chunk.content for chunk in chunks).strip()

    asyncio.run(scenario())


def test_structured_output_is_usable_when_the_model_claims_it() -> None:
    async def scenario() -> None:
        provider = live_provider(structured_output=True)
        try:
            response = await provider.chat(
                ChatRequest(
                    messages=(Message.user("Name one capital city."),),
                    response_schema={
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                        "additionalProperties": False,
                    },
                )
            )
        finally:
            await provider.aclose()

        assert response.message.content

    asyncio.run(scenario())


@pytest.mark.skipif(
    not EMBEDDING_MODEL, reason="set XYBEROS_OLLAMA_LIVE_EMBEDDING_MODEL to test embeddings"
)
def test_embeddings_round_trip() -> None:
    async def scenario() -> None:
        provider = live_provider(embedding_model=EMBEDDING_MODEL)
        try:
            response = await provider.embed(EmbeddingRequest(inputs=("alpha", "beta")))
        finally:
            await provider.aclose()

        assert len(response.embeddings) == 2
        assert response.dimensions is not None
        assert response.dimensions > 1

    asyncio.run(scenario())
