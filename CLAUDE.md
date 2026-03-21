# keymacro — Project Instructions

## Overview
KDE Plasma Wayland app for managing extra input device key mapping and macros.
Pluggable device architecture: core has zero device-specific dependencies.

## Stack
- **Python 3.13**
- **PyQt6 ≥ 6.3** — GUI + QSystemTrayIcon (StatusNotifierItem, Wayland-native)
- **Device plugins** in `plugins/<name>/` — each has its own `requirements.txt`

## Running
```bash
cd keymacro
python keymacro.py
```

## Layout
```
keymacro/
├── keymacro.py          # Entry point
├── requirements.txt     # Core only: PyQt6
├── core/                # Framework: signals, profile store, macro library, plugin manager
├── ui/                  # Qt widgets: main window, tray, panels, macro editor
├── plugins/
│   ├── g13/             # Logitech G13 plugin (no extra deps)
│   └── g600/            # Logitech G600 plugin (requires python3-evdev)
└── storage/             # .gitkeep; runtime data at ~/.config/keymacro/
```

## Key rules
- `core/` and `ui/` MUST NOT import any device-specific packages (evdev, pyusb, etc.)
- Plugin deps isolated to `plugins/<name>/requirements.txt` only
- Missing plugin deps → plugin reports `is_available()=False` with install hint; never crashes core
- Config stored under `~/.config/keymacro/` (XDG via QStandardPaths)
