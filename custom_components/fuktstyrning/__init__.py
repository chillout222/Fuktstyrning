"""The Fuktstyrning integration."""
import asyncio
import logging
from datetime import datetime, timedelta

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.const import (
    CONF_NAME,
    CONF_ENTITY_ID,
    ATTR_ENTITY_ID,
    SERVICE_TURN_ON,
    SERVICE_TURN_OFF,
)
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_HUMIDITY_SENSOR,
    CONF_PRICE_SENSOR,
    CONF_DEHUMIDIFIER_SWITCH,
    CONF_WEATHER_ENTITY,
    CONF_MAX_HUMIDITY,
    DEFAULT_MAX_HUMIDITY,
    CONF_SCHEDULE_UPDATE_TIME,
    DEFAULT_SCHEDULE_UPDATE_TIME,
    CONF_OUTDOOR_HUMIDITY_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
)
from .learning import DehumidifierLearningModule

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)

PLATFORMS = ["sensor", "switch", "binary_sensor"]

# Service schemas
SERVICE_UPDATE_SCHEDULE = "update_schedule"
SERVICE_RESET_COST_SAVINGS = "reset_cost_savings"
SERVICE_SET_MAX_HUMIDITY = "set_max_humidity"

SERVICE_SET_MAX_HUMIDITY_SCHEMA = vol.Schema({
    vol.Required(ATTR_ENTITY_ID): cv.entity_id,
    vol.Required(CONF_MAX_HUMIDITY): vol.All(
        vol.Coerce(float), vol.Range(min=50, max=90)
    ),
})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Fuktstyrning component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fuktstyrning from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    # Store config entry data
    hass.data[DOMAIN][entry.entry_id] = {
        "controller": FuktstyrningController(hass, entry),
    }
    
    # Initialize controller
    controller = hass.data[DOMAIN][entry.entry_id]["controller"]
    await controller.initialize()
    
    # Set up platforms
    hass.config_entries.async_setup_platforms(entry, PLATFORMS)
    
    # Register services
    async def handle_update_schedule(call: ServiceCall) -> None:
        """Handle the service call to update schedule."""
        entity_id = call.data.get(ATTR_ENTITY_ID)
        
        # Find the correct controller for this entity
        for entry_id, entry_data in hass.data[DOMAIN].items():
            controller = entry_data["controller"]
            if controller.dehumidifier_switch == entity_id:
                await controller._create_daily_schedule()
                _LOGGER.info(f"Manually updated schedule for {entity_id}")
                return
                
        _LOGGER.error(f"Could not find controller for entity {entity_id}")
    
    async def handle_reset_cost_savings(call: ServiceCall) -> None:
        """Handle the service call to reset cost savings."""
        entity_id = call.data.get(ATTR_ENTITY_ID)
        
        # Find the correct controller based on the entity_id
        for entry_id, entry_data in hass.data[DOMAIN].items():
            controller = entry_data["controller"]
            if f"sensor.fuktstyrning_cost_savings" in entity_id:
                controller.cost_savings = 0
                _LOGGER.info(f"Reset cost savings for {entity_id}")
                return
                
        _LOGGER.error(f"Could not find controller for entity {entity_id}")
    
    async def handle_set_max_humidity(call: ServiceCall) -> None:
        """Handle the service call to set maximum humidity."""
        entity_id = call.data.get(ATTR_ENTITY_ID)
        max_humidity = call.data.get(CONF_MAX_HUMIDITY)
        
        # Find the correct controller based on the entity_id
        for entry_id, entry_data in hass.data[DOMAIN].items():
            controller = entry_data["controller"]
            if controller.dehumidifier_switch == entity_id:
                controller.max_humidity = max_humidity
                _LOGGER.info(f"Set max humidity to {max_humidity}% for {entity_id}")
                # Force schedule update
                await controller._update_schedule()
                return
                
        _LOGGER.error(f"Could not find controller for entity {entity_id}")
    
    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_SCHEDULE, handle_update_schedule, 
        schema=vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id})
    )
    
    hass.services.async_register(
        DOMAIN, SERVICE_RESET_COST_SAVINGS, handle_reset_cost_savings,
        schema=vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id})
    )
    
    hass.services.async_register(
        DOMAIN, SERVICE_SET_MAX_HUMIDITY, handle_set_max_humidity, 
        schema=SERVICE_SET_MAX_HUMIDITY_SCHEMA
    )
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        # Stop controller
        controller = hass.data[DOMAIN][entry.entry_id]["controller"]
        await controller.shutdown()
        
        # Remove config entry from data
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok


