from typing import Any

from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceInfo

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


def resolve_zone_identity(zone_key: str, zone_data: dict[str, Any]) -> tuple[str, int]:
    """Return the (device_id, zone_id) an entity for this zone must register under.

    The coordinator writes both into every zone it builds, so they are read
    rather than recovered by taking the zone key apart. Deriving them from the
    key was fragile in two ways: it broke on a device id containing "_zone",
    and its fallback branch quietly used the whole key as the device id.

    Both failures land in `unique_id`, which Home Assistant persists to the
    entity registry — so a moment of malformed data leaves behind orphaned
    entities that outlive it and have to be cleaned up by hand. Raising
    ConfigEntryNotReady instead is cheap: HA retries the setup with backoff,
    and a single bad dev_data frame costs nothing but a delay.
    """
    device_id = zone_data.get("device_id")
    zone_id = zone_data.get("zone_id")

    if not device_id or zone_id is None:
        raise ConfigEntryNotReady(
            f"Zone {zone_key!r} is missing device_id/zone_id; refusing to register "
            "entities under an identifier that would be wrong"
        )

    return device_id, zone_id


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
