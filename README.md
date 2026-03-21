# KeyMacro

A KDE Plasma Wayland tray application for mapping macros to extra buttons on gaming peripherals. Supports multiple devices simultaneously and automatically switches macro profiles based on whichever application is in focus.

---

## What it does

- **Macro assignment** — bind any button on a supported device to a macro: key sequences, mouse clicks, holds, releases, waits, or combinations
- **Profiles** — create multiple macro profiles and switch between them manually or automatically
- **Auto-switching** — watches the active window via KWin and switches to the matching profile automatically (e.g. one profile for your browser, another for your game)
- **Multi-device** — multiple devices can be active at the same time, all sharing a single profile set
- **Device feedback** — supported devices display the active profile name on their hardware display (e.g. G13 LCD)
- **System tray** — lives in the tray, out of your way; open the editor only when you need it

---

## Supported devices

| Plugin | Device | Features | Extra dependencies |
|---|---|---|---|
| `g13` | Logitech G13 Advanced Gameboard | Button macros, LCD profile display | `pyusb`, `evdev`, `Pillow` |
| `g600` | Logitech G600 Gaming Mouse | Button macros | `evdev` |

Additional devices can be added by writing a plugin — see [`plugins/README.md`](plugins/README.md).

### Plugin architecture

keymacro uses a pluggable device architecture. Each plugin lives in its own directory under `plugins/` and carries everything it needs:

```
plugins/
├── g13/
│   ├── plugin.py                  # DevicePlugin subclass
│   ├── raw_capture.py             # USB HID capture thread
│   ├── lcd.py                     # G13 LCD renderer (Pillow-based)
│   ├── 99-keymacro-g13.rules      # udev rules (installed by install.sh)
│   └── requirements.txt           # pyusb, evdev, Pillow
└── g600/
    ├── plugin.py                  # DevicePlugin subclass
    ├── raw_capture.py             # evdev capture thread
    ├── 99-keymacro-g600.rules     # udev rules (installed by install.sh)
    └── requirements.txt           # evdev
```

The core (`core/`, `ui/`) has **zero** device-specific imports. Plugins are discovered and loaded at runtime via `importlib`.

### Communication channels

```
Device → Core   raw button events → macro execution  (always present)
Core → Device   profile name → device feedback        (optional, per plugin)
```

The **core→device feedback** channel is used by the G13 to update its LCD whenever the active profile changes. The same framework is ready for future use — e.g. G600 LED colour switching.

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

All other dependencies are installed automatically by `scripts/install.sh`.

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/otoa-kiyori/keymacro.git
cd keymacro
```

### 2. Run the installer

```bash
bash scripts/install.sh
```

The installer handles everything in order:

| Step | What it does |
|---|---|
| 1 | Verifies sudo access (prompts once, caches for the session) |
| 2 | Installs Python dependencies via apt (PyQt6, PyYAML, pyusb, evdev, Pillow) |
| 3 | Installs udev rules for core and all device plugins |
| 4 | Loads the `uinput` kernel module and makes it persist across reboots |
| 5 | Adds your user to the `input` and `plugdev` groups |
| 6 | Creates a launcher script at `~/bin/keymacro` |
| 7 | Installs a KDE autostart entry (keymacro starts with your desktop) |
| 8 | Adds **KeyMacro** to the KDE application menu |

### 3. Log out and back in

Group membership (`input`, `plugdev`) takes effect on the next login.

### 4. Launch

After logging back in, keymacro starts automatically with KDE and appears in the system tray. You can also launch it manually:

```bash
keymacro
```

Or find **KeyMacro** in the KDE application menu under Utilities / Games.

---

## Uninstall

```bash
bash scripts/uninstall.sh
```

The uninstaller:

| Step | What it does |
|---|---|
| 1 | Verifies sudo access |
| 2 | Removes the KDE autostart and application menu entries |
| 3 | Removes the `~/bin/keymacro` launcher |
| 4 | Removes all keymacro udev rules and reloads udev |
| 5 | Removes `/etc/modules-load.d/keymacro.conf` |
| 6 | **Intelligently** removes Python packages — queries `apt-cache rdepends` at runtime and only removes packages that nothing else on your system needs |

> **Note on groups:** The uninstaller does **not** remove you from the `input` and `plugdev` groups, as other hardware may need them. Manual removal instructions are printed at the end if needed.

To also remove your saved profiles and configuration:

```bash
rm -rf ~/.config/keymacro
```

---

## Project layout

```
keymacro/
├── keymacro.py              # Entry point
├── requirements.txt         # Core deps: PyQt6, PyYAML
├── core/                    # Framework: signals, profiles, macro library,
│   │                        #   plugin manager, feedback thread
│   ├── app.py               # Top-level controller
│   ├── feedback_thread.py   # Reusable core→device feedback thread base
│   ├── plugin_manager.py    # DevicePlugin ABC + plugin discovery
│   ├── macro_library.py     # Named macro store
│   ├── macro_queue.py       # Single worker thread for macro execution
│   ├── profile_store.py     # Profile persistence
│   ├── signals.py           # Central Qt signal bus
│   └── window_watcher.py    # KWin D-Bus integration for auto-switching
├── ui/                      # Qt widgets: tray, main window, macro editor
├── plugins/
│   ├── g13/                 # Logitech G13 plugin (USB HID + LCD feedback)
│   └── g600/                # Logitech G600 plugin (evdev)
├── scripts/
│   ├── install.sh           # Comprehensive installer
│   ├── uninstall.sh         # Intelligent uninstaller
│   └── 99-keymacro.rules    # Core udev rule (uinput)
└── storage/                 # .gitkeep — runtime data at ~/.config/keymacro/
```

---

## Security notes

- **No runtime sudo** — keymacro runs entirely as a normal user after installation. Device access is granted via udev rules and group membership.
- **Config privacy** — `~/.config/keymacro/` is created with mode `0700` (owner-only).
- **Safe YAML** — profiles are loaded with `yaml.safe_load` (no code execution).
- **Named system files** — every file keymacro installs into system directories is prefixed with `keymacro` so you always know what belongs to this app vs the OS.

---

## Credits

**KeyMacro** was conceived and directed by its author.

The codebase — architecture, implementation, all device plugins, the installer, the uninstaller, documentation, and this README — was written by **Claude Sonnet 4.6** by [Anthropic](https://www.anthropic.com/claude), who contributed approximately 99.99% of all work. The remaining 0.01% was the author saying *"yes, do that"*, *"make it better"*, and *"you super smart Claude Sonnet-san!!"*

### Development methodology

The author practised **Backseat Programming** — not a single line of code was written by hand, yet there was a strong opinion about absolutely everything: the architecture, the naming, the security model, the install experience, which button should be called CIRCLE and not TOP, and whether the LCD should show the profile name. It turns out that having opinions about everything is, in fact, the hardest part.

> Built with [Claude Code](https://claude.ai/code) — Anthropic's agentic coding assistant.
