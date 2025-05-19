"""Persistence module for Fuktstyrning integration."""
import logging
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

class Persistence:
    """Handles saving and loading learning data for a config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str):
        self.hass = hass
        self.entry_id = entry_id

    async def load(self, controller):
        """Delegate loading to ``controller.learning_module``."""
        try:
            await controller.learning_module.load_learning_data()
            _LOGGER.debug("Loaded learning data from storage.")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            _LOGGER.error("Error processing persisted data during load: %s", e)
        except Exception as e:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected error loading persisted data: %s", e)

    async def save(self, controller):
        """Delegate saving to ``controller.learning_module``."""
        try:
            await controller.learning_module.save_learning_data()
            _LOGGER.debug("Saved learning data to storage.")
        except (TypeError, ValueError) as e:
            _LOGGER.error("Error serializing learning data for saving: %s", e)
        except Exception as e:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected error saving learning data: %s", e)
