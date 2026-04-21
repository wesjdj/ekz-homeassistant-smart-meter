"""EKZ → HA long-term statistics importer.

Runs periodically; on first invocation (HA empty for our stat_ids) backfills up to
max_backfill_days (default ≈10 years, i.e. everything EKZ has). Subsequent runs
only fetch days newer than whatever HA already has, keeping cumulative sums
continuous.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, TypeVar

import requests
from ekzexport.session import Session
from ekzexport.timeutil import UTC_TZ, ZRH_TZ, parse_api_timestamp

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)

# HA 2026.11 drops the `has_mean` bool in favor of a `mean_type` enum for
# statistics metadata. Older versions (pre-2025.5-ish) don't have the enum at
# all, so we gracefully fall back to emitting only `has_mean: False`.
try:
    from homeassistant.components.recorder.models import StatisticMeanType

    _MEAN_META = {"mean_type": StatisticMeanType.NONE}
except ImportError:  # older HA: keep the legacy key only
    _MEAN_META = {"has_mean": False}
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_INSTALLATION_ID,
    CONF_MAX_BACKFILL_DAYS,
    CONF_PASSWORD,
    CONF_TARIFF_NAMES,
    CONF_TOTP_SECRET,
    CONF_USERNAME,
    CONSUMPTION_STAT_IDS,
    COST_COMPONENTS,
    DEFAULT_MAX_BACKFILL_DAYS,
    DOMAIN,
    STAT_COST,
    STAT_SPEC,
    TARIFFS_API,
)

_LOGGER = logging.getLogger(__name__)


def _to_utc(naive: dt.datetime) -> dt.datetime:
    """ekzexport's parse_api_timestamp parses the API's UTC timestamp into a naive
    datetime; just tag it as UTC."""
    return naive.replace(tzinfo=UTC_TZ)


T = TypeVar("T")

_RETRY_ATTEMPTS = 4
_RETRY_BASE_DELAY = 2.0
_RETRY_MAX_DELAY = 30.0


def _retry_with_backoff(func: Callable[[], T], label: str) -> T:
    """Call ``func`` with exponential backoff on transient network errors.

    Runs inside an executor thread, so ``time.sleep`` is appropriate. 4xx HTTP
    responses are treated as permanent (bad creds, bad params) and raised
    immediately; other ``RequestException``s are retried.
    """
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            return func()
        except requests.exceptions.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            if status is not None and 400 <= status < 500:
                raise
            if attempt == _RETRY_ATTEMPTS:
                raise
            delay = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)), _RETRY_MAX_DELAY)
            _LOGGER.warning(
                "EKZ %s: HTTP %s (attempt %d/%d); retrying in %.1fs",
                label, status, attempt, _RETRY_ATTEMPTS, delay,
            )
            time.sleep(delay)
        except requests.exceptions.RequestException as exc:
            if attempt == _RETRY_ATTEMPTS:
                raise
            delay = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)), _RETRY_MAX_DELAY)
            _LOGGER.warning(
                "EKZ %s: %s (attempt %d/%d); retrying in %.1fs",
                label, exc, attempt, _RETRY_ATTEMPTS, delay,
            )
            time.sleep(delay)
    raise RuntimeError("unreachable")  # loop either returns or raises


def _fetch_tariff_rates(
    tariff_names: Sequence[str], date_from: dt.date, date_to: dt.date
) -> Dict[dt.datetime, float]:
    rates: Dict[dt.datetime, float] = {}
    start_zrh = dt.datetime.combine(date_from, dt.time(0, 0), tzinfo=ZRH_TZ)
    end_zrh = dt.datetime.combine(
        date_to + dt.timedelta(days=1), dt.time(0, 0), tzinfo=ZRH_TZ
    ) - dt.timedelta(minutes=1)
    for tariff_name in tariff_names:
        def _do_fetch(name: str = tariff_name) -> dict:
            resp = requests.get(
                TARIFFS_API,
                params={
                    "tariff_name": name,
                    "start_timestamp": start_zrh.isoformat(),
                    "end_timestamp": end_zrh.isoformat(),
                },
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

        payload = _retry_with_backoff(_do_fetch, f"tariffs[{tariff_name}]")
        for price in payload.get("prices") or []:
            start_utc = dt.datetime.fromisoformat(price["start_timestamp"]).astimezone(UTC_TZ)
            chf_per_kwh = 0.0
            for component in COST_COMPONENTS:
                for entry in price.get(component) or []:
                    if entry.get("unit") == "CHF_kWh":
                        chf_per_kwh += float(entry["value"])
            rates[start_utc] = rates.get(start_utc, 0.0) + chf_per_kwh
    return rates


def _fetch_hourly_buckets(
    session: Session,
    installation_id: str,
    date_from: dt.date,
    date_to: dt.date,
    rates: Optional[Dict[dt.datetime, float]],
) -> Tuple[Dict[dt.datetime, Dict[str, float]], int]:
    """Fetch 15-min values in weekly chunks and bucket into per-hour totals.

    15-min timestamps mark the *end* of each interval, so the value at 01:00
    covers 00:45-01:00 and belongs to the 00:00-01:00 hour bucket.
    """
    buckets: Dict[dt.datetime, Dict[str, float]] = {}
    rate_misses = 0

    def empty() -> Dict[str, float]:
        return {"kwh_total": 0.0, "kwh_peak": 0.0, "kwh_offpeak": 0.0, "cost": 0.0}

    cur = date_from
    while cur <= date_to:
        week_end = min(cur + dt.timedelta(days=6), date_to)
        _LOGGER.info("EKZ fetch: %s → %s", cur, week_end)
        data = _retry_with_backoff(
            lambda: session.get_consumption_data(
                installation_id,
                "PK_VERB_15MIN",
                cur.strftime("%Y-%m-%d"),
                week_end.strftime("%Y-%m-%d"),
            ),
            f"consumption[{cur}..{week_end}]",
        )
        for tariff_key, field in (("seriesHt", "kwh_peak"), ("seriesNt", "kwh_offpeak")):
            series = data.get(tariff_key) or {}
            for v in series.get("values") or []:
                if v.get("status") != "VALID":
                    continue
                ts_end_utc = _to_utc(parse_api_timestamp(v["timestamp"]))
                interval_start_utc = ts_end_utc - dt.timedelta(minutes=15)
                hour_start = (ts_end_utc - dt.timedelta(seconds=1)).replace(
                    minute=0, second=0, microsecond=0
                )
                b = buckets.setdefault(hour_start, empty())
                kwh = float(v["value"])
                b[field] += kwh
                b["kwh_total"] += kwh
                if rates is not None:
                    rate = rates.get(interval_start_utc)
                    if rate is None:
                        rate_misses += 1
                    else:
                        b["cost"] += kwh * rate
        cur = week_end + dt.timedelta(days=1)

    return buckets, rate_misses


def _earliest_ekz_15min_date(session: Session, installation_id: str) -> Optional[dt.date]:
    try:
        data = _retry_with_backoff(
            lambda: session.get_installation_data(installation_id),
            "installation_data",
        )
    except Exception as exc:  # network / auth errors shouldn't be fatal
        _LOGGER.warning("EKZ: could not query installation data: %s", exc)
        return None
    for prop in data.get("status") or []:
        if prop.get("property") == "VERB_15MIN" and prop.get("ab"):
            try:
                return dt.date.fromisoformat(prop["ab"][:10])
            except ValueError:
                return None
    return None


def _build_stats(
    buckets: Dict[dt.datetime, Dict[str, float]],
    stat_ids: Sequence[str],
    prior_state: Dict[str, Optional[Tuple[dt.datetime, float]]],
) -> Dict[str, List[dict]]:
    """Per-stat-id list of entries with cumulative sums continuing from HA's state."""
    out: Dict[str, List[dict]] = {sid: [] for sid in stat_ids}
    for sid in stat_ids:
        prior = prior_state.get(sid)
        cutoff = prior[0] if prior else None
        running = prior[1] if prior else 0.0
        field = STAT_SPEC[sid]["field"]
        for hour in sorted(buckets):
            if cutoff is not None and hour <= cutoff:
                continue
            running += buckets[hour][field]
            out[sid].append(
                {
                    "start": hour,
                    "state": round(running, 4),
                    "sum": round(running, 4),
                }
            )
    return out


