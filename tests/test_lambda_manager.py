"""Unit tests for lambda_manager.py."""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta

import homeassistant.util.dt as dt_util
from homeassistant.helpers.storage import Store

from custom_components.fuktstyrning.lambda_manager import LambdaManager

# Mocks
async def mock_save(*args, **kwargs):
    """Mock for async_save."""
    return None

# Test setup
@pytest.fixture
def mock_hass():
    """Provide hass fixture."""
    hass = MagicMock()
    hass.async_create_task = lambda task: asyncio.create_task(task)
    return hass

@pytest.fixture
async def lambda_manager(mock_hass):
    """Create lambda manager fixture with mocked storage."""
    manager = LambdaManager()
    
    # Patcha Store för att inte faktiskt spara till disk
    with patch.object(Store, 'async_save', new=AsyncMock(side_effect=mock_save)), \
         patch.object(Store, 'async_load', new=AsyncMock(return_value=None)):
        await manager.async_init(mock_hass, 0.5)  # Sätt initial_lambda till 0.5
    
    # Reset för tydligare test
    manager._events = []
    manager._max_humidity_window = []
    
    return manager

# Tests
@pytest.mark.asyncio
async def test_lambda_init(lambda_manager):
    """Test initialization of lambda value."""
    assert lambda_manager.get_lambda() == 0.5
    assert lambda_manager._initial_lambda == 0.5

@pytest.mark.asyncio
async def test_lambda_increase_with_overflows(lambda_manager):
    """Test that lambda increases when enough overflow events occur."""
    # Lägg till 4 overflow-händelser
    now = dt_util.now()
    
    for i in range(4):
        event_time = now - timedelta(hours=i*6)  # Jämnt fördelade över de senaste dagarna
        await lambda_manager.record_event(overflow=True)
        # Manipulera timestamp för testsyften
        lambda_manager._events[-1]["timestamp"] = event_time.isoformat()
    
    # Lägg till mock-fuktdata för att passera datakraven
    for i in range(25):
        event_time = now - timedelta(hours=i*4)
        await lambda_manager.record_max_humidity(50.0, 70.0)  # Alltid under gränsen
        lambda_manager._max_humidity_window[-1]["timestamp"] = event_time.isoformat()
    
    # Kör veckovis justering
    await lambda_manager.weekly_adjust()
    
    # Lambda bör öka med 10%
    assert lambda_manager.get_lambda() == pytest.approx(0.55, abs=0.01)

@pytest.mark.asyncio
async def test_lambda_decrease_when_safe(lambda_manager):
    """Test that lambda decreases when always under threshold."""
    now = dt_util.now()
    
    # Lägg till tillräckligt med data som alltid är under gränsen
    for i in range(25):
        event_time = now - timedelta(hours=i*4)  # Jämnt fördelade över senaste dagarna
        await lambda_manager.record_max_humidity(65.0, 70.0)  # 5% under max
        lambda_manager._max_humidity_window[-1]["timestamp"] = event_time.isoformat()
    
    # Lägg till något enstaka event, men inte overflow
    await lambda_manager.record_event(overflow=False)
    
    # Kör veckovis justering
    await lambda_manager.weekly_adjust()
    
    # Lambda bör minska med 10%
    assert lambda_manager.get_lambda() == pytest.approx(0.45, abs=0.01)

@pytest.mark.asyncio
async def test_lambda_clamp_min_max(lambda_manager):
    """Test that lambda is clamped between min and max values."""
    # Sätt lambda till nästan min
    await lambda_manager.set_lambda(0.06)  # Bör bli 0.1*initial = 0.05
    assert lambda_manager.get_lambda() >= 0.05
    
    # Sätt lambda till nästan max
    await lambda_manager.set_lambda(2.49)  # Bör bli 5*initial = 2.5
    assert lambda_manager.get_lambda() <= 2.5
    
    # Försök överstiga max
    await lambda_manager.set_lambda(10.0)  # Bör clampas till 2.5
    assert lambda_manager.get_lambda() == pytest.approx(2.5, abs=0.01)
    
    # Försök understiga min
    await lambda_manager.set_lambda(0.01)  # Bör clampas till 0.05
    assert lambda_manager.get_lambda() >= 0.05

@pytest.mark.asyncio
async def test_no_adjustment_with_insufficient_data(lambda_manager):
    """Test that no adjustment is made when there is insufficient data."""
    # Lägg bara till några få datapunkter
    now = dt_util.now()
    for i in range(5):
        event_time = now - timedelta(hours=i)
        await lambda_manager.record_max_humidity(65.0, 70.0)
        lambda_manager._max_humidity_window[-1]["timestamp"] = event_time.isoformat()
    
    # Spara ursprungligt lambda
    original_lambda = lambda_manager.get_lambda()
    
    # Kör veckovis justering
    await lambda_manager.weekly_adjust()
    
    # Lambda bör vara oförändrat
    assert lambda_manager.get_lambda() == original_lambda


