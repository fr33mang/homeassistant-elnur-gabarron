"""Joins the coordinator's output to the entities' input.

Everything else in the suite tests one side of that seam or the other: the
coordinator tests assert how a dev_data frame is parsed, the platform tests
read a hand-written literal. Nothing asserts the two still agree, so renaming a
key the coordinator writes — "status" to "state", say — breaks every sensor on
a live system while the suite stays green.

These tests take a raw Engine.IO frame, run it through the real parser, and
build real entities from whatever comes out.
"""

import json
from unittest.mock import MagicMock

import pytest

from custom_components.elnur_gabarron.binary_sensor import BINARY_SENSOR_DESCRIPTIONS, ElnurGabarronBinarySensor
from custom_components.elnur_gabarron.sensor import SENSOR_DESCRIPTIONS, ElnurGabarronSensor
from custom_components.elnur_gabarron.socketio_coordinator import SOCKETIO_NAMESPACE, ElnurSocketIOCoordinator

from .fixtures import DEVICE_ID, ZONE_ID, ZONE_OFF

SENSORS = {d.key: d for d in SENSOR_DESCRIPTIONS}
BINARY_SENSORS = {d.key: d for d in BINARY_SENSOR_DESCRIPTIONS}


def dev_data_frame() -> str:
    """A dev_data event exactly as it arrives on the wire."""
    node = {
        "addr": ZONE_ID,
        "type": "acm",
        "name": ZONE_OFF["name"],
        "status": ZONE_OFF["status"],
        "setup": ZONE_OFF["setup"],
        "version": ZONE_OFF["version"],
    }
    payload = {"nodes": [node]}
    return f'42{SOCKETIO_NAMESPACE},{json.dumps(["dev_data", payload])}'


@pytest.fixture
def parsed_zones(hass) -> dict:
    """Run a real frame through the real parser."""
    coordinator = ElnurSocketIOCoordinator(hass, MagicMock(), MagicMock())
    coordinator._device_id = DEVICE_ID
    coordinator._device_name = ZONE_OFF["device_name"]
    coordinator._group_id = ZONE_OFF["group_id"]
    coordinator._group_name = ZONE_OFF["group_name"]

    zones = coordinator._parse_dev_data_message(dev_data_frame())
    assert zones, "parser produced no zones for a valid dev_data frame"
    return zones


def entity_coordinator(zones: dict) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = zones
    coordinator.last_update_success = True
    return coordinator


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("charge_level", 3),
        ("power", 0.0),
        ("target_charge", 100),
        ("error_code", 1024),
        ("priority", "Medium"),
        ("firmware", "FW: 1.4 / HW: 1.0"),
        ("charging_slot1", "00:00 - 08:00"),
        ("charging_days", "Every day"),
    ],
)
def test_sensor_reads_what_the_coordinator_actually_writes(parsed_zones, key, expected):
    zone_key = next(iter(parsed_zones))
    zone = parsed_zones[zone_key]

    sensor = ElnurGabarronSensor(
        entity_coordinator(parsed_zones), zone_key, DEVICE_ID, ZONE_ID, zone["name"], SENSORS[key]
    )

    assert sensor.native_value == expected


@pytest.mark.parametrize("key", list(BINARY_SENSORS), ids=str)
def test_binary_sensor_reads_what_the_coordinator_actually_writes(parsed_zones, key):
    zone_key = next(iter(parsed_zones))
    zone = parsed_zones[zone_key]

    sensor = ElnurGabarronBinarySensor(
        entity_coordinator(parsed_zones), zone_key, DEVICE_ID, ZONE_ID, zone["name"], BINARY_SENSORS[key]
    )

    # False, not None: None would mean the entity couldn't find the field at all.
    assert sensor.is_on is False


def test_zone_key_the_coordinator_builds_is_the_one_entities_are_set_up_with(parsed_zones):
    assert set(parsed_zones) == {f"{DEVICE_ID}_zone{ZONE_ID}"}


def test_hand_written_fixture_still_matches_the_parser_output(parsed_zones):
    # ZONE_OFF is transcribed by hand from what the coordinator produces. If the
    # coordinator's shape drifts, this is where it shows up, rather than every
    # platform test quietly passing against a stale literal.
    zone = parsed_zones[f"{DEVICE_ID}_zone{ZONE_ID}"]

    assert zone.keys() == ZONE_OFF.keys()
    assert zone == ZONE_OFF
