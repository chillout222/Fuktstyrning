"""Sensor platform for Fuktstyrning integration."""
from datetime import datetime, timedelta
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import (
    DOMAIN,
    SENSOR_SAVINGS_UNIQUE_ID,
    SENSOR_SAVINGS_NAME,
    SENSOR_HUMIDITY_PREDICTION_UNIQUE_ID,
    SENSOR_HUMIDITY_PREDICTION_NAME,
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
    """Set up the Fuktstyrning sensor platform."""
    controller = hass.data[DOMAIN][entry.entry_id]["controller"]
    
    entities = [
        CostSavingsSensor(hass, entry, controller),
        HumidityPredictionSensor(hass, entry, controller),
        LearningModelSensor(hass, entry, controller),
    ]
    
    async_add_entities(entities)


class CostSavingsSensor(SensorEntity):
    """Sensor for tracking cost savings."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "SEK"
    _attr_icon = "mdi:cash-plus"

    def __init__(self, hass, entry, controller):
        """Initialize the sensor."""
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._attr_unique_id = f"{entry.entry_id}_{SENSOR_SAVINGS_UNIQUE_ID}"
        self._attr_name = SENSOR_SAVINGS_NAME
        self._attr_native_value = 0
        self._attr_extra_state_attributes = {
            ATTR_SCHEDULE_CREATED: None,
            ATTR_CURRENT_PRICE: None,
            ATTR_OPTIMAL_PRICE: None,
        }

    async def async_update(self) -> None:
        """Update the sensor."""
        self._attr_native_value = self.controller.cost_savings
        
        # Update attributes
        price_sensor = self.hass.states.get(self.controller.price_sensor)
        current_price = float(price_sensor.state) if price_sensor else None
        
        self._attr_extra_state_attributes.update({
            ATTR_SCHEDULE_CREATED: self.controller.schedule_created_date.isoformat() if self.controller.schedule_created_date else None,
            ATTR_CURRENT_PRICE: current_price,
            ATTR_SCHEDULE: self.controller.schedule,
        })


class HumidityPredictionSensor(SensorEntity):
    """Sensor for predicting future humidity levels."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:water-percent-alert"

    def __init__(self, hass, entry, controller):
        """Initialize the sensor."""
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._attr_unique_id = f"{entry.entry_id}_{SENSOR_HUMIDITY_PREDICTION_UNIQUE_ID}"
        self._attr_name = SENSOR_HUMIDITY_PREDICTION_NAME
        self._attr_native_value = None
        self._attr_extra_state_attributes = {
            ATTR_NEXT_RUN: None,
        }

    async def async_update(self) -> None:
        """Update the sensor."""
        # Get current humidity
        humidity_sensor = self.hass.states.get(self.controller.humidity_sensor)
        if not humidity_sensor:
            return
        
        current_humidity = float(humidity_sensor.state)
        
        # Predict future humidity based on dehumidifier data
        # Simple prediction - if dehumidifier is off, humidity will increase according to the rate
        dehumidifier_on = self._is_dehumidifier_on()
        prediction_time = datetime.now() + timedelta(hours=1)
        
        predicted_humidity = current_humidity
        
        if dehumidifier_on:
            # Predict decrease in humidity
            if 69 >= current_humidity > 68:
                predicted_humidity = 68
            elif 68 >= current_humidity > 67:
                predicted_humidity = 67
            elif 67 >= current_humidity > 66:
                predicted_humidity = 66
            elif 66 >= current_humidity > 65:
                predicted_humidity = 65
            elif 65 >= current_humidity > 60:
                reduction_per_minute = 5 / 30  # 5% reduction in 30 minutes
                time_running = 60  # assuming 1 hour for prediction
                predicted_humidity = max(60, current_humidity - (reduction_per_minute * time_running))
        else:
            # Predict increase in humidity
            if 60 <= current_humidity < 65:
                # Increases by 5% over 1 hour
                predicted_humidity = min(65, current_humidity + 5)
            elif 65 <= current_humidity < 70:
                # Increases by 5% over 5 hours
                predicted_humidity = min(70, current_humidity + (5/5))
        
        self._attr_native_value = round(predicted_humidity, 1)
        
        # Find next scheduled run
        next_run = self._find_next_run_time()
        self._attr_extra_state_attributes[ATTR_NEXT_RUN] = next_run.isoformat() if next_run else None
    
    def _is_dehumidifier_on(self):
        """Check if the dehumidifier is currently on."""
        switch_state = self.hass.states.get(self.controller.dehumidifier_switch)
        return switch_state.state == "on" if switch_state else False
    
    def _find_next_run_time(self):
        """Find the next time the dehumidifier is scheduled to run."""
        now = datetime.now()
        current_hour = now.hour
        
        # If currently running and scheduled to run, next run is now
        if self._is_dehumidifier_on() and self.controller.schedule.get(current_hour, False):
            return now
        
        # Find next scheduled hour
        for hour_offset in range(1, 25):
            check_hour = (current_hour + hour_offset) % 24
            if self.controller.schedule.get(check_hour, False):
                next_day = now.date() + timedelta(days=1 if check_hour <= current_hour else 0)
                return datetime.combine(next_day, datetime.min.time().replace(hour=check_hour))
        
        # No scheduled run found
        return None


class LearningModelSensor(SensorEntity):
    """Sensor for showing learning model data."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:brain"

    def __init__(self, hass, entry, controller):
        """Initialize the sensor."""
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._attr_unique_id = f"{entry.entry_id}_learning_model"
        self._attr_name = "Dehumidifier Learning Model"
        self._attr_native_value = "Learning"
        self._attr_extra_state_attributes = {}

    async def async_update(self) -> None:
        """Update the sensor."""
        try:
            model_data = self.controller.learning_module.get_current_model()
            
            # Format data for better display
            self._attr_extra_state_attributes = {
                "data_points": model_data["data_points"],
                "humidity_reduction_minutes": {
                    key.replace("_to_", "→"): f"{value:.1f} min" 
                    for key, value in model_data["time_to_reduce"].items()
                },
                "humidity_increase_hours": {
                    key.replace("_to_", "→"): f"{value:.1f} h" 
                    for key, value in model_data["time_to_increase"].items()
                }
            }
            
            # Add weather and temperature impacts if available
            if "weather_impact" in model_data:
                self._attr_extra_state_attributes["weather_impact"] = {
                    key: f"{value:.2f}x" 
                    for key, value in model_data["weather_impact"].items()
                }
                
            if "temp_impact" in model_data:
                self._attr_extra_state_attributes["temperature_impact"] = {
                    key: f"{value:.2f}x" 
                    for key, value in model_data["temp_impact"].items()
                }
                
            # Add humidity difference impact if available
            if "humidity_diff_impact" in model_data:
                # Provide friendly descriptions for the categories
                category_descriptions = {
                    "negative": "Torrare ute än inne",
                    "neutral": "Liknande fukt ute/inne",
                    "positive": "Fuktigare ute än inne",
                    "extreme": "Mycket fuktigare ute än inne"
                }
                
                self._attr_extra_state_attributes["humidity_diff_impact"] = {
                    category_descriptions.get(key, key): f"{value:.2f}x" 
                    for key, value in model_data["humidity_diff_impact"].items()
                }
            
            # Add energy efficiency data if available
            if "energy_efficiency" in model_data and model_data["energy_efficiency"]:
                # Provide friendly descriptions for the efficiency categories
                efficiency_descriptions = {
                    "excellent": "Utmärkt (< 40 Wh/% fukt)",
                    "good": "Bra (40-80 Wh/% fukt)",
                    "average": "Genomsnittlig (80-120 Wh/% fukt)",
                    "poor": "Dålig (> 120 Wh/% fukt)"
                }
                
                # Format the efficiency values
                efficiency_data = {}
                for key, value in model_data["energy_efficiency"].items():
                    # Special handling for temperature efficiency categories
                    if "_efficiency" in key:
                        temp_category = key.split("_")[0]
                        temp_desc = {
                            "cold": "Kallt (< 5°C)",
                            "cool": "Svalt (5-15°C)",
                            "warm": "Varmt (15-25°C)",
                            "hot": "Hett (> 25°C)"
                        }.get(temp_category, temp_category)
                        formatted_key = f"{temp_desc} effektivitet"
                    else:
                        formatted_key = efficiency_descriptions.get(key, key)
                    
                    efficiency_data[formatted_key] = f"{value:.1f} Wh/%"
                
                if efficiency_data:
                    self._attr_extra_state_attributes["energy_efficiency"] = efficiency_data
                
                # Add current power consumption if available
                if hasattr(self.controller, 'current_power') and self.controller.current_power > 0:
                    self._attr_extra_state_attributes["current_power"] = f"{self.controller.current_power:.1f} W"
                
                # Add total energy used if available
                if hasattr(self.controller, 'total_energy_used') and self.controller.total_energy_used > 0:
                    self._attr_extra_state_attributes["total_energy_used"] = f"{self.controller.total_energy_used:.2f} kWh"
                
                # Calculate efficiency over the last 24 hours if data is available
                if (hasattr(self.controller, 'historical_data') and 
                    'energy_usage' in self.controller.historical_data and 
                    self.controller.historical_data['energy_usage']):
                    
                    # Get data from the last 24 hours
                    now = datetime.now()
                    day_ago = now - timedelta(days=1)
                    
                    recent_data = [
                        entry for entry in self.controller.historical_data['energy_usage']
                        if datetime.fromisoformat(entry['timestamp']) > day_ago
                    ]
                    
                    if recent_data:
                        total_energy = sum(entry['energy_used'] for entry in recent_data if 'energy_used' in entry)
                        total_humidity_change = sum(
                            abs(entry['humidity_change']) 
                            for entry in recent_data 
                            if 'humidity_change' in entry
                        )
                        
                        if total_humidity_change > 0:
                            avg_efficiency = total_energy / total_humidity_change
                            self._attr_extra_state_attributes["avg_efficiency_24h"] = f"{avg_efficiency:.1f} Wh/%"
                
            # Get latest absolute humidity data if available
            latest_data = None
            if hasattr(self.controller.learning_module, 'humidity_data') and self.controller.learning_module.humidity_data:
                latest_data = self.controller.learning_module.humidity_data[-1]
                
                # Add absolute humidity and dew point if available
                if latest_data.get("abs_humidity") is not None:
                    self._attr_extra_state_attributes["current_absolute_humidity"] = f"{latest_data['abs_humidity']:.1f} g/m³"
                
                if latest_data.get("dew_point") is not None:
                    self._attr_extra_state_attributes["current_dew_point"] = f"{latest_data['dew_point']:.1f} °C"
                    
                # Add outdoor/indoor comparison if available
                indoor_outdoor_data = {}
                
                if latest_data.get("humidity") is not None and latest_data.get("outdoor_humidity") is not None:
                    indoor_outdoor_data["relative_humidity"] = {
                        "indoor": f"{latest_data['humidity']:.1f} %",
                        "outdoor": f"{latest_data['outdoor_humidity']:.1f} %",
                        "difference": f"{latest_data['humidity_diff']:.1f} %"
                    }
                    
                if latest_data.get("abs_humidity") is not None and latest_data.get("outdoor_abs_humidity") is not None:
                    indoor_outdoor_data["absolute_humidity"] = {
                        "indoor": f"{latest_data['abs_humidity']:.1f} g/m³",
                        "outdoor": f"{latest_data['outdoor_abs_humidity']:.1f} g/m³",
                        "difference": f"{latest_data['abs_humidity_diff']:.1f} g/m³"
                    }
                    
                if indoor_outdoor_data:
                    self._attr_extra_state_attributes["indoor_outdoor_comparison"] = indoor_outdoor_data
                
            self._attr_native_value = f"{model_data['data_points']} data points"
        except Exception as e:
            _LOGGER.error(f"Error updating learning model sensor: {e}")
