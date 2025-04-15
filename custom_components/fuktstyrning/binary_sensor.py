"""Binary sensor platform for Fuktstyrning integration."""
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    BINARY_SENSOR_OPTIMAL_RUNNING_UNIQUE_ID,
    BINARY_SENSOR_OPTIMAL_RUNNING_NAME,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Fuktstyrning binary sensor platform."""
    controller = hass.data[DOMAIN][entry.entry_id]["controller"]
    
    entities = [
        OptimalRunningBinarySensor(hass, entry, controller),
    ]
    
    async_add_entities(entities)


class OptimalRunningBinarySensor(BinarySensorEntity):
    """Binary sensor to indicate optimal times for running the dehumidifier."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:clock-time-five-outline"

    def __init__(self, hass, entry, controller):
        """Initialize the binary sensor."""
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._attr_unique_id = f"{entry.entry_id}_{BINARY_SENSOR_OPTIMAL_RUNNING_UNIQUE_ID}"
        self._attr_name = BINARY_SENSOR_OPTIMAL_RUNNING_NAME
        self._attr_is_on = False
        self._attr_extra_state_attributes = {
            "current_hour_price": None,
            "average_price_today": None,
            "is_below_average": False,
        }

    async def async_update(self) -> None:
        """Update the binary sensor."""
        # Get current hour
        from datetime import datetime
        current_hour = datetime.now().hour
        
        # Check if this hour is in the optimal schedule
        is_optimal = self.controller.schedule.get(current_hour, False)
        self._attr_is_on = is_optimal
        
        # Get current price and average price
        price_sensor = self.hass.states.get(self.controller.price_sensor)
        if price_sensor and "today" in price_sensor.attributes:
            current_price = float(price_sensor.state)
            today_prices = price_sensor.attributes.get("today", [])
            if today_prices:
                avg_price = sum(today_prices) / len(today_prices)
                self._attr_extra_state_attributes.update({
                    "current_hour_price": current_price,
                    "average_price_today": avg_price,
                    "is_below_average": current_price < avg_price,
                })
