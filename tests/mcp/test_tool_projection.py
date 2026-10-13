"""Projecting server tools into the tool model: namespacing, refusals, and the allowlist.

The claim this file has to make good on is that an MCP tool is a `Tool` like any other, so the
allowlist, argument validation, and result handling are the shipped ones rather than a parallel
implementation.
"""

from __future__ import annotations

import asyncio

import pytest
from stub_server import StubMcpServer, ToolStub  # type: ignore[import-not-found]

from xyberos.ai import (
    AIFacade,
    ChatRequest,
    FakeModelProvider,
    Message,
    ModelReply,
    ToolCall,
    ToolSet,
    Usage,
)
from xyberos.errors import AISchemaError, AIToolError, McpConfigurationError, McpTransportError
from xyberos.mcp import MAX_DESCRIPTION_LENGTH, McpClient, McpServerSettings, tools_for

SEARCH = ToolStub(name="search", description="Search a corpus.", text="three documents match")
UNSUPPORTED = ToolStub(
    name="fancy",
    schema={
        "type": "object",
        "properties": {"mode": {"oneOf": [{"type": "string"}, {"type": "integer"}]}},
    },
)


def server_settings(url: str, tools: tuple[str, ...] = ("search",)) -> McpServerSettings:
    return McpServerSettings(name="kb", url=url, tools=tools)


def test_one_tool_is_registered_per_opted_in_tool_under_a_namespaced_name() -> None:
    with StubMcpServer(tools=[SEARCH]) as stub:

        async def scenario() -> list[str]:
            tools = await tools_for([McpClient(server_settings(stub.url))])
            return [tool.name for tool in tools]

        assert asyncio.run(scenario()) == ["kb_search"]


def test_a_tool_the_server_does_not_offer_is_refused_with_what_it_does_offer() -> None:
    with StubMcpServer(tools=[SEARCH]) as stub:

        async def scenario() -> None:
            client = McpClient(server_settings(stub.url, tools=("absent",)))
            with pytest.raises(
                McpConfigurationError, match="offers no tool 'absent'.*offers: search"
            ):
                await tools_for([client])

        asyncio.run(scenario())


def test_a_schema_outside_the_subset_is_refused_with_the_server_and_the_keyword_named() -> None:
    with StubMcpServer(tools=[UNSUPPORTED]) as stub:

        async def scenario() -> None:
            client = McpClient(server_settings(stub.url, tools=("fancy",)))
            with pytest.raises(AISchemaError, match=r"server 'kb'.*oneOf"):
                await tools_for([client])

        asyncio.run(scenario())


def test_a_tool_that_is_not_opted_into_never_breaks_registration() -> None:
    """One unsupported tool on a useful server costs that tool, not the server."""

    with StubMcpServer(tools=[SEARCH, UNSUPPORTED]) as stub:

        async def scenario() -> list[str]:
            tools = await tools_for([McpClient(server_settings(stub.url, tools=("search",)))])
            return [tool.name for tool in tools]

        assert asyncio.run(scenario()) == ["kb_search"]


def test_calling_a_projected_tool_reaches_the_server_and_returns_its_text() -> None:
    with StubMcpServer(tools=[SEARCH]) as stub:

        async def scenario() -> tuple[bool, object]:
            toolset = ToolSet(await tools_for([McpClient(server_settings(stub.url))]))
            result = await toolset.invoke(ToolCall(name="kb_search", arguments={"topic": "rain"}))
            return result.ok, result.value

        ok, value = asyncio.run(scenario())

    assert (ok, value) == (True, "three documents match")
    call = next(message for message in stub.received if message.get("method") == "tools/call")
    assert call["params"] == {"name": "search", "arguments": {"topic": "rain"}}, (
        "the server must see its own tool name, not the namespaced one"
    )


