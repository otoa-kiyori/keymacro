"""
core/plugin_manager.py — DevicePlugin ABC and PluginManager for keymacro.

Plugin discovery:
  - Scans plugins/ directory for subdirs containing plugin.py
  - Loads each via importlib.util.spec_from_file_location into an isolated
    module namespace (NOT added to sys.modules)
  - All exceptions during load are caught — a plugin with missing deps
    (ImportError for evdev, etc.) is marked unavailable instead of crashing core
  - is_available() is a second gate: checks device presence at runtime

Plugin contract (DevicePlugin ABC):
  - Identity:    name, display_name, description
  - Availability: is_available(), get_install_hint()
  - Lifecycle:   activate(signals), deactivate(), _get_capture()
  - Device:      get_button_specs(), get_device_profile()
  - Profile:     apply_profile() — provided by base class; no override needed
  - UI:          create_canvas(), create_settings_widget() [optional]
"""

from __future__ import annotations

import importlib.util
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PyQt6.QtWidgets import QWidget

if TYPE_CHECKING:
    from core.signals import AppSignals
    from core.profile_store import ProfileData
    from core.macro_library import MacroLibrary, NamedMacro

PLUGINS_DIR = Path(__file__).parent.parent / "plugins"


# ─── Button spec ──────────────────────────────────────────────────────────────

@dataclass
class ButtonSpec:
    """Metadata for a single physical button exposed by a plugin."""
    id: str                         # unique key: "G9", "LMB", "STICK_UP"
    locked: bool = False            # True = never reassignable (e.g. LMB, RMB)
    supports_release: bool = False  # True = separate release macro supported
    zone: str = "default"           # visual grouping: "thumb", "main", "control"


# ─── Exceptions ───────────────────────────────────────────────────────────────

class DeviceError(Exception):
    """Raised by apply_profile() or get_device_profile() on device failure."""


# ─── Abstract base ────────────────────────────────────────────────────────────

class DevicePlugin(ABC):
    """
    Abstract base class for all keymacro device plugins.

    Lifecycle:
        1. PluginManager instantiates the plugin (no heavy work in __init__).
        2. is_available() → False means show as "unavailable" in the plugin panel.
        3. activate(signals) called when user selects / enables this plugin.
        4. deactivate() called on switch-away or app exit.

    Thread safety:
        apply_profile() may be called from a worker thread.
        All UI-creating methods are called from the main Qt thread.
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Short machine name matching the plugin directory, e.g. 'g13'."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name shown in UI, e.g. 'Logitech G13 Gameboard'."""

    @property
    @abstractmethod
    def description(self) -> str:
        """One-line description of the device."""

    # ── Availability ──────────────────────────────────────────────────────────

    @abstractmethod
    def is_available(self) -> bool:
        """
        Return True if dependencies are installed AND the device is connected.
        Must not raise; return False on any error.
        Called on startup and on re-scan.
        """

    @abstractmethod
    def get_install_hint(self) -> str:
        """
        Human-readable instructions for resolving unavailability.
        Shown in PluginPanel when is_available() returns False.
        """

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @abstractmethod
    def activate(self, signals: "AppSignals") -> None:
        """
        Called when this plugin becomes the active device.
        Start background threads, grab evdev, connect to daemon, etc.
        Store the signals reference for emitting device events.
        """

    @abstractmethod
    def deactivate(self) -> None:
        """
        Called before switching to another plugin or on app exit.
        Stop background threads, ungrab evdev, close IPC pipes.
        Must not raise.
        """

    def reset(self) -> None:
        """
        Full device reset: deactivate capture → hardware USB reset → re-activate.

        Plugins override _hw_reset() to add USB-level cycling.  The default
        performs a pure soft reset (stop + restart capture, no USB cycle).
        """
        signals = getattr(self, "_signals", None)
        self.deactivate()
        self._hw_reset()
        if signals is not None:
            self.activate(signals)

    def _hw_reset(self) -> None:
        """
        Hardware-level USB reset hook.  Called by reset() between deactivate()
        and activate().  Default is a no-op (pure soft reset).
        Override in plugin subclass to add device-specific USB cycling.
        """

    # ── Device semantics ──────────────────────────────────────────────────────

    @abstractmethod
    def get_button_specs(self) -> list[ButtonSpec]:
        """
        Return metadata for every physical button this device exposes.
        Locked buttons (e.g. LMB, RMB) are included but never routed.
        """

    def get_button_ids(self) -> list[str]:
        """Convenience: return just the id strings from get_button_specs()."""
        return [s.id for s in self.get_button_specs()]

    @abstractmethod
    def get_device_profile(self) -> dict[str, Any]:
        """
        Read and return the current device state as a dict.
        Schema is device-specific (stored in ProfileData.plugin_data[self.name]).
        Returns {} if device not available.
        """

    @abstractmethod
    def _get_capture(self):
        """Return the running capture thread, or None if not active."""

    def apply_profile(self, profile: "ProfileData",
                      library: "MacroLibrary | None" = None) -> None:
        """
        Apply the given profile to the physical device.

        Resolves each button's MacroRef (macro name) to a NamedMacro from
        the library, skips locked buttons, and calls capture.update_routing_map().
        Plugins do not need to override this.
        """
        capture = self._get_capture()
        if capture is None:
            return
        specs = {s.id: s for s in self.get_button_specs()}
        routing: dict[str, "NamedMacro"] = {}
        plugin_bindings = profile.bindings.get(self.name, {})
        for btn_id, macro_ref in plugin_bindings.items():
            spec = specs.get(btn_id)
            if spec is None or spec.locked:
                continue
            if not macro_ref.macro_name:
                continue
            macro = library.get(macro_ref.macro_name) if library else None
            if macro is None:
                continue
            routing[btn_id] = macro
        capture.update_routing_map(routing)

    # ── Feedback (core → device) ──────────────────────────────────────────────

    def supports_feedback(self) -> bool:
        """
        Return True if this plugin supports core→device feedback
        (LCD text, LED colour, rumble, etc.).

        When True, core will call on_profile_changed() after every profile
        switch and immediately after the plugin is activated.
        Default: False.
        """
        return False

    def on_profile_changed(self, profile_name: str) -> None:
        """
        Called by core when the active profile changes.

        Must be non-blocking — put work on a queue or thread.
        Only called when supports_feedback() returns True.
        Default: no-op.
        """

    # ── Optional hardware slot support ────────────────────────────────────────

    def get_hw_slot_count(self) -> int:
        """Number of hardware profile slots. Default 1. G600 returns 3."""
        return 1

    def get_active_hw_slot(self) -> int:
        """Currently active hardware slot index (0-based). Default 0."""
        return 0

    # ── UI ────────────────────────────────────────────────────────────────────

    @abstractmethod
    def create_canvas(self, parent: QWidget | None = None) -> QWidget:
        """
        Return a QWidget showing the physical device layout.
        Canvas must emit signals.button_clicked(self.name, button_id)
        when the user clicks a button.
        """

    def create_settings_widget(self, parent: QWidget | None = None) -> QWidget | None:
        """
        Optional: return a device-specific settings widget (DPI, LED, etc.).
        Shown as a sub-section in the Device tab.
        Return None to skip.
        """
        return None


