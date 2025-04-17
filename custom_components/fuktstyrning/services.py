"""Service registrering för Fuktstyrning integration."""
import logging
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, SERVICE_UPDATE_SCHEDULE, SERVICE_RESET_COST_SAVINGS, SERVICE_SET_MAX_HUMIDITY, CONF_MAX_HUMIDITY, ATTR_ENTITY_ID

_LOGGER = logging.getLogger(__name__)

async def async_register_services(hass: HomeAssistant, entry: ConfigEntry, controller):
    """Register all custom services."""

    def get_controller(entity_id: str):
        for data in hass.data[DOMAIN].values():
            if data['controller'].dehumidifier_switch == entity_id or \
               'sensor.fuktstyrning_cost_savings' in entity_id:
                return data['controller']
        return None

    async def handle_update_schedule(call: ServiceCall):
        entity_id = call.data[ATTR_ENTITY_ID]
        ctrl = get_controller(entity_id)
        if ctrl:
            await ctrl._create_daily_schedule()
            _LOGGER.info(f"Manually updated schedule for {entity_id}")
        else:
            _LOGGER.error(f"Could not find controller for entity {entity_id}")

    async def handle_reset_cost_savings(call: ServiceCall):
        entity_id = call.data[ATTR_ENTITY_ID]
        ctrl = get_controller(entity_id)
        if ctrl:
            ctrl.cost_savings = 0
            _LOGGER.info(f"Reset cost savings for {entity_id}")
        else:
            _LOGGER.error(f"Could not find controller for entity {entity_id}")

    async def handle_set_max_humidity(call: ServiceCall):
        entity_id = call.data[ATTR_ENTITY_ID]
        max_humidity = call.data[CONF_MAX_HUMIDITY]
        ctrl = get_controller(entity_id)
        if ctrl:
            ctrl.max_humidity = max_humidity
            await ctrl._update_schedule()
            _LOGGER.info(f"Set max humidity to {max_humidity}% for {entity_id}")
        else:
            _LOGGER.error(f"Could not find controller for entity {entity_id}")

    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_SCHEDULE, handle_update_schedule,
        schema=vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id})
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RESET_COST_SAVINGS, handle_reset_cost_savings,
        schema=vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id})
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_MAX_HUMIDITY, handle_set_max_humidity,
        schema=vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id, vol.Required(CONF_MAX_HUMIDITY): vol.All(vol.Coerce(float), vol.Range(min=50, max=90))})
    )
