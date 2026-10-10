"""Context propagation and logging helpers."""

import asyncio
import logging
import threading

from xyberos import (
    ContextLogFilter,
    bind_context,
    bind_correlation_id,
    bind_deadline,
    capture_context_runner,
    create_task_in_context,
    get_context,
    get_correlation_id,
    get_deadline,
)


async def read_correlation_id() -> str | None:
    return get_correlation_id()


def test_bind_context_is_scoped_and_restored() -> None:
    assert get_context() == {}

    with bind_context(request_id="abc"):
        assert get_context() == {"request_id": "abc"}
        with bind_context(user="sam"):
            assert get_context() == {"request_id": "abc", "user": "sam"}
        assert get_context() == {"request_id": "abc"}

    assert get_context() == {}


def test_get_context_returns_an_independent_copy() -> None:
    with bind_context(request_id="abc"):
        snapshot = get_context()
        snapshot["request_id"] = "mutated"

        assert get_context() == {"request_id": "abc"}


def test_correlation_id_and_deadline_round_trip() -> None:
    assert get_correlation_id() is None
    assert get_deadline() is None

    with bind_correlation_id("corr-1"), bind_deadline(42.5):
        assert get_correlation_id() == "corr-1"
        assert get_deadline() == 42.5

    assert get_correlation_id() is None
    assert get_deadline() is None


def test_create_task_in_context_propagates_the_context() -> None:
    async def scenario() -> None:
        with bind_correlation_id("corr-task"):
            task = create_task_in_context(read_correlation_id())
            assert await task == "corr-task"

    asyncio.run(scenario())


def test_capture_context_runner_crosses_a_thread_boundary() -> None:
    captured: list[str | None] = []

    def worker() -> None:
        captured.append(get_correlation_id())

    with bind_correlation_id("corr-thread"):
        runner = capture_context_runner(worker)

    thread = threading.Thread(target=runner)
    thread.start()
    thread.join()

    assert captured == ["corr-thread"]


def test_plain_threads_do_not_inherit_context() -> None:
    captured: list[str | None] = []

    def worker() -> None:
        captured.append(get_correlation_id())

    with bind_correlation_id("corr-main"):
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

    assert captured == [None]


def test_log_filter_attaches_the_current_context() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", (), None)

    ContextLogFilter().filter(record)
    assert record.__dict__["xyberos_context"] == {}

    with bind_context(request_id="abc"):
        ContextLogFilter().filter(record)
        assert record.__dict__["xyberos_context"] == {"request_id": "abc"}

    ContextLogFilter().filter(record)
    assert record.__dict__["xyberos_context"] == {}
