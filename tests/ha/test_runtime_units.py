"""Plan units follow the source sensor (issue #1)."""
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from plan_helpers import make_entry, set_meter, setup_entry, stored

ENERGY_TODAY = "sensor.test_plan_off_peak_energy_today"
RATE = "sensor.test_plan_off_peak_rate"
CURRENT_RATE = "sensor.test_plan_current_rate"


async def test_kwh_source_labels_kwh(hass: HomeAssistant, hass_storage):
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry())

    assert rt.energy_unit == "kWh"
    assert stored(hass_storage)["energy_source_unit"] == "kWh"
    assert hass.states.get(ENERGY_TODAY).attributes["unit_of_measurement"] == "kWh"
    currency = hass.config.currency
    assert hass.states.get(RATE).attributes["unit_of_measurement"] == f"{currency}/kWh"


async def test_wh_source_is_billed_in_kwh(hass: HomeAssistant):
    set_meter(hass, 1_000_000, unit="Wh")
    rt = await setup_entry(hass, make_entry())

    set_meter(hass, 1_002_500, unit="Wh")
    await hass.async_block_till_done()

    assert rt.energy_unit == "kWh"
    assert rt.period_energy_kwh_today["Off-peak"] == pytest.approx(2.5)
    assert rt.cost_today == pytest.approx(2.5 * 0.20)
    assert hass.states.get(ENERGY_TODAY).state == "2.5"


async def test_mj_gas_source_labels_mj_and_bills_raw(hass: HomeAssistant):
    set_meter(hass, 5000, unit="MJ")
    rt = await setup_entry(hass, make_entry())

    set_meter(hass, 5003, unit="MJ")
    await hass.async_block_till_done()

    currency = hass.config.currency
    assert rt.energy_unit == "MJ"
    assert rt.cost_today == pytest.approx(3 * 0.20)
    assert hass.states.get(ENERGY_TODAY).attributes["unit_of_measurement"] == "MJ"
    assert hass.states.get(RATE).attributes["unit_of_measurement"] == f"{currency}/MJ"
    assert hass.states.get(CURRENT_RATE).attributes["unit_of_measurement"] == f"{currency}/MJ"


async def test_mj_average_power_is_real_watts(hass: HomeAssistant, freezer):
    # Peak runs 16:00-21:00. 3.6 MJ in its first hour is a steady 1 kW.
    from plan_helpers import local

    freezer.move_to(local("2026-10-15 16:00:00"))
    set_meter(hass, 5000, unit="MJ")
    rt = await setup_entry(hass, make_entry())

    freezer.move_to(local("2026-10-15 17:00:00"))
    set_meter(hass, 5003.6, unit="MJ")
    await hass.async_block_till_done()

    assert rt.current_period_avg_watts("Peak") == pytest.approx(1000.0)


async def test_unit_change_restarts_baseline_instead_of_booking_a_reset(hass: HomeAssistant, hass_storage):
    set_meter(hass, 1000)
    rt = await setup_entry(hass, make_entry())

    # Same meter, now reporting in Wh: 1000.5 kWh.
    set_meter(hass, 1_000_500, unit="Wh")
    await hass.async_block_till_done()
    assert rt.cost_today == 0
    assert rt.energy_source_unit == "Wh"
    assert stored(hass_storage)["energy_source_unit"] == "Wh"

    set_meter(hass, 1_001_500, unit="Wh")
    await hass.async_block_till_done()
    assert rt.cost_today == pytest.approx(1 * 0.20)


async def test_unit_comes_from_registry_while_source_is_unknown(hass: HomeAssistant):
    # Cold start: the Zigbee meter is `unknown` with no attributes yet, but
    # the entity registry remembers the unit it last reported.
    registry = er.async_get(hass)
    reg = registry.async_get_or_create(
        "sensor", "zigbee", "gas_meter", suggested_object_id="grid_import",
        unit_of_measurement="MJ",
    )
    assert reg.entity_id == "sensor.grid_import"
    hass.states.async_set(reg.entity_id, "unknown", {})

    rt = await setup_entry(hass, make_entry())
    assert rt.energy_unit == "MJ"
