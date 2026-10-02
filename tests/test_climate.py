"""Tests for the climate platform's reported state."""

from unittest.mock import MagicMock

from homeassistant.components.climate import HVACMode

from custom_components.elnur_gabarron.climate import ElnurGabarronClimate

from .fixtures import DEVICE_ID, ZONE_HEATING, ZONE_ID, ZONE_KEY, ZONE_OFF


def build_climate(zone: dict) -> ElnurGabarronClimate:
    """Build one climate entity backed by a stub coordinator."""
    coordinator = MagicMock()
    coordinator.data = {ZONE_KEY: zone}
    coordinator.last_update_success = True
    return ElnurGabarronClimate(coordinator, ZONE_KEY, zone, MagicMock(), DEVICE_ID, ZONE_ID)


def test_target_temperature_follows_stemp_when_on():
    assert build_climate(ZONE_HEATING).target_temperature == 20.0


def test_target_temperature_hidden_when_off():
    # The real off payload carries stemp "3.0", below min_temp.
    assert build_climate(ZONE_OFF).target_temperature is None


def test_target_temperature_hidden_right_after_turning_off():
    climate = build_climate(ZONE_HEATING)
    climate._optimistic_hvac_mode = HVACMode.OFF
    assert climate.target_temperature is None


def test_target_temperature_hidden_until_device_confirms_turning_on():
    climate = build_climate(ZONE_OFF)
    climate._optimistic_hvac_mode = HVACMode.HEAT
    assert climate.target_temperature is None


def test_optimistic_target_temperature_wins_while_off():
    # Setting a temperature switches the heater on; show the requested value.
    climate = build_climate(ZONE_OFF)
    climate._optimistic_target_temp = 21.5
    assert climate.target_temperature == 21.5


def test_frost_protection_temperature_attribute():
    assert build_climate(ZONE_OFF).extra_state_attributes == {"frost_protection_temperature": 7.0}
