"""Service registration for Fuktstyrning integration."""

import logging
import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import service
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    SERVICE_UPDATE_SCHEDULE,
    SERVICE_RESET_COST_SAVINGS,
    SERVICE_SET_MAX_HUMIDITY,
    CONF_MAX_HUMIDITY,
    ATTR_ENTITY_ID,
)

_LOGGER = logging.getLogger(__name__)

# Accept both data.entity_id and target.entity_id (plus area/device selectors)
SERVICE_SCHEMA = service.ENTITY_SERVICE_SCHEMA


async def async_register_services(hass: HomeAssistant, entry: ConfigEntry, controller):
    """Register all custom services."""

    def get_controller(entity_id: str):
        """Return controller instance that owns the given entity_id."""
        for data in hass.data.get(DOMAIN, {}).values():
            ctrl = data.get("controller")
            if not ctrl:
                continue
            if (
                ctrl.dehumidifier_switch == entity_id
                or ctrl.learning_sensor == entity_id
                or entity_id.endswith("cost_savings")
            ):
                return ctrl
        return None

    async def handle_update_schedule(call: ServiceCall):
        entity_ids = await service.async_extract_entity_ids(hass, call)
        for entity_id in entity_ids:
            ctrl = get_controller(entity_id)
            if not ctrl:
                _LOGGER.error("Could not find controller for %s", entity_id)
                continue
            await ctrl._create_daily_schedule()
            _LOGGER.info("Manually updated schedule for %s", entity_id)

    async def handle_reset_cost_savings(call: ServiceCall):
        entity_ids = await service.async_extract_entity_ids(hass, call)
        for entity_id in entity_ids:
            ctrl = get_controller(entity_id)
            if not ctrl:
                _LOGGER.error("Could not find controller for %s", entity_id)
                continue
            ctrl.cost_savings = 0
            _LOGGER.info("Reset cost savings for %s", entity_id)

    async def handle_set_max_humidity(call: ServiceCall):
        entity_ids = await service.async_extract_entity_ids(hass, call)
        max_humidity = call.data[CONF_MAX_HUMIDITY]
        for entity_id in entity_ids:
            ctrl = get_controller(entity_id)
            if not ctrl:
                _LOGGER.error("Could not find controller for %s", entity_id)
                continue
            ctrl.max_humidity = max_humidity
            await ctrl._update_schedule()
            _LOGGER.info("Set max humidity to %s%% for %s", max_humidity, entity_id)

    # Register services
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_SCHEDULE,
        handle_update_schedule,
        schema=SERVICE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_COST_SAVINGS,
        handle_reset_cost_savings,
        schema=SERVICE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MAX_HUMIDITY,
        handle_set_max_humidity,
        schema=SERVICE_SCHEMA.extend(
            {
                vol.Required(CONF_MAX_HUMIDITY): vol.All(
                    vol.Coerce(float), vol.Range(min=50, max=90)
                )
            }
        ),
    )
