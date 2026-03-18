"""
plugins/g13/plugin.py — keymacro plugin for the Logitech G13 Gameboard.

Device communication:
  - Read/write ~/.g13/g13.bind (text bind file)
  - Profile switching via named FIFO at /tmp/g13-0 (g13d command pipe)
  - No Python package dependencies beyond stdlib

Availability:
  - is_available() → True when g13d pipe exists OR bind file exists
    (allows editing offline; switching requires the pipe)
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, TYPE_CHECKING

from PyQt6.QtWidgets import QWidget

# DevicePlugin is imported from core at load time.
# The PluginManager passes the ABC via the module load mechanism,
# but we need to import it here so Python's type system is happy.
# This import is safe — core has no device-specific deps.
import sys
import os
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.plugin_manager import DevicePlugin, DeviceError

if TYPE_CHECKING:
    from core.signals import AppSignals
    from core.profile_store import ProfileData

# ─── Paths ────────────────────────────────────────────────────────────────────

BIND_FILE = Path.home() / ".g13" / "g13.bind"
G13_PIPE  = Path("/tmp/g13-0")

# All button IDs the G13 exposes
G13_BUTTON_IDS = [
    "G1","G2","G3","G4","G5","G6","G7",
    "G8","G9","G10","G11","G12","G13","G14",
    "G15","G16","G17","G18","G19",
    "G20","G21","G22",
    "L1","L2","L3","L4",
    "M1","M2","M3","MR",
    "STICK_UP","STICK_DOWN","STICK_LEFT","STICK_RIGHT",
    "LEFT","BD","TOP",
]


# ─── Bind file I/O ────────────────────────────────────────────────────────────

def _parse_bind_file(path: Path) -> dict[str, dict[str, str]]:
    """Parse g13d bind file → {profile_name: {key: value}}"""
    profiles: dict[str, dict[str, str]] = {"default": {}}
    current = "default"
    if not path.exists():
        return profiles
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if not parts:
            continue
        cmd = parts[0].lower()
        if cmd == "profile" and len(parts) == 2:
            current = parts[1].strip()
            if current not in profiles:
                profiles[current] = {}
        elif cmd == "bind" and len(parts) == 2:
            rest = parts[1].split(None, 1)
            if len(rest) == 2:
                profiles[current][rest[0].strip()] = rest[1].strip()
    return profiles


def _write_bind_file(path: Path, profiles: dict[str, dict[str, str]]) -> None:
    """Write profiles back to g13d bind file format. 'default' is written last."""
    lines: list[str] = []
    for name, bindings in profiles.items():
        if name == "default":
            continue
        lines.append(f"profile {name}")
        for key, val in bindings.items():
            lines.append(f"bind {key} {val}")
    lines.append("profile default")
    for key, val in profiles.get("default", {}).items():
        lines.append(f"bind {key} {val}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ─── Plugin ───────────────────────────────────────────────────────────────────

class G13Plugin(DevicePlugin):
    """keymacro plugin for the Logitech G13 Gameboard."""

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "g13"

    @property
    def display_name(self) -> str:
        return "Logitech G13 Gameboard"

    @property
    def description(self) -> str:
        return "G13 via g13d daemon — FIFO pipe + bind file"

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        try:
            return G13_PIPE.exists() or BIND_FILE.exists()
        except Exception:
            return False

    def get_install_hint(self) -> str:
        return (
            "Install and start the g13d userspace driver:\n"
            "  https://github.com/ecraven/g13\n\n"
            "Then enable the systemd service:\n"
            "  sudo systemctl enable --now g13\n\n"
            "Bind file will be created at: ~/.g13/g13.bind"
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def activate(self, signals: "AppSignals") -> None:
        self._signals = signals

    def deactivate(self) -> None:
        pass  # No threads or exclusive resources to release

    # ── Device semantics ──────────────────────────────────────────────────────

    def get_button_ids(self) -> list[str]:
        return list(G13_BUTTON_IDS)

    def get_device_profile(self) -> dict[str, Any]:
        """Read bind file and return as plugin_data["g13"] dict."""
        try:
            return {"profiles": _parse_bind_file(BIND_FILE)}
        except Exception as e:
            return {"error": str(e)}

    def apply_profile(self, profile: "ProfileData") -> None:
        """
        Write the profile's bindings to the bind file and switch via pipe.

        profile.plugin_data["g13"]["profiles"] contains the full multi-profile
        bind file state. The profile name to activate is profile.name.

        If plugin_data is absent (new profile), only the active profile's
        bindings from profile.bindings are written.
        """
        g13_data = profile.plugin_data.get("g13", {})

        if "profiles" in g13_data:
            # Full bind file state stored — write it all
            profiles_raw = g13_data["profiles"]
        else:
            # Build from core bindings — simple key:value dict
            raw_bindings: dict[str, str] = {}
            for btn_id, macro_ref in profile.bindings.items():
                if macro_ref.inline_tokens:
                    # Convert token sequence to g13d bind value
                    # g13d uses KEY_X+KEY_Y format for combos, not our space-separated format
                    raw_bindings[btn_id] = _tokens_to_g13d(macro_ref.inline_tokens)
                elif macro_ref.library_name:
                    # Can't resolve library references here — skip
                    pass
            profiles_raw = {profile.name: raw_bindings, "default": raw_bindings}

        try:
            _write_bind_file(BIND_FILE, profiles_raw)
        except Exception as e:
            raise DeviceError(f"Failed to write bind file: {e}") from e

        # Switch profile via FIFO if g13d is running
        if G13_PIPE.exists():
            try:
                G13_PIPE.write_text(f"profile {profile.name}\n", encoding="utf-8")
            except Exception as e:
                raise DeviceError(f"Failed to switch profile via pipe: {e}") from e

    # ── UI ────────────────────────────────────────────────────────────────────

    def create_canvas(self, parent: QWidget | None = None) -> QWidget:
        from plugins.g13.canvas import G13Canvas
        canvas = G13Canvas(self.name, self._signals, parent)
        return canvas

    # ── Helpers ───────────────────────────────────────────────────────────────

    def get_raw_profiles(self) -> dict[str, dict[str, str]]:
        """Return all profiles from bind file as raw dicts."""
        return _parse_bind_file(BIND_FILE)

    def switch_profile_via_pipe(self, profile_name: str) -> None:
        """Send a profile switch command directly to g13d pipe."""
        if not G13_PIPE.exists():
            raise DeviceError("/tmp/g13-0 not found — is g13d running?")
        try:
            G13_PIPE.write_text(f"profile {profile_name}\n", encoding="utf-8")
        except Exception as e:
            raise DeviceError(f"Pipe write failed: {e}") from e

    def reload_service(self) -> None:
        """Attempt to restart the g13 systemd service (requires sudo)."""
        try:
            subprocess.run(
                ["sudo", "systemctl", "restart", "g13"],
                check=True, timeout=10
            )
        except subprocess.CalledProcessError as e:
            raise DeviceError("systemctl restart g13 failed (no sudo?)") from e


# ─── Token format conversion ──────────────────────────────────────────────────

def _tokens_to_g13d(tokens: list[str]) -> str:
    """
    Convert keymacro token sequence to g13d bind value format.

    g13d uses KEY_LEFTCTRL+KEY_B for modifier combos (not space-separated).
    Simple single-key taps: KEY_A → KEY_A
    Modifier combos: +KEY_LEFTCTRL KEY_B -KEY_LEFTCTRL → KEY_LEFTCTRL+KEY_B
    """
    # Filter out hold/release tokens and collect keys in order
    keys: list[str] = []
    for tok in tokens:
        if tok.startswith('+'):
            keys.append(tok[1:])
        elif tok.startswith('-'):
            pass  # release — skip
        elif tok.startswith('t'):
            pass  # wait — g13d doesn't support waits; skip
        elif tok.startswith('KEY_') or tok.startswith('BTN_'):
            keys.append(tok)
    return "+".join(keys) if keys else ""