# ─── Plugin manager ───────────────────────────────────────────────────────────

class PluginManager:
    """
    Discovers and manages device plugins.

    Loading strategy:
        1. Scan PLUGINS_DIR for subdirectories containing plugin.py.
        2. Load each via importlib isolated namespace (not in sys.modules).
        3. Catch ALL exceptions; plugin with missing deps → load-failed entry.
        4. Verify the module exports exactly one DevicePlugin subclass.
        5. Instantiate it (no args).
    """

    def __init__(self):
        self._plugins: dict[str, DevicePlugin] = {}
        self._load_errors: dict[str, str] = {}    # name → error message

    def discover(self) -> None:
        """Scan plugins/ and attempt to load every found plugin."""
        if not PLUGINS_DIR.exists():
            return
        for plugin_dir in sorted(PLUGINS_DIR.iterdir()):
            if not plugin_dir.is_dir() or plugin_dir.name.startswith('_'):
                continue
            plugin_py = plugin_dir / "plugin.py"
            if not plugin_py.exists():
                continue
            self._load_one(plugin_dir.name, plugin_py)

    def _load_one(self, name: str, plugin_py: Path) -> None:
        module_name = f"keymacro.plugins.{name}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, plugin_py)
            module = importlib.util.module_from_spec(spec)
            # exec_module without sys.modules registration → fully isolated
            spec.loader.exec_module(module)
        except Exception as e:
            self._load_errors[name] = f"Import error: {e}"
            return

        # Find the DevicePlugin subclass
        plugin_class = None
        for attr_name in dir(module):
            attr = getattr(module, attr_name, None)
            try:
                if (attr is not None
                        and isinstance(attr, type)
                        and issubclass(attr, DevicePlugin)
                        and attr is not DevicePlugin):
                    plugin_class = attr
                    break
            except TypeError:
                continue

        if plugin_class is None:
            self._load_errors[name] = "No DevicePlugin subclass found in plugin.py"
            return

        try:
            instance = plugin_class()
        except Exception as e:
            self._load_errors[name] = f"Instantiation failed: {e}"
            return

        self._plugins[name] = instance

    # ── Access ────────────────────────────────────────────────────────────────

    def get_all(self) -> list[DevicePlugin]:
        return list(self._plugins.values())

    def get_plugin(self, name: str) -> DevicePlugin | None:
        return self._plugins.get(name)

    def get_load_error(self, name: str) -> str | None:
        return self._load_errors.get(name)

    def get_all_names(self) -> list[str]:
        """All discovered names — both successfully loaded and errored."""
        return sorted(set(self._plugins.keys()) | set(self._load_errors.keys()))

    def get_available(self) -> list[DevicePlugin]:
        """Return plugins that loaded successfully and report is_available()."""
        result = []
        for p in self._plugins.values():
            try:
                if p.is_available():
                    result.append(p)
            except Exception:
                pass
        return result
