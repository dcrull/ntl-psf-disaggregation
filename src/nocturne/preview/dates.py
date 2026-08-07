from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class DateWindow:
    start: date
    end: date

    @classmethod
    def parse(cls, start: str | date, end: str | date) -> DateWindow:
        start_date = _as_date(start)
        end_date = _as_date(end)
        if end_date < start_date:
            raise ValueError("end date must be on or after start date")
        return cls(start=start_date, end=end_date)

    def iso(self) -> tuple[str, str]:
        return (self.start.isoformat(), self.end.isoformat())


def monthly_windows(start: str | date, end: str | date) -> list[DateWindow]:
    """Return calendar-month windows clipped to the selected date range."""

    window = DateWindow.parse(start, end)
    current = date(window.start.year, window.start.month, 1)
    windows: list[DateWindow] = []
    while current <= window.end:
        month_end = _next_month(current) - timedelta(days=1)
        clipped_start = max(window.start, current)
        clipped_end = min(window.end, month_end)
        if clipped_start <= clipped_end:
            windows.append(DateWindow(clipped_start, clipped_end))
        current = _next_month(current)
    return windows


def evenly_sample_dates(window: DateWindow, max_dates: int) -> list[date]:
    """Pick a small, stable set of days from a window for lightweight previews."""

    if max_dates <= 0:
        raise ValueError("max_dates must be positive")
    days = (window.end - window.start).days + 1
    if days <= max_dates:
        return [window.start + timedelta(days=offset) for offset in range(days)]
    if max_dates == 1:
        return [window.start + timedelta(days=days // 2)]
    step = (days - 1) / (max_dates - 1)
    return [window.start + timedelta(days=round(i * step)) for i in range(max_dates)]


def _as_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)
