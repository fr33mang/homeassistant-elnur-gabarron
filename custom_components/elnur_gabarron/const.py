"""Constants for the Elnur Gabarron integration."""

DOMAIN = "elnur_gabarron"

# Configuration
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
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
