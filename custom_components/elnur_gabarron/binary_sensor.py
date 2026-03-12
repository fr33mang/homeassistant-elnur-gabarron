import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, build_device_info
from .socketio_coordinator import ElnurSocketIOCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class ElnurBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes an Elnur Gabarron binary sensor with a status key."""

    status_key: str


BINARY_SENSOR_DESCRIPTIONS: tuple[ElnurBinarySensorEntityDescription, ...] = (
    ElnurBinarySensorEntityDescription(
        key="heating",
        name="Heating",
        device_class=BinarySensorDeviceClass.HEAT,
        status_key="heating",
    ),
    ElnurBinarySensorEntityDescription(
        key="charging",
        name="Charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        status_key="charging",
    ),
    ElnurBinarySensorEntityDescription(
        key="window_open",
        name="Window",
        device_class=BinarySensorDeviceClass.WINDOW,
        status_key="window_open",
    ),
    ElnurBinarySensorEntityDescription(
        key="presence",
        name="Presence",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        status_key="presence",
    ),
    ElnurBinarySensorEntityDescription(
        key="true_radiant",
        name="True Radiant",
        icon="mdi:radiator",
        status_key="true_radiant_active",
    ),
    ElnurBinarySensorEntityDescription(
        key="extra_energy",
        name="Extra Energy",
        icon="mdi:lightning-bolt-circle",
        status_key="using_extra_nrg",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Elnur Gabarron binary sensor entities."""
    coordinator: ElnurSocketIOCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[ElnurGabarronBinarySensor] = []
    for zone_key, zone_data in coordinator.data.items():
        zone_id = zone_data.get("zone_id")

        if "_zone" in zone_key:
            actual_device_id = zone_key.split("_zone")[0]
        else:
            actual_device_id = zone_key

        zone_name = zone_data.get("name", f"Heater Zone {zone_id}")

        for description in BINARY_SENSOR_DESCRIPTIONS:
            entities.append(
                ElnurGabarronBinarySensor(
                    coordinator,
                    zone_key,
                    actual_device_id,
                    zone_id,
                    zone_name,
                    description,
                )
            )

    async_add_entities(entities)
    _LOGGER.debug("Added %s Elnur Gabarron binary sensor entities", len(entities))


class ElnurGabarronBinarySensorBase(CoordinatorEntity, BinarySensorEntity):
    """Base class for Elnur Gabarron binary sensors."""

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


class ElnurGabarronBinarySensor(ElnurGabarronBinarySensorBase):
    """Generic binary sensor driven by an ElnurBinarySensorEntityDescription."""

    entity_description: ElnurBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: ElnurSocketIOCoordinator,
        zone_key: str,
        device_id: str,
        zone_id: int,
        zone_name: str,
        description: ElnurBinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, zone_key, device_id, zone_id, zone_name)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        return self.zone_data.get("status", {}).get(self.entity_description.status_key)
