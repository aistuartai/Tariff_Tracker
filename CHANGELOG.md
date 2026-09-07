# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.12.1] - 2026-09-07

### Fixed
- Deleting a period left two of its entities behind in the entity registry
  as permanently Unavailable. The orphan cleanup's list of per-period
  unique-id suffixes was never updated when
  `sensor.<period>_energy_this_billing_period` and
  `sensor.<period>_energy_total` were added in 0.9.0, so those two were not
  recognised as per-period entities at all while the period's other four
  were removed correctly.
- `sensor.<plan>_current_rate` and `sensor.<plan>_current_export_rate` were
  removed from the entity registry and recreated on **every** reload. Both
  end with `_rate`, which the orphan cleanup read as a period's rate sensor
  belonging to a period that no longer exists. The damage was hidden
  because Home Assistant restores a removed entity's id from its
  deleted-entities record, so the entity came straight back with the same
  entity_id - only `modified_at` moving on each reload gave it away.
  Plan-level entities are now excluded explicitly.
- Export period entities would have been deleted on every reload once the
  missing suffixes above were added, since their ids end with the same
  suffixes as import ones but carry an `export_` prefix the valid-id set
  did not account for. Fixed together with the above rather than after.

### Changed
- Per-period unique-id bookkeeping moved to a new `entity_ids.py` with no
  Home Assistant imports, so it is directly unit-testable. Covered by
  `tests/test_entity_ids.py`, including a guard that the plan-level key
  list still accounts for every key that collides with a period suffix.

## [0.12.0] - 2026-09-07

### Added
- A period can now cover **several disjoint time windows**. Some bands are
  split by other periods - a shoulder rate applying both just before peak
  and again overnight - which a single start/end pair cannot express, so
  they had to be configured as two separate periods with duplicated rates.
  The period form now takes up to three windows; leave windows 2 and 3
  blank for the usual single-window period.
  Merging two such periods into one means their kWh totals, daily tier
  allowance and average power are counted once for the band rather than
  once per fragment. Tiering in particular was wrong when split: each
  fragment had its own daily allowance.
- `sensor.<period>_window` now lists every window (e.g.
  "15:00-16:00, 23:00-12:00") and carries `windows`, `window_count` and
  `total_hours` attributes. `start_time`/`end_time` remain as the first
  window for anything already reading them.

### Fixed
- A bonus window that wraps midnight (e.g. 23:00-06:00) computed a
  negative window length, making average power negative and so awarding
  the bonus unconditionally. Windows that wrap are now measured correctly.
- `sensor.<period>_avg_power_today` restarted its elapsed-time denominator
  every time one of the period's windows closed, and a restart mid-window
  left it with no denominator at all until the next window opened. Open
  time is now accumulated across all of today's windows and persisted
  across restarts.

### Changed
- Existing periods are untouched and need no migration: a period with no
  explicit window list uses its own start/end time as its single window,
  exactly as before. Re-saving a period in the options flow writes the
  window list.

## [0.11.0] - 2026-09-07

### Added
- `sensor.<plan>_bonus_days_earned` and `sensor.<plan>_bonus_day_percentage`,
  for plans with at least one bonus-enabled period. The count is kept by
  the integration as each day settles, so it is not affected by reloads.
  Both carry `days_earned`/`days_elapsed` attributes. If you were deriving
  a bonus success rate from a `history_stats` count over
  `binary_sensor.<period>_bonus_earned_today`, these replace it — see
  below for why that approach over-counts.

### Fixed
- An earned bonus was only ever deducted from
  `sensor.<plan>_cost_this_billing_period`. `cost_today` and
  `cost_this_month` were left overstated by the bonus amount for every day
  it was earned, while usage and export credit correctly adjusted all
  three. A plan earning a $1 bonus most nights read roughly $30/month too
  high.
- Editing the billing cycle in the options flow wiped the billing period's
  accumulated cost, bonus savings and per-period energy totals. The reset
  was triggered by "the computed period start changed", which cannot tell
  a genuine rollover from a config edit — and editing the cycle start by a
  single day reloads the entry, recomputes a different start, and zeroed
  the lot. The reset now fires only when today has actually reached the
  end of the period being tracked; anything else re-anchors the dates and
  keeps the totals.
- The first day of every billing period was missing its daily supply
  charge. The midnight handler added the charge to the billing-period
  total and then rolled the period bounds, wiping it in the same tick.
  Bounds are now rolled before the day's charges are applied.
