import pytest
from aiohttp import ClientError
from aioresponses import aioresponses
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.elnur_gabarron.api import ElnurGabarronAPI, ElnurGabarronAPIError
from custom_components.elnur_gabarron.const import API_BASE_URL, API_DEVICES_ENDPOINT, API_TOKEN_ENDPOINT

from .conftest import load_json_fixture


@pytest.fixture
async def api_client(hass):
    """Create an API client instance."""
    session = async_get_clientsession(hass)
    return ElnurGabarronAPI(
        session=session,
        username="test@example.com",
        password="testpass123",
        serial_id="7",
    )


async def test_authenticate_success(hass, api_client):
    """Test successful authentication."""
    auth_response = load_json_fixture("auth_success.json")

    with aioresponses() as mock_aiohttp:
        mock_aiohttp.post(
            f"{API_BASE_URL}{API_TOKEN_ENDPOINT}",
            payload=auth_response,
            status=200,
        )

        result = await api_client.authenticate()

    assert result is True
    assert api_client._access_token == auth_response["access_token"]
    assert api_client._refresh_token == auth_response["refresh_token"]


async def test_authenticate_failure_401(hass, api_client):
    """Test authentication failure with 401 response."""
    with aioresponses() as mock_aiohttp:
        mock_aiohttp.post(
            f"{API_BASE_URL}{API_TOKEN_ENDPOINT}",
            status=401,
            body="Unauthorized",
        )

        result = await api_client.authenticate()

    assert result is False


async def test_authenticate_failure_exception(hass, api_client):
    """Test authentication failure with network exception."""
    with aioresponses() as mock_aiohttp:
        mock_aiohttp.post(
            f"{API_BASE_URL}{API_TOKEN_ENDPOINT}",
            exception=ClientError("Connection error"),
        )

        with pytest.raises(ElnurGabarronAPIError):
            await api_client.authenticate()


async def test_refresh_access_token_success(hass, api_client):
    """Test successful token refresh."""
    # First authenticate to get a refresh token
    auth_response = load_json_fixture("auth_success.json")
    api_client._refresh_token = auth_response["refresh_token"]

    refresh_response = {
        "access_token": "new_access_token",
        "refresh_token": "new_refresh_token",
        "expires_in": 3600,
        "token_type": "Bearer",
    }

    with aioresponses() as mock_aiohttp:
        mock_aiohttp.post(
            f"{API_BASE_URL}{API_TOKEN_ENDPOINT}",
            payload=refresh_response,
            status=200,
        )

        result = await api_client.refresh_access_token()

    assert result is True
    assert api_client._access_token == "new_access_token"


async def test_refresh_access_token_no_refresh_token(hass, api_client):
    """Test token refresh when no refresh token is available."""
    auth_response = load_json_fixture("auth_success.json")

    with aioresponses() as mock_aiohttp:
        mock_aiohttp.post(
            f"{API_BASE_URL}{API_TOKEN_ENDPOINT}",
            payload=auth_response,
            status=200,
        )

        result = await api_client.refresh_access_token()

    # Should fall back to full authentication
    assert result is True
    assert api_client._access_token == auth_response["access_token"]


async def test_get_devices_success(hass, api_client):
    """Test successful device retrieval."""
    # Set up authenticated state
    api_client._access_token = "test_token"

    devices_response = load_json_fixture("devices_response.json")

    with aioresponses() as mock_aiohttp:
        mock_aiohttp.get(
            f"{API_BASE_URL}{API_DEVICES_ENDPOINT}",
            payload=devices_response,
            status=200,
        )

        devices = await api_client.get_devices()

    # API flattens the grouped response and enriches devices
    assert len(devices) == 1
    assert devices[0]["dev_id"] == "mock_device_id_abcdef123"
    assert devices[0]["name"] == "Test Heater"
    assert devices[0]["group_id"] == "mock_group_id_123456789abc"
    assert devices[0]["group_name"] == "Test Home"


async def test_get_devices_unauthenticated(hass, api_client):
    """Test device retrieval without authentication."""
    with aioresponses() as mock_aiohttp:
        mock_aiohttp.get(
            f"{API_BASE_URL}{API_DEVICES_ENDPOINT}",
            status=401,
        )

        with pytest.raises(ElnurGabarronAPIError):
            await api_client.get_devices()


async def test_get_devices_network_error(hass, api_client):
    """Test device retrieval with network error."""
    api_client._access_token = "test_token"

    with aioresponses() as mock_aiohttp:
        mock_aiohttp.get(
            f"{API_BASE_URL}{API_DEVICES_ENDPOINT}",
            exception=ClientError("Network error"),
        )

        with pytest.raises(ElnurGabarronAPIError):
            await api_client.get_devices()


async def test_token_expiration_check(hass, api_client):
    """Test token expiration logic."""
    from datetime import datetime, timedelta

    # Set token as expired
    api_client._access_token = "old_token"
    api_client._token_expires_at = datetime.now() - timedelta(seconds=60)

    assert api_client._access_token is not None
    # Token is expired, should need refresh
    assert api_client._token_expires_at < datetime.now()
