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
        self._consecutive_connection_failures = 0
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ping_interval: float = 25.0
        self._ping_timeout: float = 60.0
        self._ping_task: asyncio.Task | None = None
        self._last_pong_time: float = 0

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
            if not await self._connect_socketio():
                raise UpdateFailed("Failed to connect to Socket.IO")

            device_data = await self._await_dev_data(timeout=10.0)
            if device_data is None:
                raise UpdateFailed("Timed out waiting for dev_data from Socket.IO")

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

    async def _await_dev_data(self, timeout: float) -> dict[str, Any] | None:
        """Wait for a dev_data event on whichever transport is currently active.

        Returns None if no dev_data event arrived within timeout (a real
        failure the caller should retry on), or a dict — possibly empty, if
        the device genuinely has no supported zones — once one did.
        """
        deadline = time.monotonic() + timeout

        if self._ws is not None:
            ws = self._ws
            while (remaining := deadline - time.monotonic()) > 0:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=remaining)
                except asyncio.TimeoutError:
                    break

                if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                    # The socket won't produce anything else; without this the
                    # loop would spin on an immediately-returning receive()
                    # until the whole timeout elapsed.
                    break
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                if msg.data == "2":
                    await ws.send_str("3")  # Defensive PONG, see _websocket_loop
                    continue
                # Anything else here (namespace acks, "update" events that
                # happen to arrive before "dev_data") is intentionally
                # dropped: nothing is registered as an entity yet during this
                # initial fetch, so there's nothing meaningful to apply it to.
                device_data = self._parse_dev_data_message(msg.data)
                if device_data is not None:
                    return device_data
            return None

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

        return None

    async def _async_update_data(self) -> dict[str, Any]:
        """Initial data fetch (called once at startup)."""
        return await self._fetch_initial_data()

    async def _connect_socketio(self) -> bool:
        """Connect to Socket.IO server."""
        try:
            # A fresh handshake means a fresh sid; any previously upgraded
            # WebSocket belongs to the old session and would otherwise leak
            # (nothing reads from it and async_stop() can no longer reach it
            # once self._ws is overwritten below).
            if self._ws is not None and not self._ws.closed:
                await self._ws.close()
            self._ws = None

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

            # heartbeat=None: disable aiohttp's own WS-protocol ping/pong frames.
            # Keepalive here has to be the Engine.IO-level "2"/"3" text packets
            # (sent by _ping_sender), not WebSocket control frames — the server
            # only understands the former.
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

                await self._run_with_ping(self._websocket_loop() if self._ws is not None else self._polling_loop())

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

    async def _run_with_ping(self, read_loop) -> None:
        """Run a read loop (WS or polling) alongside the client-initiated ping sender."""
        self._last_pong_time = time.monotonic()  # don't immediately trip the missed-pong check
        self._ping_task = asyncio.create_task(self._ping_sender())
        try:
            await read_loop
        finally:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
            self._ping_task = None

    async def _send_ping(self) -> None:
        """Send an Engine.IO ping ("2") on whichever transport is currently active."""
        if self._ws is not None:
            await self._ws.send_str("2")
            return

        params = {
            "token": await self.api.async_get_access_token(),
            "EIO": "3",
            "transport": "polling",
            "sid": self._sid,
        }
        if self._device_id:
            params["dev_id"] = self._device_id
        url = f"{SOCKETIO_BASE_URL}{SOCKETIO_PATH}?{urlencode(params)}&t={time.time_ns()}"
        # Polling packets are length-prefixed ("<len>:<packet>"), same as the
        # namespace-join/dev_data packets sent elsewhere in this file.
        await self.session.post(url, data="1:2")

    async def _ping_sender(self) -> None:
        """Send client-initiated Engine.IO pings and disconnect on a missed pong.

        EIO=3 (used here) has the CLIENT send "2" every pingInterval and expect
        a "3" back within pingTimeout — the opposite direction from EIO=4. The
        server resets its own idle-timeout on every packet it gets from us, so
        pings must go out every pingInterval regardless of whether the previous
        one was acked yet. Waiting for a pong before scheduling the next ping
        (an earlier version of this did `sleep(interval); ping; sleep(timeout)`)
        pushes the real cadence out to pingInterval + pingTimeout — which is
        exactly the server's own deadline, so it's a coin flip whether our next
        ping lands before the server gives up (observed in practice: a real
        connection dropped at t=110s = interval + timeout + interval).
        Runs as its own task so its schedule doesn't depend on whichever read
        loop (WS or polling) happens to be active.
        """
        try:
            while self._connected:
                await asyncio.sleep(self._ping_interval)
                if not self._connected:
                    break

                try:
                    await self._send_ping()
                except Exception as err:
                    _LOGGER.debug("Failed to send ping, reconnecting: %s", err)
                    self._connected = False
                    await self._close_ws_for_reconnect()
                    break

                # Tolerate a missed pong or two (server hiccup, jitter) rather
                # than reconnecting on the first one; only give up once we're
                # as stale as the server's own pingInterval + pingTimeout budget.
                stale_for = time.monotonic() - self._last_pong_time
                if stale_for > self._ping_interval + self._ping_timeout:
                    _LOGGER.warning(
                        "No pong received in %ss, reconnecting...",
                        int(stale_for),
                    )
                    self._connected = False
                    # Close the socket now rather than leaving the read loop's
                    # ws.receive() to discover this on its own timeout: a
                    # closed ws makes receive() return CLOSED immediately.
                    await self._close_ws_for_reconnect()
                    break
        except asyncio.CancelledError:
            pass

    async def _close_ws_for_reconnect(self) -> None:
        """Close the active WebSocket, if any, to wake up a blocked ws.receive()."""
        if self._ws is not None and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception:
                pass

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

                # No "quiet for N minutes" watchdog here: a pong (or any other
                # activity, tracked below via last_activity) is proof the
                # connection is alive on its own, regardless of whether the
                # heaters have anything to report.

                # Check for idle session (no activity within the server's own timeout budget)
                elapsed = current_time - last_activity
                if elapsed > self._ping_interval + self._ping_timeout:
                    _LOGGER.info("Session idle for %ss, reconnecting...", int(elapsed))
                    self._connected = False
                    break

                # Periodic dev_data re-request as a data freshness safety net.
                # Not a real keepalive any more -- _ping_sender already keeps
                # the session itself alive -- and "every 300 polls" no longer
                # means "every 30s" now that each poll can block for up to
                # pingInterval (not a fixed 0.1s), but it's cheap insurance
                # against missing an update on this fallback path.
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

                            # Handle Engine.IO PONG (reply to our own client-initiated ping)
                            if msg == "3":
                                self._last_pong_time = current_time
                                continue

                            # Defensive: EIO=3 pings are sent by the client, not the
                            # server, so this shouldn't normally happen. Reply anyway
                            # in case the server ever does send one.
                            if msg == "2":
                                await self.session.post(f"{base_url}&t={time.time_ns()}", data="1:3")  # Send PONG
                                _LOGGER.debug("Received PING, sent PONG")
                                continue

                            # Skip namespace connection acks
                            if msg == "40" or msg.startswith("40/"):
                                continue

                            # Handle Socket.IO events (actual data updates)
                            if msg.startswith("42"):
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

                # Handle Engine.IO PONG (reply to our own client-initiated ping)
                if data == "3":
                    self._last_pong_time = current_time
                    continue

                # Defensive: EIO=3 pings are sent by the client, not the server,
                # so this shouldn't normally happen. Reply anyway in case the
                # server ever does send one.
                if data == "2":
                    await ws.send_str("3")  # Send PONG
                    _LOGGER.debug("Received PING, sent PONG (WebSocket)")
                    continue

                # Skip namespace connection acks
                if data == "40" or data.startswith("40/"):
                    continue

                # Handle Socket.IO events (actual data updates)
                if data.startswith("42"):
                    self._consecutive_connection_failures = 0
                    await self._handle_socketio_event(data)

                # No "quiet for N minutes" watchdog here: a pong is proof the
                # connection is alive on its own, regardless of whether the
                # heaters happen to have anything to report. _ping_sender
                # already reconnects us if pongs stop arriving; gating on
                # _last_update_time as well used to force a reconnect on any
                # house that's simply quiet for 5+ minutes.
        finally:
            # Stop pinging before dropping the socket reference: _ping_sender
            # checks `self._ws is not None` to decide which transport to ping
            # on, and could otherwise fire one last ping at a POST-based
            # fallback for a sid that's about to be replaced.
            if self._ping_task is not None:
                self._ping_task.cancel()
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
