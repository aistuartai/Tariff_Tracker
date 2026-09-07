"""Options flow for Tariff Tracker: billing cycle + import/export periods."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.helpers import selector

from . import tariff_engine as engine
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
    CONF_BONUS_END_TIME,
    CONF_BONUS_START_TIME,
    CONF_BONUS_THRESHOLD_W,
    CONF_DAILY_CHARGE,
    CONF_EXPORT_PERIODS,
    CONF_PERIOD_BONUS,
    CONF_PERIOD_DAYS,
    CONF_PERIOD_END_TIME,
    CONF_PERIOD_NAME,
    CONF_PERIOD_START_TIME,
    CONF_PERIOD_TIERS,
    CONF_PERIOD_WINDOWS,
    CONF_PERIODS,
    CONF_TIER_LIMIT_KWH,
    CONF_TIER_RATE,
    DAYS_ALL,
    DAYS_WEEKDAYS,
    DAYS_WEEKENDS,
)

# How many windows one period's form exposes. Window 1 is required; the rest
# are optional pairs. A period made of several disjoint windows (a shoulder
# band split by peak and off-peak blocks, say) needs more than one, but in
# practice never many - raising this only means adding form fields.
MAX_PERIOD_WINDOWS = 3


def _window_field_names(index: int) -> tuple[str, str]:
    """Form field names for window `index` (0-based).

    Window 0 reuses the period's own start_time/end_time fields so existing
    configs, translations and muscle memory are unchanged.
    """
    if index == 0:
        return CONF_PERIOD_START_TIME, CONF_PERIOD_END_TIME
    return f"window{index + 1}_start_time", f"window{index + 1}_end_time"


def _collect_windows(
    user_input: dict[str, Any]
) -> tuple[list[dict[str, str]], str | None]:
    """Build the window list from submitted form fields.

    Returns (windows, error_key). Blank optional pairs are skipped; a pair
    with only one half filled in is an error, as is a zero-length window or
    two windows that overlap.
    """
    windows: list[dict[str, str]] = []
    for i in range(MAX_PERIOD_WINDOWS):
        start_field, end_field = _window_field_names(i)
        start = user_input.get(start_field)
        end = user_input.get(end_field)
        if not start and not end:
            continue
        if not start or not end:
            return [], "window_incomplete"
        if start == end:
            return [], "start_end_equal"
        windows.append({CONF_PERIOD_START_TIME: start, CONF_PERIOD_END_TIME: end})

    if not windows:
        return [], "start_end_equal"
    if engine.windows_overlap(
        [
            (
                engine.parse_time(w[CONF_PERIOD_START_TIME]),
                engine.parse_time(w[CONF_PERIOD_END_TIME]),
            )
            for w in windows
        ]
    ):
        return [], "windows_overlap"
    return windows, None


ACTION_ADD = "__add_new__"
ACTION_FINISH = "__finish__"
ACTION_DELETE_PREFIX = "__delete__"

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
                "plan_settings",
                "billing_cycle",
                "periods_menu",
                "export_periods_menu",
                "finish",
            ],
        )

    # ---- Plan settings (daily charge) -----------------------------------

    async def async_step_plan_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            self._options[CONF_DAILY_CHARGE] = user_input[CONF_DAILY_CHARGE]
            return await self.async_step_init()

        current_daily_charge = self._options.get(
            CONF_DAILY_CHARGE, self._entry.data.get(CONF_DAILY_CHARGE, 0.0)
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DAILY_CHARGE, default=current_daily_charge
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, step=0.001, mode="box", unit_of_measurement="$/day"
                    )
                ),
            }
        )
        return self.async_show_form(step_id="plan_settings", data_schema=schema)

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
            if choice.startswith(ACTION_DELETE_PREFIX):
                index = int(choice[len(ACTION_DELETE_PREFIX):])
                del periods[index]
                options_key, _ = _KIND_CONFIG[kind]
                self._options[options_key] = periods
                return await self._async_periods_menu(None, kind=kind)
            self._editing_kind = kind
            if choice == ACTION_ADD:
                self._editing_index = None
            else:
                # choice is the index (as string) of an existing period to edit
                self._editing_index = int(choice)
            return await self.async_step_period_form()

        options = []
        for i, p in enumerate(periods):
            options.append(
                selector.SelectOptionDict(value=str(i), label=f"Edit: {p[CONF_PERIOD_NAME]}")
            )
            options.append(
                selector.SelectOptionDict(
                    value=f"{ACTION_DELETE_PREFIX}{i}",
                    label=f"Delete: {p[CONF_PERIOD_NAME]}",
                )
            )
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
            windows, window_error = _collect_windows(user_input)
            if window_error:
                errors["base"] = window_error
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
                        CONF_BONUS_START_TIME: user_input.get("bonus_start_time"),
                        CONF_BONUS_END_TIME: user_input.get("bonus_end_time"),
                    }

                period = {
                    CONF_PERIOD_NAME: user_input[CONF_PERIOD_NAME],
                    # start_time/end_time mirror the first window. The engine
                    # reads CONF_PERIOD_WINDOWS, but keeping these in sync
                    # means periods saved here still make sense to anything
                    # reading the original single-window keys.
                    CONF_PERIOD_START_TIME: windows[0][CONF_PERIOD_START_TIME],
                    CONF_PERIOD_END_TIME: windows[0][CONF_PERIOD_END_TIME],
                    CONF_PERIOD_WINDOWS: windows,
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

        # Existing windows, padded so window 1 always has a default to show
        # (blank for a brand-new period). Periods saved before multi-window
        # support have no window list, so fall back to their start/end pair.
        existing_windows = list(existing.get(CONF_PERIOD_WINDOWS) or [])
        if not existing_windows:
            existing_windows = [
                {
                    CONF_PERIOD_START_TIME: existing.get(CONF_PERIOD_START_TIME),
                    CONF_PERIOD_END_TIME: existing.get(CONF_PERIOD_END_TIME),
                }
            ]
        while len(existing_windows) < MAX_PERIOD_WINDOWS:
            existing_windows.append({})

        # Optional extra windows. Time selectors are only given a default
        # when a real value exists - an explicit default of None makes the
        # selector choke, the same way the optional number selectors do.
        window_fields: dict[Any, Any] = {}
        for i in range(1, MAX_PERIOD_WINDOWS):
            start_field, end_field = _window_field_names(i)
            for field_name, conf_key in (
                (start_field, CONF_PERIOD_START_TIME),
                (end_field, CONF_PERIOD_END_TIME),
            ):
                value = existing_windows[i].get(conf_key)
                key = (
                    vol.Optional(field_name, default=value)
                    if value is not None
                    else vol.Optional(field_name)
                )
                window_fields[key] = selector.TimeSelector()

        rate_unit = "$/kWh you're charged" if kind == "import" else "$/kWh you're credited"

        schema_dict: dict[Any, Any] = {
            vol.Required(
                CONF_PERIOD_NAME, default=existing.get(CONF_PERIOD_NAME, "")
            ): str,
            vol.Required(
                CONF_PERIOD_START_TIME,
                default=existing_windows[0].get(CONF_PERIOD_START_TIME),
            ): selector.TimeSelector(),
            vol.Required(
                CONF_PERIOD_END_TIME,
                default=existing_windows[0].get(CONF_PERIOD_END_TIME),
            ): selector.TimeSelector(),
            **window_fields,
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
            bonus_start_default = existing_bonus.get(CONF_BONUS_START_TIME)
            bonus_start_key = (
                vol.Optional(CONF_BONUS_START_TIME, default=bonus_start_default)
                if bonus_start_default is not None
                else vol.Optional(CONF_BONUS_START_TIME)
            )
            bonus_end_default = existing_bonus.get(CONF_BONUS_END_TIME)
            bonus_end_key = (
                vol.Optional(CONF_BONUS_END_TIME, default=bonus_end_default)
                if bonus_end_default is not None
                else vol.Optional(CONF_BONUS_END_TIME)
            )
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
                    # Optional sub-window the bonus is evaluated over, if
                    # narrower than the period itself (e.g. a 6-9pm bonus
                    # window inside a 4-11pm peak period). Leave blank to
                    # use the period's own start/end time.
                    bonus_start_key: selector.TimeSelector(),
                    bonus_end_key: selector.TimeSelector(),
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
