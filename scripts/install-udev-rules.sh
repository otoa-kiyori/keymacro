#!/usr/bin/env bash
# scripts/install-udev-rules.sh — install keymacro system dependencies
#
# Run once after cloning:
#   bash scripts/install-udev-rules.sh
#
# What it does:
#   1. Installs Python dependencies (apt-first, pip fallback)
#   2. Installs udev/99-keymacro.rules (core — uinput)
#   3. Installs each plugin's own rules file (plugins/*/99-keymacro-*.rules)
#   4. Reloads udev and triggers rules for connected devices
#   5. Loads the uinput kernel module and makes it persistent across reboots
#   6. Adds the current user to the input and plugdev groups

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RULES_DST_DIR="/etc/udev/rules.d"
MODULES_FILE="/etc/modules-load.d/keymacro.conf"

# ── Python dependencies ────────────────────────────────────────────────────────
# Format: "pip_name:apt_name:import_name"
PYTHON_DEPS=(
    "PyQt6:python3-pyqt6:PyQt6"
    "PyYAML:python3-yaml:yaml"
    "pyusb:python3-usb:usb"
    "evdev:python3-evdev:evdev"
)

install_python_dep() {
    local pip_name="$1"
    local apt_name="$2"
    local import_name="$3"

    if python3 -c "import $import_name" 2>/dev/null; then
        echo "    $pip_name already installed — skipping."
        return
    fi

    echo "    Installing $pip_name..."
    if sudo apt-get install -y "$apt_name" > /dev/null 2>&1; then
        echo "    $pip_name installed via apt."
    else
        echo "    apt failed, trying pip..."
        pip install --break-system-packages "$pip_name"
    fi
}

echo "==> Installing Python dependencies..."
for dep in "${PYTHON_DEPS[@]}"; do
    IFS=':' read -r pip_name apt_name import_name <<< "$dep"
    install_python_dep "$pip_name" "$apt_name" "$import_name"
done

# ── udev rules ────────────────────────────────────────────────────────────────

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

# ── uinput kernel module ──────────────────────────────────────────────────────

echo "==> Loading uinput kernel module..."
sudo modprobe uinput

if [ ! -f "$MODULES_FILE" ]; then
    echo "==> Making uinput load persist across reboots..."
    echo "uinput" | sudo tee "$MODULES_FILE" > /dev/null
    echo "    Created: $MODULES_FILE"
else
    echo "    $MODULES_FILE already exists — skipping."
fi

# ── Group membership ──────────────────────────────────────────────────────────

echo "==> Adding $USER to input and plugdev groups..."
sudo usermod -aG input,plugdev "$USER"
echo "    Done."

echo ""
echo "==> All done!"
echo "    IMPORTANT: Log out and back in for group changes to take effect."
