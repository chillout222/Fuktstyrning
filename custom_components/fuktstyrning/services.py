"""Service registration for Fuktstyrning integration.

Compatible with both old (<2024.9) and new Home Assistant
versions. Falls back gracefully if the new helpers.service
API is missing.
"""

from __future__ import annotations

import logging
from typing import Callable, Set

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    SERVICE_UPDATE_SCHEDULE,
    SERVICE_RESET_COST_SAVINGS,
    SERVICE_SET_MAX_HUMIDITY,
    CONF_MAX_HUMIDITY,
    ATTR_ENTITY_ID,
    SMART_SWITCH_UNIQUE_ID,
)

_LOGGER = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Back‑compat: resolve helpers for entity‑target extraction
# -----------------------------------------------------------------------------
try:
    # New style (≈ 2024.9+) – fat helper module
    from homeassistant.helpers import service as _hass_service  # type: ignore

    ENTITY_SERVICE_SCHEMA = _hass_service.ENTITY_SERVICE_SCHEMA  # noqa: N816
    async_extract_entity_ids: Callable[
        [HomeAssistant, ServiceCall, bool], Set[str]
    ] = _hass_service.async_extract_entity_ids
except (ImportError, AttributeError):
    # Older HA core – no helpers.service module
    _LOGGER.debug("helpers.service not found – falling back to minimal schema")

    ENTITY_SERVICE_SCHEMA = vol.Schema(
        {vol.Required(ATTR_ENTITY_ID): cv.entity_id}
    )  # type: ignore[assignment]

    async def async_extract_entity_ids(
        hass: HomeAssistant, call: ServiceCall, _: bool = True
    ) -> Set[str]:
        """Very small fallback that just returns the provided entity_id(s)."""
        ent_id = call.data.get(ATTR_ENTITY_ID)
        if ent_id is None:
            return set()
        if isinstance(ent_id, list):
            return set(ent_id)
        return {ent_id}

# -----------------------------------------------------------------------------
# Service registration entry point
# -----------------------------------------------------------------------------


async def async_register_services(
    hass: HomeAssistant, entry: ConfigEntry, controller
) -> None:
    """Register all custom services for Fuktstyrning."""

    # ---------------------------------------------------------------------
    # Helper to resolve which controller instance owns a given entity
    # ---------------------------------------------------------------------

    def get_controller(entity_id: str):
        for data in hass.data.get(DOMAIN, {}).values():
            ctrl = data.get("controller")
            if not ctrl:
                continue
            # Match physical switch, smart-control switch or cost savings sensor
            if (
                # Fysisk väggplugg (direktstyrning)
                ctrl.dehumidifier_switch == entity_id
                # Logisk smart‑switch (sätts så fort switch‑plattformen laddas)
                or ctrl.smart_switch_entity_id == entity_id
                # Fallback om tjänsten hinner gå innan raden ovan är satt
                or entity_id.endswith(SMART_SWITCH_UNIQUE_ID)
                # Kost‑sensor
                or entity_id.endswith("cost_savings")
            ):
                return ctrl
        return None

    # ------------------------------------------------------------------
    # Individual service handlers
    # ------------------------------------------------------------------

    async def handle_update_schedule(call: ServiceCall) -> None:
        entity_ids = await async_extract_entity_ids(hass, call)
        if not entity_ids:
            _LOGGER.warning("No entity_id provided to update_schedule call")
        for eid in entity_ids:
            ctrl = get_controller(eid)
            if ctrl is None:
                _LOGGER.error("Could not find controller for %s", eid)
                continue
            await ctrl._create_daily_schedule()
            _LOGGER.info("Manually updated schedule for %s", eid)

    async def handle_reset_cost_savings(call: ServiceCall) -> None:
        entity_ids = await async_extract_entity_ids(hass, call)
        if not entity_ids:
            _LOGGER.warning("No entity_id provided to reset_cost_savings call")
        for eid in entity_ids:
            ctrl = get_controller(eid)
            if ctrl is None:
                _LOGGER.error("Could not find controller for %s", eid)
                continue
            ctrl.cost_savings = 0
            _LOGGER.info("Reset cost savings for %s", eid)

    async def handle_set_max_humidity(call: ServiceCall) -> None:
        entity_ids = await async_extract_entity_ids(hass, call)
        max_humidity = call.data[CONF_MAX_HUMIDITY]
        if not entity_ids:
            _LOGGER.warning("No entity_id provided to set_max_humidity call")
        for eid in entity_ids:
            ctrl = get_controller(eid)
            if ctrl is None:
                _LOGGER.error("Could not find controller for %s", eid)
                continue
            ctrl.max_humidity = max_humidity
            await ctrl._update_schedule()
            _LOGGER.info("Set max humidity to %s%% for %s", max_humidity, eid)

    # ------------------------------------------------------------------
    # Register the three public services
    # ------------------------------------------------------------------

    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_SCHEDULE,
        handle_update_schedule,
        schema=ENTITY_SERVICE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_COST_SAVINGS,
        handle_reset_cost_savings,
        schema=ENTITY_SERVICE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MAX_HUMIDITY,
        handle_set_max_humidity,
        schema=ENTITY_SERVICE_SCHEMA.extend(
            {
                vol.Required(CONF_MAX_HUMIDITY): vol.All(
                    vol.Coerce(float), vol.Range(min=50, max=90)
                )
            }
        ),
    )
