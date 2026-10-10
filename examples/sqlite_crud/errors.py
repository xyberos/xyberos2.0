"""Domain errors that the HTTP adapter turns into responses."""

from __future__ import annotations

from xyberos import HttpError, RequestValidationError


class ItemNotFoundError(HttpError):
    """Raised when an item does not exist; exposed to the client as a 404."""

    def __init__(self, item_id: int) -> None:
        super().__init__(f"item {item_id} was not found", status_code=404)
        self.item_id = item_id


class ItemValidationError(RequestValidationError):
    """Raised when item input is invalid; exposed to the client as a 422."""
