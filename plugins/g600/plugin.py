"""
plugins/g600/plugin.py — keymacro plugin for the Logitech G600 Gaming Mouse.

Device communication:
  - Pure evdev: grabs both G600 interfaces (event-mouse + if01-event-kbd)
    exclusively via G600RawCapture and re-emits all input through uinput.
  - No external daemon or system service required.

Button→code mapping is hard-coded from hardware discovery (2026-03-18).
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Any, TYPE_CHECKING


from PyQt6.QtWidgets import QWidget

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.plugin_manager import DevicePlugin, ButtonSpec  # type: ignore

if TYPE_CHECKING:
    from core.signals import AppSignals       # type: ignore

try:
    from plugins.g600.raw_capture import G600RawCapture, _MOUSE_GLOB, _KBD_GLOB, _IF01_GLOB
    from plugins.g600.button_map import BUTTONS as _G600_BUTTON_DEFS
    _EVDEV_OK = True
except ImportError:
    _EVDEV_OK = False
    _G600_BUTTON_DEFS = []

# ButtonSpec list generated from buttons.csv — no manual maintenance needed
_G600_BUTTON_SPECS: list[ButtonSpec] = [
    ButtonSpec(b.button_id, locked=b.locked, zone=b.zone)
    for b in _G600_BUTTON_DEFS
]


def _g600_present() -> bool:
    return (bool(glob.glob(_MOUSE_GLOB))
            and bool(glob.glob(_KBD_GLOB))
            and bool(glob.glob(_IF01_GLOB)))


class G600Plugin(DevicePlugin):
    """Logitech G600 — pure evdev, no external daemon required."""

    def __init__(self) -> None:
        self._signals: Any = None
        self._capture: Any = None   # G600RawCapture | None

    @property
    def name(self) -> str:
        return "g600"

    @property
    def display_name(self) -> str:
        return "Logitech G600 Gaming Mouse"

    @property
    def description(self) -> str:
        return "G600 via pure evdev — no external daemon required"

    def is_available(self) -> bool:
        return _EVDEV_OK and _g600_present()

    def get_install_hint(self) -> str:
        if not _EVDEV_OK:
            return (
                "python3-evdev is required:\n"
                "  pip install evdev\n"
                "  or: sudo apt install python3-evdev"
            )
        return "G600 not detected — is it plugged in?"

    def activate(self, signals: "AppSignals") -> None:
        self._signals = signals
        if not _EVDEV_OK:
            return
        try:
            self._capture = G600RawCapture()
            self._capture.start()
            plugin_name = self.name
            self._capture.add_persistent_callback(
                lambda btn_id, pressed: signals.button_event.emit(plugin_name, btn_id, pressed)
            )
        except Exception as e:
            self._capture = None
            if signals:
                signals.plugin_error.emit(self.name, f"G600RawCapture: {e}")
            return

        # Thread setup (evdev grab, UInput creation, etc.) runs asynchronously.
        # Check 400 ms later whether _setup() crashed before the event loop started.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(400, lambda: self._check_capture_health(signals))

    def _check_capture_health(self, signals: "AppSignals") -> None:
        if self._capture is not None and not self._capture.is_alive():
            err = self._capture.error or "Capture thread exited unexpectedly (no error recorded)."
            # Do NOT clear self._capture — preserve it so _get_capture() still
            # returns the dead thread and its .error is visible in the debug dialog.
            if signals:
                signals.plugin_error.emit(self.name, f"Capture failed: {err}")

    def deactivate(self) -> None:
        if self._capture is not None:
            self._capture.stop()
            self._capture.join(timeout=2.0)   # wait for _teardown() to close evdev fds
            self._capture = None

    def get_button_specs(self) -> list[ButtonSpec]:
        return list(_G600_BUTTON_SPECS)

    def _get_capture(self):
        return self._capture

    def get_hw_slot_count(self) -> int:
        return 1

    def get_device_profile(self) -> dict[str, Any]:
        return {}

    def create_canvas(self, parent: QWidget | None = None) -> QWidget:
        from plugins.g600.canvas import G600Canvas  # type: ignore
        return G600Canvas(self.name, self._signals, parent)
