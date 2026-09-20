"""Tests for the sensor platform.

Covers the value_fn of every sensor description through real entity instances,
so the description table, the entity wiring and the extraction helpers are all
exercised together.
"""

from unittest.mock import MagicMock

import pytest

from custom_components.elnur_gabarron.sensor import (
    SENSOR_DESCRIPTIONS,
    ElnurGabarronSensor,
    _float_from_status,
    _get_charging_days,
    _get_charging_slot,
    _get_firmware_version,
    _int_from_status,
    _minutes_to_time,
)

from .fixtures import DEVICE_ID, ZONE_HEATING, ZONE_ID, ZONE_KEY, ZONE_OFF

DESCRIPTIONS = {d.key: d for d in SENSOR_DESCRIPTIONS}


def build_sensor(zone: dict, key: str) -> ElnurGabarronSensor:
    """Build one sensor entity backed by a stub coordinator."""
    coordinator = MagicMock()
    coordinator.data = {ZONE_KEY: zone}
    coordinator.last_update_success = True
    return ElnurGabarronSensor(coordinator, ZONE_KEY, DEVICE_ID, ZONE_ID, zone["name"], DESCRIPTIONS[key])


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (3, 3),
        ("42", 42),  # the server sends several numbers as strings
        (None, None),
        ("", None),
        ("not a number", None),
        ({"nested": 1}, None),
    ],
)
def test_int_from_status(value, expected):
    assert _int_from_status({"status": {"k": value}}, "k") == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", 0.0),
        ("23.7", 23.7),
        (30, 30.0),
        (None, None),
        ("nope", None),
    ],
)
def test_float_from_status(value, expected):
    assert _float_from_status({"status": {"k": value}}, "k") == expected


def test_helpers_tolerate_missing_status_block():
    assert _int_from_status({}, "charge_level") is None
    assert _float_from_status({}, "power") is None


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [(0, "00:00"), (480, "08:00"), (90, "01:30"), (1439, "23:59")],
)
def test_minutes_to_time(minutes, expected):
    assert _minutes_to_time(minutes) == expected


# ---------------------------------------------------------------------------
# Firmware / charging schedule formatting
# ---------------------------------------------------------------------------


def test_firmware_version_combines_both_parts():
    assert _get_firmware_version(ZONE_OFF) == "FW: 1.4 / HW: 1.0"


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ({"fw_version": "1.4"}, "FW: 1.4"),
        ({"hw_version": "1.0"}, "HW: 1.0"),
        ({}, None),
    ],
)
def test_firmware_version_partial(version, expected):
    assert _get_firmware_version({"version": version}) == expected


def test_charging_slot_formats_configured_window():
    # slot_1 on the live device: midnight to 08:00
    assert _get_charging_slot(ZONE_OFF, "slot_1") == "00:00 - 08:00"


def test_charging_slot_zero_length_window_is_disabled():
    # slot_2 is start == end == 0 on the live device
    assert _get_charging_slot(ZONE_OFF, "slot_2") == "Disabled"


def test_charging_slot_without_config_reads_as_disabled():
    # Worth pinning down: an absent charging_conf defaults start/end to 0 and so
    # is reported exactly like a slot the user switched off. The two are not
    # distinguishable in the UI.
    assert _get_charging_slot({"setup": {}}, "slot_1") == "Disabled"


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (480, 120),  # window runs backwards
        (480, 480),  # zero-length window that isn't at midnight
        (120, 0),  # a start with no end -- plausible half-finished config
    ],
)
def test_charging_slot_not_configured(start, end):
    # "Not configured" covers any end <= start, as long as they aren't both 0
    # (that case is reported as "Disabled" above).
    zone = {"setup": {"charging_conf": {"slot_1": {"start": start, "end": end}}}}
    assert _get_charging_slot(zone, "slot_1") == "Not configured"


def test_charging_days_all_active():
    assert _get_charging_days(ZONE_OFF) == "Every day"


def test_charging_days_subset():
    zone = {"setup": {"charging_conf": {"active_days": [1, 0, 1, 0, 0, 0, 0]}}}
    assert _get_charging_days(zone) == "Mon, Wed"


def test_charging_days_none_selected():
    zone = {"setup": {"charging_conf": {"active_days": [0, 0, 0, 0, 0, 0, 0]}}}
    assert _get_charging_days(zone) == "No days selected"


def test_charging_days_without_config():
    assert _get_charging_days({"setup": {}}) == "Not configured"