- A missed midnight tick (Home Assistant down or restarting at exactly
  00:00:00) left that day's supply charge out of `cost_this_month` and
  `cost_this_billing_period`, even though `cost_today` self-corrected. The
  setup self-correction now applies the charge to all three.
- A bonus whose window closed while Home Assistant was down, restarting or
  reloading was never credited at all — the finalizer only ran from a
  callback scheduled for one exact second, and the next midnight cleared
  the energy figures it needed. Setup now settles any of today's bonus
  windows that closed without being finalized.
- The bonus could be credited twice in a day. Settlement is now recorded
  per period per day, which also covers the DST fall-back repeating the
  hour the finalizer is scheduled in.

### Changed
- `binary_sensor.<period>_bonus_earned_today` now reads `off` instead of
  `unknown` before the day's window has been settled. `unknown` made it
  unusable as a template or statistics input and hid the state on
  dashboards.

## [0.10.0] - 2026-08-06

### Fixed
- `sensor.<period>_energy_today` (and the other day-scoped counters:
  `tier_usage_today`, `export_tier_usage_today`, `cost_today`,
  `export_credit_today`, `bonus_earned_today`, `period_avg_watts_today`)
  had no self-correction on setup, unlike `cost_this_month` and the
  billing period totals: they only reset via a callback scheduled for
  exactly midnight, so a Home Assistant restart or reload landing right
  on that boundary silently skipped the reset, and yesterday's values -
  including its peak - stayed baked into today's counters until the
  following midnight happened to fire cleanly. Now self-corrects on
  every setup, the same way the billing period and monthly totals
  already did.

## [0.9.0] - 2026-08-05

### Added
- New per-period sensors tracking total kWh across the current billing
  period (not just today): `sensor.<period>_energy_this_billing_period`
  for each import period, and `sensor.<period>_export_energy_this_billing_period`
  for each export period. Reset when the billing period rolls over or on
  manual billing-period reset, same as the existing cost/credit billing-
  period totals.
- New per-period lifetime totals that never reset:
  `sensor.<period>_energy_total` for each import period and
  `sensor.<period>_export_energy_total` for each export period.

## [0.8.1] - 2026-08-04

### Changed
- `sensor.<period>_energy_today` now resets at midnight instead of at the
  period's own end time. Previously it zeroed the moment a period's window
  closed (e.g. a period ending at 3pm would show 0 kWh for the rest of the
  day) - it now holds its full daily total until midnight, matching what
  the "today" in its name implies. The avg-power sensor's own internal
  energy tracking (used to compute the live/finalized average) is
  unaffected and still finalizes at the period's own end time.

## [0.8.0] - 2026-08-04

### Fixed
- `cost_this_month` (and `export_credit_this_month`) had no self-correction
  on setup, unlike the billing period total: they only reset via a
  callback scheduled for exactly midnight, so a Home Assistant restart or
  reload landing right on that boundary silently skipped the reset, and
  last month's cost stayed baked into this month's total until the
  following midnight happened to fire cleanly. Now self-corrects on every
  setup, the same way the billing period total already did.

### Added
- "Reset monthly cost" button per plan: zeroes just this month's running
  cost/credit, leaving today's, the billing period's, and tier/power
  tracking totals untouched (the existing "Reset cost history" button
  resets all of them at once).

## [0.7.0] - 2026-08-04

### Fixed
- Bonus window active sensor was tracking the enclosing period's full time
  window instead of the bonus's own narrower window (e.g. a 6pm-9pm bonus
  inside a 4pm-11pm peak period showed as active for all 7 hours).

### Added
- Delete option for time-of-use periods in the options flow (previously
  edit-only, with no way to remove a period once created).
- Automatic entity registry cleanup on reload: removes orphaned
  sensor/binary_sensor entities left behind by deleted or renamed periods,
  instead of leaving them stuck as `Unavailable`.

## [0.6.1] - 2026-08-03

### Fixed
- Controlled Load (and any other bonus-free period spanning midnight) had
  its avg-power energy bucket never reset, so it accumulated across every
  night since setup and drifted upward daily. Now reset at each period's
  own end time, same as every other period. Existing historical
  statistics/graph data is unaffected.

## [0.6.0] - 2026-08-03

### Added
- Per-period daily energy total sensor (`sensor.<period>_energy_today`),
  tracked independently of the avg-power calc, resetting at each period's
  own end time (handles overnight windows correctly).
- Diagnostic sensors per period: configured window (start/end time), rate
  ($/kWh + tier list), and bonus threshold (W + window + credit amount)
  for periods with a bonus.
