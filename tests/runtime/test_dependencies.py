"""Provider registration, graph construction, and validation behavior."""

from typing import Annotated, Protocol

import pytest

from xyberos import (
    DependencyCycleError,
    Inject,
    MissingProviderError,
    ProviderRegistry,
    RegistrationError,
    Scope,
    ScopeViolationError,
)


class Leaf:
    pass


class Middle:
    def __init__(self, leaf: Annotated[Leaf, Inject()]) -> None:
        self.leaf = leaf


class Root:
    def __init__(self, middle: Annotated[Middle, Inject()]) -> None:
        self.middle = middle


class Unregistered:
    pass


class NeedsUnregistered:
    def __init__(self, missing: Annotated[Unregistered, Inject()]) -> None:
        self.missing = missing


class CycleA:
    def __init__(self, other: Annotated["CycleB", Inject()]) -> None:
        self.other = other


class CycleB:
    def __init__(self, other: Annotated["CycleA", Inject()]) -> None:
        self.other = other


class RequestScoped:
    def __init__(self, leaf: Annotated[Leaf, Inject()]) -> None:
        self.leaf = leaf


class AppNeedsRequest:
    def __init__(self, dependency: Annotated[RequestScoped, Inject()]) -> None:
        self.dependency = dependency


class NeedsUnmarkedArgument:
    def __init__(self, leaf: Leaf) -> None:
        self.leaf = leaf


class VariadicFactory:
    def __init__(self, *args: object) -> None:
        self.args = args


class Other:
    pass


class Greeter(Protocol):
    def greet(self) -> str: ...


class FriendlyGreeter:
    def greet(self) -> str:
        return "hi"


def build_leaf() -> Leaf:
    return Leaf()


def build_other() -> Other:
    return Other()


def test_validate_orders_dependencies_before_consumers() -> None:
    registry = ProviderRegistry()
    registry.register(Root)
    registry.register(Leaf)
    registry.register(Middle)

    ordered = registry.validate()

    assert ordered == (registry.require(Leaf), registry.require(Middle), registry.require(Root))


def test_cycle_reports_the_resolution_path() -> None:
    registry = ProviderRegistry()
    registry.register(CycleA)
    registry.register(CycleB)

    with pytest.raises(DependencyCycleError) as info:
        registry.validate()

    assert info.value.path == (CycleA, CycleB, CycleA)
    assert "CycleA -> CycleB -> CycleA" in str(info.value)


def test_missing_provider_reports_the_resolution_path() -> None:
    registry = ProviderRegistry()
    registry.register(NeedsUnregistered)

    with pytest.raises(MissingProviderError) as info:
        registry.validate()

    assert info.value.path == (NeedsUnregistered, Unregistered)
    assert "NeedsUnregistered" in str(info.value)
    assert "Unregistered" in str(info.value)


def test_longer_lived_provider_cannot_depend_on_request_scope() -> None:
    registry = ProviderRegistry()
    registry.register(Leaf)
    registry.register(RequestScoped, scope=Scope.REQUEST)
    registry.register(AppNeedsRequest)

    with pytest.raises(ScopeViolationError) as info:
        registry.validate()

    assert info.value.path == (AppNeedsRequest, RequestScoped)


def test_duplicate_registration_requires_an_explicit_replacement() -> None:
    registry = ProviderRegistry()
    registry.register(Leaf)

    with pytest.raises(RegistrationError):
        registry.register(Leaf)

    replacement = registry.register(Leaf, instance=Leaf(), replace=True)

    assert replacement is registry.require(Leaf)


def test_required_parameter_needs_an_explicit_inject_marker() -> None:
    registry = ProviderRegistry()

    with pytest.raises(RegistrationError) as info:
        registry.register(NeedsUnmarkedArgument)

    assert "Annotated[T, Inject()]" in str(info.value)


def test_factory_and_instance_are_mutually_exclusive() -> None:
    registry = ProviderRegistry()

    with pytest.raises(RegistrationError):
        registry.register(Leaf, build_leaf, instance=Leaf())


def test_non_class_contract_requires_a_factory() -> None:
    registry = ProviderRegistry()

    with pytest.raises(RegistrationError):
        registry.register("cache")


def test_contract_must_be_hashable() -> None:
    registry = ProviderRegistry()

    with pytest.raises(RegistrationError):
        registry.register(["cache"], build_leaf)


def test_supplied_instance_skips_factory_return_validation() -> None:
    registry = ProviderRegistry()
    registry.register(Leaf, instance=Leaf())

    assert registry.validate() == (registry.require(Leaf),)


def test_factory_return_type_must_match_a_class_contract() -> None:
    registry = ProviderRegistry()

    with pytest.raises(RegistrationError) as info:
        registry.register(Leaf, build_other)

    assert "not compatible" in str(info.value)


def test_variadic_factories_are_rejected() -> None:
    registry = ProviderRegistry()

    with pytest.raises(RegistrationError):
        registry.register(VariadicFactory)


def test_protocol_contracts_accept_duck_typed_implementations() -> None:
    registry = ProviderRegistry()
    registry.register(Greeter, FriendlyGreeter)

    assert registry.validate() == (registry.require(Greeter),)


def test_only_app_scope_may_be_eager() -> None:
    registry = ProviderRegistry()

    with pytest.raises(RegistrationError):
        registry.register(Leaf, scope=Scope.REQUEST, eager=True)


def test_unsupported_scope_is_rejected() -> None:
    registry = ProviderRegistry()

    with pytest.raises(RegistrationError) as info:
        registry.register(Leaf, scope="singleton")

    assert "unsupported provider scope" in str(info.value)


def test_frozen_registry_rejects_new_registrations() -> None:
    registry = ProviderRegistry()
    registry.register(Leaf)
    registry.freeze()

    assert registry.frozen is True
    with pytest.raises(RegistrationError):
        registry.register(Middle)


def test_clone_is_independent_and_mutable() -> None:
    registry = ProviderRegistry()
    registry.register(Leaf)

    clone = registry.clone()
    clone.register(Middle)

    assert registry.get(Middle) is None
    assert clone.get(Middle) is not None
    assert clone.frozen is False
