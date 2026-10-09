import asyncio
import unittest
from concurrent.futures import ProcessPoolExecutor

from xyberos.subsystems.flows import (
    ExecutionPolicy,
    FlowDefinition,
    FlowEngine,
    FlowEngineContract,
    FlowExecutionError,
    FlowObserverError,
    FlowStep,
    FlowTimeoutError,
    RetryPolicy,
    FlowSubsystem,
)
from xyberos.kernel import DependencyContainer


def add_one(state):
    return state.input + 1


class TestFlowEngine(unittest.TestCase):
    def test_steps_execute_sequentially_and_keep_named_outputs(self):
        async def scenario():
            async def double(state):
                return state.outputs["increment"] * 2

            result = await FlowEngine().run(
                FlowDefinition(
                    "math",
                    (
                        FlowStep("increment", add_one, ExecutionPolicy.SYNC),
                        FlowStep("double", double),
                    ),
                ),
                4,
            )

            self.assertEqual(result.state.input, 4)
            self.assertEqual(result.state.outputs, {"increment": 5, "double": 10})
            self.assertEqual(
                [entry.status for entry in result.trace],
                ["succeeded", "succeeded"],
            )

        asyncio.run(scenario())

    def test_condition_skips_step_without_running_handler(self):
        async def scenario():
            async def should_not_run(_state):
                raise AssertionError("Skipped flow step was executed.")

            result = await FlowEngine().run(
                FlowDefinition(
                    "conditional",
                    (
                        FlowStep(
                            "skipped",
                            should_not_run,
                            condition=lambda state: state.input > 0,
                        ),
                    ),
                ),
                -1,
            )
            self.assertEqual(result.trace[0].status, "skipped")
            self.assertEqual(result.trace[0].attempts, 0)

        asyncio.run(scenario())

    def test_sync_and_thread_execution_policies(self):
        async def scenario():
            result = await FlowEngine().run(
                FlowDefinition(
                    "offload",
                    (
                        FlowStep("inline", add_one, ExecutionPolicy.SYNC),
                        FlowStep("thread", add_one, ExecutionPolicy.THREAD),
                    ),
                ),
                10,
            )
            self.assertEqual(result.state.outputs, {"inline": 11, "thread": 11})

        asyncio.run(scenario())

    def test_dependency_injection_is_available_in_flow_state(self):
        async def scenario():
            async def use_dependency(state):
                return state.dependencies["prefix"] + state.input

            result = await FlowEngine(
                dependencies={"prefix": "hello-"},
            ).run(
                FlowDefinition("di", (FlowStep("compose", use_dependency),)),
                "xyberos",
            )
            self.assertEqual(result.state.outputs["compose"], "hello-xyberos")

        asyncio.run(scenario())

    def test_engine_implements_public_flow_contract(self):
        engine: FlowEngineContract = FlowEngine()
        self.assertTrue(callable(engine.run))

    def test_flow_subsystem_registers_and_unregisters_engine(self):
        async def scenario():
            container = DependencyContainer()
            subsystem = FlowSubsystem()
            await subsystem.initialize(
                {"execution": {"max_concurrent_runs": 3}},
                container,
            )
            engine = container.resolve(FlowEngineContract)
            self.assertIsInstance(engine, FlowEngine)
            self.assertEqual(engine._run_limit._value, 3)
            await subsystem.shutdown()
            with self.assertRaises(KeyError):
                container.resolve(FlowEngineContract)

        asyncio.run(scenario())

    def test_process_policy_requires_explicit_executor(self):
        async def scenario():
            with self.assertRaises(FlowExecutionError) as caught:
                await FlowEngine().run(
                    FlowDefinition(
                        "process",
                        (FlowStep("worker", add_one, ExecutionPolicy.PROCESS),),
                    ),
                    1,
                )
            self.assertEqual(caught.exception.step_name, "worker")

        asyncio.run(scenario())

    def test_process_policy_uses_injected_executor(self):
        async def scenario():
            with ProcessPoolExecutor(max_workers=1) as executor:
                result = await FlowEngine(executor).run(
                    FlowDefinition(
                        "process",
                        (FlowStep("worker", add_one, ExecutionPolicy.PROCESS),),
                    ),
                    8,
                )
            self.assertEqual(result.state.outputs["worker"], 9)

        asyncio.run(scenario())

    def test_retries_only_explicitly_retryable_idempotent_step(self):
        async def scenario():
            calls = 0

            async def flaky(_state):
                nonlocal calls
                calls += 1
                if calls < 3:
                    raise ValueError("temporary")
                return "done"

            result = await FlowEngine().run(
                FlowDefinition(
                    "retry",
                    (
                        FlowStep(
                            "flaky",
                            flaky,
                            retry=RetryPolicy(
                                max_attempts=3,
                                retry_on=(ValueError,),
                            ),
                            idempotent=True,
                        ),
                    ),
                ),
                None,
            )
            self.assertEqual(calls, 3)
            self.assertEqual(result.trace[0].attempts, 3)

        asyncio.run(scenario())

    def test_non_idempotent_step_cannot_configure_retries(self):
        with self.assertRaisesRegex(ValueError, "marked idempotent"):
            FlowStep(
                "side-effect",
                add_one,
                policy=ExecutionPolicy.SYNC,
                retry=RetryPolicy(max_attempts=2, retry_on=(ValueError,)),
            )

    def test_failure_contains_cause_and_partial_trace(self):
        async def scenario():
            async def fail(_state):
                raise LookupError("missing")

            with self.assertRaises(FlowExecutionError) as caught:
                await FlowEngine().run(
                    FlowDefinition(
                        "failure",
                        (
                            FlowStep("first", add_one, ExecutionPolicy.SYNC),
                            FlowStep("second", fail),
                        ),
                    ),
                    2,
                )

            error = caught.exception
            self.assertIsInstance(error.__cause__, LookupError)
            self.assertEqual(error.step_name, "second")
            self.assertEqual(
                [(entry.step_name, entry.status) for entry in error.trace],
                [("first", "succeeded"), ("second", "failed")],
            )

        asyncio.run(scenario())

    def test_step_timeout_has_structured_trace(self):
        async def scenario():
            async def slow(_state):
                await asyncio.sleep(0.1)

            with self.assertRaises(FlowTimeoutError) as caught:
                await FlowEngine().run(
                    FlowDefinition(
                        "step-timeout",
                        (FlowStep("slow", slow, timeout_seconds=0.001),),
                    ),
                    None,
                )
            self.assertEqual(caught.exception.step_name, "slow")
            self.assertEqual(caught.exception.trace[0].status, "timed_out")

        asyncio.run(scenario())

    def test_flow_timeout_is_total_deadline(self):
        async def scenario():
            async def delay(state):
                await asyncio.sleep(0.02)
                return state.input

            with self.assertRaises(FlowTimeoutError) as caught:
                await FlowEngine().run(
                    FlowDefinition(
                        "overall-timeout",
                        (
                            FlowStep("first", delay),
                            FlowStep("second", delay),
                        ),
                        timeout_seconds=0.03,
                    ),
                    "value",
                )
            self.assertIsNone(caught.exception.step_name)
            self.assertEqual(caught.exception.trace[-1].status, "timed_out")

        asyncio.run(scenario())

    def test_task_cancellation_propagates(self):
        async def scenario():
            started = asyncio.Event()
            observed = []

            async def wait_forever(_state):
                started.set()
                await asyncio.Event().wait()

            task = asyncio.create_task(
                FlowEngine(
                    trace_observer=lambda record: observed.append(
                        (record.status, record.attempts)
                    )
                ).run(
                    FlowDefinition(
                        "cancel",
                        (FlowStep("waiting", wait_forever),),
                    ),
                    None,
                )
            )
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(observed, [("cancelled", 1)])

        asyncio.run(scenario())

    def test_max_concurrent_runs_is_enforced(self):
        async def scenario():
            active = 0
            peak = 0

            async def track(_state):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.01)
                active -= 1

            engine = FlowEngine(max_concurrent_runs=2)
            flow = FlowDefinition("bounded", (FlowStep("work", track),))
            await asyncio.gather(*(engine.run(flow, index) for index in range(6)))
            self.assertEqual(peak, 2)

        asyncio.run(scenario())

    def test_flow_timeout_includes_concurrency_queue_wait(self):
        async def scenario():
            entered = asyncio.Event()
            release = asyncio.Event()

            async def hold(_state):
                entered.set()
                await release.wait()

            engine = FlowEngine(max_concurrent_runs=1)
            flow = FlowDefinition("queued", (FlowStep("hold", hold),))
            first = asyncio.create_task(engine.run(flow, None))
            await entered.wait()
            with self.assertRaises(FlowTimeoutError):
                await engine.run(
                    FlowDefinition(
                        "waiter",
                        (FlowStep("never", hold),),
                        timeout_seconds=0.01,
                    ),
                    None,
                )
            release.set()
            await first

        asyncio.run(scenario())

    def test_trace_observer_receives_step_outcomes(self):
        async def scenario():
            observed = []

            async def observe(record):
                observed.append((record.step_name, record.status))

            result = await FlowEngine(trace_observer=observe).run(
                FlowDefinition(
                    "observe",
                    (
                        FlowStep("ran", add_one, ExecutionPolicy.SYNC),
                        FlowStep(
                            "skipped",
                            add_one,
                            ExecutionPolicy.SYNC,
                            condition=lambda state: False,
                        ),
                    ),
                ),
                1,
            )
            self.assertEqual(
                observed,
                [("ran", "succeeded"), ("skipped", "skipped")],
            )
            self.assertEqual(len(result.trace), len(observed))

        asyncio.run(scenario())

    def test_observer_failures_are_not_silenced(self):
        async def scenario():
            def broken_observer(_record):
                raise OSError("trace backend unavailable")

            with self.assertRaises(FlowObserverError) as caught:
                await FlowEngine(trace_observer=broken_observer).run(
                    FlowDefinition("observe-error", (FlowStep("step", add_one, ExecutionPolicy.SYNC),)),
                    1,
                )
            self.assertIsInstance(caught.exception.__cause__, OSError)

        asyncio.run(scenario())

    def test_invalid_flow_and_retry_configuration_rejected(self):
        with self.assertRaisesRegex(ValueError, "retry_on"):
            RetryPolicy(max_attempts=2)
        with self.assertRaisesRegex(ValueError, "positive finite"):
            FlowDefinition("nan", (), timeout_seconds=float("nan"))
        with self.assertRaisesRegex(ValueError, "positive integer"):
            FlowEngine(max_concurrent_runs=True)
        with self.assertRaisesRegex(ValueError, "duplicate step"):
            FlowDefinition(
                "duplicate",
                (
                    FlowStep("same", add_one, ExecutionPolicy.SYNC),
                    FlowStep("same", add_one, ExecutionPolicy.SYNC),
                ),
            )


if __name__ == "__main__":
    unittest.main()
