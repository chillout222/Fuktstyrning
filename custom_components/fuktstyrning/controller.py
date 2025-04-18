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
from datetime import datetime, time
from typing import Any, Dict, List, Optional

import homeassistant.util.dt as dt_util
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

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

        # Learning module gets reference to controller so den kan läsa data
        self.learning_module = DehumidifierLearningModule(hass, self)

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

        # simple defaults for learning
        self.dehumidifier_data: Dict[str, Any] = {
            "time_to_reduce": {"70_to_65": 30, "65_to_60": 45},
            "time_to_increase": {"60_to_65": 15, "65_to_70": 30},
        }

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        await self.learning_module.initialize()
        await self._create_daily_schedule()
        _LOGGER.debug("Fuktstyrning controller initialised")

    async def shutdown(self) -> None:
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
        # regenerate schedule daily at 13:00
        if now.hour == 13 and now.minute == 0:
            await self._create_daily_schedule()

        # override if humidity > threshold
        humidity_state = self.hass.states.get(self.humidity_sensor)
        if not humidity_state or humidity_state.state in ("unknown", "unavailable"):
            return
        try:
            current_humidity = float(humidity_state.state)
        except ValueError:
            return

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

        # simple runtime calc:  if current humidity < max‑5 → 2 h, else 4 h
        humid_state = self.hass.states.get(self.humidity_sensor)
        current_humidity = float(humid_state.state) if humid_state else 0.0
        hours_needed = 4 if current_humidity > self.max_humidity - 5 else 2

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
