#!/usr/bin/env bash
# scripts/install-udev-rules.sh — install keymacro udev rules system-wide
#
# Run once after cloning:
#   bash scripts/install-udev-rules.sh
#
# What it does:
#   1. Copies udev/99-keymacro.rules to /etc/udev/rules.d/
#   2. Reloads udev rules and triggers them for connected devices
#   3. Loads the uinput kernel module and makes it persistent across reboots

set -euo pipefail

RULES_SRC="$(cd "$(dirname "$0")/.." && pwd)/udev/99-keymacro.rules"
RULES_DST="/etc/udev/rules.d/99-keymacro.rules"
MODULES_FILE="/etc/modules-load.d/uinput.conf"

echo "==> Installing udev rules..."
sudo install -m 644 "$RULES_SRC" "$RULES_DST"
echo "    Installed: $RULES_DST"

echo "==> Reloading udev rules..."
sudo udevadm control --reload-rules
sudo udevadm trigger
echo "    Done."

echo "==> Loading uinput kernel module..."
sudo modprobe uinput

if [ ! -f "$MODULES_FILE" ]; then
    echo "==> Making uinput load persist across reboots..."
    echo "uinput" | sudo tee "$MODULES_FILE" > /dev/null
    echo "    Created: $MODULES_FILE"
else
    echo "    $MODULES_FILE already exists — skipping."
fi

echo ""
echo "==> Done!  Ensure your user is in the required groups:"
echo "    sudo usermod -aG input,plugdev \$USER"
echo "    Then log out and back in for group changes to take effect."
