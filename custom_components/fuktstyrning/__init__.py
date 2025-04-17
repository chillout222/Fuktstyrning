"""The Fuktstyrning integration."""
import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, PLATFORMS
from .controller import FuktstyrningController
from .scheduler import Scheduler
from .persistence import Persistence
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Fuktstyrning component."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fuktstyrning from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # 1) Skapa controller och spara den
    controller = FuktstyrningController(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = {"controller": controller}

    # 2) Initiera controller-logik
    await controller.initialize()

    # 3) Starta plattformar (sensor, switch, binary_sensor)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 4) Ladda sparad inlärningsdata
    persistence = Persistence(hass, entry.entry_id)
    await persistence.load(controller)
    # Attach persistence for shutdown
    controller.persistence = persistence

    # 5) Starta periodisk schemaläggning
    scheduler = Scheduler(hass, controller._update_schedule)
    await scheduler.start()
    # Attach scheduler for shutdown
    controller.scheduler = scheduler

    # 6) Registrera custom services
    await async_register_services(hass, entry, controller)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        controller = data["controller"]
        await controller.shutdown()
    return unload_ok