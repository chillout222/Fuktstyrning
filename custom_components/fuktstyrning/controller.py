"""Fuktstyrning – Controller
================================

En komplett, körbar version som:
* skickar **self** till `DehumidifierLearningModule`
* hanterar `schedule_created_date`, `schedule` som `dict[int, bool]`
* exponerar `cost_savings` för sensorerna 
* innehåller alla hjälpfunktioner (prisprognos, optimering, on/off etc.)

Drop‑in‑ersättning för `custom_components/fuktstyrning/controller.py`.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, time
from typing import Any, Dict, List, Optional

import homeassistant.util.dt as dt_util
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.recorder import get_instance
from homeassistant.helpers.storage import Store
from homeassistant.helpers.event import async_track_state_change

from .learning import DehumidifierLearningModule
from .const import (
    CONF_HUMIDITY_SENSOR,
    CONF_PRICE_SENSOR,
    CONF_DEHUMIDIFIER_SWITCH,
    CONF_WEATHER_ENTITY,
    CONF_OUTDOOR_HUMIDITY_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_POWER_SENSOR,
    CONF_ENERGY_SENSOR,
    CONF_VOLTAGE_SENSOR,
    CONF_MAX_HUMIDITY,
    DEFAULT_MAX_HUMIDITY,
    CONTROLLER_STORAGE_KEY,
    LEARNING_STORAGE_KEY,
)

_LOGGER = logging.getLogger(__name__)


class FuktstyrningController:  # pylint: disable=too-many-instance-attributes
    """High‑level logic for humidity‑based dehumidifier control."""

    # ---------------------------------------------------------------------
    # Construction / attributes
    # ---------------------------------------------------------------------

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry

        # Config options
        self.humidity_sensor: str | None = entry.data.get(CONF_HUMIDITY_SENSOR)
        self.price_sensor: str | None = entry.data.get(CONF_PRICE_SENSOR)
        self.dehumidifier_switch: str | None = entry.data.get(CONF_DEHUMIDIFIER_SWITCH)
        self.weather_entity: str | None = entry.data.get(CONF_WEATHER_ENTITY)
        self.outdoor_humidity_sensor: str | None = entry.data.get(CONF_OUTDOOR_HUMIDITY_SENSOR)
        self.outdoor_temp_sensor: str | None = entry.data.get(CONF_OUTDOOR_TEMP_SENSOR)
        self.power_sensor: str | None = entry.data.get(CONF_POWER_SENSOR)
        self.energy_sensor: str | None = entry.data.get(CONF_ENERGY_SENSOR)
        self.voltage_sensor: str | None = entry.data.get(CONF_VOLTAGE_SENSOR)

        self.max_humidity: float = entry.data.get(CONF_MAX_HUMIDITY, DEFAULT_MAX_HUMIDITY)

        # Runtime state
        self.schedule: Dict[int, bool] = {}
        self.schedule_created_date: Optional[datetime] = None
        self.override_active: bool = False
        self.cost_savings: float = 0.0
        self._store = Store(hass, 1, "fuktstyrning_controller_data")
        # Entity ID for the smart control switch
        self.smart_switch_entity_id: Optional[str] = None

        # simple defaults for learning
        self.dehumidifier_data: Dict[str, Any] = {
            "time_to_reduce": {"70_to_65": 30, "65_to_60": 45},
            "time_to_increase": {"60_to_65": 15, "65_to_70": 30},
        }
        
        # Learning module gets reference to controller so it can read data
        self.learning_module = DehumidifierLearningModule(hass, self)

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Initialize the controller."""
        self._store = Store(self.hass, 1, CONTROLLER_STORAGE_KEY)
        stored_data = await self._store.async_load()
        
        if stored_data:
            self.dehumidifier_data = stored_data.get("dehumidifier_data", {})
            self.cost_savings = stored_data.get("cost_savings", 0.0)
            _LOGGER.debug("Loaded controller data: %s", stored_data)
        
        # First initialize learning module
        await self.learning_module.initialize()
        # Register callback for price data readiness
        if self.price_sensor:
            self._price_unsub = async_track_state_change(
                self.hass,
                self.price_sensor,
                self.async_handle_price_ready,
            )
        
        # Then setup controller
        await self.setup()

    async def setup(self) -> None:
        """Set up the controller components."""
        await self._create_daily_schedule()
        _LOGGER.debug("Fuktstyrning controller initialized")

    async def shutdown(self) -> None:
        # Unregister price-ready listener
        if getattr(self, '_price_unsub', None):
            self._price_unsub()
        # Save data
        await self._store.async_save({
            "dehumidifier_data": self.dehumidifier_data,
            "cost_savings": self.cost_savings
        })
        _LOGGER.debug("Controller data saved")
        
        # Shut down learning module
        await self.learning_module.shutdown()
        _LOGGER.debug("Controller shutdown complete")

    # ------------------------------------------------------------------
    # Public entry for Scheduler (keeps original name)
    # ------------------------------------------------------------------

    async def _update_schedule(self, now=None):  # pylint: disable=unused-argument
        """Called by Scheduler every N minutes – wraps async_tick()."""
        await self.async_tick()

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------ (invoked every minute by integration)
    # ------------------------------------------------------------------

    async def async_tick(self) -> None:
        """Main loop called by the integration's time pattern trigger."""
        now = dt_util.now()
        # override if humidity > threshold
        humidity_state = self.hass.states.get(self.humidity_sensor)
        if not humidity_state or humidity_state.state in ("unknown", "unavailable"):
            _LOGGER.warning("Humidity sensor unavailable: %s", self.humidity_sensor)
            return
        try:
            current_humidity = float(humidity_state.state)
        except ValueError:
            _LOGGER.warning("Invalid humidity value: %s", humidity_state.state)
            return

        # --- record humidity data after reading current_humidity ---
        try:
            weather = self.hass.states.get(self.weather_entity).state if self.weather_entity else None
            out_rh = self.hass.states.get(self.outdoor_humidity_sensor)
            out_t = self.hass.states.get(self.outdoor_temp_sensor)
            temp = float(self.hass.states.get(self.humidity_sensor).attributes.get("temperature", "nan"))
            power = float(self.hass.states.get(self.power_sensor).state) if self.power_sensor else None
            energy = float(self.hass.states.get(self.energy_sensor).state) if self.energy_sensor else None

            self.learning_module.record_humidity_data(
                humidity=current_humidity,
                dehumidifier_on=self.override_active or self.schedule.get(now.hour, False),
                temperature=temp,
                weather=weather,
                outdoor_humidity=float(out_rh.state) if out_rh else None,
                outdoor_temp=float(out_t.state) if out_t else None,
                power=power,
                energy=energy,
            )
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error("Error recording humidity data: %s", exc)

        if current_humidity >= self.max_humidity and not self.override_active:
            await self._turn_on_dehumidifier()
            self.override_active = True
            return
        if self.override_active and current_humidity < self.max_humidity - 5:
            self.override_active = False

        # follow schedule if no override
        if not self.override_active:
            await self._follow_schedule()

        await self._update_cost_savings()

    # ------------------------------------------------------------------
    # Schedule handling
    # ------------------------------------------------------------------

    async def _create_daily_schedule(self) -> None:
        """Build a 24‑h schedule based on price forecast and humidity."""
        price_forecast = self._get_price_forecast()
        if not price_forecast:
            _LOGGER.warning("No price forecast – skipping schedule")
            return

        # ---  Hitta hur många timmar som faktiskt BEHÖVS ---------------
        humid_state = self.hass.states.get(self.humidity_sensor)
        current_humidity = float(humid_state.state) if humid_state else 0.0
        target_humidity = self.max_humidity - 5
        
        # Safely get temperature
        temperature = None
        humidity_state = self.hass.states.get(self.humidity_sensor)
        if humidity_state and humidity_state.attributes.get("temperature") is not None:
            try:
                temperature = float(humidity_state.attributes.get("temperature"))
            except (ValueError, TypeError):
                pass
                
        # Safely get weather
        weather = None
        if self.weather_entity:
            weather_state = self.hass.states.get(self.weather_entity)
            if weather_state and weather_state.state not in ("unknown", "unavailable"):
                weather = weather_state.state
        hours_needed = self.learning_module.predict_hours_needed(
            current_humidity=current_humidity,
            target_humidity=target_humidity,
            temperature=temperature,
            weather=weather,
        )

        sorted_hours = sorted(range(24), key=lambda h: price_forecast[h])
        self.schedule = {h: False for h in range(24)}
        for h in sorted_hours[:hours_needed]:
            self.schedule[h] = True

        self.schedule_created_date = dt_util.now()
        _LOGGER.info("Generated schedule %s (created %s)", self.schedule, self.schedule_created_date)

    async def _follow_schedule(self) -> None:
        now_hour = dt_util.now().hour
        should_run = self.schedule.get(now_hour, False)
        if should_run:
            await self._turn_on_dehumidifier()
        else:
            await self._turn_off_dehumidifier()

    # ------------------------------------------------------------------
    # Helpers for cost savings
    # ------------------------------------------------------------------

    async def _update_cost_savings(self) -> None:
        forecast = self._get_price_forecast()
        if not forecast:
            return
        baseline_price = sum(forecast) / len(forecast)
        hours_on = sum(1 for v in self.schedule.values() if v)
        always_on_hours = 8  # assume historical pattern
        hours_saved = max(0, always_on_hours - hours_on)
        self.cost_savings = round(baseline_price * hours_saved, 2)

    # ------------------------------------------------------------------
    # Switch helpers
    # ------------------------------------------------------------------

    async def _turn_on_dehumidifier(self) -> None:
        await self.hass.services.async_call("switch", "turn_on", {"entity_id": self.dehumidifier_switch}, blocking=True)

    async def _turn_off_dehumidifier(self) -> None:
        await self.hass.services.async_call("switch", "turn_off", {"entity_id": self.dehumidifier_switch}, blocking=True)

    # ------------------------------------------------------------------
    # Forecast helpers (very lightweight)
    # ------------------------------------------------------------------

    def _get_price_forecast(self) -> List[float] | None:
        st = self.hass.states.get(self.price_sensor)
        if not st:
            return None
        forecast = st.attributes.get("forecast")
        if isinstance(forecast, list) and all(isinstance(e, dict) and "price" in e for e in forecast):
            return [float(e["price"]) for e in forecast][:24]
        # Fallback: if state itself is number replicate 24 ggr
        try:
            price_now = float(st.state)
            return [price_now] * 24
        except ValueError:
            return None

    async def _get_rain_forecast(self) -> int:
        if not self.weather_entity:
            return 0
        st = self.hass.states.get(self.weather_entity)
        if not st:
            return 0
        fc = st.attributes.get("forecast", [])
        return sum(1 for item in fc[:24] if item.get("precipitation", 0) > 0)

    async def async_handle_price_ready(
        self, entity_id, old_state, new_state
    ) -> None:
        """Handle price data readiness and trigger daily schedule."""
        if new_state and new_state.attributes.get("tomorrow_valid"):
            await self._create_daily_schedule()
