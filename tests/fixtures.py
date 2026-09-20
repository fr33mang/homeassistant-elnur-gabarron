"""Shared zone fixtures for entity tests.

`ZONE_OFF` is a real `dev_data` payload, so the tests exercise what the server
actually sends rather than a tidied-up idea of it: string-typed numbers
("0", "23.7"), an int-typed `locked` sitting among genuine booleans, and a
non-zero `error_code` on a perfectly healthy idle heater.

`ZONE_HEATING` is that payload adjusted to a plausible running state. It has
not been captured from a device, so treat its combination of flags as
believable rather than authoritative.

`ZONE_ALL_FLAGS_ON` is deliberately synthetic: every binary flag is true at
once, which no real heater reports (window-open mode stops heating). It exists
so the binary sensor tests can assert the true case for every key in one sweep
— don't build behavioural tests on it.

Identifying values are replaced: device/group/zone names and the device id are
synthetic, the hardware `uid` is dropped, and the weekly `prog` schedule — a
record of when someone is home — is left out entirely. Nothing reads it.
"""

import copy

DEVICE_ID = "0011223344556677aa"
ZONE_ID = 2
ZONE_KEY = f"{DEVICE_ID}_zone{ZONE_ID}"

# A heater that has been switched off for a long time: cold core, no draw,
# error_code carrying a set bit that is not a fault (see docs/socketio-protocol.md).
ZONE_OFF = {
    "zone_id": ZONE_ID,
    "device_id": DEVICE_ID,
    "device_name": "Test Device",
    "group_id": "test-group",
    "group_name": "Test Home",
    "name": "Test Zone A",
    "status": {
        "sync_status": "ok",
        "mode": "off",
        "heating": False,
        "charging": False,
        "ice_temp": "7.0",
        "eco_temp": "17.5",
        "comf_temp": "20.0",
        "units": "C",
        "stemp": "3.0",
        "mtemp": "23.7",
        "power": "0",
        "locked": 0,
        "presence": False,
        "window_open": False,
        "true_radiant_active": False,
        "pcb_temp": 30,
        "charge_level": 3,
        "target_charge_per": 100,
        "error_code": 1024,
        "using_extra_nrg": False,
        "venting": False,
    },
    "setup": {
        "sync_status": "ok",
        "control_mode": 4,
        "units": "C",
        "offset": "0.0",
        "priority": "medium",
        "away_mode": 0,
        "away_offset": "0.0",
        "window_mode_enabled": False,
        "true_radiant_enabled": True,
        "init_charge_per": 100,
        "over_charge_protection": 2,
        "charging_conf": {
            "slot_1": {"start": 0, "end": 480},
            "slot_2": {"start": 0, "end": 0},
            "active_days": [1, 1, 1, 1, 1, 1, 1],
        },
        "factory_options": {
            "model": 1,
            "ui_mode": 0,
            "version": 0,
            "accumulator_power": "1950",
            "emitter_power": "450",
            "dst_config": 5,
        },
        "power_level_limit": 3,
    },
    "version": {"hw_version": "1.0", "fw_version": "1.4", "pid": "0b20"},
}


def _variant(**status_overrides: object) -> dict:
    """Deep-copy ZONE_OFF and override status fields.

    Deep, not shallow: a shallow spread would leave `setup` and `version`
    pointing at the very same dicts as ZONE_OFF, so one test mutating a nested
    value would break others depending on execution order.
    """
    zone = copy.deepcopy(ZONE_OFF)
    zone["status"].update(status_overrides)
    return zone


# The same heater mid-session: warming the room, drawing power, part charged.
# Plausible rather than captured — see the module docstring.
ZONE_HEATING = _variant(
    mode="auto",
    heating=True,
    charging=False,
    mtemp="21.4",
    stemp="20.0",
    power="450",
    pcb_temp=50,
    charge_level=66,
    error_code=0,
    presence=True,
    true_radiant_active=True,
)

# Synthetic: every binary flag true at once so the binary sensor tests can
# sweep the true case. A real device never reports this combination.
ZONE_ALL_FLAGS_ON = _variant(
    heating=True,
    charging=True,
    window_open=True,
    presence=True,
    true_radiant_active=True,
    using_extra_nrg=True,
)
