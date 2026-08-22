"""Pure observation-freshness policy shared by CI and the dashboard."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

MAX_LAG_MONTHS = 3


def _as_date(value: Any) -> date:
    """Normalize date-like values without depending on pandas."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        converted = value.date()
        if isinstance(converted, date):
            return converted
    text = str(value).strip()[:10]
    return date.fromisoformat(text)


def observation_lag_months(observed_on: Any, as_of: Any | None = None) -> int:
    """Whole calendar-month lag between an observation and an as-of date."""
    observed = _as_date(observed_on)
    current = _as_date(as_of) if as_of is not None else date.today()
    lag = (current.year - observed.year) * 12 + current.month - observed.month
    return max(0, lag)


def freshness_state(
    observed_on: Any,
    as_of: Any | None = None,
    max_lag_months: int = MAX_LAG_MONTHS,
) -> tuple[str, int, str]:
    """Return severity, exact month lag, and a user-facing message."""
    observed = _as_date(observed_on)
    lag = observation_lag_months(observed, as_of)
    if lag > max_lag_months:
        return (
            "error",
            lag,
            f"Data freshness alert: newest observation is {observed.isoformat()} "
            f"({lag} months old; policy limit: {max_lag_months}). "
            "Values are historical, not current.",
        )
    return (
        "success",
        lag,
        f"Data freshness: newest observation is {observed.isoformat()} "
        f"({lag} months old; policy limit: {max_lag_months}).",
    )
