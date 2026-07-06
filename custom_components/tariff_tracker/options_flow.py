"""Options flow for Tariff Tracker: billing cycle + import/export periods."""
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
    CONF_EXPORT_PERIODS,
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
)

ACTION_ADD = "__add_new__"
ACTION_FINISH = "__finish__"

# kind -> (options key, whether this period type supports a no-usage bonus)
_KIND_CONFIG = {
    "import": (CONF_PERIODS, True),
    "export": (CONF_EXPORT_PERIODS, False),
}


class TariffTrackerOptionsFlow(OptionsFlow):
    """Handle options: billing cycle and import/export periods, editable any time."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        # Work on a mutable copy of current options until saved.
        self._options: dict[str, Any] = dict(config_entry.options)
        self._period_lists: dict[str, list[dict[str, Any]]] = {
            kind: list(self._options.get(key, []))
            for kind, (key, _) in _KIND_CONFIG.items()
        }
        self._editing_index: int | None = None
        self._editing_kind: str = "import"

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "billing_cycle",
                "periods_menu",
                "export_periods_menu",
                "finish",
            ],
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
        cycle_start_default = current.get(CONF_BILLING_CYCLE_START)
        cycle_start_key = (
            vol.Optional(CONF_BILLING_CYCLE_START, default=cycle_start_default)
            if cycle_start_default is not None
            else vol.Optional(CONF_BILLING_CYCLE_START)
        )

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
                cycle_start_key: selector.DateSelector(),
            }
        )
        return self.async_show_form(
            step_id="billing_cycle", data_schema=schema, errors=errors
        )

    # ---- Periods list menu (shared by import + export) -------------------

    async def async_step_periods_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return await self._async_periods_menu(user_input, kind="import")

    async def async_step_export_periods_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return await self._async_periods_menu(user_input, kind="export")

    async def _async_periods_menu(
        self, user_input: dict[str, Any] | None, kind: str
    ) -> Any:
        periods = self._period_lists[kind]

        if user_input is not None:
            choice = user_input["action"]
            if choice == ACTION_FINISH:
                return await self.async_step_init()
            self._editing_kind = kind
            if choice == ACTION_ADD:
                self._editing_index = None
            else:
                # choice is the index (as string) of an existing period to edit
                self._editing_index = int(choice)
            return await self.async_step_period_form()

        options = [
            selector.SelectOptionDict(value=str(i), label=f"Edit: {p[CONF_PERIOD_NAME]}")
            for i, p in enumerate(periods)
        ]
        options.append(selector.SelectOptionDict(value=ACTION_ADD, label="Add new period"))
        options.append(selector.SelectOptionDict(value=ACTION_FINISH, label="Done"))

        schema = vol.Schema(
            {
                vol.Required("action", default=ACTION_ADD): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, mode="list")
                )
            }
        )
        step_id = "periods_menu" if kind == "import" else "export_periods_menu"
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            description_placeholders={
                "count": str(len(periods)),
                "names": ", ".join(p[CONF_PERIOD_NAME] for p in periods) or "none yet",
            },
        )

    # ---- Add/edit a single period (shared by import + export) -----------

    async def async_step_period_form(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        kind = self._editing_kind
        _, supports_bonus = _KIND_CONFIG[kind]
        periods = self._period_lists[kind]

        errors: dict[str, str] = {}
        existing = periods[self._editing_index] if self._editing_index is not None else {}
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
                if supports_bonus and user_input.get("bonus_enabled"):
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
                    periods[self._editing_index] = period
                else:
                    periods.append(period)

                options_key, _ = _KIND_CONFIG[kind]
                self._options[options_key] = periods
                return await self._async_periods_menu(None, kind=kind)

        # Optional numeric selectors choke if given an explicit `default=None`
        # (HA tries to coerce it to a float) - only attach a default when a
        # real value exists, so a genuinely blank field stays blank/absent.
        tier1_limit_default = (
            existing_tiers[0].get(CONF_TIER_LIMIT_KWH) if existing_tiers else None
        )
        tier1_limit_key = (
            vol.Optional("tier1_limit_kwh", default=tier1_limit_default)
            if tier1_limit_default is not None
            else vol.Optional("tier1_limit_kwh")
        )

        rate_unit = "$/kWh you're charged" if kind == "import" else "$/kWh you're credited"

        schema_dict: dict[Any, Any] = {
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
            tier1_limit_key: selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, step=0.01, mode="box")
            ),
            vol.Required(
                "tier1_rate",
                default=(existing_tiers[0].get(CONF_TIER_RATE) if existing_tiers else 0.0),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, step=0.001, mode="box", unit_of_measurement=rate_unit
                )
            ),
            vol.Optional(
                "tier2_rate",
                default=(existing_tiers[1].get(CONF_TIER_RATE) if len(existing_tiers) > 1 else 0.0),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, step=0.001, mode="box", unit_of_measurement=rate_unit
                )
            ),
        }

        if supports_bonus:
            schema_dict.update(
                {
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
            step_id="period_form",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={"kind": kind.capitalize()},
        )

    # ---- Finish -----------------------------------------------------------

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return self.async_create_entry(title="", data=self._options)
