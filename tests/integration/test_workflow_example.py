"""The workflow example runs end to end against its deterministic fake service."""

import asyncio

from workflow.app import build_workflow, main, run_scenario

from xyberos import WorkflowExecutor
from xyberos.execution import FakeExternalService, ManualClock, Reply


def test_the_example_reports_a_classification_retry() -> None:
    async def scenario() -> None:
        result = await run_scenario(
            [Reply.rate_limited(), Reply.ok({"category": "refund"})], "T-100"
        )

        assert result == "customer notified: refund queued for T-100"

    asyncio.run(scenario())


def test_the_example_takes_the_fallback_branch() -> None:
    async def scenario() -> None:
        result = await run_scenario([Reply.ok({"category": "question"})], "T-200")

        assert result == "customer notified: escalated T-200 to a human"

    asyncio.run(scenario())


def test_the_example_runs_all_of_its_scenarios() -> None:
    asyncio.run(main())


def test_the_example_workflow_is_inspectable_without_executing() -> None:
    service = FakeExternalService()
    workflow = build_workflow(service)

    rendered = workflow.render()

    assert "workflow 'ticket-triage' version='1'" in rendered
    assert "retry(max_attempts=3" in rendered
    assert "timeout=5s" in rendered
    assert "edge classify -> refund when=<lambda>" in rendered
    assert "edge classify -> escalate" in rendered
    assert service.calls == 0


def test_the_example_workflow_retries_on_a_virtual_clock() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        service = FakeExternalService(
            [Reply.rate_limited(), Reply.ok({"category": "refund"})], clock=clock
        )
        workflow = build_workflow(service)
        task = asyncio.ensure_future(
            workflow.run(
                input={"ticket": "T-400"},
                timeout=30.0,
                executor=WorkflowExecutor(clock=clock),
            )
        )

        result = await clock.drive(task)

        assert result.value == "customer notified: refund queued for T-400"
        assert service.calls == 2
        assert 0.05 in clock.sleeps  # the retry backoff
        assert clock.monotonic() == 0.05  # nothing else consumed virtual time

    asyncio.run(scenario())
