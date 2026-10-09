"""Local-only runnable demo app; replace this authentication before deployment."""

from apps.example_crud_app.app import create_app
from xyberos.kernel import Capability, ExecutionContext, PolicyEngine
from xyberos.kernel.security import AuthenticatedIdentity
from xyberos.providers.ai import OpenAICompatibleProvider

_DEMO_TOKEN = "Bearer xyberos-local-demo"
_DEMO_IDENTITIES = {
    _DEMO_TOKEN: AuthenticatedIdentity(actor_id="demo-user", tenant_id="demo-tenant"),
}


async def resolve_demo_identity(request):
    return _DEMO_IDENTITIES.get(request.headers.get("authorization"))


class _DemoPolicy(PolicyEngine):
    async def authorize(
        self,
        context: ExecutionContext,
        capability: Capability,
        resource: object = None,
    ) -> bool:
        del resource
        return (
            capability.name == "ai.generate"
            and context.actor_id == "demo-user"
            and context.tenant_id == "demo-tenant"
        )


app = create_app(
    identity_resolver=resolve_demo_identity,
    model_provider=OpenAICompatibleProvider(),
    policy_engine=_DemoPolicy(),
)
