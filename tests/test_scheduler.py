import random
from custom_components.fuktstyrning.scheduler import build_optimized_schedule


def test_build_schedule_short_forecast(monkeypatch):
    """Ensure short price forecasts are padded to 24 hours."""
    monkeypatch.setattr(random, "choice", lambda seq: 0)
    schedule = build_optimized_schedule(
        current_humidity=75.0,
        max_humidity=70.0,
        price_forecast=[0.1, 0.2],
        reduction_rate=1.0,
        increase_rate=0.0,
        alpha=0.1,
    )
    assert len(schedule) == 24
    assert all(isinstance(v, bool) for v in schedule)
    assert sum(schedule) >= 2


def test_build_schedule_hours_needed(monkeypatch):
    """Schedule should contain expected number of on-hours."""
    monkeypatch.setattr(random, "choice", lambda seq: 0)
    prices = list(range(24))
    schedule = build_optimized_schedule(
        current_humidity=80.0,
        max_humidity=70.0,
        price_forecast=prices,
        reduction_rate=1.0,
        increase_rate=0.0,
        alpha=0.0,
    )
    assert len(schedule) == 24
    assert sum(schedule) == 13  # from predict_hours_needed
