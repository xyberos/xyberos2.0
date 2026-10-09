from __future__ import annotations

from xyberos.subsystems.p2p.contracts import PeerIdentity, PeerIdentityProvider


class ConfiguredPeerIdentityProvider(PeerIdentityProvider):
    """Development identity provider using a configured, stable peer ID."""

    def __init__(self) -> None:
        self._identity: PeerIdentity | None = None

    @property
    def provider_name(self) -> str:
        return "configured_identity"

    async def initialize(self, config: dict[str, object]) -> None:
        unknown_keys = set(config) - {"peer_id"}
        if unknown_keys:
            raise ValueError(
                f"Unknown identity config keys: {', '.join(sorted(unknown_keys))}."
            )
        peer_id = config.get("peer_id")
        if not isinstance(peer_id, str) or not peer_id.strip():
            raise ValueError("Peer identity config requires a non-empty 'peer_id'.")
        self._identity = PeerIdentity(peer_id.strip())

    async def close(self) -> None:
        self._identity = None

    async def get_identity(self) -> PeerIdentity:
        if self._identity is None:
            raise RuntimeError("Configured peer identity provider is not initialized.")
        return self._identity
