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