- Optional `bonus_start_time`/`bonus_end_time` on a period's bonus config,
  so a bonus can be evaluated over a narrower window than the enclosing
  tariff period (e.g. a 6pm-9pm no-usage bonus inside a 4pm-11pm peak
  period). Falls back to the period's own start/end when unset.

## [0.5.0] - 2026-08-01

### Added
- Daily supply charge can now be edited after plan creation, via a new
  "Plan settings" step in the options flow (previously locked at creation
  time).
- Diagnostic sensor exposing the currently configured daily supply charge.

## [0.4.0] - 2026-07-07

### Added
- `tariff_tracker.reset_costs` service: zero cost/credit/watt counters per
  plan (today/month/billing period/power tracking, tier usage optional).
- "Reset cost history" button entity per plan. Never touches configured
  billing period dates or time-of-use period definitions.

## [0.3.1] - 2026-07-07

### Fixed
- Missing `CONF_PERIOD_START_TIME` import caused a `NameError` on setup,
  breaking all configured plans.

## [0.3.0] - 2026-07-07

### Added
- Per-period average import power (W) sensor for each day: shows a live
  average while a period's window is open, then freezes the finalized
  average once it closes.

## [0.2.0] - 2026-07-06

### Added
- Power export/feed-in tracking: an optional export energy sensor plus
  export periods (day filter, tiered rates), configured the same way as
  import periods. Export credit nets straight out of `cost_today` /
  `cost_this_month` / `cost_this_billing_period`. Adds
  `current_export_period`/`current_export_rate` and `export_credit_*`
  sensors when export is configured.

## [0.1.5] - 2026-07-06

### Fixed
- HACS validation failures: added required GitHub repo topics and a
  bundled brand icon so HACS passes its local brand check.

## [0.1.4] - 2026-07-06

### Changed
- Integration moved from the Helpers tab to the main Integrations page
  (`integration_type` changed from `helper` to `service`). Configure/
  options access is unchanged.

## [0.1.3] - 2026-07-06

### Fixed
- Leaving the first-tier limit or billing-cycle start-date field blank
  crashed the options flow with "expected float" (an explicit
  `default=None` was fed into the selector's validator). Optional fields
  now stay genuinely blank instead.

## [0.1.2] - 2026-07-06

### Fixed
- Config flow failed to load due to an invalid `NumberSelector` step value
  (`0.0001` is below Home Assistant's minimum of `0.001`), causing
  "Invalid handler specified" when adding the integration.

## [0.1.1] - 2026-07-06

### Added
- Initial release: config-driven time-of-use cost tracking with tiered
  rates, configurable billing cycle (calendar month or fixed N-day cycle),
  and a conditional low-usage bonus per period.

[0.10.0]: https://github.com/aistuartai/Tariff_Tracker/releases/tag/v0.10.0
[0.9.0]: https://github.com/aistuartai/Tariff_Tracker/releases/tag/v0.9.0
[0.8.1]: https://github.com/aistuartai/Tariff_Tracker/releases/tag/v0.8.1
[0.8.0]: https://github.com/aistuartai/Tariff_Tracker/releases/tag/v0.8.0
[0.7.0]: https://github.com/aistuartai/Tariff_Tracker/releases/tag/v0.7.0
[0.6.1]: https://github.com/aistuartai/Tariff_Tracker/releases/tag/v0.6.1
[0.6.0]: https://github.com/aistuartai/Tariff_Tracker/releases/tag/v0.6.0
[0.5.0]: https://github.com/aistuartai/Tariff_Tracker/releases/tag/v0.5.0
[0.4.0]: https://github.com/aistuartai/Tariff_Tracker/releases/tag/v0.4.0
[0.3.1]: https://github.com/aistuartai/Tariff_Tracker/releases/tag/v0.3.1
[0.3.0]: https://github.com/aistuartai/Tariff_Tracker/releases/tag/v0.3.0
[0.2.0]: https://github.com/aistuartai/Tariff_Tracker/releases/tag/v0.2.0
[0.1.5]: https://github.com/aistuartai/Tariff_Tracker/releases/tag/v0.1.5
[0.1.4]: https://github.com/aistuartai/Tariff_Tracker/releases/tag/v0.1.4
[0.1.3]: https://github.com/aistuartai/Tariff_Tracker/releases/tag/v0.1.3
[0.1.2]: https://github.com/aistuartai/Tariff_Tracker/releases/tag/v0.1.2
[0.1.1]: https://github.com/aistuartai/Tariff_Tracker/releases/tag/v0.1.1
