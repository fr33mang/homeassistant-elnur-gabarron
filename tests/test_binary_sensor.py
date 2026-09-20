"""Tests for the binary sensor platform."""

from unittest.mock import MagicMock

import pytest

from custom_components.elnur_gabarron.binary_sensor import BINARY_SENSOR_DESCRIPTIONS, ElnurGabarronBinarySensor

from .fixtures import DEVICE_ID, ZONE_HEATING, ZONE_ID, ZONE_KEY, ZONE_OFF

DESCRIPTIONS = {d.key: d for d in BINARY_SENSOR_DESCRIPTIONS}


def build_binary_sensor(zone: dict, key: str) -> ElnurGabarronBinarySensor:
    coordinator = MagicMock()
    coordinator.data = {ZONE_KEY: zone}
    coordinator.last_update_success = True
    return ElnurGabarronBinarySensor(coordinator, ZONE_KEY, DEVICE_ID, ZONE_ID, zone["name"], DESCRIPTIONS[key])


ALL_KEYS = ("heating", "charging", "window_open", "presence", "true_radiant", "extra_energy")


def test_every_description_has_a_test():
    # Guards against a new binary sensor being added without coverage here.
    assert set(DESCRIPTIONS) == set(ALL_KEYS)


@pytest.mark.parametrize("key", ALL_KEYS)
def test_all_off_on_an_idle_heater(key):
    assert build_binary_sensor(ZONE_OFF, key).is_on is False


@pytest.mark.parametrize("key", ALL_KEYS)
def test_all_on_when_the_payload_says_so(key):
    assert build_binary_sensor(ZONE_HEATING, key).is_on is True


@pytest.mark.parametrize("key", ALL_KEYS)
def test_unknown_when_status_key_is_absent(key):
    # A partial status payload should leave the entity unknown rather than
    # silently reporting "off", which would look like real information.
    zone = {**ZONE_OFF, "status": {}}
    assert build_binary_sensor(zone, key).is_on is None


def test_each_description_maps_to_a_distinct_status_key():
    status_keys = [d.status_key for d in BINARY_SENSOR_DESCRIPTIONS]
    assert len(status_keys) == len(set(status_keys))


@pytest.mark.parametrize(
    ("key", "status_key"),
    [
        ("heating", "heating"),
        ("charging", "charging"),
        ("window_open", "window_open"),
        ("presence", "presence"),
        ("true_radiant", "true_radiant_active"),
        ("extra_energy", "using_extra_nrg"),
    ],
)
def test_entity_key_maps_to_the_expected_payload_field(key, status_key):
    # The entity key and the wire field differ for half of these; pin the
    # mapping so a rename on either side can't silently cross the wires.
    assert DESCRIPTIONS[key].status_key == status_key


def test_unique_id_is_stable():
    sensor = build_binary_sensor(ZONE_OFF, "heating")
    assert sensor.unique_id == f"elnur_gabarron_{DEVICE_ID}_{ZONE_ID}_heating"


def test_unavailable_when_zone_drops_out_of_coordinator_data():
    sensor = build_binary_sensor(ZONE_OFF, "heating")
    assert sensor.available is True

    sensor.coordinator.data = {}
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


def test_device_info_is_built_per_zone():
    info = build_binary_sensor(ZONE_OFF, "heating").device_info
    assert info["identifiers"] == {("elnur_gabarron", f"{DEVICE_ID}_zone{ZONE_ID}")}
