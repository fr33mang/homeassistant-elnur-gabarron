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


@pytest.mark.parametrize("key", ALL_KEYS, ids=str)
def test_all_off_on_an_idle_heater(key):
    assert build_binary_sensor(ZONE_OFF, key).is_on is False


@pytest.mark.parametrize("key", ALL_KEYS, ids=str)
def test_all_on_when_the_payload_says_so(key):
    assert build_binary_sensor(ZONE_ALL_FLAGS_ON, key).is_on is True


@pytest.mark.parametrize("key", ALL_KEYS, ids=str)
def test_unknown_when_status_key_is_absent(key):
    # A partial status payload should leave the entity unknown rather than
    # silently reporting "off", which would look like real information.
    zone = {**ZONE_OFF, "status": {}}
    assert build_binary_sensor(zone, key).is_on is None


def test_each_description_maps_to_a_distinct_status_key():
    status_keys = [d.status_key for d in BINARY_SENSOR_DESCRIPTIONS]
    assert len(status_keys) == len(set(status_keys))


EXPECTED_STATUS_KEYS = {
    "heating": "heating",
    "charging": "charging",
    "window_open": "window_open",
    "presence": "presence",
    "true_radiant": "true_radiant_active",
    "extra_energy": "using_extra_nrg",
}


@pytest.mark.parametrize("key", ALL_KEYS, ids=str)
def test_entity_key_maps_to_the_expected_payload_field(key):
    # The entity key and the wire field differ for half of these; pin the
    # mapping so a rename on either side can't silently cross the wires.
    assert key in EXPECTED_STATUS_KEYS, f"binary sensor {key!r} has no expected status key"
    assert DESCRIPTIONS[key].status_key == EXPECTED_STATUS_KEYS[key]


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


def test_is_on_does_not_coerce_the_payload_value():
    # is_on is typed bool | None but returns whatever the payload holds. The
    # server sends real booleans for these six keys today (it uses ints
    # elsewhere, e.g. `locked`), so nothing is broken -- but if that ever
    # changes, HA would get an int where it expects a bool. Pinned so the
    # change is visible rather than silent.
    zone = {**ZONE_OFF, "status": {**ZONE_OFF["status"], "heating": 1}}

    # Asserted loosely on purpose: when is_on starts coercing to bool, this
    # should keep passing rather than reading as a regression from the fix.
    assert build_binary_sensor(zone, "heating").is_on == 1


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
