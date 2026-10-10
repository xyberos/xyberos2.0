"""Helpers for reading request input with client-safe validation errors."""

from __future__ import annotations

import json
from typing import cast

from starlette.requests import Request

from xyberos.errors import RequestValidationError


async def read_json_object(request: Request) -> dict[str, object]:
    """Return the request body as a JSON object, or raise an actionable validation error."""
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RequestValidationError("the request body must be valid JSON") from error
    if not isinstance(payload, dict):
        raise RequestValidationError("the request body must be a JSON object")
    return cast("dict[str, object]", payload)
