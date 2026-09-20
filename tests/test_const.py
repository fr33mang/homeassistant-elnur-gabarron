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


def test_resolve_zone_identity_reads_the_payload():
    from custom_components.elnur_gabarron.const import resolve_zone_identity

    # The zone key deliberately disagrees with the payload: the payload wins.
    assert resolve_zone_identity("whatever_zone9", ZONE_OFF) == (DEVICE_ID, ZONE_ID)


def test_resolve_zone_identity_accepts_zone_zero():
    from custom_components.elnur_gabarron.const import resolve_zone_identity

    # zone_id 0 is falsy but valid; only a missing value is an error.
    assert resolve_zone_identity("k", {"device_id": DEVICE_ID, "zone_id": 0}) == (DEVICE_ID, 0)


def test_resolve_zone_identity_raises_on_incomplete_data():
    from homeassistant.exceptions import ConfigEntryNotReady

    from custom_components.elnur_gabarron.const import resolve_zone_identity

    for broken in ({}, {"device_id": DEVICE_ID}, {"zone_id": 2}, {"device_id": "", "zone_id": 2}):
        with pytest.raises(ConfigEntryNotReady):
            resolve_zone_identity("zone-key", broken)
