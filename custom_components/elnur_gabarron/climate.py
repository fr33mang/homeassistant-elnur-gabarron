"""Climate platform for Elnur Gabarron."""
import asyncio
import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .socketio_coordinator import ElnurSocketIOCoordinator
from .const import DOMAIN, MANUFACTURER, MODEL

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Elnur Gabarron climate entities."""
    coordinator: ElnurSocketIOCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Create climate entities for each zone
    # Each zone becomes a separate device in Home Assistant
    entities = []
    for zone_key, zone_data in coordinator.data.items():
        entities.append(ElnurGabarronClimate(coordinator, zone_key, zone_data, entry))
        _LOGGER.debug("Created climate entity for %s", zone_data.get("name", zone_key))

    async_add_entities(entities)
    
    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(update_listener))


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


class ElnurGabarronClimate(CoordinatorEntity, ClimateEntity):
    """Representation of an Elnur Gabarron heater."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO]
    _attr_min_temp = 5.0
    _attr_max_temp = 30.0
    _attr_target_temperature_step = 0.5

    def __init__(
        self,
        coordinator: ElnurSocketIOCoordinator,
        zone_key: str,
        zone_data: dict[str, Any],
        entry: ConfigEntry,
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator)
        
        self._entry = entry
        self._zone_key = zone_key  # Full key like "device_id_zone2"
        
        # Extract device ID and zone ID
        if "_zone" in zone_key:
            self._device_id = zone_key.split("_zone")[0]
            self._zone_id = zone_data.get("zone_id", int(zone_key.split("_zone")[1]))
        else:
            self._device_id = zone_key
            self._zone_id = zone_data.get("zone_id", 3)
        
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_zone{self._zone_id}"
        
        # Optimistic state for immediate UI updates
        self._optimistic_hvac_mode: HVACMode | None = None
        self._optimistic_target_temp: float | None = None
        self._optimistic_hvac_action: HVACAction | None = None

    @property
    def name(self) -> str:
        """Return the name of the entity (dynamic from dev_data)."""
        zone_data = self.zone_data
        zone_name = zone_data.get("name")
        
        if zone_name:
            return zone_name
        else:
            # Fallback if API doesn't provide a name (shouldn't happen normally)
            return f"Heater Zone {self._zone_id}"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information.
        
        Each zone is a separate device in Home Assistant.
        """
        zone_data = self.zone_data
        
        # Get power info from setup if available
        setup = zone_data.get("setup", {})
        factory_opts = setup.get("factory_options", {})
        accumulator_power = factory_opts.get("accumulator_power", "")
        emitter_power = factory_opts.get("emitter_power", "")
        
        # Build model name with power info and location context
        model_parts = [MODEL]
        if accumulator_power:
            model_parts.append(f"{accumulator_power}W")
        if emitter_power:
            model_parts.append(f"(emitter: {emitter_power}W)")
        model_name = " ".join(model_parts)
        
        # Get location context from zone data
        device_name = zone_data.get("device_name", "")
        group_name = zone_data.get("group_name", "")
        
        return {
            "identifiers": {(DOMAIN, f"{self._device_id}_zone{self._zone_id}")},
            "name": self.name,
            "manufacturer": MANUFACTURER,
            "model": model_name,
            "suggested_area": device_name if device_name else group_name,
        }

    @property
    def zone_data(self) -> dict[str, Any]:
        """Get zone data from coordinator."""
        return self.coordinator.data.get(self._zone_key, {})

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        status = self.zone_data.get("status", {})
        # mtemp = measured temperature (current)
        temp_str = status.get("mtemp")
        if temp_str:
            try:
                return float(temp_str)
            except (ValueError, TypeError):
                return None
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        # Return optimistic value if set (immediate UI response)
        if self._optimistic_target_temp is not None:
            return self._optimistic_target_temp
            
        status = self.zone_data.get("status", {})
        # stemp = set temperature (target)
        temp_str = status.get("stemp")
        if temp_str:
            try:
                return float(temp_str)
            except (ValueError, TypeError):
                return None
        return None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        # Return optimistic value if set (immediate UI response)
        if self._optimistic_hvac_mode is not None:
            return self._optimistic_hvac_mode
            
        status = self.zone_data.get("status", {})
        # mode = "off", "auto", "modified_auto"
        mode = status.get("mode", "").lower()
        
        # Map API modes to Home Assistant HVAC modes
        if mode == "off":
            return HVACMode.OFF
        elif mode == "auto":
            return HVACMode.AUTO  # Follow internal schedule
        elif mode == "modified_auto":
            return HVACMode.HEAT  # Manual temperature control
        else:
            # Default to AUTO for unknown modes
            return HVACMode.AUTO

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return current HVAC action (what the device is actually doing)."""
        # Return optimistic value if set (immediate UI response)
        if self._optimistic_hvac_action is not None:
            return self._optimistic_hvac_action
            
        status = self.zone_data.get("status", {})
        mode = status.get("mode", "").lower()
        heating = status.get("heating", False)
        
        # Map device state to HVAC action
        if mode == "off":
            return HVACAction.OFF
        elif heating:
            # Device is actively heating (element is hot)
            return HVACAction.HEATING
        else:
            # Device is on but not actively heating (maintaining temperature)
            return HVACAction.IDLE

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        _LOGGER.debug("Setting temperature to %s°C (manual control)", temperature)
        
        # Get current temperature to predict HVAC action
        current_temp = self.current_temperature or 20.0  # Default if unknown
        
        # Optimistically update the UI immediately
        self._optimistic_target_temp = temperature
        # Setting temperature switches to HEAT mode (manual control)
        self._optimistic_hvac_mode = HVACMode.HEAT
        
        # Smart prediction: If target is significantly higher than current, device will heat
        temp_difference = temperature - current_temp
        if temp_difference > 1.0:
            # Target temp is more than 1°C higher → device will start heating
            self._optimistic_hvac_action = HVACAction.HEATING
            _LOGGER.debug(
                "Predicting HEATING (target %s°C > current %s°C)",
                temperature,
                current_temp,
            )
        else:
            # Target temp is close to or below current → device will be idle
            self._optimistic_hvac_action = HVACAction.IDLE
            _LOGGER.debug(
                "Predicting IDLE (target %s°C ~ current %s°C)",
                temperature,
                current_temp,
            )
        
        self.async_write_ha_state()
        _LOGGER.debug("UI updated optimistically: %s°C in HEAT mode", temperature)
        
        # Set temperature with mode "modified_auto" (manual control)
        success = await self.coordinator.api.set_temperature(
            self._device_id, 
            temperature, 
            self._zone_id,
            mode="modified_auto"  # Manual temperature control
        )
        
        if success:
            _LOGGER.debug("Temperature command sent, waiting for API to confirm...")
            
            # Clear optimistic state and refresh after API has time to process
            async def clear_and_refresh():
                await asyncio.sleep(3)
                self._optimistic_target_temp = None
                self._optimistic_hvac_mode = None
                self._optimistic_hvac_action = None
                await self.coordinator.async_request_refresh()
            
            async def additional_refresh():
                await asyncio.sleep(6)
                await self.coordinator.async_request_refresh()
            
            # Schedule delayed refreshes
            self.hass.async_create_task(clear_and_refresh())
            self.hass.async_create_task(additional_refresh())
        else:
            _LOGGER.error("Failed to set temperature, reverting UI")
            # Revert optimistic state on failure
            self._optimistic_target_temp = None
            self._optimistic_hvac_mode = None
            self._optimistic_hvac_action = None
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new HVAC mode."""
        _LOGGER.debug("Setting HVAC mode to %s", hvac_mode)
        
        # Optimistically update the UI immediately (mode and action)
        self._optimistic_hvac_mode = hvac_mode
        
        # Set optimistic action based on mode and temperature difference
        if hvac_mode == HVACMode.OFF:
            self._optimistic_hvac_action = HVACAction.OFF
        else:
            # For HEAT/AUTO, check if device will need to heat
            current_temp = self.current_temperature or 20.0
            target_temp = self.target_temperature or current_temp
            temp_difference = target_temp - current_temp
            
            if temp_difference > 1.0:
                # Target is significantly higher → will start heating
                self._optimistic_hvac_action = HVACAction.HEATING
                _LOGGER.debug(
                    "Predicting HEATING (target %s°C > current %s°C)",
                    target_temp,
                    current_temp,
                )
            else:
                # Target is close or lower → will be idle
                self._optimistic_hvac_action = HVACAction.IDLE
                _LOGGER.debug(
                    "Predicting IDLE (target %s°C ~ current %s°C)",
                    target_temp,
                    current_temp,
                )
        
        self.async_write_ha_state()
        _LOGGER.debug("UI updated optimistically to %s", hvac_mode)
        
        # Map Home Assistant modes to API modes
        if hvac_mode == HVACMode.OFF:
            success = await self.coordinator.api.set_mode(self._device_id, "off", self._zone_id)
        elif hvac_mode == HVACMode.AUTO:
            # Follow internal schedule
            success = await self.coordinator.api.set_mode(self._device_id, "auto", self._zone_id)
        elif hvac_mode == HVACMode.HEAT:
            # Manual control - set to modified_auto
            success = await self.coordinator.api.set_mode(self._device_id, "modified_auto", self._zone_id)
        else:
            _LOGGER.warning("Unsupported HVAC mode: %s", hvac_mode)
            return

        if success:
            _LOGGER.debug("HVAC command sent, waiting for API to confirm...")
            
            # Keep optimistic state for longer to avoid UI flicker
            # Clear optimistic state and refresh after API has time to process
            async def clear_and_refresh():
                await asyncio.sleep(3)
                self._optimistic_hvac_mode = None
                self._optimistic_hvac_action = None
                await self.coordinator.async_request_refresh()
            
            async def additional_refresh():
                await asyncio.sleep(6)
                await self.coordinator.async_request_refresh()
            
            # Schedule delayed refreshes
            self.hass.async_create_task(clear_and_refresh())
            self.hass.async_create_task(additional_refresh())
        else:
            _LOGGER.error("Failed to set HVAC mode, reverting UI")
            # Revert optimistic state on failure
            self._optimistic_hvac_mode = None
            self._optimistic_hvac_action = None
            self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self._zone_key in self.coordinator.data