def test_the_servers_error_flag_becomes_a_failed_result_rather_than_an_exception() -> None:
    failing = ToolStub(name="search", text="the corpus is unavailable", is_error=True)
    with StubMcpServer(tools=[failing]) as stub:

        async def scenario() -> object:
            toolset = ToolSet(await tools_for([McpClient(server_settings(stub.url))]))
            result = await toolset.invoke(ToolCall(name="kb_search", arguments={"topic": "rain"}))
            assert result.ok is False
            return result.error

        error = asyncio.run(scenario())

    assert "the corpus is unavailable" in str(error)


def test_a_tool_outside_the_allowlist_is_denied_before_anything_is_called() -> None:
    with StubMcpServer(tools=[SEARCH]) as stub:

        async def scenario() -> None:
            toolset = ToolSet(await tools_for([McpClient(server_settings(stub.url))]))
            with pytest.raises(AIToolError, match="not allowed for this call"):
                await toolset.invoke(ToolCall(name="kb_other", arguments={}))

        asyncio.run(scenario())

    assert not [m for m in stub.received if m.get("method") == "tools/call"]


def test_arguments_are_validated_against_the_declared_schema_before_the_call() -> None:
    with StubMcpServer(tools=[SEARCH]) as stub:

        async def scenario() -> object:
            toolset = ToolSet(await tools_for([McpClient(server_settings(stub.url))]))
            result = await toolset.invoke(ToolCall(name="kb_search", arguments={"wrong": 1}))
            assert result.ok is False
            return result.error_type

        error_type = asyncio.run(scenario())

    assert error_type == "AISchemaError"
    assert not [m for m in stub.received if m.get("method") == "tools/call"], (
        "an argument the schema rejects must never reach the server"
    )


def test_a_server_s_non_text_content_is_described_rather_than_dropped() -> None:
    with StubMcpServer(tools=[ToolStub(name="with_image", text="here is the chart")]) as stub:

        async def scenario() -> object:
            toolset = ToolSet(
                await tools_for([McpClient(server_settings(stub.url, ("with_image",)))])
            )
            result = await toolset.invoke(
                ToolCall(name="kb_with_image", arguments={"topic": "rain"})
            )
            return result.value

        assert asyncio.run(scenario()) == "here is the chart\n[image content]"


def test_a_long_description_is_bounded_because_it_is_data_a_third_party_wrote() -> None:
    verbose = ToolStub(name="search", description="x" * (MAX_DESCRIPTION_LENGTH + 500))
    with StubMcpServer(tools=[verbose]) as stub:

        async def scenario() -> str:
            tools = await tools_for([McpClient(server_settings(stub.url))])
            return tools[0].spec.description

        description = asyncio.run(scenario())

    assert len(description) == MAX_DESCRIPTION_LENGTH + 3
    assert description.endswith("...")


def test_the_facade_runs_a_projected_tool_end_to_end() -> None:
    """The integration claim: a remote tool is usable by the shipped agent loop unchanged."""

    with StubMcpServer(tools=[SEARCH]) as stub:

        async def scenario() -> tuple[str, list[str]]:
            toolset = ToolSet(await tools_for([McpClient(server_settings(stub.url))]))
            provider = FakeModelProvider(
                [
                    ModelReply.tools(
                        ToolCall(name="kb_search", arguments={"topic": "rain"}),
                        usage=Usage(input_tokens=11, output_tokens=4),
                    ),
                    ModelReply.ok("Rain is likely.", usage=Usage(input_tokens=20, output_tokens=6)),
                ]
            )
            facade = AIFacade(provider)
            response = await facade.chat_with_tools(
                ChatRequest(messages=(Message.user("Will it rain?"),), model="fake-model"),
                tools=toolset,
            )
            return response.message.content, [spec.name for spec in toolset.specs]

        answer, offered = asyncio.run(scenario())

    assert answer == "Rain is likely."
    assert offered == ["kb_search"]


def test_a_server_that_cannot_be_reached_fails_registration_rather_than_inventing_tools() -> None:
    async def scenario() -> None:
        client = McpClient(
            McpServerSettings(name="kb", url="http://127.0.0.1:1/mcp", tools=("search",))
        )
        with pytest.raises(McpTransportError, match="could not be reached"):
            await tools_for([client])

    asyncio.run(scenario())
