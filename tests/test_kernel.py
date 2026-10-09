import asyncio
import unittest

from xyberos.kernel import (
    Capability,
    CapabilityRegistry,
    EventBus,
    ExecutionContext,
    ExecutionContextAccessor,
    InProcessEventBus,
    LifecycleState,
    DependencyContainer,
    Provider,
    Subsystem,
    SubsystemShutdownError,
    XyberosKernel,
)
from xyberos.kernel.config import ConfigurationError, KernelConfig
from xyberos.kernel.registry import ProviderRegistry


class RecordingSubsystem(Subsystem):
    def __init__(self, name, calls, fail_initialize=False, fail_shutdown=False):
        self.name = name
        self.calls = calls
        self.fail_initialize = fail_initialize
        self.fail_shutdown = fail_shutdown

    async def initialize(self, config, container):
        self.asserted_config = config
        self.asserted_container = isinstance(container, DependencyContainer)
        self.calls.append(f"start:{self.name}")
        if self.fail_initialize:
            raise RuntimeError(f"start failed: {self.name}")

    async def shutdown(self):
        self.calls.append(f"stop:{self.name}")
        if self.fail_shutdown:
            raise RuntimeError(f"stop failed: {self.name}")


class RecordingProvider(Provider):
    @property
    def provider_name(self):
        return "recording"


class TestKernel(unittest.TestCase):
    def test_bootstrap_failure_rolls_back_started_subsystems_in_reverse(self):
        async def scenario():
            calls = []
            kernel = XyberosKernel()
            kernel.register_subsystem("first", RecordingSubsystem("first", calls))
            kernel.register_subsystem(
                "second",
                RecordingSubsystem("second", calls, fail_initialize=True),
            )

            with self.assertRaisesRegex(RuntimeError, "start failed: second"):
                await kernel.bootstrap(
                    {
                        "xyberos": {
                            "subsystems": {
                                "first": {"enabled": True},
                                "second": {"enabled": True},
                            }
                        }
                    }
                )

            self.assertEqual(calls, ["start:first", "start:second", "stop:first"])
            self.assertEqual(kernel.state, LifecycleState.FAILED)
            self.assertFalse(kernel.is_initialized)

        asyncio.run(scenario())

    def test_shutdown_only_stops_initialized_subsystems_and_is_idempotent(self):
        async def scenario():
            calls = []
            kernel = XyberosKernel()
            kernel.register_subsystem("first", RecordingSubsystem("first", calls))
            kernel.register_subsystem("disabled", RecordingSubsystem("disabled", calls))
            await kernel.bootstrap(
                {
                    "xyberos": {
                        "subsystems": {
                            "first": {"enabled": True},
                            "disabled": {"enabled": False},
                        }
                    }
                }
            )
            await kernel.shutdown()
            await kernel.shutdown()

            self.assertEqual(calls, ["start:first", "stop:first"])
            self.assertEqual(kernel.state, LifecycleState.STOPPED)

        asyncio.run(scenario())

    def test_shutdown_attempts_all_subsystems_then_surfaces_failures(self):
        async def scenario():
            calls = []
            kernel = XyberosKernel()
            kernel.register_subsystem(
                "first",
                RecordingSubsystem("first", calls, fail_shutdown=True),
            )
            kernel.register_subsystem("second", RecordingSubsystem("second", calls))
            await kernel.bootstrap(
                {
                    "subsystems": {
                        "first": {"enabled": True},
                        "second": {"enabled": True},
                    }
                }
            )

            with self.assertRaises(SubsystemShutdownError) as caught:
                await kernel.shutdown()

            self.assertEqual(calls, ["start:first", "start:second", "stop:second", "stop:first"])
            self.assertEqual([name for name, _ in caught.exception.failures], ["first"])

        asyncio.run(scenario())

    def test_empty_config_override_is_not_ignored(self):
        async def scenario():
            calls = []
            kernel = XyberosKernel(
                {
                    "subsystems": {
                        "first": {"enabled": True},
                    }
                }
            )
            kernel.register_subsystem("first", RecordingSubsystem("first", calls))
            await kernel.bootstrap({})
            self.assertEqual(calls, [])

        asyncio.run(scenario())

    def test_invalid_subsystem_config_fails_before_startup(self):
        with self.assertRaises(ConfigurationError):
            KernelConfig.from_dict({"subsystems": {"database": {"enabled": "yes"}}})

    def test_execution_context_resets_to_previous_scope(self):
        context = ExecutionContext("request-1", "tenant-1", "actor-1")
        token = ExecutionContextAccessor.set(context)
        try:
            self.assertIs(ExecutionContextAccessor.get(), context)
        finally:
            ExecutionContextAccessor.reset(token)
        with self.assertRaises(RuntimeError):
            ExecutionContextAccessor.get()

    def test_execution_context_is_isolated_between_async_tasks(self):
        async def scenario():
            async def read_tenant(tenant_id):
                context = ExecutionContext(f"request-{tenant_id}", tenant_id, "actor")
                token = ExecutionContextAccessor.set(context)
                try:
                    await asyncio.sleep(0)
                    return ExecutionContextAccessor.get().tenant_id
                finally:
                    ExecutionContextAccessor.reset(token)

            tenants = await asyncio.gather(
                read_tenant("tenant-a"),
                read_tenant("tenant-b"),
            )
            self.assertEqual(tenants, ["tenant-a", "tenant-b"])

        asyncio.run(scenario())

    def test_provider_registry_rejects_duplicate_names(self):
        registry = ProviderRegistry()
        provider = RecordingProvider()
        registry.register("database", provider)
        self.assertIs(registry.get("database", "recording"), provider)
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register("database", provider)

    def test_event_bus_delivers_matching_events(self):
        async def scenario():
            bus: EventBus = InProcessEventBus()
            received = []

            class Created:
                pass

            class Other:
                pass

            async def receive(event):
                received.append(type(event).__name__)

            bus.subscribe(Created, receive)
            await bus.publish(Created())
            await bus.publish(Other())
            self.assertEqual(received, ["Created"])

        asyncio.run(scenario())

    def test_capability_registry_rejects_duplicate_names(self):
        registry = CapabilityRegistry()
        capability = Capability("account.read")
        registry.register(capability)
        self.assertIs(registry.get("account.read"), capability)
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(capability)


if __name__ == "__main__":
    unittest.main()
