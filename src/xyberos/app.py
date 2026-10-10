"""The application-local runtime, lifecycle, and dependency resolver."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Hashable, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import TypeVar, cast, overload

from xyberos.config import Settings
from xyberos.errors import (
    DependencyResolutionError,
    LifecycleError,
    LifecycleStateError,
    MissingProviderError,
    ShutdownError,
)
from xyberos.routing import Handler, Route, RouteRegistry
from xyberos.runtime.dependencies import (
    _UNSET,
    CloseHook,
    Contract,
    Provider,
    ProviderRegistry,
    Scope,
)
from xyberos.runtime.lifecycle import LifecycleState

T = TypeVar("T")


class RequestContext:
    """Owns request-scoped dependencies for one bounded unit of work."""

    def __init__(self, app: App) -> None:
        self._app = app
        self._instances: dict[Contract, object] = {}
        self._locks: dict[Contract, asyncio.Lock] = {}
        self._owned: list[tuple[Provider, object]] = []
        self._closed = False

    @overload
    async def resolve(self, contract: type[T]) -> T: ...

    @overload
    async def resolve(self, contract: Contract) -> object: ...

    async def resolve(self, contract: type[T] | Contract) -> object:
        """Resolve a dependency within this request's ownership boundary."""
        if self._closed:
            raise LifecycleStateError("request context is already closed")
        return await self._app._resolve(cast(Contract, contract), request=self, path=())

    async def close(self) -> None:
        """Release request-owned resources in reverse dependency order."""
        if self._closed:
            return
        self._closed = True
        failures = await self._app._close_owned(self._owned)
        self._instances.clear()
        if failures:
            raise ShutdownError(failures)

    def _lock_for(self, contract: Contract) -> asyncio.Lock:
        return self._locks.setdefault(contract, asyncio.Lock())


_current_request_context: ContextVar[RequestContext | None] = ContextVar(
    "xyberos_request_context", default=None
)


