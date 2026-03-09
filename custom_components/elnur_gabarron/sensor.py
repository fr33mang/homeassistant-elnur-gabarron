"""Sensor platform for Elnur Gabarron."""

import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
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
    """Set up Elnur Gabarron sensor entities."""
    coordinator: ElnurSocketIOCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Create sensor entities for each zone
    entities = []
    for zone_key, zone_data in coordinator.data.items():
        zone_id = zone_data.get("zone_id")

        # Extract actual device ID (without _zoneX suffix)
        if "_zone" in zone_key:
            actual_device_id = zone_key.split("_zone")[0]
        else:
            actual_device_id = zone_key

        # Get zone name from data or use generic fallback
        zone_name = zone_data.get("name", f"Heater Zone {zone_id}")

        # Add sensors for this zone
        entities.extend(
            [
                ElnurGabarronChargeLevelSensor(coordinator, zone_key, actual_device_id, zone_id, zone_name),
                ElnurGabarronPowerSensor(coordinator, zone_key, actual_device_id, zone_id, zone_name),
                ElnurGabarronPCBTempSensor(coordinator, zone_key, actual_device_id, zone_id, zone_name),
                ElnurGabarronTargetChargeSensor(coordinator, zone_key, actual_device_id, zone_id, zone_name),
                ElnurGabarronPrioritySensor(coordinator, zone_key, actual_device_id, zone_id, zone_name),
                ElnurGabarronErrorCodeSensor(coordinator, zone_key, actual_device_id, zone_id, zone_name),
                ElnurGabarronFirmwareVersionSensor(coordinator, zone_key, actual_device_id, zone_id, zone_name),
                ElnurGabarronChargingSlot1Sensor(coordinator, zone_key, actual_device_id, zone_id, zone_name),
                ElnurGabarronChargingSlot2Sensor(coordinator, zone_key, actual_device_id, zone_id, zone_name),
                ElnurGabarronChargingDaysSensor(coordinator, zone_key, actual_device_id, zone_id, zone_name),
            ]
        )
        _LOGGER.debug("Created sensors for %s", zone_name)

    async_add_entities(entities)
    _LOGGER.debug("Added %s Elnur Gabarron sensor entities", len(entities))


class ElnurGabarronSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Elnur Gabarron sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ElnurSocketIOCoordinator,
        zone_key: str,
        device_id: str,
        zone_id: int,
        zone_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._zone_key = zone_key  # Full key like "device_id_zone2"
        self._device_id = device_id
        self._zone_id = zone_id
        self._initial_zone_name = zone_name  # Fallback initial name

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

        # Fallback to initial name
        return self._initial_zone_name

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information.

        Each zone is a separate device - must match climate entity device_info.
        """
        zone_data = self.zone_data
        setup = zone_data.get("setup", {})
        factory_opts = setup.get("factory_options", {})
        accumulator_power = factory_opts.get("accumulator_power", "")
        emitter_power = factory_opts.get("emitter_power", "")

        model_parts = [MODEL]
        if accumulator_power:
            model_parts.append(f"{accumulator_power}W")
        if emitter_power:
            model_parts.append(f"(emitter: {emitter_power}W)")

        device_name = zone_data.get("device_name", "")
        group_name = zone_data.get("group_name", "")

        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._device_id}_zone{self._zone_id}")},
            name=self.zone_name,
            manufacturer=MANUFACTURER,
            model=" ".join(model_parts),
            suggested_area=device_name or group_name,
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self._zone_key in self.coordinator.data


class ElnurGabarronChargeLevelSensor(ElnurGabarronSensorBase):
    """Charge level sensor for Elnur Gabarron heater."""

    def __init__(self, coordinator, full_device_id, device_id, zone_id, zone_name):
        """Initialize the charge level sensor."""
        super().__init__(coordinator, full_device_id, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_charge_level"
        self._attr_name = "Charge Level"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:battery-charging"

    @property
    def native_value(self) -> int | None:
        """Return the charge level."""
        status = self.zone_data.get("status", {})
        charge_level = status.get("charge_level")
        if charge_level is not None:
            try:
                return int(charge_level)
            except (ValueError, TypeError):
                return None
        return None


class ElnurGabarronPowerSensor(ElnurGabarronSensorBase):
    """Power consumption sensor for Elnur Gabarron heater."""

    def __init__(self, coordinator, full_device_id, device_id, zone_id, zone_name):
        """Initialize the power sensor."""
        super().__init__(coordinator, full_device_id, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_power"
        self._attr_name = "Power"
        self._attr_native_unit_of_measurement = UnitOfPower.WATT
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:lightning-bolt"

    @property
    def native_value(self) -> float | None:
        """Return the power consumption."""
        status = self.zone_data.get("status", {})
        power = status.get("power")
        if power is not None:
            try:
                return float(power)
            except (ValueError, TypeError):
                return None
        return None


class ElnurGabarronPCBTempSensor(ElnurGabarronSensorBase):
    """PCB temperature sensor for Elnur Gabarron heater."""

    def __init__(self, coordinator, full_device_id, device_id, zone_id, zone_name):
        """Initialize the PCB temperature sensor."""
        super().__init__(coordinator, full_device_id, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_pcb_temp"
        self._attr_name = "PCB Temperature"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:thermometer"
        self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> float | None:
        """Return the PCB temperature."""
        status = self.zone_data.get("status", {})
        pcb_temp = status.get("pcb_temp")
        if pcb_temp is not None:
            try:
                return float(pcb_temp)
            except (ValueError, TypeError):
                return None
        return None


class ElnurGabarronTargetChargeSensor(ElnurGabarronSensorBase):
    """Target charge percentage sensor."""

    def __init__(self, coordinator, full_device_id, device_id, zone_id, zone_name):
        """Initialize the target charge sensor."""
        super().__init__(coordinator, full_device_id, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_target_charge"
        self._attr_name = "Target Charge"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_icon = "mdi:battery-arrow-up"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        """Return the target charge percentage."""
        status = self.zone_data.get("status", {})
        target = status.get("target_charge_per")
        if target is not None:
            try:
                return int(target)
            except (ValueError, TypeError):
                return None
        return None


class ElnurGabarronPrioritySensor(ElnurGabarronSensorBase):
    """Heating priority sensor."""

    def __init__(self, coordinator, full_device_id, device_id, zone_id, zone_name):
        """Initialize the priority sensor."""
        super().__init__(coordinator, full_device_id, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_priority"
        self._attr_name = "Priority"
        self._attr_icon = "mdi:priority-high"
        self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> str | None:
        """Return the heating priority setting."""
        setup = self.zone_data.get("setup", {})
        priority = setup.get("priority")
        if priority:
            return priority.capitalize()
        return None


class ElnurGabarronErrorCodeSensor(ElnurGabarronSensorBase):
    """Error code sensor for diagnostics."""

    def __init__(self, coordinator, full_device_id, device_id, zone_id, zone_name):
        """Initialize the error code sensor."""
        super().__init__(coordinator, full_device_id, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_error_code"
        self._attr_name = "Error Code"
        self._attr_icon = "mdi:alert-circle"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> int | None:
        """Return the error code."""
        status = self.zone_data.get("status", {})
        error_code = status.get("error_code")
        if error_code is not None:
            try:
                return int(error_code)
            except (ValueError, TypeError):
                return None
        return None


class ElnurGabarronFirmwareVersionSensor(ElnurGabarronSensorBase):
    """Firmware version sensor."""

    def __init__(self, coordinator, full_device_id, device_id, zone_id, zone_name):
        """Initialize the firmware version sensor."""
        super().__init__(coordinator, full_device_id, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_firmware"
        self._attr_name = "Firmware Version"
        self._attr_icon = "mdi:chip"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> str | None:
        """Return the firmware version."""
        version = self.zone_data.get("version", {})
        fw_version = version.get("fw_version")
        hw_version = version.get("hw_version")

        if fw_version and hw_version:
            return f"FW: {fw_version} / HW: {hw_version}"
        elif fw_version:
            return f"FW: {fw_version}"
        elif hw_version:
            return f"HW: {hw_version}"
        return None


def _minutes_to_time(minutes: int) -> str:
    """Convert minutes from midnight to HH:MM format."""
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"


class ElnurGabarronChargingSlot1Sensor(ElnurGabarronSensorBase):
    """Charging slot 1 schedule sensor."""

    def __init__(self, coordinator, full_device_id, device_id, zone_id, zone_name):
        """Initialize the charging slot 1 sensor."""
        super().__init__(coordinator, full_device_id, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_charging_slot1"
        self._attr_name = "Charging Slot 1"
        self._attr_icon = "mdi:timer"

    @property
    def native_value(self) -> str | None:
        """Return the charging slot 1 schedule."""
        setup = self.zone_data.get("setup", {})
        charging_conf = setup.get("charging_conf", {})
        slot_1 = charging_conf.get("slot_1", {})

        start = slot_1.get("start", 0)
        end = slot_1.get("end", 0)

        # If start == end == 0, slot is disabled
        if start == 0 and end == 0:
            return "Disabled"

        # If end > start, it's a valid time range
        if end > start:
            return f"{_minutes_to_time(start)} - {_minutes_to_time(end)}"

        return "Not configured"


class ElnurGabarronChargingSlot2Sensor(ElnurGabarronSensorBase):
    """Charging slot 2 schedule sensor."""

    def __init__(self, coordinator, full_device_id, device_id, zone_id, zone_name):
        """Initialize the charging slot 2 sensor."""
        super().__init__(coordinator, full_device_id, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_charging_slot2"
        self._attr_name = "Charging Slot 2"
        self._attr_icon = "mdi:timer"

    @property
    def native_value(self) -> str | None:
        """Return the charging slot 2 schedule."""
        setup = self.zone_data.get("setup", {})
        charging_conf = setup.get("charging_conf", {})
        slot_2 = charging_conf.get("slot_2", {})

        start = slot_2.get("start", 0)
        end = slot_2.get("end", 0)

        # If start == end == 0, slot is disabled
        if start == 0 and end == 0:
            return "Disabled"

        # If end > start, it's a valid time range
        if end > start:
            return f"{_minutes_to_time(start)} - {_minutes_to_time(end)}"

        return "Not configured"


class ElnurGabarronChargingDaysSensor(ElnurGabarronSensorBase):
    """Charging active days sensor."""

    def __init__(self, coordinator, full_device_id, device_id, zone_id, zone_name):
        """Initialize the charging days sensor."""
        super().__init__(coordinator, full_device_id, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_charging_days"
        self._attr_name = "Charging Days"
        self._attr_icon = "mdi:calendar-week"

    @property
    def native_value(self) -> str | None:
        """Return the active charging days."""
        setup = self.zone_data.get("setup", {})
        charging_conf = setup.get("charging_conf", {})
        active_days = charging_conf.get("active_days", [])

        if not active_days or len(active_days) != 7:
            return "Not configured"

        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        active = [day_names[i] for i, is_active in enumerate(active_days) if is_active]

        if not active:
            return "No days selected"

        if len(active) == 7:
            return "Every day"

        return ", ".join(active)
