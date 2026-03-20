"""
plugins/g13/plugin.py — keymacro plugin for the Logitech G13 Gameboard.

Device communication:
  - Pure USB HID via pyusb — no g13d daemon, no bind file, no FIFO.
  - G13HidCapture reads 8-byte interrupt reports directly from USB endpoint
    0x81 and executes macro token sequences via a uinput virtual keyboard.

Availability:
  - is_available() → True when pyusb + evdev are installed AND G13 is found.

Profile switch:
  - Builds press_map / release_map from profile bindings.
  - Calls G13HidCapture.update_routing_map() — instant, no subprocess.

Button down and up:
  - Each button label can have a separate press macro and release macro.
  - Currently the UI only edits press macros; release macros default to "".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from PyQt6.QtWidgets import QWidget

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.plugin_manager import DevicePlugin, ButtonSpec  # type: ignore

if TYPE_CHECKING:
    from core.signals import AppSignals      # type: ignore

# ── Optional deps ─────────────────────────────────────────────────────────────

try:
    import usb.core as _usb_core
    _USB_OK = True
except ImportError:
    _USB_OK = False

try:
    import evdev as _evdev
    _EVDEV_OK = True
except ImportError:
    _EVDEV_OK = False

try:
    from plugins.g13.button_map import BUTTONS as _G13_BUTTON_DEFS
    _BTN_MAP_OK = True
except ImportError:
    _BTN_MAP_OK = False
    _G13_BUTTON_DEFS = []

def _g13_present() -> bool:
    if not _USB_OK:
        return False
    try:
        return _usb_core.find(idVendor=0x046d, idProduct=0xc21c) is not None
    except Exception:
        return False

# ── Button specs — generated from buttons.csv ─────────────────────────────────

_G13_BUTTON_SPECS: list[ButtonSpec] = [
    ButtonSpec(
        b.button_id,
        supports_release=(b.zone == "stick"),
        locked=b.locked,
        zone=b.zone,
    )
    for b in _G13_BUTTON_DEFS
]


# ── Plugin ────────────────────────────────────────────────────────────────────

class G13Plugin(DevicePlugin):
    """Logitech G13 — pure USB HID via pyusb, zero g13d dependency."""

    def __init__(self) -> None:
        self._signals: Any = None
        self._capture: Any = None   # G13HidCapture | None

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "g13"

    @property
    def display_name(self) -> str:
        return "Logitech G13 Gameboard"

    @property
    def description(self) -> str:
        return "G13 via pure USB HID — no g13d daemon required"

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return _USB_OK and _EVDEV_OK and _g13_present()

    def get_install_hint(self) -> str:
        parts = []
        if not _USB_OK:
            parts.append(
                "pyusb is required:\n"
                "  pip install pyusb\n"
                "  or: sudo apt install python3-usb"
            )
        if not _EVDEV_OK:
            parts.append(
                "python3-evdev is required:\n"
                "  pip install evdev\n"
                "  or: sudo apt install python3-evdev"
            )
        if _USB_OK and _EVDEV_OK and not _g13_present():
            parts.append("G13 not detected — is it plugged in?")
        if not parts:
            parts.append(
                "G13 USB access may require a udev rule:\n"
                '  SUBSYSTEM=="usb", ATTRS{idVendor}=="046d", '
                'ATTRS{idProduct}=="c21c", MODE="0666"\n'
                "  Save to /etc/udev/rules.d/99-g13.rules and reload udev."
            )
        return "\n\n".join(parts)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def activate(self, signals: "AppSignals") -> None:
        self._signals = signals
        if not (self._USB_OK() and _EVDEV_OK and _g13_present()):
            return
        self._start_capture(signals)

    @staticmethod
    def _USB_OK() -> bool:
        return _USB_OK

    def _start_capture(self, signals: "AppSignals") -> None:
        try:
            from plugins.g13.raw_capture import G13RawCapture  # type: ignore
            self._capture = G13RawCapture()
            self._capture.start()
        except Exception as e:
            self._capture = None
            if signals:
                signals.plugin_error.emit(self.name, f"G13RawCapture: {e}")
            return

        # Thread setup (USB detach, UInput creation, etc.) runs asynchronously.
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
            self._capture.join(timeout=2.0)   # wait for _teardown() to release USB
            self._capture = None

    def _hw_reset(self) -> None:
        try:
            import usb.core
            dev = usb.core.find(idVendor=0x046d, idProduct=0xc21c)
            if dev is not None:
                dev.reset()
        except Exception:
            pass

    # ── Device semantics ──────────────────────────────────────────────────────

    def get_button_specs(self) -> list[ButtonSpec]:
        return list(_G13_BUTTON_SPECS)

    def _get_capture(self):
        return self._capture

    def get_hw_slot_count(self) -> int:
        return 1

    def get_device_profile(self) -> dict[str, Any]:
        return {"capture_running": self._capture is not None}

    # ── UI ────────────────────────────────────────────────────────────────────

    def create_canvas(self, parent: QWidget | None = None) -> QWidget:
        from plugins.g13.canvas import G13Canvas  # type: ignore
        return G13Canvas(self.name, self._signals, parent)

