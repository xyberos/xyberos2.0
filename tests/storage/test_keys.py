"""The key rules, which every provider shares.

A key is the one input that reaches a filesystem and a log line at the same time, so the refusals
are tested here rather than in each provider: what a provider does is *call* this, and what this
does is
the contract.
"""

from __future__ import annotations

import pytest

from xyberos.errors import StorageKeyError
from xyberos.storage import MAX_KEY_LENGTH, validate_key


@pytest.mark.parametrize(
    "key",
    [
        "a",
        "a/b",
        "a/b/c.txt",
        "with space/name.txt",
        "unicode-日本語.txt",
        ".hidden",
        "a.b/c-d_e",
        "con-artist.txt",
    ],
)
def test_a_usable_key_is_returned_unchanged(key: str) -> None:
    assert validate_key(key) == key


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("", "must not be empty"),
        ("/leading", "must not start or end with '/'"),
        ("trailing/", "must not start or end with '/'"),
        ("a//b", r"empty, '.' or '\.\.' segment"),
        (".", r"empty, '.' or '\.\.' segment"),
        ("..", r"empty, '.' or '\.\.' segment"),
        ("a/../b", r"empty, '.' or '\.\.' segment"),
        ("../escaped", r"empty, '.' or '\.\.' segment"),
        ("a\\b", "must use '/' as its separator"),
        ("a\x00b", "control character"),
        ("a\nb", "control character"),
        (".xyberos-tmp/x", "reserved for provider bookkeeping"),
        ("x/.xyberos-health", "reserved for provider bookkeeping"),
    ],
)
def test_a_key_the_contract_refuses_names_the_reason(key: str, expected: str) -> None:
    with pytest.raises(StorageKeyError, match=expected):
        validate_key(key)


def test_a_key_longer_than_the_ceiling_is_refused() -> None:
    with pytest.raises(StorageKeyError, match="at most"):
        validate_key("a" * (MAX_KEY_LENGTH + 1))


def test_the_ceiling_is_configurable() -> None:
    assert validate_key("a" * 8, max_length=8) == "a" * 8

    with pytest.raises(StorageKeyError, match="at most 8"):
        validate_key("a" * 9, max_length=8)


def test_a_key_that_is_not_text_is_refused() -> None:
    with pytest.raises(StorageKeyError, match="must be a string"):
        validate_key(b"bytes")  # type: ignore[arg-type]
