# Fuktstyrning - Smart Dehumidifier Control System

A Home Assistant integration that controls a dehumidifier in a crawl space for maximum energy efficiency based on electricity spot prices and humidity levels.

## Features
- Keeps humidity below 70% in the crawl space
- Optimizes operation based on Nordpool electricity prices (SE3 area)
- Creates a daily schedule when prices update at ~13:00
- Considers dehumidifier performance and weather forecasts
- Tracks cost savings
- Prioritizes cost over energy consumption

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
- Optional: Tibber Pulse and Solis Inverter entities for enhanced features

## Dashboard
The integration includes a custom dashboard that shows:
- Current humidity level
- Electricity price now and forecast
- Dehumidifier schedule
- Cost savings statistics
