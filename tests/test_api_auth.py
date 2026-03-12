import asyncio
import base64
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.elnur_gabarron.api import ElnurGabarronAPI, ElnurGabarronAPIError
from custom_components.elnur_gabarron.const import CLIENT_ID, CLIENT_SECRET

EXPECTED_BASIC_AUTH = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()


# ---------------------------------------------------------------------------
# authenticate() -- password grant
# ---------------------------------------------------------------------------


async def test_authenticate_success(api_client: ElnurGabarronAPI, token_url: str, mock_auth_success_response: dict):
    with aioresponses() as mock:
        mock.post(token_url, payload=mock_auth_success_response, status=200)

        result = await api_client.authenticate()

    assert result is True
    assert api_client._access_token == "mock_access_token_abc123"
    assert api_client._refresh_token == "mock_refresh_token_xyz789"
    assert api_client._token_expires_at is not None
    # Token should expire roughly 1 hour from now
    assert api_client._token_expires_at > datetime.now(tz=UTC)


async def test_authenticate_sends_correct_headers(
    api_client: ElnurGabarronAPI, token_url: str, mock_auth_success_response: dict
):
    with aioresponses() as mock:
        mock.post(token_url, payload=mock_auth_success_response, status=200)

        await api_client.authenticate()

        call = mock.requests[("POST", aiohttp.client.URL(token_url))][0]
        sent_headers = call.kwargs.get("headers", {})

    assert sent_headers.get("authorization") == f"Basic {EXPECTED_BASIC_AUTH}"
    assert sent_headers.get("x-referer") == "https://remotecontrol.elnur.es"
    assert sent_headers.get("x-serialid") == "7"
    assert sent_headers.get("content-type") == "application/x-www-form-urlencoded"


async def test_authenticate_sends_password_grant_body(
    api_client: ElnurGabarronAPI, token_url: str, mock_auth_success_response: dict
):
    with aioresponses() as mock:
        mock.post(token_url, payload=mock_auth_success_response, status=200)

        await api_client.authenticate()

        call = mock.requests[("POST", aiohttp.client.URL(token_url))][0]
        sent_data = call.kwargs.get("data", {})

    assert sent_data.get("grant_type") == "password"
    assert sent_data.get("username") == "test@example.com"
    assert sent_data.get("password") == "testpass123"


async def test_authenticate_failure_401(api_client: ElnurGabarronAPI, token_url: str):
    with aioresponses() as mock:
        mock.post(token_url, status=401, body="Unauthorized")

        result = await api_client.authenticate()

    assert result is False
    assert api_client._access_token is None
    assert api_client._refresh_token is None
    assert api_client._token_expires_at is None


async def test_authenticate_failure_500(api_client: ElnurGabarronAPI, token_url: str):
    with aioresponses() as mock:
        mock.post(token_url, status=500, body="Internal Server Error")

        result = await api_client.authenticate()

    assert result is False
    assert api_client._access_token is None


async def test_authenticate_network_error(api_client: ElnurGabarronAPI, token_url: str):
    with aioresponses() as mock:
        mock.post(token_url, exception=aiohttp.ClientError("connection refused"))

        with pytest.raises(ElnurGabarronAPIError, match="Authentication failed"):
            await api_client.authenticate()


async def test_authenticate_timeout(api_client: ElnurGabarronAPI, token_url: str):
    with aioresponses() as mock:
        mock.post(token_url, exception=asyncio.TimeoutError())

        with pytest.raises(ElnurGabarronAPIError, match="Authentication failed"):
            await api_client.authenticate()


# ---------------------------------------------------------------------------
# refresh_access_token()
# ---------------------------------------------------------------------------


async def test_refresh_success(api_client: ElnurGabarronAPI, token_url: str, mock_auth_success_response: dict):
    api_client._refresh_token = "old_refresh_token"

    refreshed_response = {
        "access_token": "new_access_token",
        "refresh_token": "new_refresh_token",
        "token_type": "bearer",
        "expires_in": 3600,
    }

    with aioresponses() as mock:
        mock.post(token_url, payload=refreshed_response, status=200)

        result = await api_client.refresh_access_token()

    assert result is True
    assert api_client._access_token == "new_access_token"
    assert api_client._refresh_token == "new_refresh_token"
    assert api_client._token_expires_at is not None


