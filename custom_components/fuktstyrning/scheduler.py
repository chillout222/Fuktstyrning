"""Scheduling helpers for Fuktstyrning integration."""
import logging
import math
from datetime import timedelta
from typing import List, Sequence
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

class Scheduler:
    """Handles periodic schedule updates."""

    def __init__(self, hass: HomeAssistant, update_callback, interval_minutes: int = 15):
        self.hass = hass
        self.update_callback = update_callback
        self.interval = timedelta(minutes=interval_minutes)
        self._unsub = None

    async def start(self):
        """Start periodic schedule updates."""
        _LOGGER.debug("Starting schedule interval tracking")
        self._unsub = async_track_time_interval(
            self.hass,
            self.update_callback,
            self.interval,
        )

    def stop(self):
        """Stop schedule updates."""
        if self._unsub:
            _LOGGER.debug("Stopping schedule interval tracking")
            self._unsub()

# ---------------------------------------------------------------------------
# Optimized schedule generator
# ---------------------------------------------------------------------------
def build_optimized_schedule(
    *,
    current_humidity: float,
    max_humidity: float,
    price_forecast: Sequence[float],
    reduction_rate: float,
    increase_rate: float,
    peak_hours: Sequence[int] | None = None,
    base_buffer: float = 3.0,
    alpha: float = 0.0,
) -> List[bool]:
    """Returnerar ett bool-schema (len == len(price_forecast))."""
    n_hours = len(price_forecast)
    hours = list(range(n_hours))
    # Definiera peak-timmar
    if peak_hours is None:
        threshold = sorted(price_forecast)[int(n_hours * 0.7)]
        peak_mask = [p >= threshold for p in price_forecast]
    else:
        peak_mask = [(h % 24) in peak_hours for h in hours]
    # 1. Dynamisk buffert baserad på riskfönster
    dyn_buffer = base_buffer + increase_rate * sum(peak_mask)
    # 2. Grov estimation av timmar som behövs
    target_humidity = max(max_humidity - dyn_buffer, 0)
    hours_needed = max(
        0,
        math.ceil((current_humidity - target_humidity) / max(reduction_rate, 0.1)),
    )
    # 3. Sortera med pris + risk-penalty
    sort_cost: list[tuple[float, int]] = []
    for h in hours:
        overflow = max(0.0, current_humidity + increase_rate * h - target_humidity)
        penalty = alpha * overflow
        sort_cost.append((price_forecast[h] + penalty, h))
    schedule = [False] * n_hours
    for _, h in sorted(sort_cost)[:hours_needed]:
        schedule[h] = True
    # 4. Iterativ simulering för peak-risker
    for _ in range(2):
        predicted = current_humidity
        for h in hours:
            predicted += increase_rate if not schedule[h] else -reduction_rate
            if predicted >= max_humidity and peak_mask[h]:
                candidates = [x for x in hours[:h] if not schedule[x] and not peak_mask[x]]
                if not candidates:
                    break
                best = min(candidates, key=lambda x: price_forecast[x])
                schedule[best] = True
                predicted -= reduction_rate
    return schedule
