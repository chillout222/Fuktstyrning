"""Scheduling helpers for Fuktstyrning integration."""
import logging
from datetime import timedelta
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

class Scheduler:
    """Handles periodic schedule updates."""

    def __init__(self, hass: HomeAssistant, update_callback, interval_minutes: int = 15):
        self.hass = hass
        self.update_callback = update_callback
        self.interval = timedelta(minutes=interval_minutes)
        self._unsub = None

    async def start(self):
        """Start periodic schedule updates."""
        _LOGGER.debug("Starting schedule interval tracking")
        self._unsub = async_track_time_interval(
            self.hass,
            self.update_callback,
            self.interval,
        )

    def stop(self):
        """Stop schedule updates."""
        if self._unsub:
            _LOGGER.debug("Stopping schedule interval tracking")
            self._unsub()
