"""Constants for the EKZ Smart Meter integration."""

DOMAIN = "ekz"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_TOTP_SECRET = "totp_secret"
CONF_INSTALLATION_ID = "installation_id"
CONF_TARIFF_NAMES = "tariff_names"
CONF_RUN_AT_TIME = "run_at_time"
CONF_JITTER_MINUTES = "jitter_minutes"
CONF_MAX_BACKFILL_DAYS = "max_backfill_days"

# EKZ publishes consumption data once per day, so running once daily is plenty.
# Default time is 07:00 local: late enough that yesterday's data is reliably
# available, early enough that the Energy dashboard looks fresh each morning.
DEFAULT_RUN_AT_TIME = "07:00:00"
# A jitter window spreads load off a fixed-moment spike (nice for EKZ's API,
# which is shared across every HA user who installs this) and reduces the
# chance multiple HA restarts land on the exact same retry clock.
DEFAULT_JITTER_MINUTES = 30
DEFAULT_MAX_BACKFILL_DAYS = 3650

SERVICE_IMPORT_NOW = "import_now"

STAT_TOTAL = f"{DOMAIN}:energy_consumption"
STAT_PEAK = f"{DOMAIN}:energy_consumption_peak"
STAT_OFFPEAK = f"{DOMAIN}:energy_consumption_offpeak"
STAT_COST = f"{DOMAIN}:energy_cost"

STAT_SPEC = {
    STAT_TOTAL:   {"name": "EKZ Consumption",            "unit": "kWh", "field": "kwh_total"},
    STAT_PEAK:    {"name": "EKZ Consumption (Peak)",     "unit": "kWh", "field": "kwh_peak"},
    STAT_OFFPEAK: {"name": "EKZ Consumption (Off-Peak)", "unit": "kWh", "field": "kwh_offpeak"},
    STAT_COST:    {"name": "EKZ Cost",                   "unit": "CHF", "field": "cost"},
}

CONSUMPTION_STAT_IDS = (STAT_TOTAL, STAT_PEAK, STAT_OFFPEAK)

TARIFFS_API = "https://api.tariffs.ekz.ch/v1/tariffs"
# Component arrays in a Price whose CHF_kWh entries count toward per-kWh cost.
# "refund_storage" and "feed_in" are excluded (credits / opposite flow).
COST_COMPONENTS = ("electricity", "grid", "integrated", "regional_fees", "metering")
