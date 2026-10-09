from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from xyberos.kernel.container import DependencyContainer
from xyberos.kernel.contracts import Subsystem

from .contracts import (
    P2PShutdownError,
    PeerIdentityProvider,
    PeerMessageStore,
    PeerTransportProvider,
)
from .messaging import OfflineMessagingService

logger = logging.getLogger("xyberos.subsystems.p2p")


class P2PSubsystem(Subsystem):
    """Lifecycle bundle for explicitly selected local P2P messaging providers."""

    def __init__(
        self,
        identity_provider: PeerIdentityProvider,
        message_store: PeerMessageStore,
        transport_provider: PeerTransportProvider,
    ) -> None:
        if not isinstance(identity_provider, PeerIdentityProvider):
            raise TypeError("identity_provider must implement PeerIdentityProvider.")
        if not isinstance(message_store, PeerMessageStore):
            raise TypeError("message_store must implement PeerMessageStore.")
        if not isinstance(transport_provider, PeerTransportProvider):
            raise TypeError("transport_provider must implement PeerTransportProvider.")
        self._identity_provider = identity_provider
        self._message_store = message_store
        self._transport_provider = transport_provider
        self._initialized: list[
            PeerIdentityProvider | PeerMessageStore | PeerTransportProvider
        ] = []
        self._container: DependencyContainer | None = None

    async def initialize(
        self,
        config: dict[str, Any],
        container: DependencyContainer,
    ) -> None:
        unknown_keys = set(config) - {"identity", "message_store", "transport"}
        if unknown_keys:
            raise ValueError(
                f"Unknown P2P subsystem config keys: {', '.join(sorted(unknown_keys))}."
            )
        provider_settings = (
            ("identity", self._identity_provider),
            ("message_store", self._message_store),
            ("transport", self._transport_provider),
        )
        settings: dict[str, Mapping[str, object]] = {}
        for key in ("identity", "message_store", "transport"):
            value = config.get(key, {})
            if not isinstance(value, Mapping):
                raise ValueError(f"P2P '{key}' config must be a mapping.")
            settings[key] = value

        initialized: list[
            PeerIdentityProvider | PeerMessageStore | PeerTransportProvider
        ] = []
        try:
            for key, provider in provider_settings:
                provider_config = dict(settings[key])
                await provider.initialize(provider_config)
                initialized.append(provider)
            identity = await self._identity_provider.get_identity()
            if not identity.peer_id:
                raise ValueError("Configured peer identity is empty.")
            container.register_utility(
                OfflineMessagingService,
                OfflineMessagingService(
                    self._identity_provider,
                    self._message_store,
                    self._transport_provider,
                ),
            )
        except BaseException:
            for provider in reversed(initialized):
                try:
                    await provider.close()
                except Exception:
                    logger.exception(
                        "Failed to clean up P2P provider after initialization failure."
                    )
            raise

        self._initialized = initialized
        self._container = container

    async def shutdown(self) -> None:
        failures: list[Exception] = []
        try:
            for provider in reversed(self._initialized):
                try:
                    await provider.close()
                except Exception as exc:
                    failures.append(exc)
        finally:
            if self._container is not None:
                self._container.unregister(OfflineMessagingService)
                self._container = None
            self._initialized.clear()
        if failures:
            raise P2PShutdownError(failures) from failures[0]
