"""Deprecation mechanics: the warning a user sees, and the rules it follows.

The mechanism ships before the first deprecation exists, which is deliberate: adding one should not
require inventing a warning style. These tests are what make it more than dead code.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from xyberos.deprecation import XyberosDeprecationWarning, deprecated, warn_deprecated


def test_the_warning_category_is_a_deprecation_warning() -> None:
    """It must behave like a deprecation: silent by default, escalated by `-W error`."""
    assert issubclass(XyberosDeprecationWarning, DeprecationWarning)


def test_the_warning_names_the_subject_the_replacement_and_the_removal() -> None:
    with pytest.warns(XyberosDeprecationWarning) as caught:
        warn_deprecated(
            "xyberos.App.provide(instance=...)",
            since="0.2",
            removed_in="1.0",
            alternative="App.provide(factory=...)",
        )

    message = str(caught[0].message)
    assert message.startswith("xyberos.App.provide(instance=...) is deprecated since 0.2")
    assert "use App.provide(factory=...) instead" in message
    assert "it will be removed in 1.0" in message


def test_a_deprecation_without_a_replacement_still_says_when_it_goes() -> None:
    with pytest.warns(XyberosDeprecationWarning) as caught:
        warn_deprecated("old_helper", since="0.3")

    message = str(caught[0].message)
    assert "old_helper is deprecated since 0.3" in message
    assert "removed in a future release" in message
    assert "instead" not in message


@pytest.mark.parametrize(
    ("what", "since"),
    [("", "0.1"), ("   ", "0.1"), ("thing", ""), ("thing", "  ")],
)
def test_a_useless_deprecation_is_refused(what: str, since: str) -> None:
    """A warning that does not say what or since is noise, so it is a programming error."""
    with pytest.raises(ValueError):
        warn_deprecated(what, since=since)


def test_the_decorator_warns_on_call_and_still_returns_the_value() -> None:
    @deprecated("old_add", since="0.2", removed_in="1.0", alternative="new_add")
    def old_add(left: int, right: int = 0) -> int:
        """Add two numbers."""
        return left + right

    assert old_add.__name__ == "old_add"
    assert old_add.__doc__ == "Add two numbers."

    with pytest.warns(XyberosDeprecationWarning, match="old_add is deprecated since 0.2"):
        assert old_add(2, right=3) == 5


def test_the_decorator_works_on_an_async_callable() -> None:
    """The warning fires when the coroutine is created, and the coroutine still runs."""

    @deprecated("old_fetch", since="0.4", alternative="fetch")
    async def old_fetch(value: str) -> str:
        return f"fetched:{value}"

    async def scenario() -> str:
        with pytest.warns(XyberosDeprecationWarning, match="old_fetch is deprecated"):
            return await old_fetch("x")

    assert asyncio.run(scenario()) == "fetched:x"


def test_the_decorator_preserves_the_signature_for_tools_and_type_checkers() -> None:
    def original(alpha: int, *, beta: str = "b") -> str:
        return f"{alpha}:{beta}"

    wrapped = deprecated("old_shape", since="0.2")(original)

    assert inspect.signature(wrapped) == inspect.signature(original)
    assert wrapped.__wrapped__ is original  # type: ignore[attr-defined]
    with pytest.warns(XyberosDeprecationWarning):
        assert wrapped(1) == "1:b"
