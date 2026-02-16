"""Socket.IO coordinator for Elnur Gabarron real-time updates."""

import asyncio
import json
import logging
from typing import Any
from urllib.parse import urlencode

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ElnurGabarronAPI
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Socket.IO configuration
SOCKETIO_BASE_URL = "https://api-elnur.helki.com"
SOCKETIO_PATH = "/socket.io/"
SOCKETIO_NAMESPACE = "/api/v2/socket_io"


def parse_engineio_payload(data: bytes) -> list:
    """Parse Engine.IO v3 binary framed payload."""
    messages = []
    i = 0
    while i < len(data):
        if data[i] == 0:  # Binary frame marker
            # Find the 0xff delimiter
            j = i + 1
            while j < len(data) and data[j] != 0xFF:
                j += 1
            if j < len(data):
                i = j + 1
                # Find the next 0x00 or end of data
                msg_end = i
                while msg_end < len(data) and data[msg_end] != 0:
                    msg_end += 1
                msg = data[i:msg_end].decode("utf-8", errors="ignore")
                messages.append(msg)
                i = msg_end
            else:
                break
        else:
            # Plain text frame
            msg_end = i
            while msg_end < len(data) and data[msg_end] not in (0, 0x1E):
                msg_end += 1
            if msg_end > i:
                msg = data[i:msg_end].decode("utf-8", errors="ignore")
                messages.append(msg)
            i = msg_end + 1 if msg_end < len(data) else msg_end
    return messages


