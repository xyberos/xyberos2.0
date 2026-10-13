"""A stub MCP server over a real socket, built on the standard library alone.

It is deliberately a real HTTP server rather than a patched `urlopen`: the client's transport,
headers, session handling, and event-stream decoding are the parts most likely to be wrong, and none
of them is exercised by a mock. The stub answers the three methods the client implements and records
what it
received, so a test can assert what actually crossed the wire.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType

from xyberos.mcp import SUPPORTED_PROTOCOL_VERSION

TOOL_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"topic": {"type": "string"}},
    "required": ["topic"],
    "additionalProperties": False,
}


@dataclass
class ToolStub:
    """One tool the server offers, and what calling it returns."""

    name: str
    description: str = "A stub tool."
    schema: dict[str, object] = field(default_factory=lambda: dict(TOOL_SCHEMA))
    text: str = "stub result"
    is_error: bool = False


class StubMcpServer:
    """A minimal MCP server for tests, serving one client at a time."""

    def __init__(
        self,
        *,
        tools: list[ToolStub] | None = None,
        protocol_version: str = SUPPORTED_PROTOCOL_VERSION,
        session_id: str | None = None,
        event_stream: bool = False,
        http_status: int | None = None,
        body: bytes | None = None,
        pages: int = 1,
    ) -> None:
        self.tools = tools if tools is not None else [ToolStub(name="search")]
        self.protocol_version = protocol_version
        self.session_id = session_id
        self.event_stream = event_stream
        self.http_status = http_status
        self.body = body
        self.pages = pages
        self.received: list[dict[str, object]] = []
        self.headers: list[dict[str, str]] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> StubMcpServer:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.daemon_threads = True
        server.stub = self  # type: ignore[attr-defined]
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def url(self) -> str:
        assert self._server is not None, "use the stub as a context manager"
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/mcp"

    def handle(self, payload: dict[str, object]) -> tuple[int, bytes, str]:
        """Answer one JSON-RPC message, returning status, body, and content type."""
        self.received.append(payload)
        method = payload.get("method")
        request_id = payload.get("id")

        if request_id is None:
            return 202, b"", "application/json"

        if method == "initialize":
            return self._json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": self.protocol_version,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "stub-server", "version": "9.9"},
                    },
                }
            )

        if method == "tools/list":
            return self._list_tools(payload, request_id)

        if method == "tools/call":
            params = payload.get("params")
            name = params.get("name") if isinstance(params, dict) else None
            stub = next((tool for tool in self.tools if tool.name == name), None)
            if stub is None:
                return self._json(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32602, "message": f"unknown tool {name!r}"},
                    }
                )
            content: list[dict[str, object]] = [{"type": "text", "text": stub.text}]
            if stub.name == "with_image":
                content.append({"type": "image", "mimeType": "image/png", "data": "..."})
            return self._json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"content": content, "isError": stub.is_error},
                }
            )

        return self._json(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"the stub implements no method {method!r}"},
            }
        )

    def _list_tools(self, payload: dict[str, object], request_id: object) -> tuple[int, bytes, str]:
        per_page = max(1, -(-len(self.tools) // max(1, self.pages)))
        params = payload.get("params")
        page = 0
        if isinstance(params, dict) and isinstance(params.get("cursor"), str):
            page = int(params["cursor"])
        window = self.tools[page * per_page : (page + 1) * per_page]
        result: dict[str, object] = {
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.schema,
                }
                for tool in window
            ]
        }
        if (page + 1) * per_page < len(self.tools):
            result["nextCursor"] = str(page + 1)
        return self._json({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _json(self, message: dict[str, object]) -> tuple[int, bytes, str]:
        body = json.dumps(message).encode("utf-8")
        if self.event_stream:
            return 200, b"event: message\ndata: " + body + b"\n\n", "text/event-stream"
        return 200, body, "application/json"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 - the name is HTTP's, not ours
        stub: StubMcpServer = self.server.stub  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        stub.headers.append(dict(self.headers.items()))
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"jsonrpc": "2.0", "method": "<unparsable>", "id": None}

        if stub.http_status is not None:
            status, body, content_type = (
                stub.http_status,
                b"the stub was told to fail",
                "text/plain",
            )
        elif stub.body is not None:
            status, body, content_type = 200, stub.body, "application/json"
        else:
            status, body, content_type = stub.handle(payload)

        self.send_response(status)
        if stub.session_id:
            self.send_header("Mcp-Session-Id", stub.session_id)
        if body:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Stay quiet: a test's output is the test's."""
