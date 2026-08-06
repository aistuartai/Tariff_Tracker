# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
