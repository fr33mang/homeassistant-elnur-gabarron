import asyncio
import json
import logging
import time
from typing import Any
from urllib.parse import urlencode

import aiohttp
from homeassistant.config_entries import ConfigEntry
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
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ping_interval: float = 25.0
        self._ping_timeout: float = 60.0

    @property
    def group_name(self) -> str | None:
        """Return the group/home name."""
        return self._group_name

    async def async_start(self, entry: ConfigEntry) -> None:
        """Start the Socket.IO listener."""
        if self._listener_task is None or self._listener_task.done():
            _LOGGER.debug("Starting Socket.IO listener")
            self._listener_task = entry.async_create_background_task(
                self.hass, self._socketio_listener(), "elnur_socketio_listener"
            )

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
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        self._ws = None

    def _is_heater_zone(self, node: dict) -> bool:
        """Return True if the zone looks like a heater (has accumulator or emitter power)."""
        factory_opts = node.get("setup", {}).get("factory_options", {})
        return bool(factory_opts.get("accumulator_power") or factory_opts.get("emitter_power"))

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

            # Connect to Socket.IO and get dev_data SYNCHRONOUSLY.
            # _connect_socketio() already requests dev_data as part of its
            # own handshake (Step 3) and may upgrade to WebSocket before
            # returning, so the response has to be awaited on whichever
            # transport ends up active rather than assumed to be polling.
            _LOGGER.debug("Connecting to Socket.IO to fetch zone data")
            await self._connect_socketio()

            device_data = await self._await_dev_data(timeout=10.0)
            _LOGGER.debug("Received dev_data with %s zone(s)", len(device_data))
            return device_data

        except Exception as err:
            _LOGGER.error("Failed to fetch initial data", exc_info=True)
            raise UpdateFailed("Failed to fetch initial data") from err

    def _parse_dev_data_message(self, msg: str) -> dict[str, Any] | None:
        """Parse a raw Engine.IO message, returning zone data if it's a dev_data event."""
        if not msg.startswith("42") or "dev_data" not in msg:
            return None

        event_data = msg[2:]
        if event_data.startswith(SOCKETIO_NAMESPACE):
            event_data = event_data[len(SOCKETIO_NAMESPACE) + 1 :]

        data_obj = json.loads(event_data)
        if not (isinstance(data_obj, list) and data_obj[0] == "dev_data"):
            return None

        nodes = data_obj[1].get("nodes", [])
        device_data: dict[str, Any] = {}

        for node in nodes:
            if not self._is_heater_zone(node):
                _LOGGER.warning(
                    "Skipping zone %s ('%s') on device %s "
                    "— no heater factory_options found. "
                    "This device type is not supported yet.",
                    node.get("addr"),
                    node.get("name", "unknown"),
                    self._device_id,
                )
                continue

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

    async def _await_dev_data(self, timeout: float) -> dict[str, Any]:
        """Wait for a dev_data event on whichever transport is currently active."""
        deadline = time.monotonic() + timeout

        if self._ws is not None:
            while (remaining := deadline - time.monotonic()) > 0:
                try:
                    msg = await asyncio.wait_for(self._ws.receive(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                if msg.data == "2":
                    await self._ws.send_str("3")  # PING -> PONG
                    continue
                device_data = self._parse_dev_data_message(msg.data)
                if device_data is not None:
                    return device_data
            return {}

        # Polling fallback
        params = {
            "token": await self.api.async_get_access_token(),
            "EIO": "3",
            "transport": "polling",
            "sid": self._sid,
            "dev_id": self._device_id,
        }
        url = f"{SOCKETIO_BASE_URL}{SOCKETIO_PATH}?{urlencode(params)}"

        while time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            try:
                async with self.session.get(
                    f"{url}&t={time.time_ns()}", timeout=aiohttp.ClientTimeout(total=2)
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.read()
                    for raw_msg in parse_engineio_payload(data):
                        device_data = self._parse_dev_data_message(raw_msg)
                        if device_data is not None:
                            return device_data
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                _LOGGER.debug("Poll error: %s", e)
                continue

        return {}

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
                self._ping_interval = handshake.get("pingInterval", 25000) / 1000
                self._ping_timeout = handshake.get("pingTimeout", 60000) / 1000
                _LOGGER.debug(
                    "Socket.IO connected, session ID: %s (pingInterval=%ss, pingTimeout=%ss)",
                    self._sid,
                    self._ping_interval,
                    self._ping_timeout,
                )

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

            # Try to upgrade to WebSocket, same as the official web client does
            # (the handshake advertises "upgrades": ["websocket"]). Polling is
            # kept as a fallback if the upgrade doesn't succeed.
            await self._upgrade_to_websocket(token)

            return True

        except Exception as err:
            _LOGGER.error("Socket.IO connection failed: %s", err)
            return False

    async def _upgrade_to_websocket(self, token: str) -> None:
        """Attempt to upgrade the Engine.IO polling connection to WebSocket.

        Follows the Engine.IO v3 upgrade handshake: open a WebSocket to the
        existing sid, send a "2probe", expect "3probe" back, then confirm
        with "5". Leaves self._ws unset (None) on any failure so the caller
        falls back to polling.
        """
        try:
            ws_scheme_url = SOCKETIO_BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
            params = {
                "token": token,
                "EIO": "3",
                "transport": "websocket",
                "sid": self._sid,
            }
            if self._device_id:
                params["dev_id"] = self._device_id

            ws_url = f"{ws_scheme_url}{SOCKETIO_PATH}?{urlencode(params)}"

            ws = await self.session.ws_connect(ws_url, timeout=aiohttp.ClientTimeout(total=10), heartbeat=None)

            await ws.send_str("2probe")
            probe_reply = await ws.receive(timeout=5)
            if probe_reply.type != aiohttp.WSMsgType.TEXT or probe_reply.data != "3probe":
                _LOGGER.debug("WebSocket probe failed, staying on polling transport")
                await ws.close()
                return

            await ws.send_str("5")  # Confirm upgrade
            self._ws = ws
            _LOGGER.debug("Upgraded Socket.IO connection to WebSocket transport")

        except Exception as err:
            _LOGGER.debug("WebSocket upgrade failed, staying on polling transport: %s", err)
            self._ws = None

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

                    await asyncio.sleep(reconnect_delay)
                    # Exponential backoff, max 60s
                    reconnect_delay = min(reconnect_delay * 2, 60)
                    continue

                # Reset on successful connection
                self._reconnect_count = 0
                self._consecutive_connection_failures = 0
                reconnect_delay = 5
                last_activity = time.monotonic()
                self._last_update_time = last_activity
                self._last_successful_connect_time = last_activity

                if self._ws is not None:
                    await self._websocket_loop()
                else:
                    await self._polling_loop()

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

    async def _polling_loop(self) -> None:
        """Read loop while connected via the Engine.IO polling transport.

        Fallback path used only when the WebSocket upgrade fails. Poll GETs
        are bounded by pingInterval so we never hold a request open longer
        than the server itself expects to hear from us.
        """
        last_activity = time.monotonic()
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

        base_url = f"{SOCKETIO_BASE_URL}{SOCKETIO_PATH}?{urlencode(params)}"
        poll_timeout = aiohttp.ClientTimeout(total=self._ping_interval)

        while self._connected:
            try:
                poll_count += 1
                current_time = time.monotonic()

                # Watchdog: Check for stale connection (no real updates in 5 minutes)
                time_since_update = current_time - self._last_update_time
                if time_since_update > 300:  # 5 minutes
                    _LOGGER.warning(
                        "No updates received for %ss, forcing reconnect...",
                        int(time_since_update),
                    )
                    self._connected = False
                    break

                # Check for idle session (no activity within the server's own timeout budget)
                elapsed = current_time - last_activity
                if elapsed > self._ping_interval + self._ping_timeout:
                    _LOGGER.info("Session idle for %ss, reconnecting...", int(elapsed))
                    self._connected = False
                    break

                # Periodic keepalive dev_data request (every 30s)
                if poll_count % 300 == 0:
                    _LOGGER.debug("Sending periodic dev_data keepalive...")
                    dev_data_event = f'42{SOCKETIO_NAMESPACE},["dev_data"]'
                    dev_data_packet = f"{len(dev_data_event)}:{dev_data_event}"
                    await self.session.post(f"{base_url}&t={time.time_ns()}", data=dev_data_packet)

                # Poll for messages, cache-busted like the official client to
                # avoid a proxy/CDN serving a stale response for this GET
                url = f"{base_url}&t={time.time_ns()}"
                async with self.session.get(url, timeout=poll_timeout) as resp:
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
                                await self.session.post(f"{base_url}&t={time.time_ns()}", data="3")  # Send PONG
                                _LOGGER.debug("Received PING, sent PONG")
                                continue

                            # Skip namespace connection acks
                            if msg == "40" or msg.startswith("40/"):
                                continue

                            # Handle Socket.IO events (actual data updates)
                            if msg.startswith("42"):
                                self._last_update_time = current_time  # Real update received
                                self._consecutive_connection_failures = 0  # Reset failure counter on successful data
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
                # Expected: the server had nothing to say within pingInterval.
                # Not an error by itself, just loop and poll again.
                _LOGGER.debug("Socket.IO poll timeout, continuing...")
                continue
            except Exception as poll_err:
                _LOGGER.error("Socket.IO poll error: %s", poll_err, exc_info=True)
                self._connected = False
                break

    async def _websocket_loop(self) -> None:
        """Read loop while connected via the upgraded WebSocket transport."""
        ws = self._ws
        # Give the server a bit of slack beyond its own ping/pong budget
        # before deciding the socket is dead.
        recv_timeout = self._ping_interval + self._ping_timeout

        try:
            while self._connected:
                try:
                    msg = await ws.receive(timeout=recv_timeout)
                except asyncio.TimeoutError:
                    _LOGGER.warning(
                        "No WebSocket activity for %ss, reconnecting...",
                        int(recv_timeout),
                    )
                    self._connected = False
                    break

                current_time = time.monotonic()

                if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                    _LOGGER.warning("WebSocket closed (%s), reconnecting...", msg.type)
                    self._connected = False
                    break

                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue

                data = msg.data
                if not data or data == "6":  # Skip NOOP
                    continue

                # Handle Engine.IO CLOSE
                if data == "1":
                    _LOGGER.debug("Server sent CLOSE over WebSocket, reconnecting...")
                    self._connected = False
                    break

                # Handle Engine.IO PING
                if data == "2":
                    await ws.send_str("3")  # Send PONG
                    _LOGGER.debug("Received PING, sent PONG (WebSocket)")
                    continue

                # Skip namespace connection acks
                if data == "40" or data.startswith("40/"):
                    continue

                # Handle Socket.IO events (actual data updates)
                if data.startswith("42"):
                    self._last_update_time = current_time
                    self._consecutive_connection_failures = 0
                    await self._handle_socketio_event(data)

                # Watchdog: Check for stale connection (no real updates in 5 minutes)
                time_since_update = current_time - self._last_update_time
                if time_since_update > 300:  # 5 minutes
                    _LOGGER.warning(
                        "No updates received for %ss, forcing reconnect...",
                        int(time_since_update),
                    )
                    self._connected = False
                    break
        finally:
            if not ws.closed:
                await ws.close()
            self._ws = None

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
                if not self._is_heater_zone(node):
                    _LOGGER.warning(
                        "Skipping zone %s ('%s') on device %s "
                        "— no heater factory_options found. "
                        "This device type is not supported yet.",
                        node.get("addr"),
                        node.get("name", "unknown"),
                        self._device_id,
                    )
                    continue

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
            dev_data_event = f'42{SOCKETIO_NAMESPACE},["dev_data"]'
            try:
                if self._ws is not None:
                    await self._ws.send_str(dev_data_event)
                    _LOGGER.debug("Requested dev_data refresh via WebSocket")
                    return

                token = await self.api.async_get_access_token()
                params = {
                    "token": token,
                    "EIO": "3",
                    "transport": "polling",
                    "sid": self._sid,
                }
                if self._device_id:
                    params["dev_id"] = self._device_id

                url = f"{SOCKETIO_BASE_URL}{SOCKETIO_PATH}?{urlencode(params)}&t={time.time_ns()}"
                dev_data_packet = f"{len(dev_data_event)}:{dev_data_event}"

                await self.session.post(url, data=dev_data_packet)
                _LOGGER.debug("Requested dev_data refresh via Socket.IO polling")
                return
            except Exception as err:
                _LOGGER.error("Socket.IO refresh failed, %s", err)

        _LOGGER.error("Socket.IO refresh failed")
