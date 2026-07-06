"""Per-config-entry runtime: listens to the source energy/power sensors and
maintains cost + bonus state. Shared by every entity of one plan so there is
a single listener per source sensor, not one per entity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable

from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import tariff_engine as engine
from .const import (
    BONUS_CALC_LIVE_POWER,
    CONF_BILLING_CYCLE_DAYS,
    CONF_BILLING_CYCLE_START,
    CONF_BILLING_CYCLE_TYPE,
    CONF_BONUS_THRESHOLD_W,
    CONF_DAILY_CHARGE,
    CONF_EXPORT_ENERGY_SENSOR,
    CONF_EXPORT_PERIODS,
    CONF_IMPORT_ENERGY_SENSOR,
    CONF_IMPORT_POWER_SENSOR,
    CONF_PERIOD_BONUS,
    CONF_PERIOD_END_TIME,
    CONF_PERIOD_NAME,
    CONF_PERIOD_TIERS,
    CONF_PERIODS,
    BILLING_CYCLE_CALENDAR_MONTH,
    DOMAIN,
)

STORAGE_VERSION = 1


@dataclass
class BonusWindowSample:
    """Accumulator for live-power-sensor bonus averaging within one window."""

    watt_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    last_time: datetime | None = None
    last_watts: float = 0.0

    def sample(self, now: datetime, watts: float) -> None:
        if self.last_time is not None:
            dt = (now - self.last_time).total_seconds()
            self.watt_seconds += self.last_watts * dt
            self.elapsed_seconds += dt
        self.last_time = now
        self.last_watts = watts

    def average(self) -> float:
        if self.elapsed_seconds <= 0:
            return self.last_watts
        return self.watt_seconds / self.elapsed_seconds

    def reset(self) -> None:
        self.watt_seconds = 0.0
        self.elapsed_seconds = 0.0
        self.last_time = None
        self.last_watts = 0.0


@dataclass
class PlanRuntime:
    """Live state for one configured tariff plan."""

    hass: HomeAssistant
    entry_id: str
    plan_name: str
    options: dict[str, Any]

    last_energy_kwh: float | None = None
    tier_usage_today: dict[str, float] = field(default_factory=dict)
    energy_by_period_today: dict[str, float] = field(default_factory=dict)
    bonus_earned_today: dict[str, bool | None] = field(default_factory=dict)
    bonus_samples: dict[str, BonusWindowSample] = field(default_factory=dict)

    last_export_kwh: float | None = None
    export_tier_usage_today: dict[str, float] = field(default_factory=dict)

    cost_today: float = 0.0
    cost_month: float = 0.0
    cost_billing_period: float = 0.0
    bonus_savings_billing_period: float = 0.0

    export_credit_today: float = 0.0
    export_credit_month: float = 0.0
    export_credit_billing_period: float = 0.0

    today: date = field(default_factory=lambda: dt_util.now().date())
    billing_period_start: date | None = None
    billing_period_end: date | None = None

    listeners: list[Callable[[], None]] = field(default_factory=list)
    update_callbacks: list[Callable[[], None]] = field(default_factory=list)
    _store: Store | None = field(default=None, repr=False)
    _unsub_source: Callable[[], None] | None = field(default=None, repr=False)
    _unsub_power: Callable[[], None] | None = field(default=None, repr=False)
    _unsub_export: Callable[[], None] | None = field(default=None, repr=False)

    @property
    def periods(self) -> list[dict[str, Any]]:
        return self.options.get(CONF_PERIODS, [])

    @property
    def export_periods(self) -> list[dict[str, Any]]:
        return self.options.get(CONF_EXPORT_PERIODS, [])

    @property
    def daily_charge(self) -> float:
        return self.options.get(CONF_DAILY_CHARGE, 0.0)

    def current_period(self) -> dict[str, Any] | None:
        return engine.find_active_period(self.periods, dt_util.now())

    def current_rate(self) -> float | None:
        period = self.current_period()
        if period is None:
            return None
        used_today = self.tier_usage_today.get(period[CONF_PERIOD_NAME], 0.0)
        return engine.tier_rate_for_usage(period[CONF_PERIOD_TIERS], used_today)

    def current_export_period(self) -> dict[str, Any] | None:
        return engine.find_active_period(self.export_periods, dt_util.now())

    def current_export_rate(self) -> float | None:
        period = self.current_export_period()
        if period is None:
            return None
        used_today = self.export_tier_usage_today.get(period[CONF_PERIOD_NAME], 0.0)
        return engine.tier_rate_for_usage(period[CONF_PERIOD_TIERS], used_today)

    def days_remaining(self) -> int | None:
        if self.billing_period_end is None:
            return None
        return (self.billing_period_end - dt_util.now().date()).days

    def register_update_callback(self, cb: Callable[[], None]) -> Callable[[], None]:
        self.update_callbacks.append(cb)

        def _remove() -> None:
            self.update_callbacks.remove(cb)

        return _remove

    def _notify(self) -> None:
        for cb in self.update_callbacks:
            cb()

    async def async_setup(self) -> None:
        self._store = Store(
            self.hass, STORAGE_VERSION, f"{DOMAIN}_{self.entry_id}"
        )
        saved = await self._store.async_load()
        if saved:
            self._restore(saved)

        self._recompute_billing_bounds(dt_util.now().date())

        energy_sensor = self.options[CONF_IMPORT_ENERGY_SENSOR]
        self._unsub_source = async_track_state_change_event(
            self.hass, [energy_sensor], self._handle_energy_event
        )

        power_sensor = self.options.get(CONF_IMPORT_POWER_SENSOR)
        if power_sensor:
            self._unsub_power = async_track_state_change_event(
                self.hass, [power_sensor], self._handle_power_event
            )

        export_sensor = self.options.get(CONF_EXPORT_ENERGY_SENSOR)
        if export_sensor:
            self._unsub_export = async_track_state_change_event(
                self.hass, [export_sensor], self._handle_export_energy_event
            )

        # Midnight rollover: reset daily/period accumulators, apply daily charge.
        self.listeners.append(
            async_track_time_change(
                self.hass, self._handle_midnight, hour=0, minute=0, second=0
            )
        )

        # Finalize bonus windows at each period's end time.
        for period in self.periods:
            if not period.get(CONF_PERIOD_BONUS):
                continue
            end_time = engine.parse_time(period[CONF_PERIOD_END_TIME])
            self.listeners.append(
                async_track_time_change(
                    self.hass,
                    self._make_bonus_finalizer(period[CONF_PERIOD_NAME]),
                    hour=end_time.hour,
                    minute=end_time.minute,
                    second=end_time.second,
                )
            )

    def async_unload(self) -> None:
        if self._unsub_source:
            self._unsub_source()
        if self._unsub_power:
            self._unsub_power()
        if self._unsub_export:
            self._unsub_export()
        for unsub in self.listeners:
            unsub()

    # ---- persistence -----------------------------------------------------

    def _restore(self, saved: dict[str, Any]) -> None:
        self.last_energy_kwh = saved.get("last_energy_kwh")
        self.tier_usage_today = saved.get("tier_usage_today", {})
        self.energy_by_period_today = saved.get("energy_by_period_today", {})
        self.bonus_earned_today = saved.get("bonus_earned_today", {})
        self.cost_today = saved.get("cost_today", 0.0)
        self.cost_month = saved.get("cost_month", 0.0)
        self.cost_billing_period = saved.get("cost_billing_period", 0.0)
        self.bonus_savings_billing_period = saved.get("bonus_savings_billing_period", 0.0)
        self.last_export_kwh = saved.get("last_export_kwh")
        self.export_tier_usage_today = saved.get("export_tier_usage_today", {})
        self.export_credit_today = saved.get("export_credit_today", 0.0)
        self.export_credit_month = saved.get("export_credit_month", 0.0)
        self.export_credit_billing_period = saved.get("export_credit_billing_period", 0.0)
        if saved.get("today"):
            self.today = date.fromisoformat(saved["today"])
        if saved.get("billing_period_start"):
            self.billing_period_start = date.fromisoformat(saved["billing_period_start"])
        if saved.get("billing_period_end"):
            self.billing_period_end = date.fromisoformat(saved["billing_period_end"])

    async def _async_save(self) -> None:
        if not self._store:
            return
        await self._store.async_save(
            {
                "last_energy_kwh": self.last_energy_kwh,
                "tier_usage_today": self.tier_usage_today,
                "energy_by_period_today": self.energy_by_period_today,
                "bonus_earned_today": self.bonus_earned_today,
                "cost_today": self.cost_today,
                "cost_month": self.cost_month,
                "cost_billing_period": self.cost_billing_period,
                "bonus_savings_billing_period": self.bonus_savings_billing_period,
                "last_export_kwh": self.last_export_kwh,
                "export_tier_usage_today": self.export_tier_usage_today,
                "export_credit_today": self.export_credit_today,
                "export_credit_month": self.export_credit_month,
                "export_credit_billing_period": self.export_credit_billing_period,
                "today": self.today.isoformat(),
                "billing_period_start": (
                    self.billing_period_start.isoformat()
                    if self.billing_period_start
                    else None
                ),
                "billing_period_end": (
                    self.billing_period_end.isoformat()
                    if self.billing_period_end
                    else None
                ),
            }
        )

    # ---- billing period bookkeeping --------------------------------------

    def _recompute_billing_bounds(self, today: date) -> None:
        cycle_type = self.options.get(
            CONF_BILLING_CYCLE_TYPE, BILLING_CYCLE_CALENDAR_MONTH
        )
        cycle_days = self.options.get(CONF_BILLING_CYCLE_DAYS)
        cycle_start_raw = self.options.get(CONF_BILLING_CYCLE_START)
        cycle_start = (
            date.fromisoformat(cycle_start_raw) if cycle_start_raw else None
        )
        start, end = engine.billing_period_bounds(
            cycle_type, cycle_days, cycle_start, today
        )
        if self.billing_period_start != start:
            self.billing_period_start = start
            self.billing_period_end = end
            self.cost_billing_period = 0.0
            self.bonus_savings_billing_period = 0.0
            self.export_credit_billing_period = 0.0

    # ---- energy sensor handling -------------------------------------------

    @callback
    def _handle_energy_event(self, event: Event) -> None:
        new_state: State | None = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return
        try:
            new_kwh = float(new_state.state)
        except ValueError:
            return

        now = dt_util.now()
        if self.last_energy_kwh is None:
            self.last_energy_kwh = new_kwh
            self._notify()
            return

        delta = new_kwh - self.last_energy_kwh
        if delta < 0:
            # Meter reset (e.g. firmware restart) rather than real usage.
            delta = new_kwh
        self.last_energy_kwh = new_kwh

        if delta > 0:
            self._apply_delta(now, delta)

        self.hass.async_create_task(self._async_save())
        self._notify()

    def _apply_delta(self, now: datetime, delta_kwh: float) -> None:
        period = engine.find_active_period(self.periods, now)
        if period is None:
            return  # configuration gap in period coverage
        name = period[CONF_PERIOD_NAME]
        used_today = self.tier_usage_today.get(name, 0.0)
        cost = engine.cost_of_delta(period, used_today, delta_kwh)

        self.tier_usage_today[name] = used_today + delta_kwh
        self.energy_by_period_today[name] = (
            self.energy_by_period_today.get(name, 0.0) + delta_kwh
        )
        self.cost_today += cost
        self.cost_month += cost
        self.cost_billing_period += cost

    # ---- export sensor handling --------------------------------------

    @callback
    def _handle_export_energy_event(self, event: Event) -> None:
        new_state: State | None = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return
        try:
            new_kwh = float(new_state.state)
        except ValueError:
            return

        now = dt_util.now()
        if self.last_export_kwh is None:
            self.last_export_kwh = new_kwh
            self._notify()
            return

        delta = new_kwh - self.last_export_kwh
        if delta < 0:
            # Meter reset (e.g. firmware restart) rather than real usage.
            delta = new_kwh
        self.last_export_kwh = new_kwh

        if delta > 0:
            self._apply_export_delta(now, delta)

        self.hass.async_create_task(self._async_save())
        self._notify()

    def _apply_export_delta(self, now: datetime, delta_kwh: float) -> None:
        period = engine.find_active_period(self.export_periods, now)
        if period is None:
            return  # no export period configured for this moment
        name = period[CONF_PERIOD_NAME]
        used_today = self.export_tier_usage_today.get(name, 0.0)
        credit = engine.cost_of_delta(period, used_today, delta_kwh)

        self.export_tier_usage_today[name] = used_today + delta_kwh

        # Credit nets straight out of the running cost totals.
        self.cost_today -= credit
        self.cost_month -= credit
        self.cost_billing_period -= credit
        self.export_credit_today += credit
        self.export_credit_month += credit
        self.export_credit_billing_period += credit

    # ---- live power sensor handling (bonus calc_mode=live_power_sensor) --

    @callback
    def _handle_power_event(self, event: Event) -> None:
        new_state: State | None = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return
        try:
            watts = float(new_state.state)
        except ValueError:
            return

        now = dt_util.now()
        active = engine.find_active_period(self.periods, now)
        if active is None:
            return
        bonus = active.get(CONF_PERIOD_BONUS)
        if not bonus or bonus.get("calc_mode") != BONUS_CALC_LIVE_POWER:
            return
        name = active[CONF_PERIOD_NAME]
        sample = self.bonus_samples.setdefault(name, BonusWindowSample())
        sample.sample(now, watts)
        self._notify()

    # ---- bonus finalization -------------------------------------------

    def _make_bonus_finalizer(self, period_name: str) -> Callable[[datetime], None]:
        @callback
        def _finalize(now: datetime) -> None:
            period = next(
                (p for p in self.periods if p[CONF_PERIOD_NAME] == period_name), None
            )
            if period is None:
                return
            bonus = period.get(CONF_PERIOD_BONUS)
            if not bonus:
                return

            threshold = bonus[CONF_BONUS_THRESHOLD_W]
            if bonus.get("calc_mode") == BONUS_CALC_LIVE_POWER and period_name in self.bonus_samples:
                avg_w = self.bonus_samples[period_name].average()
            else:
                start_t = engine.parse_time(period[CONF_PERIOD_START_TIME])
                end_t = engine.parse_time(period[CONF_PERIOD_END_TIME])
                window_hours = (
                    datetime.combine(date.min, end_t)
                    - datetime.combine(date.min, start_t)
                ).total_seconds() / 3600
                energy = self.energy_by_period_today.get(period_name, 0.0)
                avg_w = engine.avg_watts_from_energy(energy, window_hours)

            earned = avg_w < threshold
            self.bonus_earned_today[period_name] = earned
            if earned:
                self.cost_billing_period -= bonus["amount"]
                self.bonus_savings_billing_period += bonus["amount"]

            if period_name in self.bonus_samples:
                self.bonus_samples[period_name].reset()
            self.energy_by_period_today.pop(period_name, None)

            self.hass.async_create_task(self._async_save())
            self._notify()

        return _finalize

    # ---- daily/monthly/billing-period rollover -----------------------

    @callback
    def _handle_midnight(self, now: datetime) -> None:
        today = now.date()
        self.tier_usage_today = {}
        # A period whose window is still open right at midnight (e.g. an
        # overnight 22:00-06:00 window) needs its running energy total kept
        # until its own finalizer closes it out later this morning - only
        # clear totals for periods that are NOT mid-window right now.
        self.energy_by_period_today = {
            name: total
            for name, total in self.energy_by_period_today.items()
            if any(
                p[CONF_PERIOD_NAME] == name and engine.period_contains_time(p, now)
                for p in self.periods
            )
        }
        self.bonus_earned_today = {}
        self.export_tier_usage_today = {}
        self.export_credit_today = 0.0
        self.cost_today = self.daily_charge
        self.cost_billing_period += self.daily_charge

        if today.month != self.today.month:
            self.cost_month = 0.0
            self.export_credit_month = 0.0
        self.cost_month += self.daily_charge

        self._recompute_billing_bounds(today)
        self.today = today

        self.hass.async_create_task(self._async_save())
        self._notify()
