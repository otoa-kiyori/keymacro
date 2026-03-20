# keymacro

A KDE Plasma Wayland tray application for mapping macros to extra buttons on gaming peripherals. Supports multiple devices simultaneously and automatically switches macro profiles based on whichever application is in focus.

## What it does

- **Macro assignment** — bind any button on a supported device to a macro: key sequences, mouse clicks, holds, releases, waits, or combinations thereof
- **Profiles** — create multiple macro profiles and switch between them manually or automatically
- **Auto-switching** — keymacro watches the active window via KWin and switches to the matching profile automatically (e.g. one profile for your browser, another for your game)
- **Multi-device** — multiple devices can be active at the same time, all sharing a single profile set
- **System tray** — lives in the tray, out of your way; open the editor only when you need it

### Supported devices

| Plugin | Device | Extra dependencies |
|---|---|---|
| `g13` | Logitech G13 | `pyusb`, `evdev` |
| `g600` | Logitech G600 | `evdev` |

Additional devices can be added by writing a plugin (see [`plugins/README.md`](plugins/README.md)).

### Macro token language

Macros are sequences of space-separated tokens:

| Token | Meaning |
|---|---|
| `A`, `Enter`, `F5` | Tap key (press + release) |
| `+LeftCtrl` | Hold key down |
| `-LeftCtrl` | Release held key |
| `+LeftCtrl C -LeftCtrl` | Ctrl+C |
| `t50` | Wait 50 ms |
| `BTN_LEFT`, `LeftButton` | Mouse button tap |

---

## Requirements

- KDE Plasma on Wayland
- Python 3.13+
- PyQt6 ≥ 6.3
- PyYAML ≥ 6.0

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/otoa-kiyori/keymacro.git
cd keymacro
```

### 2. Create a virtual environment and install core dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Install plugin dependencies

Install dependencies only for the devices you use.

**Logitech G600** (requires `evdev`):
```bash
pip install -r plugins/g600/requirements.txt
# or via apt:
sudo apt install python3-evdev
```

**Logitech G13** (requires `evdev` + `pyusb`):
```bash
pip install -r plugins/g13/requirements.txt
# or via apt:
sudo apt install python3-evdev python3-usb
```

### 4. Grant device access (udev rules)

Raw device access requires a udev rule so you don't need to run as root.

Create `/etc/udev/rules.d/99-keymacro.rules`:

```
# Logitech G600
SUBSYSTEM=="input", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="c24a", GROUP="input", MODE="0664"

# Logitech G13
SUBSYSTEM=="usb", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="c21c", GROUP="plugdev", MODE="0664"
```

Then reload udev and re-plug your device:
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Add your user to the relevant groups if not already a member:
```bash
sudo usermod -aG input,plugdev $USER
# Log out and back in for group changes to take effect
```

### 5. Run

```bash
source .venv/bin/activate   # if not already active
python keymacro.py
```

keymacro appears in the system tray. Click the tray icon to open the macro editor.

### Autostart with KDE Plasma

To have keymacro start automatically with your desktop session, create an autostart entry:

```bash
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/keymacro.desktop << EOF
[Desktop Entry]
Type=Application
Name=keymacro
Exec=/path/to/keymacro/.venv/bin/python /path/to/keymacro/keymacro.py
Hidden=false
X-KDE-AutostartEnabled=true
EOF
```

Replace `/path/to/keymacro` with the actual path to your clone.

---

## Uninstall

### 1. Remove the autostart entry (if created)

```bash
rm ~/.config/autostart/keymacro.desktop
```

### 2. Remove configuration and saved data

```bash
rm -rf ~/.keymacro
rm -rf ~/.config/keymacro
```

### 3. Remove the udev rules (if added)

```bash
sudo rm /etc/udev/rules.d/99-keymacro.rules
sudo udevadm control --reload-rules
```

### 4. Delete the repository

```bash
rm -rf /path/to/keymacro
```

That's it — no system-wide packages are installed, so nothing else needs to be cleaned up.

---

## Project layout

```
keymacro/
├── keymacro.py          # Entry point
├── requirements.txt     # Core deps: PyQt6, PyYAML
├── core/                # Framework: signals, profiles, macro library, plugin manager
├── ui/                  # Qt widgets: tray, main window, macro editor
├── plugins/
│   ├── g13/             # Logitech G13 plugin
│   ├── g600/            # Logitech G600 plugin
│   └── README.md        # Plugin authoring guide
└── storage/             # Runtime data lives at ~/.keymacro/ (not here)
```
