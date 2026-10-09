from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from xyberos.kernel.container import DependencyContainer
from xyberos.kernel.contracts import (
    Capability,
    ExecutionContextAccessor,
    PolicyEngine,
    Subsystem,
)

from .contracts import ModelMessage, ModelProvider, ModelResponse

_MODEL_GENERATION_CAPABILITY = Capability(
    "ai.generate",
    "Send a prompt to the configured model provider.",
)


class _GuardedModelProvider(ModelProvider):
    def __init__(self, provider: ModelProvider, policy_engine: PolicyEngine) -> None:
        self._provider = provider
        self._policy_engine = policy_engine

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    async def initialize(self, config: Mapping[str, object]) -> None:
        del config
        raise RuntimeError("Guarded model providers are initialized by AISubsystem.")

    async def close(self) -> None:
        raise RuntimeError("Guarded model providers are closed by AISubsystem.")

    async def generate(
        self,
        messages: Sequence[ModelMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: Mapping[str, Any] | None = None,
    ) -> ModelResponse:
        try:
            context = ExecutionContextAccessor.get()
        except RuntimeError as exc:
            raise PermissionError(
                "Model generation requires a trusted execution context."
            ) from exc
        if (
            not isinstance(context.tenant_id, str)
            or not context.tenant_id.strip()
            or not isinstance(context.actor_id, str)
            or not context.actor_id.strip()
        ):
            raise PermissionError(
                "Model generation requires a trusted actor and tenant."
            )
        resource = {
            "provider": self._provider.provider_name,
            "model": model,
        }
        if not await self._policy_engine.authorize(
            context,
            _MODEL_GENERATION_CAPABILITY,
            resource,
        ):
            raise PermissionError("Policy denied model generation.")
        return await self._provider.generate(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )


class AISubsystem(Subsystem):
    """Lifecycle adapter that exposes an explicitly selected model provider."""

    def __init__(
        self,
        providers: ModelProvider | Mapping[str, ModelProvider],
    ) -> None:
        if isinstance(providers, ModelProvider):
            self.providers = {providers.provider_name: providers}
        else:
            self.providers = dict(providers)
        if not self.providers:
            raise ValueError("AISubsystem requires at least one model provider.")
        for name, provider in self.providers.items():
            if not isinstance(provider, ModelProvider):
                raise TypeError(
                    f"Model provider '{name}' does not implement ModelProvider."
                )
            if name != provider.provider_name:
                raise ValueError(
                    f"Model provider registry key '{name}' does not match "
                    f"provider name '{provider.provider_name}'."
                )
        self._container: DependencyContainer | None = None
        self._active_provider: ModelProvider | None = None

    async def initialize(
        self,
        config: dict[str, Any],
        container: DependencyContainer,
    ) -> None:
        unknown_keys = set(config) - {"provider", "config"}
        if unknown_keys:
            raise ValueError(
                f"Unknown AI subsystem config keys: {', '.join(sorted(unknown_keys))}."
            )
        provider_name = config.get(
            "provider",
            next(iter(self.providers)) if len(self.providers) == 1 else None,
        )
        if not isinstance(provider_name, str) or provider_name not in self.providers:
            available = ", ".join(sorted(self.providers))
            raise ValueError(
                f"Model provider '{provider_name}' is not registered. "
                f"Available providers: {available}."
            )
        provider_config = config.get("config", {})
        if not isinstance(provider_config, Mapping):
            raise ValueError("Model provider config must be a mapping.")

        try:
            policy_engine = container.resolve(PolicyEngine)
        except KeyError as exc:
            raise RuntimeError(
                "AISubsystem requires an application-registered PolicyEngine."
            ) from exc
        provider = self.providers[provider_name]
        await provider.initialize(provider_config)
        container.register_utility(
            ModelProvider,
            _GuardedModelProvider(provider, policy_engine),
        )
        self._container = container
        self._active_provider = provider

    async def shutdown(self) -> None:
        try:
            if self._active_provider is not None:
                await self._active_provider.close()
        finally:
            if self._container is not None:
                self._container.unregister(ModelProvider)
                self._container = None
            self._active_provider = None
