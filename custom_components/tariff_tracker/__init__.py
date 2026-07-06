"""Tariff Tracker: track cost and conditional bonuses for TOU electricity plans."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_PLAN_NAME, DOMAIN
from .runtime import PlanRuntime

PLATFORMS = ["sensor", "binary_sensor"]


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
