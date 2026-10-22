"""Live-power bonus samples survive a restart inside the bonus window."""
from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.core import HomeAssistant

from plan_helpers import (
    OFF_PEAK,
    PEAK,
    advance_to,
    local,
    make_entry,
    preload,
    runtime_of,
    set_meter,
    setup_entry,
    stored,
)

POWER = "sensor.grid_power"
LIVE_BONUS_PEAK = {
    **PEAK,
    "bonus": {
        "amount": 1.0,
        "threshold_w": 100,
        "calc_mode": "live_power_sensor",
        "bonus_start_time": "18:00:00",
        "bonus_end_time": "21:00:00",
    },
}


def live_entry():
    return make_entry(
        periods=[LIVE_BONUS_PEAK, OFF_PEAK],
        extra_options={"import_power_sensor": POWER},
    )


async def power_at(hass, freezer, when: str, watts: float) -> None:
    freezer.move_to(local(when))
    hass.states.async_set(POWER, str(watts), {"unit_of_measurement": "W"})
    await hass.async_block_till_done()


async def test_restart_inside_window_keeps_earlier_samples(hass: HomeAssistant, freezer):
    freezer.move_to(local("2026-10-15 18:00:00"))
    set_meter(hass, 1000)
    entry = live_entry()
    await setup_entry(hass, entry)

    # Two quiet hours at ~20 W...
    await power_at(hass, freezer, "2026-10-15 18:00:00", 20)
    await power_at(hass, freezer, "2026-10-15 20:00:00", 20.1)

    # ...HA down 20:00-20:30...
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.move_to(local("2026-10-15 20:30:00"))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # ...then a busier half hour at 150 W.
    await power_at(hass, freezer, "2026-10-15 20:30:00", 150)
    await power_at(hass, freezer, "2026-10-15 20:59:59", 150.1)
    await advance_to(hass, freezer, "2026-10-15 21:00:00")

    rt = runtime_of(hass)
    # Whole window: (20 W x 2 h + 150 W x 0.5 h) / 2.5 h = 46 W, under 100 W.
    # On the post-restart half hour alone it would read 150 W and be withheld.
    # The 30 minutes down count for neither.
    assert rt.bonus_earned_today["Peak"] is True


async def test_samples_are_written_on_a_delay(hass: HomeAssistant, freezer, hass_storage):
    freezer.move_to(local("2026-10-15 18:00:00"))
    set_meter(hass, 1000)
    await setup_entry(hass, live_entry())

    await power_at(hass, freezer, "2026-10-15 18:00:00", 20)
    await power_at(hass, freezer, "2026-10-15 18:10:00", 30)

    later = local("2026-10-15 18:12:00")
    freezer.move_to(later)
    async_fire_time_changed(hass, later + timedelta(seconds=1))
    await hass.async_block_till_done()

    saved = stored(hass_storage)["bonus_samples"]["Peak"]
    assert saved["elapsed_seconds"] == pytest.approx(600)
    assert saved["watt_seconds"] == pytest.approx(20 * 600)
    assert "last_time" not in saved


async def test_samples_from_an_earlier_day_are_dropped(hass: HomeAssistant, freezer, hass_storage):
    preload(
        hass_storage,
        last_energy_kwh=1000.0,
        last_energy_source="sensor.grid_import",
        today="2026-10-14",
        bonus_samples={"Peak": {"watt_seconds": 1e6, "elapsed_seconds": 3600, "last_watts": 300}},
        billing_period_start="2026-10-01",
        billing_period_end="2026-10-31",
    )
    freezer.move_to(local("2026-10-15 18:30:00"))
    set_meter(hass, 1000)
    rt = await setup_entry(hass, live_entry())

    assert rt.bonus_samples == {}


async def test_samples_reset_after_settlement(hass: HomeAssistant, freezer, hass_storage):
    freezer.move_to(local("2026-10-15 18:00:00"))
    set_meter(hass, 1000)
    rt = await setup_entry(hass, live_entry())
    await power_at(hass, freezer, "2026-10-15 18:00:00", 20)
    await power_at(hass, freezer, "2026-10-15 19:00:00", 20.1)

    await advance_to(hass, freezer, "2026-10-15 21:00:00")

    assert rt.bonus_earned_today["Peak"] is True
    assert rt.bonus_samples["Peak"].elapsed_seconds == 0
    assert stored(hass_storage)["bonus_samples"]["Peak"]["elapsed_seconds"] == 0
