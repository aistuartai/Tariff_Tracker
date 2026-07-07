"""Tariff Tracker: track cost and conditional bonuses for TOU electricity plans."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import CONF_PLAN_NAME, DOMAIN
from .runtime import PlanRuntime

PLATFORMS = ["sensor", "binary_sensor", "button"]

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
