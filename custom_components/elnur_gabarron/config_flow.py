"""Config flow for Elnur Gabarron integration."""
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ElnurGabarronAPI, ElnurGabarronAPIError
from .const import DOMAIN, CONF_SERIAL_ID, DEFAULT_SERIAL_ID

_LOGGER = logging.getLogger(__name__)


class ElnurGabarronConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Elnur Gabarron."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Prevent duplicates (stable, non-secret identifier)
            await self.async_set_unique_id(
                f"{user_input[CONF_USERNAME]}::{user_input.get(CONF_SERIAL_ID, DEFAULT_SERIAL_ID)}"
            )
            self._abort_if_unique_id_configured()

            # Validate the input
            try:
                await self._test_connection(user_input)
            except ElnurGabarronAPIError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title="Elnur Gabarron Heaters",
                    data=user_input,
                )

        # Show form
        data_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_SERIAL_ID, default=DEFAULT_SERIAL_ID): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def _test_connection(self, user_input: dict[str, Any]) -> bool:
        """Test if we can authenticate with the API."""
        session = async_get_clientsession(self.hass)
        api = ElnurGabarronAPI(
            session=session,
            username=user_input[CONF_USERNAME],
            password=user_input[CONF_PASSWORD],
            serial_id=user_input.get(CONF_SERIAL_ID, DEFAULT_SERIAL_ID),
        )

        return await api.authenticate()

