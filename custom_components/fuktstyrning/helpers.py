"""Helper methods to create schedule visualization."""
import logging

from homeassistant.const import EVENT_HOMEASSISTANT_START
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.components import input_boolean

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_create_schedule_helpers(hass: HomeAssistant, entry_id: str, controller) -> None:
    """Create input_boolean helpers for visualizing the schedule."""
    # On startup, create input_boolean entities for each hour
    @callback
    async def _async_create_helpers(_):
        """Create the input_boolean helpers."""
        # Create or update an input_boolean for each hour
        for hour in range(24):
            # Create a helper for this hour
            hour_name = f"Hour {hour:02d}:00"
            input_id = f"dehumidifier_hour_{hour:02d}"
            
            # Create or update the input_boolean
            state = controller.schedule.get(hour, False)
            
            # Check if it already exists
            entity_id = f"input_boolean.{input_id}"
            if hass.states.get(entity_id) is None:
                # Create it using the helper API
                await input_boolean.async_create(
                    hass,
                    input_id,
                    hour_name,
                    icon="mdi:clock-time-two-outline",
                )
            
            # Set the initial state
            service = "turn_on" if state else "turn_off"
            await hass.services.async_call(
                input_boolean.DOMAIN,
                service,
                {"entity_id": entity_id},
            )
    
    # Register to track controller schedule changes
    @callback
    async def _async_schedule_updated(event: Event):
        """Update input_boolean helpers when schedule changes."""
        if event.data.get("entity_id") == f"switch.fuktstyrning_dehumidifier_smart_control_{entry_id}":
            # Update all hourly helpers
            for hour in range(24):
                state = controller.schedule.get(hour, False)
                entity_id = f"input_boolean.dehumidifier_hour_{hour:02d}"
                
                # Set state if it exists
                if hass.states.get(entity_id) is not None:
                    service = "turn_on" if state else "turn_off"
                    await hass.services.async_call(
                        input_boolean.DOMAIN,
                        service,
                        {"entity_id": entity_id},
                    )
    
    # Create helpers on startup
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_create_helpers)
    
    # Track schedule changes
    async_track_state_change_event(
        hass, 
        [f"switch.fuktstyrning_dehumidifier_smart_control_{entry_id}"], 
        _async_schedule_updated
    )
