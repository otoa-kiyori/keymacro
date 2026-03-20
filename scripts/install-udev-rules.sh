#!/usr/bin/env bash
# scripts/install-udev-rules.sh — install keymacro udev rules system-wide
#
# Run once after cloning:
#   bash scripts/install-udev-rules.sh
#
# What it does:
#   1. Installs udev/99-keymacro.rules (core — uinput)
#   2. Installs each plugin's own rules file (plugins/*/99-keymacro-*.rules)
#   3. Reloads udev and triggers rules for connected devices
#   4. Loads the uinput kernel module and makes it persistent across reboots

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RULES_DST_DIR="/etc/udev/rules.d"
MODULES_FILE="/etc/modules-load.d/keymacro.conf"

echo "==> Installing core udev rules..."
sudo install -m 644 "$REPO_ROOT/udev/99-keymacro.rules" "$RULES_DST_DIR/"
echo "    Installed: $RULES_DST_DIR/99-keymacro.rules"

echo "==> Installing plugin udev rules..."
for rules_file in "$REPO_ROOT"/plugins/*/99-keymacro-*.rules; do
    [ -f "$rules_file" ] || continue
    filename="$(basename "$rules_file")"
    sudo install -m 644 "$rules_file" "$RULES_DST_DIR/"
    echo "    Installed: $RULES_DST_DIR/$filename"
done

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
