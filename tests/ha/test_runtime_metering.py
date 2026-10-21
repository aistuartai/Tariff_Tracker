"""Meter readings in, cost out: baselines, deltas, restarts and source changes."""
import pytest

from homeassistant.core import HomeAssistant

from plan_helpers import (
    SOURCE,
    make_entry,
    preload,
    runtime_of,
    set_meter,
    setup_entry,
    stored,
)


async def test_seeds_baseline_at_setup_without_booking_usage(hass: HomeAssistant, hass_storage):
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry())

    assert rt.last_energy_kwh == 1000
    assert rt.cost_today == 0
    # Persisted in the same path that set it - an unsaved seed dies on restart.
    assert stored(hass_storage)["last_energy_kwh"] == 1000
    assert stored(hass_storage)["last_energy_source"] == SOURCE


async def test_delta_is_costed_at_the_active_periods_rate(hass: HomeAssistant, hass_storage):
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry())

    set_meter(hass, 1002.5)
    await hass.async_block_till_done()

    # 10:00 is off-peak: 2.5 kWh inside the 10 kWh first tier at $0.20.
    assert rt.cost_today == pytest.approx(0.50)
    assert rt.cost_billing_period == pytest.approx(0.50)
    assert rt.period_energy_kwh_today["Off-peak"] == pytest.approx(2.5)
    assert rt.tier_usage_today["Off-peak"] == pytest.approx(2.5)
    assert stored(hass_storage)["cost_today"] == pytest.approx(0.50)


async def test_delta_straddling_a_daily_tier_boundary_splits(hass: HomeAssistant):
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry())

    set_meter(hass, 1008)
    await hass.async_block_till_done()
    set_meter(hass, 1012)
    await hass.async_block_till_done()

    # 10 kWh at $0.20, then 2 kWh at $0.30.
    assert rt.cost_today == pytest.approx(10 * 0.20 + 2 * 0.30)
    assert rt.current_rate() == 0.30


async def test_unavailable_and_garbage_states_are_ignored(hass: HomeAssistant):
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry())

    for bad in ("unavailable", "unknown", "not-a-number"):
        set_meter(hass, bad)
        await hass.async_block_till_done()
    set_meter(hass, 1001)
    await hass.async_block_till_done()

    assert rt.last_energy_kwh == 1001
    assert rt.cost_today == pytest.approx(0.20)


async def test_meter_reset_books_the_new_reading_not_a_negative(hass: HomeAssistant):
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry())

    set_meter(hass, 2)
    await hass.async_block_till_done()

    assert rt.cost_today == pytest.approx(2 * 0.20)
    assert rt.last_energy_kwh == 2


async def test_unavailable_source_at_setup_falls_back_to_first_event(hass: HomeAssistant, hass_storage):
    set_meter(hass, "unavailable")
    rt = await setup_entry(hass, make_entry())
    assert rt.last_energy_kwh is None

    set_meter(hass, 1000)
    await hass.async_block_till_done()

    assert rt.last_energy_kwh == 1000
    assert rt.cost_today == 0
    assert stored(hass_storage)["last_energy_kwh"] == 1000


async def test_restart_counts_usage_made_while_down(hass: HomeAssistant):
    set_meter(hass, 1000)
    entry = make_entry()
    await setup_entry(hass, entry)

    assert await hass.config_entries.async_unload(entry.entry_id)
    set_meter(hass, 1003)  # nobody listening
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    rt = runtime_of(hass)
    # The stored baseline survives; the seed doesn't overwrite it.
    assert rt.last_energy_kwh == 1000
    set_meter(hass, 1004)
    await hass.async_block_till_done()
    assert rt.cost_today == pytest.approx(4 * 0.20)


async def test_source_change_drops_baseline_instead_of_booking_the_gap(hass: HomeAssistant, hass_storage):
    set_meter(hass, 1000)
    set_meter(hass, 5000, entity_id="sensor.better_meter")
    entry = make_entry()
    await setup_entry(hass, entry)

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "import_energy_sensor": "sensor.better_meter"}
    )
    await hass.async_block_till_done()  # update listener reloads the entry

    rt = runtime_of(hass)
    assert rt.last_energy_source == "sensor.better_meter"
    assert rt.last_energy_kwh == 5000
    assert rt.cost_today == 0

    set_meter(hass, 5001, entity_id="sensor.better_meter")
    await hass.async_block_till_done()
    assert rt.cost_today == pytest.approx(0.20)
    assert stored(hass_storage)["last_energy_source"] == "sensor.better_meter"


async def test_legacy_state_without_source_id_keeps_its_baseline(hass: HomeAssistant, hass_storage):
    preload(hass_storage, last_energy_kwh=990.0, today="2026-10-15",
            billing_period_start="2026-10-01", billing_period_end="2026-10-31")
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry())

    assert rt.last_energy_kwh == 990.0
    assert rt.last_energy_source == SOURCE
    set_meter(hass, 1001)
    await hass.async_block_till_done()
    # 990 -> 1001: the downtime usage is counted against the kept baseline.
    assert rt.cost_today == pytest.approx(10 * 0.20 + 1 * 0.30)
