"""Tariff Tracker: track cost and conditional bonuses for TOU electricity plans."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_PERIOD_BONUS,
    CONF_PERIOD_NAME,
    CONF_PERIODS,
    CONF_PLAN_NAME,
    DOMAIN,
)
from .runtime import PlanRuntime

PLATFORMS = ["sensor", "binary_sensor", "button"]

# unique_id suffixes minted per import period in sensor.py / binary_sensor.py.
# Kept here (rather than imported) since sensor.py/binary_sensor.py build these
# ids inline - this list just has to stay in sync with them.
_PERIOD_SENSOR_SUFFIXES = ("avg_watts_today", "energy_kwh_today", "window", "rate")
_PERIOD_BONUS_SUFFIXES = (
    "bonus_threshold",  # sensor.py
    "bonus_active_window",  # binary_sensor.py
    "bonus_earned_today",  # binary_sensor.py
)
_ALL_PERIOD_SUFFIXES = _PERIOD_SENSOR_SUFFIXES + _PERIOD_BONUS_SUFFIXES


def _async_cleanup_orphaned_period_entities(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Remove registry entries for periods that no longer exist.

    Deleting or renaming a period in the options flow removes it from the
    periods list, but the platforms only ever *add* entities for periods
    that still exist - nothing tells the entity registry the old ones are
    gone, so they'd otherwise sit there forever as Unavailable.
    """
    periods = entry.options.get(CONF_PERIODS, [])
    valid_ids: set[str] = set()
    for period in periods:
        name = period[CONF_PERIOD_NAME]
        for suffix in _PERIOD_SENSOR_SUFFIXES:
            valid_ids.add(f"{entry.entry_id}_{name}_{suffix}")
        if period.get(CONF_PERIOD_BONUS):
            for suffix in _PERIOD_BONUS_SUFFIXES:
                valid_ids.add(f"{entry.entry_id}_{name}_{suffix}")

    registry = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        unique_id = entity_entry.unique_id
        is_period_entity = any(
            unique_id.endswith(f"_{suffix}") for suffix in _ALL_PERIOD_SUFFIXES
        )
        if is_period_entity and unique_id not in valid_ids:
            registry.async_remove(entity_entry.entity_id)

SERVICE_RESET_COSTS = "reset_costs"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"

RESET_COSTS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional("reset_today", default=True): cv.boolean,
        vol.Optional("reset_month", default=True): cv.boolean,
        vol.Optional("reset_billing_period", default=True): cv.boolean,
        vol.Optional("reset_power_tracking", default=True): cv.boolean,
        vol.Optional("reset_tier_usage", default=False): cv.boolean,
    }
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register domain-wide services."""

    async def _handle_reset_costs(call: ServiceCall) -> None:
        entry_id = call.data[ATTR_CONFIG_ENTRY_ID]
        runtime: PlanRuntime | None = hass.data.get(DOMAIN, {}).get(entry_id)
        if runtime is None:
            raise ServiceValidationError(
                f"Unknown tariff_tracker config entry: {entry_id}"
            )
        await runtime.async_reset_costs(
            reset_today=call.data["reset_today"],
            reset_month=call.data["reset_month"],
            reset_billing_period=call.data["reset_billing_period"],
            reset_power_tracking=call.data["reset_power_tracking"],
            reset_tier_usage=call.data["reset_tier_usage"],
        )

    hass.services.async_register(
        DOMAIN, SERVICE_RESET_COSTS, _handle_reset_costs, schema=RESET_COSTS_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tariff Tracker from a config entry."""
    combined_options = {**entry.data, **entry.options}

    runtime = PlanRuntime(
        hass=hass,
        entry_id=entry.entry_id,
        plan_name=entry.data[CONF_PLAN_NAME],
        options=combined_options,
    )
    await runtime.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime

    _async_cleanup_orphaned_period_entities(hass, entry)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options (billing cycle/periods) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime: PlanRuntime = hass.data[DOMAIN].pop(entry.entry_id)
        runtime.async_unload()
    return unload_ok
