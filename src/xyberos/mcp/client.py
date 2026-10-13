"""The client: settings, the JSON-RPC exchange, and the three methods it implements.

The HTTP call runs in a worker thread because the standard library has no asynchronous HTTP client.
That is a documented cost, not a hidden one: one thread per request, and the request is bounded by
``timeout``. The alternative — hand-rolling HTTP/1.1 over ``asyncio.open_connection`` — would be
more code, more of it wrong, and a second implementation of chunked encoding and TLS.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from xyberos import __version__
from xyberos.errors import McpConfigurationError, McpProtocolError, McpTransportError

__all__ = [
    "CLIENT_NAME",
    "SUPPORTED_PROTOCOL_VERSION",
    "McpCallResult",
    "McpClient",
    "McpServerInfo",
    "McpServerSettings",
    "McpToolInfo",
]

SUPPORTED_PROTOCOL_VERSION = "2025-06-18"
"""The MCP revision this client speaks. A server that negotiates a different one is refused."""

CLIENT_NAME = "xyberos"
"""What this client reports as its name during initialization."""

_SESSION_HEADER = "Mcp-Session-Id"
_PROTOCOL_HEADER = "MCP-Protocol-Version"
_MAX_LIST_PAGES = 50
"""How many ``tools/list`` pages this client follows before refusing to loop for ever."""


@dataclass(frozen=True)
class McpServerSettings:
    """Everything one MCP server needs: where it is, and which of its tools are wanted.

    ``tools`` is the opt-in and it is deliberately required to be non-empty. It is also what makes a
    server with one unsupported tool usable: a tool whose schema falls outside the closed subset is
    refused at registration, so the operator leaves that name out instead of losing the whole
    server."""

    name: str
    url: str
    tools: tuple[str, ...]
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout: float = 30.0
    protocol_version: str = SUPPORTED_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not self.name.isidentifier():
            raise McpConfigurationError(
                f"the server name {self.name!r} must be an identifier, because it prefixes "
                f"every tool name it contributes"
            )
        scheme = self.url.split("://", 1)[0].lower() if "://" in self.url else ""
        if scheme not in {"http", "https"}:
            raise McpConfigurationError(
                f"the URL of server {self.name!r} must start with http:// or https://: {self.url!r}"
            )
        if not self.tools:
            raise McpConfigurationError(
                f"server {self.name!r} needs a non-empty 'tools'; a server with nothing "
                f"opted into registers nothing, which is a mistake or a server you do not need"
            )
        for tool in self.tools:
            if not isinstance(tool, str) or not tool.strip():
                raise McpConfigurationError(
                    f"the tools of {self.name!r} must be non-empty strings, and {tool!r} is not"
                )
        duplicates = sorted({tool for tool in self.tools if self.tools.count(tool) > 1})
        if duplicates:
            raise McpConfigurationError(
                f"server {self.name!r} opts into the same tool twice: {', '.join(duplicates)}"
            )
        if self.timeout <= 0:
            raise McpConfigurationError(
                f"the timeout of server {self.name!r} must be positive, not {self.timeout}"
            )
        if not isinstance(self.protocol_version, str) or not self.protocol_version.strip():
            raise McpConfigurationError(
                f"the protocol_version of server {self.name!r} must be a non-empty string"
            )


@dataclass(frozen=True)
class McpServerInfo:
    """What a server reports about itself during initialization."""

    name: str
    version: str
    protocol_version: str


@dataclass(frozen=True)
class McpToolInfo:
    """One tool a server offers, as the server described it."""

    name: str
    description: str
    parameters: Mapping[str, object]


@dataclass(frozen=True)
class McpCallResult:
    """The outcome of one ``tools/call``.

    ``is_error`` is the server's own flag. The content is the server's text verbatim — it is data,
    and this client does not paraphrase, reorder, or interpret it.
    """

    tool: str
    text: str
    is_error: bool = False


class McpClient:
    """One MCP server, spoken to over streamable HTTP.

    Everything the client knows is derived from what the server answers: capabilities, tool names,
    and schemas are read, never assumed. A failure to reach the server, or a response that is not
    the shape the method promises, is reported as it happened rather than as an empty result.
    """

    def __init__(self, settings: McpServerSettings) -> None:
        self._settings = settings
        self._session_id: str | None = None
        self._request_id = 0
        self._initialized = False

    @property
    def settings(self) -> McpServerSettings:
        """The settings this client was built with."""
        return self._settings

    @property
    def initialized(self) -> bool:
        """Whether the initialize handshake has completed."""
        return self._initialized

    async def initialize(self) -> McpServerInfo:
        """Perform the handshake, then tell the server the client is ready."""
        result = await self._request(
            "initialize",
            {
                "protocolVersion": self._settings.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": __version__},
            },
        )
        info = result.get("serverInfo")
        if not isinstance(info, Mapping):
            raise McpProtocolError(
                f"server {self._settings.name!r} answered initialize without a serverInfo object"
            )
        negotiated = result.get("protocolVersion")
        if isinstance(negotiated, str) and negotiated != self._settings.protocol_version:
            raise McpProtocolError(
                f"server {self._settings.name!r} negotiated {negotiated!r}, and this client "
                f"speaks {self._settings.protocol_version!r}; pin one of them rather than guessing "
                f"which side is wrong"
            )
        self._initialized = True
        await self._notify("notifications/initialized")
        return McpServerInfo(
            name=_text(info.get("name")),
            version=_text(info.get("version")),
            protocol_version=negotiated
            if isinstance(negotiated, str)
            else self._settings.protocol_version,
        )

    async def list_tools(self) -> tuple[McpToolInfo, ...]:
        """Return every tool the server offers, following pagination within a bound."""
        tool_infos: list[McpToolInfo] = []
        cursor: object = None
        for _ in range(_MAX_LIST_PAGES):
            params: dict[str, object] | None = {"cursor": cursor} if cursor else None
            result = await self._request("tools/list", params)
            entries = result.get("tools")
            if not isinstance(entries, list):
                raise McpProtocolError(
                    f"server {self._settings.name!r} answered tools/list without a list of tools"
                )
            for entry in entries:
                tool_infos.append(self._tool_info(entry))
            cursor = result.get("nextCursor")
            if not cursor:
                return tuple(tool_infos)
        raise McpProtocolError(
            f"server {self._settings.name!r} paginated tools/list past {_MAX_LIST_PAGES} pages, "
            f"so this client stops rather than following it indefinitely"
        )

    async def call_tool(self, name: str, arguments: Mapping[str, object]) -> McpCallResult:
        """Call one tool by its own name — unprefixed, because the server never sees the prefix."""
        result = await self._request("tools/call", {"name": name, "arguments": dict(arguments)})
        return McpCallResult(
            tool=name,
            text=_content_text(result.get("content")),
            is_error=result.get("isError") is True,
        )

    def _tool_info(self, entry: object) -> McpToolInfo:
        if not isinstance(entry, Mapping):
            raise McpProtocolError(
                f"server {self._settings.name!r} listed a tool that is not an object: {entry!r}"
            )
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise McpProtocolError(
                f"server {self._settings.name!r} listed a tool without a usable name"
            )
        schema = entry.get("inputSchema", {"type": "object"})
        if not isinstance(schema, Mapping):
            raise McpProtocolError(
                f"the schema of tool {name!r} from server {self._settings.name!r} is not an object"
            )
        return McpToolInfo(
            name=name,
            description=_text(entry.get("description")),
            parameters=dict(schema),
        )

    async def _request(
        self, method: str, params: Mapping[str, object] | None = None
    ) -> Mapping[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        payload: dict[str, object] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = dict(params)
        message = await self._post(payload)
        error = message.get("error")
        if isinstance(error, Mapping):
            code = error.get("code")
            detail = error.get("message")
            raise McpProtocolError(
                f"server {self._settings.name!r} answered {method} with JSON-RPC error {code!r}: "
                f"{detail!r}"
            )
        result = message.get("result")
        if not isinstance(result, Mapping):
            raise McpProtocolError(
                f"server {self._settings.name!r} answered {method} without a result object"
            )
        return result

    async def _notify(self, method: str) -> None:
        await self._post({"jsonrpc": "2.0", "method": method})

    async def _post(self, payload: Mapping[str, object]) -> Mapping[str, Any]:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request_id = payload.get("id")
        raw, content_type, session_id = await asyncio.to_thread(self._send, body)
        if session_id:
            self._session_id = session_id
        if request_id is None:
            # A notification's answer is an accepted response with no body, by specification.
            return {}
        for message in _messages(raw, content_type, self._settings):
            if message.get("id") == request_id:
                return message
        raise McpProtocolError(
            f"server {self._settings.name!r} answered {payload.get('method')!r} without a reply "
            f"carrying request id {request_id}"
        )

    def _send(self, body: bytes) -> tuple[bytes, str, str | None]:
        """POST ``body`` from a worker thread and return the body, content type, and session ID."""
        request = urllib.request.Request(
            self._settings.url, data=body, method="POST", headers=self._headers()
        )
        try:
            with urllib.request.urlopen(request, timeout=self._settings.timeout) as response:
                return (
                    response.read(),
                    response.headers.get("Content-Type", ""),
                    response.headers.get(_SESSION_HEADER),
                )
        except urllib.error.HTTPError as error:
            detail = error.read()[:200].decode("utf-8", "replace")
            raise McpTransportError(
                f"server {self._settings.name!r} at {self._settings.url} answered HTTP {error.code}"
                f"{f': {detail}' if detail else ''}"
            ) from error
        except urllib.error.URLError as error:
            raise McpTransportError(
                f"server {self._settings.name!r} at {self._settings.url} could not be reached: "
                f"{error.reason}"
            ) from error
        except TimeoutError as error:
            raise McpTransportError(
                f"server {self._settings.name!r} at {self._settings.url} did not answer within "
                f"{self._settings.timeout:g}s"
            ) from error

    def _headers(self) -> dict[str, str]:
        # ``urllib`` title-cases outgoing header names, so the wire spelling is ``Mcp-Session-Id``
        # rather than ``Mcp-Session-Id``-as-written. HTTP header names are case-insensitive by
        # specification, so a server that compares them case-sensitively is the one that is wrong.
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self._settings.headers,
        }
        if self._initialized:
            headers[_PROTOCOL_HEADER] = self._settings.protocol_version
        if self._session_id:
            headers[_SESSION_HEADER] = self._session_id
        return headers


def _messages(
    raw: bytes, content_type: str, settings: McpServerSettings
) -> list[Mapping[str, Any]]:
    """Return the JSON-RPC messages in a response body, whether it is JSON or an event stream."""
    if not raw.strip():
        return []
    if "text/event-stream" in content_type.lower():
        return [_load(payload, settings) for payload in _event_data(raw)]
    return [_load(raw, settings)]


def _event_data(raw: bytes) -> list[bytes]:
    """Return the ``data:`` payloads of a server-sent-event body, in order."""
    payloads: list[bytes] = []
    current: list[bytes] = []
    for line in raw.splitlines():
        if line.startswith(b"data:"):
            current.append(line[len(b"data:") :].strip())
            continue
        if not line.strip() and current:
            payloads.append(b"\n".join(current))
            current = []
    if current:
        payloads.append(b"\n".join(current))
    return payloads


def _load(raw: bytes, settings: McpServerSettings) -> Mapping[str, Any]:
    try:
        message = json.loads(raw)
    except ValueError as error:
        raise McpTransportError(
            f"server {settings.name!r} at {settings.url} answered with a body that is not JSON: "
            f"{raw[:120]!r}"
        ) from error
    if not isinstance(message, Mapping):
        raise McpTransportError(
            f"server {settings.name!r} answered with a JSON value that is not a JSON-RPC message"
        )
    return message


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _content_text(content: object) -> str:
    """Flatten a ``tools/call`` content list into text, describing what is not text.

    A block this client cannot render — an image, an embedded resource, or a type the server
    invented — is named rather than dropped, because a silently missing result is worse than a
    described one.
    """
    if not isinstance(content, Iterable) or isinstance(content, (str, bytes, Mapping)):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, Mapping) and block.get("type") == "text":
            parts.append(_text(block.get("text")))
        elif isinstance(block, Mapping):
            parts.append(f"[{_text(block.get('type')) or 'non-text'} content]")
        else:
            parts.append("[unreadable content block]")
    return "\n".join(parts)
