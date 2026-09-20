import logging
from collections.abc import Iterator
from typing import Any

from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceInfo

_LOGGER = logging.getLogger(__name__)

DOMAIN = "elnur_gabarron"

# Configuration
CONF_SERIAL_ID = "serial_id"

# API Constants
API_BASE_URL = "https://api-elnur.helki.com"
API_TOKEN_ENDPOINT = "/client/token"
API_DEVICES_ENDPOINT = "/api/v2/grouped_devs"
API_DEVICE_CONTROL_ENDPOINT = "/api/v2/devs/{device_id}/acm/{zone_id}/status"

# Socket.IO Constants
SOCKETIO_PATH = "/socket.io/"

# OAuth2 Client Credentials (from the web app)
CLIENT_ID = "54bccbfb41a9a5113f0488d0"
CLIENT_SECRET = "vdivdi"

# Defaults
DEFAULT_SERIAL_ID = "7"

# Device info
MANUFACTURER = "Elnur Gabarron"
MODEL = "Electric Heater"


def iter_resolvable_zones(
    zones: dict[str, dict[str, Any]],
) -> Iterator[tuple[str, dict[str, Any], str, int]]:
    """Yield (zone_key, zone_data, device_id, zone_id) for each usable zone.

    The coordinator writes device_id and zone_id into every zone it builds, so
    both are read rather than recovered by taking the zone key apart. Deriving
    them from the key was fragile in two ways: it broke on a device id
    containing "_zone", and its fallback branch quietly used the whole key as
    the device id. Both failures land in `unique_id`, which Home Assistant
    persists to the entity registry, so a moment of malformed data leaves
    orphaned entities behind that outlive it.

    A zone that can't be resolved is skipped with a warning rather than taken
    as fatal: zone_id comes from a single node's `addr`, so one malformed node
    would otherwise cost the user every healthy zone on the device, forever, if
    the device keeps sending it. device_id is the same value for every zone, so
    if that is what's missing nothing resolves at all — which is the one case
    that raises, letting Home Assistant retry setup with backoff.

    The raise happens on exhaustion, so a caller that breaks out of the loop
    early won't see it. Every platform consumes this fully.
    """
    resolved = 0

    for zone_key, zone_data in zones.items():
        device_id = zone_data.get("device_id")
        zone_id = zone_data.get("zone_id")

        if not device_id or zone_id is None:
            _LOGGER.warning(
                "Skipping zone %r: device_id=%r zone_id=%r — refusing to register entities "
                "under an identifier that would be wrong",
                zone_key,
                device_id,
                zone_id,
            )
            continue

        resolved += 1
        yield zone_key, zone_data, device_id, zone_id

    if zones and not resolved:
        raise ConfigEntryNotReady(
            f"None of the {len(zones)} zone(s) reported by the coordinator could be "
            "resolved to a device_id and zone_id"
        )


def build_device_info(
    zone_data: dict[str, Any],
    device_id: str,
    zone_id: int,
    zone_name: str,
) -> DeviceInfo:
    """Build DeviceInfo for an Elnur Gabarron zone.

    Shared across all platforms so every entity registers the same device.
    """
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
        identifiers={(DOMAIN, f"{device_id}_zone{zone_id}")},
        name=zone_name,
        manufacturer=MANUFACTURER,
        model=" ".join(model_parts),
        suggested_area=device_name or group_name,
    )
