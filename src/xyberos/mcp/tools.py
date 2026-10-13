"""Project a server's tools into the tool model the facade already has.

An MCP tool becomes a :class:`~xyberos.ai.tools.Tool` like any other: same declaration, same handler
signature, same result. That is the whole point — an application's allowlist, argument validation,
event sink, and result handling work on a remote tool without a second code path, and a tool the
operator did not opt into is a name the set does not contain, which raises at the policy boundary.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from xyberos.ai.contracts import ToolSpec
from xyberos.ai.schema import check_schema
from xyberos.ai.tools import Tool, ToolContext
from xyberos.errors import AIError, AISchemaError, AIToolError, McpConfigurationError
from xyberos.mcp.client import McpClient, McpToolInfo

__all__ = ["MAX_DESCRIPTION_LENGTH", "tools_for"]

MAX_DESCRIPTION_LENGTH = 1024
"""How much of a server's tool description reaches a prompt.

A description is data a third party wrote, and a server that returns a megabyte of prose would
inflate every request that carries it. Truncating is the cheap bound; the tool's *schema* is never
truncated, because that is what arguments are validated against.
"""


async def tools_for(clients: Iterable[McpClient]) -> tuple[Tool, ...]:
    """Return one :class:`Tool` per opted-in tool across ``clients``, namespaced and validated.

    Each client is initialized first, so a server that is unreachable or disagrees about the
    protocol fails here — at startup, with the server named — rather than on the first tool call.
    Every tool the operator opted into must exist on the server and must declare a schema inside the
    closed subset this framework validates; anything else is refused with the server, the tool, and
    the offending keyword named.

    A tool the operator did *not* opt into is simply not registered, which is what makes one
    unsupported tool on an otherwise useful server a non-event.
    """
    tools: list[Tool] = []
    for client in clients:
        await client.initialize()
        available = {info.name: info for info in await client.list_tools()}
        for name in client.settings.tools:
            info = available.get(name)
            if info is None:
                offered = ", ".join(sorted(available)) or "none"
                raise McpConfigurationError(
                    f"server {client.settings.name!r} offers no tool {name!r}; it offers: {offered}"
                )
            _check_server_schema(client.settings.name, info)
            tools.append(_project(client, info))
    return tuple(tools)


def _check_server_schema(server: str, info: McpToolInfo) -> None:
    """Refuse a tool whose declared schema cannot be validated with the closed subset."""
    location = f"the schema of tool {info.name!r} from server {server!r}"
    try:
        check_schema(dict(info.parameters), location=location)
    except AIError as error:
        raise AISchemaError(
            f"{location} uses a JSON Schema keyword this framework does not implement, so it is "
            f"refused rather than offered to a model with arguments nothing could check: {error}"
        ) from error


def _project(client: McpClient, info: McpToolInfo) -> Tool:
    """Build the :class:`Tool` for one server tool."""
    spec = ToolSpec(
        name=f"{client.settings.name}_{info.name}",
        description=_describe(info.description),
        parameters=info.parameters,
    )

    async def handler(arguments: Mapping[str, object], context: ToolContext) -> str:
        result = await client.call_tool(info.name, dict(arguments))
        if result.is_error:
            raise AIToolError(
                f"server {client.settings.name!r} reported an error calling {info.name!r}: "
                f"{result.text}",
                tool=spec.name,
            )
        return result.text

    return Tool(spec=spec, handler=handler)


def _describe(description: str) -> str:
    if len(description) <= MAX_DESCRIPTION_LENGTH:
        return description
    return description[:MAX_DESCRIPTION_LENGTH] + "..."
