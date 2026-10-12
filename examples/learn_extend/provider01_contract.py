"""Walkthrough — a database provider, checked by the conformance suite.

Run it with:

    python -m learn_extend.provider01_contract
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from learn_extend.sql_provider import CommitsOnFailure, open_provider
from xyberos.database.testing import assert_provider_contract

#: The suite builds a table of its own, so a provider needs nothing but a working database.
TABLE = "provider_walkthrough"


async def main() -> None:
    """Write a provider, prove it with the suite, and then prove the suite can refuse one."""
    with tempfile.TemporaryDirectory() as directory:
        provider = await open_provider(Path(directory) / "walkthrough.db")
        checked = await assert_provider_contract(provider, table=TABLE)
        print(f"the conformance suite passed {len(checked)} checks:")
        for name in checked:
            print("  -", name)
        await provider.aclose()
        print("aclose() released the engine; the application's shutdown is what calls it")

        inner = await open_provider(Path(directory) / "broken.db")
        try:
            broken = CommitsOnFailure(inner)
            try:
                await assert_provider_contract(broken, table="broken_walkthrough")  # type: ignore[arg-type]
            except AssertionError as error:
                print("a provider that commits rolled-back work is refused:", error)
        finally:
            await inner.aclose()


if __name__ == "__main__":
    asyncio.run(main())