class ElnurSocketIOCoordinator(DataUpdateCoordinator):
    """Coordinator for Socket.IO real-time updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: ElnurGabarronAPI,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the Socket.IO coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_socketio",
            update_interval=None,  # Push-based updates, no polling
        )

        self.api = api
        self.session = session
        self._sid: str | None = None
        self._device_id: str | None = None
        self._device_name: str | None = None
        self._group_id: str | None = None
        self._group_name: str | None = None
        self._connected = False
        self._listener_task: asyncio.Task | None = None
        self._reconnect_count = 0
        self._last_update_time: float = 0
        self._last_successful_connect_time: float = 0
        self._consecutive_connection_failures = 0

    @property
    def group_name(self) -> str | None:
        """Return the group/home name."""
        return self._group_name

    async def async_start(self) -> None:
        """Start the Socket.IO listener."""
        if self._listener_task is None or self._listener_task.done():
            _LOGGER.debug("Starting Socket.IO listener")
            self._listener_task = asyncio.create_task(self._socketio_listener())

    async def async_stop(self) -> None:
        """Stop the Socket.IO listener."""
        _LOGGER.debug("Stopping Socket.IO listener")
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        self._connected = False

    async def _fetch_initial_data(self) -> dict[str, Any]:
        """Fetch initial device data via Socket.IO dev_data (synchronously)."""
        try:
            devices = await self.api.get_devices()
            if not devices:
                raise UpdateFailed("No devices found")

            # Get first device info (including group information)
            first_device = devices[0]
            self._device_id = first_device.get("dev_id")
            self._device_name = first_device.get("name", "Device")
            self._group_id = first_device.get("group_id")
            self._group_name = first_device.get("group_name", "Home")

            _LOGGER.debug("Device: %s (ID: %s)", self._device_name, self._device_id)
            _LOGGER.debug("Group: %s (ID: %s)", self._group_name, self._group_id)

            # Connect to Socket.IO and get dev_data SYNCHRONOUSLY
            _LOGGER.debug("Connecting to Socket.IO to fetch zone data")
            connected = await self._connect_socketio()

            if not connected:
                _LOGGER.warning("Socket.IO connection failed during startup; using fallback zone discovery")
                # Fallback to hardcoded zones if Socket.IO fails
                device_data = {}
                for zone_id in [2, 3]:
                    try:
                        status = await self.api.get_device_status(self._device_id, zone_id)
                        unique_key = f"{self._device_id}_zone{zone_id}"
                        device_data[unique_key] = {
                            "zone_id": zone_id,
                            "status": status,
                            "device_id": self._device_id,
                            "device_name": self._device_name,
                            "group_id": self._group_id,
                            "group_name": self._group_name,
                        }
                    except Exception:
                        pass
                return device_data

            # Request dev_data
            token = await self.api.async_get_access_token()
            params = {
                "token": token,
                "EIO": "3",
                "transport": "polling",
                "sid": self._sid,
                "dev_id": self._device_id,
            }
            url = f"{SOCKETIO_BASE_URL}{SOCKETIO_PATH}?{urlencode(params)}"

            dev_data_event = f'42{SOCKETIO_NAMESPACE},["dev_data"]'
            dev_data_packet = f"{len(dev_data_event)}:{dev_data_event}"

            await self.session.post(url, data=dev_data_packet)
            _LOGGER.debug("Requested dev_data from Socket.IO")

            # Poll for dev_data response (with timeout)
            device_data = {}
            for attempt in range(20):  # Wait up to 10 seconds
                await asyncio.sleep(0.5)

                try:
                    async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            messages = parse_engineio_payload(data)

                            for msg in messages:
                                if msg.startswith("42") and "dev_data" in msg:
                                    # Parse dev_data event
                                    event_data = msg[2:]
                                    if event_data.startswith(SOCKETIO_NAMESPACE):
                                        event_data = event_data[len(SOCKETIO_NAMESPACE) + 1 :]

                                    data_obj = json.loads(event_data)
                                    if isinstance(data_obj, list) and data_obj[0] == "dev_data":
                                        payload = data_obj[1]
                                        nodes = payload.get("nodes", [])

                                        _LOGGER.debug(
                                            "Received dev_data with %s zone(s)",
                                            len(nodes),
                                        )

                                        # Build device data from nodes
                                        for node in nodes:
                                            zone_id = node.get("addr")
                                            zone_name = node.get("name", f"Zone {zone_id}")

                                            unique_key = f"{self._device_id}_zone{zone_id}"
                                            device_data[unique_key] = {
                                                "zone_id": zone_id,
                                                "device_id": self._device_id,
                                                "device_name": self._device_name,
                                                "group_id": self._group_id,
                                                "group_name": self._group_name,
                                                "name": zone_name,
                                                "status": node.get("status", {}),
                                                "setup": node.get("setup", {}),
                                                "version": node.get("version", {}),
                                            }
                                            _LOGGER.debug("Zone %s: %s", zone_id, zone_name)

                                        return device_data
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    _LOGGER.debug("Poll error: %s", e)
                    continue

            _LOGGER.warning("dev_data not received within timeout; using fallback")
            # Fallback if dev_data not received
            for zone_id in [2, 3]:
                try:
                    status = await self.api.get_device_status(self._device_id, zone_id)
                    unique_key = f"{self._device_id}_zone{zone_id}"
                    device_data[unique_key] = {
                        "zone_id": zone_id,
                        "status": status,
                        "device_id": self._device_id,
                        "device_name": self._device_name,
                        "group_id": self._group_id,
                        "group_name": self._group_name,
                    }
                except Exception:
                    pass

            return device_data

        except Exception as err:
            _LOGGER.error("Failed to fetch initial data", exc_info=True)
            raise UpdateFailed("Failed to fetch initial data") from err

    async def _async_update_data(self) -> dict[str, Any]:
        """Initial data fetch (called once at startup)."""
        return await self._fetch_initial_data()

    async def _connect_socketio(self) -> bool:
        """Connect to Socket.IO server."""
        try:
            token = await self.api.async_get_access_token()
            params = {
                "token": token,
                "EIO": "3",
                "transport": "polling",
            }

            if self._device_id:
                params["dev_id"] = self._device_id

            url = f"{SOCKETIO_BASE_URL}{SOCKETIO_PATH}?{urlencode(params)}"

            # Step 1: Handshake
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    _LOGGER.error("Socket.IO handshake failed: HTTP %s", resp.status)
                    return False

                data = await resp.read()
                messages = parse_engineio_payload(data)

                if not messages or not messages[0].startswith("0"):
                    _LOGGER.error("Invalid Socket.IO handshake response")
                    return False

                handshake = json.loads(messages[0][1:])
                self._sid = handshake.get("sid")
                _LOGGER.debug("Socket.IO connected, session ID: %s", self._sid)

            # Step 2: Join namespace
            params["sid"] = self._sid
            namespace_conn = f"40{SOCKETIO_NAMESPACE}?token={token}&dev_id={self._device_id}"
            namespace_packet = f"{len(namespace_conn)}:{namespace_conn}"

            async with self.session.post(
                f"{SOCKETIO_BASE_URL}{SOCKETIO_PATH}?{urlencode(params)}",
                data=namespace_packet,
            ) as resp:
                if resp.status == 200:
                    _LOGGER.debug("Joined Socket.IO namespace: %s", SOCKETIO_NAMESPACE)
                else:
                    _LOGGER.warning("Namespace join: HTTP %s", resp.status)

            # Step 3: Request device data
            dev_data_event = f'42{SOCKETIO_NAMESPACE},["dev_data"]'
            dev_data_packet = f"{len(dev_data_event)}:{dev_data_event}"

            await self.session.post(
                f"{SOCKETIO_BASE_URL}{SOCKETIO_PATH}?{urlencode(params)}",
                data=dev_data_packet,
            )

            self._connected = True
            return True

        except Exception as err:
            _LOGGER.error("Socket.IO connection failed: %s", err)
            return False

    async def _socketio_listener(self) -> None:
        """Main Socket.IO listener loop with auto-reconnection."""
        _LOGGER.debug("Socket.IO listener started")
        reconnect_delay = 5  # Start with 5 seconds

        while True:  # Infinite retry loop
            try:
                # Connect
                if self._reconnect_count > 0:
                    _LOGGER.info(
                        "Reconnecting to Socket.IO (attempt %s)...",
                        self._reconnect_count,
                    )
                else:
                    _LOGGER.debug("Connecting to Socket.IO...")

                connected = await self._connect_socketio()
                if not connected:
                    self._reconnect_count += 1
                    self._consecutive_connection_failures += 1
                    _LOGGER.warning(
                        "Socket.IO connection failed (failure #%s), retrying in %ss",
                        self._consecutive_connection_failures,
                        reconnect_delay,
                    )

                    # If Socket.IO has been failing for too long, try fetching via REST API as fallback
                    if self._consecutive_connection_failures >= 10:  # ~10+ minutes of failures with backoff
                        _LOGGER.warning("Socket.IO repeatedly failing, attempting REST API data refresh...")
                        try:
                            fallback_data = await self._fetch_initial_data()
                            self.async_set_updated_data(fallback_data)
                            _LOGGER.info("Successfully refreshed data via REST API fallback")
                        except Exception as fallback_err:
                            _LOGGER.error("REST API fallback also failed: %s", fallback_err)

                    await asyncio.sleep(reconnect_delay)
                    # Exponential backoff, max 60s
                    reconnect_delay = min(reconnect_delay * 2, 60)
                    continue

                # Reset on successful connection
                self._reconnect_count = 0
                self._consecutive_connection_failures = 0
                reconnect_delay = 5
                last_activity = asyncio.get_event_loop().time()
                self._last_update_time = last_activity
                self._last_successful_connect_time = last_activity
                poll_count = 0

                token = await self.api.async_get_access_token()
                params = {
                    "token": token,
                    "EIO": "3",
                    "transport": "polling",
                    "sid": self._sid,
                }
                if self._device_id:
                    params["dev_id"] = self._device_id

                url = f"{SOCKETIO_BASE_URL}{SOCKETIO_PATH}?{urlencode(params)}"

                # Poll loop
                while self._connected:
                    try:
                        poll_count += 1
                        current_time = asyncio.get_event_loop().time()

                        # Watchdog: Check for stale connection (no real updates in 5 minutes)
                        time_since_update = current_time - self._last_update_time
                        if time_since_update > 300:  # 5 minutes
                            _LOGGER.warning(
                                "No updates received for %ss, forcing reconnect...",
                                int(time_since_update),
                            )
                            self._connected = False
                            break

                        # Check for idle session (40s without any activity)
                        elapsed = current_time - last_activity
                        if elapsed > 40:
                            _LOGGER.info("Session idle for 40s, reconnecting...")
                            self._connected = False
                            break

                        # Periodic keepalive dev_data request (every 30s)
                        if poll_count % 300 == 0:
                            _LOGGER.debug("Sending periodic dev_data keepalive...")
                            dev_data_event = f'42{SOCKETIO_NAMESPACE},["dev_data"]'
                            dev_data_packet = f"{len(dev_data_event)}:{dev_data_event}"
                            await self.session.post(url, data=dev_data_packet)

                        # Poll for messages
                        async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                            if resp.status == 200:
                                data = await resp.read()
                                messages = parse_engineio_payload(data)

                                for msg in messages:
                                    if not msg or msg == "6":  # Skip NOOP
                                        continue

                                    last_activity = current_time

                                    # Handle Engine.IO CLOSE
                                    if msg == "1":
                                        _LOGGER.debug("Server sent CLOSE, reconnecting...")
                                        self._connected = False
                                        break

                                    # Handle Engine.IO PING
                                    if msg == "2":
                                        await self.session.post(url, data="3")  # Send PONG
                                        _LOGGER.debug("Received PING, sent PONG")
                                        continue

                                    # Skip namespace connection acks
                                    if msg == "40" or msg.startswith("40/"):
                                        continue

                                    # Handle Socket.IO events (actual data updates)
                                    if msg.startswith("42"):
                                        self._last_update_time = current_time  # Real update received
                                        self._consecutive_connection_failures = (
                                            0  # Reset failure counter on successful data
                                        )
                                        await self._handle_socketio_event(msg)
                            elif resp.status >= 400:
                                _LOGGER.warning(
                                    "Socket.IO poll returned HTTP %s, reconnecting...",
                                    resp.status,
                                )
                                self._consecutive_connection_failures += 1
                                self._connected = False
                                break

                        await asyncio.sleep(0.1)

                    except asyncio.TimeoutError:
                        _LOGGER.debug("Socket.IO poll timeout, continuing...")
                        continue
                    except Exception as poll_err:
                        _LOGGER.error("Socket.IO poll error: %s", poll_err, exc_info=True)
                        self._connected = False
                        break

                # Connection ended, will reconnect
                self._connected = False
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                _LOGGER.debug("Socket.IO listener cancelled (integration unloading)")
                raise  # Re-raise to properly propagate cancellation
            except Exception as err:
                _LOGGER.error("Socket.IO listener error: %s", err, exc_info=True)
                self._reconnect_count += 1
                await asyncio.sleep(reconnect_delay)
                # Exponential backoff
                reconnect_delay = min(reconnect_delay * 2, 60)

        _LOGGER.debug("Socket.IO listener stopped")

    async def _handle_socketio_event(self, msg: str) -> None:
        """Handle Socket.IO event message."""
        try:
            # Extract event data
            event_data = msg[2:]
            if event_data.startswith(SOCKETIO_NAMESPACE):
                event_data = event_data[len(SOCKETIO_NAMESPACE) + 1 :]

            data_obj = json.loads(event_data)
            event_name = data_obj[0] if isinstance(data_obj, list) and len(data_obj) > 0 else "unknown"
            event_payload = data_obj[1] if isinstance(data_obj, list) and len(data_obj) > 1 else {}

            _LOGGER.debug("Socket.IO event: %s", event_name)

            if event_name == "update":
                await self._handle_update_event(event_payload)
            elif event_name == "dev_data":
                await self._handle_dev_data_event(event_payload)

        except Exception as err:
            _LOGGER.error("Failed to handle Socket.IO event: %s", err)

    async def _handle_update_event(self, payload: dict[str, Any]) -> None:
        """Handle device update event."""
        try:
            path = payload.get("path", "")
            body = payload.get("body", {})

            # Parse path to get device and zone
            # Format: /acm/2/status or /acm/3/setup or /connected
            if "/acm/" in path:
                parts = path.split("/")
                if len(parts) >= 3:
                    zone_id = int(parts[2])
                    update_type = parts[3] if len(parts) > 3 else "status"

                    # Update coordinator data for this zone
                    if self._device_id:
                        unique_key = f"{self._device_id}_zone{zone_id}"
                        if unique_key in (self.data or {}):
                            new_data = dict(self.data)
                            zone = dict(new_data.get(unique_key, {}))
                            if update_type == "status":
                                zone["status"] = body
                            elif update_type == "setup":
                                zone["setup"] = body
                            new_data[unique_key] = zone

                            # Notify listeners (copy-on-write)
                            self.async_set_updated_data(new_data)
                            _LOGGER.debug("Updated %s %s", unique_key, update_type)

        except Exception as err:
            _LOGGER.error("Failed to handle update event: %s", err)

    async def _handle_dev_data_event(self, payload: dict[str, Any]) -> None:
        """Handle full device data event."""
        try:
            nodes = payload.get("nodes", [])
            if not nodes:
                return

            new_data = dict(self.data or {})

            # Update coordinator data with full zone info
            for node in nodes:
                addr = node.get("addr")
                if addr and self._device_id:
                    unique_key = f"{self._device_id}_zone{addr}"

                    # Create or update zone data
                    zone = dict(new_data.get(unique_key, {}))
                    if not zone:
                        zone = {
                            "dev_id": self._device_id,
                            "device_id": self._device_id,
                            "device_name": self._device_name,
                            "group_id": self._group_id,
                            "group_name": self._group_name,
                            "zone_id": addr,
                            "name": node.get("name", f"Zone {addr}"),
                        }

                    # Update with node data
                    zone.update(
                        {
                            "name": node.get("name", zone.get("name")),
                            "device_name": self._device_name,
                            "group_name": self._group_name,
                            "status": node.get("status", {}),
                            "setup": node.get("setup", {}),
                            "version": node.get("version", {}),
                        }
                    )

                    new_data[unique_key] = zone

            # Notify listeners
            self.async_set_updated_data(new_data)
            _LOGGER.debug("Updated device data for %s zone(s) via dev_data", len(nodes))

        except Exception as err:
            _LOGGER.error("Failed to handle dev_data event: %s", err)

    async def async_request_refresh(self) -> None:
        """Request a data refresh (Socket.IO or REST API fallback)."""
        # Try Socket.IO first if connected
        if self._connected and self._sid:
            try:
                token = await self.api.async_get_access_token()
                params = {
                    "token": token,
                    "EIO": "3",
                    "transport": "polling",
                    "sid": self._sid,
                }
                if self._device_id:
                    params["dev_id"] = self._device_id

                url = f"{SOCKETIO_BASE_URL}{SOCKETIO_PATH}?{urlencode(params)}"
                dev_data_event = f'42{SOCKETIO_NAMESPACE},["dev_data"]'
                dev_data_packet = f"{len(dev_data_event)}:{dev_data_event}"

                await self.session.post(url, data=dev_data_packet)
                _LOGGER.debug("Requested dev_data refresh via Socket.IO")
                return
            except Exception as err:
                _LOGGER.warning("Socket.IO refresh failed, falling back to REST API: %s", err)

        # Fallback: Refresh via REST API (status only, names come from Socket.IO)
        try:
            _LOGGER.debug("Refreshing data via REST API (Socket.IO unavailable)")
            new_data = dict(self.data or {})
            for zone_key in list(new_data.keys()):
                zone_data = new_data.get(zone_key, {})
                device_id = zone_data.get("device_id")
                zone_id = zone_data.get("zone_id")

                if device_id and zone_id:
                    # Fetch latest status
                    status = await self.api.get_device_status(device_id, zone_id)

                    # Update coordinator data
                    zone = dict(zone_data)
                    zone["status"] = status
                    new_data[zone_key] = zone

            # Notify listeners
            self.async_set_updated_data(new_data)
            _LOGGER.debug("Data refreshed via REST API")
        except Exception as err:
            _LOGGER.error("Failed to refresh via REST API: %s", err)
