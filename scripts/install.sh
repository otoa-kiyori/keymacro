#!/usr/bin/env bash
# scripts/install.sh — comprehensive installer for keymacro
#
# Run once after cloning:
#   bash scripts/install.sh
#
# What it does:
#   1. Verifies sudo access
#   2. Installs Python dependencies (apt-first, pip fallback)
#   3. Installs udev rules for core and all device plugins
#   4. Loads the uinput kernel module and persists it across reboots
#   5. Adds the current user to the input and plugdev groups
#   6. Creates a launcher script at ~/bin/keymacro
#   7. Installs the autostart entry so keymacro starts with KDE

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RULES_DST_DIR="/etc/udev/rules.d"
MODULES_FILE="/etc/modules-load.d/keymacro.conf"
LAUNCHER="$HOME/bin/keymacro"
AUTOSTART_DIR="$HOME/.config/autostart"
AUTOSTART_FILE="$AUTOSTART_DIR/keymacro.desktop"

TOTAL_STEPS=7
STEP=0

step() {
    STEP=$((STEP + 1))
    echo ""
    echo "[$STEP/$TOTAL_STEPS] $*"
}

# ── Step 1: Sudo check ────────────────────────────────────────────────────────

step "Checking sudo access..."
if ! sudo -v 2>/dev/null; then
    echo "    ERROR: sudo access is required to install keymacro."
    echo "    Please run as a user with sudo privileges."
    exit 1
fi
echo "    OK — sudo credentials cached for this session."

# ── Step 2: Python dependencies ───────────────────────────────────────────────
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

step "Installing Python dependencies..."
for dep in "${PYTHON_DEPS[@]}"; do
    IFS=':' read -r pip_name apt_name import_name <<< "$dep"
    install_python_dep "$pip_name" "$apt_name" "$import_name"
done

# ── Step 3: udev rules ────────────────────────────────────────────────────────

step "Installing udev rules..."
sudo install -m 644 "$REPO_ROOT/udev/99-keymacro.rules" "$RULES_DST_DIR/"
echo "    Installed: $RULES_DST_DIR/99-keymacro.rules"

for rules_file in "$REPO_ROOT"/plugins/*/99-keymacro-*.rules; do
    [ -f "$rules_file" ] || continue
    filename="$(basename "$rules_file")"
    sudo install -m 644 "$rules_file" "$RULES_DST_DIR/"
    echo "    Installed: $RULES_DST_DIR/$filename"
done

echo "    Reloading udev rules..."
sudo udevadm control --reload-rules
sudo udevadm trigger
echo "    udev reloaded."

# ── Step 4: uinput kernel module ──────────────────────────────────────────────

step "Loading uinput kernel module..."
sudo modprobe uinput
echo "    uinput loaded."

if [ ! -f "$MODULES_FILE" ]; then
    echo "uinput" | sudo tee "$MODULES_FILE" > /dev/null
    echo "    Created $MODULES_FILE — uinput will load on every boot."
else
    echo "    $MODULES_FILE already exists — skipping."
fi

# ── Step 5: Group membership ──────────────────────────────────────────────────

step "Adding $USER to input and plugdev groups..."
sudo usermod -aG input,plugdev "$USER"
echo "    $USER added to: input, plugdev"

# ── Step 6: Launcher script ───────────────────────────────────────────────────

step "Creating launcher script..."
mkdir -p "$HOME/bin"
cat > "$LAUNCHER" << LAUNCHEREOF
#!/usr/bin/env bash
exec python3 "$REPO_ROOT/keymacro.py" "\$@"
LAUNCHEREOF
chmod +x "$LAUNCHER"
echo "    Created: $LAUNCHER"

# ── Step 7: Autostart entry ───────────────────────────────────────────────────

step "Installing KDE autostart entry..."
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_FILE" << DESKTOPEOF
[Desktop Entry]
Type=Application
Name=keymacro
Comment=Key mapping and macros for gaming peripherals
Exec=$LAUNCHER
Icon=input-gaming
Hidden=false
X-KDE-AutostartEnabled=true
X-KDE-autostart-phase=2
DESKTOPEOF
echo "    Installed: $AUTOSTART_FILE"

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo "========================================"
echo " keymacro installation complete!"
echo "========================================"
echo ""
echo "  IMPORTANT: Log out and back in for group changes to take effect."
echo "  keymacro will then start automatically with KDE."
echo "  You can also launch it manually: keymacro"
echo ""
