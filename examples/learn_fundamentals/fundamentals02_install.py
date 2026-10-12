"""Lesson 2 — what installing Xyberos gives you, and what it deliberately does not.

The core package imports no optional capability, so a missing extra is a stated requirement rather
than an import error somewhere else. This module proves the property by running: it records what is
loaded before the AI import, and asks the facade for an answer with no SDK involved.
"""

from __future__ import annotations

import asyncio
import sys

import xyberos


async def main() -> None:
    """Show that the core package, and the AI facade, need no extra installed."""
    print(f"xyberos {xyberos.__version__}")

    before = "httpx" in sys.modules
    from xyberos.ai import AIFacade, ChatRequest, FakeModelProvider, Message, ModelReply

    print("importing the AI facade pulled in an SDK:", "httpx" in sys.modules and not before)

    facade = AIFacade(FakeModelProvider([ModelReply.ok("hello from the fake")]))
    answer = await facade.chat(ChatRequest(messages=(Message.user("hi"),), model="fake"))
    print("an answer with no SDK installed:", answer.message.content)


if __name__ == "__main__":
    asyncio.run(main())
