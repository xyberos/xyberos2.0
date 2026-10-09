import asyncio
import json
import unittest
from collections.abc import Mapping, Sequence
from typing import Any

from apps.example_crud_app.app import create_app, migrate_schema
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from xyberos.kernel import (
    Capability,
    ExecutionContext,
    ExecutionContextAccessor,
    PolicyEngine,
    XyberosKernel,
)
from xyberos.http.health import create_health_routes
from xyberos.http.middleware import KernelAdmissionMiddleware
from xyberos.kernel.security import AuthenticatedIdentity
from xyberos.providers.database import SQLiteProvider
from xyberos.subsystems.ai import ModelMessage, ModelProvider, ModelResponse
from xyberos.subsystems.database import Database


class StubModelProvider(ModelProvider):
    def __init__(self):
        self.messages = []
        self.initialized = False

    @property
    def provider_name(self):
        return "stub"

    async def initialize(self, config: Mapping[str, object]) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.initialized = False

    async def generate(
        self,
        messages: Sequence[ModelMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: Mapping[str, Any] | None = None,
    ) -> ModelResponse:
        self.messages.extend(messages)
        return ModelResponse(
            content="Generated: " + messages[0].content,
            model=model or "stub-model",
            provider=self.provider_name,
        )


class DemoTestPolicy(PolicyEngine):
    def __init__(self, allowed: bool):
        self.allowed = allowed
        self.authorized_contexts = []

    async def authorize(
        self,
        context: ExecutionContext,
        capability: Capability,
        resource: Any = None,
    ) -> bool:
        self.authorized_contexts.append((context, capability, resource))
        return self.allowed and capability.name == "ai.generate"


class TestPhaseTwoApplication(unittest.TestCase):
    def test_readiness_reports_bounded_dependency_probe_failures_safely(self):
        async def scenario():
            kernel = XyberosKernel()
            await kernel.bootstrap()

            async def healthy_probe():
                return None

            async def failing_probe():
                raise RuntimeError("database password must not appear")

            async def slow_probe():
                await asyncio.sleep(0.05)

            app = Starlette(
                routes=create_health_routes(
                    kernel,
                    probes={
                        "database": healthy_probe,
                        "model": failing_probe,
                        "relay": slow_probe,
                    },
                    probe_timeout_seconds=0.005,
                )
            )
            try:
                with self.assertLogs("xyberos.http.health", level="WARNING") as logs:
                    response = await self._request(app, "GET", "/health/ready")
                body = json.loads(response["body"])
                self.assertEqual(response["status"], 503)
                self.assertFalse(body["ready"])
                self.assertEqual(
                    body["dependencies"],
                    {
                        "database": "ready",
                        "model": "unavailable",
                        "relay": "unavailable",
                    },
                )
                self.assertNotIn("password", response["body"].decode())
                self.assertNotIn("password", " ".join(logs.output))
            finally:
                await kernel.shutdown()

        asyncio.run(scenario())

    def test_example_readiness_stays_down_until_schema_is_migrated(self):
        async def scenario():
            app = create_app(database_path=":memory:", auto_migrate=False)
            async with app.router.lifespan_context(app):
                with self.assertLogs("xyberos.http.health", level="WARNING"):
                    before = await self._request(app, "GET", "/health/ready")
                before_body = json.loads(before["body"])
                self.assertEqual(before["status"], 503)
                self.assertEqual(
                    before_body["dependencies"],
                    {"database": "unavailable"},
                )

                database = app.state.kernel.container.resolve(Database)
                await migrate_schema(database)
                after = await self._request(app, "GET", "/health/ready")
                after_body = json.loads(after["body"])
                self.assertEqual(after["status"], 200)
                self.assertEqual(after_body["dependencies"], {"database": "ready"})

        asyncio.run(scenario())

    def test_reference_app_integrates_public_health_admission_and_auth(self):
        async def scenario():
            async def resolve_identity(request):
                if request.headers.get("authorization") == "Bearer demo":
                    return AuthenticatedIdentity("alice", "tenant-a")
                return None

            app = create_app(resolve_identity, ":memory:", shutdown_drain_timeout=0.1)
            live_before_start = await self._request(app, "GET", "/health/live")
            ready_before_start = await self._request(app, "GET", "/health/ready")
            blocked_before_start = await self._request(app, "GET", "/items")
            self.assertEqual(live_before_start["status"], 200)
            self.assertEqual(ready_before_start["status"], 503)
            self.assertEqual(blocked_before_start["status"], 503)

            async with app.router.lifespan_context(app):
                ready = await self._request(app, "GET", "/health/ready")
                unauthenticated = await self._request(app, "GET", "/items")
                authenticated = await self._request(
                    app,
                    "POST",
                    "/items",
                    headers=[(b"authorization", b"Bearer demo")],
                    body=json.dumps({"title": "Integrated example"}).encode(),
                )
                self.assertEqual(ready["status"], 200)
                self.assertEqual(unauthenticated["status"], 401)
                self.assertEqual(authenticated["status"], 201)

                await app.state.kernel.shutdown()
                blocked_during_shutdown = await self._request(app, "GET", "/items")
                stopped_ready = await self._request(app, "GET", "/health/ready")
                stopped_live = await self._request(app, "GET", "/health/live")
                self.assertEqual(blocked_during_shutdown["status"], 503)
                self.assertEqual(stopped_ready["status"], 503)
                self.assertEqual(stopped_live["status"], 503)

        asyncio.run(scenario())

    def test_reference_app_optional_ai_endpoint_uses_trusted_context_and_policy(self):
        async def scenario():
            provider = StubModelProvider()
            policy = DemoTestPolicy(allowed=True)

            async def resolve_identity(request):
                if request.headers.get("authorization") == "Bearer demo":
                    return AuthenticatedIdentity("alice", "tenant-a")
                return None

            app = create_app(
                identity_resolver=resolve_identity,
                database_path=":memory:",
                model_provider=provider,
                policy_engine=policy,
            )
            async with app.router.lifespan_context(app):
                no_identity = await self._request(
                    app,
                    "POST",
                    "/ai/generate",
                    body=b'{"prompt":"hello"}',
                )
                generated = await self._request(
                    app,
                    "POST",
                    "/ai/generate",
                    headers=[
                        (b"authorization", b"Bearer demo"),
                        (b"x-tenant-id", b"forged-tenant"),
                        (b"x-actor-id", b"forged-actor"),
                    ],
                    body=b'{"prompt":"hello"}',
                )

                self.assertEqual(no_identity["status"], 401)
                self.assertEqual(generated["status"], 200)
                self.assertEqual(
                    json.loads(generated["body"])["content"],
                    "Generated: hello",
                )
                self.assertEqual(
                    policy.authorized_contexts[0][0].tenant_id,
                    "tenant-a",
                )
                self.assertEqual(
                    policy.authorized_contexts[0][0].actor_id,
                    "alice",
                )
                self.assertEqual(provider.messages[0].content, "hello")
                self.assertTrue(provider.initialized)

            self.assertFalse(provider.initialized)

        asyncio.run(scenario())

    def test_reference_app_returns_forbidden_when_ai_policy_denies(self):
        async def scenario():
            async def resolve_identity(_request):
                return AuthenticatedIdentity("alice", "tenant-a")

            app = create_app(
                identity_resolver=resolve_identity,
                database_path=":memory:",
                model_provider=StubModelProvider(),
                policy_engine=DemoTestPolicy(allowed=False),
            )
            async with app.router.lifespan_context(app):
                response = await self._request(
                    app,
                    "POST",
                    "/ai/generate",
                    body=b'{"prompt":"hello"}',
                )
                self.assertEqual(response["status"], 403)

        asyncio.run(scenario())

    def test_health_routes_and_http_admission_follow_kernel_lifecycle(self):
        async def scenario():
            kernel = XyberosKernel()

            async def work_endpoint(_request):
                return JSONResponse({"ok": True})

            app = Starlette(
                routes=[
                    *create_health_routes(kernel),
                    Route("/work", work_endpoint),
                ]
            )
            app = KernelAdmissionMiddleware(app, kernel)

            live = await self._request(app, "GET", "/health/live")
            ready = await self._request(app, "GET", "/health/ready")
            rejected = await self._request(app, "GET", "/work")
            self.assertEqual(live["status"], 200)
            self.assertEqual(ready["status"], 503)
            self.assertEqual(rejected["status"], 503)

            await kernel.bootstrap()
            ready = await self._request(app, "GET", "/health/ready")
            accepted = await self._request(app, "GET", "/work")
            self.assertEqual(ready["status"], 200)
            self.assertEqual(accepted["status"], 200)
            await kernel.shutdown()

        asyncio.run(scenario())

    def test_http_authentication_and_tenant_scoped_crud(self):
        async def scenario():
            identities = {
                "Bearer alice": AuthenticatedIdentity("alice", "tenant-a"),
                "Bearer bob": AuthenticatedIdentity("bob", "tenant-b"),
            }

            async def resolve_identity(request):
                return identities.get(request.headers.get("authorization"))

            app = create_app(resolve_identity, ":memory:")
            async with app.router.lifespan_context(app):
                created = await self._request(
                    app,
                    "POST",
                    "/items",
                    headers=[
                        (b"authorization", b"Bearer alice"),
                        (b"x-tenant-id", b"tenant-b"),
                        (b"x-actor-id", b"administrator"),
                    ],
                    body=json.dumps({"title": "Alice's item"}).encode(),
                )
                self.assertEqual(created["status"], 201)
                item = json.loads(created["body"])
                with self.assertRaises(RuntimeError):
                    ExecutionContextAccessor.get()

                bob_list = await self._request(
                    app,
                    "GET",
                    "/items",
                    headers=[
                        (b"authorization", b"Bearer bob"),
                        (b"x-tenant-id", b"tenant-a"),
                    ],
                )
                self.assertEqual(json.loads(bob_list["body"]), {"items": []})

                bob_read = await self._request(
                    app,
                    "GET",
                    f"/items/{item['id']}",
                    headers=[(b"authorization", b"Bearer bob")],
                )
                self.assertEqual(bob_read["status"], 404)

                alice_read = await self._request(
                    app,
                    "GET",
                    f"/items/{item['id']}",
                    headers=[(b"authorization", b"Bearer alice")],
                )
                self.assertEqual(alice_read["status"], 200)
                self.assertEqual(json.loads(alice_read["body"])["title"], "Alice's item")

                alice_delete = await self._request(
                    app,
                    "DELETE",
                    f"/items/{item['id']}",
                    headers=[(b"authorization", b"Bearer alice")],
                )
                self.assertEqual(alice_delete["status"], 204)

        asyncio.run(scenario())

    def test_sqlite_transactions_commit_and_rollback(self):
        async def scenario():
            provider = SQLiteProvider()
            await provider.initialize({"path": ":memory:"})
            await provider.execute(
                "CREATE TABLE values_table (value TEXT NOT NULL)"
            )

            with self.assertRaisesRegex(RuntimeError, "rollback"):
                async with provider.transaction() as transaction:
                    await transaction.execute(
                        "INSERT INTO values_table (value) VALUES (?)",
                        ("not committed",),
                    )
                    raise RuntimeError("rollback")
            self.assertEqual(
                await provider.fetch_all("SELECT value FROM values_table"),
                [],
            )

            async with provider.transaction() as transaction:
                await transaction.execute(
                    "INSERT INTO values_table (value) VALUES (?)",
                    ("committed",),
                )
            self.assertEqual(
                await provider.fetch_all("SELECT value FROM values_table"),
                [{"value": "committed"}],
            )
            await provider.close()

        asyncio.run(scenario())

    def test_protected_routes_reject_missing_identity(self):
        async def scenario():
            app = create_app(database_path=":memory:")
            async with app.router.lifespan_context(app):
                response = await self._request(app, "GET", "/items")
                self.assertEqual(response["status"], 401)

        asyncio.run(scenario())

    @staticmethod
    async def _request(app, method, path, headers=(), body=b""):
        received = False
        sent = []

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {
                    "type": "http.request",
                    "body": body,
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": list(headers),
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
        await app(scope, receive, send)
        start = next(message for message in sent if message["type"] == "http.response.start")
        response_body = b"".join(
            message.get("body", b"")
            for message in sent
            if message["type"] == "http.response.body"
        )
        return {
            "status": start["status"],
            "headers": dict(start["headers"]),
            "body": response_body,
        }


if __name__ == "__main__":
    unittest.main()
