# Tariff Tracker

[![GitHub release](https://img.shields.io/github/v/release/aistuartai/Tariff_Tracker)](https://github.com/aistuartai/Tariff_Tracker/releases)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Home Assistant custom integration that tracks the real cost of a time-of-use
electricity plan — daily supply charge, peak/shoulder/off-peak/free periods
(with per-period tiered rates), and an optional "stay under a threshold and
get a bonus" reward some retailers offer during a peak window.

Everything is configured in the UI: no YAML. Point it at your existing grid
import energy sensor and define your plan's rates and time windows.

See [CHANGELOG.md](CHANGELOG.md) for release history.

## Features

- Daily, monthly, and billing-period (calendar month **or** a fixed N-day
  cycle from a start date, e.g. "every 28 days") cost totals
- Any number of time-of-use periods, each with:
  - one or more time windows, so a band split by other periods (e.g. a
    shoulder rate applying both before peak and again overnight) is a
    single period rather than two with duplicated rates
  - a day filter (every day / weekdays / weekends)
  - a flat rate, or a two-tier rate (e.g. "first 50 kWh/day free, then a
    balance rate")
  - an optional conditional bonus: a fixed $ credit if average import power
    during that period's window stays under a configured watt threshold
- Bonus can be calculated purely from your energy sensor's usage during the
  window (no extra hardware needed), or from a live power sensor if you have
  one and want real-time "how close am I" feedback
- A `binary_sensor` per bonus-enabled period that flips daily, so you get a
  free calendar-style history of bonus days via Home Assistant's built-in
  history/logbook — no extra dashboard needed, plus a running count and
  success percentage of bonus days for the current billing period
- Optional export/feed-in tracking: define export periods the same way as
  import periods (day filter, tiered rates), and the credit is netted
  straight out of `cost_today` / `cost_this_month` / `cost_this_billing_period`
  automatically — no separate bill math needed

## Requirements

- An existing sensor for your home's grid import **energy** (kWh,
  `state_class: total_increasing`) — most inverter/battery/smart-meter
  integrations already expose one.
- Optionally, a grid import **power** (W) sensor if you want live bonus
  window feedback instead of the after-the-fact energy-based calculation.
- Optionally, a grid export **energy** (kWh, `total_increasing`) sensor if
  you have solar and want feed-in credit tracked and netted against cost.

## Installation

### HACS

1. HACS → Integrations → ⋮ → Custom repositories → add this repo URL,
   category "Integration".
2. Search for "Tariff Tracker" and install.
3. Restart Home Assistant.

### Manual

Copy `custom_components/tariff_tracker` into your `config/custom_components/`
directory and restart Home Assistant.

## Setup

1. Settings → Devices & Services → Add Integration → **Tariff Tracker**.
2. Give the plan a name, pick your grid import energy sensor (and power
   sensor, if using), and set your daily supply charge.
3. Open the new entry's **Configure** to set the billing cycle and add your
   import periods (rates, times, tiers, and bonus rules) and, if you have
   solar, your export/feed-in periods.
4. Rates change every year or two — come back to **Configure** to edit,
   add, or delete periods any time; no need to remove and re-add the
   integration.

## Entities created per plan

| Entity | Description |
|---|---|
| `sensor.<plan>_current_period` | Name of the active import period right now |
| `sensor.<plan>_current_rate` | $/kWh charged right now |
| `sensor.<plan>_cost_today` | Running net cost for today (import cost + daily charge − export credit − bonus) |
| `sensor.<plan>_cost_this_month` | Running net cost for the calendar month |
| `sensor.<plan>_cost_this_billing_period` | Running net cost for the current billing cycle |
| `sensor.<plan>_bonus_savings_this_billing_period` | Total bonus $ earned so far this cycle |
| `sensor.<plan>_bonus_days_earned` | Days this cycle whose bonus was earned; only present if a period has a bonus configured. `days_elapsed` as an attribute |
| `sensor.<plan>_bonus_day_percentage` | Share of completed cycle days whose bonus was earned; only present if a period has a bonus configured. `days_earned`/`days_elapsed` as attributes |
| `sensor.<plan>_billing_period_start` | Start date of the current billing cycle |
| `sensor.<plan>_billing_period_days_remaining` | Days left in the current cycle |
| `binary_sensor.<period>_bonus_active_window` | On while that period's bonus window is active |
| `binary_sensor.<period>_bonus_earned_today` | Result once the window closes for the day; `off` until then |
| `sensor.<period>_avg_power_today` | Average import power (W) implied by that period's energy use so far |
| `sensor.<period>_energy_today` | kWh used in that period today; resets at midnight (and self-corrects on restart if one lands right on that boundary), holding its value for the rest of the day once the window closes |
| `sensor.<period>_window` *(diagnostic)* | The period's configured window(s), e.g. `15:00-16:00, 23:00-12:00`. Full list, count and total hours as attributes |
| `sensor.<period>_rate` *(diagnostic)* | The period's configured $/kWh rate (full tier list as an attribute) |
| `sensor.<period>_bonus_threshold` *(diagnostic)* | Configured bonus power threshold, in W; only present if the period has a bonus configured. Bonus window + credit amount as attributes |

Only present if an export energy sensor is configured:

| Entity | Description |
|---|---|
| `sensor.<plan>_current_export_period` | Name of the active export period right now |
| `sensor.<plan>_current_export_rate` | $/kWh credited right now |
| `sensor.<plan>_export_credit_today` | Feed-in credit earned today (already netted into `cost_today`) |
| `sensor.<plan>_export_credit_this_month` | Feed-in credit earned this month |
| `sensor.<plan>_export_credit_this_billing_period` | Feed-in credit earned this billing cycle |

### Periods with more than one window

Retailers often price a band that isn't one contiguous block — a shoulder
rate that applies from 3pm until peak starts, and again from 11pm through
to midday. Configure that as **one** period with two windows, not two
periods sharing a rate.

In the period form, window 1 is required and windows 2 and 3 are optional;
fill in both halves of a pair to add a window, or clear both to remove it.
Windows may wrap past midnight and must not overlap each other.

Keeping the band as one period matters beyond tidiness:

- **Tiers are per period, per day.** Split across two periods, a "first
  50 kWh/day at $0" allowance is granted *twice* — once to each fragment.
- kWh totals (today, billing period, lifetime) are one figure for the band
  rather than two you have to add up.
- `sensor.<period>_avg_power_today` averages over the band's whole open
  time for the day instead of restarting at each fragment.

Periods saved before this existed keep working untouched — a period with no
window list simply uses its own start/end time as its single window. Editing
and saving a period writes the window list.

### Merging two existing periods into one

Add the second period's window to the first, then delete the second. Note
that per-period kWh counters are keyed by period name, so the deleted
period's billing-period and lifetime totals are dropped rather than moved.
Do it just after a billing period rolls over if you want the running totals
to stay meaningful.

### Counting bonus days

Use `sensor.<plan>_bonus_days_earned` rather than a `history_stats` count
over `binary_sensor.<period>_bonus_earned_today`. Reloading the integration
after a bonus has settled re-adds the binary sensor, which records a second
entry into `on` — `history_stats` counts that as another bonus day, so the
total creeps above the number of days that have actually passed. The
integration's own counter is incremented once per day as it settles and is
unaffected by reloads and restarts.

## Buttons created per plan

| Entity | Description |
|---|---|
| `button.<plan>_reset_cost_history` | Zeroes today's, this month's, this billing period's, and power-tracking totals in one go |
| `button.<plan>_reset_monthly_cost` | Zeroes just this month's running cost/credit, leaving everything else untouched |

## Contributing

Issues and PRs welcome. Core cost/bonus math lives in
`custom_components/tariff_tracker/tariff_engine.py` and is plain Python with
no Home Assistant imports, so it's easy to unit test — see `tests/`.
