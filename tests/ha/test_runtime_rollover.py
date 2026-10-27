"""Midnight, billing-period rollover, pooled tiers (issue #2) and bonus settlement."""
import pytest

from homeassistant.core import HomeAssistant

from plan_helpers import (
    OFF_PEAK,
    PEAK,
    advance_to,
    local,
    make_entry,
    preload,
    set_meter,
    setup_entry,
    stored,
)

POOLED_OFF_PEAK = {**OFF_PEAK, "tier_reset": "billing_period"}


async def test_midnight_resets_daily_counters_and_charges_supply(hass: HomeAssistant, freezer):
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry(daily_charge=1.5))
    set_meter(hass, 1012)
    await hass.async_block_till_done()
    day_one = 10 * 0.20 + 2 * 0.30
    assert rt.cost_today == pytest.approx(day_one)

    await advance_to(hass, freezer, "2026-10-16 00:00:00")

    assert rt.today.isoformat() == "2026-10-16"
    assert rt.cost_today == pytest.approx(1.5)
    assert rt.cost_billing_period == pytest.approx(day_one + 1.5)
    assert rt.tier_usage_today == {}
    assert rt.period_energy_kwh_today == {}
    # Billing-period energy is not a daily counter.
    assert rt.period_energy_kwh_billing_period["Off-peak"] == pytest.approx(12)
    # The daily tier is fresh again.
    assert rt.current_rate() == 0.20


async def test_missed_midnight_self_corrects_on_setup(hass: HomeAssistant, hass_storage):
    preload(
        hass_storage,
        last_energy_kwh=1000.0,
        last_energy_source="sensor.grid_import",
        today="2026-10-14",
        cost_today=3.0,
        cost_billing_period=10.0,
        tier_usage_today={"Off-peak": 12.0},
        billing_period_start="2026-10-01",
        billing_period_end="2026-10-31",
    )
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry(daily_charge=1.5))

    assert rt.cost_today == pytest.approx(1.5)
    assert rt.cost_billing_period == pytest.approx(11.5)
    assert rt.tier_usage_today == {}


async def test_billing_rollover_resets_period_totals_and_pool(hass: HomeAssistant, freezer):
    freezer.move_to(local("2026-10-30 23:00:00"))
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry(periods=[PEAK, POOLED_OFF_PEAK], daily_charge=1.0))
    set_meter(hass, 1005)
    await hass.async_block_till_done()
    assert rt.tier_usage_billing_period["Off-peak"] == pytest.approx(5)

    await advance_to(hass, freezer, "2026-10-31 00:00:00")

    assert rt.billing_period_start.isoformat() == "2026-10-31"
    assert rt.tier_usage_billing_period == {}
    assert rt.period_energy_kwh_billing_period == {}
    # The new period's first day keeps its supply charge.
    assert rt.cost_billing_period == pytest.approx(1.0)


async def test_billing_cycle_edit_mid_period_keeps_the_money(hass: HomeAssistant):
    set_meter(hass, 1000)
    entry = make_entry()
    rt = await setup_entry(hass, entry)
    set_meter(hass, 1001)
    await hass.async_block_till_done()

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "billing_cycle_start": "2026-10-02"}
    )
    await hass.async_block_till_done()

    from plan_helpers import runtime_of

    rt = runtime_of(hass)
    assert rt.billing_period_start.isoformat() == "2026-10-02"
    assert rt.cost_billing_period == pytest.approx(0.20)


async def test_pooled_tier_spends_allowance_across_days(hass: HomeAssistant, freezer):
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry(periods=[PEAK, POOLED_OFF_PEAK]))

    # 25 kWh in one day: a daily tier would bill 15 of it at $0.30.
    set_meter(hass, 1025)
    await hass.async_block_till_done()
    assert rt.cost_today == pytest.approx(25 * 0.20)

    await advance_to(hass, freezer, "2026-10-16 00:00:00")
    assert rt.tier_usage_billing_period["Off-peak"] == pytest.approx(25)
    assert rt.current_rate() == 0.20


async def test_pooled_tier_straddles_the_pool_boundary(hass: HomeAssistant, hass_storage):
    # 30-day bill x 10/day = a 300 kWh pool, 295 already used.
    preload(
        hass_storage,
        last_energy_kwh=1000.0,
        last_energy_source="sensor.grid_import",
        energy_source_unit="kWh",
        today="2026-10-15",
        tier_usage_billing_period={"Off-peak": 295.0},
        billing_period_start="2026-10-01",
        billing_period_end="2026-10-31",
    )
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry(periods=[PEAK, POOLED_OFF_PEAK]))

    set_meter(hass, 1010)
    await hass.async_block_till_done()

    assert rt.cost_today == pytest.approx(5 * 0.20 + 5 * 0.30)
    assert rt.current_rate() == 0.30
    assert stored(hass_storage)["tier_usage_billing_period"]["Off-peak"] == pytest.approx(305)


async def test_pool_is_seeded_from_billing_energy_on_upgrade(hass: HomeAssistant, hass_storage):
    preload(
        hass_storage,
        last_energy_kwh=1000.0,
        today="2026-10-15",
        period_energy_kwh_billing_period={"Off-peak": 120.0},
        billing_period_start="2026-10-01",
        billing_period_end="2026-10-31",
    )
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry(periods=[PEAK, POOLED_OFF_PEAK]))

    assert rt.tier_usage_billing_period == {"Off-peak": 120.0}


