"""Constants for the Fuktstyrning integration."""

DOMAIN = "fuktstyrning"
PLATFORMS = ["sensor", "switch", "binary_sensor"]

SERVICE_UPDATE_SCHEDULE = "update_schedule"
SERVICE_RESET_COST_SAVINGS = "reset_cost_savings"
SERVICE_SET_MAX_HUMIDITY = "set_max_humidity"
SERVICE_LEARNING_RESET = "learning_reset"   # <-- NY tjänst
ATTR_ENTITY_ID = "entity_id"

# Configuration
CONF_HUMIDITY_SENSOR = "humidity_sensor"
CONF_PRICE_SENSOR = "price_sensor"
CONF_DEHUMIDIFIER_SWITCH = "dehumidifier_switch"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_MAX_HUMIDITY = "max_humidity"
CONF_LAMBDA_DEFAULT = "lambda_default"
CONF_SCHEDULE_UPDATE_TIME = "schedule_update_time"
CONF_OUTDOOR_HUMIDITY_SENSOR = "outdoor_humidity_sensor"
CONF_OUTDOOR_TEMP_SENSOR = "outdoor_temp_sensor"
CONF_POWER_SENSOR = "power_sensor"
CONF_ENERGY_SENSOR = "energy_sensor"
CONF_VOLTAGE_SENSOR = "voltage_sensor"

# Defaults
DEFAULT_MAX_HUMIDITY = 70.0
DEFAULT_LAMBDA = 0.5
DEFAULT_SCHEDULE_UPDATE_TIME = "13:00"

# Entity attributes
ATTR_SCHEDULE = "schedule"
ATTR_OVERRIDE_ACTIVE = "override_active"
ATTR_COST_SAVINGS = "cost_savings"
ATTR_SCHEDULE_CREATED = "schedule_created"
ATTR_NEXT_RUN = "next_run"
ATTR_CURRENT_PRICE = "current_price"
ATTR_OPTIMAL_PRICE = "optimal_price"
ATTR_CURRENT_POWER = "current_power"
ATTR_ENERGY_USED = "energy_used"
ATTR_ENERGY_EFFICIENCY = "energy_efficiency"

# Unique IDs
CONTROLLER_UNIQUE_ID = "controller"
SWITCH_UNIQUE_ID = "dehumidifier_switch"
SENSOR_LAMBDA_UNIQUE_ID = "lambda_parameter"
SMART_SWITCH_UNIQUE_ID = "dehumidifier_smart_control"  # unique ID for the smart-control switch
SENSOR_SAVINGS_UNIQUE_ID = "cost_savings"
SENSOR_HUMIDITY_PREDICTION_UNIQUE_ID = "humidity_prediction"
BINARY_SENSOR_OPTIMAL_RUNNING_UNIQUE_ID = "optimal_running"
SENSOR_DEW_POINT_UNIQUE_ID = "dew_point"
SENSOR_POWER_UNIQUE_ID = "power"
SENSOR_GROUND_STATE_UNIQUE_ID = "ground_state"

# Display names
CONTROLLER_NAME = "Dehumidifier Controller"
SWITCH_NAME = "Dehumidifier Smart Control"
SENSOR_SAVINGS_NAME = "Dehumidifier Cost Savings"
SENSOR_HUMIDITY_PREDICTION_NAME = "Predicted Humidity"
BINARY_SENSOR_OPTIMAL_RUNNING_NAME = "Optimal Running Period"
SENSOR_DEW_POINT_NAME = "Dew Point"
SENSOR_POWER_NAME = "Power Usage"
SENSOR_GROUND_STATE_NAME = "Ground State"
SENSOR_LAMBDA_NAME = "Dehumidifier Lambda"

# Storage
CONTROLLER_STORAGE_KEY = "fuktstyrning_controller_data"
LEARNING_STORAGE_KEY = "fuktstyrning_learning_data"
LAMBDA_STORAGE_KEY = "fuktstyrning_lambda"

# Default learning parameters
DEFAULT_TIME_TO_REDUCE = {"70_to_65": 30, "65_to_60": 45}
DEFAULT_TIME_TO_INCREASE = {"60_to_65": 15, "65_to_70": 30}
DEFAULT_REDUCTION_MINUTES = 30

# Scheduler specific constants
SCHEDULER_MIN_HOURS_NEEDED = 2
SCHEDULER_MAX_HOURS_NEEDED = 24
SCHEDULER_MIN_REDUCTION_RATE_DIVISOR = 0.1
SCHEDULER_DEFAULT_BASE_BUFFER = 3.0
SCHEDULER_DEFAULT_PRICE = 0.5
SCHEDULER_PEAK_PRICE_THRESHOLD = 1.0
SCHEDULER_OPTIMIZATION_ITERATIONS = 2

# LambdaManager specific constants
DEFAULT_LAMBDA_VALUE = 0.5 # Default initial lambda if not from config
MIN_INITIAL_LAMBDA_THRESHOLD = 0.01
LAMBDA_CLAMP_MIN_VALUE = 0.1
LAMBDA_CLAMP_INITIAL_FACTOR_MIN = 0.1  # 10%
LAMBDA_CLAMP_INITIAL_FACTOR_MAX = 5.0  # 500%
DAYS_IN_WEEK = 7
MIN_DATA_POINTS_FOR_LAMBDA_ADJUST = 24
LAMBDA_ADJUST_HUMIDITY_HYSTERESIS = 3.0 # RH %
LAMBDA_ADJUST_OVERFLOW_THRESHOLD = 3   # count
LAMBDA_ADJUST_INCREASE_FACTOR = 1.1    # 10% increase
LAMBDA_ADJUST_DECREASE_FACTOR = 0.9    # 10% decrease
