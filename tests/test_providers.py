import asyncio
import importlib.util
import os
import tempfile
import unittest
from uuid import uuid4

from xyberos.kernel import DependencyContainer
from xyberos.providers.blob import LocalFilesystemBlobProvider
from xyberos.providers.database import PostgreSQLProvider, SQLiteProvider
from xyberos.providers.database.postgresql import adapt_placeholders
from xyberos.subsystems.blob import BlobProvider, BlobSubsystem
from xyberos.subsystems.database import Database, DatabaseProvider, DatabaseSubsystem


class AlternateSQLiteProvider(SQLiteProvider):
    @property
    def provider_name(self):
        return "sqlite-alternate"


class TestProviderContracts(unittest.TestCase):
    def test_sqlite_contract_operations_and_transaction(self):
        async def scenario():
            provider = SQLiteProvider()
            self.assertIsInstance(provider, DatabaseProvider)
            await provider.initialize({"path": ":memory:"})
            await provider.execute(
                "CREATE TABLE contract_rows (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
            )

            async with provider.transaction() as transaction:
                await transaction.execute(
                    "INSERT INTO contract_rows (value) VALUES (?)",
                    ("first",),
                )
                row = await transaction.fetch_one(
                    "SELECT value FROM contract_rows WHERE value = ?",
                    ("first",),
                )
                self.assertEqual(row, {"value": "first"})

            self.assertEqual(
                await provider.fetch_all("SELECT value FROM contract_rows"),
                [{"value": "first"}],
            )
            await provider.close()
            await provider.close()

        asyncio.run(scenario())

    def test_database_subsystem_selects_provider_by_configuration(self):
        async def scenario():
            container = DependencyContainer()
            default_provider = SQLiteProvider()
            selected_provider = AlternateSQLiteProvider()
            subsystem = DatabaseSubsystem(
                {
                    "sqlite": default_provider,
                    "sqlite-alternate": selected_provider,
                }
            )

            await subsystem.initialize(
                {
                    "provider": "sqlite-alternate",
                    "config": {"path": ":memory:"},
                },
                container,
            )
            self.assertIs(container.resolve(Database), selected_provider)
            await subsystem.shutdown()
            with self.assertRaises(KeyError):
                container.resolve(Database)

        asyncio.run(scenario())

    def test_database_subsystem_rejects_unregistered_provider(self):
        async def scenario():
            subsystem = DatabaseSubsystem(SQLiteProvider())
            with self.assertRaisesRegex(ValueError, "not registered"):
                await subsystem.initialize(
                    {"provider": "missing", "config": {}},
                    DependencyContainer(),
                )

        asyncio.run(scenario())

    def test_postgresql_qmark_binding_preserves_non_parameter_question_marks(self):
        statement = (
            "SELECT '?' AS literal, value FROM records WHERE id = ? "
            "-- ignore ?\nAND note = 'it''s ?' /* ? */"
        )
        self.assertEqual(
            adapt_placeholders(statement, (7,)),
            "SELECT '?' AS literal, value FROM records WHERE id = %s "
            "-- ignore ?\nAND note = 'it''s ?' /* ? */",
        )

    def test_postgresql_named_binding_preserves_casts_and_dollar_quotes(self):
        statement = (
            "SELECT :value::text, $$:ignored ?$$, $tag$:ignored$tag$ "
            "/* :comment */ -- :line\n"
        )
        self.assertEqual(
            adapt_placeholders(statement, {"value": "ok"}),
            "SELECT %(value)s::text, $$:ignored ?$$, $tag$:ignored$tag$ "
            "/* :comment */ -- :line\n",
        )

    def test_postgresql_binding_handles_nested_comments_and_escape_strings(self):
        statement = "SELECT E'it\\'s ?', /* outer ? /* inner ? */ still ? */ ?"
        self.assertEqual(
            adapt_placeholders(statement, (3,)),
            "SELECT E'it\\'s ?', /* outer ? /* inner ? */ still ? */ %s",
        )

    def test_postgresql_provider_requires_optional_driver(self):
        if importlib.util.find_spec("psycopg") is not None:
            self.skipTest("psycopg is installed; live PostgreSQL requires a test DSN.")

        async def scenario():
            provider = PostgreSQLProvider()
            with self.assertRaisesRegex(RuntimeError, "optional 'postgres' extra"):
                await provider.initialize({"conninfo": "postgresql://invalid"})

        asyncio.run(scenario())

    def test_local_blob_contract_atomic_round_trip_and_delete(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                provider = LocalFilesystemBlobProvider()
                self.assertIsInstance(provider, BlobProvider)
                await provider.initialize(
                    {"root": directory, "max_size_bytes": 16}
                )
                info = await provider.put(b"hello", "text/plain")
                self.assertEqual(info.size_bytes, 5)
                blob = await provider.get(info.blob_id)
                self.assertEqual(blob.data, b"hello")
                self.assertEqual(blob.info.content_type, "text/plain")
                self.assertTrue(await provider.delete(info.blob_id))
                self.assertFalse(await provider.delete(info.blob_id))
                await provider.close()

        asyncio.run(scenario())

    def test_local_blob_rejects_path_traversal_and_oversized_content(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                provider = LocalFilesystemBlobProvider()
                await provider.initialize(
                    {"root": directory, "max_size_bytes": 2}
                )
                with self.assertRaisesRegex(ValueError, "identifier is invalid"):
                    await provider.get("../outside")
                with self.assertRaisesRegex(ValueError, "exceeds configured limit"):
                    await provider.put(b"too large")
                await provider.close()

        asyncio.run(scenario())

    def test_blob_subsystem_selects_provider_and_closes_it(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                provider = LocalFilesystemBlobProvider()
                subsystem = BlobSubsystem(provider)
                container = DependencyContainer()
                await subsystem.initialize({"config": {"root": directory}}, container)
                self.assertIs(container.resolve(BlobProvider), provider)
                await subsystem.shutdown()
                with self.assertRaises(KeyError):
                    container.resolve(BlobProvider)

        asyncio.run(scenario())


class TestPostgreSQLIntegration(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("XYBEROS_TEST_POSTGRES_DSN"),
        "Set XYBEROS_TEST_POSTGRES_DSN to run PostgreSQL integration tests.",
    )
    def test_postgresql_database_contract(self):
        async def scenario():
            provider = PostgreSQLProvider()
            await provider.initialize(
                {"conninfo": os.environ["XYBEROS_TEST_POSTGRES_DSN"]}
            )
            table = f"xyberos_contract_{uuid4().hex}"
            await provider.execute(
                f"CREATE TABLE {table} (value TEXT NOT NULL)"
            )
            try:
                async with provider.transaction() as transaction:
                    await transaction.execute(
                        f"INSERT INTO {table} (value) VALUES (?)",
                        ("portable",),
                    )
                row = await provider.fetch_one(
                    f"SELECT value FROM {table} WHERE value = ?",
                    ("portable",),
                )
                self.assertEqual(row, {"value": "portable"})
                await provider.execute(f"DROP TABLE {table}")
            finally:
                await provider.close()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
