"""Recording, arithmetic, and reporting for the resource baselines.

The numbers this produces are for comparison against the previous run of the same suite, not against
an absolute target: a shared CI machine is not a benchmark rig, and a threshold tight enough to be
interesting is a threshold that fails for reasons unrelated to the change under test. So the
measurements are printed, and the assertions that use them are deliberately loose — they catch a
change of kind (a linear walk that became quadratic, a connection opened per call), not a change of
degree.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = ["Measurement", "Report", "time_async", "time_call"]


@dataclass(frozen=True)
class Measurement:
    """One labelled set of samples, in seconds."""

    label: str
    samples: tuple[float, ...]

    @property
    def best_ms(self) -> float:
        return min(self.samples) * 1000

    @property
    def median_ms(self) -> float:
        return statistics.median(self.samples) * 1000

    @property
    def p95_ms(self) -> float:
        """The 95th percentile, by nearest rank, which is stable for small sample sizes."""
        ordered = sorted(self.samples)
        index = max(0, min(len(ordered) - 1, round(0.95 * (len(ordered) - 1))))
        return ordered[index] * 1000

    def line(self) -> str:
        return (
            f"{self.label:<40} best {self.best_ms:8.2f} ms   "
            f"median {self.median_ms:8.2f} ms   p95 {self.p95_ms:8.2f} ms"
        )


class Report:
    """Collects measurements and renders them once, as a table."""

    def __init__(self) -> None:
        self._measurements: list[Measurement] = []

    def add(self, label: str, samples: list[float]) -> Measurement:
        measurement = Measurement(label=label, samples=tuple(samples))
        self._measurements.append(measurement)
        return measurement

    def render(self) -> str:
        lines = ["resource baselines (one sample per operation, lower is better)"]
        lines.extend(f"  {measurement.line()}" for measurement in self._measurements)
        return "\n".join(lines)


def time_call(
    report: Report, label: str, call: Callable[[], object], *, repeat: int
) -> Measurement:
    """Time a synchronous operation ``repeat`` times and record every sample."""
    samples: list[float] = []
    for _ in range(repeat):
        started = time.perf_counter()
        call()
        samples.append(time.perf_counter() - started)
    return report.add(label, samples)


async def time_async(
    report: Report, label: str, call: Callable[[], Awaitable[object]], *, repeat: int
) -> Measurement:
    """Time an asynchronous operation ``repeat`` times and record every sample.

    The event loop is already running, so each sample is one awaited operation rather than one loop
    start-up; that keeps the sample comparable and the number honest about what it includes.
    """
    samples: list[float] = []
    for _ in range(repeat):
        started = time.perf_counter()
        await call()
        samples.append(time.perf_counter() - started)
    return report.add(label, samples)
