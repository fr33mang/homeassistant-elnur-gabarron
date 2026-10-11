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
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, build_device_info, iter_resolvable_zones
from .socketio_coordinator import ElnurSocketIOCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class ElnurBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes an Elnur Gabarron binary sensor read from one payload field."""

    payload_key: str
    # Which block of the zone payload the field lives in: "status" is what the
    # heater is doing right now, "setup" is how it's configured.
    section: str = "status"


BINARY_SENSOR_DESCRIPTIONS: tuple[ElnurBinarySensorEntityDescription, ...] = (
    ElnurBinarySensorEntityDescription(
        key="heating",
        name="Heating",
        device_class=BinarySensorDeviceClass.HEAT,
        payload_key="heating",
    ),
    ElnurBinarySensorEntityDescription(
        key="charging",
        name="Charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        payload_key="charging",
    ),
    ElnurBinarySensorEntityDescription(
        key="window_open",
        name="Window",
        device_class=BinarySensorDeviceClass.WINDOW,
        payload_key="window_open",
    ),
    ElnurBinarySensorEntityDescription(
        key="presence",
        name="Presence",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        payload_key="presence",
    ),
    ElnurBinarySensorEntityDescription(
        key="true_radiant",
        name="True Radiant",
        icon="mdi:radiator",
        payload_key="true_radiant_active",
    ),
    ElnurBinarySensorEntityDescription(
        key="extra_energy",
        name="Extra Energy",
        icon="mdi:lightning-bolt-circle",
        payload_key="using_extra_nrg",
    ),
    # Fields no entity used before. Diagnostic for now: what some of them mean
    # in practice is still being worked out from their history.
    ElnurBinarySensorEntityDescription(
        key="child_lock",
        name="Child Lock",
        # Not BinarySensorDeviceClass.LOCK: that one reads "on" as unlocked.
        icon="mdi:lock",
        entity_category=EntityCategory.DIAGNOSTIC,
        payload_key="locked",
    ),
    ElnurBinarySensorEntityDescription(
        key="venting",
        name="Venting",
        icon="mdi:fan",
        entity_category=EntityCategory.DIAGNOSTIC,
        payload_key="venting",
    ),
    ElnurBinarySensorEntityDescription(
        key="window_detection",
        name="Window Detection",
        icon="mdi:window-open-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        section="setup",
        payload_key="window_mode_enabled",
    ),
    ElnurBinarySensorEntityDescription(
        key="true_radiant_enabled",
        name="True Radiant Enabled",
        icon="mdi:radiator",
        entity_category=EntityCategory.DIAGNOSTIC,
        section="setup",
        payload_key="true_radiant_enabled",
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
    for zone_key, zone_data, actual_device_id, zone_id in iter_resolvable_zones(coordinator.data):
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
        description = self.entity_description
        value = self.zone_data.get(description.section, {}).get(description.payload_key)
        # Coerced: the server sends `locked` as 0/1 next to real booleans.
        return None if value is None else bool(value)
