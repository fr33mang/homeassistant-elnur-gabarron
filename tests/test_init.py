from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.elnur_gabarron import async_setup_entry, async_unload_entry
from custom_components.elnur_gabarron.api import ElnurGabarronAPIError
from custom_components.elnur_gabarron.const import DOMAIN


@pytest.fixture
def mock_api():
    """Mock the ElnurGabarronAPI."""
    with patch("custom_components.elnur_gabarron.ElnurGabarronAPI") as mock:
        mock_instance = MagicMock()
        mock_instance.authenticate = AsyncMock(return_value=True)
        mock.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_coordinator():
    """Mock the ElnurSocketIOCoordinator."""
    with patch("custom_components.elnur_gabarron.ElnurSocketIOCoordinator") as mock:
        mock_instance = MagicMock()
        mock_instance.async_config_entry_first_refresh = AsyncMock()
        mock_instance.async_start = AsyncMock()
        mock_instance.async_stop = AsyncMock()
        mock_instance.data = {
            "mock_device_id_abcdef123": {
                "3": {
                    "zone_id": "3",
                    "name": "Test Zone",
                    "current_temp": 21.5,
                    "setpoint": 22.0,
                }
            }
        }
        mock_instance.group_name = "Test Home"
        mock.return_value = mock_instance
        yield mock_instance


async def test_setup_entry_success(hass, mock_api, mock_coordinator):
    """Test successful setup of config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test@example.com",
            "password": "testpass123",
            "serial_id": "7",
        },
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.elnur_gabarron.async_get_clientsession"),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            return_value=None,
        ),
    ):
        result = await async_setup_entry(hass, entry)

    assert result is True
    assert DOMAIN in hass.data
    assert entry.entry_id in hass.data[DOMAIN]


async def test_setup_entry_auth_failure(hass, mock_coordinator):
    """Test setup failure due to authentication error."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test@example.com",
            "password": "wrongpass",
            "serial_id": "7",
        },
    )
    entry.add_to_hass(hass)

    with patch("custom_components.elnur_gabarron.ElnurGabarronAPI") as mock_api:
        mock_instance = MagicMock()
        mock_instance.authenticate = AsyncMock(return_value=False)
        mock_api.return_value = mock_instance

        with patch("custom_components.elnur_gabarron.async_get_clientsession"):
            with pytest.raises(ConfigEntryNotReady):
                await async_setup_entry(hass, entry)


async def test_setup_entry_api_error(hass, mock_coordinator):
    """Test setup failure due to API error."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test@example.com",
            "password": "testpass123",
            "serial_id": "7",
        },
    )
    entry.add_to_hass(hass)

    with patch("custom_components.elnur_gabarron.ElnurGabarronAPI") as mock_api:
        mock_instance = MagicMock()
        mock_instance.authenticate = AsyncMock(side_effect=ElnurGabarronAPIError("Connection failed"))
        mock_api.return_value = mock_instance

        with patch("custom_components.elnur_gabarron.async_get_clientsession"):
            with pytest.raises(ConfigEntryNotReady):
                await async_setup_entry(hass, entry)


async def test_setup_entry_unexpected_error(hass, mock_coordinator):
    """Test setup failure due to unexpected error."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test@example.com",
            "password": "testpass123",
            "serial_id": "7",
        },
    )
    entry.add_to_hass(hass)

    with patch("custom_components.elnur_gabarron.ElnurGabarronAPI") as mock_api:
        mock_instance = MagicMock()
        mock_instance.authenticate = AsyncMock(side_effect=Exception("Unexpected error"))
        mock_api.return_value = mock_instance

        with patch("custom_components.elnur_gabarron.async_get_clientsession"):
            with pytest.raises(ConfigEntryNotReady):
                await async_setup_entry(hass, entry)


async def test_unload_entry(hass, mock_api, mock_coordinator):
    """Test successful unload of a config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test@example.com",
            "password": "testpass123",
            "serial_id": "7",
        },
    )
    entry.add_to_hass(hass)

    # Setup the entry first
    with (
        patch("custom_components.elnur_gabarron.async_get_clientsession"),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            return_value=None,
        ),
    ):
        await async_setup_entry(hass, entry)

    assert DOMAIN in hass.data
    assert entry.entry_id in hass.data[DOMAIN]

    # Now unload it
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        return_value=True,
    ):
        result = await async_unload_entry(hass, entry)

    assert result is True
    assert entry.entry_id not in hass.data[DOMAIN]
    # Verify coordinator was stopped
    mock_coordinator.async_stop.assert_called_once()


async def test_setup_entry_updates_title(hass, mock_api, mock_coordinator):
    """Test that setup updates entry title with group name."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test@example.com",
            "password": "testpass123",
            "serial_id": "7",
        },
        title="Old Title",
    )
    entry.add_to_hass(hass)

    mock_coordinator.group_name = "New Home Name"

    with (
        patch("custom_components.elnur_gabarron.async_get_clientsession"),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            return_value=None,
        ),
    ):
        await async_setup_entry(hass, entry)

    # Entry title should be updated
    assert entry.title == "New Home Name"
