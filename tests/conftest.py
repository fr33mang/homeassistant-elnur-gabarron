import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture

from custom_components.elnur_gabarron.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests."""
    yield


@pytest.fixture
def mock_setup_entry():
    """Mock setup entry to prevent actual platform loading during flow tests."""
    with patch(
        "custom_components.elnur_gabarron.async_setup_entry",
        return_value=True,
    ) as mock_setup:
        yield mock_setup


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test@example.com",
            "password": "testpass123",
            "serial_id": "7",
        },
        unique_id="test@example.com::7",
    )


def load_json_fixture(filename):
    """Load a JSON fixture."""
    return json.loads(load_fixture(filename))
