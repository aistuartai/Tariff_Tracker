"""Options flow for Tariff Tracker: billing cycle + period management."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.helpers import selector

from .const import (
    BILLING_CYCLE_CALENDAR_MONTH,
    BILLING_CYCLE_EVERY_N_DAYS,
    BONUS_CALC_ENERGY_DELTA,
    BONUS_CALC_LIVE_POWER,
    CONF_BILLING_CYCLE_DAYS,
    CONF_BILLING_CYCLE_START,
    CONF_BILLING_CYCLE_TYPE,
    CONF_BONUS_AMOUNT,
    CONF_BONUS_CALC_MODE,
    CONF_BONUS_THRESHOLD_W,
    CONF_PERIOD_BONUS,
    CONF_PERIOD_DAYS,
    CONF_PERIOD_END_TIME,
    CONF_PERIOD_NAME,
    CONF_PERIOD_START_TIME,
    CONF_PERIOD_TIERS,
    CONF_PERIODS,
    CONF_TIER_LIMIT_KWH,
    CONF_TIER_RATE,
    DAYS_ALL,
    DAYS_WEEKDAYS,
    DAYS_WEEKENDS,
    DOMAIN,
)

ACTION_ADD = "__add_new__"
ACTION_FINISH = "__finish__"


class TariffTrackerOptionsFlow(OptionsFlow):
    """Handle options: billing cycle and periods, editable any time."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        # Work on a mutable copy of current options until saved.
        self._options: dict[str, Any] = dict(config_entry.options)
        self._periods: list[dict[str, Any]] = list(
            self._options.get(CONF_PERIODS, [])
        )
        self._editing_index: int | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return self.async_show_menu(
            step_id="init",
            menu_options=["billing_cycle", "periods_menu", "finish"],
        )

    # ---- Billing cycle -------------------------------------------------

    async def async_step_billing_cycle(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        errors: dict[str, str] = {}

        if user_input is not None:
            if (
                user_input[CONF_BILLING_CYCLE_TYPE] == BILLING_CYCLE_EVERY_N_DAYS
                and not user_input.get(CONF_BILLING_CYCLE_START)
            ):
                errors["base"] = "start_date_required"
            else:
                self._options[CONF_BILLING_CYCLE_TYPE] = user_input[
                    CONF_BILLING_CYCLE_TYPE
                ]
                self._options[CONF_BILLING_CYCLE_DAYS] = user_input.get(
                    CONF_BILLING_CYCLE_DAYS
                )
                self._options[CONF_BILLING_CYCLE_START] = user_input.get(
                    CONF_BILLING_CYCLE_START
                )
                return await self.async_step_init()

        current = self._options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_BILLING_CYCLE_TYPE,
                    default=current.get(
                        CONF_BILLING_CYCLE_TYPE, BILLING_CYCLE_CALENDAR_MONTH
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            BILLING_CYCLE_CALENDAR_MONTH,
                            BILLING_CYCLE_EVERY_N_DAYS,
                        ],
                        translation_key="billing_cycle_type",
                    )
                ),
                vol.Optional(
                    CONF_BILLING_CYCLE_DAYS,
                    default=current.get(CONF_BILLING_CYCLE_DAYS, 28),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=365, step=1, mode="box")
                ),
                vol.Optional(
                    CONF_BILLING_CYCLE_START,
                    default=current.get(CONF_BILLING_CYCLE_START),
                ): selector.DateSelector(),
            }
        )
        return self.async_show_form(
            step_id="billing_cycle", data_schema=schema, errors=errors
        )

    # ---- Periods list menu ----------------------------------------------

    async def async_step_periods_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            choice = user_input["action"]
            if choice == ACTION_FINISH:
                return await self.async_step_init()
            if choice == ACTION_ADD:
                self._editing_index = None
                return await self.async_step_period_form()
            # choice is the index (as string) of an existing period to edit
            self._editing_index = int(choice)
            return await self.async_step_period_form()

        options = [
            selector.SelectOptionDict(value=str(i), label=f"Edit: {p[CONF_PERIOD_NAME]}")
            for i, p in enumerate(self._periods)
        ]
        options.append(selector.SelectOptionDict(value=ACTION_ADD, label="Add new period"))
        options.append(selector.SelectOptionDict(value=ACTION_FINISH, label="Done with periods"))

        schema = vol.Schema(
            {
                vol.Required("action", default=ACTION_ADD): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, mode="list")
                )
            }
        )
        return self.async_show_form(
            step_id="periods_menu",
            data_schema=schema,
            description_placeholders={
                "count": str(len(self._periods)),
                "names": ", ".join(p[CONF_PERIOD_NAME] for p in self._periods) or "none yet",
            },
        )

    # ---- Add/edit a single period ---------------------------------------

    async def async_step_period_form(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        errors: dict[str, str] = {}
        existing = (
            self._periods[self._editing_index]
            if self._editing_index is not None
            else {}
        )
        existing_tiers = existing.get(CONF_PERIOD_TIERS, [])
        existing_bonus = existing.get(CONF_PERIOD_BONUS) or {}

        if user_input is not None:
            if user_input[CONF_PERIOD_START_TIME] == user_input[CONF_PERIOD_END_TIME]:
                errors["base"] = "start_end_equal"
            else:
                tiers = [
                    {
                        CONF_TIER_LIMIT_KWH: user_input.get("tier1_limit_kwh"),
                        CONF_TIER_RATE: user_input["tier1_rate"],
                    }
                ]
                if user_input.get("tier1_limit_kwh"):
                    tiers.append(
                        {
                            CONF_TIER_LIMIT_KWH: None,
                            CONF_TIER_RATE: user_input["tier2_rate"],
                        }
                    )

                bonus = None
                if user_input.get("bonus_enabled"):
                    bonus = {
                        CONF_BONUS_AMOUNT: user_input["bonus_amount"],
                        CONF_BONUS_THRESHOLD_W: user_input["bonus_threshold_w"],
                        CONF_BONUS_CALC_MODE: user_input["bonus_calc_mode"],
                    }

                period = {
                    CONF_PERIOD_NAME: user_input[CONF_PERIOD_NAME],
                    CONF_PERIOD_START_TIME: user_input[CONF_PERIOD_START_TIME],
                    CONF_PERIOD_END_TIME: user_input[CONF_PERIOD_END_TIME],
                    CONF_PERIOD_DAYS: user_input[CONF_PERIOD_DAYS],
                    CONF_PERIOD_TIERS: tiers,
                    CONF_PERIOD_BONUS: bonus,
                }

                if self._editing_index is not None:
                    self._periods[self._editing_index] = period
                else:
                    self._periods.append(period)

                self._options[CONF_PERIODS] = self._periods
                return await self.async_step_periods_menu()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PERIOD_NAME, default=existing.get(CONF_PERIOD_NAME, "")
                ): str,
                vol.Required(
                    CONF_PERIOD_START_TIME,
                    default=existing.get(CONF_PERIOD_START_TIME),
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_PERIOD_END_TIME, default=existing.get(CONF_PERIOD_END_TIME)
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_PERIOD_DAYS, default=existing.get(CONF_PERIOD_DAYS, DAYS_ALL)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[DAYS_ALL, DAYS_WEEKDAYS, DAYS_WEEKENDS],
                        translation_key="period_days",
                    )
                ),
                vol.Optional(
                    "tier1_limit_kwh",
                    default=(existing_tiers[0].get(CONF_TIER_LIMIT_KWH) if existing_tiers else None),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, step=0.01, mode="box")
                ),
                vol.Required(
                    "tier1_rate",
                    default=(existing_tiers[0].get(CONF_TIER_RATE) if existing_tiers else 0.0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, step=0.0001, mode="box")
                ),
                vol.Optional(
                    "tier2_rate",
                    default=(existing_tiers[1].get(CONF_TIER_RATE) if len(existing_tiers) > 1 else 0.0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, step=0.0001, mode="box")
                ),
                vol.Required(
                    "bonus_enabled", default=bool(existing_bonus)
                ): selector.BooleanSelector(),
                vol.Optional(
                    "bonus_amount", default=existing_bonus.get(CONF_BONUS_AMOUNT, 1.0)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, step=0.01, mode="box")
                ),
                vol.Optional(
                    "bonus_threshold_w",
                    default=existing_bonus.get(CONF_BONUS_THRESHOLD_W, 60),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, step=1, mode="box")
                ),
                vol.Optional(
                    "bonus_calc_mode",
                    default=existing_bonus.get(
                        CONF_BONUS_CALC_MODE, BONUS_CALC_ENERGY_DELTA
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[BONUS_CALC_ENERGY_DELTA, BONUS_CALC_LIVE_POWER],
                        translation_key="bonus_calc_mode",
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="period_form", data_schema=schema, errors=errors
        )

    # ---- Finish -----------------------------------------------------------

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return self.async_create_entry(title="", data=self._options)
