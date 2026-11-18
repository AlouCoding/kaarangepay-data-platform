"""Traffic intensity over time.

``intensity(ts)`` returns a multiplier of the base rate. It combines independent
factors that a Senegalese mobile money operator would recognise:

* a day/night cycle (quiet nights, lunch and evening peaks);
* paydays (end and start of the month);
* the week (Sunday is calmer);
* public holidays — with a strong peak in the days *before* Tabaski / Korité,
  when families send and spend money.

All values are illustrative assumptions, not measured operator data.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

# Relative activity per hour of the day (index = hour, 0..23). Peak = 1.0.
HOURLY_PROFILE: tuple[float, ...] = (
    0.05, 0.03, 0.02, 0.02, 0.03, 0.08,   # 00h-05h: night
    0.20, 0.45, 0.65, 0.75, 0.80, 0.85,   # 06h-11h: morning ramp-up
    1.00, 0.95, 0.80, 0.75, 0.80, 0.90,   # 12h-17h: lunch peak, afternoon
    1.00, 0.95, 0.80, 0.55, 0.30, 0.12,   # 18h-23h: evening peak, wind-down
)

# Monday=0 .. Sunday=6
WEEKDAY_FACTOR: tuple[float, ...] = (1.0, 0.95, 0.95, 1.0, 1.10, 1.05, 0.80)

PAYDAY_FACTOR = 1.6
HOLIDAY_EVE_DAYS = 3


@dataclass(frozen=True)
class Holiday:
    name: str
    eve_factor: float  # multiplier during the HOLIDAY_EVE_DAYS days before
    day_factor: float  # multiplier on the day itself


def default_holidays(year: int) -> dict[date, Holiday]:
    """Holidays for ``year``. Islamic holidays follow the lunar calendar:
    the 2026 dates below are approximate and should be adjusted each year."""
    fixed: dict[date, Holiday] = {
        date(year, 1, 1): Holiday("New Year", 1.3, 0.8),
        date(year, 4, 4): Holiday("Independence Day", 1.2, 0.8),
        date(year, 12, 25): Holiday("Christmas", 1.4, 0.8),
    }
    lunar_2026: dict[date, Holiday] = {
        date(2026, 3, 20): Holiday("Korité (approx.)", 1.9, 0.9),
        date(2026, 5, 27): Holiday("Tabaski (approx.)", 2.3, 0.9),
        date(2026, 8, 26): Holiday("Maouloud (approx.)", 1.3, 0.9),
    }
    return fixed | (lunar_2026 if year == 2026 else {})


def is_payday_period(day: date) -> bool:
    """Salaries are commonly paid around the end of the month."""
    return day.day >= 25 or day.day <= 3


@dataclass
class TrafficCalendar:
    """Computes the intensity multiplier for any timestamp."""

    holidays: Mapping[date, Holiday] = field(default_factory=dict)

    @classmethod
    def for_years(cls, *years: int) -> TrafficCalendar:
        merged: dict[date, Holiday] = {}
        for year in years:
            merged |= default_holidays(year)
        return cls(holidays=merged)

    def holiday_factor(self, day: date) -> float:
        if day in self.holidays:
            return self.holidays[day].day_factor
        for offset in range(1, HOLIDAY_EVE_DAYS + 1):
            upcoming = self.holidays.get(day + timedelta(days=offset))
            if upcoming is not None:
                return upcoming.eve_factor
        return 1.0

    def intensity(self, ts: datetime) -> float:
        day = ts.date()
        factor = HOURLY_PROFILE[ts.hour] * WEEKDAY_FACTOR[ts.weekday()]
        if is_payday_period(day):
            factor *= PAYDAY_FACTOR
        return factor * self.holiday_factor(day)

    def max_intensity(self) -> float:
        """Upper bound of ``intensity`` — required by Poisson thinning."""
        holiday_max = max((max(h.eve_factor, h.day_factor) for h in self.holidays.values()), default=1.0)
        return max(HOURLY_PROFILE) * max(WEEKDAY_FACTOR) * PAYDAY_FACTOR * max(holiday_max, 1.0)
