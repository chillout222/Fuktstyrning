import sys
import types
from datetime import datetime

# Stub homeassistant.util.dt
util_dt = types.ModuleType('homeassistant.util.dt')
util_dt.now = lambda: datetime.now()

util = types.ModuleType('homeassistant.util')
util.dt = util_dt

# Stub homeassistant.core
core = types.ModuleType('homeassistant.core')
class HomeAssistant: ...
core.HomeAssistant = HomeAssistant

# Stub config entries
config_entries = types.ModuleType('homeassistant.config_entries')
class ConfigEntry:
    def __init__(self, data=None):
        self.data = data or {}
config_entries.ConfigEntry = ConfigEntry

# Stub helpers.storage
helpers_storage = types.ModuleType('homeassistant.helpers.storage')
class Store:
    def __init__(self, hass, version, key):
        self.hass = hass
        self.version = version
        self.data = None
    async def async_save(self, data):
        self.data = data
    async def async_load(self):
        return self.data
helpers_storage.Store = Store

# Stub helpers.event
helpers_event = types.ModuleType('homeassistant.helpers.event')
async def async_track_state_change_event(*args, **kwargs):
    return None
async def async_call_later(*args, **kwargs):
    return None
async def async_track_time_interval(*args, **kwargs):
    return None
helpers_event.async_track_state_change_event = async_track_state_change_event
helpers_event.async_call_later = async_call_later
helpers_event.async_track_time_interval = async_track_time_interval

# Stub helpers.update_coordinator
helpers_update = types.ModuleType('homeassistant.helpers.update_coordinator')
class UpdateFailed(Exception):
    pass
helpers_update.UpdateFailed = UpdateFailed

# Stub components.recorder
components_recorder = types.ModuleType('homeassistant.components.recorder')
def get_instance(*args, **kwargs):
    return None
components_recorder.get_instance = get_instance

# Constants
const = types.ModuleType('homeassistant.const')
const.STATE_UNKNOWN = 'unknown'
const.STATE_UNAVAILABLE = 'unavailable'

# Exceptions
exceptions = types.ModuleType('homeassistant.exceptions')
class ConfigEntryNotReady(Exception):
    pass
exceptions.ConfigEntryNotReady = ConfigEntryNotReady

# Aggregate helpers
helpers = types.ModuleType('homeassistant.helpers')
helpers.storage = helpers_storage
helpers.event = helpers_event

# Root homeassistant module
ha = types.ModuleType('homeassistant')
ha.core = core
ha.config_entries = config_entries
ha.helpers = helpers
ha.util = util
ha.components = types.ModuleType('homeassistant.components')
ha.components.recorder = components_recorder
ha.const = const
ha.exceptions = exceptions

# Register modules
sys.modules.setdefault('homeassistant', ha)
sys.modules.setdefault('homeassistant.core', core)
sys.modules.setdefault('homeassistant.config_entries', config_entries)
sys.modules.setdefault('homeassistant.helpers', helpers)
sys.modules.setdefault('homeassistant.helpers.storage', helpers_storage)
sys.modules.setdefault('homeassistant.helpers.event', helpers_event)
sys.modules.setdefault('homeassistant.helpers.update_coordinator', helpers_update)
sys.modules.setdefault('homeassistant.components.recorder', components_recorder)
sys.modules.setdefault('homeassistant.util', util)
sys.modules.setdefault('homeassistant.util.dt', util_dt)
sys.modules.setdefault('homeassistant.const', const)
sys.modules.setdefault('homeassistant.exceptions', exceptions)
