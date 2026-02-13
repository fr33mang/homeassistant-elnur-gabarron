from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.climate import ATTR_HVAC_MODE
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.components.climate import SERVICE_SET_HVAC_MODE, SERVICE_SET_TEMPERATURE, HVACMode
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.elnur_gabarron.climate import async_setup_entry
from custom_components.elnur_gabarron.const import DOMAIN


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with zone data."""
    coordinator = MagicMock()
    coordinator.data = {
        "mock_device_id_abcdef123_zone3": {
            "zone_id": "3",
            "name": "Living Room",
            "device_name": "Main Heater",
            "group_name": "Test Home",
            "status": {
                "mtemp": "21.5",  # measured temperature
                "stemp": "22.0",  # setpoint temperature
                "mode": "on",
                "heating": "1",
            },
            "setup": {
                "factory_options": {
                    "accumulator_power": "1500",
                    "emitter_power": "1000",
                }
            },
        }
    }
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


@pytest.fixture
def mock_entry():
    """Create a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test@example.com",
            "password": "testpass123",
            "serial_id": "7",
        },
    )


async def test_async_setup_entry(hass: HomeAssistant, mock_coordinator, mock_entry):
    """Test climate entity setup."""
    hass.data[DOMAIN] = {mock_entry.entry_id: mock_coordinator}

    entities = []

    def async_add_entities(new_entities):
        entities.extend(new_entities)

    await async_setup_entry(hass, mock_entry, async_add_entities)

    assert len(entities) == 1
    entity = entities[0]

    assert entity.name == "Living Room"
    assert entity._zone_id == "3"
    assert entity._device_id == "mock_device_id_abcdef123"


async def test_climate_entity_properties(hass: HomeAssistant, mock_coordinator, mock_entry):
    """Test climate entity properties."""
    hass.data[DOMAIN] = {mock_entry.entry_id: mock_coordinator}

    entities = []

    def async_add_entities(new_entities):
        entities.extend(new_entities)

    await async_setup_entry(hass, mock_entry, async_add_entities)

    entity = entities[0]

    # Test current temperature
    assert entity.current_temperature == 21.5

    # Test target temperature
    assert entity.target_temperature == 22.0

    # Test HVAC mode (mode "on" defaults to AUTO)
    assert entity.hvac_mode == HVACMode.AUTO

    # Test device info
    device_info = entity.device_info
    assert device_info["name"] == "Living Room"
    assert device_info["manufacturer"] == "Elnur Gabarron"
    assert "1500W" in device_info["model"]
    assert device_info["suggested_area"] == "Main Heater"


async def test_climate_entity_hvac_mode_off(hass: HomeAssistant, mock_coordinator, mock_entry):
    """Test climate entity with HVAC mode off."""
    mock_coordinator.data["mock_device_id_abcdef123_zone3"]["status"]["mode"] = "off"

    hass.data[DOMAIN] = {mock_entry.entry_id: mock_coordinator}

    entities = []

    def async_add_entities(new_entities):
        entities.extend(new_entities)

    await async_setup_entry(hass, mock_entry, async_add_entities)

    entity = entities[0]

    assert entity.hvac_mode == HVACMode.OFF


async def test_climate_set_temperature(hass: HomeAssistant, mock_coordinator, mock_entry):
    """Test setting target temperature updates optimistic state."""
    hass.data[DOMAIN] = {mock_entry.entry_id: mock_coordinator}

    entities = []

    def async_add_entities(new_entities):
        entities.extend(new_entities)

    await async_setup_entry(hass, mock_entry, async_add_entities)

    entity = entities[0]

    # Manually set hass to allow write
    entity.hass = hass
    entity.entity_id = "climate.test"

    # Mock the API method
    mock_coordinator.api = MagicMock()
    mock_coordinator.api.set_temperature = AsyncMock(return_value=True)

    await entity.async_set_temperature(**{ATTR_TEMPERATURE: 23.0})

    # Verify optimistic state
    assert entity._optimistic_target_temp == 23.0

    # Verify API was called
    mock_coordinator.api.set_temperature.assert_called_once()


async def test_climate_set_hvac_mode_heat(hass: HomeAssistant, mock_coordinator, mock_entry):
    """Test setting HVAC mode to heat."""
    hass.data[DOMAIN] = {mock_entry.entry_id: mock_coordinator}

    entities = []

    def async_add_entities(new_entities):
        entities.extend(new_entities)

    await async_setup_entry(hass, mock_entry, async_add_entities)

    entity = entities[0]
    entity.hass = hass
    entity.entity_id = "climate.test"

    # Mock the API method
    mock_coordinator.api = MagicMock()
    mock_coordinator.api.set_mode = AsyncMock(return_value=True)

    await entity.async_set_hvac_mode(HVACMode.HEAT)

    # Verify optimistic state
    assert entity._optimistic_hvac_mode == HVACMode.HEAT

    # Verify API was called
    mock_coordinator.api.set_mode.assert_called_once()


async def test_climate_set_hvac_mode_off(hass: HomeAssistant, mock_coordinator, mock_entry):
    """Test setting HVAC mode to off."""
    hass.data[DOMAIN] = {mock_entry.entry_id: mock_coordinator}

    entities = []

    def async_add_entities(new_entities):
        entities.extend(new_entities)

    await async_setup_entry(hass, mock_entry, async_add_entities)

    entity = entities[0]
    entity.hass = hass
    entity.entity_id = "climate.test"

    # Mock the API method
    mock_coordinator.api = MagicMock()
    mock_coordinator.api.set_mode = AsyncMock(return_value=True)

    await entity.async_set_hvac_mode(HVACMode.OFF)

    # Verify optimistic state
    assert entity._optimistic_hvac_mode == HVACMode.OFF

    # Verify API was called
    mock_coordinator.api.set_mode.assert_called_once()


async def test_climate_entity_unique_id(hass: HomeAssistant, mock_coordinator, mock_entry):
    """Test climate entity unique ID generation."""
    hass.data[DOMAIN] = {mock_entry.entry_id: mock_coordinator}

    entities = []

    def async_add_entities(new_entities):
        entities.extend(new_entities)

    await async_setup_entry(hass, mock_entry, async_add_entities)

    entity = entities[0]

    assert entity.unique_id == "elnur_gabarron_mock_device_id_abcdef123_zone3"


async def test_climate_entity_heating_action(hass: HomeAssistant, mock_coordinator, mock_entry):
    """Test climate entity shows heating action when active."""
    mock_coordinator.data["mock_device_id_abcdef123_zone3"]["status"]["heating"] = "1"

    hass.data[DOMAIN] = {mock_entry.entry_id: mock_coordinator}

    entities = []

    def async_add_entities(new_entities):
        entities.extend(new_entities)

    await async_setup_entry(hass, mock_entry, async_add_entities)

    entity = entities[0]

    # When heating is active and mode is on
    from homeassistant.components.climate import HVACAction

    assert entity.hvac_action == HVACAction.HEATING
