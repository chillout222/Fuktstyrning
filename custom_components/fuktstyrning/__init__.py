"""The Fuktstyrning integration."""
import logging
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, PLATFORMS, SERVICE_LEARNING_RESET
from .controller import FuktstyrningController
from .scheduler import Scheduler
from .persistence import Persistence
from .services import async_register_services
from .learning import DehumidifierLearningModule  # <- behövs för type check

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

    # 6) Registrera custom services + learning_reset
    await async_register_services(hass, entry, controller)

    async def _async_learning_reset(call):
        """Handle fuktstyrning.learning_reset."""
        try:
            target_id = call.data.get("entry_id")
            
            if target_id:
                # Kontrollera att entry_id finns
                if target_id not in hass.data[DOMAIN]:
                    _LOGGER.error("Invalid entry_id: %s", target_id)
                    return
                ctrls = [hass.data[DOMAIN][target_id]["controller"]]
            else:
                ctrls = [v["controller"] for v in hass.data[DOMAIN].values()]
                
            for ctrl in filter(None, ctrls):
                await ctrl.learning_module.async_reset()
                _LOGGER.warning("Learning module reset for %s", ctrl.entry_id)
        except Exception as e:
            _LOGGER.error("Error during learning reset: %s", str(e))

    hass.services.async_register(
        DOMAIN,
        SERVICE_LEARNING_RESET,
        _async_learning_reset,
    )

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        controller = data["controller"]
        await controller.shutdown()
    return unload_ok