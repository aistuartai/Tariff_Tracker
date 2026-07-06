"""Pure calculation logic for Tariff Tracker.

No Home Assistant imports here on purpose: this module is unit-testable
in isolation and holds all the "what does this plan actually cost" logic.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

try:
    from .const import (
        BILLING_CYCLE_EVERY_N_DAYS,
        CONF_PERIOD_DAYS,
        CONF_PERIOD_END_TIME,
        CONF_PERIOD_NAME,
        CONF_PERIOD_START_TIME,
        CONF_PERIOD_TIERS,
        CONF_TIER_LIMIT_KWH,
        CONF_TIER_RATE,
        DAYS_WEEKDAYS,
        DAYS_WEEKENDS,
    )
except ImportError:  # imported standalone (e.g. from tests) without the package
    from const import (
        BILLING_CYCLE_EVERY_N_DAYS,
        CONF_PERIOD_DAYS,
        CONF_PERIOD_END_TIME,
        CONF_PERIOD_NAME,
        CONF_PERIOD_START_TIME,
        CONF_PERIOD_TIERS,
        CONF_TIER_LIMIT_KWH,
        CONF_TIER_RATE,
        DAYS_WEEKDAYS,
        DAYS_WEEKENDS,
    )


def parse_time(value: str | time) -> time:
    if isinstance(value, time):
        return value
    return datetime.strptime(value, "%H:%M:%S").time() if len(value) > 5 else datetime.strptime(value, "%H:%M").time()


def period_applies_to_day(period: dict[str, Any], day: date) -> bool:
    """Return True if a period's day-filter includes the given date."""
    days_filter = period.get(CONF_PERIOD_DAYS)
    is_weekend = day.weekday() >= 5
    if days_filter == DAYS_WEEKDAYS:
        return not is_weekend
    if days_filter == DAYS_WEEKENDS:
        return is_weekend
    return True  # DAYS_ALL or unset


def period_contains_time(period: dict[str, Any], at: datetime) -> bool:
    """Return True if `at` falls inside period's time window on its own day.

    Supports overnight windows (start > end, e.g. 22:00-06:00).
    """
    if not period_applies_to_day(period, at.date()):
        return False

    start = parse_time(period[CONF_PERIOD_START_TIME])
    end = parse_time(period[CONF_PERIOD_END_TIME])
    now = at.time()

    if start <= end:
        return start <= now < end
    # Overnight window wraps past midnight.
    return now >= start or now < end


def find_active_period(
    periods: list[dict[str, Any]], at: datetime
) -> dict[str, Any] | None:
    """Find which configured period is active at the given moment.

    Periods are checked in configured order; first match wins. Returns
    None if no period covers this moment (a configuration gap).
    """
    for period in periods:
        if period_contains_time(period, at):
            return period
    return None


def tier_rate_for_usage(
    tiers: list[dict[str, Any]], kwh_already_used_in_period_today: float
) -> float:
    """Return the $/kWh rate that applies for the next unit of usage.

    `tiers` is an ordered list of {limit_kwh, rate}. A tier with
    limit_kwh=None is the final/unbounded tier. `kwh_already_used_in_period_today`
    is how much has already been consumed under this period *today* (tiers
    reset daily, matching typical retailer "first N kWh/day" wording).
    """
    cumulative = 0.0
    for tier in tiers:
        limit = tier.get(CONF_TIER_LIMIT_KWH)
        rate = tier[CONF_TIER_RATE]
        if limit is None:
            return rate
        if kwh_already_used_in_period_today < cumulative + limit:
            return rate
        cumulative += limit
    # Fell through: usage exceeds all bounded tiers and there was no
    # unbounded final tier configured. Fall back to the last tier's rate.
    return tiers[-1][CONF_TIER_RATE] if tiers else 0.0


def cost_of_delta(
    period: dict[str, Any], kwh_already_used_in_period_today: float, delta_kwh: float
) -> float:
    """Cost in dollars of importing `delta_kwh` more, given today's tier usage so far.

    Splits the delta across a tier boundary if it straddles one.
    """
    tiers = period.get(CONF_PERIOD_TIERS, [])
    if not tiers or delta_kwh <= 0:
        return 0.0

    remaining = delta_kwh
    used = kwh_already_used_in_period_today
    total_cost = 0.0
    cumulative = 0.0

    for tier in tiers:
        limit = tier.get(CONF_TIER_LIMIT_KWH)
        rate = tier[CONF_TIER_RATE]
        tier_ceiling = cumulative + limit if limit is not None else float("inf")

        if used >= tier_ceiling:
            cumulative = tier_ceiling
            continue

        available_in_tier = tier_ceiling - used
        consumed_here = min(remaining, available_in_tier)
        total_cost += consumed_here * rate
        remaining -= consumed_here
        used += consumed_here

        if remaining <= 0:
            break
        cumulative = tier_ceiling

    return total_cost


def billing_period_bounds(
    cycle_type: str, cycle_days: int | None, cycle_start: date | None, today: date
) -> tuple[date, date]:
    """Return (start, end_exclusive) of the billing period containing `today`."""
    if cycle_type == BILLING_CYCLE_EVERY_N_DAYS:
        if cycle_start is None or not cycle_days:
            raise ValueError("cycle_start and cycle_days required for every_n_days")
        days_since_anchor = (today - cycle_start).days
        cycles_elapsed = days_since_anchor // cycle_days
        start = cycle_start + timedelta(days=cycles_elapsed * cycle_days)
        end = start + timedelta(days=cycle_days)
        return start, end

    # calendar_month
    start = today.replace(day=1)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def avg_watts_from_energy(kwh_over_window: float, window_hours: float) -> float:
    """Average import power (W) implied by energy imported over a window."""
    if window_hours <= 0:
        return 0.0
    return (kwh_over_window / window_hours) * 1000
