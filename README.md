# Elnur Gabarron Integration for Home Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![Hassfest](https://github.com/fr33mang/homeassistant-elnur-gabarron/workflows/Validate%20with%20hassfest/badge.svg)](https://github.com/fr33mang/homeassistant-elnur-gabarron/actions/workflows/hassfest.yaml)
[![HACS Validation](https://github.com/fr33mang/homeassistant-elnur-gabarron/workflows/HACS%20Validation/badge.svg)](https://github.com/fr33mang/homeassistant-elnur-gabarron/actions/workflows/hacs.yaml)

Elnur Gabarron Heaters integration based on reverse engineered API. Control your electric heaters using real-time Socket.IO updates and the unofficial Elnur API.

## Features

✅ **Real-time updates** - Instant synchronization via Socket.IO
✅ **Automatic device discovery** - Each radiator zone appears as a separate device
✅ **Temperature control** - Set target temperature and view current temperature
✅ **Multiple temperature presets** - Configure Eco, Comfort, and Anti-frost temperatures
✅ **Power management** - Turn heaters on/off
✅ **Comprehensive sensors** - Temperature, power, charge level, error codes, firmware
✅ **Auto-reconnection** - Seamless recovery from connection issues
✅ **Dynamic naming** - Device names sync from Elnur app

## Installation

### Option 1: HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL and select "Integration" as the category
6. Click "Install"
7. Restart Home Assistant
8. Go to **Settings** → **Devices & Services** → **Add Integration**
9. Search for **"Elnur Gabarron"**

### Option 2: Manual Installation

1. Download or clone this repository
2. Copy the `custom_components/elnur_gabarron` folder to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant
4. Go to **Settings** → **Devices & Services** → **Add Integration**
5. Search for **"Elnur Gabarron"**

## Configuration

After installation, configure the integration with your Elnur credentials:

- **Email**: Your Elnur account email
- **Password**: Your Elnur account password
- **Serial ID**: `7` (default)

## Devices & Entities

### Integration Structure
The integration displays as your home name from the Elnur API (e.g., "My Home").

Each radiator zone appears as a **separate device** containing all its entities:

### Climate Entities (per zone)
- Current temperature monitoring
- Target temperature control (5-30°C)
- HVAC modes (Heat/Off)
- HVAC actions (Heating/Idle/Off)

### Temperature Controls (Configuration Section, per zone)
- **Anti-Frost Temperature** (5-15°C) - Freeze protection setpoint
- **Economy Temperature** (7-30°C) - Energy-saving mode setpoint
- **Comfort Temperature** (7-30°C) - Maximum comfort setpoint

### Sensors (Diagnostic Section, per zone)
- **Current Temperature** - Room temperature reading
- **Operating Mode** - Current mode (Off, Auto, Manual, etc.)
- **Power Ratings** - Min/Max/Nominal power in watts
- **Error Code** - Device error status
- **Firmware Version** - Installed firmware
- **PCB Temperature** - Internal board temperature
- **Charging Schedule** - Active charging periods and days

Temperature preset sensors are disabled by default (since number controls are available).

Only the actual radiator zones appear as devices—no empty hub devices are created.

## How It Works

### Startup Flow
1. Authenticate via REST API
2. Discover devices and zones (including home/group name)
3. Update integration title to match your home name
4. Connect to Socket.IO server
5. Request initial device data (`dev_data`)
6. Create zone devices with proper names from Socket.IO
7. Start real-time listener

### Real-Time Updates
- Server pushes updates instantly via Socket.IO
- Status changes appear in HA immediately
- Changes in Elnur app sync to HA in real-time
- Changes in HA sync to Elnur app immediately

## Troubleshooting

### Authentication fails
- Verify credentials work on https://remotecontrol.elnur.es
- Check serial ID (usually `7`)
- Review Home Assistant logs
- Check client_id and client_secret (they can be changed and need to be found in a browser history base64 encoded)

### No real-time updates
- Check Socket.IO connection in logs
- Verify no firewall blocking `api-elnur.helki.com`
- Look for reconnection messages (normal every ~40s)

## Repository Structure

```
custom_components/elnur_gabarron/
├── __init__.py                  # Integration setup
├── api.py                       # REST API client with OAuth2
├── climate.py                   # Climate platform (thermostats)
├── number.py                    # Number platform (temperature presets)
├── sensor.py                    # Sensor platform (readings & status)
├── socketio_coordinator.py      # Socket.IO coordinator (real-time updates)
├── config_flow.py               # Configuration UI
├── const.py                     # Constants & API endpoints
├── manifest.json                # Integration metadata
└── translations/
    └── en.json                  # UI translations
```

## Support

- **Official Web App**: https://remotecontrol.elnur.es
- **Elnur Website**: https://elnur.es
- **API Base**: https://api-elnur.helki.com
- **GitHub Issues**: [Report a bug or request a feature](https://github.com/fr33mang/homeassistant-elnur-gabarron/issues)

## Notes

- Integration automatically manages OAuth2 tokens
- Socket.IO sessions expire by design (~40s), auto-reconnection is normal
- All credentials stored securely in Home Assistant config
- Integration title and zone names update automatically from Elnur API/app
- Multiple zones per device hub are fully supported
- Each zone appears as a separate device in Home Assistant
- Changes sync bidirectionally (HA ↔ Elnur app)
- Should support multiple device hubs in one home or across multiple homes

## Version

**Status**: Working ✅
**Version**: 2026.2.13 (CalVer: YYYY.MM.DD)
**Features**: Complete with real-time updates

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
