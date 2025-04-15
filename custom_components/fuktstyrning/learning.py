"""Learning module for Fuktstyrning that analyzes historical data and adjusts models."""
import logging
from datetime import datetime, timedelta
import statistics
import json
import os
import asyncio
import math

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

class DehumidifierLearningModule:
    """Module for learning how humidity changes in the crawl space."""

    def __init__(self, hass, controller):
        """Initialize the learning module."""
        self.hass = hass
        self.controller = controller
        self.humidity_data = []
        self.learning_data_file = os.path.join(
            hass.config.path(), "fuktstyrning_learning_data.json"
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
        
        # Load existing learning data
        self.load_learning_data()

    async def initialize(self):
        """Start the learning process."""
        # Register periodic analysis
        self._unsub_interval = async_track_time_interval(
            self.hass, 
            self._perform_analysis,
            timedelta(hours=12)  # Run analysis twice daily
        )
        
        # Also schedule a delayed initial analysis
        self.hass.async_create_task(
            self._delayed_initial_analysis()
        )
    
    async def _delayed_initial_analysis(self):
        """Run initial analysis after a delay to gather some data first."""
        await asyncio.sleep(3600)  # Wait 1 hour
        await self._perform_analysis(datetime.now())
        
    async def shutdown(self):
        """Shut down the learning module."""
        if self._unsub_interval:
            self._unsub_interval()
            
        # Save learning data one last time
        self.save_learning_data()

    def load_learning_data(self):
        """Load learning data from file."""
        try:
            if os.path.exists(self.learning_data_file):
                with open(self.learning_data_file, "r") as f:
                    data = json.load(f)
                    
                # Update controller with learned data
                if "time_to_reduce" in data:
                    self.controller.dehumidifier_data["time_to_reduce"] = data["time_to_reduce"]
                if "time_to_increase" in data:
                    self.controller.dehumidifier_data["time_to_increase"] = data["time_to_increase"]
                if "weather_impact" in data:
                    self.controller.dehumidifier_data["weather_impact"] = data["weather_impact"]
                if "temp_impact" in data:
                    self.controller.dehumidifier_data["temp_impact"] = data["temp_impact"]
                if "humidity_diff_impact" in data:
                    self.controller.dehumidifier_data["humidity_diff_impact"] = data["humidity_diff_impact"]
                    
                _LOGGER.info("Loaded learning data from file")
        except Exception as e:
            _LOGGER.error(f"Error loading learning data: {e}")

    def save_learning_data(self):
        """Save learning data to file."""
        try:
            data = {
                "time_to_reduce": self.controller.dehumidifier_data["time_to_reduce"],
                "time_to_increase": self.controller.dehumidifier_data["time_to_increase"]
            }
            
            # Add weather and temperature impact if available
            if "weather_impact" in self.controller.dehumidifier_data:
                data["weather_impact"] = self.controller.dehumidifier_data["weather_impact"]
            if "temp_impact" in self.controller.dehumidifier_data:
                data["temp_impact"] = self.controller.dehumidifier_data["temp_impact"]
            if "humidity_diff_impact" in self.controller.dehumidifier_data:
                data["humidity_diff_impact"] = self.controller.dehumidifier_data["humidity_diff_impact"]
                
            with open(self.learning_data_file, "w") as f:
                json.dump(data, f, indent=2)
                
            _LOGGER.info("Saved learning data to file")
        except Exception as e:
            _LOGGER.error(f"Error saving learning data: {e}")

    def record_humidity_data(self, humidity, dehumidifier_on, temperature=None, weather=None, 
                           outdoor_humidity=None, outdoor_temp=None):
        """Record current humidity data with context."""
        now = datetime.now()
        
        # Calculate absolute humidity and dew point if possible
        abs_humidity = None
        dew_point = None
        if humidity is not None and temperature is not None:
            abs_humidity = self._calculate_absolute_humidity(humidity, temperature)
            dew_point = self._calculate_dew_point(humidity, temperature)
            
        outdoor_abs_humidity = None
        outdoor_dew_point = None
        if outdoor_humidity is not None and outdoor_temp is not None:
            outdoor_abs_humidity = self._calculate_absolute_humidity(outdoor_humidity, outdoor_temp)
            outdoor_dew_point = self._calculate_dew_point(outdoor_humidity, outdoor_temp)
            
        # Calculate humidity difference (indoor vs outdoor)
        humidity_diff = None
        abs_humidity_diff = None
        if humidity is not None and outdoor_humidity is not None:
            humidity_diff = outdoor_humidity - humidity
            
        if abs_humidity is not None and outdoor_abs_humidity is not None:
            abs_humidity_diff = outdoor_abs_humidity - abs_humidity
        
        data_point = {
            "timestamp": now.isoformat(),
            "humidity": humidity,
            "dehumidifier_on": dehumidifier_on,
            "temperature": temperature,
            "weather": weather,
            "outdoor_humidity": outdoor_humidity,
            "outdoor_temp": outdoor_temp,
            "abs_humidity": abs_humidity,
            "dew_point": dew_point,
            "outdoor_abs_humidity": outdoor_abs_humidity,
            "outdoor_dew_point": outdoor_dew_point,
            "humidity_diff": humidity_diff,
            "abs_humidity_diff": abs_humidity_diff
        }
        
        self.humidity_data.append(data_point)
        
        # Keep only last 1000 data points to prevent memory issues
        if len(self.humidity_data) > 1000:
            self.humidity_data = self.humidity_data[-1000:]

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
        _LOGGER.info("Performing analysis of humidity data")
        
        if len(self.humidity_data) < 10:
            _LOGGER.info("Not enough data for analysis yet")
            return
            
        # Analyze humidity reduction rate when dehumidifier is on
        self._analyze_humidity_reduction()
        
        # Analyze humidity increase rate when dehumidifier is off
        self._analyze_humidity_increase()
        
        # Analyze weather impact on humidity
        self._analyze_weather_impact()
        
        # Analyze temperature impact on humidity
        self._analyze_temperature_impact()
        
        # Analyze indoor-outdoor humidity difference impact
        self._analyze_humidity_difference_impact()
        
        # Save updated learning data
        self.save_learning_data()
        
        _LOGGER.info("Analysis complete, models updated")

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
            if len(rates) >= self.min_data_points_for_update:
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

    def get_current_model(self):
        """Return the current learning model data for display."""
        return {
            "time_to_reduce": self.controller.dehumidifier_data["time_to_reduce"],
            "time_to_increase": self.controller.dehumidifier_data["time_to_increase"],
            "weather_impact": self.controller.dehumidifier_data.get("weather_impact", {}),
            "temp_impact": self.controller.dehumidifier_data.get("temp_impact", {}),
            "humidity_diff_impact": self.controller.dehumidifier_data.get("humidity_diff_impact", {}),
            "data_points": len(self.humidity_data)
        }
