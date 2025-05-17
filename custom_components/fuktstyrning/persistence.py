"""Persistence module for Fuktstyrning integration."""
import logging
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class Persistence:
    """Handles saving and loading learning data for a config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str, version: int = 1):
        self.hass = hass
        self.entry_id = entry_id
        # Use DOMAIN and entry_id to create a unique storage key
        self.store = Store(hass, version=version, key=f"{DOMAIN}_{entry_id}")

    async def load(self, controller):
        """Load persisted data into the controller learning module."""
        try:
            await controller.learning_module.load_learning_data()
            _LOGGER.debug("Loaded learning data from storage.")
        except Exception as e:  # pylint: disable=broad-except
            _LOGGER.error("Error loading persisted data: %s", e)

    async def save(self, controller):
        """Save controller learning data to storage."""
        try:
            await controller.learning_module.save_learning_data()
            _LOGGER.debug("Saved learning data to storage.")
        except Exception as e:  # pylint: disable=broad-except
            _LOGGER.error("Error saving learning data: %s", e)
