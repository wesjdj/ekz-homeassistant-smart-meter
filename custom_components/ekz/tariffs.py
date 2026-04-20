"""Curated EKZ tariff-name list for the config / options flow dropdown.

Source of truth: the EKZ Tariffs API OpenAPI spec
(https://api.tariffs.ekz.ch/openapi/swagger_future.yaml). The names below are
the 2026 set; each one is a valid `tariff_name` query parameter for the
public `/v1/tariffs` endpoint.

The `custom_value=True` flag on the selector means users on exotic tariffs
(Einsiedeln `_E` suffix, `_woSDL` / `_inclFees` variants, etc.) can still type
the raw name even if it isn't listed here.

Any of these tariff types can be used, fixed and dynamic alike. For a fixed
tariff the API simply publishes the same CHF/kWh for every 15-min slot of the
day; the cost calculation is identical.
"""
from __future__ import annotations

from typing import List, Tuple

# Ordered by usefulness: integrated bundles first (one selection covers the
# whole bill), then the à-la-carte building blocks.
TARIFF_OPTIONS: List[Tuple[str, str]] = [
    # Bundled: electricity + grid + national fees. Pick one and you're done.
    ("integrated_400ST", "Integrated 400ST: Energie Erneuerbar + Netz 400ST + national fees"),
    ("integrated_400F",  "Integrated 400F: Energie Erneuerbar + Netz 400F + national fees"),
    ("integrated_400WP", "Integrated 400WP: Energie Erneuerbar + Netz 400WP + national fees"),
    ("integrated_400D",  "Integrated 400D: Energie Dynamisch + Netz 400D + national fees (2026+)"),
    ("integrated_400B",  "Integrated 400B: Beleuchtung + Netz 400B + national fees"),
    ("integrated_400L",  "Integrated 400L: Business Erneuerbar + Netz 400L + national fees"),
    ("integrated_400LS", "Integrated 400LS: Business Erneuerbar + Netz 400LS + national fees"),
    ("integrated_16L",   "Integrated 16L: Business Erneuerbar + Netz 16L + national fees"),
    ("integrated_16LS",  "Integrated 16LS: Business Erneuerbar + Netz 16LS + national fees"),
    # Electricity component only (combine with grid + national fees manually).
    ("electricity_standard", "Electricity: Energie Erneuerbar"),
    ("electricity_dynamic",  "Electricity: Energie Dynamisch (2026+)"),
    ("electricity_lighting", "Electricity: Energie Beleuchtung"),
    ("electricity_business", "Electricity: Energie Business Erneuerbar"),
    # Grid component (includes SDL; combine with electricity + national fees).
    ("grid_400ST", "Grid: Netz 400ST + SDL"),
    ("grid_400F",  "Grid: Netz 400F + SDL"),
    ("grid_400WP", "Grid: Netz 400WP + SDL"),
    ("grid_400D",  "Grid: Netz 400D + SDL (2026+)"),
    ("grid_400B",  "Grid: Netz 400B + SDL"),
    ("grid_400L",  "Grid: Netz 400L + SDL"),
    ("grid_400LS", "Grid: Netz 400LS + SDL"),
    ("grid_16L",   "Grid: Netz 16L + SDL"),
    ("grid_16LS",  "Grid: Netz 16LS + SDL"),
    # National fees.
    ("national_fees_woSDL",                    "National fees: Stromreserve + Solidarisierte + Bundesabgaben"),
    ("national_fees_onlySDL",                  "National fees: SDL only"),
    ("national_fees_onlyStromreserve",         "National fees: Stromreserve only"),
    ("national_fees_onlySolidarisierteKosten", "National fees: Solidarisierte Kosten only"),
    ("national_fees_onlyBundesabgaben",        "National fees: Bundesabgaben only"),
    # Regional fees (municipality concessions / efficiency funds).
    ("regional_fees_lt500MWh_ZH", "Regional: Förderung Energieeffizienz <500 MWh (ZH)"),
    ("regional_fees_gt500MWh_ZH", "Regional: Förderung Energieeffizienz ≥500 MWh (ZH)"),
    ("regional_fees_Menzingen",   "Regional: Konzessionsabgabe Menzingen"),
    ("regional_fees_Einsiedeln",  "Regional: Konzessionsabgabe Einsiedeln"),
    # Metering.
    ("metering_directNE7",   "Metering: Messung direkt (NE7)"),
    ("metering_indirectNE7", "Metering: Messung indirekt (NE7)"),
    ("metering_indirectNE5", "Metering: Messung indirekt (NE5)"),
    ("metering_virtual",     "Metering: Virtueller Messpunkt"),
]


def normalize_tariff_names(value) -> List[str]:
    """Accept either a list (new multi-select form) or a comma-separated string
    (legacy free-text form stored by older versions of this integration) and
    return a clean list. Empty entries and whitespace are dropped."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [t.strip() for t in str(value).split(",") if t.strip()]
