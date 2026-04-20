"""Config flow for the EKZ Smart Meter integration."""
from __future__ import annotations

import base64
import binascii
import logging
import re
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TimeSelector,
)

from .const import (
    CONF_INSTALLATION_ID,
    CONF_JITTER_MINUTES,
    CONF_MAX_BACKFILL_DAYS,
    CONF_PASSWORD,
    CONF_RUN_AT_TIME,
    CONF_TARIFF_NAMES,
    CONF_TOTP_SECRET,
    CONF_USERNAME,
    DEFAULT_JITTER_MINUTES,
    DEFAULT_MAX_BACKFILL_DAYS,
    DEFAULT_RUN_AT_TIME,
    DOMAIN,
)
from .tariffs import TARIFF_OPTIONS, normalize_tariff_names

_LOGGER = logging.getLogger(__name__)


def _normalize_totp_secret(raw: str) -> str:
    """Accept a base32 TOTP secret (with or without spacing) and return it clean.

    myEKZ presents the TOTP setup page with a QR code and a "can't scan QR
    code" link that reveals the manual-entry secret, typically shown as
    uppercase base32 in space-separated groups. We accept that format as-is
    (spaces/dashes/underscores stripped, case-folded to upper) and raise
    ValueError with a human-readable message if the result isn't valid base32.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    s = re.sub(r"[\s\-_]", "", s).upper()
    if not re.fullmatch(r"[A-Z2-7]+=*", s):
        raise ValueError(
            "TOTP secret contains non-base32 characters; expected A-Z and 2-7 only"
        )
    try:
        padding = "=" * ((8 - len(s) % 8) % 8)
        base64.b32decode(s + padding, casefold=False)
    except binascii.Error as exc:
        raise ValueError(f"TOTP secret is not valid base32: {exc}") from exc
    return s


def _tariff_selector() -> SelectSelector:
    """Multi-select dropdown of every EKZ tariff name documented in the API,
    plus a free-text fallback so users on rare variants (e.g. Einsiedeln `_E`
    suffixes, `_woSDL` / `_inclFees` variants) can still type theirs."""
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=v, label=l) for v, l in TARIFF_OPTIONS],
            multiple=True,
            custom_value=True,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _user_schema(defaults: Optional[Dict[str, Any]] = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=d.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD, default=d.get(CONF_PASSWORD, "")): str,
            vol.Optional(CONF_TOTP_SECRET, default=d.get(CONF_TOTP_SECRET, "")): str,
            vol.Required(CONF_INSTALLATION_ID, default=d.get(CONF_INSTALLATION_ID, "")): str,
            vol.Optional(
                CONF_TARIFF_NAMES,
                default=normalize_tariff_names(d.get(CONF_TARIFF_NAMES)),
            ): _tariff_selector(),
            vol.Optional(
                CONF_RUN_AT_TIME,
                default=d.get(CONF_RUN_AT_TIME, DEFAULT_RUN_AT_TIME),
            ): TimeSelector(),
            vol.Optional(
                CONF_JITTER_MINUTES,
                default=d.get(CONF_JITTER_MINUTES, DEFAULT_JITTER_MINUTES),
            ): vol.All(int, vol.Range(min=0, max=720)),
            vol.Optional(
                CONF_MAX_BACKFILL_DAYS,
                default=d.get(CONF_MAX_BACKFILL_DAYS, DEFAULT_MAX_BACKFILL_DAYS),
            ): vol.All(int, vol.Range(min=0)),
        }
    )


class EkzConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Initial setup via UI."""

    VERSION = 1

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        # NOTE: we intentionally don't do a live myEKZ login here. myEKZ's TOTP
        # is single-use per 30-second window, and the coordinator's first real
        # login would land inside the same window and get rejected. We validate
        # only what we can check locally (TOTP shape) and let the initial
        # import's login be the single authoritative credential check; any
        # error surfaces in the integration's log.
        errors: Dict[str, str] = {}
        if user_input is not None:
            try:
                user_input[CONF_TOTP_SECRET] = _normalize_totp_secret(
                    user_input.get(CONF_TOTP_SECRET, "")
                )
            except ValueError as exc:
                _LOGGER.warning("EKZ TOTP secret rejected: %s", exc)
                errors[CONF_TOTP_SECRET] = "invalid_totp"
            else:
                user_input[CONF_TARIFF_NAMES] = normalize_tariff_names(
                    user_input.get(CONF_TARIFF_NAMES)
                )
                await self.async_set_unique_id(user_input[CONF_INSTALLATION_ID])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"EKZ {user_input[CONF_INSTALLATION_ID]}",
                    data=user_input,
                )
        return self.async_show_form(
            step_id="user", data_schema=_user_schema(user_input), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "EkzOptionsFlow":
        # Newer HA (2024.12+) injects `config_entry` as a read-only property on
        # OptionsFlow; older versions expected us to stash it in __init__. Not
        # overriding __init__ works on both.
        return EkzOptionsFlow()


class EkzOptionsFlow(config_entries.OptionsFlow):
    """Edit tariffs / schedule / backfill without re-entering credentials."""

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        if user_input is not None:
            user_input[CONF_TARIFF_NAMES] = normalize_tariff_names(
                user_input.get(CONF_TARIFF_NAMES)
            )
            return self.async_create_entry(title="", data=user_input)

        current = {
            CONF_TARIFF_NAMES: normalize_tariff_names(
                self.config_entry.options.get(
                    CONF_TARIFF_NAMES, self.config_entry.data.get(CONF_TARIFF_NAMES)
                )
            ),
            CONF_RUN_AT_TIME: self.config_entry.options.get(
                CONF_RUN_AT_TIME,
                self.config_entry.data.get(CONF_RUN_AT_TIME, DEFAULT_RUN_AT_TIME),
            ),
            CONF_JITTER_MINUTES: self.config_entry.options.get(
                CONF_JITTER_MINUTES,
                self.config_entry.data.get(CONF_JITTER_MINUTES, DEFAULT_JITTER_MINUTES),
            ),
            CONF_MAX_BACKFILL_DAYS: self.config_entry.options.get(
                CONF_MAX_BACKFILL_DAYS,
                self.config_entry.data.get(CONF_MAX_BACKFILL_DAYS, DEFAULT_MAX_BACKFILL_DAYS),
            ),
        }
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TARIFF_NAMES, default=current[CONF_TARIFF_NAMES]
                ): _tariff_selector(),
                vol.Optional(
                    CONF_RUN_AT_TIME, default=current[CONF_RUN_AT_TIME]
                ): TimeSelector(),
                vol.Optional(
                    CONF_JITTER_MINUTES, default=current[CONF_JITTER_MINUTES]
                ): vol.All(int, vol.Range(min=0, max=720)),
                vol.Optional(
                    CONF_MAX_BACKFILL_DAYS, default=current[CONF_MAX_BACKFILL_DAYS]
                ): vol.All(int, vol.Range(min=0)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
