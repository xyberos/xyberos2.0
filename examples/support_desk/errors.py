"""Domain errors the HTTP adapter turns into responses.

The two refusals the path cares about are `401` and `403`, and they answer different questions:
`401` means the request's assertion did not verify, so a client can act on it by authenticating
better; `403` means it verified and the answer is no, so retrying changes nothing. Those live in
``security.py`` next to the verifier; these are about the ticket itself.
"""

from __future__ import annotations

from xyberos import HttpError, RequestValidationError


class TicketValidationError(RequestValidationError):
    """Raised when a ticket's input is invalid; exposed to the client as a 422."""


class TicketNotFoundError(HttpError):
    """Raised when a ticket is not in the caller's tenant; exposed as a 404.

    A ticket in another tenant is reported as *not found* rather than *forbidden*, because a `403`
    would confirm that the ticket exists. The tenant is part of the lookup, not a check after it.
    """

    def __init__(self, ticket_id: int) -> None:
        super().__init__(f"ticket {ticket_id} was not found", status_code=404)
        self.ticket_id = ticket_id


class SuggestionNotFoundError(HttpError):
    """Raised when a ticket has no draft reply; exposed as a 404."""

    def __init__(self, ticket_id: int) -> None:
        super().__init__(f"ticket {ticket_id} has no suggested reply", status_code=404)
        self.ticket_id = ticket_id


class TransitionRefusedError(HttpError):
    """Raised when a ticket is in a state a transition cannot leave; exposed as a 409."""

    def __init__(self, state: str, action: str) -> None:
        super().__init__(f"{action} is not allowed while a ticket is in {state!r}", status_code=409)
        self.state = state
        self.action = action


class ApprovalRequiredError(HttpError):
    """Raised when a reply would be sent without an approved suggestion; exposed as a 409.

    This is the one refusal the path exists to demonstrate: nothing sends a draft, so the send path
    asks for the approval rather than performing it.
    """

    def __init__(self, ticket_id: int) -> None:
        super().__init__(
            f"ticket {ticket_id} has no approved reply, so there is nothing to send",
            status_code=409,
        )
        self.ticket_id = ticket_id
