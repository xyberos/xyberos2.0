"""The shipped test doubles are deterministic and cover the documented fault modes."""

import asyncio

import pytest

from xyberos import TransientError
from xyberos.execution import (
    FakeExternalService,
    MalformedResponseError,
    ManualClock,
    RateLimitError,
    Reply,
    TransientServiceError,
    pending_tasks,
)


def test_manual_clock_only_moves_when_the_test_moves_it() -> None:
    clock = ManualClock(start=5.0)

    assert clock.monotonic() == 5.0
    clock.advance(2.5)
    assert clock.monotonic() == 7.5
    assert clock.advance_to_next() is None
    assert clock.pending == ()


def test_manual_clock_advances_to_the_next_wake_up() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        task = asyncio.ensure_future(clock.sleep(3.0))
        await clock.wait_for_sleepers(1)

        assert clock.pending == (3.0,)
        assert clock.sleeps == (3.0,)
        assert clock.advance_to_next() == 3.0
        assert clock.monotonic() == 3.0

        await task

        assert clock.pending == ()

    asyncio.run(scenario())


def test_manual_clock_reports_when_a_sleeper_never_appears() -> None:
    async def scenario() -> None:
        clock = ManualClock()

        with pytest.raises(AssertionError, match="never reached 1 pending sleeper"):
            await clock.wait_for_sleepers(1, ticks=3)

    asyncio.run(scenario())


def test_drive_propagates_the_task_failure() -> None:
    async def scenario() -> None:
        clock = ManualClock()

        async def explode() -> object:
            raise ValueError("boom")

        task = asyncio.ensure_future(explode())

        with pytest.raises(ValueError, match="boom"):
            await clock.drive(task)

    asyncio.run(scenario())


def test_pending_tasks_ignores_the_calling_task() -> None:
    async def scenario() -> None:
        assert pending_tasks() == []

        async def background() -> None:
            await asyncio.sleep(0)

        task = asyncio.ensure_future(background())
        assert pending_tasks() == [task]
        await task

    asyncio.run(scenario())


def test_the_fake_service_plays_its_script_in_order_and_repeats_the_last_reply() -> None:
    async def scenario() -> None:
        service = FakeExternalService([Reply.ok("first"), Reply.ok("second")])

        assert await service.call() == "first"
        assert await service.call() == "second"
        assert await service.call() == "second"
        assert service.calls == 3

    asyncio.run(scenario())


def test_the_fake_service_defaults_to_a_single_successful_reply() -> None:
    async def scenario() -> None:
        service = FakeExternalService()

        assert await service.call() is None
        assert service.calls == 1

    asyncio.run(scenario())


def test_the_fake_service_records_the_last_request() -> None:
    async def scenario() -> None:
        service = FakeExternalService()

        await service.call("positional", query="ticket")

        assert service.last_call == (("positional",), {"query": "ticket"})
        service.reset()
        assert service.last_call is None
        assert service.calls == 0

    asyncio.run(scenario())


def test_the_fake_service_covers_the_documented_fault_modes() -> None:
    async def scenario() -> None:
        rate_limited = FakeExternalService([Reply.rate_limited()])
        transient = FakeExternalService([Reply.transient()])
        malformed = FakeExternalService([Reply.malformed()])
        custom = FakeExternalService([Reply.failing(MalformedResponseError("bad shape"))])

        with pytest.raises(RateLimitError):
            await rate_limited.call()
        with pytest.raises(TransientServiceError):
            await transient.call()
        assert dict(await malformed.call()) == {
            "error": "unexpected response shape",
            "missing": ("data",),
        }
        with pytest.raises(MalformedResponseError):
            await custom.call()

    asyncio.run(scenario())


def test_transient_failures_are_retryable_by_default_and_malformed_ones_are_not() -> None:
    assert isinstance(RateLimitError(), TransientError)
    assert isinstance(TransientServiceError(), TransientError)
    assert not isinstance(MalformedResponseError(), TransientError)


def test_the_fake_service_simulates_latency_on_the_injected_clock() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        service = FakeExternalService([Reply.slow(2.5)], clock=clock)
        task = asyncio.ensure_future(service.call())

        await clock.wait_for_sleepers(1)
        clock.advance(2.5)

        assert await task is None
        assert clock.monotonic() == 2.5
        assert clock.sleeps == (2.5,)

    asyncio.run(scenario())


def test_a_cancellation_aware_call_observes_cancellation() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        service = FakeExternalService([Reply.slow(30.0)], clock=clock)
        task = asyncio.ensure_future(service.call())

        await clock.wait_for_sleepers(1)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert service.observed_cancellations == 1
        assert pending_tasks() == []

    asyncio.run(scenario())
