import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, build_device_info, iter_resolvable_zones
from .socketio_coordinator import ElnurSocketIOCoordinator

_LOGGER = logging.getLogger(__name__)


def _number_from(zone_data: dict[str, Any], section: str, key: str, cast: Callable[[Any], StateType]) -> StateType:
    val = zone_data.get(section, {}).get(key)
    if val is not None:
        try:
            return cast(val)
        except (ValueError, TypeError):
            return None
    return None


def _int_from_status(zone_data: dict[str, Any], key: str) -> int | None:
    return _number_from(zone_data, "status", key, int)


def _float_from_status(zone_data: dict[str, Any], key: str) -> float | None:
    return _number_from(zone_data, "status", key, float)


def _int_from_setup(zone_data: dict[str, Any], key: str) -> int | None:
    return _number_from(zone_data, "setup", key, int)


def _float_from_setup(zone_data: dict[str, Any], key: str) -> float | None:
    return _number_from(zone_data, "setup", key, float)


def _get_priority(zone_data: dict[str, Any]) -> str | None:
    # isinstance, not a bare truthiness check: this is the same server that
    # sends numbers as strings and ints where booleans belong, and a priority
    # arriving as an int would otherwise raise AttributeError out of a property
    # Home Assistant calls on every state write. The neighbouring extractors
    # already swallow a wrong type and return None; match them.
    priority = zone_data.get("setup", {}).get("priority")
    return priority.capitalize() if isinstance(priority, str) and priority else None


def _get_firmware_version(zone_data: dict[str, Any]) -> str | None:
    version = zone_data.get("version", {})
    fw_version = version.get("fw_version")
    hw_version = version.get("hw_version")
    if fw_version and hw_version:
        return f"FW: {fw_version} / HW: {hw_version}"
    if fw_version:
        return f"FW: {fw_version}"
    if hw_version:
        return f"HW: {hw_version}"
    return None


# setup.control_mode is an index into this list, in the order the official web
# client's HeatingNodeController uses (Elnur storage heaters inherit it).
CONTROL_MODES = (
    "Hysteresis 0.2",
    "Hysteresis 0.3",
    "Hysteresis 0.5",
    "Hysteresis 0.7",
    "PID",
    "PID 15",
    "PID 30",
)


def _get_control_mode(zone_data: dict[str, Any]) -> str | None:
    index = _int_from_setup(zone_data, "control_mode")
    if index is None or not 0 <= index < len(CONTROL_MODES):
        return None
    return CONTROL_MODES[index]


