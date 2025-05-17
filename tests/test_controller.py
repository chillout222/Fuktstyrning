import pytest
from unittest.mock import MagicMock, AsyncMock

from custom_components.fuktstyrning.controller import FuktstyrningController

class DummyEntry:
    def __init__(self, data=None):
        self.data = data or {}

@pytest.fixture
def controller(monkeypatch):
    hass = MagicMock()
    hass.states.get = MagicMock()
    entry = DummyEntry({})
    ctrl = FuktstyrningController(hass, entry)
    ctrl.humidity_sensor = "sensor.h"
    ctrl.price_sensor = "sensor.price"
    ctrl.dehumidifier_switch = "switch.dh"
    ctrl.weather_entity = "weather.w"
    ctrl.outdoor_temp_sensor = "sensor.temp"
    ctrl.learning_module = MagicMock()
    ctrl.learning_module.predict_reduction_rate.return_value = 1.0
    ctrl.lambda_manager = MagicMock()
    ctrl.lambda_manager.get_lambda.return_value = 0.5
    ctrl.lambda_manager.record_max_humidity = AsyncMock()
    ctrl._turn_on_dehumidifier = AsyncMock()
    ctrl._turn_off_dehumidifier = AsyncMock()
    return ctrl

def make_state(value, **attrs):
    st = MagicMock()
    st.state = value
    st.attributes = attrs
    return st


def test_get_price_forecast_raw(controller):
    controller.hass.states.get.return_value = make_state(
        "1",
        raw_today=[{"value": "0.1"}, {"value": 0.2}],
        raw_tomorrow=[{"value": "0.3"}],
        tomorrow_valid=True,
    )
    fc = controller._get_price_forecast()
    assert fc == [0.1, 0.2, 0.3]


def test_get_price_forecast_fallback(controller):
    controller.hass.states.get.return_value = make_state(
        "1",
        raw_today=[],
        tomorrow_valid=False,
        today="0.4,0.5",
        tomorrow=[0.6],
    )
    fc = controller._get_price_forecast()
    assert fc == [0.4, 0.5, 0.6]


@pytest.mark.asyncio
async def test_create_daily_schedule(controller, monkeypatch):
    # patch price forecast and build_optimized_schedule
    monkeypatch.setattr(controller, "_get_price_forecast", lambda: [0.1]*24)
    monkeypatch.setattr(
        "custom_components.fuktstyrning.controller.build_optimized_schedule",
        lambda **kwargs: [True] * 24,
    )
    controller.hass.states.get.side_effect = lambda eid: {
        "sensor.h": make_state("65"),
        "sensor.temp": make_state("10"),
        "weather.w": make_state("sunny"),
    }.get(eid)
    await controller._create_daily_schedule()
    assert len(controller.schedule) == 24
    assert all(controller.schedule.values())
    assert controller.schedule_created_date is not None


@pytest.mark.asyncio
async def test_immediate_override(controller):
    controller.override_active = False
    controller.max_humidity = 70.0
    event = {
        "entity_id": controller.humidity_sensor,
        "new_state": make_state("75"),
    }
    await controller.async_handle_humidity_change(event)
    assert controller.override_active is True
    controller._turn_on_dehumidifier.assert_awaited_once()
    controller.lambda_manager.record_event.assert_awaited_with(overflow=True)

    controller.override_active = True
    event["new_state"] = make_state("64")
    await controller.async_handle_humidity_change(event)
    assert controller.override_active is False
    controller._turn_off_dehumidifier.assert_awaited_once()
    controller.lambda_manager.record_event.assert_awaited_with(overflow=False)
