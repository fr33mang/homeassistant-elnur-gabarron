import asyncio

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.elnur_gabarron.api import ElnurGabarronAPI
from custom_components.elnur_gabarron.const import API_BASE_URL, API_TOKEN_ENDPOINT

TEST_USERNAME = "test@example.com"
TEST_PASSWORD = "testpass123"
TEST_SERIAL_ID = "7"

TOKEN_URL = f"{API_BASE_URL}{API_TOKEN_ENDPOINT}"


@pytest.fixture
def token_url() -> str:
    return TOKEN_URL


@pytest.fixture
def mock_auth_success_response() -> dict:
    return {
        "access_token": "mock_access_token_abc123",
        "refresh_token": "mock_refresh_token_xyz789",
        "token_type": "bearer",
        "expires_in": 3600,
    }


@pytest.fixture
async def mock_api_session(aioclient_mock: AiohttpClientMocker):
    # Home Assistant's own HTTP mock, rather than aioresponses: it ships with
    # pytest-homeassistant-custom-component, so it tracks the aiohttp version
    # Home Assistant pins instead of breaking whenever that moves.
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield session
    await session.close()


@pytest.fixture
def api_client(mock_api_session: aiohttp.ClientSession) -> ElnurGabarronAPI:
    return ElnurGabarronAPI(
        session=mock_api_session,
        username=TEST_USERNAME,
        password=TEST_PASSWORD,
        serial_id=TEST_SERIAL_ID,
    )
