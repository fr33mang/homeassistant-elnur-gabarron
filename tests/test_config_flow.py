from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.elnur_gabarron.api import ElnurGabarronAPIError
from custom_components.elnur_gabarron.const import CONF_SERIAL_ID, DEFAULT_SERIAL_ID, DOMAIN


async def test_form_valid_input(hass, mock_setup_entry):
    """Test we get the form and can create an entry with valid input."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {}
    assert result["step_id"] == "user"

    with patch("custom_components.elnur_gabarron.config_flow.ElnurGabarronAPI") as mock_api:
        mock_api.return_value.authenticate = AsyncMock(return_value=True)

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "testpass123",
                CONF_SERIAL_ID: "7",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == "Elnur Gabarron Heaters"
    assert result2["data"] == {
        CONF_USERNAME: "test@example.com",
        CONF_PASSWORD: "testpass123",
        CONF_SERIAL_ID: "7",
    }
    assert len(mock_setup_entry.mock_calls) == 1


async def test_form_invalid_auth(hass, mock_setup_entry):
    """Test we handle invalid auth."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    with patch("custom_components.elnur_gabarron.config_flow.ElnurGabarronAPI") as mock_api:
        mock_api.return_value.authenticate = AsyncMock(side_effect=ElnurGabarronAPIError("Invalid credentials"))

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "wrongpass",
                CONF_SERIAL_ID: "7",
            },
        )

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_form_cannot_connect(hass, mock_setup_entry):
    """Test we handle cannot connect error."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    with patch("custom_components.elnur_gabarron.config_flow.ElnurGabarronAPI") as mock_api:
        # API returns False (authentication failed but not exception)
        mock_api.return_value.authenticate = AsyncMock(side_effect=ElnurGabarronAPIError("Connection failed"))

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "testpass123",
                CONF_SERIAL_ID: "7",
            },
        )

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_form_already_configured(hass, mock_setup_entry):
    """Test we handle duplicate entries."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpass123",
            CONF_SERIAL_ID: "7",
        },
        unique_id="test@example.com::7",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    with patch("custom_components.elnur_gabarron.config_flow.ElnurGabarronAPI") as mock_api:
        mock_api.return_value.authenticate = AsyncMock(return_value=True)

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "testpass123",
                CONF_SERIAL_ID: "7",
            },
        )

    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


async def test_form_unknown_error(hass, mock_setup_entry):
    """Test we handle unknown errors."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    with patch("custom_components.elnur_gabarron.config_flow.ElnurGabarronAPI") as mock_api:
        mock_api.return_value.authenticate = AsyncMock(side_effect=Exception("Unexpected error"))

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "testpass123",
                CONF_SERIAL_ID: "7",
            },
        )

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "unknown"}


async def test_form_default_serial_id(hass, mock_setup_entry):
    """Test form uses default serial_id when not provided."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    with patch("custom_components.elnur_gabarron.config_flow.ElnurGabarronAPI") as mock_api:
        mock_api.return_value.authenticate = AsyncMock(return_value=True)

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "testpass123",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["data"][CONF_SERIAL_ID] == DEFAULT_SERIAL_ID
