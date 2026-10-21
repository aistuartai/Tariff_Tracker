"""Plan energy units (issue #1) and billing-period pooled tiers (issue #2)."""
import pytest

import tariff_engine as engine

# 15/day free, then $0.30 - priced like a retailer's "first N per day" step.
STEPPED = {
    "name": "Anytime",
    "start_time": "00:00",
    "end_time": "00:00",
    "days": "all",
    "tiers": [
        {"limit_kwh": 15, "rate": 0.20},
        {"limit_kwh": None, "rate": 0.30},
    ],
}
POOLED = dict(STEPPED, tier_reset="billing_period")


# ---- tier_view ---------------------------------------------------------


def test_daily_view_is_the_default_and_uses_todays_usage():
    tiers, used = engine.tier_view(STEPPED, 4.0, 400.0, 30)
    assert tiers == STEPPED["tiers"]
    assert used == 4.0


def test_explicit_daily_matches_absent_key():
    daily = dict(STEPPED, tier_reset="daily")
    assert engine.tier_view(daily, 4.0, 400.0, 30) == engine.tier_view(
        STEPPED, 4.0, 400.0, 30
    )


def test_pooled_view_scales_limits_by_billing_days():
    tiers, used = engine.tier_view(POOLED, 4.0, 400.0, 30)
    assert tiers[0]["limit_kwh"] == 450
    assert tiers[1]["limit_kwh"] is None
    assert used == 400.0
    # Config is not mutated by the scaling.
    assert POOLED["tiers"][0]["limit_kwh"] == 15


def test_pooled_view_falls_back_to_daily_without_bounds():
    assert engine.tier_view(POOLED, 4.0, 400.0, None) == (POOLED["tiers"], 4.0)


def test_pooled_heavy_day_stays_on_first_tier_while_allowance_remains():
    # 40 kWh in a day: daily reset bills 25 of it at the second tier, but
    # with quiet days banked the whole day is still inside the pool.
    daily = engine.cost_of_delta(*engine.tier_view(STEPPED, 0.0, 100.0, 30), 40)
    pooled = engine.cost_of_delta(*engine.tier_view(POOLED, 0.0, 100.0, 30), 40)
    assert daily == pytest.approx(15 * 0.20 + 25 * 0.30)
    assert pooled == pytest.approx(40 * 0.20)


def test_pooled_delta_straddles_the_pool_boundary():
    # 440 used of a 450 pool; 20 more splits 10 / 10.
    cost = engine.cost_of_delta(*engine.tier_view(POOLED, 0.0, 440.0, 30), 20)
    assert cost == pytest.approx(10 * 0.20 + 10 * 0.30)


def test_pooled_rate_after_pool_exhausted():
    tiers, used = engine.tier_view(POOLED, 0.0, 450.0, 30)
    assert engine.tier_rate_for_usage(tiers, used) == 0.30


def test_pooled_flat_rate_period_is_unchanged():
    flat = {"name": "Peak", "tier_reset": "billing_period", "tiers": [{"limit_kwh": None, "rate": 0.44}]}
    tiers, _ = engine.tier_view(flat, 1.0, 50.0, 30)
    assert tiers == flat["tiers"]


# ---- plan_energy_unit ----------------------------------------------------


@pytest.mark.parametrize(
    "source, expected",
    [
        ("kWh", ("kWh", 1.0)),
        ("Wh", ("kWh", 0.001)),
        ("MWh", ("kWh", 1000.0)),
        ("MJ", ("MJ", 1.0)),
        ("GJ", ("GJ", 1.0)),
        (None, ("kWh", 1.0)),
        ("", ("kWh", 1.0)),
    ],
)
def test_plan_energy_unit(source, expected):
    unit, factor = engine.plan_energy_unit(source)
    assert unit == expected[0]
    assert factor == pytest.approx(expected[1])


def test_wh_source_bills_in_kwh():
    # 2500 Wh read off the meter is 2.5 kWh at the plan's $/kWh rate.
    _, factor = engine.plan_energy_unit("Wh")
    cost = engine.cost_of_delta(STEPPED["tiers"], 0.0, 2500 * factor)
    assert cost == pytest.approx(2.5 * 0.20)


def test_kwh_per_plan_unit_gives_real_power_for_gas():
    # 3.6 MJ over one hour is a steady 1 kW.
    kwh = 3.6 * engine.kwh_per_plan_unit("MJ")
    assert engine.avg_watts_from_energy(kwh, 1.0) == pytest.approx(1000.0)


def test_kwh_per_plan_unit_unknown_unit():
    assert engine.kwh_per_plan_unit("furlongs") is None
