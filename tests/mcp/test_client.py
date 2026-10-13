"""The MCP client's transport and handshake, against a stub server on a real socket."""

from __future__ import annotations

import asyncio

import pytest
from stub_server import StubMcpServer, ToolStub  # type: ignore[import-not-found]

from xyberos.errors import McpConfigurationError, McpProtocolError, McpTransportError
from xyberos.mcp import SUPPORTED_PROTOCOL_VERSION, McpClient, McpServerSettings
from xyberos.mcp.client import _PROTOCOL_HEADER, _SESSION_HEADER


def settings(url: str, **overrides: object) -> McpServerSettings:
    arguments: dict[str, object] = {"name": "stub", "url": url, "tools": ("search",)}
    arguments.update(overrides)
    return McpServerSettings(**arguments)  # type: ignore[arg-type]


def header_value(header: dict[str, str], name: str) -> str | None:
    """Return one header's value, matching the name the way HTTP says to: case-insensitively."""
    wanted = name.lower()
    for key, value in header.items():
        if key.lower() == wanted:
            return value
    return None


def test_the_handshake_reports_what_the_server_says() -> None:
    with StubMcpServer() as stub:

        async def scenario() -> tuple[str, str, str]:
            client = McpClient(settings(stub.url))
            info = await client.initialize()
            assert client.initialized is True
            return info.name, info.version, info.protocol_version

        assert asyncio.run(scenario()) == ("stub-server", "9.9", SUPPORTED_PROTOCOL_VERSION)

    methods = [message.get("method") for message in stub.received]
    assert methods == ["initialize", "notifications/initialized"]
    initialize = stub.received[0]
    params = initialize.get("params")
    assert isinstance(params, dict)
    assert params["protocolVersion"] == SUPPORTED_PROTOCOL_VERSION
    assert params["capabilities"] == {}
    client_info = params["clientInfo"]
    assert isinstance(client_info, dict)
    assert client_info["name"] == "xyberos"
    assert client_info["version"]


def test_a_server_that_negotiates_another_protocol_is_refused() -> None:
    with StubMcpServer(protocol_version="2024-11-05") as stub:

        async def scenario() -> None:
            with pytest.raises(McpProtocolError, match="negotiated"):
                await McpClient(settings(stub.url)).initialize()

        asyncio.run(scenario())


def test_an_unreachable_server_is_reported_with_its_url() -> None:
    async def scenario() -> None:
        client = McpClient(settings("http://127.0.0.1:1/mcp", name="absent", tools=("search",)))
        with pytest.raises(McpTransportError, match="could not be reached"):
            await client.initialize()

    asyncio.run(scenario())


def test_an_http_error_is_reported_with_its_status() -> None:
    with StubMcpServer(http_status=502) as stub:

        async def scenario() -> None:
            with pytest.raises(McpTransportError, match="HTTP 502"):
                await McpClient(settings(stub.url)).initialize()

        asyncio.run(scenario())


def test_a_body_that_is_not_json_is_reported_rather_than_parsed_hopefully() -> None:
    with StubMcpServer(body=b"<html>a proxy</html>") as stub:

        async def scenario() -> None:
            with pytest.raises(McpTransportError, match="not JSON"):
                await McpClient(settings(stub.url)).initialize()

        asyncio.run(scenario())


def test_a_json_rpc_error_becomes_a_protocol_error() -> None:
    with StubMcpServer(tools=[ToolStub(name="search")]) as stub:

        async def scenario() -> None:
            client = McpClient(settings(stub.url))
            await client.initialize()
            with pytest.raises(McpProtocolError, match="JSON-RPC error -32602"):
                await client.call_tool("absent", {})

        asyncio.run(scenario())


def test_an_event_stream_response_is_decoded() -> None:
    with StubMcpServer(event_stream=True) as stub:

        async def scenario() -> str:
            client = McpClient(settings(stub.url))
            info = await client.initialize()
            return info.name

        assert asyncio.run(scenario()) == "stub-server"


def test_the_session_id_the_server_hands_out_is_echoed() -> None:
    with StubMcpServer(session_id="session-42") as stub:

        async def scenario() -> None:
            client = McpClient(settings(stub.url))
            await client.initialize()
            await client.list_tools()

        asyncio.run(scenario())

    first, second, third = (header_value(header, _SESSION_HEADER) for header in stub.headers)
    assert first is None, "the handshake establishes the session, so it cannot carry one yet"
    assert second == "session-42"
    assert third == "session-42"


def test_the_protocol_header_is_sent_only_after_the_handshake() -> None:
    with StubMcpServer() as stub:

        async def scenario() -> None:
            await McpClient(settings(stub.url)).initialize()

        asyncio.run(scenario())

    first, second = (header_value(header, _PROTOCOL_HEADER) for header in stub.headers)
    assert first is None
    assert second == SUPPORTED_PROTOCOL_VERSION


def test_tools_list_follows_pagination_and_stops_at_the_end() -> None:
    tools = [ToolStub(name=f"tool{index}") for index in range(5)]
    with StubMcpServer(tools=tools, pages=2) as stub:

        async def scenario() -> list[str]:
            client = McpClient(settings(stub.url))
            await client.initialize()
            return [info.name for info in await client.list_tools()]

        assert asyncio.run(scenario()) == [tool.name for tool in tools]

    cursors = [
        (message.get("params") or {}).get("cursor")
        for message in stub.received
        if message.get("method") == "tools/list"
    ]
    assert cursors == [None, "1"]


def test_settings_refuse_a_name_that_cannot_prefix_a_tool_and_an_empty_opt_in() -> None:
    with pytest.raises(McpConfigurationError, match="must be an identifier"):
        settings("http://localhost/mcp", name="not an identifier")

    with pytest.raises(McpConfigurationError, match="http:// or https://"):
        settings("ftp://localhost/mcp")

    with pytest.raises(McpConfigurationError, match="non-empty 'tools'"):
        settings("http://localhost/mcp", tools=())

    with pytest.raises(McpConfigurationError, match="same tool twice"):
        settings("http://localhost/mcp", tools=("search", "search"))

    with pytest.raises(McpConfigurationError, match="must be positive"):
        settings("http://localhost/mcp", timeout=0)
