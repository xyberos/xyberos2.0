"""Domain errors that the HTTP adapter turns into responses."""

from __future__ import annotations

from xyberos import HttpError, RequestValidationError


class UserValidationError(RequestValidationError):
    """Raised when user input is invalid; exposed to the client as a 422."""


class DuplicateEmailError(HttpError):
    """Raised when an email is already registered; exposed to the client as a 409."""

    def __init__(self, email: str) -> None:
        super().__init__(f"{email} is already registered", status_code=409)
        self.email = email


class UserNotFoundError(HttpError):
    """Raised when a user does not exist; exposed to the client as a 404."""

    def __init__(self, user_id: int) -> None:
        super().__init__(f"user {user_id} was not found", status_code=404)
        self.user_id = user_id


class AccountNotLinkedError(HttpError):
    """Raised when a verified principal belongs to no local account; exposed as a 404."""

    def __init__(self, subject: str) -> None:
        super().__init__(f"no local account is linked to {subject}", status_code=404)
        self.subject = subject


class AccountAlreadyLinkedError(HttpError):
    """Raised when a verified principal already has a local account; exposed as a 409."""

    def __init__(self, subject: str) -> None:
        super().__init__(f"{subject} is already linked to an account", status_code=409)
        self.subject = subject