# ---------------------------------------------------------------------------
# Every sensor, through a real entity
# ---------------------------------------------------------------------------


# What every sensor must report for ZONE_OFF. The test below is parametrized
# over the production description table, so adding a sensor without adding its
# expected value here fails on that sensor's own case.
OFF_EXPECTATIONS = {
    "charge_level": 3,
    "power": 0.0,
    "pcb_temp": 30.0,
    "target_charge": 100,
    "priority": "Medium",
    "error_code": 1024,  # non-zero on a healthy idle device
    "firmware": "FW: 1.4 / HW: 1.0",
    "charging_slot1": "00:00 - 08:00",
    "charging_slot2": "Disabled",
    "charging_days": "Every day",
}


@pytest.mark.parametrize("key", list(DESCRIPTIONS), ids=str)
def test_sensor_native_value_when_off(key):
    assert key in OFF_EXPECTATIONS, f"sensor {key!r} has no expected value for ZONE_OFF"
    assert build_sensor(ZONE_OFF, key).native_value == OFF_EXPECTATIONS[key]


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("charge_level", 66),
        ("power", 450.0),
        ("pcb_temp", 50.0),
        ("error_code", 0),
    ],
)
def test_sensor_native_value_when_heating(key, expected):
    assert build_sensor(ZONE_HEATING, key).native_value == expected


def test_sensor_value_is_none_when_status_key_absent():
    zone = {**ZONE_OFF, "status": {}}
    assert build_sensor(zone, "charge_level").native_value is None


def test_sensor_unique_id_is_stable():
    sensor = build_sensor(ZONE_OFF, "charge_level")
    assert sensor.unique_id == f"elnur_gabarron_{DEVICE_ID}_{ZONE_ID}_charge_level"


def test_sensor_unavailable_when_zone_drops_out_of_coordinator_data():
    sensor = build_sensor(ZONE_OFF, "charge_level")
    assert sensor.available is True

    sensor.coordinator.data = {}
    assert sensor.available is False


def test_sensor_unavailable_after_a_failed_update():
    # The common case: Socket.IO drops, the coordinator marks the update
    # failed, but the last zone dict is still sitting in .data. The entity has
    # to go unavailable instead of presenting yesterday's temperature as
    # current.
    sensor = build_sensor(ZONE_OFF, "charge_level")
    assert sensor.available is True

    sensor.coordinator.last_update_success = False

    assert sensor.available is False
    # The stale value is still reachable -- availability is the only thing
    # standing between it and the user.
    assert sensor.native_value == 3


def test_sensor_follows_zone_rename():
    sensor = build_sensor(ZONE_OFF, "charge_level")
    sensor.coordinator.data = {ZONE_KEY: {**ZONE_OFF, "name": "Renamed"}}
    assert sensor.zone_name == "Renamed"


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------


async def test_async_setup_entry_creates_every_sensor_for_every_zone():
    from custom_components.elnur_gabarron.const import DOMAIN
    from custom_components.elnur_gabarron.sensor import async_setup_entry

    second_key = f"{DEVICE_ID}_zone3"
    coordinator = MagicMock()
    coordinator.data = {ZONE_KEY: ZONE_OFF, second_key: {**ZONE_OFF, "zone_id": 3, "name": "Test Zone B"}}

    hass = MagicMock()
    entry = MagicMock()
    hass.data = {DOMAIN: {entry.entry_id: coordinator}}
    added = []

    await async_setup_entry(hass, entry, lambda entities: added.extend(entities))

    assert len(added) == 2 * len(SENSOR_DESCRIPTIONS)
    assert len({e.unique_id for e in added}) == len(added)  # no collisions across zones


async def test_async_setup_entry_recovers_device_id_from_the_zone_key():
    # The device id is parsed back out of "<device_id>_zone<n>"; a device id
    # that itself contains an underscore must not be truncated.
    from custom_components.elnur_gabarron.const import DOMAIN
    from custom_components.elnur_gabarron.sensor import async_setup_entry

    odd_device = "dev_with_underscores"
    key = f"{odd_device}_zone2"
    coordinator = MagicMock()
    coordinator.data = {key: {**ZONE_OFF, "zone_id": 2}}

    hass = MagicMock()
    entry = MagicMock()
    hass.data = {DOMAIN: {entry.entry_id: coordinator}}
    added = []

    await async_setup_entry(hass, entry, lambda entities: added.extend(entities))

    assert all(e.unique_id.startswith(f"elnur_gabarron_{odd_device}_2_") for e in added)
