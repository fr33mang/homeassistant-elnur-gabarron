# Elnur Gabarron Integration for Home Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![Lint](https://github.com/fr33mang/homeassistant-elnur-gabarron/workflows/Lint/badge.svg)](https://github.com/fr33mang/homeassistant-elnur-gabarron/actions/workflows/lint.yaml)
[![Tests](https://github.com/fr33mang/homeassistant-elnur-gabarron/workflows/Tests/badge.svg)](https://github.com/fr33mang/homeassistant-elnur-gabarron/actions/workflows/test.yaml)
[![codecov](https://codecov.io/gh/fr33mang/homeassistant-elnur-gabarron/graph/badge.svg?token=2BMLJJGA4G)](https://codecov.io/gh/fr33mang/homeassistant-elnur-gabarron)
[![Hassfest](https://github.com/fr33mang/homeassistant-elnur-gabarron/workflows/Validate%20with%20hassfest/badge.svg)](https://github.com/fr33mang/homeassistant-elnur-gabarron/actions/workflows/hassfest.yaml)
[![HACS Validation](https://github.com/fr33mang/homeassistant-elnur-gabarron/workflows/HACS%20Validation/badge.svg)](https://github.com/fr33mang/homeassistant-elnur-gabarron/actions/workflows/hacs.yaml)

Unofficial Home Assistant integration for Elnur Gabarron electric heaters, built on the reverse-engineered API behind the official web app. State changes arrive in real time over Socket.IO.

<img width="1386" height="574" alt="Elnur Gabarron heater zones in Home Assistant" src="https://github.com/user-attachments/assets/e01af915-97be-4995-bc74-12f40847fb1f" />

## Features

- **Real-time updates** — changes made in the Elnur app or on the heater show up in Home Assistant immediately, and vice versa
- **Automatic discovery** — every heater zone becomes its own device, named as in the Elnur app; the integration takes your home's name
- **Climate control** — Heat (manual setpoint), Auto (the heater's own schedule) and Off
- **Temperature presets** — Anti-frost, Economy and Comfort setpoints
- **Diagnostics** — charge level, power draw, board temperature, error code, charging schedule, firmware

## Supported Hardware

Only storage heaters (`acm`) have been tested on a real device.

Direct heaters (`htr`), modulating heaters (`htr_mod`) and towel rails are recognised and appear in Home Assistant, but control commands are always addressed as `acm`, so changing their mode or temperature probably won't work yet. If you have one, please [open an issue](https://github.com/fr33mang/homeassistant-elnur-gabarron/issues).

Water and solar storage tanks, power meters, thermostats and timers are skipped.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=fr33mang&repository=homeassistant-elnur-gabarron&category=integration)

Or add it by hand:

1. In HACS, open the **⋮** menu (top right) → **Custom repositories**
2. Add `https://github.com/fr33mang/homeassistant-elnur-gabarron` with type **Integration**
3. Find **Elnur Gabarron Heaters** in HACS and click **Download**
4. Restart Home Assistant

### Manual

1. Copy `custom_components/elnur_gabarron` from this repository into your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

Go to **Settings** → **Devices & Services** → **Add Integration**, search for **Elnur Gabarron** and enter:

- **Email** and **Password** — your Elnur account, the same one used at https://remotecontrol.elnur.es
- **Serial ID** — leave at `7` unless you know your account uses a different one

## Entities

Each heater zone is a separate device with the entities below. No empty hub device is created.

### Climate

- Current temperature
- Target temperature (5–30 °C); hidden while the zone is Off, since the heater has no setpoint then
- HVAC modes: **Heat** (manual setpoint), **Auto** (follows the schedule programmed on the heater) and **Off**
- HVAC action: Heating / Idle / Off
- `frost_protection_temperature` attribute — the zone's anti-frost setpoint

<img width="380" height="385" alt="Climate card for a heater zone" src="https://github.com/user-attachments/assets/8cf01a4d-4a1a-45a3-91d2-e33b07f166fc" />

### Temperature presets (Configuration)

All three accept 7–30 °C:

- **Anti-Frost Temperature** — freeze protection setpoint
- **Economy Temperature** — energy-saving setpoint
- **Comfort Temperature** — comfort setpoint

<img width="261" height="234" alt="Temperature preset controls" src="https://github.com/user-attachments/assets/db54a8a7-7234-4738-945a-5e8789110324" />

### Binary sensors

- **Heating** — the heating element is on
- **Charging** — the accumulator is charging
- **Window** — open window detected
- **Presence** — presence detected
- **True Radiant** — True Radiant mode active
- **Extra Energy** — extra energy mode active

### Sensors (Diagnostic)

- **Charge Level** — accumulator charge, %
- **Target Charge** — charge target, %
- **Power** — current power draw
- **PCB Temperature** — internal board temperature
- **Priority** — zone heating priority
- **Error Code** — device error status
- **Firmware Version**
- **Charging Slot 1** / **Charging Slot 2** — charging periods
- **Charging Days** — days the charging schedule applies to

<img width="411" height="590" alt="Diagnostic sensors for a heater zone" src="https://github.com/user-attachments/assets/e5054f85-662e-4714-b30a-0b067c63c0af" />

## How It Works

1. Logs in over the REST API (OAuth2; tokens are refreshed automatically)
2. Discovers the hub, its zones and your home's name, and renames the integration entry to match
3. Connects to the Socket.IO server and switches to WebSocket right after the handshake, as the official web app does, falling back to HTTP long-polling if the server offers no upgrade
4. Requests the full device state (`dev_data`) and creates one device per zone
5. Applies pushed updates as they arrive; the connection stays open indefinitely and reconnects only after an actual disconnect

Protocol details — ping direction and timing, packet framing, the upgrade sequence — are in [`docs/socketio-protocol.md`](docs/socketio-protocol.md).

## Limitations

- **One hub per config entry** — only the first hub on the account is set up; any others are ignored
- **Storage heaters only** — see [Supported Hardware](#supported-hardware)

## Troubleshooting

### Authentication fails

- Check that the same email and password work at https://remotecontrol.elnur.es
- Check the Serial ID (usually `7`): it's sent as the `x-serialid` header in the web app's requests, visible in the browser's developer tools, Network tab
- Look for errors in the Home Assistant logs
- The OAuth client ID and secret are built into the integration. If Elnur changes them, login will fail for everyone until the integration is updated — please [open an issue](https://github.com/fr33mang/homeassistant-elnur-gabarron/issues)

### No real-time updates

- Look for Socket.IO errors in the Home Assistant logs
- Make sure nothing blocks `api-elnur.helki.com`, including `wss://` for the WebSocket transport
- An occasional reconnect is normal. Reconnects every few minutes or more often mean something is wrong — check the errors logged just before them

## Links

- [Official Elnur web app](https://remotecontrol.elnur.es)
- [Elnur website](https://elnur.es)
- [Report a bug or request a feature](https://github.com/fr33mang/homeassistant-elnur-gabarron/issues)

## License

MIT — see [LICENSE](LICENSE).
