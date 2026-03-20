#!/usr/bin/env bash
# scripts/uninstall.sh — remove keymacro system dependencies
#
# Run to undo what install-udev-rules.sh installed:
#   bash scripts/uninstall.sh
#
# What it does:
#   1. Removes keymacro udev rules from /etc/udev/rules.d/
#   2. Reloads udev
#   3. Removes /etc/modules-load.d/keymacro.conf
#   4. Removes Python packages that nothing else on the system depends on
#   5. Reminds you about group membership (not auto-removed — too risky)

set -euo pipefail

RULES_DST_DIR="/etc/udev/rules.d"
MODULES_FILE="/etc/modules-load.d/keymacro.conf"

# ── Python dependencies ────────────────────────────────────────────────────────
# Format: "pip_name:apt_name:import_name"  — must match install-udev-rules.sh
PYTHON_DEPS=(
    "PyQt6:python3-pyqt6:PyQt6"
    "PyYAML:python3-yaml:yaml"
    "pyusb:python3-usb:usb"
    "evdev:python3-evdev:evdev"
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

# ── udev rules ────────────────────────────────────────────────────────────────

echo "==> Removing keymacro udev rules..."
for rules_file in "$RULES_DST_DIR"/99-keymacro*.rules; do
    [ -f "$rules_file" ] || continue
    sudo rm "$rules_file"
    echo "    Removed: $rules_file"
done

echo "==> Reloading udev rules..."
sudo udevadm control --reload-rules
sudo udevadm trigger
echo "    Done."

# ── modules-load.d ────────────────────────────────────────────────────────────

if [ -f "$MODULES_FILE" ]; then
    echo "==> Removing $MODULES_FILE..."
    sudo rm "$MODULES_FILE"
    echo "    Removed. (uinput will no longer load on next boot)"
    echo "    Note: uinput is still loaded in the current session."
else
    echo "==> $MODULES_FILE not found — skipping."
fi

# ── Python packages ───────────────────────────────────────────────────────────

echo "==> Checking Python dependencies..."
TO_REMOVE=()

for dep in "${PYTHON_DEPS[@]}"; do
    IFS=':' read -r pip_name apt_name import_name <<< "$dep"

    # Skip if not installed at all
    if ! python3 -c "import $import_name" 2>/dev/null; then
        echo "    $pip_name not installed — skipping."
        continue
    fi

    # Skip if something else needs it
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
    echo "==> Removing unused Python packages: ${TO_REMOVE[*]}..."
    sudo apt-get remove -y "${TO_REMOVE[@]}"
    sudo apt-get autoremove -y
    echo "    Done."
else
    echo "    No Python packages to remove."
fi

# ── Groups ────────────────────────────────────────────────────────────────────

echo ""
echo "==> All done!"
echo ""
echo "    NOTE: Your user was not removed from the 'input' and 'plugdev' groups."
echo "    These groups may be needed by other hardware (audio, USB devices, etc.)."
echo "    To remove manually if you are sure nothing else needs them:"
echo "      sudo gpasswd -d \$USER input"
echo "      sudo gpasswd -d \$USER plugdev"
