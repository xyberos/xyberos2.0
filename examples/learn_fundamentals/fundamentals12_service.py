"""The service module lesson 12 inspects.

It imports nothing from Xyberos, and it does not need to: the framework appears in a composition
root and nowhere else. That is what makes this module testable with no application, no event loop,
and no plugin — and it is the single convention the rest of the layout follows.
"""

from __future__ import annotations


class InvoiceLine:
    """One line on an invoice."""

    def __init__(self, description: str, cents: int) -> None:
        self.description = description
        self.cents = cents


class InvoiceFormatter:
    """Turn an amount in cents into the line a person reads."""

    def format(self, cents: int) -> str:
        """Return the amount as dollars and cents."""
        return f"${cents // 100}.{cents % 100:02d}"
