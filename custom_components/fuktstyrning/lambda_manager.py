"""Lambda parameter manager for Fuktstyrning integration."""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
import homeassistant.util.dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
LAMBDA_STORAGE_KEY = "fuktstyrning_lambda"
SENSOR_LAMBDA_UNIQUE_ID = "lambda_parameter"
SENSOR_LAMBDA_NAME = "Dehumidifier Lambda"

class LambdaManager:
    
    ENTITY_ID = "sensor.dehumidifier_lambda"
    """Manager för λ-parametern som balanserar kostnad mot fuktighet."""

    def __init__(self):
        """Initialize the lambda manager."""
        self._lambda = 0.5  # Default value
        self._initial_lambda = 0.5  # Startvärde att jämföra med
        self._store = None
        self._events = []
        self._lambda_sensor = None
        self._max_humidity_window = []
        self._hass = None
        self._lock = asyncio.Lock()  # För thread-safety

    async def async_init(self, hass: HomeAssistant, initial_lambda: float = None) -> None:
        """Initialize the lambda manager with storage."""
        self._hass = hass
        self._store = Store(hass, 2, LAMBDA_STORAGE_KEY)  # Version 2 för framtida migration
        
        # -----------------------------------------------------------
        # MIGRERING: säkerställ att lagring är på version ≥ 2
        # -----------------------------------------------------------
        if self._store.version < 2:
            _LOGGER.info("Migrerar lambda-lagring från v%s till v2 …", self._store.version)
            await self._migrate_v1_to_v2()
        
        # Ladda sparad data
        stored_data = await self._store.async_load()
        
        if stored_data:
            self._lambda = stored_data.get("lambda", 0.5)
            self._initial_lambda = stored_data.get("initial_lambda", self._lambda)
            self._events = stored_data.get("events", [])
            self._max_humidity_window = stored_data.get("max_humidity_window", [])
            _LOGGER.debug("Laddat lambda-data: %s", stored_data)
        else:
            # Om inget sparat, använd medelpris eller default
            # Hantera 0.0 som "använd default"
            if initial_lambda is not None and initial_lambda > 0.01:  # Undvik för små värden
                self._lambda = initial_lambda
                self._initial_lambda = initial_lambda
            else:
                _LOGGER.debug("Ignorerade initial_lambda=%.3f, använder default", 
                            0.0 if initial_lambda is None else initial_lambda)
            _LOGGER.info("Initierat lambda till %.3f", self._lambda)
        
        # Skapa första state
        self._update_sensor_state()
                
    def _update_sensor_state(self) -> None:
        """Sätt eller uppdatera λ-sensorns state via HA-state-API."""
        self._hass.states.async_set(
            self.ENTITY_ID,
            round(self._lambda, 3),
            {
                "unit_of_measurement": "SEK/%RH·h",
                "friendly_name": "Dehumidifier λ",
                "icon": "mdi:sigma",
            },
        )
        
    def get_lambda(self) -> float:
        """Get current lambda value."""
        return self._lambda
        
    async def set_lambda(self, value: float) -> None:
        """Set lambda value."""
        async with self._lock:  # Prevent race conditions
            if value != self._lambda:
                # Förhindra 0-division eller för små värden genom att sätta minimum
                min_lambda = max(0.1, self._initial_lambda * 0.1) if self._initial_lambda > 0 else 0.1
                self._lambda = max(min_lambda, min(self._initial_lambda * 5.0, value))
                _LOGGER.info("Lambda uppdaterad till %.3f", self._lambda)
                
                # Uppdatera state direkt
                self._update_sensor_state()
                    
                # Spara till persistent storage
                await self._save_data()
        
    async def record_event(self, overflow: bool) -> None:
        """Record a humidity event."""
        async with self._lock:  # Thread-safety för events-listan
            now = dt_util.now()
            self._events.append({"timestamp": now.isoformat(), "overflow": overflow})
            
            # Rensa gamla events (äldre än 7 dagar)
            week_ago = now - timedelta(days=7)
            self._events = [e for e in self._events 
                            if datetime.fromisoformat(e["timestamp"]) >= week_ago]
            
            # Spara data
            await self._save_data()
            _LOGGER.debug("Händelse registrerad: %s, totalt %d händelser", 
                         "överskriden fukt" if overflow else "normal nivå", 
                         len(self._events))
        
    async def record_max_humidity(self, current_humidity: float, max_humidity: float) -> None:
        """Record current humidity for weekly adjustment."""
        async with self._lock:  # Thread-safety för humidity-fönstret
            now = dt_util.now()
            self._max_humidity_window.append({
                "timestamp": now.isoformat(),
                "humidity": current_humidity,
                "max": max_humidity
            })
            
            # Rensa gamla mätningar (äldre än 7 dagar)
            week_ago = now - timedelta(days=7)
            self._max_humidity_window = [m for m in self._max_humidity_window 
                                        if datetime.fromisoformat(m["timestamp"]) >= week_ago]
        
    async def weekly_adjust(self) -> None:
        """Adjust lambda value based on weekly data."""
        now = dt_util.now()
        week_ago = now - timedelta(days=7)
        
        # Räkna overflow events senaste veckan
        overflow_count = sum(1 for e in self._events 
                             if e["overflow"] and datetime.fromisoformat(e["timestamp"]) >= week_ago)
        
        # Kontrollera om det finns tillräckligt med data
        if len(self._max_humidity_window) < 24:
            _LOGGER.info(
                "För lite data för att justera lambda (%d mätningar). Behåller %.3f", 
                len(self._max_humidity_window), self._lambda
            )
            return
        
        # Kontrollera om RH alltid varit under target-3%
        always_safe = True
        for m in self._max_humidity_window:
            if m["humidity"] > (m["max"] - 3.0):
                always_safe = False
                break
                
        # Justera lambda baserat på data
        new_lambda = self._lambda
        adjustment_needed = False
        
        if overflow_count >= 3:
            # För många överflöden - öka lambda för att prioritera fuktreducering
            new_lambda = self._lambda * 1.1
            _LOGGER.info("Ökar lambda med 10%% pga %d överflöden senaste veckan", overflow_count)
            adjustment_needed = True
        elif always_safe:
            # Alltid säkert - minska lambda för att spara pengar
            new_lambda = self._lambda * 0.9
            _LOGGER.info("Minskar lambda med 10%% pga att RH alltid varit under (max-3%%)") 
            adjustment_needed = True
        else:
            _LOGGER.info(
                "Ingen justering av lambda behövs. %d överflöden och RH har %svarit under gräns", 
                overflow_count, "" if always_safe else "inte "
            )
            
        if adjustment_needed:
            # Tillämpa min/max-gränser och uppdatera värdet
            await self.set_lambda(new_lambda)
        else:
            # Efter justering, uppdatera state
            self._update_sensor_state()
        
    # -----------------------------------------------------------
    # ===  MIGRERING V1 → V2  ====================================
    # -----------------------------------------------------------
    async def _migrate_v1_to_v2(self) -> None:
        """Migrera befintlig lagring till schema-version 2.

        v1 lagrade endast 'lambda'.  I v2 inför vi fältet
        'base_lambda' (ursprungligt grundvärde) för att
        kunna beräkna min/max-clamp som faktor × base.
        """
        data: dict[str, Any] | None = await self._store.async_load()
        data = data or {}

        # Lägg till nytt fält om det saknas
        if "lambda" in data and "initial_lambda" not in data:
            data["initial_lambda"] = data["lambda"]

        # Uppdatera versionsnummer och spara
        await self._store.async_save(data)
        self._store.version = 2
        _LOGGER.info("Migrering till v2 klar – data: %s", data)
    
    async def _save_data(self) -> None:
        """Save lambda data to storage."""
        if self._store:
            await self._store.async_save({
                "lambda": self._lambda,
                "initial_lambda": self._initial_lambda,
                "events": self._events,
                "max_humidity_window": self._max_humidity_window,
                "last_updated": dt_util.now().isoformat(),
            })



