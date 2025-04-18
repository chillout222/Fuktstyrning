"""Learning module for Fuktstyrning that analyzes historical data and adjusts models."""
import logging
from datetime import datetime, timedelta
import statistics
import json
import os
import asyncio
import math
import tempfile

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.json import JSONEncoder
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, LEARNING_STORAGE_KEY

try:
    import aiofiles
    HAS_AIOFILES = True
except ImportError:
    HAS_AIOFILES = False

_LOGGER = logging.getLogger(__name__)

class DehumidifierLearningModule:
    """Module for learning how humidity changes in the crawl space."""

    def __init__(self, hass, controller):
        """Initialize the learning module."""
        self.hass = hass
        self.controller = controller
        self.data_store = None
        
        # Humidity data for learning
        self.humidity_data = []
        
        # Flag to make sure analysis is only done once
        self._analysis_scheduled = False
        
        # Use Storage helper for learning data
        # Version=1, increment to version=2 if data structure changes in future
        self._store = Store(hass, 1, LEARNING_STORAGE_KEY)
        
        # Keep raw humidity data in a separate file
        self.data_file = os.path.join(
            hass.config.path(), ".storage", "fuktstyrning_humidity_data.json"
        )
        self.min_data_points_for_update = 5
        self._unsub_interval = None
        
        # Weather condition categories
        self.weather_categories = {
            "rainy": ["rainy", "pouring", "lightning", "lightning-rainy", "partlycloudy"],
            "dry": ["sunny", "clear-night", "cloudy"],
            "other": ["snowy", "snowy-rainy", "hail", "fog", "windy"]
        }
        
        # Temperature categories (degrees C)
        self.temp_categories = {
            "cold": (-30, 5),
            "cool": (5, 15),
            "warm": (15, 25),
            "hot": (25, 50)
        }
        
        # Energy efficiency categories (Wh per % humidity)
        self.efficiency_categories = {
            "excellent": (0, 40),  # Less than 40 Wh to remove 1% humidity
            "good": (40, 80),      # 40-80 Wh per % humidity
            "average": (80, 120),   # 80-120 Wh per % humidity
            "poor": (120, 999)     # More than 120 Wh per % humidity
        }

    async def initialize(self):
        """Initialize the learning module and schedule periodic analysis."""
        # Register periodic analysis twice daily
        self._unsub_interval = async_track_time_interval(
            self.hass,
            self._perform_analysis,
            timedelta(hours=12)
        )
        
        # Auto-save data every 10 minutes
        @callback
        async def _autosave_callback(_now):
            """Autosave learning data to storage."""
            await self.save_learning_data()
            
        async_track_time_interval(
            self.hass,
            _autosave_callback,
            timedelta(minutes=10)
        )
        
        try:
            # Load previous data
            stored_data = await self._store.async_load()
            if stored_data:
                _LOGGER.debug("Loaded stored learning data (%d keys)", len(stored_data))
                self.controller.dehumidifier_data.update(stored_data)
            
            # Load humidity data history
            await self.hass.async_add_executor_job(self._load_humidity_data)
            
            # Perform initial analysis only once
            if not self._analysis_scheduled:
                self._analysis_scheduled = True
                await self._perform_analysis()
                _LOGGER.debug("Initial learning analysis complete")
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error("Learning module initialization failed: %s", exc)

    async def shutdown(self):
        """Shut down the learning module."""
        if self._unsub_interval:
            self._unsub_interval()
            
        # Save learning and humidity data one last time
        await self.save_learning_data()
        await self._save_humidity_data()

    def _load_humidity_data(self):
        """Load humidity data history from file."""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, "r") as f:
                    data = json.load(f)
                    if "humidity_data" in data:
                        # Only load last 60 days of data for better trend analysis
                        # while keeping file size manageable
                        cutoff = (dt_util.now() - timedelta(days=60)).isoformat()
                        self.humidity_data = [
                            point for point in data["humidity_data"]
                            if "timestamp" in point and point["timestamp"] > cutoff
                        ]
                        _LOGGER.info("Loaded %d humidity data points (60 day history)", len(self.humidity_data))
        except json.JSONDecodeError as json_error:
            _LOGGER.error("Failed to decode humidity data JSON: %s", json_error)
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error("Failed to load humidity data: %s", exc)

    async def _save_humidity_data(self):
        """Save humidity data to file."""
        now = dt_util.now()
        
        # Skip if last save was less than save_interval ago
        if self.last_save_time and now - self.last_save_time < self.save_interval:
            return
            
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
            
            if HAS_AIOFILES:
                # Write to temporary file first, then replace
                async with aiofiles.open(f"{self.data_file}.tmp", "w") as f:
                    await f.write(json.dumps(
                        {"humidity_data": self.humidity_data},
                        cls=JSONEncoder
                    ))
                os.replace(f"{self.data_file}.tmp", self.data_file)
            else:
                # Fallback if aiofiles not available
                with open(f"{self.data_file}.tmp", "w") as f:
                    json.dump({"humidity_data": self.humidity_data}, f, cls=JSONEncoder)
                os.replace(f"{self.data_file}.tmp", self.data_file)
                
            self.last_save_time = now
            _LOGGER.debug("Saved %d humidity data points", len(self.humidity_data))
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error("Failed to save humidity data: %s", exc)

    async def load_learning_data(self):
        """Load learning data from store."""
        try:
            stored_data = await self._store.async_load()
            if stored_data:
                # Update controller with learned data
                try:
                    if "time_to_reduce" in stored_data:
                        self.controller.dehumidifier_data["time_to_reduce"] = stored_data["time_to_reduce"]
                    if "time_to_increase" in stored_data:
                        self.controller.dehumidifier_data["time_to_increase"] = stored_data["time_to_increase"]
                    if "weather_impact" in stored_data:
                        self.controller.dehumidifier_data["weather_impact"] = stored_data["weather_impact"]
                    if "temp_impact" in stored_data:
                        self.controller.dehumidifier_data["temp_impact"] = stored_data["temp_impact"]
                    if "humidity_diff_impact" in stored_data:
                        self.controller.dehumidifier_data["humidity_diff_impact"] = stored_data["humidity_diff_impact"]
                    if "energy_efficiency" in stored_data:
                        self.controller.dehumidifier_data["energy_efficiency"] = stored_data["energy_efficiency"]
                    
                    _LOGGER.debug("Loaded learning data from store (%d keys)", len(stored_data))
                except (ValueError, KeyError, TypeError) as schema_error:
                    # Handle future schema migration errors
                    _LOGGER.warning("Schema error in stored data: %s", schema_error)
        except json.JSONDecodeError as json_error:
            _LOGGER.error("Failed to decode learning data JSON: %s", json_error)
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error("Failed to load learning data: %s", exc)

    async def save_learning_data(self):
        """Save learning data to store."""
        try:
            # Prepare data for saving
            data = {
                "time_to_reduce": self.controller.dehumidifier_data.get("time_to_reduce", {}),
                "time_to_increase": self.controller.dehumidifier_data.get("time_to_increase", {}),
                "weather_impact": self.controller.dehumidifier_data.get("weather_impact", {}),
                "temp_impact": self.controller.dehumidifier_data.get("temp_impact", {}),
                "humidity_diff_impact": self.controller.dehumidifier_data.get("humidity_diff_impact", {}),
                "energy_efficiency": self.controller.dehumidifier_data.get("energy_efficiency", {}),
            }
            
            # Save using storage helper
            await self._store.async_save(data)
            _LOGGER.debug("Saved learning data to store")
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error("Failed to save learning data: %s", exc)

    def record_humidity_data(self, humidity, dehumidifier_on, temperature=None, weather=None, 
                           outdoor_humidity=None, outdoor_temp=None, power=None, energy=None):
        """Record current humidity data with context."""
        now = datetime.now()
        
        # Calculate absolute humidity if we have temperature
        abs_humidity = None
        dew_point = None
        outdoor_abs_humidity = None
        humidity_diff = None
        
        if temperature is not None:
            abs_humidity = self._calculate_absolute_humidity(humidity, temperature)
            dew_point = self._calculate_dew_point(humidity, temperature)
        
        # Calculate outdoor absolute humidity
        if outdoor_humidity is not None and outdoor_temp is not None:
            outdoor_abs_humidity = self._calculate_absolute_humidity(outdoor_humidity, outdoor_temp)
            
            # Calculate humidity difference (can be useful for predicting condensation risk)
            if abs_humidity is not None:
                humidity_diff = outdoor_abs_humidity - abs_humidity
        
        # Create data point
        data_point = {
            "timestamp": now.isoformat(),
            "humidity": humidity,
            "dehumidifier_on": dehumidifier_on,
            "temperature": temperature,
            "abs_humidity": abs_humidity,
            "dew_point": dew_point,
            "weather": weather,
            "outdoor_humidity": outdoor_humidity,
            "outdoor_temp": outdoor_temp,
            "outdoor_abs_humidity": outdoor_abs_humidity,
            "humidity_diff": humidity_diff,
            "power": power,
            "energy": energy
        }
        
        # Add to data set
        self.humidity_data.append(data_point)
        
        # Keep the size reasonable (keep the most recent 1000 data points)
        if len(self.humidity_data) > 1000:
            self.humidity_data = self.humidity_data[-1000:]

    # Helper to predict dehumidifier reduction rate including dynamic impacts
    def predict_reduction_rate(self, start_humidity: float, temperature: float = None, weather: str = None) -> float:
        """Return %‑enheter per timme som modellen tror avfuktaren klarar, med justering för väder och temperatur."""
        # Get reduction times from learned data
        try:
            # Try to get exact match first
            rounded_humidity = round(start_humidity)
            time_to_reduce_data = self.controller.dehumidifier_data.get("time_to_reduce", {})
            
            # Check if we have any data at all
            if not time_to_reduce_data:
                _LOGGER.debug("No time_to_reduce data available, using default rate")
                minutes = 30  # Default to 30 min (2%/hour) if no data
            else:
                # Try exact match
                key = f"{rounded_humidity}_to_{rounded_humidity-1}"
                if key in time_to_reduce_data:
                    minutes = time_to_reduce_data[key]
                    _LOGGER.debug("Using exact reduction time match for %s: %.1f minutes", key, minutes)
                else:
                    # Look for nearby humidity values (within ±5%)
                    nearby_keys = []
                    for existing_key in time_to_reduce_data:
                        try:
                            parts = existing_key.split('_to_')
                            from_humidity = int(parts[0])
                            # Use nearby values that are within reasonable range and preferably higher
                            # (since reduction gets slower at lower humidity levels)
                            if abs(from_humidity - rounded_humidity) <= 5:
                                nearby_keys.append((existing_key, abs(from_humidity - rounded_humidity)))
                        except (ValueError, IndexError):
                            continue
                    
                    if nearby_keys:
                        # Sort by proximity (closest first)
                        nearby_keys.sort(key=lambda x: x[1])
                        closest_key = nearby_keys[0][0]
                        minutes = time_to_reduce_data[closest_key]
                        _LOGGER.debug("Using nearby reduction time for %s: %.1f minutes from %s", 
                                     key, minutes, closest_key)
                    else:
                        # No nearby keys, use default
                        minutes = 30
                        _LOGGER.debug("No nearby reduction time found for %s, using default", key)
                        
                # Validate value
                if not isinstance(minutes, (int, float)) or minutes <= 0:
                    _LOGGER.warning("Invalid reduction time: %s", minutes)
                    minutes = 30
        except (KeyError, TypeError, ValueError) as exc:
            _LOGGER.warning("Error in reduction time lookup: %s", exc)
            minutes = 30
            
        rate = 60 / minutes  # Convert minutes per % to % per hour
        
        # Apply weather impact if available
        if weather:
            try:
                weather_factor = self.controller.dehumidifier_data.get("weather_impact", {}).get(weather, 1.0)
                if isinstance(weather_factor, (int, float)) and weather_factor > 0:
                    rate *= weather_factor
            except (KeyError, TypeError) as exc:
                _LOGGER.debug("No weather impact data for %s: %s", weather, exc)
                
        # Apply temperature impact if available
        if temperature is not None and not math.isnan(temperature):
            try:
                for cat, (min_t, max_t) in self.temp_categories.items():
                    if min_t <= temperature < max_t:
                        temp_factor = self.controller.dehumidifier_data.get("temp_impact", {}).get(cat, 1.0)
                        if isinstance(temp_factor, (int, float)) and temp_factor > 0:
                            rate *= temp_factor
                        break
            except (KeyError, TypeError) as exc:
                _LOGGER.debug("No temperature impact data for %.1f°C: %s", temperature, exc)
                
        return max(0.5, rate)  # Ensure minimum rate of 0.5%/hour

    def predict_hours_needed(
        self,
        current_humidity: float,
        target_humidity: float,
        temperature: float = None,
        weather: str = None,
    ) -> int:
        """Returnera antal timmar avfuktaren behöver vara på för att nå target_humidity."""
        diff = current_humidity - target_humidity
        if diff <= 0:
            return 0
        rate = self.predict_reduction_rate(current_humidity, temperature, weather)
        hours = math.ceil(diff / rate) if rate > 0 else 0
        return max(2, min(hours, 24))

    def _calculate_absolute_humidity(self, relative_humidity, temperature):
        """Calculate absolute humidity in g/m3 from relative humidity and temperature."""
        if relative_humidity is None or temperature is None:
            return None
            
        # Constants for water vapor calculation
        C1 = 17.625
        C2 = 243.04  # °C
        
        # Calculate saturation vapor pressure
        saturation_vapor_pressure = 6.112 * math.exp((C1 * temperature) / (C2 + temperature))
        
        # Calculate vapor pressure
        vapor_pressure = saturation_vapor_pressure * relative_humidity / 100.0
        
        # Calculate absolute humidity (g/m³)
        absolute_humidity = 217.0 * vapor_pressure / (273.15 + temperature)
        
        return round(absolute_humidity, 2)
    
    def _calculate_dew_point(self, relative_humidity, temperature):
        """Calculate dew point in °C from relative humidity and temperature."""
        if relative_humidity is None or temperature is None:
            return None
            
        # Constants for dew point calculation
        C1 = 17.625
        C2 = 243.04  # °C
        
        # Calculate intermediate term
        term = math.log(relative_humidity / 100.0) + (C1 * temperature) / (C2 + temperature)
        
        # Calculate dew point
        dew_point = C2 * term / (C1 - term)
        
        return round(dew_point, 2)

    async def _perform_analysis(self, _now=None):
        """Analyze recorded data and update models."""
        _LOGGER.info("Performing humidity learning analysis")
        
        # Need some minimum amount of data for analysis
        if len(self.humidity_data) < self.min_data_points_for_update:
            _LOGGER.info(f"Not enough data points yet ({len(self.humidity_data)})")
            return
            
        # Analyze how humidity decreases when dehumidifier is on
        self._analyze_humidity_reduction()
        
        # Analyze how humidity increases when dehumidifier is off
        self._analyze_humidity_increase()
        
        # Analyze how weather affects humidity increase rate
        self._analyze_weather_impact()
        
        # Analyze how temperature affects humidity behavior
        self._analyze_temperature_impact()
        
        # Analyze how outdoor/indoor humidity difference affects increase rate
        self._analyze_humidity_difference_impact()
        
        # Analyze energy efficiency
        self._analyze_energy_efficiency()
        
        # Save updated model to store
        try:
            await self.save_learning_data()
            _LOGGER.debug("Learning data saved after analysis")
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error("Failed to save learning data after analysis: %s", exc)

    def _analyze_humidity_reduction(self):
        """Analyze how fast humidity decreases when dehumidifier is on."""
        # Find consecutive records when dehumidifier was on and humidity decreased
        reduction_data = {}
        
        for i in range(1, len(self.humidity_data)):
            prev = self.humidity_data[i-1]
            curr = self.humidity_data[i]
            
            # Check if time between readings is reasonable (< 15 minutes)
            try:
                prev_time = datetime.fromisoformat(prev["timestamp"])
                curr_time = datetime.fromisoformat(curr["timestamp"])
                
                time_diff = (curr_time - prev_time).total_seconds() / 60  # in minutes
                
                if (prev["dehumidifier_on"] and curr["dehumidifier_on"] and 
                    prev["humidity"] > curr["humidity"] and 
                    0 < time_diff < 15):
                    
                    # Round humidities to nearest percent
                    start_humidity = round(prev["humidity"])
                    end_humidity = round(curr["humidity"])
                    
                    if start_humidity > end_humidity:
                        # Calculate minutes per 1% reduction
                        humidity_diff = start_humidity - end_humidity
                        minutes_per_percent = time_diff / humidity_diff
                        
                        # Create key for range (e.g. "69_to_68")
                        for h in range(end_humidity, start_humidity):
                            key = f"{h+1}_to_{h}"
                            if key not in reduction_data:
                                reduction_data[key] = []
                            reduction_data[key].append(minutes_per_percent)
            except (ValueError, TypeError):
                continue
        
        # Update model with new median values
        for key, times in reduction_data.items():
            if len(times) >= self.min_data_points_for_update:
                median_time = statistics.median(times)
                
                # Ensure we have the category in our model
                if key not in self.controller.dehumidifier_data["time_to_reduce"]:
                    self.controller.dehumidifier_data["time_to_reduce"][key] = 5  # Default
                    
                # Update with exponential moving average (75% old, 25% new)
                old_value = self.controller.dehumidifier_data["time_to_reduce"][key]
                new_value = (0.75 * old_value) + (0.25 * median_time)
                
                # Round to nearest tenth of a minute
                self.controller.dehumidifier_data["time_to_reduce"][key] = round(new_value, 1)
                
                _LOGGER.info(f"Updated humidity reduction rate for {key}: {new_value:.1f} minutes")

    def _analyze_humidity_increase(self):
        """Analyze how fast humidity increases when dehumidifier is off."""
        # Find consecutive records when dehumidifier was off and humidity increased
        increase_data = {}
        
        for i in range(1, len(self.humidity_data)):
            prev = self.humidity_data[i-1]
            curr = self.humidity_data[i]
            
            # Check if time between readings is reasonable (< 2 hours)
            try:
                prev_time = datetime.fromisoformat(prev["timestamp"])
                curr_time = datetime.fromisoformat(curr["timestamp"])
                
                time_diff = (curr_time - prev_time).total_seconds() / 3600  # in hours
                
                if (not prev["dehumidifier_on"] and not curr["dehumidifier_on"] and 
                    prev["humidity"] < curr["humidity"] and 
                    0 < time_diff < 2):
                    
                    # Round humidities to nearest percent
                    start_humidity = round(prev["humidity"])
                    end_humidity = round(curr["humidity"])
                    
                    if start_humidity < end_humidity:
                        # Calculate hours per 1% increase
                        humidity_diff = end_humidity - start_humidity
                        hours_per_percent = time_diff / humidity_diff
                        
                        # Create range key (e.g. "60_to_65")
                        # We use larger ranges for increase data
                        key = None
                        if 60 <= start_humidity < 65 and 60 < end_humidity <= 65:
                            key = "60_to_65"
                        elif 65 <= start_humidity < 70 and 65 < end_humidity <= 70:
                            key = "65_to_70"
                        elif 60 <= start_humidity < 70 and 60 < end_humidity <= 70:
                            # For smaller changes that don't cross boundaries
                            key = f"{start_humidity}_to_{end_humidity}"
                            
                        if key and key not in increase_data:
                            increase_data[key] = []
                        if key:
                            increase_data[key].append(hours_per_percent)
            except (ValueError, TypeError):
                continue
        
        # Update model with new median values
        for key, times in increase_data.items():
            if len(times) >= self.min_data_points_for_update:
                median_time = statistics.median(times)
                
                # Ensure we have the category in our model
                if key not in self.controller.dehumidifier_data["time_to_increase"]:
                    default_value = 5 if "65_to_70" in key else 1  # Default values
                    self.controller.dehumidifier_data["time_to_increase"][key] = default_value
                    
                # Update with exponential moving average (80% old, 20% new)
                old_value = self.controller.dehumidifier_data["time_to_increase"][key]
                new_value = (0.8 * old_value) + (0.2 * median_time)
                
                # Round to nearest tenth of an hour
                self.controller.dehumidifier_data["time_to_increase"][key] = round(new_value, 1)
                
                _LOGGER.info(f"Updated humidity increase rate for {key}: {new_value:.1f} hours")

    def _analyze_weather_impact(self):
        """Analyze how weather affects humidity increase rate."""
        if not any("weather" in data and data["weather"] for data in self.humidity_data):
            return  # No weather data available
            
        # Initialize weather impact model if not present
        if "weather_impact" not in self.controller.dehumidifier_data:
            self.controller.dehumidifier_data["weather_impact"] = {
                "rainy": 1.5,  # Default: 50% faster humidity increase when rainy
                "dry": 0.8,    # Default: 20% slower humidity increase when dry
                "other": 1.0   # Default: normal humidity increase for other weather
            }
            
        # Group data by weather category
        weather_humidity_data = {
            "rainy": [],
            "dry": [],
            "other": []
        }
        
        # Find consecutive readings with same weather conditions
        for i in range(1, len(self.humidity_data)):
            prev = self.humidity_data[i-1]
            curr = self.humidity_data[i]
            
            if not prev.get("weather") or not curr.get("weather"):
                continue
                
            # Determine weather category
            weather_category = None
            for category, conditions in self.weather_categories.items():
                if prev["weather"] in conditions and curr["weather"] in conditions:
                    weather_category = category
                    break
            
            if not weather_category:
                weather_category = "other"
                
            try:
                prev_time = datetime.fromisoformat(prev["timestamp"])
                curr_time = datetime.fromisoformat(curr["timestamp"])
                
                time_diff = (curr_time - prev_time).total_seconds() / 3600  # in hours
                
                if (not prev["dehumidifier_on"] and not curr["dehumidifier_on"] and 
                    prev["humidity"] < curr["humidity"] and 
                    0 < time_diff < 6):  # Longer time allowed for weather analysis
                    
                    # Calculate humidity increase rate per hour
                    humidity_diff = curr["humidity"] - prev["humidity"]
                    increase_rate = humidity_diff / time_diff
                    
                    weather_humidity_data[weather_category].append(increase_rate)
            except (ValueError, TypeError):
                continue
        
        # Calculate median increase rates for each weather category
        base_rate = None
        for category, rates in weather_humidity_data.items():
            if category == "other" or not base_rate:
                base_rate = statistics.median(rates)
                    
        # Only update multipliers if we have a base rate
        if base_rate and base_rate > 0:
            for category, rates in weather_humidity_data.items():
                if len(rates) >= self.min_data_points_for_update:
                    median_rate = statistics.median(rates)
                    multiplier = median_rate / base_rate
                    
                    # Update with exponential moving average
                    old_value = self.controller.dehumidifier_data["weather_impact"][category]
                    new_value = (0.8 * old_value) + (0.2 * multiplier)
                    
                    # Bound the multiplier to reasonable values (0.5 to 3.0)
                    new_value = max(0.5, min(3.0, new_value))
                    
                    self.controller.dehumidifier_data["weather_impact"][category] = round(new_value, 2)
                    _LOGGER.info(f"Updated weather impact for {category}: {new_value:.2f}x")

    def _analyze_temperature_impact(self):
        """Analyze how temperature affects humidity behavior."""
        if not any("temperature" in data and data["temperature"] for data in self.humidity_data):
            return  # No temperature data available
            
        # Initialize temperature impact model if not present
        if "temp_impact" not in self.controller.dehumidifier_data:
            self.controller.dehumidifier_data["temp_impact"] = {
                "cold": 0.7,   # Slower humidity changes when cold
                "cool": 0.9,
                "warm": 1.0,   # Baseline
                "hot": 1.2     # Faster humidity changes when hot
            }
            
        # Group data by temperature category
        temp_humidity_data = {
            "cold": [],
            "cool": [],
            "warm": [],
            "hot": []
        }
        
        # Find consecutive readings with similar temperature conditions
        for i in range(1, len(self.humidity_data)):
            prev = self.humidity_data[i-1]
            curr = self.humidity_data[i]
            
            if not prev.get("temperature") or not curr.get("temperature"):
                continue
                
            # Determine temperature category
            temp_category = None
            for category, (min_temp, max_temp) in self.temp_categories.items():
                if (min_temp <= prev["temperature"] < max_temp and 
                    min_temp <= curr["temperature"] < max_temp):
                    temp_category = category
                    break
            
            if not temp_category:
                continue
                
            try:
                prev_time = datetime.fromisoformat(prev["timestamp"])
                curr_time = datetime.fromisoformat(curr["timestamp"])
                
                time_diff = (curr_time - prev_time).total_seconds() / 3600  # in hours
                
                if time_diff > 0 and abs(prev["humidity"] - curr["humidity"]) > 0:
                    # Calculate the rate of humidity change (absolute)
                    humidity_change_rate = abs(curr["humidity"] - prev["humidity"]) / time_diff
                    
                    temp_humidity_data[temp_category].append(humidity_change_rate)
            except (ValueError, TypeError):
                continue
        
        # Calculate median change rates for each temperature category
        warm_rate = None
        for category, rates in temp_humidity_data.items():
            if category == "warm" and len(rates) >= self.min_data_points_for_update:
                warm_rate = statistics.median(rates)
                break
                
        # Only update multipliers if we have a warm rate as baseline
        if warm_rate and warm_rate > 0:
            for category, rates in temp_humidity_data.items():
                if len(rates) >= self.min_data_points_for_update:
                    median_rate = statistics.median(rates)
                    multiplier = median_rate / warm_rate
                    
                    # Update with exponential moving average
                    old_value = self.controller.dehumidifier_data["temp_impact"][category]
                    new_value = (0.8 * old_value) + (0.2 * multiplier)
                    
                    # Bound the multiplier to reasonable values (0.5 to 2.0)
                    new_value = max(0.5, min(2.0, new_value))
                    
                    self.controller.dehumidifier_data["temp_impact"][category] = round(new_value, 2)
                    _LOGGER.info(f"Updated temperature impact for {category}: {new_value:.2f}x")

    def _analyze_humidity_difference_impact(self):
        """Analyze how the outdoor/indoor humidity difference affects humidity increase rate."""
        # Check if we have enough data points with humidity difference
        if not any("humidity_diff" in data and data["humidity_diff"] is not None 
                 for data in self.humidity_data):
            return  # No humidity difference data available
            
        # Initialize humidity difference impact model if not present
        if "humidity_diff_impact" not in self.controller.dehumidifier_data:
            self.controller.dehumidifier_data["humidity_diff_impact"] = {
                "negative": 0.7,   # When outdoor humidity is lower than indoor
                "neutral": 1.0,    # When indoor and outdoor humidity are similar
                "positive": 1.3,   # When outdoor humidity is higher than indoor
                "extreme": 1.8     # When outdoor humidity is much higher than indoor
            }
            
        # Categories for humidity differences
        humidity_diff_categories = {
            "negative": (-100, -5),  # Outdoor humidity is lower than indoor
            "neutral": (-5, 5),     # Indoor and outdoor humidity are similar
            "positive": (5, 15),     # Outdoor humidity is higher than indoor
            "extreme": (15, 100)     # Outdoor humidity is much higher than indoor
        }
            
        # Group data by humidity difference category
        humidity_diff_data = {
            "negative": [],
            "neutral": [],
            "positive": [],
            "extreme": []
        }
        
        # Find consecutive readings with humidity increases and classify by humidity difference
        for i in range(1, len(self.humidity_data)):
            prev = self.humidity_data[i-1]
            curr = self.humidity_data[i]
            
            # Need both points to have humidity difference data
            if (prev.get("humidity_diff") is None or curr.get("humidity_diff") is None or
                prev.get("humidity") is None or curr.get("humidity") is None):
                continue
                
            try:
                # Calculate average humidity difference during the period
                avg_humidity_diff = (prev["humidity_diff"] + curr["humidity_diff"]) / 2
                
                # Find the category this falls into
                diff_category = None
                for category, (min_diff, max_diff) in humidity_diff_categories.items():
                    if min_diff <= avg_humidity_diff < max_diff:
                        diff_category = category
                        break
                        
                if not diff_category:
                    continue
                    
                prev_time = datetime.fromisoformat(prev["timestamp"])
                curr_time = datetime.fromisoformat(curr["timestamp"])
                
                time_diff = (curr_time - prev_time).total_seconds() / 3600  # in hours
                
                # Only analyze periods when dehumidifier is off and humidity is increasing
                if (not prev["dehumidifier_on"] and not curr["dehumidifier_on"] and 
                    prev["humidity"] < curr["humidity"] and 
                    0 < time_diff < 6):
                    
                    # Calculate humidity increase rate per hour
                    humidity_diff = curr["humidity"] - prev["humidity"]
                    increase_rate = humidity_diff / time_diff
                    
                    humidity_diff_data[diff_category].append(increase_rate)
            except (ValueError, TypeError):
                continue
                
        # Calculate median increase rates for each humidity difference category
        neutral_rate = None
        for category, rates in humidity_diff_data.items():
            if category == "neutral" and len(rates) >= self.min_data_points_for_update:
                neutral_rate = statistics.median(rates)
                break
                
        # Only update multipliers if we have a neutral rate as baseline
        if neutral_rate and neutral_rate > 0:
            for category, rates in humidity_diff_data.items():
                if len(rates) >= self.min_data_points_for_update:
                    median_rate = statistics.median(rates)
                    multiplier = median_rate / neutral_rate
                    
                    # Update with exponential moving average
                    old_value = self.controller.dehumidifier_data["humidity_diff_impact"][category]
                    new_value = (0.8 * old_value) + (0.2 * multiplier)
                    
                    # Bound the multiplier to reasonable values (0.4 to 3.0)
                    new_value = max(0.4, min(3.0, new_value))
                    
                    self.controller.dehumidifier_data["humidity_diff_impact"][category] = round(new_value, 2)
                    _LOGGER.info(f"Updated humidity difference impact for {category}: {new_value:.2f}x")

    def _analyze_energy_efficiency(self):
        """Analyze energy efficiency during dehumidification."""
        # Skip if no energy data is available
        if not self.controller.energy_sensor:
            return
            
        efficiency_data = {}
        
        # Find consecutive readings to calculate energy usage per % humidity reduction
        for i in range(1, len(self.humidity_data)):
            prev = self.humidity_data[i-1]
            curr = self.humidity_data[i]
            
            # Need both points to have humidity and energy data
            if (prev.get("humidity") is None or curr.get("humidity") is None or 
                prev.get("energy") is None or curr.get("energy") is None or 
                not prev.get("dehumidifier_on") or not curr.get("dehumidifier_on")):
                continue
                
            try:
                # Calculate humidity change
                humidity_change = prev["humidity"] - curr["humidity"]
                
                # Only analyze when humidity was reduced
                if humidity_change <= 0:
                    continue
                    
                # Calculate energy used
                energy_used = curr["energy"] - prev["energy"]
                if energy_used <= 0:
                    continue
                    
                # Calculate efficiency (Wh per % humidity)
                efficiency = energy_used / humidity_change
                
                # Categorize the efficiency
                efficiency_category = None
                for category, (min_val, max_val) in self.efficiency_categories.items():
                    if min_val <= efficiency < max_val:
                        efficiency_category = category
                        break
                        
                if not efficiency_category:
                    continue
                    
                # Record this efficiency value for the category
                if efficiency_category not in efficiency_data:
                    efficiency_data[efficiency_category] = []
                    
                efficiency_data[efficiency_category].append(efficiency)
                
                # Also categorize by temperature range if available
                if curr.get("temperature") is not None:
                    temp = curr["temperature"]
                    temp_category = None
                    
                    for cat, (min_t, max_t) in self.temp_categories.items():
                        if min_t <= temp < max_t:
                            temp_category = cat
                            break
                            
                    if temp_category:
                        temp_efficiency_key = f"{temp_category}_efficiency"
                        if temp_efficiency_key not in efficiency_data:
                            efficiency_data[temp_efficiency_key] = []
                            
                        efficiency_data[temp_efficiency_key].append(efficiency)
                
            except (ValueError, TypeError):
                continue
                
        # Calculate median efficiency for each category
        for category, values in efficiency_data.items():
            if len(values) >= self.min_data_points_for_update:
                median_efficiency = statistics.median(values)
                
                # Update with exponential moving average if data exists
                if category in self.controller.dehumidifier_data["energy_efficiency"]:
                    old_value = self.controller.dehumidifier_data["energy_efficiency"][category]
                    new_value = (0.8 * old_value) + (0.2 * median_efficiency)
                else:
                    new_value = median_efficiency
                    
                self.controller.dehumidifier_data["energy_efficiency"][category] = round(new_value, 2)
                _LOGGER.info(f"Updated energy efficiency for {category}: {new_value:.2f} Wh per % humidity")

    def get_current_model(self):
        """Return the current learning model data for display."""
        return {
            "time_to_reduce": self.controller.dehumidifier_data["time_to_reduce"],
            "time_to_increase": self.controller.dehumidifier_data["time_to_increase"],
            "weather_impact": self.controller.dehumidifier_data.get("weather_impact", {}),
            "temp_impact": self.controller.dehumidifier_data.get("temp_impact", {}),
            "humidity_diff_impact": self.controller.dehumidifier_data.get("humidity_diff_impact", {}),
            "energy_efficiency": self.controller.dehumidifier_data.get("energy_efficiency", {}),
            "data_points": len(self.humidity_data)
        }
