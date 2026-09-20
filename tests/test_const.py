"""Tests for the shared device-info builder.

`build_device_info` is the one place every platform agrees on what device an
entity belongs to. The `identifiers` value in particular is load-bearing: if
its shape changes, Home Assistant treats every entity as belonging to a new
device and silently re-registers it, losing the user's history, area
assignment and customisations. Hence pinning the exact string here.
"""

import pytest

from custom_components.elnur_gabarron.const import DOMAIN, build_device_info

from .fixtures import DEVICE_ID, ZONE_ID, ZONE_OFF


def test_identifier_shape_is_pinned():
    info = build_device_info(ZONE_OFF, DEVICE_ID, ZONE_ID, "Test Zone A")

    assert info["identifiers"] == {(DOMAIN, f"{DEVICE_ID}_zone{ZONE_ID}")}


def test_identifiers_differ_per_zone_on_the_same_device():
    # Two zones of one hub must not collapse into a single HA device.
    first = build_device_info(ZONE_OFF, DEVICE_ID, 2, "A")["identifiers"]
    second = build_device_info(ZONE_OFF, DEVICE_ID, 3, "B")["identifiers"]

    assert first != second


def test_model_includes_both_power_ratings():
    info = build_device_info(ZONE_OFF, DEVICE_ID, ZONE_ID, "Test Zone A")

    assert info["model"] == "Electric Heater 1950W (emitter: 450W)"


def test_model_falls_back_when_factory_options_are_missing():
    info = build_device_info({}, DEVICE_ID, ZONE_ID, "Test Zone A")

    assert info["model"] == "Electric Heater"
    assert info["name"] == "Test Zone A"


def test_suggested_area_prefers_device_name_then_group_name():
    device_named = {"device_name": "Downstairs", "group_name": "Home"}
    group_only = {"group_name": "Home"}

    assert build_device_info(device_named, DEVICE_ID, 2, "A")["suggested_area"] == "Downstairs"
    assert build_device_info(group_only, DEVICE_ID, 2, "A")["suggested_area"] == "Home"
    assert build_device_info({}, DEVICE_ID, 2, "A")["suggested_area"] == ""


def test_iter_resolvable_zones_reads_the_payload():
    from custom_components.elnur_gabarron.const import iter_resolvable_zones

    # The zone key deliberately disagrees with the payload: the payload wins.
    zones = {"whatever_zone9": ZONE_OFF}

    assert list(iter_resolvable_zones(zones)) == [("whatever_zone9", ZONE_OFF, DEVICE_ID, ZONE_ID)]


def test_iter_resolvable_zones_accepts_zone_zero():
    from custom_components.elnur_gabarron.const import iter_resolvable_zones

    # zone_id 0 is falsy but valid; only a missing value is an error.
    zones = {"k": {"device_id": DEVICE_ID, "zone_id": 0}}

    assert [z[3] for z in iter_resolvable_zones(zones)] == [0]


def test_iter_resolvable_zones_skips_one_bad_zone_and_keeps_the_rest():
    from custom_components.elnur_gabarron.const import iter_resolvable_zones

    # zone_id comes from a single node's addr, so one malformed node must not
    # cost the user every healthy zone on the device.
    zones = {
        "d_zone2": {"device_id": DEVICE_ID, "zone_id": 2},
        "d_zoneNone": {"device_id": DEVICE_ID, "zone_id": None},
        "d_zone4": {"device_id": DEVICE_ID, "zone_id": 4},
    }

    assert [z[0] for z in iter_resolvable_zones(zones)] == ["d_zone2", "d_zone4"]


def test_iter_resolvable_zones_raises_only_when_nothing_resolves():
    from homeassistant.exceptions import ConfigEntryNotReady

    from custom_components.elnur_gabarron.const import iter_resolvable_zones

    # device_id is the same value for every zone, so if that is what's missing
    # nothing resolves -- the one case worth failing setup over.
    zones = {
        "a": {"zone_id": 2},
        "b": {"device_id": "", "zone_id": 3},
    }

    with pytest.raises(ConfigEntryNotReady):
        list(iter_resolvable_zones(zones))


def test_iter_resolvable_zones_accepts_an_empty_coordinator():
    from custom_components.elnur_gabarron.const import iter_resolvable_zones

    # A device with no supported zones is a legitimate state, not a reason to
    # retry setup forever.
    assert list(iter_resolvable_zones({})) == []
