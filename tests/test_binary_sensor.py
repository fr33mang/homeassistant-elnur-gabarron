"""Tests for the binary sensor platform."""

from unittest.mock import MagicMock

import pytest

from custom_components.elnur_gabarron.binary_sensor import BINARY_SENSOR_DESCRIPTIONS, ElnurGabarronBinarySensor

from .fixtures import DEVICE_ID, ZONE_ALL_FLAGS_ON, ZONE_ID, ZONE_KEY, ZONE_OFF

DESCRIPTIONS = {d.key: d for d in BINARY_SENSOR_DESCRIPTIONS}


def build_binary_sensor(zone: dict, key: str) -> ElnurGabarronBinarySensor:
    coordinator = MagicMock()
    coordinator.data = {ZONE_KEY: zone}
    coordinator.last_update_success = True
    return ElnurGabarronBinarySensor(coordinator, ZONE_KEY, DEVICE_ID, ZONE_ID, zone["name"], DESCRIPTIONS[key])


# Parametrized over the production description table rather than a list kept
# in step by hand, so a new binary sensor gets these cases automatically.
ALL_KEYS = list(DESCRIPTIONS)


# What every binary sensor reports for the real ZONE_OFF payload. Everything
# that describes activity is off; True Radiant is a setting, and it's enabled.
OFF_EXPECTATIONS = {key: False for key in DESCRIPTIONS} | {"true_radiant_enabled": True}


@pytest.mark.parametrize("key", ALL_KEYS, ids=str)
def test_values_on_an_idle_heater(key):
    assert build_binary_sensor(ZONE_OFF, key).is_on is OFF_EXPECTATIONS[key]


@pytest.mark.parametrize("key", ALL_KEYS, ids=str)
def test_all_on_when_the_payload_says_so(key):
    assert build_binary_sensor(ZONE_ALL_FLAGS_ON, key).is_on is True


@pytest.mark.parametrize("key", ALL_KEYS, ids=str)
def test_unknown_when_payload_key_is_absent(key):
    # A partial payload should leave the entity unknown rather than silently
    # reporting "off", which would look like real information.
    zone = {**ZONE_OFF, DESCRIPTIONS[key].section: {}}
    assert build_binary_sensor(zone, key).is_on is None


def test_each_description_maps_to_a_distinct_payload_field():
    fields = [(d.section, d.payload_key) for d in BINARY_SENSOR_DESCRIPTIONS]
    assert len(fields) == len(set(fields))


EXPECTED_FIELDS = {
    "heating": ("status", "heating"),
    "charging": ("status", "charging"),
    "window_open": ("status", "window_open"),
    "presence": ("status", "presence"),
    "true_radiant": ("status", "true_radiant_active"),
    "extra_energy": ("status", "using_extra_nrg"),
    "child_lock": ("status", "locked"),
    "venting": ("status", "venting"),
    "window_detection": ("setup", "window_mode_enabled"),
    "true_radiant_enabled": ("setup", "true_radiant_enabled"),
}


@pytest.mark.parametrize("key", ALL_KEYS, ids=str)
def test_entity_key_maps_to_the_expected_payload_field(key):
    # The entity key and the wire field differ for half of these; pin the
    # mapping so a rename on either side can't silently cross the wires.
    assert key in EXPECTED_FIELDS, f"binary sensor {key!r} has no expected payload field"
    description = DESCRIPTIONS[key]
    assert (description.section, description.payload_key) == EXPECTED_FIELDS[key]


def test_unique_id_is_stable():
    sensor = build_binary_sensor(ZONE_OFF, "heating")
    assert sensor.unique_id == f"elnur_gabarron_{DEVICE_ID}_{ZONE_ID}_heating"


def test_unavailable_when_zone_drops_out_of_coordinator_data():
    sensor = build_binary_sensor(ZONE_OFF, "heating")
    assert sensor.available is True

    sensor.coordinator.data = {}
    assert sensor.available is False


def test_unavailable_after_a_failed_update():
    # Socket.IO dropping is the common case, and the stale zone dict survives
    # in .data; availability is what keeps it off the dashboard.
    sensor = build_binary_sensor(ZONE_OFF, "heating")
    assert sensor.available is True

    sensor.coordinator.last_update_success = False

    assert sensor.available is False


async def test_async_setup_entry_creates_every_binary_sensor_for_every_zone():
    from custom_components.elnur_gabarron.binary_sensor import async_setup_entry
    from custom_components.elnur_gabarron.const import DOMAIN

    second_key = f"{DEVICE_ID}_zone3"
    coordinator = MagicMock()
    coordinator.data = {ZONE_KEY: ZONE_OFF, second_key: {**ZONE_OFF, "zone_id": 3, "name": "Test Zone B"}}

    hass = MagicMock()
    entry = MagicMock()
    hass.data = {DOMAIN: {entry.entry_id: coordinator}}
    added = []

    await async_setup_entry(hass, entry, lambda entities: added.extend(entities))

    assert len(added) == 2 * len(BINARY_SENSOR_DESCRIPTIONS)
    assert len({e.unique_id for e in added}) == len(added)


def test_is_on_coerces_an_int_flag_to_bool():
    # The server sends `locked` as 0/1 next to genuine booleans; HA expects
    # is_on to be a bool.
    zone = {**ZONE_OFF, "status": {**ZONE_OFF["status"], "locked": 1}}

    assert build_binary_sensor(zone, "child_lock").is_on is True
    assert build_binary_sensor(ZONE_OFF, "child_lock").is_on is False


def test_follows_zone_rename():
    # zone_name is duplicated character for character across the two platform
    # base classes, so it needs asserting on both -- a fix applied to one copy
    # would otherwise sail past the suite.
    sensor = build_binary_sensor(ZONE_OFF, "heating")
    sensor.coordinator.data = {ZONE_KEY: {**ZONE_OFF, "name": "Renamed"}}

    assert sensor.zone_name == "Renamed"


def test_falls_back_to_initial_name_when_payload_has_none():
    sensor = build_binary_sensor(ZONE_OFF, "heating")
    sensor.coordinator.data = {ZONE_KEY: {**ZONE_OFF, "name": ""}}

    assert sensor.zone_name == ZONE_OFF["name"]
