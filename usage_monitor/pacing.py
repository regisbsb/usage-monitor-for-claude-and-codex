"""Work-hour pacing for normalized quota windows."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

__all__ = ['WorkSchedule', 'parse_work_schedule', 'validate_schedule_fields']

_WEEKDAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
_DAY = timedelta(days=1)


def parse_work_schedule(value: object, fields: tuple[str, ...] | None = None) -> WorkSchedule:
    """Validate and normalize a local weekday schedule or raise ValueError.

    A weekday can have one pair or a list of pairs. An end before its start
    crosses midnight, and an empty weekday has no active time.
    """
    if not isinstance(value, dict):
        raise ValueError('expected an object keyed by weekday')
    for day in value:
        if day not in _WEEKDAYS:
            raise ValueError(f'{day}: expected a weekday key from mon to sun')

    weekdays = []
    for day in _WEEKDAYS:
        slots = value.get(day, [])
        if not isinstance(slots, list):
            raise ValueError(f'{day}: expected a slot [start, end] or an array of slots')
        pairs = slots if not slots or isinstance(slots[0], list) else [slots]
        normalized = []
        for pair in pairs:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError(f'{day}: expected a slot [start, end]')
            start, end = pair
            if not _valid_hour(start) or not _valid_hour(end) or start >= 24 or start == end:
                raise ValueError(f'{day}: require 0 <= start < 24, 0 <= end <= 24, and different hours')
            normalized.append((float(start), float(end)))
        weekdays.append(tuple(normalized))
    return WorkSchedule(tuple(weekdays), fields)


def _valid_hour(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 24 and math.isfinite(value)


def validate_schedule_fields(value: object) -> list[str]:
    """Validate exact field names or `*` patterns and preserve their order."""
    if not isinstance(value, list) or any(not isinstance(field, str) or not field or field.startswith('-') for field in value):
        raise ValueError('expected nonempty field names or wildcard patterns; exclusions are unsupported')
    return list(dict.fromkeys(value))


@dataclass(frozen=True)
class WorkSchedule:
    """Local working slots in weekday order and an optional quota selector."""

    weekdays: tuple[tuple[tuple[float, float], ...], ...]
    fields: tuple[str, ...] | None = None

    def window(self, reset: datetime, period_seconds: int, field: str | None) -> _WorkingWindow | None:
        """Return the active time within an eligible quota, if any."""
        if period_seconds < 86400 or not any(self.weekdays):
            return None
        if self.fields is not None and (field is None or not any(_matches(pattern, field) for pattern in self.fields)):
            return None

        end = reset.astimezone(timezone.utc)
        begin = end - timedelta(seconds=period_seconds)
        day = begin.astimezone().date() - _DAY
        last_day = end.astimezone().date()
        intervals = []
        starts = []
        while day <= last_day:
            day_starts = []
            for start_hour, end_hour in self.weekdays[day.weekday()]:
                slot_start = _local_boundary(day, start_hour)
                slot_end = _local_boundary(day + _DAY if end_hour < start_hour else day, end_hour)
                lower, upper = max(begin, slot_start), min(end, slot_end)
                if lower < upper:
                    intervals.append((lower, upper))
                    day_starts.append(slot_start)
            if day_starts and begin < min(day_starts) < end:
                starts.append(min(day_starts))
            day += _DAY

        merged: list[tuple[datetime, datetime]] = []
        for lower, upper in sorted(intervals):
            if merged and lower <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(upper, merged[-1][1]))
            else:
                merged.append((lower, upper))
        if not merged:
            return None
        return _WorkingWindow(merged, starts, sum((upper - lower).total_seconds() for lower, upper in merged))


def _matches(pattern: str, field: str) -> bool:
    return re.fullmatch(re.escape(pattern).replace(r'\*', '.*'), field) is not None


def _local_boundary(day: date, hour: float) -> datetime:
    """Convert each wall-clock boundary using the OS offset on its date."""
    return (datetime(day.year, day.month, day.day) + timedelta(hours=hour)).astimezone(timezone.utc)


@dataclass(frozen=True)
class _WorkingWindow:
    intervals: list[tuple[datetime, datetime]]
    starts: list[datetime]
    total: float

    def fraction(self, when: datetime) -> float:
        elapsed = sum(max(0.0, (min(when, upper) - lower).total_seconds()) for lower, upper in self.intervals)
        return elapsed / self.total

    def dividers(self) -> list[float]:
        return sorted({position for start in self.starts if 0.003 < (position := self.fraction(start)) < 0.997})
