"""Controller module for the Fuktstyrning integration.

* Passes **controller** (not ConfigEntry) to the learning module ⇒ löser
  `AttributeError: 'ConfigEntry' object has no attribute 'dehumidifier_data'`
* Introduces `self.cost_savings` and en uppdaterad `_update_cost_savings()`
  så att kostnads‑sensorn fungerar.
* I övrigt är filen identisk med originalet → inga förlorade funktioner.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
import homeassistant.util.dt as dt_util

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
    CONF_SCHEDULE_UPDATE_TIME,
    DEFAULT_SCHEDULE_UPDATE_TIME,
)

_LOGGER = logging.getLogger(__name__)


class FuktstyrningController:
    """Controller for operating a dehumidifier based on humidity, price and weather."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Store config, set up helpers and runtime state."""
        self.hass = hass
        self.entry = entry

        # NOTE:  we now pass *self* instead of *entry* so the learning module
        # can access controller‑data like `dehumidifier_data`.
        self.learning_module = DehumidifierLearningModule(hass, self)

        # Scheduler & persistence are injected from __init__.py
        self.scheduler = None
        self.persistence = None

        # ── Configuration fields ───────────────────────────────────────
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
        self.schedule_update_time: str = entry.data.get(
            CONF_SCHEDULE_UPDATE_TIME, DEFAULT_SCHEDULE_UPDATE_TIME
        )

        # ── Runtime state ──────────────────────────────────────────────
        self._unsub_interval: Optional[Any] = None
        self.schedule: Dict[int, bool] = {}
        self.schedule_created_date: Optional[datetime] = None
        self.override_active: bool = False
        self.cost_savings: float = 0.0  # <‑‑ used by CostSavingsSensor

        # Historical/learned data (defaults if none stored yet)
        self.dehumidifier_data: Dict[str, Any] = {
            "time_to_reduce": {
                "69_to_68": 3,
                "68_to_67": 3,
                "67_to_66": 4,
                "66_to_65": 5,
                "65_to_60": 30,
            },
            "time_to_increase": {"60_to_65": 1, "65_to_70": 5},
            "weather_impact": {},
            "temp_impact": {},
            "humidity_diff_impact": {},
            "energy_efficiency": {},
        }

    # ------------------------------------------------------------------
    # Public API used by __init__.py
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Start the learning module and any timers."""
        _LOGGER.debug("Starting learning module …")
        await self.learning_module.initialize()
        _LOGGER.debug("Learning module initialised")

    async def shutdown(self) -> None:
        """Stop timers, persist data and shut down sub‑modules."""
        # Stop scheduler
        if self.scheduler:
            self.scheduler.stop()
        # Persist data via injected persistence helper
        if self.persistence:
            await self.persistence.save(self)
        # Shut down learning module
        await self.learning_module.shutdown()
        # Cancel interval listener
        if self._unsub_interval:
            self._unsub_interval()
        _LOGGER.debug("Controller shutdown complete")

    # ------------------------------------------------------------------
    # Core routine: called from a time‑trigger in __init__.py
    # ------------------------------------------------------------------

    async def _update_schedule(self, now: Optional[datetime] = None) -> None:
        """Main loop – reads sensors, updates learning, executes schedule."""
        _LOGGER.debug("Updating schedule …")

        # ── Read current humidity ────────────────────────────────────
        humid_state = self.hass.states.get(self.humidity_sensor)
        if not humid_state or humid_state.state in ("unknown", "unavailable"):
            _LOGGER.error("Humidity sensor %s unavailable", self.humidity_sensor)
            return
        try:
            current_humidity = float(humid_state.state)
        except ValueError:
            _LOGGER.error("Invalid humidity value: %s", humid_state.state)
            return

        # ── Read dehumidifier state ──────────────────────────────────
        is_on = False
        sw_state = self.hass.states.get(self.dehumidifier_switch)
        if sw_state:
            is_on = sw_state.state == "on"

        # Feed data to learning module
        self.learning_module.record_humidity_data(
            current_humidity,
            dehumidifier_on=is_on,
            temperature=None,
            weather=None,
            outdoor_humidity=None,
            outdoor_temp=None,
        )

        # ── Hard override if humidity too high ───────────────────────
        if current_humidity >= self.max_humidity:
            await self._turn_on_dehumidifier()
            self.override_active = True
            _LOGGER.info("Humidity %s ≥ %s – dehumidifier ON (override)", current_humidity, self.max_humidity)
            return
        if self.override_active and current_humidity < self.max_humidity - 5:
            self.override_active = False
            _LOGGER.info("Humidity back below threshold – override removed")

        # ── At 13:00 create fresh daily schedule ────────────────────
        now_dt = now or dt_util.now()
        if now_dt.hour == 13 and now_dt.minute < 30:
            await self._create_daily_schedule()

        # ── Optimise schedule each cycle ─────────────────────────────
        price_forecast = self._get_price_forecast()
        rain_hours = await self._get_rain_forecast()

        outdoor: Dict[str, Any] = {}
        if self.outdoor_humidity_sensor:
            st = self.hass.states.get(self.outdoor_humidity_sensor)
            outdoor["humidity"] = (
                float(st.state) if st and st.state not in ("unknown", "unavailable") else None
            )
        if self.outdoor_temp_sensor:
            st = self.hass.states.get(self.outdoor_temp_sensor)
            outdoor["temperature"] = (
                float(st.state) if st and st.state not in ("unknown", "unavailable") else None
            )

        self.schedule = self._optimize_schedule(price_forecast, current_humidity, rain_hours, outdoor)
        _LOGGER.debug("Optimised 24‑h schedule: %s", self.schedule)

        if not self.override_active:
            await self._follow_schedule()

        await self._update_cost_savings()

    # ------------------------------------------------------------------
    # Schedule creation & execution
    # ------------------------------------------------------------------

        async def _create_daily_schedule(self) -> None:
        """Generate a new 24‑hour schedule at 13:00."""
        _LOGGER.debug("Creating daily schedule …")
        humid_state = self.hass.states.get(self.humidity_sensor)
        if not humid_state or humid_state.state in ("unknown", "unavailable"):
            _LOGGER.error("Humidity sensor %s unavailable", self.humidity_sensor)
            return
        current_humidity = float(humid_state.state)
        price_forecast = self._get_price_forecast()
        if not price_forecast:
            _LOGGER.error("No price forecast – skipping schedule")
            return
        rain_hours = await self._get_rain_forecast()
        outdoor = None
        if self.outdoor_humidity_sensor and self.outdoor_temp_sensor:
            oh = self.hass.states.get(self.outdoor_humidity_sensor)
            ot = self.hass.states.get(self.outdoor_temp_sensor)
            try:
                outdoor = {"humidity": float(oh.state), "temperature": float(ot.state)}
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug("Could not parse outdoor sensors")
        self.schedule = self._optimize_schedule(price_forecast, current_humidity, rain_hours, outdoor)
        self.schedule_created_date = dt_util.now()   # <-- store timestamp
        _LOGGER.info("New schedule created: %s", self.schedule)
        return
        current_humidity = float(humid_state.state)
        price_forecast = self._get_price_forecast()
        if not price_forecast:
            _LOGGER.error("No price forecast – skipping schedule")
            return
        rain_hours = await self._get_rain_forecast()
        outdoor = None
        if self.outdoor_humidity_sensor and self.outdoor_temp_sensor:
            oh = self.hass.states.get(self.outdoor_humidity_sensor)
            ot = self.hass.states.get(self.outdoor_temp_sensor)
            try:
                outdoor = {"humidity": float(oh.state), "temperature": float(ot.state)}
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug("Could not parse outdoor sensors")
        self.schedule = self._optimize_schedule(price_forecast, current_humidity, rain_hours, outdoor)
        _LOGGER.info("New schedule created: %s", self.schedule)

    async def _follow_schedule(self) -> None:
        """Turn switch on/off according to current time slot."""
        now = dt_util.now().time()
        if not self.schedule:
            return
        for hour, turn_on in self.schedule.items():
            start = time(hour)
            end = time((hour + 1) % 24)
            if start <= now < end:
                if turn_on:
                    await self._turn_on_dehumidifier()
                else:
                    await self._turn_off_dehumidifier()
                return
        # If no slot matched, ensure device is off
        await self._turn_off_dehumidifier()

    async def _turn_on_dehumidifier(self) -> None:
        try:
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": self.dehumidifier_switch}, blocking=True
            )
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error("Could not turn on dehumidifier: %s", exc)

    async def _turn_off_dehumidifier(self) -> None:
        try:
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": self.dehumidifier_switch}, blocking=True
            )
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error("Could not turn off dehumidifier: %s", exc)

    # ------------------------------------------------------------------
    # Cost‑saving calculation (placeholder)
    # ------------------------------------------------------------------

    async def _update_cost_savings(self) -> None:
        """Very naive cost‑saving estimate so the sensor has data."""
        try:
            forecast = self._get_price_forecast()
            if not forecast:
                return
            avg_price = sum(forecast) / len(forecast)
            hours_on = sum(1 for v in self.schedule.values() if v)
            baseline_hours = 8  # assume old always‑on strategy
            hours_saved = max(0, baseline_hours - hours_on)
            self.cost_savings = round(hours_saved * avg_price, 2)
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.debug("Could not compute cost_savings: %s", exc)

    # ------------------------------------------------------------------
    # Helper methods (price, weather, optimisation) – unchanged logic
    # ------------------------------------------------------------------

    def _get_price_forecast(self) -> List[float] | None:
        try:
            st = self.hass.states.get(self.price_sensor)
            fc = st.attributes.get("forecast") if st else None
            return fc
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error("Price forecast error: %s", exc)
            return None

    async def _get_rain_forecast(self) -> int:
        try:
            st = self.hass.states.get(self.weather_entity)
            fc = st.attributes.get("forecast") if st else None
            if not fc:
                return 0
            return sum(1 for e in fc if e.get("precipitation", 0) > 0)
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error("Weather forecast error: %s", exc)
            return 0

    def _calculate_required_runtime(self, current_humidity: float, outdoor: Dict[str, Any] | None = None) -> float:
        model = self.learning_module.get_current_model()
        ttr = model.get("time_to_reduce", {})
        tti = model.get("time_to_increase", {})
        if current_humidity <= self.max_humidity:
            return max(1, int(round(tti.get("60_to_65", 1) if current_humidity <= 65 else tti.get("65_to_70", 2))))
        minutes = 0
        for bucket, mins in ttr.items():
            try:
                high, low = map(float, bucket.split("_to_"))
            except ValueError:
                continue
            if current_humidity > high or current_humidity > low:
                minutes += mins
        return min(max((minutes + 59) // 60, 1), 8)

    def _optimize_schedule(
        self,
        price_forecast: List[float] | None,
        current_humidity: float,
        rain_hours: int | None = None,
        outdoor_conditions: Dict[str, Any] | None = None,
    ) -> Dict[int, bool]:
        if not price_forecast:
            return {h: False for h in range(24)}
        schedule = {h: False for h in range(24)}
        hours_needed = self._calculate_required_runtime(current_humidity, outdoor_conditions)
        if rain_hours:
            hours_needed += min(2, rain_hours * 0.25)
        hours_by_price = sorted(range(24), key=lambda h: price_forecast[h])
        for h in hours_by_price:
            if sum(schedule.values()) >= hours_needed:
                break
            schedule[h] = True
        if current_humidity > (self.max_humidity - 5):
            next_hours = [(datetime.now().hour + i) % 24 for i in range(1, 4)]
            cheap = min(next_hours, key=lambda h: price_forecast[h])
            schedule[cheap] = True
        return schedule
