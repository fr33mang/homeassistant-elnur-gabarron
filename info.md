# Elnur Gabarron Integration

Elnur Gabarron Heaters integration based on reverse engineered API. Control your electric heaters using real-time Socket.IO updates.

## Features

- **Real-time updates** - Instant synchronization via Socket.IO
- **Automatic device discovery** - Each radiator zone appears as a separate device
- **Temperature control** - Set target temperature and view current temperature
- **Multiple temperature presets** - Configure Eco, Comfort, and Anti-frost temperatures
- **Power management** - Turn heaters on/off
- **Comprehensive sensors** - Temperature, power, charge level, error codes, firmware
- **Auto-reconnection** - Seamless recovery from connection issues

## Installation via HACS

1. Add this repository to HACS as a custom repository
2. Search for "Elnur Gabarron" in HACS
3. Click Install
4. Restart Home Assistant
5. Go to **Settings** → **Devices & Services** → **Add Integration**
6. Search for "Elnur Gabarron" and configure with your credentials

## Manual Installation

1. Copy the `custom_components/elnur_gabarron` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Go to **Settings** → **Devices & Services** → **Add Integration**
4. Search for "Elnur Gabarron" and configure with your credentials

## Configuration

You'll need your Elnur account credentials:
- **Email**: Your Elnur account email
- **Password**: Your Elnur account password
- **Serial ID**: `7` (default)

## Support

For issues and questions, please visit the [GitHub repository](https://github.com/fr33mang/homeassistant-elnur-gabarron).
