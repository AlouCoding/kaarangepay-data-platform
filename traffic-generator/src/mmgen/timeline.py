"""Event times as a non-homogeneous Poisson process (Lewis-Shedler thinning).

Arrivals are drawn at the maximum rate, then each one is kept with probability
``intensity(t) / max_intensity``. The result has exactly the shape of the
calendar: more events at lunch, on paydays, before Tabaski, and so on.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import datetime, timedelta

from mmgen.patterns import TrafficCalendar


def event_times(
    calendar: TrafficCalendar,
    start: datetime,
    end: datetime,
    base_rate_per_hour: float,
    rng: random.Random,
) -> Iterator[datetime]:
    """Yield event timestamps in ``[start, end)``, in increasing order.

    ``base_rate_per_hour`` is the rate when ``intensity == 1``.
    """
    if base_rate_per_hour <= 0:
        raise ValueError("base_rate_per_hour must be positive")
    if end <= start:
        return

    max_intensity = calendar.max_intensity()
    max_rate_per_second = base_rate_per_hour * max_intensity / 3600.0
    t = start
    while True:
        t += timedelta(seconds=rng.expovariate(max_rate_per_second))
        if t >= end:
            return
        if rng.random() * max_intensity < calendar.intensity(t):
            yield t
