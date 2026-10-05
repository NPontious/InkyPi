#!/usr/bin/env bash
set -e

PORT="${1:-/dev/ttyACM0}"
BAUD="${2:-460800}"
FW_DIR="/tmp/esp32-photoframe-ee02"
RELEASE_TAG="${3:-v2.19.0}"
FW_NAME="photoframe-firmware-seeedstudio_xiao_ee02-merged.bin"
FW_URL="https://github.com/aitjcize/esp32-photoframe/releases/download/${RELEASE_TAG}/${FW_NAME}"

echo "=========================================================="
echo "  Flashing XIAO EE02 13.3\" Spectra 6 E-Ink Firmware"
echo "=========================================================="
echo "Port: $PORT"
echo "Baud: $BAUD"
echo "Release: $RELEASE_TAG"

if [ ! -e "$PORT" ]; then
    echo "Error: Device port $PORT not found!"
    echo "Make sure the board is connected and you have write permissions (e.g. dialout group)."
    exit 1
fi

mkdir -p "$FW_DIR"
if [ ! -f "$FW_DIR/$FW_NAME" ]; then
    echo "Downloading prebuilt firmware: $FW_URL..."
    curl -L "$FW_URL" -o "$FW_DIR/$FW_NAME"
else
    echo "Firmware binary already downloaded at $FW_DIR/$FW_NAME"
fi

echo "Flashing firmware to $PORT..."
if command -v esptool.py >/dev/null 2>&1; then
    ESPTOOL_CMD="esptool.py"
elif python3 -m esptool --help >/dev/null 2>&1; then
    ESPTOOL_CMD="python3 -m esptool"
else
    echo "esptool not found in current environment, invoking via nix-shell..."
    ESPTOOL_CMD="nix-shell -p python3Packages.esptool --run esptool.py"
fi

$ESPTOOL_CMD --chip esp32s3 --port "$PORT" --baud "$BAUD" write_flash 0x0 "$FW_DIR/$FW_NAME"

echo "=========================================================="
echo "  Flashing complete!"
echo "  1. Reset or power cycle the XIAO EE02 board."
echo "  2. Connect to the 'PhotoFrame-XXXX' Wi-Fi access point."
echo "  3. Configure your Wi-Fi credentials."
echo "  4. Set Mode to 'Image Server' and URL to:"
echo "     http://<your-server-ip>:8080/api/photoframe/image"
echo "=========================================================="
