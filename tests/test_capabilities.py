from __future__ import annotations

import asyncio
import unittest

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from xyberos.http.middleware import XyberosContextMiddleware
from xyberos.kernel import (
    Capability,
    ExecutionContext,
    ExecutionContextAccessor,
    PolicyEngine,
    XyberosKernel,
)
from xyberos.kernel.contracts import Capability as CapabilityContract
from xyberos.kernel.contracts import ExecutionContext as ExecutionContextContract
from xyberos.kernel.security import AuthenticatedIdentity


class StubPolicy(PolicyEngine):
    def __init__(self, decision: bool = True, failure: Exception | None = None) -> None:
        self.decision = decision
        self.failure = failure
        self.calls: list[tuple[ExecutionContext, Capability, object]] = []

    async def authorize(
        self,
        context: ExecutionContextContract,
        capability: CapabilityContract,
        resource: object = None,
    ) -> bool:
        self.calls.append((context, capability, resource))
        if self.failure is not None:
            raise self.failure
        return self.decision


class TestCapabilityExecution(unittest.TestCase):
    def test_execution_denies_without_context_or_policy_or_handler(self):
        async def scenario():
            kernel = XyberosKernel()
            calls: list[str] = []

            async def handler() -> str:
                calls.append("handler")
                return "done"

            capability = Capability("records.read")
            kernel.register_capability(capability, handler)
            unbound_capability = Capability("records.unbound")
            kernel.register_capability(unbound_capability)
            await kernel.bootstrap()
            try:
                with self.assertRaisesRegex(PermissionError, "trusted execution context"):
                    await kernel.execute_capability("records.read")

                token = ExecutionContextAccessor.set(
                    ExecutionContext("request", "tenant", "actor")
                )
                try:
                    with self.assertRaisesRegex(PermissionError, "PolicyEngine"):
                        await kernel.execute_capability("records.read")
                    with self.assertRaises(KeyError):
                        await kernel.execute_capability("unknown.capability")
                    with self.assertRaisesRegex(RuntimeError, "No handler"):
                        await kernel.execute_capability("records.unbound")
                finally:
                    ExecutionContextAccessor.reset(token)
                self.assertEqual(calls, [])
            finally:
                await kernel.shutdown()

        asyncio.run(scenario())

    def test_denial_and_policy_failure_never_invoke_handler(self):
        async def scenario():
            for policy in (
                StubPolicy(decision=False),
                StubPolicy(failure=RuntimeError("policy unavailable")),
            ):
                kernel = XyberosKernel()
                calls: list[str] = []

                async def handler() -> None:
                    calls.append("handler")

                capability = Capability("records.write")
                kernel.register_capability(capability, handler)
                kernel.container.register_utility(PolicyEngine, policy)
                await kernel.bootstrap()
                token = ExecutionContextAccessor.set(
                    ExecutionContext("request", "tenant", "actor")
                )
                try:
                    if policy.failure is not None:
                        with self.assertRaisesRegex(RuntimeError, "policy unavailable"):
                            await kernel.execute_capability(
                                "records.write",
                                resource={"record_id": "r1"},
                            )
                    else:
                        with self.assertRaisesRegex(PermissionError, "Policy denied"):
                            await kernel.execute_capability(
                                "records.write",
                                resource={"record_id": "r1"},
                            )
                    self.assertEqual(calls, [])
                    self.assertEqual(policy.calls[0][2], {"record_id": "r1"})
                finally:
                    ExecutionContextAccessor.reset(token)
                    await kernel.shutdown()

        asyncio.run(scenario())

    def test_success_runs_bound_handler_after_policy_and_tracks_work(self):
        async def scenario():
            kernel = XyberosKernel()
            events: list[str] = []
            policy = StubPolicy()

            async def handler(value: str) -> str:
                events.append("handler")
                self.assertEqual(kernel.health.active_work, 1)
                return f"handled:{value}"

            capability = Capability("records.read")
            kernel.register_capability(capability)
            kernel.register_capability_handler("records.read", handler)
            kernel.container.register_utility(PolicyEngine, policy)
            await kernel.bootstrap()
            token = ExecutionContextAccessor.set(
                ExecutionContext("request", "tenant-a", "actor-a")
            )
            try:
                result = await kernel.execute_capability(
                    "records.read",
                    "item-1",
                    resource={"item_id": "item-1"},
                )
                self.assertEqual(result, "handled:item-1")
                self.assertEqual(events, ["handler"])
                self.assertEqual(policy.calls[0][1], capability)
                self.assertEqual(policy.calls[0][2], {"item_id": "item-1"})
                self.assertEqual(policy.calls[0][0].tenant_id, "tenant-a")
                self.assertEqual(kernel.health.active_work, 0)
            finally:
                ExecutionContextAccessor.reset(token)
                await kernel.shutdown()

        asyncio.run(scenario())

    def test_authenticated_capability_requires_actor_and_tenant(self):
        async def scenario():
            kernel = XyberosKernel()
            policy = StubPolicy()
            calls: list[bool] = []
            capability = Capability("records.read")
            kernel.register_capability(capability, lambda: calls.append(True))
            kernel.container.register_utility(PolicyEngine, policy)
            await kernel.bootstrap()
            token = ExecutionContextAccessor.set(
                ExecutionContext("request", "", "actor")
            )
            try:
                with self.assertRaisesRegex(PermissionError, "authenticated actor and tenant"):
                    await kernel.execute_capability("records.read")
                self.assertEqual(policy.calls, [])
                self.assertEqual(calls, [])
            finally:
                ExecutionContextAccessor.reset(token)
                await kernel.shutdown()

        asyncio.run(scenario())

    def test_http_context_and_forged_headers_cannot_change_capability_identity(self):
        async def scenario():
            kernel = XyberosKernel()
            policy = StubPolicy()
            calls: list[str] = []

            async def handler() -> str:
                calls.append(ExecutionContextAccessor.get().tenant_id)
                return "ok"

            kernel.register_capability(Capability("records.read"), handler)
            kernel.container.register_utility(PolicyEngine, policy)
            await kernel.bootstrap()

            async def endpoint(_request: Request) -> JSONResponse:
                del _request
                result = await kernel.execute_capability("records.read")
                return JSONResponse({"result": result})

            async def failing_endpoint(_request: Request) -> JSONResponse:
                del _request
                ExecutionContextAccessor.get()
                raise RuntimeError("endpoint failed")

            async def resolve_identity(
                auth_request: Request,
            ) -> AuthenticatedIdentity | None:
                if auth_request.headers.get("authorization") == "valid":
                    return AuthenticatedIdentity("actor-a", "tenant-a")
                return None

            app = XyberosContextMiddleware(
                Starlette(
                    routes=[
                        Route("/records", endpoint),
                        Route("/fails", failing_endpoint),
                    ]
                ),
                identity_resolver=resolve_identity,
            )
            try:
                response = await _request(
                    app,
                    "/records",
                    [
                        (b"authorization", b"valid"),
                        (b"x-tenant-id", b"tenant-attacker"),
                        (b"x-actor-id", b"actor-attacker"),
                    ],
                )
                self.assertEqual(response["status"], 200)
                self.assertEqual(calls, ["tenant-a"])
                self.assertEqual(policy.calls[0][0].actor_id, "actor-a")
                self.assertEqual(policy.calls[0][0].tenant_id, "tenant-a")
                with self.assertRaisesRegex(RuntimeError, "ExecutionContext missing"):
                    ExecutionContextAccessor.get()

                with self.assertRaisesRegex(RuntimeError, "endpoint failed"):
                    await _request(
                        app,
                        "/fails",
                        [(b"authorization", b"valid")],
                    )
                with self.assertRaisesRegex(RuntimeError, "ExecutionContext missing"):
                    ExecutionContextAccessor.get()

                rejected = await _request(
                    app,
                    "/records",
                    [(b"x-tenant-id", b"tenant-a")],
                )
                self.assertEqual(rejected["status"], 401)
                self.assertEqual(calls, ["tenant-a"])
            finally:
                await kernel.shutdown()

        asyncio.run(scenario())


async def _request(
    app,
    path: str,
    headers: list[tuple[bytes, bytes]],
) -> dict[str, object]:
    sent: list[dict[str, object]] = []
    received = False

    async def receive() -> dict[str, object]:
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    start = next(
        message for message in sent if message["type"] == "http.response.start"
    )
    return {
        "status": start["status"],
        "body": b"".join(
            message.get("body", b"")
            for message in sent
            if message["type"] == "http.response.body"
        ),
    }


if __name__ == "__main__":
    unittest.main()
