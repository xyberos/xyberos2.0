"""Explicit typed provider registration and dependency-graph validation."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, TypeAlias, cast, get_args, get_origin, get_type_hints

from xyberos.errors import (
    DependencyCycleError,
    MissingProviderError,
    RegistrationError,
    ScopeViolationError,
)

Contract: TypeAlias = Hashable
ProviderFactory: TypeAlias = Callable[..., object]
CloseHook: TypeAlias = Callable[[object], object]
# Shared with the ``App`` facade so "no instance supplied" is recognized across both layers.
_UNSET = object()


class Scope(str, Enum):
    """Supported ownership scopes for provider instances."""

    APP = "app"
    REQUEST = "request"
    TRANSIENT = "transient"

    @classmethod
    def parse(cls, value: Scope | str) -> Scope:
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError as error:
            supported = ", ".join(scope.value for scope in cls)
            raise RegistrationError(
                f"unsupported provider scope {value!r}; expected one of: {supported}"
            ) from error


@dataclass(frozen=True)
class Inject:
    """Marks an ``Annotated`` parameter as an explicit provider dependency."""

    contract: Contract | None = None


@dataclass(frozen=True)
class Dependency:
    """A provider dependency bound to a factory parameter name."""

    parameter: str
    contract: Contract


@dataclass(frozen=True)
class Provider:
    """A complete, immutable provider registration."""

    contract: Contract
    factory: ProviderFactory
    scope: Scope
    dependencies: tuple[Dependency, ...]
    eager: bool
    close: CloseHook | None
    source: str
    order: int


class ProviderRegistry:
    """An application-local registry that can be frozen before serving work."""

    def __init__(self) -> None:
        self._providers: dict[Contract, Provider] = {}
        self._frozen = False
        self._next_order = 0

    @property
    def frozen(self) -> bool:
        """Whether registrations are immutable."""
        return self._frozen

    def register(
        self,
        contract: Contract,
        factory: ProviderFactory | None = None,
        *,
        instance: object = _UNSET,
        scope: Scope | str = Scope.APP,
        eager: bool = False,
        close: CloseHook | None = None,
        replace: bool = False,
        source: str = "application",
    ) -> Provider:
        """Register a provider and infer its explicit annotated dependencies."""
        self._ensure_mutable()
        _ensure_hashable(contract, "provider contract")
        parsed_scope = Scope.parse(scope)
        if eager and parsed_scope is not Scope.APP:
            raise RegistrationError("only app-scoped providers may be eager")
        if close is not None and not callable(close):
            raise RegistrationError("provider close hook must be callable")
        if contract in self._providers and not replace:
            raise RegistrationError(
                f"a provider is already registered for {_contract_name(contract)}; "
                "use an explicit replacement for tests or configuration"
            )
        if instance is not _UNSET and factory is not None:
            raise RegistrationError("provide either a factory or an instance, not both")
        provided_instance = instance is not _UNSET
        if provided_instance:
            factory = _instance_factory(instance)
        elif factory is None:
            if not inspect.isclass(contract):
                raise RegistrationError(
                    f"a factory is required when {_contract_name(contract)} is not a class contract"
                )
            factory = cast(ProviderFactory, contract)
        if not callable(factory):
            raise RegistrationError("provider factory must be callable")

        dependencies = _dependencies_from_factory(factory)
        if not provided_instance:
            _validate_factory_contract(contract, factory)
        provider = Provider(
            contract=contract,
            factory=factory,
            scope=parsed_scope,
            dependencies=dependencies,
            eager=eager,
            close=close,
            source=source,
            order=self._next_order,
        )
        self._next_order += 1
        self._providers[contract] = provider
        return provider

    @property
    def providers(self) -> tuple[Provider, ...]:
        """Return the registered providers in registration order."""
        return tuple(self._providers.values())

    def get(self, contract: Contract) -> Provider | None:
        """Return a provider without mutating the registry."""
        return self._providers.get(contract)

    def require(self, contract: Contract) -> Provider:
        """Return a provider or report the missing contract."""
        provider = self.get(contract)
        if provider is None:
            raise MissingProviderError(f"no provider is registered for {_contract_name(contract)}")
        return provider

    def validate(self) -> tuple[Provider, ...]:
        """Validate all providers and return them in dependency-safe order."""
        visited: set[Contract] = set()
        active: list[Contract] = []
        ordered: list[Provider] = []

        def visit(contract: Contract) -> None:
            if contract in visited:
                return
            if contract in active:
                start = active.index(contract)
                cycle = tuple(active[start:] + [contract])
                raise DependencyCycleError(
                    f"dependency cycle detected: {_format_path(cycle)}",
                    path=cycle,
                )
            provider = self.get(contract)
            if provider is None:
                path = tuple(active + [contract])
                raise MissingProviderError(
                    f"no provider is registered for {_contract_name(contract)}; "
                    f"required by {_format_path(path[:-1])}",
                    path=path,
                )
            active.append(contract)
            for dependency in provider.dependencies:
                dependency_provider = self.get(dependency.contract)
                path = tuple(active + [dependency.contract])
                if dependency_provider is None:
                    raise MissingProviderError(
                        f"no provider is registered for {_contract_name(dependency.contract)}; "
                        f"required by {_format_path(active)}",
                        path=path,
                    )
                if _scope_rank(provider.scope) > _scope_rank(dependency_provider.scope):
                    raise ScopeViolationError(
                        f"{provider.scope.value}-scoped {_contract_name(provider.contract)} cannot "
                        f"depend on shorter-lived {dependency_provider.scope.value}-scoped "
                        f"{_contract_name(dependency.contract)}",
                        path=path,
                    )
                visit(dependency.contract)
            active.pop()
            visited.add(contract)
            ordered.append(provider)

        for provider in sorted(self._providers.values(), key=lambda item: item.order):
            visit(provider.contract)
        return tuple(ordered)

    def freeze(self) -> None:
        """Prevent further registration changes after startup validation."""
        self._frozen = True

    def clone(self) -> ProviderRegistry:
        """Create an unfrozen copy for an isolated application or test override."""
        clone = ProviderRegistry()
        clone._providers = dict(self._providers)
        clone._next_order = self._next_order
        return clone

    def _ensure_mutable(self) -> None:
        if self._frozen:
            raise RegistrationError("provider registrations are frozen after application startup")


def _dependencies_from_factory(factory: ProviderFactory) -> tuple[Dependency, ...]:
    target = factory.__init__ if inspect.isclass(factory) else factory
    try:
        signature = inspect.signature(factory)
        annotations = get_type_hints(target, include_extras=True)
    except (NameError, TypeError, ValueError) as error:
        factory_name = _factory_name(factory)
        raise RegistrationError(f"cannot inspect provider factory {factory_name}") from error

    dependencies: list[Dependency] = []
    for parameter in signature.parameters.values():
        if parameter.name in {"self", "cls"}:
            continue
        if parameter.kind in {parameter.VAR_KEYWORD, parameter.VAR_POSITIONAL}:
            raise RegistrationError(
                f"provider factory {_factory_name(factory)} cannot declare *args or **kwargs"
            )
        annotation = annotations.get(parameter.name)
        marker = _inject_marker(annotation)
        if marker is None:
            if parameter.default is inspect.Parameter.empty:
                raise RegistrationError(
                    f"required parameter {parameter.name!r} on {_factory_name(factory)} must use "
                    "Annotated[T, Inject()]"
                )
            continue
        contract = marker.contract if marker.contract is not None else _annotated_type(annotation)
        if contract is None:
            raise RegistrationError(
                f"injected parameter {parameter.name!r} on {_factory_name(factory)} "
                "needs a type contract"
            )
        _ensure_hashable(contract, f"dependency for parameter {parameter.name!r}")
        dependencies.append(Dependency(parameter=parameter.name, contract=contract))
    return tuple(dependencies)


def _inject_marker(annotation: object | None) -> Inject | None:
    if get_origin(annotation) is not Annotated:
        return None
    markers = [value for value in get_args(annotation)[1:] if isinstance(value, Inject)]
    if len(markers) > 1:
        raise RegistrationError("an injected parameter may declare at most one Inject marker")
    return markers[0] if markers else None


def _annotated_type(annotation: object | None) -> Contract | None:
    if get_origin(annotation) is not Annotated:
        return None
    return cast(Contract, get_args(annotation)[0])


def _validate_factory_contract(contract: Contract, factory: ProviderFactory) -> None:
    if not isinstance(contract, type):
        return
    if inspect.isclass(factory) and isinstance(factory, type):
        _ensure_assignable(factory, contract, factory)
        return
    try:
        return_annotation = get_type_hints(factory, include_extras=True).get("return")
    except (NameError, TypeError, ValueError) as error:
        raise RegistrationError(
            f"cannot inspect provider factory {_factory_name(factory)}"
        ) from error
    if isinstance(return_annotation, type):
        _ensure_assignable(return_annotation, contract, factory)


def _ensure_assignable(candidate: type[object], contract: type[object], factory: object) -> None:
    if getattr(contract, "_is_protocol", False):
        return
    try:
        compatible = issubclass(candidate, contract)
    except TypeError:
        return
    if not compatible:
        raise RegistrationError(
            f"provider factory {_factory_name(factory)} returns {candidate.__name__}, which is not "
            f"compatible with {_contract_name(contract)}"
        )


def _instance_factory(instance: object) -> ProviderFactory:
    def factory() -> object:
        return instance

    return factory


def _scope_rank(scope: Scope) -> int:
    return {Scope.APP: 3, Scope.REQUEST: 2, Scope.TRANSIENT: 1}[scope]


def _ensure_hashable(value: object, description: str) -> None:
    try:
        hash(value)
    except TypeError as error:
        raise RegistrationError(f"{description} must be hashable") from error


def _factory_name(factory: object) -> str:
    return getattr(factory, "__qualname__", repr(factory))


def _contract_name(contract: object) -> str:
    return getattr(contract, "__qualname__", repr(contract))


def _format_path(path: tuple[Contract, ...] | list[Contract]) -> str:
    return " -> ".join(_contract_name(contract) for contract in path)