async def test_manual_cost_reset_keeps_pool_progress(hass: HomeAssistant):
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry(periods=[PEAK, POOLED_OFF_PEAK]))
    set_meter(hass, 1020)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "tariff_tracker", "reset_costs", {"config_entry_id": "test_entry"}, blocking=True
    )
    assert rt.cost_billing_period == 0
    assert rt.tier_usage_billing_period["Off-peak"] == pytest.approx(20)

    await hass.services.async_call(
        "tariff_tracker",
        "reset_costs",
        {"config_entry_id": "test_entry", "reset_tier_usage": True},
        blocking=True,
    )
    assert rt.tier_usage_billing_period == {}


async def test_daily_default_is_unchanged_by_pooling_support(hass: HomeAssistant):
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry())
    set_meter(hass, 1025)
    await hass.async_block_till_done()
    assert rt.cost_today == pytest.approx(10 * 0.20 + 15 * 0.30)


# ---- bonus -------------------------------------------------------------

BONUS_PEAK = {
    **PEAK,
    "bonus": {
        "amount": 1.0,
        "threshold_w": 100,
        "calc_mode": "energy_delta",
        "bonus_start_time": "18:00:00",
        "bonus_end_time": "21:00:00",
    },
}


async def _bonus_evening(hass, freezer, used_kwh: float):
    freezer.move_to(local("2026-10-15 18:00:00"))
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry(periods=[BONUS_PEAK, OFF_PEAK]))
    freezer.move_to(local("2026-10-15 19:00:00"))
    set_meter(hass, 1000 + used_kwh)
    await hass.async_block_till_done()
    await advance_to(hass, freezer, "2026-10-15 21:00:00")
    return rt


async def test_bonus_credited_once_when_window_stays_under_threshold(hass: HomeAssistant, freezer, hass_storage):
    # 0.2 kWh over the 3 h window is ~67 W, under 100 W.
    rt = await _bonus_evening(hass, freezer, 0.2)

    usage = 0.2 * 0.40
    assert rt.bonus_earned_today["Peak"] is True
    assert rt.cost_today == pytest.approx(usage - 1.0)
    assert rt.cost_month == pytest.approx(usage - 1.0)
    assert rt.cost_billing_period == pytest.approx(usage - 1.0)
    assert rt.bonus_days_earned_billing_period == 1
    assert stored(hass_storage)["bonus_finalized_for"]["Peak"] == "2026-10-15"
    assert hass.states.get("binary_sensor.test_plan_peak_bonus_earned_today").state == "on"

    # A repeat of the same tick (DST fall-back) must not credit twice.
    assert rt._finalize_bonus("Peak", local("2026-10-15 21:00:00")) is False


async def test_bonus_withheld_over_threshold(hass: HomeAssistant, freezer):
    # 0.6 kWh over 3 h is 200 W.
    rt = await _bonus_evening(hass, freezer, 0.6)

    assert rt.bonus_earned_today["Peak"] is False
    assert rt.cost_today == pytest.approx(0.6 * 0.40)
    assert hass.states.get("binary_sensor.test_plan_peak_bonus_earned_today").state == "off"


async def test_bonus_credited_at_exactly_the_threshold(hass: HomeAssistant, freezer):
    # 0.3 kWh over 3 h is exactly 100 W - the limit itself keeps the bonus.
    rt = await _bonus_evening(hass, freezer, 0.3)

    assert rt.bonus_earned_today["Peak"] is True
    assert rt.bonus_days_earned_billing_period == 1


async def test_bonus_survives_period_close_firing_first(hass: HomeAssistant, freezer):
    # Bonus and period both end at 21:00, so two callbacks share a second in
    # no guaranteed order. The period's close used to clear the bonus
    # numerator, settling the bonus against zero usage. Force that order.
    freezer.move_to(local("2026-10-15 18:00:00"))
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry(periods=[BONUS_PEAK, OFF_PEAK]))
    freezer.move_to(local("2026-10-15 19:00:00"))
    set_meter(hass, 1000.6)  # 200 W over the window - no bonus
    await hass.async_block_till_done()

    at = local("2026-10-15 21:00:00")
    freezer.move_to(at)
    rt._make_period_avg_finalizer("Peak")(at)
    assert rt._finalize_bonus("Peak", at) is True
    assert rt.bonus_earned_today["Peak"] is False


async def test_usage_before_the_bonus_window_does_not_count_against_it(hass: HomeAssistant, freezer):
    # Peak opens 16:00 but the bonus window is 18:00-21:00. A big 17:00 load
    # is paid for at the peak rate and has no bearing on the bonus.
    freezer.move_to(local("2026-10-15 16:00:00"))
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry(periods=[BONUS_PEAK, OFF_PEAK]))
    freezer.move_to(local("2026-10-15 17:00:00"))
    set_meter(hass, 1003)
    await hass.async_block_till_done()
    freezer.move_to(local("2026-10-15 19:00:00"))
    set_meter(hass, 1003.1)  # ~33 W across the bonus window
    await hass.async_block_till_done()

    await advance_to(hass, freezer, "2026-10-15 21:00:00")

    assert rt.bonus_earned_today["Peak"] is True
    assert rt.period_energy_kwh_today["Peak"] == pytest.approx(3.1)


async def test_bonus_missed_while_down_is_settled_on_setup(hass: HomeAssistant, freezer, hass_storage):
    preload(
        hass_storage,
        last_energy_kwh=1000.0,
        last_energy_source="sensor.grid_import",
        today="2026-10-15",
        energy_by_period_today={"Peak": 0.1},
        bonus_finalized_for={},
        billing_period_start="2026-10-01",
        billing_period_end="2026-10-31",
    )
    freezer.move_to(local("2026-10-15 21:30:00"))
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry(periods=[BONUS_PEAK, OFF_PEAK]))

    assert rt.bonus_earned_today["Peak"] is True
    assert rt.cost_today == pytest.approx(-1.0)