class App:
    """Compose and run one independent Xyberos application instance."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = Settings.load() if settings is None else settings
        self._registry = ProviderRegistry()
        self._routes = RouteRegistry()
        self._state = LifecycleState.NEW
        self._validated_plan: tuple[Provider, ...] | None = None
        self._app_instances: dict[Contract, object] = {}
        self._app_locks: dict[Contract, asyncio.Lock] = {}
        self._owned: list[tuple[Provider, object]] = []
        self._active_requests: set[RequestContext] = set()
        self._no_active_requests = asyncio.Event()
        self._no_active_requests.set()
        self._lifecycle_lock = asyncio.Lock()

    @property
    def state(self) -> LifecycleState:
        """Return the current application lifecycle state."""
        return self._state

    @property
    def routes(self) -> tuple[Route, ...]:
        """Return the registered route records in registration order."""
        return self._routes.routes

    @property
    def route_version(self) -> int:
        """Return a monotonic count of route registrations for adapter cache invalidation."""
        return self._routes.version

    def provide(
        self,
        contract: Contract,
        factory: Callable[..., object] | None = None,
        *,
        instance: object = _UNSET,
        scope: Scope | str = Scope.APP,
        eager: bool = False,
        close: CloseHook | None = None,
        replace: bool = False,
    ) -> App:
        """Register an explicit typed provider before the application starts."""
        self._ensure_registration_allowed()
        self._registry.register(
            contract,
            factory,
            instance=instance,
            scope=scope,
            eager=eager,
            close=close,
            replace=replace,
        )
        self._validated_plan = None
        if self._state is LifecycleState.VALIDATED:
            self._state = LifecycleState.NEW
        return self

    @overload
    def route(
        self, method: str, path: str, handler: Handler, *, name: str | None = None
    ) -> Handler: ...

    @overload
    def route(
        self, method: str, path: str, *, name: str | None = None
    ) -> Callable[[Handler], Handler]: ...

    def route(
        self,
        method: str,
        path: str,
        handler: Handler | None = None,
        *,
        name: str | None = None,
    ) -> Handler | Callable[[Handler], Handler]:
        """Register a route record, either directly or as a decorator."""
        self._ensure_registration_allowed()
        if handler is not None:
            self._routes.add(method, path, handler, name=name)
            return handler

        def decorator(inner: Handler) -> Handler:
            self._routes.add(method, path, inner, name=name)
            return inner

        return decorator

    def get(self, path: str, *, name: str | None = None) -> Callable[[Handler], Handler]:
        """Register a GET route."""
        return self.route("GET", path, name=name)

    def post(self, path: str, *, name: str | None = None) -> Callable[[Handler], Handler]:
        """Register a POST route."""
        return self.route("POST", path, name=name)

    def put(self, path: str, *, name: str | None = None) -> Callable[[Handler], Handler]:
        """Register a PUT route."""
        return self.route("PUT", path, name=name)

    def patch(self, path: str, *, name: str | None = None) -> Callable[[Handler], Handler]:
        """Register a PATCH route."""
        return self.route("PATCH", path, name=name)

    def delete(self, path: str, *, name: str | None = None) -> Callable[[Handler], Handler]:
        """Register a DELETE route."""
        return self.route("DELETE", path, name=name)

    def validate(self) -> tuple[Provider, ...]:
        """Validate the complete provider graph without constructing services."""
        if self._state not in {LifecycleState.NEW, LifecycleState.VALIDATED}:
            raise LifecycleStateError(
                f"cannot validate an application in {self._state.value!r} state"
            )
        self._validated_plan = self._registry.validate()
        self._state = LifecycleState.VALIDATED
        return self._validated_plan

    async def start(self) -> None:
        """Validate, freeze, and start eager app-scoped resources."""
        async with self._lifecycle_lock:
            if self._state is LifecycleState.READY:
                return
            if self._state not in {LifecycleState.NEW, LifecycleState.VALIDATED}:
                raise LifecycleStateError(
                    f"cannot start an application in {self._state.value!r} state"
                )
            self._state = LifecycleState.STARTING
            try:
                plan = self._validated_plan or self._registry.validate()
                self._registry.freeze()
                for provider in plan:
                    if provider.scope is Scope.APP and provider.eager:
                        await self._resolve(provider.contract, request=None, path=())
            except BaseException as error:
                failures = await self._close_owned(self._owned)
                self._app_instances.clear()
                self._state = LifecycleState.FAILED
                if failures:
                    raise ShutdownError(failures) from error
                raise
            self._state = LifecycleState.READY

    async def stop(self) -> None:
        """Stop accepting work and release app-owned resources safely."""
        async with self._lifecycle_lock:
            if self._state is LifecycleState.STOPPED:
                return
            if self._state in {LifecycleState.NEW, LifecycleState.VALIDATED}:
                self._state = LifecycleState.STOPPED
                return
            if self._state is LifecycleState.FAILED:
                self._state = LifecycleState.STOPPED
                return
            if self._state is not LifecycleState.READY:
                raise LifecycleStateError(
                    f"cannot stop an application in {self._state.value!r} state"
                )
            self._state = LifecycleState.STOPPING
            failures: list[tuple[str, BaseException]] = []
            timeout = self.settings.app.shutdown_timeout
            try:
                if timeout is None:
                    await self._no_active_requests.wait()
                else:
                    await asyncio.wait_for(self._no_active_requests.wait(), timeout)
            except asyncio.TimeoutError:
                active = len(self._active_requests)
                failures.append(
                    (
                        f"{active} in-flight request context(s)",
                        LifecycleError(f"shutdown timed out after {timeout}s"),
                    )
                )
            failures.extend(await self._close_owned(self._owned))
            self._app_instances.clear()
            self._state = LifecycleState.STOPPED
            if failures:
                raise ShutdownError(failures)

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[App]:
        """Run the application for the duration of an async context manager."""
        await self.start()
        try:
            yield self
        finally:
            await self.stop()

    @asynccontextmanager
    async def request_context(self) -> AsyncIterator[RequestContext]:
        """Create a request-scoped dependency and cleanup boundary."""
        self._ensure_ready("create a request context")
        request = RequestContext(self)
        self._active_requests.add(request)
        self._no_active_requests.clear()
        token = _current_request_context.set(request)
        try:
            yield request
        finally:
            try:
                await request.close()
            finally:
                _current_request_context.reset(token)
                self._active_requests.discard(request)
                if not self._active_requests:
                    self._no_active_requests.set()

    @overload
    async def resolve(self, contract: type[T]) -> T: ...

    @overload
    async def resolve(self, contract: Contract) -> object: ...

    async def resolve(self, contract: type[T] | Contract) -> object:
        """Resolve an app or active request dependency."""
        self._ensure_ready("resolve dependencies")
        return await self._resolve(
            cast(Contract, contract), request=_current_request_context.get(), path=()
        )

    def with_overrides(self, overrides: Mapping[Contract, object]) -> App:
        """Clone registrations into an independent app with test-value overrides."""
        clone = App(settings=self.settings)
        clone._registry = self._registry.clone()
        clone._routes = self._routes.clone()
        for contract, value in overrides.items():
            original = clone._registry.get(contract)
            if original is None:
                raise MissingProviderError(
                    f"cannot override {_contract_name(contract)} because it is not registered"
                )
            clone._registry.register(
                contract,
                instance=value,
                scope=original.scope,
                eager=original.eager,
                replace=True,
                source="test override",
            )
        return clone

    async def _resolve(
        self,
        contract: Contract,
        *,
        request: RequestContext | None,
        path: tuple[Contract, ...],
    ) -> object:
        current_path = path + (contract,)
        provider = self._registry.get(contract)
        if provider is None:
            raise MissingProviderError(
                f"no provider is registered for {_contract_name(contract)}",
                path=current_path,
            )
        if provider.scope is Scope.APP:
            return await self._resolve_app_provider(provider, request, current_path)
        if provider.scope is Scope.REQUEST:
            if request is None:
                raise DependencyResolutionError(
                    f"request-scoped {_contract_name(contract)} requires an active request context",
                    path=current_path,
                )
            return await self._resolve_request_provider(provider, request, current_path)
        return await self._create_instance(provider, request, current_path)

    async def _resolve_app_provider(
        self,
        provider: Provider,
        request: RequestContext | None,
        path: tuple[Contract, ...],
    ) -> object:
        existing = self._app_instances.get(provider.contract, _UNSET)
        if existing is not _UNSET:
            return existing
        lock = self._app_locks.setdefault(provider.contract, asyncio.Lock())
        async with lock:
            existing = self._app_instances.get(provider.contract, _UNSET)
            if existing is not _UNSET:
                return existing
            instance = await self._create_instance(provider, request, path)
            self._app_instances[provider.contract] = instance
            if _needs_cleanup(provider, instance):
                self._owned.append((provider, instance))
            return instance

    async def _resolve_request_provider(
        self,
        provider: Provider,
        request: RequestContext,
        path: tuple[Contract, ...],
    ) -> object:
        existing = request._instances.get(provider.contract, _UNSET)
        if existing is not _UNSET:
            return existing
        async with request._lock_for(provider.contract):
            existing = request._instances.get(provider.contract, _UNSET)
            if existing is not _UNSET:
                return existing
            instance = await self._create_instance(provider, request, path)
            request._instances[provider.contract] = instance
            if _needs_cleanup(provider, instance):
                request._owned.append((provider, instance))
            return instance

    async def _create_instance(
        self,
        provider: Provider,
        request: RequestContext | None,
        path: tuple[Contract, ...],
    ) -> object:
        arguments: dict[str, object] = {}
        for dependency in provider.dependencies:
            arguments[dependency.parameter] = await self._resolve(
                dependency.contract,
                request=request,
                path=path,
            )
        try:
            created = provider.factory(**arguments)
            instance = await _await_if_needed(created)
        except DependencyResolutionError:
            raise
        except BaseException as error:
            raise DependencyResolutionError(
                f"failed to construct {_contract_name(provider.contract)} from {provider.source}",
                path=path,
            ) from error
        try:
            _validate_instance(provider, instance, path)
            if provider.scope is Scope.TRANSIENT and _needs_cleanup(provider, instance):
                raise DependencyResolutionError(
                    f"transient {_contract_name(provider.contract)} returned a managed resource; "
                    "use request or app scope instead",
                    path=path,
                )
        except DependencyResolutionError:
            await self._close_resource(provider, instance)
            raise
        return instance

    async def _close_owned(
        self, owned: list[tuple[Provider, object]]
    ) -> tuple[tuple[str, BaseException], ...]:
        failures: list[tuple[str, BaseException]] = []
        while owned:
            provider, instance = owned.pop()
            try:
                await self._close_resource(provider, instance)
            except BaseException as error:
                failures.append((_contract_name(provider.contract), error))
        return tuple(failures)

    async def _close_resource(self, provider: Provider, instance: object) -> None:
        if provider.close is not None:
            await _await_if_needed(provider.close(instance))
            return
        for method_name in ("aclose", "close"):
            method = getattr(instance, method_name, None)
            if callable(method):
                await _await_if_needed(method())
                return

    def _ensure_registration_allowed(self) -> None:
        if self._state not in {LifecycleState.NEW, LifecycleState.VALIDATED}:
            raise LifecycleStateError(
                f"cannot register providers in {self._state.value!r} application state"
            )

    def _ensure_ready(self, action: str) -> None:
        if self._state is not LifecycleState.READY:
            raise LifecycleStateError(
                f"cannot {action} while application state is {self._state.value!r}"
            )


async def _await_if_needed(value: object) -> object:
    if inspect.isawaitable(value):
        return await cast(Awaitable[object], value)
    return value


def _validate_instance(provider: Provider, instance: object, path: tuple[Contract, ...]) -> None:
    contract = provider.contract
    if not isinstance(contract, type) or getattr(contract, "_is_protocol", False):
        return
    try:
        valid = isinstance(instance, contract)
    except TypeError:
        return
    if not valid:
        raise DependencyResolutionError(
            f"provider for {_contract_name(contract)} returned {type(instance).__name__}",
            path=path,
        )


def _needs_cleanup(provider: Provider, instance: object) -> bool:
    return provider.close is not None or any(
        callable(getattr(instance, method_name, None)) for method_name in ("aclose", "close")
    )


def _contract_name(contract: Hashable) -> str:
    return getattr(contract, "__qualname__", repr(contract))