class FuktstyrningController:
    """Controller for the dehumidifier based on price and humidity."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize the controller."""
        self.hass = hass
        self.entry = entry
        self.humidity_sensor = entry.data.get(CONF_HUMIDITY_SENSOR)
        self.price_sensor = entry.data.get(CONF_PRICE_SENSOR)
        self.dehumidifier_switch = entry.data.get(CONF_DEHUMIDIFIER_SWITCH)
        self.weather_entity = entry.data.get(CONF_WEATHER_ENTITY)
        self.outdoor_humidity_sensor = entry.data.get(CONF_OUTDOOR_HUMIDITY_SENSOR)
        self.outdoor_temp_sensor = entry.data.get(CONF_OUTDOOR_TEMP_SENSOR)
        self.max_humidity = entry.data.get(CONF_MAX_HUMIDITY, DEFAULT_MAX_HUMIDITY)
        self.schedule_update_time = entry.data.get(
            CONF_SCHEDULE_UPDATE_TIME, DEFAULT_SCHEDULE_UPDATE_TIME
        )
        
        self._unsub_interval = None
        self.schedule = {}
        self.cost_savings = 0
        self.schedule_created_date = None
        self.override_active = False
        self.historical_data = {
            "hourly_savings": [], 
            "hourly_operations": [],
            "last_24h_hours_run": 0,
        }
        
        # Dehumidifier performance data as provided by the user
        self.dehumidifier_data = {
            # Time (minutes) to reduce humidity by X%
            "time_to_reduce": {
                "69_to_68": 3,
                "68_to_67": 3,
                "67_to_66": 4,
                "66_to_65": 5,
                "65_to_60": 30
            },
            # Time (hours) for humidity to increase by X%
            "time_to_increase": {
                "60_to_65": 1,
                "65_to_70": 5
            },
            # Energy consumption estimation (kWh)
            "estimated_power_kw": 0.35,  # An approximation for a typical dehumidifier
            "minutes_to_60": 45,  # Total time to reduce from 69% to 60%
        }
        
        # Power consumption tracking
        self.baseline_consumption = 0
        self.actual_consumption = 0
        self.energy_reading_last = None
        
        # Initialize learning module
        self.learning_module = DehumidifierLearningModule(hass, self)

    async def initialize(self):
        """Initialize the controller operations."""
        # Start periodic schedule update
        self._unsub_interval = async_track_time_interval(
            self.hass, 
            self._update_schedule,
            timedelta(minutes=15)
        )
        
        # Initialize learning module
        await self.learning_module.initialize()
        
        # Create initial schedule
        await self._update_schedule(datetime.now())
        
    async def shutdown(self):
        """Shutdown the controller operations."""
        if self._unsub_interval:
            self._unsub_interval()
            
        # Shutdown learning module
        await self.learning_module.shutdown()

    async def _update_schedule(self, now=None):
        """Update the operating schedule based on price and humidity."""
        _LOGGER.debug("Updating dehumidifier schedule")
        
        # Get current humidity
        humidity_state = self.hass.states.get(self.humidity_sensor)
        if not humidity_state:
            _LOGGER.error(f"Cannot get state of humidity sensor {self.humidity_sensor}")
            return
        
        try:
            current_humidity = float(humidity_state.state)
        except (ValueError, TypeError):
            _LOGGER.error(f"Invalid humidity value: {humidity_state.state}")
            return
        
        # Get dehumidifier state
        dehumidifier_state = self.hass.states.get(self.dehumidifier_switch)
        is_on = dehumidifier_state.state == "on" if dehumidifier_state else False
        
        # Get temperature and weather data if available for learning
        indoor_temp = None
        weather = None
        if self.weather_entity:
            weather_state = self.hass.states.get(self.weather_entity)
            if weather_state:
                weather = weather_state.state
                indoor_temp = weather_state.attributes.get("temperature")
        
        # Get outdoor humidity and temperature if available
        outdoor_humidity = None
        outdoor_temp = None
        
        if self.outdoor_humidity_sensor:
            humidity_state = self.hass.states.get(self.outdoor_humidity_sensor)
            if humidity_state:
                try:
                    outdoor_humidity = float(humidity_state.state)
                except (ValueError, TypeError):
                    _LOGGER.error(f"Invalid outdoor humidity value: {humidity_state.state}")
        
        if self.outdoor_temp_sensor:
            temp_state = self.hass.states.get(self.outdoor_temp_sensor)
            if temp_state:
                try:
                    outdoor_temp = float(temp_state.state)
                except (ValueError, TypeError):
                    _LOGGER.error(f"Invalid outdoor temperature value: {temp_state.state}")
                
        # Record data for learning module
        self.learning_module.record_humidity_data(
            current_humidity,
            dehumidifier_on=is_on,
            temperature=indoor_temp,
            weather=weather,
            outdoor_humidity=outdoor_humidity,
            outdoor_temp=outdoor_temp
        )
        
        # Check if we need to override the schedule due to high humidity
        if current_humidity >= self.max_humidity:
            await self._turn_on_dehumidifier()
            self.override_active = True
            _LOGGER.info(f"Humidity {current_humidity}% is above max threshold, turning dehumidifier ON")
            return
        elif self.override_active and current_humidity < (self.max_humidity - 5):
            # Turn off override mode when humidity is 5% below threshold
            self.override_active = False
            _LOGGER.info(f"Humidity {current_humidity}% is now well below max threshold, disabling override")
        
        # If prices are updated around 13:00, create new schedule
        current_time = now.time() if now else datetime.now().time()
        if current_time.hour == 13 and current_time.minute < 30:
            await self._create_daily_schedule()
            
        # Follow the schedule if we're not in override mode
        if not self.override_active:
            await self._follow_schedule()
            
        # Update cost savings
        await self._update_cost_savings()
    
    async def _create_daily_schedule(self):
        """Create a daily schedule based on price forecasts and humidity patterns."""
        # Get price forecast for next 24 hours
        price_state = self.hass.states.get(self.price_sensor)
        if not price_state or "tomorrow" not in price_state.attributes:
            _LOGGER.error(f"Cannot get price forecast from {self.price_sensor}")
            return
        
        # Get current humidity
        humidity_state = self.hass.states.get(self.humidity_sensor)
        if not humidity_state:
            _LOGGER.error(f"Cannot get state of humidity sensor {self.humidity_sensor}")
            return
        
        try:
            current_humidity = float(humidity_state.state)
        except (ValueError, TypeError):
            _LOGGER.error(f"Invalid humidity value: {humidity_state.state}")
            return
        
        # Get outdoor conditions for better predictions
        outdoor_conditions = {
            "humidity": None,
            "temperature": None
        }
        
        if self.outdoor_humidity_sensor:
            humidity_state = self.hass.states.get(self.outdoor_humidity_sensor)
            if humidity_state:
                try:
                    outdoor_conditions["humidity"] = float(humidity_state.state)
                except (ValueError, TypeError):
                    pass
                    
        if self.outdoor_temp_sensor:
            temp_state = self.hass.states.get(self.outdoor_temp_sensor)
            if temp_state:
                try:
                    outdoor_conditions["temperature"] = float(temp_state.state)
                except (ValueError, TypeError):
                    pass
        
        # Combine today's remaining hours and tomorrow's prices
        current_hour = datetime.now().hour
        today_prices = list(price_state.attributes.get("today", []))[current_hour:]
        tomorrow_prices = list(price_state.attributes.get("tomorrow", []))
        
        # Create 24-hour price list
        price_forecast = today_prices + tomorrow_prices
        price_forecast = price_forecast[:24]  # Ensure we only have 24 hours
        
        # Get weather forecast if available to adjust for expected rain
        rain_forecast = await self._get_rain_forecast()
        
        # Create optimized running schedule based on prices, humidity and weather
        self.schedule = self._optimize_schedule(price_forecast, current_humidity, rain_forecast, outdoor_conditions)
        self.schedule_created_date = datetime.now().date()
        
        _LOGGER.info(f"Created new dehumidifier schedule: {self.schedule}")
    
    async def _get_rain_forecast(self):
        """Get rain forecast from the weather entity if available."""
        if not self.weather_entity:
            return None
            
        weather = self.hass.states.get(self.weather_entity)
        if not weather or "forecast" not in weather.attributes:
            return None
            
        # Create a list of hours with expected rain
        rain_hours = []
        forecast = weather.attributes.get("forecast", [])
        for f in forecast:
            if "datetime" in f and "precipitation" in f:
                dt = f.get("datetime")
                if isinstance(dt, str):
                    try:
                        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
                        # Convert to local time
                        if dt.tzinfo:
                            dt = dt.astimezone(datetime.now().astimezone().tzinfo)
                    except (ValueError, TypeError):
                        continue
                    
                # Check for rain (precipitation > 0)
                if f.get("precipitation", 0) > 0:
                    rain_hours.append(dt.hour)
                    
        return rain_hours
    
    def _optimize_schedule(self, price_forecast, current_humidity, rain_hours=None, outdoor_conditions=None):
        """Create an optimized schedule based on prices, humidity trends, and weather.
        
        This algorithm tries to:
        1. Run during the cheapest hours to save money
        2. Maintain humidity below 70%
        3. Adjust runtime based on dehumidifier performance data
        4. Consider weather forecast (rain increases humidity)
        5. Use outdoor humidity to better predict humidity increases
        """
        # Initialize schedule - all hours OFF by default
        schedule = {hour: False for hour in range(24)}
        
        # Calculate how many hours we need to run the dehumidifier
        hours_needed = self._calculate_required_runtime(current_humidity, outdoor_conditions)
        
        # Apply weather impact adjustments if weather data is available
        if "weather_impact" in self.dehumidifier_data and rain_hours:
            # Increase runtime if rain is expected (rainy weather impact multiplier)
            rainy_multiplier = self.dehumidifier_data["weather_impact"].get("rainy", 1.5)
            rain_adjustment = min(2, len(rain_hours) / 8 * (rainy_multiplier - 1))
            hours_needed += rain_adjustment
            _LOGGER.info(f"Adjusted runtime by +{rain_adjustment:.1f} hours due to rain forecast")
            
        # If outdoor humidity is higher than indoor, humidity will increase faster
        # This is a simple model to account for this effect
        if outdoor_conditions and "humidity" in outdoor_conditions and outdoor_conditions["humidity"] is not None:
            outdoor_humidity = outdoor_conditions["humidity"]
            if outdoor_humidity > current_humidity + 10:  # Significantly higher outdoor humidity
                # Increase runtime proportionally to the difference
                humid_diff = outdoor_humidity - current_humidity
                humidity_adjustment = min(1.5, humid_diff / 20)  # Maximum 1.5 hours extra
                hours_needed += humidity_adjustment
                _LOGGER.info(f"Adjusted runtime by +{humidity_adjustment:.1f} hours due to high outdoor humidity")
        
        # Create a list of hours sorted by price (cheapest first)
        hours_by_price = sorted(range(len(price_forecast)), key=lambda i: price_forecast[i])
        
        # Calculate an average price threshold
        avg_price = sum(price_forecast) / len(price_forecast)
        threshold = avg_price * 0.9  # 90% of average price
        
        # First, schedule hours that are below the price threshold and also during daytime
        # (if we have solar power, it's better to run during daylight hours)
        scheduled_hours = 0
        daytime_hours = range(8, 18)  # 8 AM to 6 PM
        
        if hours_needed > 0:
            # First try scheduling during cheap daytime hours (prioritizing solar production)
            for hour_idx in hours_by_price:
                hour = hour_idx % 24  # Convert to 0-23 hour format
                
                if hour in daytime_hours and price_forecast[hour_idx] < threshold:
                    schedule[hour] = True
                    scheduled_hours += 1
                    
                    if scheduled_hours >= hours_needed:
                        break
        
        # If we still need more hours, use the cheapest available hours regardless of time
        if scheduled_hours < hours_needed:
            for hour_idx in hours_by_price:
                hour = hour_idx % 24
                
                if not schedule[hour]:  # Skip already scheduled hours
                    schedule[hour] = True
                    scheduled_hours += 1
                    
                    if scheduled_hours >= hours_needed:
                        break
        
        # Special case: If current humidity is close to threshold, ensure we run soon
        if current_humidity > (self.max_humidity - 5):
            # Ensure we run in the next few hours to bring humidity down
            next_hours = [(datetime.now().hour + i) % 24 for i in range(1, 4)]
            cheapest_next_hour = min(next_hours, key=lambda h: price_forecast[h])
            schedule[cheapest_next_hour] = True
            _LOGGER.info(f"Humidity is high ({current_humidity}%), forcing run at hour {cheapest_next_hour}")
            
        # Special case: If we have high-price periods coming up, run before them
        # Find periods with significantly above-average prices
        high_price_periods = []
        current_period = []
        for hour, price in enumerate(price_forecast):
            if price > avg_price * 1.3:  # 30% above average is considered high
                current_period.append(hour)
            elif current_period:
                if len(current_period) >= 3:  # At least 3 consecutive high-price hours
                    high_price_periods.append(current_period)
                current_period = []
                
        if current_period and len(current_period) >= 3:
            high_price_periods.append(current_period)
            
        # Try to run before high-price periods to preemptively lower humidity
        for period in high_price_periods:
            start_hour = period[0]
            if start_hour > datetime.now().hour:  # Only for future periods
                # Try to run 1-3 hours before the high-price period
                for h in range(1, 4):
                    prep_hour = (start_hour - h) % 24
                    if prep_hour >= datetime.now().hour and not schedule[prep_hour]:
                        schedule[prep_hour] = True
                        _LOGGER.info(f"Added prep hour {prep_hour} before high-price period starting at {start_hour}")
                        break
        
        return schedule
    
    def _calculate_required_runtime(self, current_humidity, outdoor_conditions=None):
        """Calculate how many hours the dehumidifier needs to run in the next 24h."""
        # If humidity is already at target levels, run maintenance cycles
        if current_humidity <= 60:
            return 1  # Run 1 hour per day for maintenance
            
        # For humidity between 60% and 70%, calculate required runtime
        if 60 < current_humidity <= 70:
            # This is a simplified model based on the provided dehumidifier data
            
            # First, estimate how long it will take to reduce to optimal level
            minutes_to_optimal = 0
            
            if current_humidity > 68:
                minutes_to_optimal += self.dehumidifier_data["time_to_reduce"]["69_to_68"]
            if current_humidity > 67:
                minutes_to_optimal += self.dehumidifier_data["time_to_reduce"]["68_to_67"]
            if current_humidity > 66:
                minutes_to_optimal += self.dehumidifier_data["time_to_reduce"]["67_to_66"]
            if current_humidity > 65:
                minutes_to_optimal += self.dehumidifier_data["time_to_reduce"]["66_to_65"]
            if current_humidity > 60:
                minutes_to_optimal += self.dehumidifier_data["time_to_reduce"]["65_to_60"]
                
            # Convert to hours and round up
            hours_to_optimal = (minutes_to_optimal + 59) // 60
            
            # Add maintenance time to prevent humidity from rising back too quickly
            # The higher the humidity, the more maintenance time needed
            maintenance_hours = 1
            if current_humidity > 65:
                maintenance_hours = 2
            
            # Adjust based on outdoor conditions
            if outdoor_conditions and outdoor_conditions.get("humidity") is not None:
                outdoor_humidity = outdoor_conditions["humidity"]
                # If outdoor humidity is significantly higher, increase runtime
                if outdoor_humidity > current_humidity + 15:
                    maintenance_hours += 1
                    
            return min(max(hours_to_optimal + maintenance_hours, 1), 8)  # Between 1-8 hours
        
        # For safety, if humidity is very high, run more
        return 8  # Maximum runtime per day
    
    async def _follow_schedule(self):
        """Follow the created schedule."""
        if not self.schedule:
            _LOGGER.warning("No schedule available, creating one")
            await self._create_daily_schedule()
            return
        
        current_hour = datetime.now().hour
        should_be_on = self.schedule.get(current_hour, False)
        
        dehumidifier_state = self.hass.states.get(self.dehumidifier_switch)
        is_on = dehumidifier_state.state == "on" if dehumidifier_state else False
        
        if should_be_on and not is_on:
            await self._turn_on_dehumidifier()
            _LOGGER.info(f"Turning dehumidifier ON according to schedule (hour {current_hour})")
        elif not should_be_on and is_on and not self.override_active:
            await self._turn_off_dehumidifier()
            _LOGGER.info(f"Turning dehumidifier OFF according to schedule (hour {current_hour})")
    
    async def _update_cost_savings(self):
        """Update cost savings based on price optimization."""
        # Get current price
        price_state = self.hass.states.get(self.price_sensor)
        if not price_state:
            return
            
        try:
            current_price = float(price_state.state)
            today_prices = list(price_state.attributes.get("today", []))
        except (ValueError, TypeError, AttributeError):
            return
            
        if not today_prices:
            return
            
        # Calculate average price
        avg_price = sum(today_prices) / len(today_prices)
        
        # Get dehumidifier power state
        dehumidifier_state = self.hass.states.get(self.dehumidifier_switch)
        is_on = dehumidifier_state.state == "on" if dehumidifier_state else False
        
        if is_on:
            # Calculate cost if we ran at average price vs. current price
            power_kw = self.dehumidifier_data["estimated_power_kw"]
            hourly_saving = power_kw * (avg_price - current_price)
            
            # If the current price is below average, we're saving money
            if current_price < avg_price:
                # Add to total savings
                self.cost_savings += hourly_saving / 4  # Divided by 4 since we check every 15 minutes
                
            # Track operation
            self.historical_data["hourly_operations"].append({
                "timestamp": datetime.now().isoformat(),
                "price": current_price,
                "avg_price": avg_price,
                "saving": hourly_saving if current_price < avg_price else 0
            })
            
            # Keep only last 100 operations
            self.historical_data["hourly_operations"] = \
                self.historical_data["hourly_operations"][-100:]
    
    async def _turn_on_dehumidifier(self):
        """Turn on the dehumidifier."""
        await self.hass.services.async_call(
            "switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: self.dehumidifier_switch}
        )
    
    async def _turn_off_dehumidifier(self):
        """Turn off the dehumidifier."""
        await self.hass.services.async_call(
            "switch", SERVICE_TURN_OFF, {ATTR_ENTITY_ID: self.dehumidifier_switch}
        )
