# Consuming MCP tools

> Status: preview API. `xyberos.mcp` ships with the core package and needs nothing beyond the standard
> library, so there is no extra to install. The `expose()` direction and a stdio transport live in the
> `xyberos-mcp` package instead, because spawning a process is a policy decision rather than a client
> feature ([ADR 0018](adr/0018-capability-placement-rule.md)).

An MCP server offers tools. This module turns the ones you ask for into ordinary
[`Tool`](ai.md) objects, so the allowlist, argument validation, and result handling an application already
has apply to a remote tool with no second code path.

## What it implements, and what it does not

| Covered | Not covered |
| --- | --- |
| the `initialize` handshake, with the negotiated protocol version checked | prompts, resources, and sampling |
| `tools/list`, following pagination within a bound | server-initiated notifications |
| `tools/call`, including the server's own `isError` flag | a stdio transport, and `expose()` |

The client reports no capabilities during the handshake rather than claiming ones it does not have. It
speaks the MCP revision in `SUPPORTED_PROTOCOL_VERSION`; a server that negotiates a different one is
refused with both versions named, because guessing which side is wrong is worse than stopping.

## Registering a server's tools

```python
from xyberos.mcp import McpClient, McpServerSettings, tools_for

clients = [
    McpClient(
        McpServerSettings(
            name="kb",
            url="http://127.0.0.1:8931/mcp",
            tools=("search", "fetch"),  # the opt-in, by the server's own names
            timeout=30.0,
        )
    )
]

tools = await tools_for(clients)   # one Tool per opted-in tool, namespaced "kb_search", "kb_fetch"
```

Then hand the set to the facade like any other:

```python
from xyberos.ai import ToolSet

toolset = ToolSet(tools)
response = await facade.chat_with_tools(request, tools=toolset)
```

Why it is shaped this way:

- **The opt-in is by name and it is required.** A server with nothing opted into registers nothing, so
  the settings refuse an empty list rather than leaving you with a silent no-op.
- **Names are namespaced `{server}_{tool}`.** The server only ever sees its own tool name, and two
  servers can contribute a `search` without colliding.
- **Registration happens at startup.** Every client is initialized, every tool you asked for must exist
  on the server, and an unreachable server fails here rather than on the first tool call.
- **A tool you did not opt into is invisible.** That is what makes one unsupported tool on an otherwise
  useful server cost you that tool and nothing else.

## Schemas, and why one tool can be refused

Arguments are validated against the tool's declared schema through the
[closed JSON Schema subset](ai.md) this framework implements, and by the same machinery that validates a
local tool's arguments. A schema outside that subset — `oneOf`, `$ref`, `pattern` — is refused at
registration, naming the server, the tool, and the keyword:

```
AISchemaError: the schema of tool 'fancy' from server 'kb' uses a JSON Schema keyword this framework
does not implement, so it is refused rather than offered to a model with arguments nothing could check
```

The refusal is per tool, not per server: leave that name out of `tools` and the rest of the server still
works. Validating locally rather than forwarding whatever the model produced is the point — a tool call
the schema rejects never leaves the process.

## Failures, and how to tell them apart

| Error | Means |
| --- | --- |
| `McpTransportError` | the server could not be reached, answered an HTTP error, or returned a body that is not JSON-RPC. It is also a `TransientError`, so a retry is a classification rather than a guess |
| `McpProtocolError` | the server answered a JSON-RPC error, or a result that is not the shape the method promises — including a different negotiated protocol version. Deliberately *not* transient |
| `McpConfigurationError` | the settings are unusable, or name a tool the server does not offer |
| `AISchemaError` | the tool's declared schema is outside the subset this framework can validate |
| a failed `ToolResult` | the server ran the tool and reported an error. It is a result, not an exception, so an agent loop can hand it back to the model |

Settings refuse a `name` that is not an identifier (it prefixes every tool name), a URL that is not
`http://` or `https://`, an empty or duplicated opt-in, and a non-positive timeout.

## Treating a server as untrusted

A server's descriptions, results, and schemas are **data**, and the client treats them that way: nothing
is interpreted or evaluated, nothing is logged, a description is truncated to
`MAX_DESCRIPTION_LENGTH` so a server cannot inflate every prompt that carries it, and a content block
that is not text is described (`[image content]`) rather than dropped. The tool's *schema* is never
truncated, because that is what validates arguments.

The transport is streamable HTTP, so there is no process to spawn, no shell, and no filesystem access
granted by registering a server. Spawning one is a decision the `xyberos-mcp` package leaves to the
application and its operator.
