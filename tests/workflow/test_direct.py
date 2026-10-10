"""Direct calls are one await with framework deadlines, not a workflow."""

import asyncio

import pytest

from xyberos import (
    DIRECT_WORKFLOW,
    CancellationToken,
    WorkflowCancelledError,
    WorkflowExecutor,
    WorkflowTimeoutError,
    WorkflowValidationError,
    direct,
)
from xyberos.execution import ManualClock, pending_tasks


async def echo(value: object) -> object:
    return f"echo:{value}"


def test_a_direct_call_returns_the_value() -> None:
    async def scenario() -> None:
        assert await direct(echo, 1, timeout=1.0) == "echo:1"
        assert await direct(echo, 2) == "echo:2"
        assert await direct(echo, value=3) == "echo:3"

    asyncio.run(scenario())


def test_a_direct_call_propagates_the_callers_exception_unchanged() -> None:
    async def scenario() -> None:
        error = ValueError("the caller's own failure")

        async def explode() -> object:
            raise error

        with pytest.raises(ValueError) as caught:
            await direct(explode)

        assert caught.value is error

    asyncio.run(scenario())


def test_a_direct_call_enforces_its_timeout() -> None:
    async def scenario() -> None:
        clock = ManualClock()

        async def slow() -> object:
            await clock.sleep(10.0)
            return "late"

        task = asyncio.ensure_future(
            direct(slow, timeout=2.0, executor=WorkflowExecutor(clock=clock))
        )
        await clock.wait_for_sleepers(2)
        clock.advance(2.0)

        with pytest.raises(WorkflowTimeoutError) as caught:
            await task

        assert caught.value.workflow == DIRECT_WORKFLOW
        assert caught.value.step == "slow"
        assert pending_tasks() == []

    asyncio.run(scenario())


def test_a_direct_call_can_be_cancelled() -> None:
    async def scenario() -> None:
        token = CancellationToken()
        token.cancel("nothing to do")

        async def work() -> object:
            return "done"

        with pytest.raises(WorkflowCancelledError, match="before it started"):
            await direct(work, cancellation=token)

    asyncio.run(scenario())


def test_a_direct_call_can_be_named_for_errors() -> None:
    async def scenario() -> None:
        clock = ManualClock()

        async def work() -> object:
            await clock.sleep(5.0)

        task = asyncio.ensure_future(
            direct(
                work,
                name="refresh-cache",
                timeout=1.0,
                executor=WorkflowExecutor(clock=clock),
            )
        )
        await clock.wait_for_sleepers(2)
        clock.advance(1.0)

        with pytest.raises(WorkflowTimeoutError) as caught:
            await task

        assert caught.value.step == "refresh-cache"

    asyncio.run(scenario())


def test_a_direct_call_rejects_a_non_positive_timeout() -> None:
    async def scenario() -> None:
        with pytest.raises(WorkflowValidationError, match="greater than zero"):
            await direct(echo, 1, timeout=0)

    asyncio.run(scenario())


def test_a_direct_call_leaves_no_task_behind() -> None:
    async def scenario() -> None:
        clock = ManualClock()

        async def work() -> object:
            await clock.sleep(1.0)
            return "done"

        task = asyncio.ensure_future(direct(work, executor=WorkflowExecutor(clock=clock)))

        assert await clock.drive(task) == "done"
        assert pending_tasks() == []

    asyncio.run(scenario())
