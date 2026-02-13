import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ElnurGabarronAPI, ElnurGabarronAPIError
from .const import CONF_PASSWORD, CONF_SERIAL_ID, CONF_USERNAME, DEFAULT_SERIAL_ID, DOMAIN
from .socketio_coordinator import ElnurSocketIOCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CLIMATE, Platform.NUMBER, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Elnur Gabarron from a config entry."""
    _LOGGER.debug("Starting Elnur Gabarron integration setup")
    hass.data.setdefault(DOMAIN, {})

    # Get configuration
    username = entry.data.get(CONF_USERNAME, "")
    password = entry.data.get(CONF_PASSWORD, "")
    serial_id = entry.data.get(CONF_SERIAL_ID, DEFAULT_SERIAL_ID)
    _LOGGER.debug("Config loaded (username redacted), serial_id=%s", serial_id)

    # Create API client
    session = async_get_clientsession(hass)
    api = ElnurGabarronAPI(
        session=session,
        username=username,
        password=password,
        serial_id=serial_id,
    )

    # Authenticate
    try:
        _LOGGER.debug("Attempting authentication...")
        authenticated = await api.authenticate()
        if not authenticated:
            raise ConfigEntryNotReady("Failed to authenticate with Elnur Gabarron API")
        _LOGGER.debug("Authentication successful")
    except ElnurGabarronAPIError as err:
        raise ConfigEntryNotReady("Authentication error") from err
    except Exception as err:
        raise ConfigEntryNotReady("Unexpected authentication error") from err

    # Create Socket.IO coordinator for real-time updates
    coordinator = ElnurSocketIOCoordinator(
        hass,
        api=api,
        session=session,
    )

    # Fetch initial data
    _LOGGER.debug("Fetching initial data...")
    await coordinator.async_config_entry_first_refresh()
    _LOGGER.debug("Initial data fetched: %s zones", len(coordinator.data))

    # Update config entry title to show the actual home/group name
    if coordinator.group_name and entry.title != coordinator.group_name:
        hass.config_entries.async_update_entry(entry, title=coordinator.group_name)
        _LOGGER.debug("Updated integration title to: %s", coordinator.group_name)

    # Store coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward entry setup to platforms
    _LOGGER.debug("Setting up platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Start Socket.IO listener AFTER platforms are set up (non-blocking)
    # This will update zone names dynamically when dev_data is received
    _LOGGER.debug("Starting Socket.IO real-time listener...")
    await coordinator.async_start()

    _LOGGER.debug("Elnur Gabarron integration setup complete")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Stop Socket.IO listener
    coordinator: ElnurSocketIOCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
