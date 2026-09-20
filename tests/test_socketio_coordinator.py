import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.elnur_gabarron.socketio_coordinator import ElnurSocketIOCoordinator, parse_engineio_payload

DEVICE_ID = "aed33c760ec38bd05e"

HEATER_NODE = {
    "addr": 2,
    "name": "Living Room",
    "setup": {"factory_options": {"emitter_power": "450"}},
    "status": {"mode": "auto"},
    "version": {"fw": "1.0"},
}

NON_HEATER_NODE = {
    "addr": 9,
    "name": "Unsupported thing",
    "setup": {"factory_options": {}},
    "status": {},
    "version": {},
}


# ---------------------------------------------------------------------------
# parse_engineio_payload() -- pure parsing, no network/hass needed
# ---------------------------------------------------------------------------


def test_parse_engineio_payload_plain_single_packet():
    # No framing marker at all -- treated as one message spanning the buffer.
    assert parse_engineio_payload(b"40") == ["40"]


def test_parse_engineio_payload_binary_framed_single_message():
    # 0x00, then arbitrary length bytes up to 0xFF, then the packet itself.
    # This is the actual framing api-elnur.helki.com uses on the wire.
    payload = b"\x00\x01\xff" + b"40"
    assert parse_engineio_payload(payload) == ["40"]


def test_parse_engineio_payload_binary_framed_multiple_messages():
    payload = b"\x00\x01\xff" + b"2" + b"\x00\x01\xff" + b"40"
    assert parse_engineio_payload(payload) == ["2", "40"]


def test_parse_engineio_payload_empty():
    assert parse_engineio_payload(b"") == []


# ---------------------------------------------------------------------------
# _parse_dev_data_message()
# ---------------------------------------------------------------------------


@pytest.fixture
def coordinator(hass) -> ElnurSocketIOCoordinator:
    api = MagicMock()
    session = MagicMock(spec=aiohttp.ClientSession)
    coord = ElnurSocketIOCoordinator(hass, api, session)
    coord._device_id = DEVICE_ID
    coord._device_name = "Bajo Sedes"
    coord._group_id = "group1"
    coord._group_name = "Torre Sedes"
    return coord


def test_parse_dev_data_message_ignores_non_dev_data(coordinator):
    msg = '42/api/v2/socket_io,["update",{"path":"/acm/2/status","body":{}}]'
    assert coordinator._parse_dev_data_message(msg) is None


def test_parse_dev_data_message_ignores_non_42_prefix(coordinator):
    assert coordinator._parse_dev_data_message("40") is None
    assert coordinator._parse_dev_data_message("2") is None


def test_parse_dev_data_message_builds_zone_data(coordinator):
    payload = {"nodes": [HEATER_NODE]}
    msg = f'42/api/v2/socket_io,["dev_data",{json.dumps(payload)}]'
    result = coordinator._parse_dev_data_message(msg)

    assert result is not None
    key = f"{DEVICE_ID}_zone2"
    assert key in result
    assert result[key]["name"] == "Living Room"
    assert result[key]["device_name"] == "Bajo Sedes"
    assert result[key]["group_name"] == "Torre Sedes"


def test_parse_dev_data_message_skips_non_heater_zones(coordinator):
    payload = {"nodes": [HEATER_NODE, NON_HEATER_NODE]}
    msg = f'42/api/v2/socket_io,["dev_data",{json.dumps(payload)}]'

    result = coordinator._parse_dev_data_message(msg)

    assert f"{DEVICE_ID}_zone2" in result
    assert f"{DEVICE_ID}_zone9" not in result


def test_parse_dev_data_message_empty_nodes_returns_empty_dict(coordinator):
    msg = '42/api/v2/socket_io,["dev_data",{"nodes":[]}]'
    result = coordinator._parse_dev_data_message(msg)
    assert result == {}


# ---------------------------------------------------------------------------
# _ping_sender() -- EIO=3 pings are client-initiated: we send "2", and must
# see a "3" back within pingTimeout or we tear the connection down ourselves.
# ---------------------------------------------------------------------------


async def test_ping_sender_paces_pings_by_interval_not_interval_plus_timeout(coordinator):
    # Regression test: an earlier version scheduled the next ping only after
    # sleeping ping_timeout on top of ping_interval, so with timeout >>
    # interval the real cadence was ~ping_interval + ping_timeout instead of
    # ping_interval. Using a timeout much bigger than the interval here means
    # the buggy version would send at most one ping in this whole window.
    coordinator._connected = True
    coordinator._ping_interval = 0.02
    coordinator._ping_timeout = 1.0
    coordinator._ws = AsyncMock()

    async def fake_send_str(data):
        coordinator._last_pong_time = time.monotonic()

    coordinator._ws.send_str.side_effect = fake_send_str

    task = asyncio.create_task(coordinator._ping_sender())
    await asyncio.sleep(0.09)  # should fit ~4 pings at a 0.02s cadence
    coordinator._connected = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    ping_calls = [c for c in coordinator._ws.send_str.call_args_list if c.args == ("2",)]
    assert len(ping_calls) >= 3


async def test_ping_sender_disconnects_on_missed_pong(coordinator):
    coordinator._connected = True
    coordinator._ping_interval = 0.01
    coordinator._ping_timeout = 0.01
    coordinator._ws = AsyncMock()
    # Never update _last_pong_time -- simulates the server never replying.

    await coordinator._ping_sender()

    assert coordinator._connected is False


async def test_ping_sender_disconnects_when_send_fails(coordinator):
    coordinator._connected = True
    coordinator._ping_interval = 0.01
    coordinator._ping_timeout = 1
    coordinator._ws = AsyncMock()
    coordinator._ws.send_str.side_effect = ConnectionResetError("boom")

    await coordinator._ping_sender()

    assert coordinator._connected is False
