"""Config flow for Fuktstyrning integration."""
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.entity_registry import async_get

from .const import (
    DOMAIN,
    CONF_HUMIDITY_SENSOR,
    CONF_PRICE_SENSOR,
    CONF_DEHUMIDIFIER_SWITCH,
    CONF_WEATHER_ENTITY,
    CONF_MAX_HUMIDITY,
    DEFAULT_MAX_HUMIDITY,
    CONF_OUTDOOR_HUMIDITY_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
)

_LOGGER = logging.getLogger(__name__)


class FuktstyrningConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fuktstyrning."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Validate the input
            try:
                # Check if entities exist
                hass = self.hass
                
                humidity_sensor = user_input.get(CONF_HUMIDITY_SENSOR)
                if humidity_sensor and not hass.states.get(humidity_sensor):
                    errors[CONF_HUMIDITY_SENSOR] = "entity_not_found"
                    
                price_sensor = user_input.get(CONF_PRICE_SENSOR)
                if price_sensor and not hass.states.get(price_sensor):
                    errors[CONF_PRICE_SENSOR] = "entity_not_found"
                    
                dehumidifier_switch = user_input.get(CONF_DEHUMIDIFIER_SWITCH)
                if dehumidifier_switch and not hass.states.get(dehumidifier_switch):
                    errors[CONF_DEHUMIDIFIER_SWITCH] = "entity_not_found"
                    
                weather_entity = user_input.get(CONF_WEATHER_ENTITY)
                if weather_entity and not hass.states.get(weather_entity):
                    errors[CONF_WEATHER_ENTITY] = "entity_not_found"
                
                outdoor_humidity_sensor = user_input.get(CONF_OUTDOOR_HUMIDITY_SENSOR)
                if outdoor_humidity_sensor and not hass.states.get(outdoor_humidity_sensor):
                    errors[CONF_OUTDOOR_HUMIDITY_SENSOR] = "entity_not_found"
                    
                outdoor_temp_sensor = user_input.get(CONF_OUTDOOR_TEMP_SENSOR)
                if outdoor_temp_sensor and not hass.states.get(outdoor_temp_sensor):
                    errors[CONF_OUTDOOR_TEMP_SENSOR] = "entity_not_found"
                
                if not errors:
                    # Create entry
                    return self.async_create_entry(
                        title=f"Fuktstyrning", 
                        data=user_input
                    )
                    
            except Exception as e:
                _LOGGER.exception("Unexpected exception during config flow")
                errors["base"] = "unknown"

        # Prepare schema
        schema = vol.Schema({
            vol.Required(CONF_HUMIDITY_SENSOR, default="sensor.aqara_t1_innerst_luftfuktighet"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(CONF_PRICE_SENSOR, default="sensor.nordpool_kwh_se3_3_10_025"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(CONF_DEHUMIDIFIER_SWITCH): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Optional(CONF_OUTDOOR_HUMIDITY_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_OUTDOOR_TEMP_SENSOR): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_WEATHER_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            vol.Required(CONF_MAX_HUMIDITY, default=DEFAULT_MAX_HUMIDITY): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=50, max=90, step=1, unit_of_measurement="%"
                )
            ),
        })

        return self.async_show_form(
            step_id="user", 
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return FuktstyrningOptionsFlowHandler(config_entry)


class FuktstyrningOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a option flow for Fuktstyrning."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Handle options flow."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        data = self.config_entry.data

        schema = vol.Schema({
            vol.Required(
                CONF_MAX_HUMIDITY,
                default=options.get(CONF_MAX_HUMIDITY, data.get(CONF_MAX_HUMIDITY, DEFAULT_MAX_HUMIDITY))
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=50, max=90, step=1, unit_of_measurement="%"
                )
            ),
            vol.Optional(
                CONF_OUTDOOR_HUMIDITY_SENSOR,
                default=options.get(CONF_OUTDOOR_HUMIDITY_SENSOR, data.get(CONF_OUTDOOR_HUMIDITY_SENSOR, ""))
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(
                CONF_OUTDOOR_TEMP_SENSOR,
                default=options.get(CONF_OUTDOOR_TEMP_SENSOR, data.get(CONF_OUTDOOR_TEMP_SENSOR, ""))
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(
                CONF_WEATHER_ENTITY,
                default=options.get(CONF_WEATHER_ENTITY, data.get(CONF_WEATHER_ENTITY, ""))
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
        })

        return self.async_show_form(step_id="init", data_schema=schema)
