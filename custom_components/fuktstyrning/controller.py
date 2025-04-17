"""Controller module for Fuktstyrning integration."""
import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from datetime import datetime

from .learning import DehumidifierLearningModule
from .const import (
    CONF_HUMIDITY_SENSOR, CONF_PRICE_SENSOR, CONF_DEHUMIDIFIER_SWITCH,
    CONF_WEATHER_ENTITY, CONF_OUTDOOR_HUMIDITY_SENSOR, CONF_OUTDOOR_TEMP_SENSOR,
    CONF_POWER_SENSOR, CONF_ENERGY_SENSOR, CONF_VOLTAGE_SENSOR,
    CONF_MAX_HUMIDITY, DEFAULT_MAX_HUMIDITY,
    CONF_SCHEDULE_UPDATE_TIME, DEFAULT_SCHEDULE_UPDATE_TIME
)

_LOGGER = logging.getLogger(__name__)

class FuktstyrningController:
    """Controller for the dehumidifier based on price and humidity."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize the controller."""
        self.hass = hass
        self.entry = entry
        self.learning_module = DehumidifierLearningModule(hass, entry)
        # Scheduler and persistence will be injected by __init__.py
        self.scheduler = None
        self.persistence = None

        # Configuration and default state
        self.humidity_sensor = entry.data.get(CONF_HUMIDITY_SENSOR)
        self.price_sensor = entry.data.get(CONF_PRICE_SENSOR)
        self.dehumidifier_switch = entry.data.get(CONF_DEHUMIDIFIER_SWITCH)
        self.weather_entity = entry.data.get(CONF_WEATHER_ENTITY)
        self.outdoor_humidity_sensor = entry.data.get(CONF_OUTDOOR_HUMIDITY_SENSOR)
        self.outdoor_temp_sensor = entry.data.get(CONF_OUTDOOR_TEMP_SENSOR)
        self.power_sensor = entry.data.get(CONF_POWER_SENSOR)
        self.energy_sensor = entry.data.get(CONF_ENERGY_SENSOR)
        self.voltage_sensor = entry.data.get(CONF_VOLTAGE_SENSOR)
        self.max_humidity = entry.data.get(CONF_MAX_HUMIDITY, DEFAULT_MAX_HUMIDITY)
        self.schedule_update_time = entry.data.get(CONF_SCHEDULE_UPDATE_TIME, DEFAULT_SCHEDULE_UPDATE_TIME)
        self._unsub_interval = None
        self.schedule = {}
        self.override_active = False
        self.dehumidifier_data = {
            "time_to_reduce": {
                "69_to_68": 3,
                "68_to_67": 3,
                "67_to_66": 4,
                "66_to_65": 5,
                "65_to_60": 30
            },
            "time_to_increase": {
                "60_to_65": 1,
                "65_to_70": 5
            },
            "weather_impact": {},
            "temp_impact": {},
            "humidity_diff_impact": {},
            "energy_efficiency": {}
        }

    async def initialize(self):
        """Initialize controller operations by starting the learning module."""
        try:
            _LOGGER.debug("Initializing learning module")
            await self.learning_module.initialize()
            _LOGGER.debug("Learning module initialized")
        except Exception as e:
            _LOGGER.error(f"Failed to initialize learning module: {e}")
            raise

    async def shutdown(self):
        """Shutdown the controller operations."""
        # Stop the scheduler
        if self.scheduler:
            _LOGGER.debug("Stopping scheduler")
            self.scheduler.stop()
        # Save learning data
        if self.persistence:
            _LOGGER.debug("Saving persisted data")
            await self.persistence.save(self)
        # Shutdown learning module
        _LOGGER.debug("Shutting down learning module")
        await self.learning_module.shutdown()

    async def _update_schedule(self, now=None):
        """Update the operating schedule based on price and humidity."""
        _LOGGER.debug("Updating dehumidifier schedule")

        try:
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

            # Get dehumidifier on/off state
            is_on = False
            deh_state = self.hass.states.get(self.dehumidifier_switch)
            if deh_state:
                is_on = deh_state.state == "on"

        except Exception as e:
            _LOGGER.error(f"Error getting sensor data: {e}")
            return

        # Record data for learning
        self.learning_module.record_humidity_data(
            current_humidity,
            dehumidifier_on=is_on,
            temperature=None,
            weather=None,
            outdoor_humidity=None,
            outdoor_temp=None
        )

        # Override om fukt för hög
        if current_humidity >= self.max_humidity:
            await self._turn_on_dehumidifier()
            self.override_active = True
            _LOGGER.info(f"Humidity {current_humidity}% ≥ max {self.max_humidity}%, dehumidifier ON")
            return
        elif self.override_active and current_humidity < self.max_humidity - 5:
            self.override_active = False
            _LOGGER.info(f"Humidity {current_humidity}% under threshold again, override OFF")

        # Nytt schema runt 13:00
        current_time = now.time() if now else homeassistant.util.dt.now().time()
        if current_time.hour == 13 and current_time.minute < 30:
            await self._create_daily_schedule()

        # Optimize schedule each run
        price_forecast = self._get_price_forecast()
        rain_hours = await self._get_rain_forecast()
        outdoor = {}
        if self.outdoor_humidity_sensor:
            st = self.hass.states.get(self.outdoor_humidity_sensor)
            outdoor["humidity"] = float(st.state) if st and st.state not in ("unknown", "unavailable") else None
        if self.outdoor_temp_sensor:
            st = self.hass.states.get(self.outdoor_temp_sensor)
            outdoor["temperature"] = float(st.state) if st and st.state not in ("unknown", "unavailable") else None
        self.schedule = self._optimize_schedule(price_forecast, current_humidity, rain_hours, outdoor)
        _LOGGER.info(f"Optimized schedule: {self.schedule}")
        # Follow schedule om vi inte överstyr
        if not self.override_active:
            await self._follow_schedule()

        # Uppdatera kostnadsbesparingar
        await self._update_cost_savings()

    async def _create_daily_schedule(self):
        """Create a daily schedule based on price forecasts and humidity patterns."""
        _LOGGER.debug("Creating daily schedule")
        # Get current humidity
        humidity_state = self.hass.states.get(self.humidity_sensor)
        if not humidity_state:
            _LOGGER.error(f"Could not find humidity sensor {self.humidity_sensor}")
            return
        try:
            current_humidity = float(humidity_state.state)
        except (ValueError, TypeError):
            _LOGGER.error(f"Invalid humidity value: {humidity_state.state}")
            return

        # Price forecast
        price_forecast = self._get_price_forecast()
        if not price_forecast:
            _LOGGER.error("No price forecast available, skipping schedule")
            return

        # Optional rain forecast
        rain_hours = await self._get_rain_forecast()

        # Build outdoor conditions dict if sensors are set
        outdoor_conditions = None
        if self.outdoor_humidity_sensor and self.outdoor_temp_sensor:
            oh = self.hass.states.get(self.outdoor_humidity_sensor)
            ot = self.hass.states.get(self.outdoor_temp_sensor)
            try:
                outdoor_conditions = {
                    "humidity": float(oh.state),
                    "temperature": float(ot.state),
                }
            except Exception:
                _LOGGER.warning("Could not parse outdoor sensor values")

        # Record for learning
        self.learning_module.record_humidity_data(
            current_humidity,
            dehumidifier_on=False,
            temperature=None,
            weather=None,
            outdoor_humidity=outdoor_conditions.get("humidity") if outdoor_conditions else None,
            outdoor_temp=outdoor_conditions.get("temperature") if outdoor_conditions else None,
        )

        # Optimize schedule
        self.schedule = self._optimize_schedule(
            price_forecast, current_humidity, rain_hours, outdoor_conditions
        )
        _LOGGER.info(f"New schedule created: {self.schedule}")

    async def _follow_schedule(self):
        """Follow the schedule and turn dehumidifier on/off accordingly."""
        _LOGGER.debug("Following schedule")
        now = homeassistant.util.dt.now().time()
        if not hasattr(self, "schedule") or not self.schedule:
            _LOGGER.warning("No schedule found, skipping follow step")
            return

        # Hitta aktuell post i schemat
        for period in self.schedule:
            start = period.get("start")
            end = period.get("end")
            if start <= now < end:
                # Om perioden kräver on
                if period.get("turn_on", False):
                    await self._turn_on_dehumidifier()
                else:
                    await self._turn_off_dehumidifier()
                return

        # Om utanför alla tider, se till att stänga av
        await self._turn_off_dehumidifier()

    async def _turn_on_dehumidifier(self):
        """Turn on the dehumidifier switch."""
        try:
            await self.hass.services.async_call(
                'switch', 'turn_on',
                {'entity_id': self.dehumidifier_switch},
                blocking=True
            )
            _LOGGER.info(f"Dehumidifier {self.dehumidifier_switch} turned ON")
        except Exception as e:
            _LOGGER.error(f"Error turning on dehumidifier: {e}")

    async def _turn_off_dehumidifier(self):
        """Turn off the dehumidifier switch."""
        try:
            await self.hass.services.async_call(
                'switch', 'turn_off',
                {'entity_id': self.dehumidifier_switch},
                blocking=True
            )
            _LOGGER.info(f"Dehumidifier {self.dehumidifier_switch} turned OFF")
        except Exception as e:
            _LOGGER.error(f"Error turning off dehumidifier: {e}")

    async def _update_cost_savings(self):
        """Update cost savings based on learning model."""
        try:
            savings = self.learning_module.get_current_model()
            # Store savings data for frontend or logging
            self.dehumidifier_data['cost_savings'] = savings
        except Exception as e:
            _LOGGER.error(f"Error updating cost savings: {e}")

    def _get_price_forecast(self):
        """Get price forecast from price sensor for next 24h."""
        try:
            state = self.hass.states.get(self.price_sensor)
            forecast = state.attributes.get('forecast') if state else None
            if not forecast:
                _LOGGER.error(f"No price forecast available for {self.price_sensor}")
            return forecast
        except Exception as e:
            _LOGGER.error(f"Error fetching price forecast: {e}")
            return None

    async def _get_rain_forecast(self):
        """Get expected rain hours for next 24h from weather entity."""
        try:
            state = self.hass.states.get(self.weather_entity)
            forecast = state.attributes.get('forecast') if state else None
            if not forecast:
                _LOGGER.debug(f"No weather forecast for {self.weather_entity}")
                return 0
            # Count forecast entries with precipitation > 0
            rain_hours = sum(1 for entry in forecast if entry.get('precipitation', 0) > 0)
            return rain_hours
        except Exception as e:
            _LOGGER.error(f"Error fetching rain forecast: {e}")
            return 0

    def _calculate_required_runtime(self, current_humidity, outdoor_conditions=None):
        """Calculate how many hours the dehumidifier needs to run in the next 24h."""
        model = self.learning_module.get_current_model()
        ttr = model.get("time_to_reduce", {})
        tti = model.get("time_to_increase", {})
        if current_humidity <= self.max_humidity:
            maintenance = tti.get("60_to_65", 1) if current_humidity <= 65 else tti.get("65_to_70", 2)
            return max(1, int(round(maintenance)))
        minutes = 0
        for bucket, mins in ttr.items():
            parts = bucket.split("_to_")
            if len(parts) != 2:
                continue
            high, low = float(parts[0]), float(parts[1])
            if current_humidity > high or current_humidity > low:
                minutes += mins
        hours_needed = (minutes + 59) // 60
        return min(max(hours_needed, 1), 8)

    def _optimize_schedule(self, price_forecast, current_humidity, rain_hours=None, outdoor_conditions=None):
        """Create an optimized schedule based on prices, humidity trends, and weather."""
        schedule = {hour: False for hour in range(24)}
        hours_needed = self._calculate_required_runtime(current_humidity, outdoor_conditions)
        _LOGGER.info(f"Calculated required runtime: {hours_needed}h for humidity {current_humidity}%")
        if rain_hours:
            multiplier = self.dehumidifier_data["weather_impact"].get("rainy", 1.5)
            rain_adj = min(2, len(rain_hours) / 8 * (multiplier - 1))
            hours_needed += rain_adj
            _LOGGER.info(f"Adjusted runtime by +{rain_adj:.1f} hours due to rain forecast")
        if outdoor_conditions and outdoor_conditions.get("humidity") is not None:
            out_h = outdoor_conditions["humidity"]
            if out_h > current_humidity + 10:
                diff = out_h - current_humidity
                adj = min(1.5, diff / 20)
                hours_needed += adj
                _LOGGER.info(f"Adjusted runtime by +{adj:.1f} hours due to high outdoor humidity")
        hours_by_price = sorted(range(len(price_forecast)), key=lambda i: price_forecast[i])
        avg_price = sum(price_forecast) / len(price_forecast)
        threshold = avg_price * 0.9
        scheduled = 0
        daytime = range(8, 18)
        for idx in hours_by_price:
            hr = idx % 24
            if scheduled >= hours_needed:
                break
            if hr in daytime and price_forecast[idx] < threshold:
                schedule[hr] = True
                scheduled += 1
        if scheduled < hours_needed:
            for idx in hours_by_price:
                hr = idx % 24
                if scheduled >= hours_needed:
                    break
                if not schedule[hr]:
                    schedule[hr] = True
                    scheduled += 1
        if current_humidity > (self.max_humidity - 5):
            next_hours = [(datetime.now().hour + i) % 24 for i in range(1, 4)]
            cheap = min(next_hours, key=lambda h: price_forecast[h])
            schedule[cheap] = True
            _LOGGER.info(f"Humidity is high ({current_humidity}%), forcing run at hour {cheap}")
        high_periods = []
        current = []
        for h, price in enumerate(price_forecast):
            if price > avg_price * 1.3:
                current.append(h)
            elif current:
                if len(current) >= 3:
                    high_periods.append(current)
                current = []
        if current and len(current) >= 3:
            high_periods.append(current)
        for period in high_periods:
            start = period[0]
            if start > datetime.now().hour:
                for x in range(1, 4):
                    ph = (start - x) % 24
                    if ph >= datetime.now().hour and not schedule[ph]:
                        schedule[ph] = True
                        _LOGGER.info(f"Added prep hour {ph} before high-price period starting at {start}")
                        break
        return schedule