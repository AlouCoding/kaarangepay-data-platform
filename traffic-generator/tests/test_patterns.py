import random
from datetime import UTC, datetime, timedelta

import pytest

from mmgen.patterns import TrafficCalendar, is_payday_period
from mmgen.timeline import event_times

CAL = TrafficCalendar.for_years(2026)


def at(day: str, hour: int) -> datetime:
    return datetime.fromisoformat(day).replace(hour=hour, tzinfo=UTC)


def test_lunch_is_busier_than_night() -> None:
    assert CAL.intensity(at("2026-11-11", 12)) > 10 * CAL.intensity(at("2026-11-11", 3))


def test_payday_is_busier_than_mid_month() -> None:
    # Same weekday (Wednesday), same hour.
    assert CAL.intensity(at("2026-11-25", 12)) > CAL.intensity(at("2026-11-11", 12))
    assert is_payday_period(datetime(2026, 12, 2).date())
    assert not is_payday_period(datetime(2026, 12, 15).date())


def test_days_before_tabaski_peak() -> None:
    eve = CAL.intensity(at("2026-05-25", 12))     # 2 days before Tabaski (approx.)
    normal = CAL.intensity(at("2026-05-11", 12))  # a normal Monday two weeks before
    assert eve > 2 * normal


def test_intensity_never_exceeds_declared_maximum() -> None:
    start = at("2026-01-01", 0)
    peak = max(CAL.intensity(start + timedelta(hours=h)) for h in range(24 * 365))
    assert peak <= CAL.max_intensity()


def test_event_times_follow_the_calendar() -> None:
    rng = random.Random(7)
    start = at("2026-11-09", 0)  # Monday, mid-month
    times = list(event_times(CAL, start, start + timedelta(days=7), base_rate_per_hour=200, rng=rng))

    assert times == sorted(times)
    assert all(start <= t < start + timedelta(days=7) for t in times)
    night = sum(1 for t in times if 1 <= t.hour < 5)
    lunch = sum(1 for t in times if 12 <= t.hour < 14)
    assert lunch > 8 * night


def test_event_volume_matches_expected_rate() -> None:
    rng = random.Random(1)
    start = at("2026-11-10", 12)  # Tuesday noon, intensity ~0.95
    hours = 50
    times = list(event_times(CAL, start, start + timedelta(hours=hours), 100, rng))
    expected = sum(100 * CAL.intensity(start + timedelta(hours=h, minutes=30)) for h in range(hours))
    assert times
    assert abs(len(times) - expected) / expected < 0.15


def test_rejects_non_positive_rate() -> None:
    with pytest.raises(ValueError):
        list(event_times(CAL, at("2026-11-10", 0), at("2026-11-11", 0), 0, random.Random()))
