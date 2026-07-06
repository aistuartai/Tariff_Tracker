"""Config flow for Tariff Tracker."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigEntry, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DAILY_CHARGE,
    CONF_IMPORT_ENERGY_SENSOR,
    CONF_IMPORT_POWER_SENSOR,
    CONF_PLAN_NAME,
    DEFAULT_DAILY_CHARGE,
    DOMAIN,
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PLAN_NAME): str,
        vol.Required(CONF_IMPORT_ENERGY_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="energy")
        ),
        vol.Optional(CONF_IMPORT_POWER_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="power")
        ),
        vol.Required(
            CONF_DAILY_CHARGE, default=DEFAULT_DAILY_CHARGE
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, step=0.001, mode="box", unit_of_measurement="$/day")
        ),
    }
)


class TariffTrackerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tariff Tracker.

    Billing cycle and period setup happen in the options flow immediately
    after creation, so there is a single place to maintain that logic for
    both initial setup and later edits.
    """

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Handle the initial step: plan identity and cost inputs."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_PLAN_NAME])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input[CONF_PLAN_NAME],
                data=user_input,
                options={},
            )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        from .options_flow import TariffTrackerOptionsFlow

        return TariffTrackerOptionsFlow(config_entry)
