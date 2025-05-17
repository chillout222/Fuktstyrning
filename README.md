# Fuktstyrning - Smart Dehumidifier Control System

A Home Assistant integration that controls a dehumidifier in a crawl space for maximum energy efficiency based on electricity spot prices and humidity levels.

## Features
- Keeps humidity below 70% in the crawl space
- Optimizes operation based on Nordpool electricity prices (SE3 area)
- Creates a daily schedule when prices update at ~13:00
- Considers dehumidifier performance and weather forecasts
- Monitors energy consumption and efficiency (energy used per % humidity removed)
- Adapts to outdoor temperature and humidity conditions
- Tracks cost savings and energy usage statistics
- Prioritizes cost over energy consumption when prices fluctuate

## Installation
1. Copy the `custom_components/fuktstyrning` folder to your Home Assistant `config/custom_components` directory
2. Restart Home Assistant
3. Add the integration via the Home Assistant UI (Configuration -> Integrations -> Add Integration -> Fuktstyrning)

## Configuration
Configure the following entities in the integration setup:
- Humidity sensor: `sensor.aqara_t1_innerst_luftfuktighet`
- Electricity price sensor: `sensor.nordpool_kwh_se3_3_10_025`
- Dehumidifier switch: Aqara Wall plug entity
- Optional: SMHI weather forecast entity
- Optional: Outdoor humidity and temperature sensors
- Optional: Power sensor for the dehumidifier (e.g., `sensor.lumi_lumi_plug_maeu01_consumer_active_power`)
- Optional: Energy consumption sensor (e.g., `sensor.lumi_lumi_plug_maeu01_summation_delivered`)
- Optional: Voltage sensor (e.g., `sensor.lumi_lumi_plug_maeu01_rms_voltage`)
- Optional: Lambda parameter to tune price sensitivity (default is `0.5`). This can be adjusted later under the integration's options.

## Energy Monitoring & Optimization
The integration now includes advanced energy monitoring features:
- Measures actual power consumption of the dehumidifier
- Tracks total energy usage over time
- Calculates energy efficiency (Wh used per percentage point of humidity reduction)
- Learns optimal operating conditions based on energy efficiency
- Categorizes efficiency from "excellent" to "poor" based on performance
- Analyzes efficiency variations based on temperature and humidity conditions

## Dashboard
The integration includes a custom dashboard that shows:
- Current humidity level
- Electricity price now and forecast
- Dehumidifier schedule
- Cost savings statistics
- Energy consumption metrics
- Energy efficiency analysis

## Machine Learning
The system incorporates a self-learning model that continuously improves by:
- Analyzing humidity reduction rates under various conditions
- Learning how outdoor conditions affect indoor humidity
- Measuring energy efficiency at different temperature ranges
- Optimizing run times based on historical performance data

## Requirements
- Home Assistant
- A humidity sensor
- A smart plug with power monitoring (such as Aqara Smart Plug)
- Nordpool integration for electricity prices

## Services

The integration exposes several custom services that can be used in
automations. The target entity should normally be the smart control switch or
one of the sensors created by the integration.

| Service | Description |
| ------- | ----------- |
| `fuktstyrning.update_schedule` | Force regeneration of the daily schedule |
| `fuktstyrning.reset_cost_savings` | Reset the cost saving counter to zero |
| `fuktstyrning.set_max_humidity` | Temporarily change the maximum humidity threshold |
| `fuktstyrning.learning_reset` | Clear all stored learning data |

Example service calls:

```yaml
# Rebuild today's schedule
service: fuktstyrning.update_schedule
target:
  entity_id: switch.dehumidifier_smart_control

# Reset savings counter
service: fuktstyrning.reset_cost_savings
target:
  entity_id: sensor.dehumidifier_cost_savings

# Override humidity limit to 75%
service: fuktstyrning.set_max_humidity
data:
  max_humidity: 75
target:
  entity_id: switch.dehumidifier_smart_control

# Reset the learning module for all controllers
service: fuktstyrning.learning_reset
```

### Resetting the learning module

Calling `fuktstyrning.learning_reset` removes all accumulated statistics and
model data. If multiple controllers are configured an optional `entry_id` can be
passed to only reset one instance.

### Adjusting lambda values

The cost optimisation factor λ is exposed as `sensor.dehumidifier_lambda`. It is
automatically adjusted once a week based on humidity events. If you want to
manually tune it you can create a small [Python script](https://www.home-assistant.io/docs/scripts/python_script/)
that calls `lambda_manager.set_lambda()` on the controller instance. A value
around `0.5` is typically balanced between humidity and cost.

## Example automations

Below are short examples showing how the services can be invoked from a Home
Assistant automation.

```yaml
- alias: Update dehumidifier schedule at 13:05
  trigger:
    platform: time
    at: "13:05"
  action:
    service: fuktstyrning.update_schedule
    target:
      entity_id: switch.dehumidifier_smart_control

- alias: Monthly reset of cost statistics
  trigger:
    platform: time
    at: "00:00:00"
    day: 1
  action:
    service: fuktstyrning.reset_cost_savings
    target:
      entity_id: sensor.dehumidifier_cost_savings

- alias: Temporary humidity boost
  trigger:
    platform: state
    entity_id: sensor.outdoor_humidity
    to: ">= 90"
  action:
    service: fuktstyrning.set_max_humidity
    data:
      max_humidity: 80
    target:
      entity_id: switch.dehumidifier_smart_control

- alias: Clear learning data on demand
  trigger:
    platform: event
    event_type: RESET_LEARNING
  action:
    service: fuktstyrning.learning_reset
```

## Development & Testing

Install the test dependencies and run the test suite with:

```bash
pip install -r requirements-dev.txt
pytest
```
