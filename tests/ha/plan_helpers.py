"""Shared setup for running the integration inside a real Home Assistant.

Everything here goes through the same path a user's install does - config
entry setup, state change events, time-change callbacks, the Store - so it
covers runtime.py, which the engine tests deliberately can't reach.
"""
from __future__ import annotations

from typing import Any

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.tariff_tracker.const import DOMAIN
from custom_components.tariff_tracker.runtime import PlanRuntime

ENTRY_ID = "test_entry"
STORE_KEY = f"{DOMAIN}_{ENTRY_ID}"
SOURCE = "sensor.grid_import"
EXPORT_SOURCE = "sensor.grid_export"

# Mid-morning in the middle of a 30-day bill (2026-10-01 .. 2026-10-31),
# inside the off-peak window below.
START = "2026-10-15 10:00:00"

PEAK = {
    "name": "Peak",
    "start_time": "16:00",
    "end_time": "21:00",
    "days": "all",
    "tiers": [{"limit_kwh": None, "rate": 0.40}],
    "bonus": None,
}
OFF_PEAK = {
    "name": "Off-peak",
    "start_time": "21:00",
    "end_time": "16:00",
    "days": "all",
    "tiers": [{"limit_kwh": 10, "rate": 0.20}, {"limit_kwh": None, "rate": 0.30}],
    "bonus": None,
}
BILLING = {
    "billing_cycle_type": "every_n_days",
    "billing_cycle_days": 30,
    "billing_cycle_start": "2026-10-01",
}


def local(when: str):
    """A wall-clock time string in the configured zone, as an aware datetime."""
    return dt_util.parse_datetime(when).replace(tzinfo=dt_util.get_default_time_zone())


def set_meter(
    hass: HomeAssistant, value: float | str, unit: str = "kWh", entity_id: str = SOURCE
) -> None:
    hass.states.async_set(
        entity_id,
        str(value),
        {"unit_of_measurement": unit, "device_class": "energy", "state_class": "total_increasing"},
    )


def make_entry(
    *,
    periods: list[dict[str, Any]] | None = None,
    export_periods: list[dict[str, Any]] | None = None,
    daily_charge: float = 0.0,
    export_sensor: str | None = None,
    extra_options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    data = {
        "plan_name": "Test Plan",
        "import_energy_sensor": SOURCE,
        "daily_charge": daily_charge,
    }
    if export_sensor:
        data["export_energy_sensor"] = export_sensor
    options = {
        **BILLING,
        "periods": periods if periods is not None else [PEAK, OFF_PEAK],
        **({"export_periods": export_periods} if export_periods else {}),
        **(extra_options or {}),
    }
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        title="Test Plan",
        unique_id="Test Plan",
        data=data,
        options=options,
    )


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> PlanRuntime:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN][entry.entry_id]


def runtime_of(hass: HomeAssistant) -> PlanRuntime:
    return hass.data[DOMAIN][ENTRY_ID]


def stored(hass_storage: dict[str, Any]) -> dict[str, Any]:
    return hass_storage[STORE_KEY]["data"]


def preload(hass_storage: dict[str, Any], **data: Any) -> None:
    """Seed the plan's store as a previous run would have left it."""
    hass_storage[STORE_KEY] = {"version": 1, "key": STORE_KEY, "data": data}


async def advance_to(hass: HomeAssistant, freezer, when: str) -> None:
    """Move the clock and fire any time-change listeners due on the way."""
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    freezer.move_to(local(when))
    async_fire_time_changed(hass, local(when))
    await hass.async_block_till_done()