async def test_refresh_sends_refresh_grant_body(
    api_client: ElnurGabarronAPI, token_url: str, mock_auth_success_response: dict
):
    api_client._refresh_token = "old_refresh_token"

    with aioresponses() as mock:
        mock.post(token_url, payload=mock_auth_success_response, status=200)

        await api_client.refresh_access_token()

        call = mock.requests[("POST", aiohttp.client.URL(token_url))][0]
        sent_data = call.kwargs.get("data", {})

    assert sent_data.get("grant_type") == "refresh_token"
    assert sent_data.get("refresh_token") == "old_refresh_token"


async def test_refresh_failure_falls_back_to_authenticate(
    api_client: ElnurGabarronAPI, token_url: str, mock_auth_success_response: dict
):
    api_client._refresh_token = "stale_refresh_token"

    with aioresponses() as mock:
        # First call: refresh fails
        mock.post(token_url, status=401, body="Unauthorized")
        # Second call: fallback authenticate succeeds
        mock.post(token_url, payload=mock_auth_success_response, status=200)

        result = await api_client.refresh_access_token()

    assert result is True
    assert api_client._access_token == "mock_access_token_abc123"


async def test_refresh_network_error_falls_back(
    api_client: ElnurGabarronAPI, token_url: str, mock_auth_success_response: dict
):
    api_client._refresh_token = "some_refresh_token"

    with aioresponses() as mock:
        mock.post(token_url, exception=aiohttp.ClientError("network error"))
        mock.post(token_url, payload=mock_auth_success_response, status=200)

        result = await api_client.refresh_access_token()

    assert result is True
    assert api_client._access_token == "mock_access_token_abc123"


async def test_refresh_no_refresh_token_falls_back_to_authenticate(
    api_client: ElnurGabarronAPI, token_url: str, mock_auth_success_response: dict
):
    assert api_client._refresh_token is None

    with aioresponses() as mock:
        mock.post(token_url, payload=mock_auth_success_response, status=200)

        result = await api_client.refresh_access_token()

    assert result is True
    assert api_client._access_token == "mock_access_token_abc123"


# ---------------------------------------------------------------------------
# _ensure_authenticated() -- token lifecycle
# ---------------------------------------------------------------------------


async def test_ensure_authenticated_no_token_calls_authenticate(api_client: ElnurGabarronAPI):
    assert api_client._access_token is None

    with patch.object(api_client, "authenticate", new_callable=AsyncMock, return_value=True) as mock_auth:
        result = await api_client._ensure_authenticated()

    mock_auth.assert_called_once()
    assert result is True


async def test_ensure_authenticated_valid_token_skips_http(api_client: ElnurGabarronAPI):
    api_client._access_token = "valid_token"
    api_client._token_expires_at = datetime.now(tz=UTC) + timedelta(hours=1)

    with patch.object(api_client, "authenticate", new_callable=AsyncMock) as mock_auth:
        with patch.object(api_client, "refresh_access_token", new_callable=AsyncMock) as mock_refresh:
            result = await api_client._ensure_authenticated()

    mock_auth.assert_not_called()
    mock_refresh.assert_not_called()
    assert result is True


async def test_ensure_authenticated_expiring_token_calls_refresh(api_client: ElnurGabarronAPI):
    api_client._access_token = "expiring_token"
    # expires in 2 minutes -- within the 5-minute refresh window
    api_client._token_expires_at = datetime.now(tz=UTC) + timedelta(minutes=2)

    with patch.object(api_client, "refresh_access_token", new_callable=AsyncMock, return_value=True) as mock_refresh:
        result = await api_client._ensure_authenticated()

    mock_refresh.assert_called_once()
    assert result is True


# ---------------------------------------------------------------------------
# async_get_access_token()
# ---------------------------------------------------------------------------


async def test_get_access_token_success(api_client: ElnurGabarronAPI):
    api_client._access_token = "valid_token"
    api_client._token_expires_at = datetime.now(tz=UTC) + timedelta(hours=1)

    token = await api_client.async_get_access_token()

    assert token == "valid_token"


async def test_get_access_token_no_auth_raises(api_client: ElnurGabarronAPI, token_url: str):
    with aioresponses() as mock:
        mock.post(token_url, status=401, body="Unauthorized")

        with pytest.raises(ElnurGabarronAPIError, match="No access token available"):
            await api_client.async_get_access_token()
