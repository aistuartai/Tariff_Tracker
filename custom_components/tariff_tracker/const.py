"""Constants for Tariff Tracker."""

DOMAIN = "tariff_tracker"

CONF_PLAN_NAME = "plan_name"
CONF_IMPORT_ENERGY_SENSOR = "import_energy_sensor"
CONF_IMPORT_POWER_SENSOR = "import_power_sensor"
CONF_EXPORT_ENERGY_SENSOR = "export_energy_sensor"
CONF_DAILY_CHARGE = "daily_charge"

CONF_BILLING_CYCLE_TYPE = "billing_cycle_type"
CONF_BILLING_CYCLE_DAYS = "billing_cycle_days"
CONF_BILLING_CYCLE_START = "billing_cycle_start"

BILLING_CYCLE_CALENDAR_MONTH = "calendar_month"
BILLING_CYCLE_EVERY_N_DAYS = "every_n_days"

CONF_PERIODS = "periods"
CONF_EXPORT_PERIODS = "export_periods"

# Per-period keys (stored as list of dicts in CONF_PERIODS / CONF_EXPORT_PERIODS)
CONF_PERIOD_NAME = "name"
CONF_PERIOD_START_TIME = "start_time"
CONF_PERIOD_END_TIME = "end_time"
CONF_PERIOD_DAYS = "days"
CONF_PERIOD_TIERS = "tiers"
CONF_PERIOD_BONUS = "bonus"

# Per-tier keys (list of dicts in CONF_PERIOD_TIERS)
CONF_TIER_LIMIT_KWH = "limit_kwh"
CONF_TIER_RATE = "rate"

# Bonus keys (dict in CONF_PERIOD_BONUS, absent/None if disabled)
CONF_BONUS_AMOUNT = "amount"
CONF_BONUS_THRESHOLD_W = "threshold_w"
CONF_BONUS_CALC_MODE = "calc_mode"

BONUS_CALC_ENERGY_DELTA = "energy_delta"
BONUS_CALC_LIVE_POWER = "live_power_sensor"

DAYS_ALL = "all"
DAYS_WEEKDAYS = "weekdays"
DAYS_WEEKENDS = "weekends"
DAYS_CUSTOM = "custom"

DEFAULT_DAILY_CHARGE = 0.0
