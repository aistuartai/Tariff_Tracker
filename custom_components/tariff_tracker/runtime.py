"""Per-config-entry runtime: listens to the source energy/power sensors and
maintains cost + bonus state. Shared by every entity of one plan so there is
a single listener per source sensor, not one per entity.
"""
from __future__ import annotations

import logging
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
    CONF_BONUS_END_TIME,
    CONF_BONUS_START_TIME,
    CONF_BONUS_THRESHOLD_W,
    CONF_DAILY_CHARGE,
    CONF_EXPORT_ENERGY_SENSOR,
    CONF_EXPORT_PERIODS,
    CONF_IMPORT_ENERGY_SENSOR,
    CONF_IMPORT_POWER_SENSOR,
    CONF_PERIOD_BONUS,
    CONF_PERIOD_DAYS,
    CONF_PERIOD_END_TIME,
    CONF_PERIOD_NAME,
    CONF_PERIOD_START_TIME,
    CONF_PERIOD_TIERS,
    CONF_PERIODS,
    BILLING_CYCLE_CALENDAR_MONTH,
    DAYS_ALL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

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
    # ISO date string per period name, recording the last day that period's
    # bonus was finalized. Two jobs: stop the finalizer crediting the same
    # day twice (a DST fall-back repeats the hour its callback is scheduled
    # in), and let setup settle a bonus whose end time passed while Home
    # Assistant was down.
    bonus_finalized_for: dict[str, str] = field(default_factory=dict)

    last_export_kwh: float | None = None
    export_tier_usage_today: dict[str, float] = field(default_factory=dict)

    period_started_at: dict[str, datetime] = field(default_factory=dict)
    # Seconds a period has been open so far today, summed across every window
    # that has already closed. A period can have several disjoint windows, so
    # "how long has this been open today" is not simply now-minus-start: with
    # one start marker per window, the marker for window 2 would otherwise
    # discard window 1's elapsed time and spike the average.
    period_open_seconds_today: dict[str, float] = field(default_factory=dict)
    period_avg_watts_today: dict[str, float] = field(default_factory=dict)
    # Independent running total of kWh used in each period today. Separate
    # from energy_by_period_today (which the avg-watts calc owns) so this
    # can't interfere with that calc; resets at midnight, not at the
    # period's own end time, so it holds its value for the rest of the day
    # once the window closes.
    period_energy_kwh_today: dict[str, float] = field(default_factory=dict)
    # Running total kWh used in each period across the current billing
    # period. Resets only when the billing period itself rolls over (see
    # _recompute_billing_bounds), unlike period_energy_kwh_today which
    # resets nightly.
    period_energy_kwh_billing_period: dict[str, float] = field(default_factory=dict)
    export_period_energy_kwh_billing_period: dict[str, float] = field(default_factory=dict)
    # All-time running total kWh per period. Never reset by any rollover or
    # manual reset - a lifetime counter.
    period_energy_kwh_total: dict[str, float] = field(default_factory=dict)
    export_period_energy_kwh_total: dict[str, float] = field(default_factory=dict)

    cost_today: float = 0.0
    cost_month: float = 0.0
    cost_billing_period: float = 0.0
    bonus_savings_billing_period: float = 0.0
    # Number of days in the current billing period whose bonus was earned.
    # Incremented by the finalizer, so it counts settled days directly
    # rather than inferring them from binary sensor state changes - a
    # history_stats count over the bonus binary sensor double-counts any
    # day where the integration is reloaded after the bonus is settled,
    # because re-adding the entity records a second entry into "on".
    bonus_days_earned_billing_period: int = 0

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

    def period_open_hours_so_far(self, period_name: str, now: datetime) -> float:
        """Hours this period has been open today, including the window that
        is open right now, if any."""
        seconds = self.period_open_seconds_today.get(period_name, 0.0)
        started = self.period_started_at.get(period_name)
        if started is not None:
            seconds += max((now - started).total_seconds(), 0.0)
        return seconds / 3600

    def current_period_avg_watts(self, period_name: str) -> float | None:
        period = next(
            (p for p in self.periods if p[CONF_PERIOD_NAME] == period_name), None
        )
        if period is None:
            return None
        now = dt_util.now()
        if engine.period_contains_time(period, now):
            elapsed_hours = self.period_open_hours_so_far(period_name, now)
            if elapsed_hours <= 0:
                return None
            # period_energy_kwh_today is the day's full total for this period
            # and survives each window closing, so a multi-window period
            # averages across all of today's windows rather than restarting
            # from zero when a later window opens.
            energy = self.period_energy_kwh_today.get(period_name, 0.0)
            return engine.avg_watts_from_energy(energy, elapsed_hours)
        return self.period_avg_watts_today.get(period_name)

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

    @property
    def has_bonus(self) -> bool:
        return any(p.get(CONF_PERIOD_BONUS) for p in self.periods)

    def bonus_days_elapsed(self) -> int | None:
        """Whole days of the billing period that have finished.

        Today is excluded: its bonus windows may not have closed yet, so
        counting it would drag the success rate down for most of the day.
        """
        if self.billing_period_start is None:
            return None
        return max((dt_util.now().date() - self.billing_period_start).days, 0)

    def bonus_day_percentage(self) -> float | None:
        elapsed = self.bonus_days_elapsed()
        if not elapsed:
            return None
        return round(self.bonus_days_earned_billing_period / elapsed * 100, 1)

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

        now = dt_util.now()
        today = now.date()
        # Whether this setup is resuming a day already in progress. A first
        # ever run has no history to settle, and a run on a later day has
        # had its inputs cleared by _recompute_daily_bounds below - in
        # either case a bonus catch-up would credit against zero usage and
        # hand out a bonus that was never earned.
        resuming_same_day = bool(saved) and self.today == today

        self._recompute_billing_bounds(today)
        self._recompute_month_bounds(today)
        self._recompute_daily_bounds(today)
        if resuming_same_day and self._catch_up_bonuses(now):
            await self._async_save()

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

        # Finalize bonus windows at the bonus's own end time if it defines a
        # sub-window narrower than the enclosing period, else the period's end time.
        for period in self.periods:
            bonus = period.get(CONF_PERIOD_BONUS)
            if not bonus:
                continue
            end_time = engine.parse_time(
                bonus.get(CONF_BONUS_END_TIME) or period[CONF_PERIOD_END_TIME]
            )
            self.listeners.append(
                async_track_time_change(
                    self.hass,
                    self._make_bonus_finalizer(period[CONF_PERIOD_NAME]),
                    hour=end_time.hour,
                    minute=end_time.minute,
                    second=end_time.second,
                )
            )

        # Mark window-open time and finalize avg import power for every
        # period. A period can be made of several disjoint windows, so this
        # registers one marker/finalizer pair per window, not per period.
        for period in self.periods:
            name = period[CONF_PERIOD_NAME]
            for start_time, end_time in engine.period_windows(period):
                self.listeners.append(
                    async_track_time_change(
                        self.hass,
                        self._make_period_start_marker(name),
                        hour=start_time.hour,
                        minute=start_time.minute,
                        second=start_time.second,
                    )
                )
                self.listeners.append(
                    async_track_time_change(
                        self.hass,
                        self._make_period_avg_finalizer(name),
                        hour=end_time.hour,
                        minute=end_time.minute,
                        second=end_time.second,
                    )
                )

        # A window that is already open at setup (a restart mid-window, or a
        # window spanning midnight) never fires its start marker, so nothing
        # would record when it opened and the average would have no
        # denominator until the next window. Mark it as open from now.
        for period in self.periods:
            name = period[CONF_PERIOD_NAME]
            if name not in self.period_started_at and engine.period_contains_time(
                period, now
            ):
                self.period_started_at[name] = now

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
        self.bonus_finalized_for = saved.get("bonus_finalized_for", {})
        self.cost_today = saved.get("cost_today", 0.0)
        self.cost_month = saved.get("cost_month", 0.0)
        self.cost_billing_period = saved.get("cost_billing_period", 0.0)
        self.bonus_savings_billing_period = saved.get("bonus_savings_billing_period", 0.0)
        self.bonus_days_earned_billing_period = saved.get(
            "bonus_days_earned_billing_period", 0
        )
        self.last_export_kwh = saved.get("last_export_kwh")
        self.export_tier_usage_today = saved.get("export_tier_usage_today", {})
        self.export_credit_today = saved.get("export_credit_today", 0.0)
        self.export_credit_month = saved.get("export_credit_month", 0.0)
        self.export_credit_billing_period = saved.get("export_credit_billing_period", 0.0)
        self.period_avg_watts_today = saved.get("period_avg_watts_today", {})
        self.period_open_seconds_today = saved.get("period_open_seconds_today", {})
        # Persisted so a restart mid-window keeps the real window-open time
        # as the average's denominator, instead of restarting the clock and
        # over-stating average power for the rest of that window.
        self.period_started_at = {
            name: datetime.fromisoformat(value)
            for name, value in (saved.get("period_started_at") or {}).items()
        }
        self.period_energy_kwh_today = saved.get("period_energy_kwh_today", {})
        self.period_energy_kwh_billing_period = saved.get(
            "period_energy_kwh_billing_period", {}
        )
        self.export_period_energy_kwh_billing_period = saved.get(
            "export_period_energy_kwh_billing_period", {}
        )
        self.period_energy_kwh_total = saved.get("period_energy_kwh_total", {})
        self.export_period_energy_kwh_total = saved.get(
            "export_period_energy_kwh_total", {}
        )
        if saved.get("today"):
            self.today = date.fromisoformat(saved["today"])
        if saved.get("billing_period_start"):
            self.billing_period_start = date.fromisoformat(saved["billing_period_start"])
        if saved.get("billing_period_end"):
            self.billing_period_end = date.fromisoformat(saved["billing_period_end"])

        # Upgrade path: installs from before bonus_finalized_for existed have
        # no record of which bonuses already settled today, and the setup
        # catch-up would credit them a second time. The old code set
        # bonus_earned_today[name] at the moment it finalized, so treat any
        # entry there as already settled for the stored day.
        if "bonus_finalized_for" not in saved and self.bonus_earned_today:
            today_iso = self.today.isoformat()
            self.bonus_finalized_for = {
                name: today_iso for name in self.bonus_earned_today
            }

    async def _async_save(self) -> None:
        if not self._store:
            return
        await self._store.async_save(
            {
                "last_energy_kwh": self.last_energy_kwh,
                "tier_usage_today": self.tier_usage_today,
                "energy_by_period_today": self.energy_by_period_today,
                "bonus_earned_today": self.bonus_earned_today,
                "bonus_finalized_for": self.bonus_finalized_for,
                "cost_today": self.cost_today,
                "cost_month": self.cost_month,
                "cost_billing_period": self.cost_billing_period,
                "bonus_savings_billing_period": self.bonus_savings_billing_period,
                "bonus_days_earned_billing_period": self.bonus_days_earned_billing_period,
                "last_export_kwh": self.last_export_kwh,
                "export_tier_usage_today": self.export_tier_usage_today,
                "export_credit_today": self.export_credit_today,
                "export_credit_month": self.export_credit_month,
                "export_credit_billing_period": self.export_credit_billing_period,
                "period_avg_watts_today": self.period_avg_watts_today,
                "period_open_seconds_today": self.period_open_seconds_today,
                "period_started_at": {
                    name: value.isoformat()
                    for name, value in self.period_started_at.items()
                },
                "period_energy_kwh_today": self.period_energy_kwh_today,
                "period_energy_kwh_billing_period": self.period_energy_kwh_billing_period,
                "export_period_energy_kwh_billing_period": self.export_period_energy_kwh_billing_period,
                "period_energy_kwh_total": self.period_energy_kwh_total,
                "export_period_energy_kwh_total": self.export_period_energy_kwh_total,
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

    # ---- manual reset ------------------------------------------------

    async def async_reset_costs(
        self,
        *,
        reset_today: bool = True,
        reset_month: bool = True,
        reset_billing_period: bool = True,
        reset_power_tracking: bool = True,
        reset_tier_usage: bool = False,
    ) -> None:
        """Zero accumulated cost/credit/power counters. Never touches the
        configured billing period dates or time-of-use period definitions.
        """
        if reset_today:
            self.cost_today = 0.0
            self.export_credit_today = 0.0
        if reset_month:
            self.cost_month = 0.0
            self.export_credit_month = 0.0
        if reset_billing_period:
            self.cost_billing_period = 0.0
            self.bonus_savings_billing_period = 0.0
            self.bonus_days_earned_billing_period = 0
            self.export_credit_billing_period = 0.0
            self.period_energy_kwh_billing_period = {}
            self.export_period_energy_kwh_billing_period = {}
        if reset_power_tracking:
            self.energy_by_period_today = {}
            self.period_avg_watts_today = {}
            self.period_open_seconds_today = {}
            self.period_energy_kwh_today = {}
            for sample in self.bonus_samples.values():
                sample.reset()
        if reset_tier_usage:
            self.tier_usage_today = {}
            self.export_tier_usage_today = {}

        await self._async_save()
        self._notify()

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

        # Only wipe the running totals when the billing period has genuinely
        # elapsed - i.e. today has reached the end of the period we were
        # last tracking. Testing "did the computed start change?" instead
        # conflates a real rollover with an edit to the cycle config, and
        # editing the cycle start by even one day in the options flow
        # reloads the entry, recomputes a different start, and silently
        # zeroes a whole period's accumulated cost and bonuses.
        #
        # Anything else (a config edit mid-period, a restart, a reload)
        # re-anchors the dates and keeps the money. A first run has no
        # stored end, and its counters are zero already.
        rolled_over = self.billing_period_end is not None and today >= self.billing_period_end

        if self.billing_period_start != start or self.billing_period_end != end:
            _LOGGER.debug(
                "%s: billing period bounds %s..%s -> %s..%s (%s)",
                self.plan_name,
                self.billing_period_start,
                self.billing_period_end,
                start,
                end,
                "rolled over, counters reset" if rolled_over else "re-anchored, counters kept",
            )

        self.billing_period_start = start
        self.billing_period_end = end

        if rolled_over:
            self.cost_billing_period = 0.0
            self.bonus_savings_billing_period = 0.0
            self.bonus_days_earned_billing_period = 0
            self.export_credit_billing_period = 0.0
            self.period_energy_kwh_billing_period = {}
            self.export_period_energy_kwh_billing_period = {}

    def _reset_period_open_clocks(self, now: datetime) -> None:
        """Restart the per-period "open time today" clocks for a new day.

        Today's open time starts at midnight, so the accumulated seconds go
        back to zero. A window that spans midnight is still open, and its
        contribution to *today* runs from midnight rather than from when it
        opened yesterday - so it is re-marked as starting now instead of
        being dropped, which would leave the average without a denominator
        until the window closed.
        """
        self.period_open_seconds_today = {}
        self.period_started_at = {
            period[CONF_PERIOD_NAME]: now
            for period in self.periods
            if engine.period_contains_time(period, now)
        }

    def _recompute_month_bounds(self, today: date) -> None:
        """Self-correct cost_month/export_credit_month on setup if the last
        known day is in a different calendar month than now.

        _handle_midnight is the only other place these reset, and it only
        fires from a callback scheduled for exactly 00:00:00 - if Home
        Assistant is restarting/reloading right at that moment, that
        specific tick never runs, and last month's cost would otherwise
        stay stuck inside this month's total until the following midnight
        happens to land cleanly. billing_period_start already gets this
        same self-correction in _recompute_billing_bounds above; this
        mirrors it for the calendar-month counters.
        """
        if (self.today.year, self.today.month) != (today.year, today.month):
            self.cost_month = 0.0
            self.export_credit_month = 0.0

    def _recompute_daily_bounds(self, today: date) -> None:
        """Self-correct the day-scoped counters on setup if the last known
        day is earlier than today.

        _handle_midnight is the only other place these reset, and it only
        fires from a callback scheduled for exactly 00:00:00 - if Home
        Assistant is restarting/reloading right at that moment, that
        specific tick never runs, and yesterday's values (including its
        peak `_energy_today` total) stay stuck in today's counters until
        the following midnight happens to land cleanly. cost_this_month
        and the billing period bounds already get this same self-
        correction on setup; this mirrors it for the daily counters.
        """
        if self.today == today:
            return
        now = dt_util.now()
        self.tier_usage_today = {}
        self.period_energy_kwh_today = {}
        self.energy_by_period_today = {
            name: total
            for name, total in self.energy_by_period_today.items()
            if any(
                p[CONF_PERIOD_NAME] == name and engine.period_contains_time(p, now)
                for p in self.periods
            )
        }
        self.bonus_earned_today = {}
        self.period_avg_watts_today = {
            name: val
            for name, val in self.period_avg_watts_today.items()
            if any(
                p[CONF_PERIOD_NAME] == name and engine.period_contains_time(p, now)
                for p in self.periods
            )
        }
        self._reset_period_open_clocks(now)
        self.export_tier_usage_today = {}
        self.export_credit_today = 0.0
        self.cost_today = self.daily_charge
        # _handle_midnight also adds the new day's supply charge to the
        # running totals. This path only runs when that tick was missed, so
        # it has to do the same or the day's charge is missing from the
        # month and billing-period figures while showing correctly in
        # "cost today".
        self.cost_month += self.daily_charge
        self.cost_billing_period += self.daily_charge
        self.today = today

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
        self.period_energy_kwh_today[name] = (
            self.period_energy_kwh_today.get(name, 0.0) + delta_kwh
        )
        self.period_energy_kwh_billing_period[name] = (
            self.period_energy_kwh_billing_period.get(name, 0.0) + delta_kwh
        )
        self.period_energy_kwh_total[name] = (
            self.period_energy_kwh_total.get(name, 0.0) + delta_kwh
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
        self.export_period_energy_kwh_billing_period[name] = (
            self.export_period_energy_kwh_billing_period.get(name, 0.0) + delta_kwh
        )
        self.export_period_energy_kwh_total[name] = (
            self.export_period_energy_kwh_total.get(name, 0.0) + delta_kwh
        )

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
        bonus_start = bonus.get(CONF_BONUS_START_TIME)
        bonus_end = bonus.get(CONF_BONUS_END_TIME)
        if bonus_start and bonus_end:
            window = {
                CONF_PERIOD_START_TIME: bonus_start,
                CONF_PERIOD_END_TIME: bonus_end,
                CONF_PERIOD_DAYS: active.get(CONF_PERIOD_DAYS, DAYS_ALL),
            }
            if not engine.period_contains_time(window, now):
                return
        name = active[CONF_PERIOD_NAME]
        sample = self.bonus_samples.setdefault(name, BonusWindowSample())
        sample.sample(now, watts)
        self._notify()

    # ---- bonus finalization -------------------------------------------

    def _finalize_bonus(self, period_name: str, now: datetime) -> bool:
        """Settle one period's bonus for the day `now` falls on.

        Returns True if it settled the bonus, False if there was nothing to
        do (no such period, no bonus configured, or already settled today).
        Callers own saving and notifying.
        """
        period = next(
            (p for p in self.periods if p[CONF_PERIOD_NAME] == period_name), None
        )
        if period is None:
            return False
        bonus = period.get(CONF_PERIOD_BONUS)
        if not bonus:
            return False

        # One settlement per period per day. Without this the bonus can be
        # credited twice: the finalizer is scheduled by wall-clock time, and
        # a DST fall-back repeats the hour it sits in.
        today_iso = now.date().isoformat()
        if self.bonus_finalized_for.get(period_name) == today_iso:
            return False

        threshold = bonus[CONF_BONUS_THRESHOLD_W]
        if bonus.get("calc_mode") == BONUS_CALC_LIVE_POWER and period_name in self.bonus_samples:
            avg_w = self.bonus_samples[period_name].average()
        else:
            start_t = engine.parse_time(
                bonus.get(CONF_BONUS_START_TIME) or period[CONF_PERIOD_START_TIME]
            )
            end_t = engine.parse_time(
                bonus.get(CONF_BONUS_END_TIME) or period[CONF_PERIOD_END_TIME]
            )
            # engine.window_hours, not a plain subtraction: a bonus window
            # that wraps midnight (23:00-06:00) subtracts to a negative
            # span, which would make average power negative and hand out
            # the bonus unconditionally.
            energy = self.energy_by_period_today.get(period_name, 0.0)
            avg_w = engine.avg_watts_from_energy(
                energy, engine.window_hours(start_t, end_t)
            )

        earned = avg_w < threshold
        self.bonus_earned_today[period_name] = earned
        self.bonus_finalized_for[period_name] = today_iso
        if earned:
            # The bonus is a credit against the day's bill, so it belongs in
            # every cost accumulator - the same three that usage and export
            # credit already adjust. Previously only the billing-period
            # total carried it, leaving "cost today" and "cost this month"
            # overstated by the bonus amount for every day it was earned.
            amount = bonus["amount"]
            self.cost_today -= amount
            self.cost_month -= amount
            self.cost_billing_period -= amount
            self.bonus_savings_billing_period += amount
            self.bonus_days_earned_billing_period += 1

        if period_name in self.bonus_samples:
            self.bonus_samples[period_name].reset()
        self.energy_by_period_today.pop(period_name, None)
        return True

    def _bonus_window_end(self, period: dict[str, Any]):
        """The time of day a period's bonus is settled at."""
        bonus = period.get(CONF_PERIOD_BONUS)
        if not bonus:
            return None
        return engine.parse_time(
            bonus.get(CONF_BONUS_END_TIME) or period[CONF_PERIOD_END_TIME]
        )

    def _catch_up_bonuses(self, now: datetime) -> bool:
        """Settle any bonus whose window already closed today but was never
        finalized.

        _finalize_bonus only ever runs from a callback scheduled for one
        exact wall-clock second. If Home Assistant is down, restarting or
        reloading at that second, the tick never fires and the day's bonus
        is silently never credited - the cost accumulators end the period
        overstated with no way to tell after the fact, because the next
        midnight clears the underlying energy figures.

        Only today's bonuses can be recovered: once the day rolls over the
        inputs are gone. Mirrors the same self-correction the daily,
        monthly and billing-period counters already get on setup.
        """
        settled = False
        for period in self.periods:
            end_t = self._bonus_window_end(period)
            if end_t is None:
                continue
            if now.time() < end_t:
                continue
            name = period[CONF_PERIOD_NAME]
            if self._finalize_bonus(name, now):
                settled = True
                _LOGGER.debug(
                    "%s: settled missed bonus for period %s (window closed %s)",
                    self.plan_name,
                    name,
                    end_t,
                )
        return settled

    def _make_bonus_finalizer(self, period_name: str) -> Callable[[datetime], None]:
        @callback
        def _finalize(now: datetime) -> None:
            if not self._finalize_bonus(period_name, now):
                return
            self.hass.async_create_task(self._async_save())
            self._notify()

        return _finalize

    # ---- per-period average import power -------------------------------

    def _make_period_start_marker(self, period_name: str) -> Callable[[datetime], None]:
        @callback
        def _mark(now: datetime) -> None:
            self.period_started_at[period_name] = now

        return _mark

    def _make_period_avg_finalizer(self, period_name: str) -> Callable[[datetime], None]:
        @callback
        def _finalize(now: datetime) -> None:
            period = next(
                (p for p in self.periods if p[CONF_PERIOD_NAME] == period_name), None
            )
            if period is None:
                return

            # Bank the window that just closed, then average over every
            # window this period has been open for today. A period split
            # into several windows must not restart its denominator each
            # time one closes.
            started = self.period_started_at.pop(period_name, None)
            if started is not None:
                self.period_open_seconds_today[period_name] = (
                    self.period_open_seconds_today.get(period_name, 0.0)
                    + max((now - started).total_seconds(), 0.0)
                )

            elapsed_hours = self.period_open_seconds_today.get(period_name, 0.0) / 3600
            if elapsed_hours <= 0:
                # No start marker was ever seen today (Home Assistant was
                # down when the window opened). Fall back to the window's
                # configured length so the average is still roughly right.
                elapsed_hours = engine.period_total_hours(period)

            energy = self.period_energy_kwh_today.get(period_name, 0.0)
            self.period_avg_watts_today[period_name] = engine.avg_watts_from_energy(
                energy, elapsed_hours
            )

            # period_energy_kwh_today is NOT touched here - it resets at
            # midnight (see _handle_midnight), not at the period's own end
            # time, so it reads as a genuine "used today" total that holds
            # its value for the rest of the day once the window closes.

            # Reset the avg-watts numerator itself now that it's been
            # consumed above. A period that spans midnight (e.g. Controlled
            # Load) is exempt from the midnight-rollover clear (so its energy
            # survives being split by the day boundary while its window is
            # still open) - but with no bonus finalizer either to pop it,
            # nothing was ever clearing it, so it accumulated night after
            # night indefinitely and inflated this same average further each
            # day. Resetting it here, at the point the value has just been
            # used, closes that gap for every period regardless of whether
            # it has a bonus. Harmless if a bonus finalizer already cleared
            # it - both just want it empty by day's end.
            self.energy_by_period_today.pop(period_name, None)

            self.hass.async_create_task(self._async_save())
            self._notify()

        return _finalize

    # ---- daily/monthly/billing-period rollover -----------------------

    @callback
    def _handle_midnight(self, now: datetime) -> None:
        today = now.date()
        self.tier_usage_today = {}
        self.period_energy_kwh_today = {}
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
        self.period_avg_watts_today = {
            name: val
            for name, val in self.period_avg_watts_today.items()
            if any(
                p[CONF_PERIOD_NAME] == name and engine.period_contains_time(p, now)
                for p in self.periods
            )
        }
        self._reset_period_open_clocks(now)
        self.export_tier_usage_today = {}
        self.export_credit_today = 0.0

        # Roll the period bounds *before* applying the new day's charges.
        # A rollover zeroes the billing-period totals, so charging first
        # meant the first day of every billing period had its supply charge
        # added and then immediately wiped - that day was silently free.
        self._recompute_billing_bounds(today)
        if today.month != self.today.month:
            self.cost_month = 0.0
            self.export_credit_month = 0.0

        self.cost_today = self.daily_charge
        self.cost_billing_period += self.daily_charge
        self.cost_month += self.daily_charge

        self.today = today

        self.hass.async_create_task(self._async_save())
        self._notify()
