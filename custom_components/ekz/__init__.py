"""EKZ Smart Meter integration: imports myEKZ consumption into HA long-term statistics."""
from __future__ import annotations

import logging
import random
from datetime import datetime, time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.event import async_call_later, async_track_time_change

from .const import (
    CONF_JITTER_MINUTES,
    CONF_RUN_AT_TIME,
    DEFAULT_JITTER_MINUTES,
    DEFAULT_RUN_AT_TIME,
    DOMAIN,
    SERVICE_IMPORT_NOW,
)
from .coordinator import EkzImporter

_LOGGER = logging.getLogger(__name__)


def _parse_run_at(raw: str | None) -> time:
    """TimeSelector stores values as 'HH:MM:SS'; accept 'HH:MM' too, for
    hand-edited configs, and fall back to the default on garbage."""
    try:
        parts = str(raw or DEFAULT_RUN_AT_TIME).split(":")
        return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except (ValueError, IndexError):
        _LOGGER.warning("EKZ: invalid run_at_time %r, defaulting to %s", raw, DEFAULT_RUN_AT_TIME)
        return time.fromisoformat(DEFAULT_RUN_AT_TIME)


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Register the one-shot "run an import now" service (once per HA instance)."""
    hass.data.setdefault(DOMAIN, {})

    async def _import_now(_call: ServiceCall) -> None:
        for importer in hass.data.get(DOMAIN, {}).values():
            hass.async_create_background_task(
                importer.async_run(), name="ekz-manual-import"
            )

    if not hass.services.has_service(DOMAIN, SERVICE_IMPORT_NOW):
        hass.services.async_register(DOMAIN, SERVICE_IMPORT_NOW, _import_now)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    importer = EkzImporter(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = importer

    # Kick off an import right after setup without blocking HA startup.
    hass.async_create_background_task(
        importer.async_run(), name=f"ekz-initial-{entry.entry_id}"
    )

    run_at = _parse_run_at(
        entry.options.get(CONF_RUN_AT_TIME, entry.data.get(CONF_RUN_AT_TIME, DEFAULT_RUN_AT_TIME))
    )
    jitter_minutes = max(
        0,
        int(
            entry.options.get(
                CONF_JITTER_MINUTES,
                entry.data.get(CONF_JITTER_MINUTES, DEFAULT_JITTER_MINUTES),
            )
        ),
    )

    @callback
    def _fire_import(_now: datetime | None) -> None:
        hass.async_create_background_task(
            importer.async_run(_now), name=f"ekz-tick-{entry.entry_id}"
        )

    @callback
    def _daily_trigger(now: datetime) -> None:
        # At the scheduled wall-clock minute each day, defer the actual run by
        # a uniform-random 0..jitter_minutes. This spreads load across users
        # (EKZ's API is shared) and avoids a thundering herd on restart.
        if jitter_minutes <= 0:
            _fire_import(now)
            return
        delay_seconds = random.uniform(0, jitter_minutes * 60)
        _LOGGER.info(
            "EKZ: scheduled tick at %s; firing in %.0fs (jitter window %dmin)",
            now.strftime("%H:%M"),
            delay_seconds,
            jitter_minutes,
        )
        async_call_later(hass, delay_seconds, _fire_import)

    unsub_daily = async_track_time_change(
        hass, _daily_trigger, hour=run_at.hour, minute=run_at.minute, second=0
    )
    entry.async_on_unload(unsub_daily)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change so a new schedule takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True