def _minutes_to_time(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _get_charging_slot(zone_data: dict[str, Any], slot_key: str) -> str | None:
    slot = zone_data.get("setup", {}).get("charging_conf", {}).get(slot_key, {})
    start = slot.get("start", 0)
    end = slot.get("end", 0)
    if start == 0 and end == 0:
        return "Disabled"
    if end > start:
        return f"{_minutes_to_time(start)} - {_minutes_to_time(end)}"
    return "Not configured"


def _get_charging_days(zone_data: dict[str, Any]) -> str | None:
    active_days = zone_data.get("setup", {}).get("charging_conf", {}).get("active_days", [])
    if not active_days or len(active_days) != 7:
        return "Not configured"
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    active = [day_names[i] for i, is_active in enumerate(active_days) if is_active]
    if not active:
        return "No days selected"
    if len(active) == 7:
        return "Every day"
    return ", ".join(active)


@dataclass(frozen=True, kw_only=True)
class ElnurSensorEntityDescription(SensorEntityDescription):
    """Describes an Elnur Gabarron sensor with a value extraction function."""

    value_fn: Callable[[dict[str, Any]], StateType]


SENSOR_DESCRIPTIONS: tuple[ElnurSensorEntityDescription, ...] = (
    ElnurSensorEntityDescription(
        key="charge_level",
        name="Charge Level",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-charging",
        value_fn=lambda d: _int_from_status(d, "charge_level"),
    ),
    ElnurSensorEntityDescription(
        key="power",
        name="Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt",
        value_fn=lambda d: _float_from_status(d, "power"),
    ),
    ElnurSensorEntityDescription(
        key="pcb_temp",
        name="PCB Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        entity_registry_enabled_default=False,
        value_fn=lambda d: _float_from_status(d, "pcb_temp"),
    ),
    ElnurSensorEntityDescription(
        key="target_charge",
        name="Target Charge",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-arrow-up",
        value_fn=lambda d: _int_from_status(d, "target_charge_per"),
    ),
    ElnurSensorEntityDescription(
        key="priority",
        name="Priority",
        icon="mdi:priority-high",
        entity_registry_enabled_default=False,
        value_fn=_get_priority,
    ),
    ElnurSensorEntityDescription(
        key="error_code",
        name="Error Code",
        icon="mdi:alert-circle",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _int_from_status(d, "error_code"),
    ),
    ElnurSensorEntityDescription(
        key="firmware",
        name="Firmware Version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_get_firmware_version,
    ),
    ElnurSensorEntityDescription(
        key="charging_slot1",
        name="Charging Slot 1",
        icon="mdi:timer",
        value_fn=lambda d: _get_charging_slot(d, "slot_1"),
    ),
    ElnurSensorEntityDescription(
        key="charging_slot2",
        name="Charging Slot 2",
        icon="mdi:timer",
        value_fn=lambda d: _get_charging_slot(d, "slot_2"),
    ),
    ElnurSensorEntityDescription(
        key="charging_days",
        name="Charging Days",
        icon="mdi:calendar-week",
        value_fn=_get_charging_days,
    ),
    # Setup fields no entity used before, kept diagnostic.
    ElnurSensorEntityDescription(
        key="temperature_offset",
        name="Temperature Offset",
        # No device class: this is a delta, and the temperature class would
        # convert it as an absolute reading for Fahrenheit users.
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:thermometer-plus",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _float_from_setup(d, "offset"),
    ),
    ElnurSensorEntityDescription(
        key="away_offset",
        name="Away Offset",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:thermometer-minus",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _float_from_setup(d, "away_offset"),
    ),
    ElnurSensorEntityDescription(
        key="power_level_limit",
        name="Power Level Limit",
        icon="mdi:speedometer-medium",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _int_from_setup(d, "power_level_limit"),
    ),
    ElnurSensorEntityDescription(
        key="control_mode",
        name="Control Mode",
        icon="mdi:tune-variant",
        device_class=SensorDeviceClass.ENUM,
        options=list(CONTROL_MODES),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_get_control_mode,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Elnur Gabarron sensor entities."""
    coordinator: ElnurSocketIOCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[ElnurGabarronSensor] = []
    for zone_key, zone_data, actual_device_id, zone_id in iter_resolvable_zones(coordinator.data):
        zone_name = zone_data.get("name", f"Heater Zone {zone_id}")

        for description in SENSOR_DESCRIPTIONS:
            entities.append(
                ElnurGabarronSensor(
                    coordinator,
                    zone_key,
                    actual_device_id,
                    zone_id,
                    zone_name,
                    description,
                )
            )

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
        super().__init__(coordinator)
        self._zone_key = zone_key
        self._device_id = device_id
        self._zone_id = zone_id
        self._initial_zone_name = zone_name

    @property
    def zone_data(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._zone_key, {})

    @property
    def zone_name(self) -> str:
        return self.zone_data.get("name") or self._initial_zone_name

    @property
    def device_info(self) -> DeviceInfo:
        return build_device_info(self.zone_data, self._device_id, self._zone_id, self.zone_name)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._zone_key in self.coordinator.data


class ElnurGabarronSensor(ElnurGabarronSensorBase):
    """Generic sensor driven by an ElnurSensorEntityDescription."""

    entity_description: ElnurSensorEntityDescription

    def __init__(
        self,
        coordinator: ElnurSocketIOCoordinator,
        zone_key: str,
        device_id: str,
        zone_id: int,
        zone_name: str,
        description: ElnurSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, zone_key, device_id, zone_id, zone_name)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_{description.key}"

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.zone_data)
