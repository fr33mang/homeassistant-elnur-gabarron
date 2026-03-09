"""Binary sensor platform for Elnur Gabarron."""

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
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
    """Set up Elnur Gabarron binary sensor entities."""
    coordinator: ElnurSocketIOCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for zone_key, zone_data in coordinator.data.items():
        zone_id = zone_data.get("zone_id")

        if "_zone" in zone_key:
            actual_device_id = zone_key.split("_zone")[0]
        else:
            actual_device_id = zone_key

        zone_name = zone_data.get("name", f"Heater Zone {zone_id}")

        entities.extend(
            [
                ElnurGabarronHeatingSensor(coordinator, zone_key, actual_device_id, zone_id, zone_name),
                ElnurGabarronChargingSensor(coordinator, zone_key, actual_device_id, zone_id, zone_name),
                ElnurGabarronWindowOpenSensor(coordinator, zone_key, actual_device_id, zone_id, zone_name),
                ElnurGabarronPresenceSensor(coordinator, zone_key, actual_device_id, zone_id, zone_name),
                ElnurGabarronTrueRadiantSensor(coordinator, zone_key, actual_device_id, zone_id, zone_name),
                ElnurGabarronExtraEnergySensor(coordinator, zone_key, actual_device_id, zone_id, zone_name),
            ]
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
        """Initialize the binary sensor."""
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
        current_name = self.zone_data.get("name")
        return current_name or self._initial_zone_name

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information - must match climate entity device_info."""
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


class ElnurGabarronHeatingSensor(ElnurGabarronBinarySensorBase):
    """Heating status binary sensor."""

    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, coordinator, full_device_id, device_id, zone_id, zone_name):
        """Initialize the heating sensor."""
        super().__init__(coordinator, full_device_id, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_heating"
        self._attr_name = "Heating"

    @property
    def is_on(self) -> bool | None:
        """Return true if the heating element is active."""
        status = self.zone_data.get("status", {})
        return status.get("heating")


class ElnurGabarronChargingSensor(ElnurGabarronBinarySensorBase):
    """Charging status binary sensor."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    def __init__(self, coordinator, full_device_id, device_id, zone_id, zone_name):
        """Initialize the charging sensor."""
        super().__init__(coordinator, full_device_id, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_charging"
        self._attr_name = "Charging"

    @property
    def is_on(self) -> bool | None:
        """Return true if the heater is charging."""
        status = self.zone_data.get("status", {})
        return status.get("charging")


class ElnurGabarronWindowOpenSensor(ElnurGabarronBinarySensorBase):
    """Window open detection binary sensor."""

    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(self, coordinator, full_device_id, device_id, zone_id, zone_name):
        """Initialize the window open sensor."""
        super().__init__(coordinator, full_device_id, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_window_open"
        self._attr_name = "Window"

    @property
    def is_on(self) -> bool | None:
        """Return true if window is detected as open."""
        status = self.zone_data.get("status", {})
        return status.get("window_open")


class ElnurGabarronPresenceSensor(ElnurGabarronBinarySensorBase):
    """Presence detection binary sensor."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, coordinator, full_device_id, device_id, zone_id, zone_name):
        """Initialize the presence sensor."""
        super().__init__(coordinator, full_device_id, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_presence"
        self._attr_name = "Presence"

    @property
    def is_on(self) -> bool | None:
        """Return true if presence is detected."""
        status = self.zone_data.get("status", {})
        return status.get("presence")


class ElnurGabarronTrueRadiantSensor(ElnurGabarronBinarySensorBase):
    """True radiant mode binary sensor."""

    def __init__(self, coordinator, full_device_id, device_id, zone_id, zone_name):
        """Initialize the true radiant sensor."""
        super().__init__(coordinator, full_device_id, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_true_radiant"
        self._attr_name = "True Radiant"
        self._attr_icon = "mdi:radiator"

    @property
    def is_on(self) -> bool | None:
        """Return true if true radiant mode is active."""
        status = self.zone_data.get("status", {})
        return status.get("true_radiant_active")


class ElnurGabarronExtraEnergySensor(ElnurGabarronBinarySensorBase):
    """Extra energy mode binary sensor."""

    def __init__(self, coordinator, full_device_id, device_id, zone_id, zone_name):
        """Initialize the extra energy sensor."""
        super().__init__(coordinator, full_device_id, device_id, zone_id, zone_name)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{zone_id}_extra_energy"
        self._attr_name = "Extra Energy"
        self._attr_icon = "mdi:lightning-bolt-circle"

    @property
    def is_on(self) -> bool | None:
        """Return true if extra energy mode is active."""
        status = self.zone_data.get("status", {})
        return status.get("using_extra_nrg")
