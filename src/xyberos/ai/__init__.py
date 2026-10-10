"""Provider-neutral AI support, installed with the core package.

The facade, the contracts, the tool contract, the JSON Schema subset, and the deterministic fake
provider have no third-party dependency, so this package is importable without an AI SDK. Provider
adapters are separate modules: ``xyberos.ai.ollama`` needs the ``ollama`` extra, so importing
``xyberos.ai`` never imports one.
"""

from xyberos.ai.contracts import (
    ChatChunk,
    ChatModel,
    ChatRequest,
    ChatResponse,
    EmbeddingModel,
    EmbeddingRequest,
    EmbeddingResponse,
    FinishReason,
    Message,
    ModelCapabilities,
    ModelHealth,
    ModelProvider,
    ModelStatus,
    Role,
    ToolCall,
    ToolSpec,
    Usage,
)
from xyberos.ai.facade import DEFAULT_LOGGER_NAME, AIFacade, LoggingPolicy
from xyberos.ai.schema import check_schema, describe_schema, validate_payload
from xyberos.ai.testing import FakeModelProvider, ModelReply
from xyberos.ai.tools import (
    Tool,
    ToolContext,
    ToolEvent,
    ToolEventSink,
    ToolEventType,
    ToolHandler,
    ToolResult,
    ToolSet,
)

__all__ = [
    "DEFAULT_LOGGER_NAME",
    "AIFacade",
    "ChatChunk",
    "ChatModel",
    "ChatRequest",
    "ChatResponse",
    "EmbeddingModel",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "FakeModelProvider",
    "FinishReason",
    "LoggingPolicy",
    "Message",
    "ModelCapabilities",
    "ModelHealth",
    "ModelProvider",
    "ModelReply",
    "ModelStatus",
    "Role",
    "Tool",
    "ToolCall",
    "ToolContext",
    "ToolEvent",
    "ToolEventSink",
    "ToolEventType",
    "ToolHandler",
    "ToolResult",
    "ToolSet",
    "ToolSpec",
    "Usage",
    "check_schema",
    "describe_schema",
    "validate_payload",
]
