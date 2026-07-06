# Tariff Tracker

Home Assistant custom integration that tracks the real cost of a time-of-use
electricity plan — daily supply charge, peak/shoulder/off-peak/free periods
(with per-period tiered rates), and an optional "stay under a threshold and
get a bonus" reward some retailers offer during a peak window.

Everything is configured in the UI: no YAML. Point it at your existing grid
import energy sensor and define your plan's rates and time windows.

## Features

- Daily, monthly, and billing-period (calendar month **or** a fixed N-day
  cycle from a start date, e.g. "every 28 days") cost totals
- Any number of time-of-use periods, each with:
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
  history/logbook — no extra dashboard needed
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
4. Rates change every year or two — come back to **Configure** to edit them,
   no need to remove and re-add the integration.

## Entities created per plan

| Entity | Description |
|---|---|
| `sensor.<plan>_current_period` | Name of the active import period right now |
| `sensor.<plan>_current_rate` | $/kWh charged right now |
| `sensor.<plan>_cost_today` | Running net cost for today (import cost + daily charge − export credit) |
| `sensor.<plan>_cost_this_month` | Running net cost for the calendar month |
| `sensor.<plan>_cost_this_billing_period` | Running net cost for the current billing cycle |
| `sensor.<plan>_bonus_savings_this_billing_period` | Total bonus $ earned so far this cycle |
| `sensor.<plan>_billing_period_start` | Start date of the current billing cycle |
| `sensor.<plan>_billing_period_days_remaining` | Days left in the current cycle |
| `binary_sensor.<period>_bonus_active_window` | On while that period's bonus window is active |
| `binary_sensor.<period>_bonus_earned_today` | Result once the window closes for the day |

Only present if an export energy sensor is configured:

| Entity | Description |
|---|---|
| `sensor.<plan>_current_export_period` | Name of the active export period right now |
| `sensor.<plan>_current_export_rate` | $/kWh credited right now |
| `sensor.<plan>_export_credit_today` | Feed-in credit earned today (already netted into `cost_today`) |
| `sensor.<plan>_export_credit_this_month` | Feed-in credit earned this month |
| `sensor.<plan>_export_credit_this_billing_period` | Feed-in credit earned this billing cycle |

## Contributing

Issues and PRs welcome. Core cost/bonus math lives in
`custom_components/tariff_tracker/tariff_engine.py` and is plain Python with
no Home Assistant imports, so it's easy to unit test — see `tests/`.
