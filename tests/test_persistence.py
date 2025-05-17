import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.fuktstyrning.persistence import Persistence

@pytest.fixture
def mock_hass():
    return MagicMock()

@pytest.fixture
def controller(mock_hass):
    ctrl = MagicMock()
    ctrl.learning_module = MagicMock()
    return ctrl

@pytest.mark.asyncio
async def test_load_invokes_learning_module(mock_hass, controller):
    persistence = Persistence(mock_hass, "entry")
    controller.learning_module.load_learning_data = AsyncMock()

    await persistence.load(controller)

    controller.learning_module.load_learning_data.assert_awaited_once()

@pytest.mark.asyncio
async def test_save_invokes_learning_module(mock_hass, controller):
    persistence = Persistence(mock_hass, "entry")
    controller.learning_module.save_learning_data = AsyncMock()

    await persistence.save(controller)

    controller.learning_module.save_learning_data.assert_awaited_once()
