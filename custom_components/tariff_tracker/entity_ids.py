"""Unique-id bookkeeping for per-period entities.

Deleting or renaming a period removes it from the config, but the platforms
only ever *add* entities for periods that still exist - nothing tells the
entity registry the old ones are gone. Working out which registry entries
are now orphaned means knowing the shape of every per-period unique id, so
that lives here: no Home Assistant imports, directly unit-testable, and one
place to update when a per-period entity is added.

Kept out of tariff_engine.py because it is entity plumbing, not tariff math.
"""
from __future__ import annotations

from typing import Any

try:
    from .const import CONF_PERIOD_BONUS, CONF_PERIOD_NAME
except ImportError:  # imported standalone (e.g. from tests) without the package
    from const import CONF_PERIOD_BONUS, CONF_PERIOD_NAME

# Suffixes minted for every import period, in sensor.py / binary_sensor.py.
PERIOD_SUFFIXES: tuple[str, ...] = (
    "avg_watts_today",
    "energy_kwh_today",
    "energy_kwh_billing_period",
    "energy_kwh_total",
    "window",
    "rate",
)

# Only minted for an import period that has a bonus configured.
PERIOD_BONUS_SUFFIXES: tuple[str, ...] = (
    "bonus_threshold",  # sensor.py
    "bonus_active_window",  # binary_sensor.py
    "bonus_earned_today",  # binary_sensor.py
)

# Export periods get a smaller set, and their ids carry an "export_" prefix
# ahead of the period name. The suffixes themselves overlap with the import
# ones, so anything classifying an id by suffix alone must account for both -
# otherwise every export period entity looks like an orphaned import one and
# gets deleted on each reload.
EXPORT_PERIOD_SUFFIXES: tuple[str, ...] = (
    "energy_kwh_billing_period",
    "energy_kwh_total",
)

ALL_PERIOD_SUFFIXES: tuple[str, ...] = tuple(
    dict.fromkeys(PERIOD_SUFFIXES + PERIOD_BONUS_SUFFIXES + EXPORT_PERIOD_SUFFIXES)
)

# Keys of the plan-level entities: one of each per config entry, never tied to
# a period. They are listed here because two of them - current_rate and
# current_export_rate - end with "_rate" and so look exactly like a period's
# rate sensor to a suffix test. That misread deleted both from the entity
# registry on every reload; they only appeared to survive because Home
# Assistant restores a removed entity's id from its deleted-entities record,
# so the churn was invisible apart from modified_at moving every time.
PLAN_LEVEL_KEYS: tuple[str, ...] = (
    "billing_period_start",
    "bonus_day_percentage",
    "bonus_days_earned",
    "bonus_savings",
    "bonus_window_avg_w",
    "cost_billing_period",
    "cost_month",
    "cost_today",
    "current_export_period",
    "current_export_rate",
    "current_period",
    "current_rate",
    "daily_charge",
    "days_remaining",
    "export_credit_billing_period",
    "export_credit_month",
    "export_credit_today",
    "reset_cost_history",
    "reset_monthly_cost",
)


def is_period_unique_id(unique_id: str, entry_id: str) -> bool:
    """Whether a unique id belongs to a per-period entity.

    Plan-level entities must fail this: they are never orphaned, so cleanup
    must not consider them at all.
    """
    if any(unique_id == f"{entry_id}_{key}" for key in PLAN_LEVEL_KEYS):
        return False
    return any(unique_id.endswith(f"_{suffix}") for suffix in ALL_PERIOD_SUFFIXES)


def period_unique_ids(
    entry_id: str,
    periods: list[dict[str, Any]],
    export_periods: list[dict[str, Any]] | None = None,
) -> set[str]:
    """Every per-period unique id the platforms will create for this entry."""
    valid: set[str] = set()

    for period in periods:
        name = period[CONF_PERIOD_NAME]
        for suffix in PERIOD_SUFFIXES:
            valid.add(f"{entry_id}_{name}_{suffix}")
        if period.get(CONF_PERIOD_BONUS):
            for suffix in PERIOD_BONUS_SUFFIXES:
                valid.add(f"{entry_id}_{name}_{suffix}")

    for period in export_periods or []:
        name = period[CONF_PERIOD_NAME]
        for suffix in EXPORT_PERIOD_SUFFIXES:
            valid.add(f"{entry_id}_export_{name}_{suffix}")

    return valid
