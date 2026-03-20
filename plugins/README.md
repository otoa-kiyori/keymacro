# keymacro Plugin Authoring Guide

Each plugin lives in its own subdirectory under `plugins/`:

```
plugins/
└── mydevice/
    ├── plugin.py         # required — DevicePlugin subclass
    ├── requirements.txt  # plugin-specific pip deps (can be empty)
    └── README.md         # optional
```

## Minimal plugin.py

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.plugin_manager import DevicePlugin, DeviceError
from PyQt6.QtWidgets import QWidget, QLabel

class MyDevicePlugin(DevicePlugin):

    @property
    def name(self) -> str:
        return "mydevice"

    @property
    def display_name(self) -> str:
        return "My Custom Device"

    @property
    def description(self) -> str:
        return "One-line description"

    def is_available(self) -> bool:
        return True   # or check device presence

    def get_install_hint(self) -> str:
        return "sudo apt install <package>"

    def activate(self, signals) -> None:
        self._signals = signals
        # start background thread, open device, etc.

    def deactivate(self) -> None:
        pass  # stop threads, release device

    def get_button_ids(self) -> list[str]:
        return ["BTN1", "BTN2", "BTN3"]

    def get_device_profile(self) -> dict:
        return {}

    def apply_profile(self, profile) -> None:
        # Read profile.bindings and profile.plugin_data[self.name]
        # Write to device
        pass

    def create_canvas(self, parent=None) -> QWidget:
        # Return a QWidget showing the device layout.
        # When a button is clicked, emit:
        #   self._signals.button_clicked.emit(self.name, button_id)
        lbl = QLabel("My Device Canvas")
        return lbl
```

## Button clicked flow

1. Canvas button is clicked → `signals.button_clicked.emit(plugin_name, button_id)`
2. `MainWindow._on_button_clicked()` receives it
3. Opens `ButtonEditDialog` with `MacroEditorWidget`
4. User edits token sequence → saved to `ProfileStore` → `signals.profile_saved` emitted

## Token format

```
KEY_A           tap A
+KEY_LEFTCTRL   hold Ctrl
-KEY_LEFTCTRL   release Ctrl
BTN_LEFT        click left mouse button (requires software remap)
t300            wait 300 ms
```

## Dependency isolation

- Import device-specific packages **only inside plugin.py** (and sub-modules).
- Wrap imports in try/except ImportError:

```python
try:
    import evdev
    _EVDEV_OK = True
except ImportError:
    _EVDEV_OK = False
```

- In `is_available()`, return False if required deps are missing.
- In `get_install_hint()`, explain how to install them.
- **Never** import evdev, pyusb, or other device libs in `core/` or `ui/`.
