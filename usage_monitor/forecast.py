"""
Forecast
=========

Pure functions behind the popup's usage forecast: an in-memory log of the
readings seen while the app runs, and a projection of the current pace to
the end of the quota window.

The projection uses the same elapsed-time scale as the popup's time marker
(:func:`~usage_monitor.formatting.elapsed_fraction`), so a quota
is forecast to run out exactly when its bar is drawn in the warning color,
and with an active schedule the projected line stays flat outside working
hours.  Nothing here is persisted: the log starts empty on every launch.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .formatting import divider_positions, elapsed_fraction, field_period, is_active_quota
from .i18n import T
from .pacing import WorkSchedule
from .settings import TIME_FORMAT

__all__ = ['MAX_SAMPLES', 'record_samples', 'usage_forecast']

# Readings kept per quota - more than a week of polls at the normal cadence,
# since unchanged readings collapse into the ends of a flat run.
MAX_SAMPLES = 2000

# Below this share of elapsed time the pace is too noisy to project.
_MIN_ELAPSED_FRACTION = 0.02

# Points of the projected line; enough for flat off-hour steps to stay sharp.
_PROJECTION_STEPS = 120

# Bisection steps for the run-out instant - below a second over a week.
_BISECTION_STEPS = 40

# Rounding of a session's run-out time: to the hour, or to the quarter hour
# when it is less than an hour away and a full hour would be too coarse.
_ROUNDING_STEP = timedelta(hours=1)
_NEAR_ROUNDING_STEP = timedelta(minutes=15)


def record_samples(history: dict[str, dict[str, Any]], usage: dict[str, Any], now: float) -> dict[str, dict[str, Any]]:
    """Return *history* extended by the readings in a successful usage response.

    Each active quota with a reset window keeps the readings of its current
    window as ``(unix_time, utilization)`` pairs.  A new window - a reset
    time that moved, or a utilization that dropped (a reset or an account
    switch) - starts the log over.  A reading equal to the two before it
    only moves the end of that flat run, so a quiet week stays small.

    Parameters
    ----------
    history : dict
        Previous result of this function (``{}`` initially).  Not modified.
    usage : dict
        Normalized quota data.
    now : float
        Unix time of the reading.

    Returns
    -------
    dict
        ``{field: {'resets_at': str, 'samples': tuple}}`` for every quota
        in *usage* that has a reset window.
    """
    result: dict[str, dict[str, Any]] = {}
    for field, entry in usage.items():
        if field == 'extra_usage' or not is_active_quota(field, entry) or not entry.get('resets_at'):
            continue

        period = field_period(field)
        reset = _parse_reset(entry['resets_at'])
        pct = _utilization(entry)
        if period is None or reset is None or pct is None:
            continue

        resets_at = entry['resets_at']
        previous = history.get(field)
        samples: tuple[tuple[float, float], ...] = ()
        if previous and _same_window(previous['resets_at'], reset, period):
            last_time, last_pct = previous['samples'][-1]
            if now >= last_time and pct >= last_pct:
                samples = previous['samples']

        if len(samples) >= 2 and samples[-1][1] == pct and samples[-2][1] == pct:
            samples = samples[:-1] + ((now, pct),)
        else:
            samples = (samples + ((now, pct),))[-MAX_SAMPLES:]

        result[field] = {'resets_at': resets_at, 'samples': samples}

    return result


def usage_forecast(
    field: str, usage: dict[str, Any], history: dict[str, dict[str, Any]], now: datetime, *,
    work_schedule: WorkSchedule | None = None,
) -> dict[str, Any] | None:
    """Build the popup's forecast chart for one quota.

    The pace is the average over the window so far: the current utilization
    divided by the elapsed share of the window.  Projected forward on the
    same scale, it gives the utilization at reset, or - when it would pass
    100% first - the time the quota runs out.  Usage comes in bursts, so the
    summary states this as an approximation at the current pace; an exhausted
    quota has nothing left to project and gets no summary.

    Parameters
    ----------
    field : str
        Quota field to forecast.
    usage : dict
        Normalized quota data.
    history : dict
        Readings logged by :func:`record_samples`.
    now : datetime
        Timezone-aware current time.
    work_schedule : WorkSchedule or None
        The owning provider's optional pacing schedule.

    Returns
    -------
    dict or None
        Chart payload with ``x`` as the wall-clock share of the window
        (0.0-1.0) and ``y`` as utilization (0-100), or None when the field
        has no period, no reset window, or no utilization.
    """
    entry = usage.get(field)
    period = field_period(field)
    if not period or not isinstance(entry, dict):
        return None
    reset = _parse_reset(entry.get('resets_at'))
    pct = _utilization(entry)
    if reset is None or pct is None or now.utcoffset() is None:
        return None
    try:
        start = reset - timedelta(seconds=period)
    except OverflowError:
        return None
    if not start <= now < reset:
        return None

    fraction_at = elapsed_fraction(entry['resets_at'], period, field=field, work_schedule=work_schedule)
    if fraction_at is None:
        return None

    def wall_x(when: datetime) -> float:
        return max(0.0, min(1.0, (when - start).total_seconds() / period))

    now_x = wall_x(now)
    measured = []
    logged = history.get(field)
    if logged and _same_window(logged['resets_at'], reset, period):
        for timestamp, sample_pct in logged['samples']:
            sample_time = datetime.fromtimestamp(timestamp, timezone.utc)
            if start <= sample_time <= now:
                measured.append([wall_x(sample_time), min(100.0, sample_pct)])
    # The current reading is usually the last logged one; draw it once.
    if measured and measured[-1][0] >= now_x - 1e-6:
        measured.pop()
    measured.append([now_x, min(100.0, pct)])

    forecast: dict[str, Any] = {
        'actual': [[0.0, 0.0]] + measured,
        # Before the first logged reading only the window start (0%) is known.
        'measured_from': measured[0][0],
        'now_x': now_x,
        'ticks': _ticks(start, reset, period),
        'projection': [],
        'runs_out': False,
        'summary': '',
    }

    elapsed_now = fraction_at(now)
    if elapsed_now < _MIN_ELAPSED_FRACTION:
        return forecast

    if pct >= 100:
        forecast['runs_out'] = True
        return forecast

    rate = pct / elapsed_now
    end = _run_out_time(fraction_at, 100 / rate, now, reset) if rate > 100 else reset

    projection = []
    span = (end - now).total_seconds()
    for step in range(_PROJECTION_STEPS + 1):
        when = now + timedelta(seconds=span * step / _PROJECTION_STEPS)
        projection.append([wall_x(when), min(100.0, rate * fraction_at(when))])

    forecast['projection'] = projection
    forecast['runs_out'] = end < reset
    if end < reset:
        forecast['summary'] = T['forecast_runs_out'].format(when=_approximate_time(end, period, now))
    else:
        forecast['summary'] = T['forecast_at_reset'].format(pct=f'{min(100.0, rate):.0f}')

    return forecast


def _parse_reset(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        reset = datetime.fromisoformat(value)
        return None if reset.utcoffset() is None else reset.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _utilization(entry: dict[str, Any]) -> float | None:
    value = entry.get('utilization')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return float(min(value, 100))


def _same_window(previous_reset: str, reset: datetime, period: int) -> bool:
    """Allow timestamp jitter, capped well below even a short quota period."""
    previous = _parse_reset(previous_reset)
    tolerance = min(60, period / 100)
    return previous is not None and abs((reset - previous).total_seconds()) <= tolerance


def _run_out_time(fraction_at: Callable[[datetime], float], target: float, now: datetime, reset: datetime) -> datetime:
    """Find the first instant between *now* and *reset* whose elapsed share reaches *target*.

    The elapsed share never decreases over time, so bisection converges;
    with a schedule it settles on the end of the working time that crosses
    the target, never inside a flat off-hour stretch.
    """
    low, high = now, reset
    for _ in range(_BISECTION_STEPS):
        middle = low + (high - low) / 2
        if fraction_at(middle) >= target:
            high = middle
        else:
            low = middle

    return high


def _ticks(start: datetime, reset: datetime, period: int) -> list[dict[str, Any]]:
    """Return x-axis ticks: local midnights labelled with the day they start, or unlabelled hours."""
    if period < 86400:
        return [{'x': position, 'label': ''} for position in divider_positions(reset.isoformat(), period)]

    ticks = []
    day = start.astimezone().date() + timedelta(days=1)
    while True:
        midnight = datetime(day.year, day.month, day.day).astimezone(timezone.utc)
        if midnight >= reset:
            break
        relative = (midnight - start).total_seconds() / period
        if 0.003 < relative < 0.997:
            ticks.append({'x': relative, 'label': T['weekdays'][day.weekday()]})
        day += timedelta(days=1)
    return ticks


def _approximate_time(when: datetime, period: int, now: datetime) -> str:
    """Format a projected instant no finer than the projection deserves.

    A period of a day or longer names the weekday.  A session names the
    clock time, rounded to the hour - or to the quarter hour when *when* is
    less than an hour away - and never to a time at or before *now*.

    Parameters
    ----------
    when : datetime
        Timezone-aware projected instant, after *now*.
    period : int
        Length of the quota period in seconds.
    now : datetime
        Timezone-aware current time.

    Returns
    -------
    str
        Localized weekday or clock time.
    """
    local = when.astimezone()
    if period >= 24 * 3600:
        return T['weekdays'][local.weekday()]

    step = _NEAR_ROUNDING_STEP if when - now < _ROUNDING_STEP else _ROUNDING_STEP
    hour = local.replace(minute=0, second=0, microsecond=0)
    rounded = hour + step * ((local - hour + step / 2) // step)
    if rounded <= now:
        rounded += step

    if TIME_FORMAT == '24h':
        return rounded.strftime('%H:%M')
    return rounded.strftime('%I:%M %p').lstrip('0')
