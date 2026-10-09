from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedIdentity:
    """Identity established by a trusted authentication mechanism."""

    actor_id: str
    tenant_id: str

    def __post_init__(self) -> None:
        if not self.actor_id.strip():
            raise ValueError("Authenticated actor_id must not be empty.")
        if not self.tenant_id.strip():
            raise ValueError("Authenticated tenant_id must not be empty.")
