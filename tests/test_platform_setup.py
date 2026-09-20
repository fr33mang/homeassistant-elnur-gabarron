"""Setup-path tests for the climate and number platforms.

Neither platform has real coverage yet, but both were changed when zone
identity moved out of key-parsing and into the shared resolver — climate most
of all, where a magic zone_id default disappeared and the failure path moved
out of the entity constructor. Shipping that untested is the exact thing this
work exists to prevent, so the setup path is covered here; the rest of both
platforms follows separately.
"""

from unittest.mock import MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.elnur_gabarron.climate import async_setup_entry as climate_setup
from custom_components.elnur_gabarron.const import DOMAIN
from custom_components.elnur_gabarron.number import async_setup_entry as number_setup

from .fixtures import DEVICE_ID, ZONE_ID, ZONE_KEY, ZONE_OFF

PLATFORMS = [pytest.param(climate_setup, 1, id="climate"), pytest.param(number_setup, 3, id="number")]


async def run_setup(setup, zones: dict) -> list:
    coordinator = MagicMock()
    coordinator.data = zones
    coordinator.last_update_success = True

    hass = MagicMock()
    entry = MagicMock()
    hass.data = {DOMAIN: {entry.entry_id: coordinator}}
    added: list = []

    await setup(hass, entry, lambda entities: added.extend(entities))
    return added


@pytest.mark.parametrize(("setup", "per_zone"), PLATFORMS)
async def test_creates_entities_for_each_zone(setup, per_zone):
    added = await run_setup(setup, {ZONE_KEY: ZONE_OFF, f"{DEVICE_ID}_zone4": {**ZONE_OFF, "zone_id": 4}})

    assert len(added) == 2 * per_zone
    assert len({e.unique_id for e in added}) == len(added)


@pytest.mark.parametrize(("setup", "per_zone"), PLATFORMS)
async def test_identity_comes_from_the_payload_not_the_zone_key(setup, per_zone):
    # climate used to read the zone id out of the key with int(split(...)[1])
    # and fall back to a hardcoded 3; both platforms now read the payload, so
    # the key is free to disagree.
    added = await run_setup(setup, {"nonsense_zone99": {**ZONE_OFF, "device_id": "dev_zone_x", "zone_id": 2}})

    assert len(added) == per_zone
    assert all("dev_zone_x" in e.unique_id for e in added)
    assert not any("99" in e.unique_id for e in added)


@pytest.mark.parametrize(("setup", "per_zone"), PLATFORMS)
async def test_skips_a_broken_zone_and_keeps_the_healthy_one(setup, per_zone):
    added = await run_setup(
        setup,
        {
            ZONE_KEY: ZONE_OFF,
            f"{DEVICE_ID}_zoneBroken": {**ZONE_OFF, "zone_id": None},
        },
    )

    assert len(added) == per_zone
    assert not any("Broken" in e.unique_id for e in added)


@pytest.mark.parametrize(("setup", "per_zone"), PLATFORMS)
async def test_refuses_when_no_zone_resolves(setup, per_zone):
    zones = {ZONE_KEY: {k: v for k, v in ZONE_OFF.items() if k != "device_id"}}

    with pytest.raises(ConfigEntryNotReady):
        await run_setup(setup, zones)


async def test_climate_unique_id_format_is_unchanged():
    # Pinned because unique_id is persisted to the entity registry: a change
    # here silently re-registers every climate entity and loses the user's
    # history and customisations. climate's format differs from the other
    # platforms' -- it has no trailing description key.
    added = await run_setup(climate_setup, {ZONE_KEY: ZONE_OFF})

    assert added[0].unique_id == f"{DOMAIN}_{DEVICE_ID}_zone{ZONE_ID}"