def _coerce_ha_stat_start(start_val: Any) -> dt.datetime:
    """HA's get_last_statistics returns 'start' as either a float (seconds since
    epoch, UTC) or an ISO string, depending on HA version. Normalize to UTC dt."""
    if isinstance(start_val, (int, float)):
        # float is seconds; older versions used ms, disambiguate by magnitude.
        secs = start_val / 1000 if start_val > 1e11 else start_val
        return dt.datetime.fromtimestamp(secs, tz=dt.timezone.utc)
    return dt.datetime.fromisoformat(str(start_val).replace("Z", "+00:00"))


class EkzImporter:
    """Runs the EKZ → HA stats import. Invoked on a schedule and on service call."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._lock = asyncio.Lock()

    def _cfg(self, key: str, default: Any = None) -> Any:
        return self.entry.options.get(key, self.entry.data.get(key, default))

    def _resolve_tariffs(self) -> List[str]:
        # Tariff names are stored as a list in new installs and as a
        # comma-separated string in installs that predate the dropdown.
        from .tariffs import normalize_tariff_names

        return normalize_tariff_names(self._cfg(CONF_TARIFF_NAMES))

    async def async_run(self, _now: Any = None) -> None:
        if self._lock.locked():
            _LOGGER.debug("EKZ import already running; skipping.")
            return
        async with self._lock:
            try:
                await self._async_run_once()
            except Exception:
                _LOGGER.exception("EKZ import failed")

    async def _async_run_once(self) -> None:
        tariffs = self._resolve_tariffs()
        stat_ids: List[str] = list(CONSUMPTION_STAT_IDS)
        if tariffs:
            stat_ids.append(STAT_COST)

        prior_state: Dict[str, Optional[Tuple[dt.datetime, float]]] = {}
        for sid in stat_ids:
            prior_state[sid] = await self._async_latest_stat(sid)

        yesterday = dt.date.today() - dt.timedelta(days=1)
        date_to = yesterday
        existing_hours = [p[0] for p in prior_state.values() if p is not None]
        # If a stat we'll emit has no prior state while another does, we're adding
        # a new series mid-life (e.g. user just enabled a tariff). Resuming from
        # the consumption cursor would leave the new series with only recent data;
        # fall through to the full-backfill branches instead.
        new_series_added = existing_hours and any(prior_state[sid] is None for sid in stat_ids)

        username = self._cfg(CONF_USERNAME)
        password = self._cfg(CONF_PASSWORD)
        totp = self._cfg(CONF_TOTP_SECRET, "") or ""
        installation_id = self._cfg(CONF_INSTALLATION_ID)
        max_backfill = int(self._cfg(CONF_MAX_BACKFILL_DAYS, DEFAULT_MAX_BACKFILL_DAYS) or 0)

        if existing_hours and not new_series_added:
            # Day after oldest "latest hour" across stat_ids, with 1-day margin for DST/skew.
            next_day_anchor = (
                min(existing_hours) + dt.timedelta(hours=1)
            ).astimezone(ZRH_TZ).date()
            date_from = next_day_anchor - dt.timedelta(days=1)
        elif max_backfill > 0:
            if new_series_added:
                _LOGGER.info(
                    "EKZ: new statistic(s) %s detected; backfilling %d days to populate history.",
                    [sid for sid in stat_ids if prior_state[sid] is None],
                    max_backfill,
                )
            date_from = yesterday - dt.timedelta(days=max_backfill - 1)
        else:
            date_from = await self.hass.async_add_executor_job(
                self._blocking_earliest_date, username, password, totp, installation_id
            )
            if date_from is None:
                _LOGGER.info("EKZ: earliest date unavailable; defaulting to 365 days.")
                date_from = yesterday - dt.timedelta(days=364)
            else:
                _LOGGER.info("EKZ: auto-backfill from %s", date_from)

        if date_from > date_to:
            _LOGGER.info("EKZ: already up to date through %s", date_to)
            return

        _LOGGER.info("EKZ import: %s → %s (stats: %s)", date_from, date_to, stat_ids)
        buckets, rate_misses = await self.hass.async_add_executor_job(
            self._blocking_fetch_everything,
            username,
            password,
            totp,
            installation_id,
            tariffs,
            date_from,
            date_to,
        )
        if not buckets:
            _LOGGER.info("EKZ: no valid 15-min data in this range.")
            return
        if tariffs and rate_misses:
            _LOGGER.warning(
                "EKZ: %d 15-min intervals had no matching tariff rate; cost not counted for those slots.",
                rate_misses,
            )

        stats = _build_stats(buckets, stat_ids, prior_state)
        for sid in stat_ids:
            entries = stats[sid]
            if not entries:
                continue
            spec = STAT_SPEC[sid]
            meta = {
                **_MEAN_META,
                "has_sum": True,
                "name": spec["name"],
                "source": DOMAIN,
                "statistic_id": sid,
                "unit_of_measurement": spec["unit"],
            }
            _LOGGER.info("EKZ: importing %d hourly entries for %s", len(entries), sid)
            async_add_external_statistics(self.hass, meta, entries)
        _LOGGER.info("EKZ import finished.")

    async def _async_latest_stat(
        self, statistic_id: str
    ) -> Optional[Tuple[dt.datetime, float]]:
        """Return (hour_utc, cumulative_sum) for the latest hour HA has, or None."""
        # `start` and `end` are always returned by get_last_statistics; the
        # `types` set only selects additional value fields (sum/state/mean/...).
        result = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )
        series = (result or {}).get(statistic_id) or []
        if not series:
            return None
        entry = series[0]
        return _coerce_ha_stat_start(entry.get("start")), float(entry.get("sum") or 0.0)

    # Blocking helpers run in an executor thread ---------------------------------

    @staticmethod
    def _blocking_earliest_date(
        username: str, password: str, totp: str, installation_id: str
    ) -> Optional[dt.date]:
        with Session(username, password, token=totp, login_immediately=True) as session:
            return _earliest_ekz_15min_date(session, installation_id)

    @staticmethod
    def _blocking_fetch_everything(
        username: str,
        password: str,
        totp: str,
        installation_id: str,
        tariffs: Sequence[str],
        date_from: dt.date,
        date_to: dt.date,
    ) -> Tuple[Dict[dt.datetime, Dict[str, float]], int]:
        rates = _fetch_tariff_rates(tariffs, date_from, date_to) if tariffs else None
        with Session(username, password, token=totp, login_immediately=True) as session:
            return _fetch_hourly_buckets(session, installation_id, date_from, date_to, rates)
