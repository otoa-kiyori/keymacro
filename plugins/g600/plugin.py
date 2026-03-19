"""
plugins/g600/plugin.py — keymacro plugin for the Logitech G600 Gaming Mouse.

Device communication:
  - Hardware state read/written via ratbagctl CLI (libratbag)
  - Software remap (BTN_* macros) via EvdevTranslator background thread
  - evdev is optional: plugin works without it (ratbagctl path only)

Availability:
  - is_available() → True when ratbagctl is installed AND G600 is detected
  - get_install_hint() covers both ratbagd and python3-evdev

plugin_data["g600"] schema (stored in ProfileData):
  {
    "hw_slot": 0,          # hardware slot index (0-2)
    "dpi": 1200,
    "led_mode": "on",
    "led_color": "ffffff",
    "led_duration": 2000,
    "buttons": {
      "0": {"kind": "button", "value": "1"},
      "8": {"kind": "key", "value": "KEY_1"},
      "15": {"kind": "macro", "value": "+KEY_LEFTCTRL KEY_S -KEY_LEFTCTRL"},
      "20": {"kind": "swremap", "value": "BTN_LEFT", "routing_key": "KEY_F21"}
    }
  }
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

from PyQt6.QtWidgets import QWidget

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.plugin_manager import DevicePlugin, DeviceError

if TYPE_CHECKING:
    from core.signals import AppSignals
    from core.profile_store import ProfileData

# ─── Optional evdev import ────────────────────────────────────────────────────

try:
    from plugins.g600.translator import EvdevTranslator
    _EVDEV_OK = True
except ImportError:
    _EVDEV_OK = False

# ─── Constants ────────────────────────────────────────────────────────────────

RATBAGCTL = "/usr/bin/ratbagctl"
ROUTING_KEY_POOL = ["KEY_F21", "KEY_F22", "KEY_F23", "KEY_F24"]

G600_BUTTON_IDS = [
    "LMB", "RMB", "Mid", "Back", "Fwd", "GS", "DPI", "Prof",
    "G9", "G10", "G11", "G12", "G13", "G14",
    "G15", "G16", "G17", "G18", "G19", "G20",
]

# Label → ratbag button index
_LABEL_TO_IDX = {
    "LMB": 0, "RMB": 1, "Mid": 2, "Back": 3, "Fwd": 4,
    "GS": 5, "DPI": 6, "Prof": 7,
    "G9": 8,  "G10": 9,  "G11": 10,
    "G12": 11, "G13": 12, "G14": 13,
    "G15": 14, "G16": 15, "G17": 16,
    "G18": 17, "G19": 18, "G20": 19,
}


# ─── ratbagctl helpers ────────────────────────────────────────────────────────

class RatbagError(Exception):
    pass


def _ratbag(*args: str, timeout: int = 10) -> str:
    try:
        r = subprocess.run(
            [RATBAGCTL] + list(args),
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        if r.returncode != 0:
            raise RatbagError(r.stderr.strip() or r.stdout.strip())
        return r.stdout.strip()
    except FileNotFoundError:
        raise RatbagError(f"ratbagctl not found at {RATBAGCTL}")
    except subprocess.TimeoutExpired:
        raise RatbagError(f"ratbagctl timed out after {timeout}s")


def _discover_device() -> str | None:
    try:
        out = _ratbag("list")
    except RatbagError:
        return None
    for line in out.splitlines():
        if "G600" in line or "g600" in line.lower():
            token = re.split(r"[\s:]+", line.strip())[0].strip()
            return token or None
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    if len(lines) == 1:
        return re.split(r"[\s:]+", lines[0])[0].strip() or None
    return None


def _ratbag_available() -> bool:
    return Path(RATBAGCTL).exists()


# ─── Plugin ───────────────────────────────────────────────────────────────────

class G600Plugin(DevicePlugin):
    """keymacro plugin for the Logitech G600 Gaming Mouse."""

    # Buttons that must never be reassigned — they are hardware mouse clicks.
    # The canvas disables these buttons visually; main_window respects this too.
    LOCKED_BUTTONS: frozenset[str] = frozenset({"LMB", "RMB"})

    def __init__(self):
        self._signals = None
        self._device: str | None = None
        self._translator: Any = None   # EvdevTranslator | None

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "g600"

    @property
    def display_name(self) -> str:
        return "Logitech G600 Gaming Mouse"

    @property
    def description(self) -> str:
        return "G600 via ratbagctl (firmware) + evdev software remap (optional)"

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        try:
            return _ratbag_available() and _discover_device() is not None
        except Exception:
            return False

    def get_install_hint(self) -> str:
        hints = []
        if not _ratbag_available():
            hints.append(
                "Install libratbag:\n"
                "  sudo apt install ratbagd\n"
                "  sudo systemctl enable --now ratbagd"
            )
        if not _EVDEV_OK:
            hints.append(
                "For BTN_* (software remap) macros, also install:\n"
                "  sudo apt install python3-evdev"
            )
        if not hints:
            hints.append("G600 device not detected — is it plugged in?")
        return "\n\n".join(hints)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def activate(self, signals: "AppSignals") -> None:
        self._signals = signals
        self._device = _discover_device()
        if _EVDEV_OK and self._device:
            try:
                self._translator = EvdevTranslator()
                self._translator.start()
            except Exception as e:
                if signals:
                    signals.plugin_error.emit(self.name, f"EvdevTranslator: {e}")

    def deactivate(self) -> None:
        if self._translator is not None:
            try:
                self._translator.stop()
            except Exception:
                pass
            self._translator = None

    # ── Device semantics ──────────────────────────────────────────────────────

    def get_button_ids(self) -> list[str]:
        return list(G600_BUTTON_IDS)

    def get_hw_slot_count(self) -> int:
        return 3

    def get_device_profile(self) -> dict[str, Any]:
        if not self._device:
            self._device = _discover_device()
        if not self._device:
            return {}
        try:
            info = _ratbag(self._device, "info")
            return {"raw_info": info}
        except RatbagError as e:
            return {"error": str(e)}

    def apply_profile(self, profile: "ProfileData") -> None:
        if not self._device:
            self._device = _discover_device()
        if not self._device:
            raise DeviceError("G600 not found — is it plugged in?")

        # Hardware settings from plugin_data (DPI, LED, slot)
        g600_data    = profile.plugin_data.get("g600", {})
        hw_slot      = int(g600_data.get("hw_slot", 0))
        dpi          = int(g600_data.get("dpi", 1200))
        led_mode     = g600_data.get("led_mode", "on")
        led_color    = g600_data.get("led_color", "ffffff")
        led_duration = int(g600_data.get("led_duration", 2000))

        # Button bindings come from profile.bindings["g600"] — label → MacroRef.
        # This is where the macro editor saves assignments (consistent with G13).
        g600_bindings = profile.bindings.get("g600", {})

        routing_map: dict[int, str] = {}   # for EvdevTranslator
        used_routing_keys: set[str] = set()

        try:
            # Always restore primary mouse buttons to their correct hardware actions.
            # A previous session may have remapped them as evdev routing keys.
            _ratbag(self._device, "profile", str(hw_slot),
                    "button", "0", "action", "set", "button", "1")   # LMB → BTN_LEFT
            _ratbag(self._device, "profile", str(hw_slot),
                    "button", "1", "action", "set", "button", "2")   # RMB → BTN_RIGHT
            _ratbag(self._device, "profile", str(hw_slot),
                    "button", "2", "action", "set", "button", "3")   # Mid → BTN_MIDDLE

            for label, macro_ref in g600_bindings.items():
                if label in self.LOCKED_BUTTONS:
                    continue   # never overwrite hardware mouse clicks
                btn_idx = _LABEL_TO_IDX.get(label)
                if btn_idx is None:
                    continue   # unknown label — skip

                tokens    = macro_ref.inline_tokens or []
                token_str = " ".join(tokens)

                # BTN_* tokens require evdev software remap via a routing key
                has_btn = any(t.lstrip("+-").startswith("BTN_") for t in tokens)
                if has_btn and _EVDEV_OK:
                    rkey = self.allocate_routing_key(used_routing_keys)
                    if rkey:
                        used_routing_keys.add(rkey)
                        args = _build_ratbag_args("swremap", token_str, rkey)
                        try:
                            from evdev import ecodes
                            keycode = ecodes.ecodes.get(rkey)
                            if keycode is not None:
                                routing_map[keycode] = token_str
                        except Exception:
                            pass
                    else:
                        args = ["disabled"]
                else:
                    args = _build_ratbag_args("macro", token_str)

                _ratbag(self._device, "profile", str(hw_slot),
                        "button", str(btn_idx), "action", "set", *args)

            # Write DPI
            _ratbag(self._device, "profile", str(hw_slot), "dpi", "set", str(dpi))

            # Write LED
            _ratbag(self._device, "profile", str(hw_slot), "led", "0", "set", "mode", led_mode)
            if led_mode in ("on", "breathing"):
                _ratbag(self._device, "profile", str(hw_slot),
                        "led", "0", "set", "color", led_color)
            if led_mode in ("breathing", "cycle"):
                _ratbag(self._device, "profile", str(hw_slot),
                        "led", "0", "set", "duration", str(led_duration))

            # Activate hardware slot
            _ratbag(self._device, "profile", "active", "set", str(hw_slot))

        except RatbagError as e:
            raise DeviceError(f"ratbagctl error: {e}") from e

        # Update translator routing map
        if self._translator is not None and routing_map:
            self._translator.update_routing_map(routing_map)

    # ── UI ────────────────────────────────────────────────────────────────────

    def create_canvas(self, parent: QWidget | None = None) -> QWidget:
        from plugins.g600.canvas import G600Canvas
        return G600Canvas(self.name, self._signals, parent)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def allocate_routing_key(self, used_keys: set[str]) -> str | None:
        """Return the next unused routing key from the pool."""
        for k in ROUTING_KEY_POOL:
            if k not in used_keys:
                return k
        return None


# ─── Build ratbagctl args ─────────────────────────────────────────────────────

def _build_ratbag_args(kind: str, value: str, routing_key: str = "") -> list[str]:
    if kind == "none":
        return ["disabled"]
    if kind == "swremap":
        return ["macro", routing_key] if routing_key else ["disabled"]
    if kind == "special":
        if value in ("disable", "disabled"):
            return ["disabled"]
        return ["special", value]
    if kind == "button":
        return ["button", value]
    if kind in ("key", "macro"):
        tokens = value.split()
        return ["macro"] + tokens if tokens else ["disabled"]
    return ["disabled"]
