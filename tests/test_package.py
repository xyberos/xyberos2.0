from xyberos import __version__


def test_package_imports_without_optional_capabilities() -> None:
    assert __version__ == "0.0.0"
