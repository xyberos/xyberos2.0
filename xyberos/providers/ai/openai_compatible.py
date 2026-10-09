from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from typing import Any

from xyberos.subsystems.ai.contracts import (
    ModelMessage,
    ModelProvider,
    ModelResponse,
)


class ModelProviderError(RuntimeError):
    """A model endpoint rejected a request or returned an unusable response."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


class OpenAICompatibleProvider(ModelProvider):
    """Async adapter for Ollama-default and other OpenAI-compatible endpoints."""

    DEFAULT_BASE_URL = "http://localhost:11434/v1"
    DEFAULT_MODEL = "llama3.2"
    _MAX_RESPONSE_BYTES = 4 * 1024 * 1024

    def __init__(self) -> None:
        self._base_url: str | None = None
        self._api_key: str | None = None
        self._default_model: str | None = None
        self._timeout_seconds = 30.0
        self._max_input_chars = 100_000
        self._max_output_tokens = 2_048

    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    async def initialize(self, config: Mapping[str, object]) -> None:
        unknown_keys = set(config) - {
            "base_url",
            "api_key",
            "model",
            "timeout_seconds",
            "max_input_chars",
            "max_output_tokens",
        }
        if unknown_keys:
            raise ValueError(
                f"Unknown model provider config keys: {', '.join(sorted(unknown_keys))}."
            )
        base_url = config.get("base_url", self.DEFAULT_BASE_URL)
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("Model provider requires a non-empty 'base_url'.")
        parsed_url = urlsplit(base_url.strip())
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.netloc
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError(
                "'base_url' must be an HTTP(S) URL without credentials, query, or fragment."
            )
        api_key = config.get("api_key")
        if api_key is not None and (
            not isinstance(api_key, str) or not api_key.strip()
        ):
            raise ValueError("'api_key' must be non-empty text when configured.")
        if (
            parsed_url.scheme == "http"
            and parsed_url.hostname not in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError(
                "Non-loopback model endpoints must use HTTPS to protect prompts and credentials."
            )
        default_model = config.get("model", self.DEFAULT_MODEL)
        if default_model is not None and (
            not isinstance(default_model, str) or not default_model.strip()
        ):
            raise ValueError("'model' must be non-empty text when configured.")
        timeout = config.get("timeout_seconds", 30)
        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("'timeout_seconds' must be a positive number.")
        max_input_chars = config.get("max_input_chars", 100_000)
        if (
            not isinstance(max_input_chars, int)
            or isinstance(max_input_chars, bool)
            or max_input_chars < 1
        ):
            raise ValueError("'max_input_chars' must be a positive integer.")
        max_output_tokens = config.get("max_output_tokens", 2_048)
        if (
            not isinstance(max_output_tokens, int)
            or isinstance(max_output_tokens, bool)
            or max_output_tokens < 1
        ):
            raise ValueError("'max_output_tokens' must be a positive integer.")

        self._base_url = base_url.strip().rstrip("/")
        self._api_key = api_key.strip() if isinstance(api_key, str) else None
        self._default_model = default_model.strip() if isinstance(default_model, str) else None
        self._timeout_seconds = float(timeout)
        self._max_input_chars = max_input_chars
        self._max_output_tokens = max_output_tokens

    async def close(self) -> None:
        self._base_url = None
        self._api_key = None
        self._default_model = None
        self._max_input_chars = 100_000
        self._max_output_tokens = 2_048

    async def generate(
        self,
        messages: Sequence[ModelMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: Mapping[str, Any] | None = None,
    ) -> ModelResponse:
        if self._base_url is None:
            raise RuntimeError("Model provider is not initialized.")
        if not messages or not all(isinstance(item, ModelMessage) for item in messages):
            raise ValueError("Model generation requires at least one ModelMessage.")
        if sum(len(message.content) for message in messages) > self._max_input_chars:
            raise ValueError("Model request exceeds configured max_input_chars.")
        selected_model = model or self._default_model
        if not isinstance(selected_model, str) or not selected_model.strip():
            raise ValueError("A model name must be configured or supplied per request.")
        if temperature is not None and (
            not isinstance(temperature, (int, float))
            or isinstance(temperature, bool)
            or not math.isfinite(temperature)
            or not 0 <= temperature <= 2
        ):
            raise ValueError("'temperature' must be between zero and two.")
        if max_tokens is not None and (
            not isinstance(max_tokens, int)
            or isinstance(max_tokens, bool)
            or max_tokens < 1
        ):
            raise ValueError("'max_tokens' must be a positive integer.")
        if max_tokens is not None and max_tokens > self._max_output_tokens:
            raise ValueError("Model request exceeds configured max_output_tokens.")
        if response_format is not None and not isinstance(response_format, Mapping):
            raise ValueError("'response_format' must be a mapping.")

        payload: dict[str, Any] = {
            "model": selected_model.strip(),
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        else:
            payload["max_tokens"] = self._max_output_tokens
        if response_format is not None:
            payload["response_format"] = dict(response_format)

        return await asyncio.to_thread(self._request_sync, payload)

    def _request_sync(self, payload: Mapping[str, Any]) -> ModelResponse:
        if self._base_url is None:
            raise RuntimeError("Model provider is not initialized.")
        headers = {"Content-Type": "application/json"}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            opener = build_opener(_NoRedirectHandler())
            with opener.open(request, timeout=self._timeout_seconds) as response:
                raw_body = response.read(self._MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            exc.close()
            raise ModelProviderError(
                f"Model endpoint returned HTTP {exc.code}."
            ) from exc
        except URLError as exc:
            raise ModelProviderError(
                f"Could not reach model endpoint: {exc.reason}"
            ) from exc

        if len(raw_body) > self._MAX_RESPONSE_BYTES:
            raise ModelProviderError("Model endpoint response exceeded the size limit.")
        try:
            response_data = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelProviderError("Model endpoint returned invalid JSON.") from exc
        if not isinstance(response_data, dict):
            raise ModelProviderError("Model endpoint response must be a JSON object.")
        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ModelProviderError("Model endpoint response contains no choices.")
        message = choices[0].get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ModelProviderError("Model endpoint response contains no text content.")
        response_model = response_data.get("model", payload["model"])
        if not isinstance(response_model, str):
            raise ModelProviderError("Model endpoint response has an invalid model name.")
        usage_value = response_data.get("usage", {})
        usage: dict[str, int] = {}
        if isinstance(usage_value, dict):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage_value.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    usage[key] = value
        finish_reason = choices[0].get("finish_reason")
        return ModelResponse(
            content=message["content"],
            model=response_model,
            provider=self.provider_name,
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
            usage=usage,
        )
