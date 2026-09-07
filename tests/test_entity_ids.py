"""Orphaned-entity cleanup id bookkeeping.

Regression cover for a real miss: `energy_kwh_billing_period` and
`energy_kwh_total` were added as per-period sensors in 0.9.0 but never added
to the cleanup's suffix list, so deleting a period left those two entities
in the registry forever while its other four were removed correctly.
"""
import entity_ids

ENTRY = "01ABC"

PEAK_WITH_BONUS = {
    "name": "Peak Usage",
    "bonus": {"amount": 1.0, "threshold_w": 30},
}
SHOULDER_NO_BONUS = {"name": "Shoulder Usage", "bonus": None}
EXPORT_DAY = {"name": "Export Day"}


def test_every_import_period_suffix_is_claimed():
    ids = entity_ids.period_unique_ids(ENTRY, [SHOULDER_NO_BONUS])
    for suffix in entity_ids.PERIOD_SUFFIXES:
        assert f"{ENTRY}_Shoulder Usage_{suffix}" in ids


def test_the_two_suffixes_that_were_missed_are_covered():
    ids = entity_ids.period_unique_ids(ENTRY, [SHOULDER_NO_BONUS])
    assert f"{ENTRY}_Shoulder Usage_energy_kwh_billing_period" in ids
    assert f"{ENTRY}_Shoulder Usage_energy_kwh_total" in ids
    # ...and they must classify as period entities, or cleanup skips them.
    assert entity_ids.is_period_unique_id(
        f"{ENTRY}_Shoulder Usage_energy_kwh_billing_period", ENTRY
    )
    assert entity_ids.is_period_unique_id(f"{ENTRY}_Shoulder Usage_energy_kwh_total", ENTRY)


def test_bonus_ids_only_for_periods_that_have_a_bonus():
    ids = entity_ids.period_unique_ids(ENTRY, [PEAK_WITH_BONUS, SHOULDER_NO_BONUS])
    for suffix in entity_ids.PERIOD_BONUS_SUFFIXES:
        assert f"{ENTRY}_Peak Usage_{suffix}" in ids
        assert f"{ENTRY}_Shoulder Usage_{suffix}" not in ids


def test_export_period_ids_carry_the_export_prefix():
    ids = entity_ids.period_unique_ids(ENTRY, [], [EXPORT_DAY])
    assert f"{ENTRY}_export_Export Day_energy_kwh_total" in ids
    # The un-prefixed form is an import-period id and must not appear.
    assert f"{ENTRY}_Export Day_energy_kwh_total" not in ids


def test_export_entities_are_not_treated_as_orphans():
    # Export ids end with the same suffixes as import ones. If they were left
    # out of the valid set they would look orphaned and be deleted on every
    # single reload - the trap that adding the missing suffixes opens up.
    ids = entity_ids.period_unique_ids(ENTRY, [SHOULDER_NO_BONUS], [EXPORT_DAY])
    export_id = f"{ENTRY}_export_Export Day_energy_kwh_billing_period"
    assert entity_ids.is_period_unique_id(export_id, ENTRY)
    assert export_id in ids


def test_a_deleted_period_id_is_not_in_the_valid_set():
    ids = entity_ids.period_unique_ids(ENTRY, [SHOULDER_NO_BONUS])
    for suffix in entity_ids.PERIOD_SUFFIXES:
        assert f"{ENTRY}_Shoulder Load B_{suffix}" not in ids
        assert entity_ids.is_period_unique_id(f"{ENTRY}_Shoulder Load B_{suffix}", ENTRY)


def test_plan_level_key_list_matches_the_platforms():
    # A plan-level key that ends with a period suffix (current_rate,
    # current_export_rate) is indistinguishable from a period entity by
    # suffix alone, so it must be listed explicitly or cleanup deletes it.
    colliding = [
        key
        for key in entity_ids.PLAN_LEVEL_KEYS
        if any(key.endswith(f"_{s}") or key == s for s in entity_ids.ALL_PERIOD_SUFFIXES)
    ]
    assert colliding == ["current_export_rate", "current_rate"]


def test_plan_level_ids_are_never_period_entities():
    # These must fail classification, or cleanup would delete the plan's own
    # cost and billing sensors.
    for plan_key in (
        "cost_today",
        "cost_month",
        "cost_billing_period",
        "bonus_savings",
        "bonus_days_earned",
        "bonus_day_percentage",
        "billing_period_start",
        "days_remaining",
        "daily_charge",
        "current_period",
        "current_rate",
        "bonus_window_avg_w",
        "export_credit_today",
        "current_export_rate",
        "reset_cost_history",
        "reset_monthly_cost",
    ):
        assert not entity_ids.is_period_unique_id(f"{ENTRY}_{plan_key}", ENTRY), plan_key
