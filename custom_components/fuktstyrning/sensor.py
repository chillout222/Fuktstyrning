"""Sensor platform for Fuktstyrning integration.

This file replaces the original sensor.py and fixes:
* monetary sensor must use state_class TOTAL (not TOTAL_INCREASING).
* Works with new controller attributes schedule (dict) and schedule_created_date.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, time
from typing import Any, Dict, List, Optional

from homeassistant.helpers.update_coordinator import UpdateFailed

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from .const import CONF_HUMIDITY_SENSOR, CONF_POWER_SENSOR, CONF_ENERGY_SENSOR
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import (
    DOMAIN,
    # Unique IDs / names
    SENSOR_SAVINGS_UNIQUE_ID,
    SENSOR_SAVINGS_NAME,
    SENSOR_HUMIDITY_PREDICTION_UNIQUE_ID,
    SENSOR_HUMIDITY_PREDICTION_NAME,
    SENSOR_DEW_POINT_UNIQUE_ID,
    SENSOR_DEW_POINT_NAME,
    SENSOR_POWER_UNIQUE_ID,
    SENSOR_POWER_NAME,
    SENSOR_GROUND_STATE_UNIQUE_ID,
    SENSOR_GROUND_STATE_NAME,
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
        DewPointSensor(hass, entry, controller),
        PowerSensor(hass, entry, controller),
        GroundStateSensor(hass, entry, controller),
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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Fuktstyrning Dehumidifier Controller",
            manufacturer="Fuktstyrning",
            model="Smart Dehumidifier Control",
        )

    async def async_update(self) -> None:  # type: ignore[override]
        self._attr_native_value = self.controller.cost_savings

        try:
            price_forecast: List[float] | None = self.controller._get_price_forecast()  # noqa: SLF001
        except UpdateFailed as err:
            _LOGGER.warning("Price forecast unavailable: %s", err)
            price_forecast = None

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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Fuktstyrning Dehumidifier Controller",
            manufacturer="Fuktstyrning",
            model="Smart Dehumidifier Control",
        )

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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Fuktstyrning Dehumidifier Controller",
            manufacturer="Fuktstyrning",
            model="Smart Dehumidifier Control",
        )

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


# -----------------------------------------------------------------------------
# Dew Point sensor
# -----------------------------------------------------------------------------


class DewPointSensor(SensorEntity):
    """Sensor that calculates the dew point based on temperature and humidity."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:water-thermometer"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "°C"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller):
        self.hass = hass
        self.entry = entry
        self.controller = controller
        
        # Använd primära fukt- och temperatursensorn från konfigurationen
        # Temperatursensorn är ofta samma som fuktsensorn (Aqara T1 rapporterar båda)
        self._humidity_entity = entry.data.get(CONF_HUMIDITY_SENSOR, "sensor.aqara_t1_innerst_luftfuktighet")
        self._temperature_entity = entry.data.get(CONF_HUMIDITY_SENSOR, "sensor.aqara_t1_innerst_temperatur")
        
        self._attr_unique_id = f"{entry.entry_id}_{SENSOR_DEW_POINT_UNIQUE_ID}"
        self._attr_name = SENSOR_DEW_POINT_NAME
        self._attr_native_value = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Fuktstyrning Dehumidifier Controller",
            manufacturer="Fuktstyrning",
            model="Smart Dehumidifier Control",
        )

    async def async_update(self) -> None:
        """Update the dew point calculation."""
        try:
            # Get humidity
            humidity_state = self.hass.states.get(self._humidity_entity)
            if not humidity_state or humidity_state.state in ("unknown", "unavailable"):
                return
                
            # Get temperature
            temp_state = self.hass.states.get(self._temperature_entity)
            if not temp_state or temp_state.state in ("unknown", "unavailable"):
                return
                
            try:
                humidity = float(humidity_state.state)
                temperature = float(temp_state.state)
            except ValueError:
                return
                
            # Calculate dew point using Magnus-Tetens approximation
            alpha = 17.27
            beta = 237.7  # °C
            
            # Calculate gamma term
            gamma = (alpha * temperature) / (beta + temperature) + math.log(humidity / 100.0)
            
            # Calculate dew point
            dew_point = (beta * gamma) / (alpha - gamma)
            
            self._attr_native_value = round(dew_point, 1)
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error("DewPointSensor update error: %s", exc)


# -----------------------------------------------------------------------------
# Power Usage sensor
# -----------------------------------------------------------------------------


class PowerSensor(SensorEntity):
    """Sensor that tracks power usage of the dehumidifier."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:flash"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller):
        self.hass = hass
        self.entry = entry
        self.controller = controller
        
        # Använd effektsensorn från konfigurationen
        self._power_entity = entry.data.get(CONF_POWER_SENSOR, "sensor.lumi_lumi_plug_maeu01_active_power")
        # Energisensor för effektivitetsberäkningar
        self._energy_sensor = entry.data.get(CONF_ENERGY_SENSOR, None)
        
        self._attr_unique_id = f"{entry.entry_id}_{SENSOR_POWER_UNIQUE_ID}"
        self._attr_name = SENSOR_POWER_NAME
        self._attr_native_value = None
        self._attr_extra_state_attributes = {
            ATTR_ENERGY_EFFICIENCY: None,
        }
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Fuktstyrning Dehumidifier Controller",
            manufacturer="Fuktstyrning",
            model="Smart Dehumidifier Control",
        )

    async def async_update(self) -> None:
        """Update the power usage."""
        try:
            # Get current power
            if self._power_entity:
                power_state = self.hass.states.get(self._power_entity)
                if power_state and power_state.state not in ("unknown", "unavailable"):
                    try:
                        power = float(power_state.state)
                        self._attr_native_value = power
                    except ValueError:
                        pass
                
            # Add efficiency data if available
            model = self.controller.learning_module.get_current_model()
            if "energy_efficiency" in model:
                self._attr_extra_state_attributes[ATTR_ENERGY_EFFICIENCY] = model["energy_efficiency"]
                
            # Add energy data if available
            if self._energy_sensor:
                energy_state = self.hass.states.get(self._energy_sensor)
                if energy_state and energy_state.state not in ("unknown", "unavailable"):
                    try:
                        energy = float(energy_state.state)
                        self._attr_extra_state_attributes[ATTR_ENERGY_USED] = energy
                    except ValueError:
                        pass
                
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error("PowerSensor update error: %s", exc)


# -----------------------------------------------------------------------------
# Ground state sensor
# -----------------------------------------------------------------------------


class GroundStateSensor(SensorEntity):
    """Sensor that indicates ground dryness state."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:water-percent"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller):
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._attr_unique_id = f"{entry.entry_id}_{SENSOR_GROUND_STATE_UNIQUE_ID}"
        self._attr_name = SENSOR_GROUND_STATE_NAME
        self._attr_native_value: str | None = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Fuktstyrning Dehumidifier Controller",
            manufacturer="Fuktstyrning",
            model="Smart Dehumidifier Control",
        )

    async def async_update(self) -> None:
        """Update ground state based on controller classification."""
        self._attr_native_value = self.controller.ground_state
