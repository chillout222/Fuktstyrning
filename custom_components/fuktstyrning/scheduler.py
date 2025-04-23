"""Scheduling helpers for Fuktstyrning integration."""
import logging
import math
import random
import numpy as np
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

def predict_hours_needed(current: float, target: float, reduction_rate: float) -> int:
    """Beräkna antal timmar som behövs för att nå target från current."""
    diff = current - target
    if diff <= 0:
        return 2  # Minst 2 timmar
    return max(2, min(24, math.ceil(diff / max(reduction_rate, 0.1))))
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
    alpha: float,
) -> List[bool]:
    """Returnerar ett bool-schema som lista av 24 boolska värden."""
    assert isinstance(reduction_rate, (int, float)), "reduction_rate must be numeric"
    assert isinstance(increase_rate, (int, float)), "increase_rate must be numeric"
    
    # För bakåtkompatibilitet - garantera 24 poster
    prices = list(price_forecast)[:24]
    while len(prices) < 24:
        prices.append(prices[-1] if prices else 0.5)  # Duplicera sista priset eller använd default
    
    # Lokala referenser för tydlighet
    rh_now = current_humidity
    
    # Beräkna target-fuktighet (används för överflödesberäkning)
    target_rh = max_humidity - base_buffer
    
    # ---------------------------------------------------------
    # 1. Beräkna hours_needed (2–24) med befintlig funktion
    # ---------------------------------------------------------
    hours_needed = max(2, min(24, predict_hours_needed(rh_now, target_rh, reduction_rate)))
    
    # ---------------------------------------------------------
    # 2. Peak-mask (topp 5 % eller pris > 1 SEK)
    # ---------------------------------------------------------
    p95 = np.percentile(prices, 95)
    peak_mask = [(p >= p95) or (p > 1.0) for p in prices]
    
    # ---------------------------------------------------------
    # 3. Kostnad = pris + α·overflow
    # ---------------------------------------------------------
    costs = []
    for t, price in enumerate(prices):
        overflow = max(0.0, rh_now + increase_rate * t - target_rh)
        costs.append(price + alpha * overflow)
    
    chosen = sorted(range(24), key=costs.__getitem__)[:hours_needed]
    
    # ---------------------------------------------------------
    # 4. Simulera RH och flytta bort från peak vid risk
    # ---------------------------------------------------------
    # Gör flera iterationer av simulering och optimering
    for iteration in range(2):  # Två iterationer räcker normalt
        # Simulera framtida RH baserat på nuvarande val
        current_chosen = chosen.copy()  # Använd en kopia för att undvika modifiering under iteration
        sim_rh = rh_now
        modifications = []  # Lagra ändringar att göra
        
        for h in range(24):
            # Uppdatera simulerad RH
            sim_rh += (-reduction_rate if h in current_chosen else increase_rate)
            
            # Om vi överskrider max-fuktighetsgränsen under en peak-timme
            if sim_rh > max_humidity and peak_mask[h]:
                # Hitta billigaste non-peak-timme före nuvarande timme
                candidates = [i for i in range(h) if i not in current_chosen and not peak_mask[i]]
                if candidates:
                    best = min(candidates, key=costs.__getitem__)
                    worst = max(current_chosen, key=costs.__getitem__)
                    modifications.append((worst, best))  # Spara (ta bort, lägg till)
        
        # Applicera ändringar efter iteration
        for worst, best in modifications:
            if worst in chosen and best not in chosen:  # Dubbelkolla att villkoren fortfarande gäller
                chosen.remove(worst)
                chosen.append(best)
    
    # ---------------------------------------------------------
    # 5. Stokastisk jitter ±1 h
    # ---------------------------------------------------------
    jittered = {max(0, min(23, h + random.choice([-1, 0, 1]))) for h in chosen}
    
    # Säkerställ bounds 2–24
    while len(jittered) < 2:
        jittered.add(min(set(range(24)) - jittered, key=costs.__getitem__))
    if len(jittered) > 24:
        jittered = set(sorted(jittered)[:24])
    
    # Konvertera set till lista av booleans (med bevarad ordning)    
    return [h in jittered for h in range(24)]
