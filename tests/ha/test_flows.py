"""Config and options flows, driven the way the UI drives them."""
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.tariff_tracker.const import DOMAIN

from plan_helpers import SOURCE, make_entry, set_meter, setup_entry


async def test_config_flow_creates_entry(hass: HomeAssistant):
    set_meter(hass, 1000)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"plan_name": "My Plan", "import_energy_sensor": SOURCE, "daily_charge": 1.2},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["import_energy_sensor"] == SOURCE


async def _open_period_form(hass, entry, action="__add_new__"):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "periods_menu"}
    )
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"action": action}
    )


async def _finish(hass, flow_id):
    result = await hass.config_entries.options.async_configure(flow_id, {"action": "__finish__"})
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.options.async_configure(flow_id, {"next_step_id": "finish"})


async def test_period_form_saves_pooled_tier_reset(hass: HomeAssistant):
    set_meter(hass, 1000)
    entry = make_entry()
    await setup_entry(hass, entry)

    result = await _open_period_form(hass, entry)
    assert result["step_id"] == "period_form"
    assert result["description_placeholders"]["unit"] == "kWh"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "name": "Solar soak",
            "start_time": "11:00:00",
            "end_time": "14:00:00",
            "days": "all",
            "tier1_limit_kwh": 15,
            "tier_reset": "billing_period",
            "tier1_rate": 0.10,
            "tier2_rate": 0.25,
            "bonus_enabled": False,
        },
    )
    result = await _finish(hass, result["flow_id"])
    assert result["type"] is FlowResultType.CREATE_ENTRY

    saved = next(p for p in entry.options["periods"] if p["name"] == "Solar soak")
    assert saved["tier_reset"] == "billing_period"
    assert saved["tiers"] == [
        {"limit_kwh": 15, "rate": 0.10},
        {"limit_kwh": None, "rate": 0.25},
    ]


async def test_period_form_shows_gas_unit(hass: HomeAssistant):
    set_meter(hass, 5000, unit="MJ")
    entry = make_entry()
    await setup_entry(hass, entry)

    result = await _open_period_form(hass, entry, action="0")
    assert result["description_placeholders"]["unit"] == "MJ"


async def test_existing_period_without_tier_reset_defaults_to_daily(hass: HomeAssistant):
    set_meter(hass, 1000)
    entry = make_entry()
    await setup_entry(hass, entry)

    result = await _open_period_form(hass, entry, action="1")  # Off-peak
    schema = result["data_schema"].schema
    tier_reset = next(k for k in schema if k == "tier_reset")
    assert tier_reset.default() == "daily"


async def test_source_sensor_step_repoints_the_plan(hass: HomeAssistant):
    set_meter(hass, 1000)
    set_meter(hass, 2000, entity_id="sensor.better_meter")
    entry = make_entry()
    await setup_entry(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "source_sensors"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"import_energy_sensor": "sensor.better_meter"}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    await hass.async_block_till_done()

    assert entry.options["import_energy_sensor"] == "sensor.better_meter"
    assert entry.data["import_energy_sensor"] == SOURCE
    assert hass.data[DOMAIN][entry.entry_id].last_energy_kwh == 2000
