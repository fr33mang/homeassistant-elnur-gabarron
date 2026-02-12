"""Number platform for Elnur Gabarron."""
import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from .socketio_coordinator import ElnurSocketIOCoordinator
from .const import DOMAIN, MANUFACTURER, MODEL

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
        entities.extend([
            ElnurGabarronAntiFrostTempNumber(coordinator, zone_key, device_id, zone_id, zone_name),
            ElnurGabarronEcoTempNumber(coordinator, zone_key, device_id, zone_id, zone_name),
            ElnurGabarronComfortTempNumber(coordinator, zone_key, device_id, zone_id, zone_name),
        ])

    async_add_entities(entities)
    _LOGGER.info("Added %s Elnur Gabarron number entities", len(entities))


class ElnurGabarronNumberBase(CoordinatorEntity, NumberEntity):
    """Base class for Elnur Gabarron number entities."""

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


class ElnurGabarronEcoTempNumber(ElnurGabarronNumberBase):
    """Economy temperature setting number."""

    def __init__(
        self,
        coordinator: ElnurSocketIOCoordinator,
        zone_key: str,
        device_id: str,
        zone_id: int,
        zone_name: str,
    ) -> None:
        """Initialize the eco temp number."""
        super().__init__(coordinator, zone_key, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_eco_temp_setting"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_icon = "mdi:leaf"
        self._attr_mode = NumberMode.BOX
        self._attr_native_min_value = 7.0
        self._attr_native_max_value = 30.0
        self._attr_native_step = 0.5
        self._attr_entity_category = EntityCategory.CONFIG
    
    @property
    def name(self) -> str:
        """Return the name of the number entity."""
        return f"{self.zone_name} Economy Temperature"

    @property
    def native_value(self) -> float | None:
        """Return the economy temperature setting."""
        status = self.zone_data.get("status", {})
        temp = status.get("eco_temp")
        if temp is not None:
            try:
                return float(temp)
            except (ValueError, TypeError):
                return None
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set new economy temperature."""
        _LOGGER.info("Setting economy temperature for %s zone %s to %s°C", self._device_id, self._zone_id, value)
        
        try:
            # Send control command to API
            control_data = {
                "eco_temp": str(value),
                "units": "C"
            }
            success = await self.coordinator.api.set_control(
                self._device_id, 
                control_data, 
                self._zone_id
            )
            
            if success:
                # Optimistically update the state
                if self._zone_key in self.coordinator.data:
                    status = self.coordinator.data[self._zone_key].get("status", {})
                    status["eco_temp"] = str(value)
                    self.async_write_ha_state()
                    _LOGGER.info("Successfully set economy temperature to %s°C", value)
                else:
                    _LOGGER.error("Failed to set economy temperature")
        except Exception as err:
            _LOGGER.error("Error setting economy temperature: %s", err)


class ElnurGabarronComfortTempNumber(ElnurGabarronNumberBase):
    """Comfort temperature setting number."""

    def __init__(
        self,
        coordinator: ElnurSocketIOCoordinator,
        zone_key: str,
        device_id: str,
        zone_id: int,
        zone_name: str,
    ) -> None:
        """Initialize the comfort temp number."""
        super().__init__(coordinator, zone_key, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_comfort_temp_setting"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_icon = "mdi:sofa"
        self._attr_mode = NumberMode.BOX
        self._attr_native_min_value = 7.0
        self._attr_native_max_value = 30.0
        self._attr_native_step = 0.5
        self._attr_entity_category = EntityCategory.CONFIG
    
    @property
    def name(self) -> str:
        """Return the name of the number entity."""
        return f"{self.zone_name} Comfort Temperature"

    @property
    def native_value(self) -> float | None:
        """Return the comfort temperature setting."""
        status = self.zone_data.get("status", {})
        temp = status.get("comf_temp")
        if temp is not None:
            try:
                return float(temp)
            except (ValueError, TypeError):
                return None
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set new comfort temperature."""
        _LOGGER.info("Setting comfort temperature for %s zone %s to %s°C", self._device_id, self._zone_id, value)
        
        try:
            # Send control command to API
            control_data = {
                "comf_temp": str(value),
                "units": "C"
            }
            success = await self.coordinator.api.set_control(
                self._device_id, 
                control_data, 
                self._zone_id
            )
            
            if success:
                # Optimistically update the state
                if self._zone_key in self.coordinator.data:
                    status = self.coordinator.data[self._zone_key].get("status", {})
                    status["comf_temp"] = str(value)
                    self.async_write_ha_state()
                    _LOGGER.info("Successfully set comfort temperature to %s°C", value)
                else:
                    _LOGGER.error("Failed to set comfort temperature")
        except Exception as err:
            _LOGGER.error("Error setting comfort temperature: %s", err)


class ElnurGabarronAntiFrostTempNumber(ElnurGabarronNumberBase):
    """Anti-frost temperature setting number."""

    def __init__(
        self,
        coordinator: ElnurSocketIOCoordinator,
        zone_key: str,
        device_id: str,
        zone_id: int,
        zone_name: str,
    ) -> None:
        """Initialize the anti-frost temp number."""
        super().__init__(coordinator, zone_key, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_antifrost_temp_setting"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_icon = "mdi:snowflake-alert"
        self._attr_mode = NumberMode.BOX
        self._attr_native_min_value = 5.0
        self._attr_native_max_value = 15.0
        self._attr_native_step = 0.5
        self._attr_entity_category = EntityCategory.CONFIG
    
    @property
    def name(self) -> str:
        """Return the name of the number entity."""
        return f"{self.zone_name} Anti-Frost Temperature"

    @property
    def native_value(self) -> float | None:
        """Return the anti-frost temperature setting."""
        status = self.zone_data.get("status", {})
        temp = status.get("ice_temp")
        if temp is not None:
            try:
                return float(temp)
            except (ValueError, TypeError):
                return None
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set new anti-frost temperature."""
        _LOGGER.info("Setting anti-frost temperature for %s zone %s to %s°C", self._device_id, self._zone_id, value)
        
        try:
            # Send control command to API
            control_data = {
                "ice_temp": str(value),
                "units": "C"
            }
            success = await self.coordinator.api.set_control(
                self._device_id, 
                control_data, 
                self._zone_id
            )
            
            if success:
                # Optimistically update the state
                if self._zone_key in self.coordinator.data:
                    status = self.coordinator.data[self._zone_key].get("status", {})
                    status["ice_temp"] = str(value)
                    self.async_write_ha_state()
                    _LOGGER.info("Successfully set anti-frost temperature to %s°C", value)
                else:
                    _LOGGER.error("Failed to set anti-frost temperature")
        except Exception as err:
            _LOGGER.error("Error setting anti-frost temperature: %s", err)
