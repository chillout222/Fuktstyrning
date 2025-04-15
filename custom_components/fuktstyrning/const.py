"""Constants for the Fuktstyrning integration."""

DOMAIN = "fuktstyrning"

# Configuration
CONF_HUMIDITY_SENSOR = "humidity_sensor"
CONF_PRICE_SENSOR = "price_sensor"
CONF_DEHUMIDIFIER_SWITCH = "dehumidifier_switch"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_MAX_HUMIDITY = "max_humidity"
CONF_SCHEDULE_UPDATE_TIME = "schedule_update_time"
CONF_OUTDOOR_HUMIDITY_SENSOR = "outdoor_humidity_sensor"
CONF_OUTDOOR_TEMP_SENSOR = "outdoor_temp_sensor"

# Defaults
DEFAULT_MAX_HUMIDITY = 70.0
DEFAULT_SCHEDULE_UPDATE_TIME = "13:00"

# Entity attributes
ATTR_SCHEDULE = "schedule"
ATTR_OVERRIDE_ACTIVE = "override_active"
ATTR_COST_SAVINGS = "cost_savings"
ATTR_SCHEDULE_CREATED = "schedule_created"
ATTR_NEXT_RUN = "next_run"
ATTR_CURRENT_PRICE = "current_price"
ATTR_OPTIMAL_PRICE = "optimal_price"

# Unique IDs
CONTROLLER_UNIQUE_ID = "controller"
SWITCH_UNIQUE_ID = "dehumidifier_switch"
SENSOR_SAVINGS_UNIQUE_ID = "cost_savings"
SENSOR_HUMIDITY_PREDICTION_UNIQUE_ID = "humidity_prediction"
BINARY_SENSOR_OPTIMAL_RUNNING_UNIQUE_ID = "optimal_running"

# Display names
CONTROLLER_NAME = "Dehumidifier Controller"
SWITCH_NAME = "Dehumidifier Smart Control"
SENSOR_SAVINGS_NAME = "Dehumidifier Cost Savings"
SENSOR_HUMIDITY_PREDICTION_NAME = "Predicted Humidity"
BINARY_SENSOR_OPTIMAL_RUNNING_NAME = "Optimal Running Period"
