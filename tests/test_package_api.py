import unittest

import xyberos
from xyberos import http, kernel, providers, subsystems
from xyberos.kernel import (
    AuthenticatedIdentity,
    Capability,
    ExecutionContext,
    PolicyEngine,
    XyberosKernel,
)
from xyberos.subsystems.database import Database, DatabaseSubsystem, SchemaMigrator


class TestPackageApi(unittest.TestCase):
    def test_root_package_exposes_version_and_core_modules(self):
        self.assertEqual(
            xyberos.__all__,
            ["__version__", "kernel", "http", "providers", "subsystems"],
        )
        self.assertIsInstance(xyberos.__version__, str)
        self.assertTrue(xyberos.__version__)
        self.assertIs(kernel, xyberos.kernel)
        self.assertIs(http, xyberos.http)
        self.assertIs(providers, xyberos.providers)
        self.assertIs(subsystems, xyberos.subsystems)

    def test_documented_public_symbols_import(self):
        self.assertTrue(callable(XyberosKernel))
        self.assertTrue(callable(Capability))
        self.assertTrue(callable(ExecutionContext))
        self.assertTrue(callable(AuthenticatedIdentity))
        self.assertTrue(callable(PolicyEngine))
        self.assertTrue(callable(Database))
        self.assertTrue(callable(DatabaseSubsystem))
        self.assertTrue(callable(SchemaMigrator))

    def test_supported_root_and_submodule_imports(self):
        import xyberos.providers.database as providers_database
        import xyberos.providers.p2p as providers_p2p
        import xyberos.subsystems.database as subsystems_database
        import xyberos.subsystems.p2p as subsystems_p2p

        self.assertIsNotNone(providers_database)
        self.assertIsNotNone(providers_p2p)
        self.assertIsNotNone(subsystems_database)
        self.assertIsNotNone(subsystems_p2p)
        self.assertTrue(hasattr(xyberos.kernel, "XyberosKernel"))
        self.assertTrue(hasattr(xyberos.http, "__doc__"))


if __name__ == "__main__":
    unittest.main()
