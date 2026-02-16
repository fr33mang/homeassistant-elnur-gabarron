"""Number platform for Elnur Gabarron."""

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .socketio_coordinator import ElnurSocketIOCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Elnur Gabarron number entities."""
    coordinator: ElnurSocketIOCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Create number entities for each zone
    entities = []
    for zone_key, zone_data in coordinator.data.items():
        device_id = zone_data.get("device_id")
        zone_id = zone_data.get("zone_id")
        zone_name = zone_data.get("name", f"Zone {zone_id}")

        # Add temperature setting numbers in desired order
        entities.extend(
            [
                ElnurGabarronAntiFrostTempNumber(coordinator, zone_key, device_id, zone_id, zone_name),
                ElnurGabarronEcoTempNumber(coordinator, zone_key, device_id, zone_id, zone_name),
                ElnurGabarronComfortTempNumber(coordinator, zone_key, device_id, zone_id, zone_name),
            ]
        )

    async_add_entities(entities)
    _LOGGER.info("Added %s Elnur Gabarron number entities", len(entities))


class ElnurGabarronScheduleTemperatureBase(CoordinatorEntity, NumberEntity):
    """Base class for Elnur Gabarron number entities."""

    status_key: str
    name_suffix: str
    setting_suffix: str
    icon_suffix: str

    def __init__(
        self,
        coordinator: ElnurSocketIOCoordinator,
        zone_key: str,
        device_id: str,
        zone_id: int,
        zone_name: str,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._zone_key = zone_key
        self._device_id = device_id
        self._zone_id = zone_id
        self._initial_zone_name = zone_name

        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_{self.status_key}_setting"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_icon = f"mdi:{self.icon_suffix}"
        self._attr_mode = NumberMode.BOX
        self._attr_native_min_value = 7.0
        self._attr_native_max_value = 30.0
        self._attr_native_step = 0.5
        self._attr_entity_category = EntityCategory.CONFIG

    @property
    def zone_data(self) -> dict[str, Any]:
        """Get zone data from coordinator."""
        return self.coordinator.data.get(self._zone_key, {})

    @property
    def zone_name(self) -> str:
        """Get the current zone name (dynamic from dev_data)."""
        zone_data = self.zone_data
        current_name = zone_data.get("name")

        if current_name:
            return current_name

        return self._initial_zone_name

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information - must match climate/sensor entities."""
        zone_data = self.zone_data
        setup = zone_data.get("setup", {})
        factory_opts = setup.get("factory_options", {})
        accumulator_power = factory_opts.get("accumulator_power", "")
        emitter_power = factory_opts.get("emitter_power", "")

        model_parts = [MODEL]
        if accumulator_power:
            model_parts.append(f"{accumulator_power}W")
        if emitter_power:
            model_parts.append(f"{emitter_power}W")

        # Get location context from zone data
        device_name = zone_data.get("device_name", "")
        group_name = zone_data.get("group_name", "")

        return {
            "identifiers": {(DOMAIN, self._zone_key)},
            "name": self.zone_name,
            "manufacturer": MANUFACTURER,
            "model": " ".join(model_parts),
            "suggested_area": device_name if device_name else group_name,
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self._zone_key in self.coordinator.data

    @property
    def name(self) -> str:
        """Return the name of the number entity."""
        return f"{self.zone_name} {self.name_suffix}"

    @property
    def native_value(self) -> float | None:
        """Return the temperature setting"""
        return self._get_temp_from_status()

    async def async_set_native_value(self, value: float) -> None:
        """Set new temperature for self.status_key."""
        await self._set_temp_value(value=value)

    def _get_temp_from_status(self) -> float | None:
        """Extract a temperature value from zone status for self.status_key."""
        status = self.zone_data.get("status", {})
        temp = status.get(self.status_key)
        if temp is not None:
            try:
                return float(temp)
            except (ValueError, TypeError):
                return None
        return None

    async def _set_temp_value(self, value: float) -> None:
        """Set a temperature value via API and optimistically update state."""
        _LOGGER.info(
            "Setting %s temperature for %s zone %s to %s°C",
            self.status_key,
            self._device_id,
            self._zone_id,
            value,
        )
        try:
            control_data = {self.status_key: str(value), "units": "C"}
            success = await self.coordinator.api.set_control(self._device_id, control_data, self._zone_id)
            if success:
                if self._zone_key in self.coordinator.data:
                    status = self.coordinator.data[self._zone_key].get("status", {})
                    status[self.status_key] = str(value)
                    self.async_write_ha_state()
                    _LOGGER.info(
                        "Successfully set %s temperature to %s°C",
                        self.status_key,
                        value,
                    )
                else:
                    _LOGGER.error("Failed to set %s temperature", self.status_key)
        except Exception as err:
            _LOGGER.error("Error setting %s temperature: %s", self.status_key, err)


class ElnurGabarronEcoTempNumber(ElnurGabarronScheduleTemperatureBase):
    """Economy temperature setting number."""

    status_key = "eco_temp"
    name_suffix = "Economy Temperature"
    icon_suffix = "leaf"


class ElnurGabarronComfortTempNumber(ElnurGabarronScheduleTemperatureBase):
    """Comfort temperature setting number."""

    status_key = "comf_temp"
    name_suffix = "Comfort Temperature"
    icon_suffix = "sofa"


class ElnurGabarronAntiFrostTempNumber(ElnurGabarronScheduleTemperatureBase):
    """Anti-frost temperature setting number."""

    status_key = "ice_temp"
    name_suffix = "Anti-Frost Temperature"
    icon_suffix = "snowflake-alert"
