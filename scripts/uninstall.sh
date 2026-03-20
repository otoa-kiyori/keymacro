#!/usr/bin/env bash
# scripts/uninstall.sh — remove keymacro system dependencies
#
# Run to undo what install.sh installed:
#   bash scripts/uninstall.sh
#
# What it does:
#   1. Verifies sudo access
#   2. Removes the KDE autostart entry
#   3. Removes the launcher script from ~/bin/
#   4. Removes keymacro udev rules and reloads udev
#   5. Removes /etc/modules-load.d/keymacro.conf
#   6. Removes Python packages that nothing else on the system depends on
#   7. Reminds you about group membership (not auto-removed — too risky)

set -euo pipefail

RULES_DST_DIR="/etc/udev/rules.d"
MODULES_FILE="/etc/modules-load.d/keymacro.conf"
LAUNCHER="$HOME/bin/keymacro"
AUTOSTART_FILE="$HOME/.config/autostart/keymacro.desktop"
APPS_FILE="$HOME/.local/share/applications/keymacro.desktop"

TOTAL_STEPS=6
STEP=0

step() {
    STEP=$((STEP + 1))
    echo ""
    echo "[$STEP/$TOTAL_STEPS] $*"
}

# ── Python dependencies ────────────────────────────────────────────────────────
# Format: "pip_name:apt_name:import_name"  — must match install.sh
PYTHON_DEPS=(
    "PyQt6:python3-pyqt6:PyQt6"
    "PyYAML:python3-yaml:yaml"
    "pyusb:python3-usb:usb"
    "evdev:python3-evdev:evdev"
    "Pillow:python3-pil:PIL"
)

# Returns 0 (true) if another installed package depends on $apt_name
has_other_dependents() {
    local apt_name="$1"
    local count
    count=$(apt-cache rdepends --installed "$apt_name" 2>/dev/null \
        | grep -v "^${apt_name}$" \
        | grep -v "^Reverse Depends:" \
        | grep -v "^[[:space:]]*$" \
        | wc -l)
    [ "$count" -gt 0 ]
}

# ── Step 1: Sudo check ────────────────────────────────────────────────────────

step "Checking sudo access..."
if ! sudo -v 2>/dev/null; then
    echo "    ERROR: sudo access is required to uninstall keymacro."
    echo "    Please run as a user with sudo privileges."
    exit 1
fi
echo "    OK — sudo credentials cached for this session."

# ── Step 2: Autostart entry ───────────────────────────────────────────────────

step "Removing KDE autostart and application menu entries..."
if [ -f "$AUTOSTART_FILE" ]; then
    rm "$AUTOSTART_FILE"
    echo "    Removed: $AUTOSTART_FILE"
else
    echo "    $AUTOSTART_FILE not found — skipping."
fi
if [ -f "$APPS_FILE" ]; then
    rm "$APPS_FILE"
    update-desktop-database "$(dirname "$APPS_FILE")" 2>/dev/null || true
    echo "    Removed: $APPS_FILE"
else
    echo "    $APPS_FILE not found — skipping."
fi

# ── Step 3: Launcher script ───────────────────────────────────────────────────

step "Removing launcher script..."
if [ -f "$LAUNCHER" ]; then
    rm "$LAUNCHER"
    echo "    Removed: $LAUNCHER"
else
    echo "    $LAUNCHER not found — skipping."
fi

# ── Step 4: udev rules ────────────────────────────────────────────────────────

step "Removing keymacro udev rules..."
found_rules=0
for rules_file in "$RULES_DST_DIR"/99-keymacro*.rules; do
    [ -f "$rules_file" ] || continue
    sudo rm "$rules_file"
    echo "    Removed: $rules_file"
    found_rules=1
done
if [ "$found_rules" -eq 0 ]; then
    echo "    No keymacro rules found in $RULES_DST_DIR — skipping."
fi

echo "    Reloading udev rules..."
sudo udevadm control --reload-rules
sudo udevadm trigger
echo "    udev reloaded."

# ── Step 5: modules-load.d ────────────────────────────────────────────────────

step "Removing uinput persistence..."
if [ -f "$MODULES_FILE" ]; then
    sudo rm "$MODULES_FILE"
    echo "    Removed: $MODULES_FILE"
    echo "    uinput will no longer load automatically on next boot."
    echo "    Note: uinput is still loaded in the current session."
else
    echo "    $MODULES_FILE not found — skipping."
fi

# ── Step 6: Python packages ───────────────────────────────────────────────────

step "Checking Python dependencies..."
TO_REMOVE=()

for dep in "${PYTHON_DEPS[@]}"; do
    IFS=':' read -r pip_name apt_name import_name <<< "$dep"

    if ! python3 -c "import $import_name" 2>/dev/null; then
        echo "    $pip_name not installed — skipping."
        continue
    fi

    if has_other_dependents "$apt_name"; then
        dependents=$(apt-cache rdepends --installed "$apt_name" 2>/dev/null \
            | grep -v "^${apt_name}$" \
            | grep -v "^Reverse Depends:" \
            | grep -v "^[[:space:]]*$" \
            | tr -d ' ' | paste -sd ', ')
        echo "    $pip_name kept — also needed by: $dependents"
        continue
    fi

    TO_REMOVE+=("$apt_name")
    echo "    $pip_name queued for removal."
done

if [ "${#TO_REMOVE[@]}" -gt 0 ]; then
    echo "    Removing: ${TO_REMOVE[*]}..."
    sudo apt-get remove -y "${TO_REMOVE[@]}"
    sudo apt-get autoremove -y
    echo "    Done."
else
    echo "    No Python packages to remove."
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo "========================================"
echo " keymacro uninstallation complete!"
echo "========================================"
echo ""
echo "  NOTE: Your user was NOT removed from the 'input' and 'plugdev' groups."
echo "  These groups may be needed by other hardware (audio, USB devices, etc.)."
echo "  To remove manually if you are sure nothing else needs them:"
echo "    sudo gpasswd -d \$USER input"
echo "    sudo gpasswd -d \$USER plugdev"
echo ""
