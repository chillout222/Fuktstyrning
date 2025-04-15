"""Switch platform for Fuktstyrning integration."""
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_ON,
    SERVICE_TURN_OFF,
)

from .const import (
    DOMAIN,
    SWITCH_UNIQUE_ID,
    SWITCH_NAME,
    ATTR_OVERRIDE_ACTIVE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Fuktstyrning switch platform."""
    controller = hass.data[DOMAIN][entry.entry_id]["controller"]
    
    entities = [
        DehumidifierControlSwitch(hass, entry, controller),
    ]
    
    async_add_entities(entities)


class DehumidifierControlSwitch(SwitchEntity):
    """Switch to enable/disable smart control of dehumidifier."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:dehumidifier"

    def __init__(self, hass, entry, controller):
        """Initialize the switch."""
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._attr_unique_id = f"{entry.entry_id}_{SWITCH_UNIQUE_ID}"
        self._attr_name = SWITCH_NAME
        self._is_on = True
        self._attr_extra_state_attributes = {
            ATTR_OVERRIDE_ACTIVE: False,
        }

    @property
    def is_on(self) -> bool:
        """Return true if the smart control is enabled."""
        return self._is_on

    async def async_turn_on(self, **kwargs):
        """Turn on the smart control."""
        self._is_on = True
        self.controller.override_active = False
        # Trigger schedule update
        await self.controller._update_schedule()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn off the smart control."""
        self._is_on = False
        # Turn off the dehumidifier
        await self.hass.services.async_call(
            "switch", SERVICE_TURN_OFF, {ATTR_ENTITY_ID: self.controller.dehumidifier_switch}
        )
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update the switch state."""
        self._attr_extra_state_attributes[ATTR_OVERRIDE_ACTIVE] = self.controller.override_active
