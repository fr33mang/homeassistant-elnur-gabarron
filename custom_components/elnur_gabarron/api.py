"""API Client for Elnur Gabarron heaters."""

import base64
import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from .const import (
    API_BASE_URL,
    API_DEVICE_CONTROL_ENDPOINT,
    API_DEVICES_ENDPOINT,
    API_TOKEN_ENDPOINT,
    CLIENT_ID,
    CLIENT_SECRET,
)

_LOGGER = logging.getLogger(__name__)


class ElnurGabarronAPIError(Exception):
    """Exception for API errors."""


class ElnurGabarronAPI:
    """API client for Elnur Gabarron heaters."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        serial_id: str = "7",
    ):
        """Initialize the API client."""
        self._session = session
        self._username = username
        self._password = password
        self._serial_id = serial_id
        self._access_token = None
        self._refresh_token = None
        self._token_expires_at = None

    async def authenticate(self) -> bool:
        """Authenticate with the API using OAuth2 password grant."""
        try:
            url = f"{API_BASE_URL}{API_TOKEN_ENDPOINT}"

            # Create Basic Auth header with client credentials
            credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
            basic_auth = base64.b64encode(credentials.encode()).decode()

            headers = {
                "accept": "application/json, text/plain, */*",
                "authorization": f"Basic {basic_auth}",
                "content-type": "application/x-www-form-urlencoded",
                "x-referer": "https://remotecontrol.elnur.es",
                "x-serialid": self._serial_id,
            }

            # OAuth2 password grant
            data = {
                "grant_type": "password",
                "username": self._username,
                "password": self._password,
            }

            async with self._session.post(url, data=data, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    self._access_token = result.get("access_token")
                    self._refresh_token = result.get("refresh_token")

                    # Calculate token expiration (usually 3600 seconds)
                    expires_in = result.get("expires_in", 3600)
                    self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)

                    _LOGGER.debug("Successfully authenticated with Elnur Gabarron API")
                    return True
                else:
                    error_text = await response.text()
                    _LOGGER.error("Authentication failed: %s - %s", response.status, error_text)
                    return False
        except Exception as err:
            _LOGGER.error("Authentication error: %s", err)
            raise ElnurGabarronAPIError(f"Authentication failed: {err}")

    async def refresh_access_token(self) -> bool:
        """Refresh the access token using the refresh token."""
        if not self._refresh_token:
            _LOGGER.warning("No refresh token available, re-authenticating")
            return await self.authenticate()

        try:
            url = f"{API_BASE_URL}{API_TOKEN_ENDPOINT}"

            credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
            basic_auth = base64.b64encode(credentials.encode()).decode()

            headers = {
                "accept": "application/json, text/plain, */*",
                "authorization": f"Basic {basic_auth}",
                "content-type": "application/x-www-form-urlencoded",
                "x-referer": "https://remotecontrol.elnur.es",
                "x-serialid": self._serial_id,
            }

            data = {
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            }

            async with self._session.post(url, data=data, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    self._access_token = result.get("access_token")
                    self._refresh_token = result.get("refresh_token")

                    expires_in = result.get("expires_in", 3600)
                    self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)

                    _LOGGER.debug("Successfully refreshed access token")
                    return True
                else:
                    _LOGGER.error("Token refresh failed: %s", response.status)
                    # If refresh fails, try full authentication
                    return await self.authenticate()
        except Exception as err:
            _LOGGER.error("Token refresh error: %s", err)
            return await self.authenticate()

    async def _ensure_authenticated(self) -> bool:
        """Ensure we have a valid access token."""
        if not self._access_token:
            return await self.authenticate()

        # Check if token is expired or about to expire (within 5 minutes)
        if self._token_expires_at and datetime.now() >= self._token_expires_at - timedelta(minutes=5):
            return await self.refresh_access_token()

        return True

    async def async_get_access_token(self) -> str:
        """Return a valid access token (refreshing/re-authing if needed)."""
        ok = await self._ensure_authenticated()
        if not ok or not self._access_token:
            raise ElnurGabarronAPIError("No access token available")
        return self._access_token

    async def get_devices(self) -> list[dict[str, Any]]:
        """Get list of all devices from grouped_devs endpoint."""
        await self._ensure_authenticated()

        try:
            url = f"{API_BASE_URL}{API_DEVICES_ENDPOINT}"

            async with self._session.get(url, headers=self._get_headers()) as response:
                if response.status == 200:
                    groups = await response.json()
                    _LOGGER.debug(
                        "Fetched %s group(s) from API",
                        len(groups) if isinstance(groups, list) else 0,
                    )

                    # API returns groups with devices inside
                    # Flatten the structure to get all devices
                    devices = []
                    if isinstance(groups, list):
                        for group in groups:
                            group_id = group.get("id")
                            group_name = group.get("name")
                            devs = group.get("devs", [])
                            _LOGGER.debug("Group '%s' has %s device(s)", group_name, len(devs))

                            for dev in devs:
                                # Enrich device with group info
                                dev["group_id"] = group_id
                                dev["group_name"] = group_name
                                devices.append(dev)
                                _LOGGER.debug(
                                    "Device: %s (ID: %s)",
                                    dev.get("name"),
                                    dev.get("dev_id"),
                                )

                    _LOGGER.debug(
                        "Total: %s device(s) across %s group(s)",
                        len(devices),
                        len(groups) if isinstance(groups, list) else 0,
                    )
                    return devices
                else:
                    error_text = await response.text()
                    _LOGGER.error("Failed to get devices: %s - %s", response.status, error_text)
                    return []
        except Exception as err:
            _LOGGER.error("Error getting devices: %s", err)
            raise ElnurGabarronAPIError(f"Failed to get devices: {err}")

    async def get_device_status(self, device_id: str, zone_id: int = 3) -> dict[str, Any]:
        """Get status of a specific device zone."""
        await self._ensure_authenticated()

        try:
            url = f"{API_BASE_URL}{API_DEVICE_CONTROL_ENDPOINT.format(device_id=device_id, zone_id=zone_id)}"

            async with self._session.get(url, headers=self._get_headers()) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    _LOGGER.error(
                        "Failed to get device status: %s - %s",
                        response.status,
                        error_text,
                    )
                    return {}
        except Exception as err:
            _LOGGER.error("Error getting device status: %s", err)
            raise ElnurGabarronAPIError(f"Failed to get device status: {err}")

    async def set_temperature(
        self,
        device_id: str,
        temperature: float,
        zone_id: int = 3,
        mode: str | None = None,
    ) -> bool:
        """Set target temperature for a device zone.

        Args:
            device_id: Device ID
            temperature: Target temperature in Celsius
            zone_id: Zone ID (2 or 3)
            mode: Optional mode to set with temperature ("modified_auto" for manual control)
        """
        await self._ensure_authenticated()

        try:
            url = f"{API_BASE_URL}{API_DEVICE_CONTROL_ENDPOINT.format(device_id=device_id, zone_id=zone_id)}"
            # Control command format - temperature and optional mode
            data = {
                "stemp": str(temperature),
                "units": "C",
            }

            # Include mode if specified (e.g., "modified_auto" for manual control)
            if mode:
                data["mode"] = mode

            async with self._session.post(url, json=data, headers=self._get_headers()) as response:
                if response.status in [200, 201, 204]:
                    mode_msg = f" with mode '{mode}'" if mode else ""
                    _LOGGER.info(
                        "Set temperature to %s°C%s for device %s zone %s",
                        temperature,
                        mode_msg,
                        device_id,
                        zone_id,
                    )
                    return True
                else:
                    error_text = await response.text()
                    _LOGGER.error(
                        "Failed to set temperature: %s - %s",
                        response.status,
                        error_text,
                    )
                    return False
        except Exception as err:
            _LOGGER.error("Error setting temperature: %s", err)
            raise ElnurGabarronAPIError(f"Failed to set temperature: {err}")

    async def set_mode(self, device_id: str, mode: str, zone_id: int = 3) -> bool:
        """Set device zone mode.

        Args:
            device_id: Device ID
            mode: Mode to set ("off", "auto", "modified_auto")
            zone_id: Zone ID (2 or 3)
        """
        await self._ensure_authenticated()

        try:
            url = f"{API_BASE_URL}{API_DEVICE_CONTROL_ENDPOINT.format(device_id=device_id, zone_id=zone_id)}"
            # Control command format from HAR file
            # Modes: "off", "auto" (follows schedule), "modified_auto" (manual control)
            data = {
                "mode": mode,
            }

            async with self._session.post(url, json=data, headers=self._get_headers()) as response:
                if response.status in [200, 201, 204]:
                    _LOGGER.info(
                        "Set mode to '%s' for device %s zone %s",
                        mode,
                        device_id,
                        zone_id,
                    )
                    return True
                else:
                    error_text = await response.text()
                    _LOGGER.error("Failed to set mode: %s - %s", response.status, error_text)
                    return False
        except Exception as err:
            _LOGGER.error("Error setting mode: %s", err)
            raise ElnurGabarronAPIError(f"Failed to set mode: {err}")

    async def set_control(self, device_id: str, control_data: dict[str, Any], zone_id: int = 3) -> bool:
        """Send control command to a device zone with custom data."""
        await self._ensure_authenticated()

        try:
            url = f"{API_BASE_URL}{API_DEVICE_CONTROL_ENDPOINT.format(device_id=device_id, zone_id=zone_id)}"

            async with self._session.post(url, json=control_data, headers=self._get_headers()) as response:
                if response.status in [200, 201, 204]:
                    _LOGGER.info(
                        "Sent control command to device %s zone %s: %s",
                        device_id,
                        zone_id,
                        control_data,
                    )
                    return True
                else:
                    error_text = await response.text()
                    _LOGGER.error(
                        "Failed to send control command: %s - %s",
                        response.status,
                        error_text,
                    )
                    return False
        except Exception as err:
            _LOGGER.error("Error sending control command: %s", err)
            raise ElnurGabarronAPIError(f"Failed to send control command: {err}")

    def _get_headers(self) -> dict[str, str]:
        """Return headers for API requests."""

        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "x-referer": "https://remotecontrol.elnur.es",
            "x-serialid": self._serial_id,
        }

        # Add Authorization header if we have a token
        if self._access_token:
            headers["authorization"] = f"Bearer {self._access_token}"

        return headers
