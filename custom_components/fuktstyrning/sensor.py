"""Sensor platform for Fuktstyrning integration.

This file replaces the original sensor.py and fixes:
* monetary sensor must use state_class TOTAL (not TOTAL_INCREASING).
* Works with new controller attributes schedule (dict) and schedule_created_date.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import (
    DOMAIN,
    # Unique IDs / names
    SENSOR_SAVINGS_UNIQUE_ID,
    SENSOR_SAVINGS_NAME,
    SENSOR_HUMIDITY_PREDICTION_UNIQUE_ID,
    SENSOR_HUMIDITY_PREDICTION_NAME,
    # Attribute keys
    ATTR_SCHEDULE,
    ATTR_OVERRIDE_ACTIVE,
    ATTR_COST_SAVINGS,
    ATTR_SCHEDULE_CREATED,
    ATTR_NEXT_RUN,
    ATTR_CURRENT_PRICE,
    ATTR_OPTIMAL_PRICE,
    ATTR_CURRENT_POWER,
    ATTR_ENERGY_USED,
    ATTR_ENERGY_EFFICIENCY,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fuktstyrning sensors from a config entry."""

    controller = hass.data[DOMAIN][entry.entry_id]["controller"]

    entities = [
        CostSavingsSensor(hass, entry, controller),
        HumidityPredictionSensor(hass, entry, controller),
        LearningModelSensor(hass, entry, controller),
    ]
    async_add_entities(entities)


# -----------------------------------------------------------------------------
# Cost savings (monetary)
# -----------------------------------------------------------------------------


class CostSavingsSensor(SensorEntity):
    """Sensor that displays accumulated SEK saved by optimised runtime."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL  # compliant with HA monetary rules
    _attr_native_unit_of_measurement = "SEK"
    _attr_icon = "mdi:cash-plus"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller):
        self.hass = hass
        self.entry = entry
        self.controller = controller

        self._attr_unique_id = f"{entry.entry_id}_{SENSOR_SAVINGS_UNIQUE_ID}"
        self._attr_name = SENSOR_SAVINGS_NAME
        self._attr_native_value: float | None = 0.0

        self._attr_extra_state_attributes: Dict[str, Any] = {
            ATTR_SCHEDULE_CREATED: None,
            ATTR_CURRENT_PRICE: None,
            ATTR_OPTIMAL_PRICE: None,
            ATTR_SCHEDULE: None,
        }

    async def async_update(self) -> None:  # type: ignore[override]
        self._attr_native_value = self.controller.cost_savings

        price_forecast: List[float] | None = self.controller._get_price_forecast()  # noqa: SLF001
        optimal_price: float | None = min(price_forecast) if price_forecast else None

        price_state = self.hass.states.get(self.controller.price_sensor)
        current_price: Optional[float] = None
        if price_state and price_state.state not in ("unknown", "unavailable"):
            try:
                current_price = float(price_state.state)
            except ValueError:
                pass

        self._attr_extra_state_attributes.update(
            {
                ATTR_SCHEDULE_CREATED: self.controller.schedule_created_date.isoformat()
                if self.controller.schedule_created_date
                else None,
                ATTR_CURRENT_PRICE: current_price,
                ATTR_OPTIMAL_PRICE: optimal_price,
                ATTR_SCHEDULE: self.controller.schedule,
            }
        )


# -----------------------------------------------------------------------------
# Humidity prediction sensor
# -----------------------------------------------------------------------------


class HumidityPredictionSensor(SensorEntity):
    """Predict relative humidity one hour ahead."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:water-percent-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller):
        self.hass = hass
        self.entry = entry
        self.controller = controller

        self._attr_unique_id = f"{entry.entry_id}_{SENSOR_HUMIDITY_PREDICTION_UNIQUE_ID}"
        self._attr_name = SENSOR_HUMIDITY_PREDICTION_NAME
        self._attr_native_value: float | None = None
        self._attr_extra_state_attributes: Dict[str, Any] = {ATTR_NEXT_RUN: None}

    async def async_update(self) -> None:  # type: ignore[override]
        humidity_state = self.hass.states.get(self.controller.humidity_sensor)
        if not humidity_state or humidity_state.state in ("unknown", "unavailable"):
            return
        try:
            current_humidity = float(humidity_state.state)
        except ValueError:
            return

        model = self.controller.learning_module.get_current_model()
        ttr = model.get("time_to_reduce", {})
        tti = model.get("time_to_increase", {})

        predicted = current_humidity
        if self._is_dehumidifier_on():
            # dehumidifier is ON → humidity will drop
            for bucket, mins in ttr.items():
                try:
                    hi, lo = map(float, bucket.split("_to_"))
                except ValueError:
                    continue
                if hi >= current_humidity > lo:
                    rate_per_min = (hi - lo) / mins if mins > 0 else 0
                    predicted = max(lo, current_humidity - rate_per_min * 60)
                    break
        else:
            # device off → humidity rise
            for bucket, hrs in tti.items():
                try:
                    lo, hi = map(float, bucket.split("_to_"))
                except ValueError:
                    continue
                if lo <= current_humidity < hi:
                    rate_per_hr = (hi - lo) / hrs if hrs > 0 else 0
                    predicted = min(hi, current_humidity + rate_per_hr)
                    break

        self._attr_native_value = round(predicted, 1)
        self._attr_extra_state_attributes[ATTR_NEXT_RUN] = (
            self._find_next_run_time().isoformat() if self._find_next_run_time() else None
        )

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _is_dehumidifier_on(self) -> bool:
        state = self.hass.states.get(self.controller.dehumidifier_switch)
        return state.state == "on" if state else False

    def _find_next_run_time(self) -> Optional[datetime]:
        now = datetime.now()
        current_hour = now.hour

        if self._is_dehumidifier_on() and self.controller.schedule.get(current_hour, False):
            return now

        for offset in range(1, 25):
            check_hour = (current_hour + offset) % 24
            if self.controller.schedule.get(check_hour, False):
                next_day = now.date() + timedelta(days=1 if check_hour <= current_hour else 0)
                return datetime.combine(next_day, time(check_hour))
        return None


# -----------------------------------------------------------------------------
# Learning model diagnostic sensor
# -----------------------------------------------------------------------------


class LearningModelSensor(SensorEntity):
    """Expose the raw learning model as attributes for diagnostics."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:brain"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller):
        self.hass = hass
        self.entry = entry
        self.controller = controller

        self._attr_unique_id = f"{entry.entry_id}_learning_model"
        self._attr_name = "Dehumidifier Learning Model"
        self._attr_native_value = "learning"
        self._attr_extra_state_attributes: Dict[str, Any] = {}

    async def async_update(self) -> None:  # type: ignore[override]
        try:
            model_data = self.controller.learning_module.get_current_model()
            self._attr_extra_state_attributes = {
                "data_points": model_data.get("data_points"),
                "time_to_reduce": model_data.get("time_to_reduce"),
                "time_to_increase": model_data.get("time_to_increase"),
                "weather_impact": model_data.get("weather_impact"),
                "temp_impact": model_data.get("temp_impact"),
            }
            self._attr_native_value = f"{model_data.get('data_points', 0)} pts"
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error("LearningModelSensor update error: %s", exc)
