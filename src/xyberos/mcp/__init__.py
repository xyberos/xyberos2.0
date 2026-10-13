"""A minimal MCP client over the streamable HTTP transport, using only the standard library.

Xyberos speaks JSON-RPC 2.0 to a server the operator names, learns which tools that server offers,
and projects the ones opted into by name into the shipped ``xyberos.ai.tools`` model — so an MCP
tool and a tool written in the application are the same kind of thing, and the allowlist, argument
validation, and result handling are the ones the facade already has.

Three limits are deliberate and stated rather than discovered:

* **The transport is streamable HTTP.** A stdio transport spawns a process, which collides with the
  standing policy that the framework starts nothing and behaves differently on each platform; it
  lives in the ``xyberos-mcp`` package instead ([ADR
  0018](../adr/0018-capability-placement-rule.md)).
* **The client subset is `initialize`, `tools/list`, and `tools/call`.** Prompts, resources,
sampling, and server-initiated notifications are not implemented, and the initialize handshake
reports no client
  capabilities rather than claiming ones that do not exist.
* **A server's descriptions and results are data.** They are never interpreted, never evaluated, and
  never logged; a description is truncated to a bound so a server cannot inflate every prompt, and a
  non-text content block is described rather than silently dropped.

The module needs nothing from PyPI, so it ships with the core package as ``xyberos.mcp`` rather than
as an extra that would install nothing.
"""

from xyberos.mcp.client import (
    CLIENT_NAME,
    SUPPORTED_PROTOCOL_VERSION,
    McpCallResult,
    McpClient,
    McpServerInfo,
    McpServerSettings,
    McpToolInfo,
)
from xyberos.mcp.tools import MAX_DESCRIPTION_LENGTH, tools_for

__all__ = [
    "CLIENT_NAME",
    "MAX_DESCRIPTION_LENGTH",
    "SUPPORTED_PROTOCOL_VERSION",
    "McpCallResult",
    "McpClient",
    "McpServerInfo",
    "McpServerSettings",
    "McpToolInfo",
    "tools_for",
]
