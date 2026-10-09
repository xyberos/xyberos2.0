import asyncio
import json
import unittest

from apps.example_crud_app.app import create_app
from xyberos.kernel import ExecutionContextAccessor
from xyberos.kernel.security import AuthenticatedIdentity
from xyberos.providers.database import SQLiteProvider


class TestPhaseTwoApplication(unittest.TestCase):
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
