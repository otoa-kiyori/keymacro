"""
core/signals.py — Central Qt signal bus for keymacro.

All cross-component communication goes through AppSignals.
No component imports another component's class directly for signaling.
"""

from PyQt6.QtCore import QObject, pyqtSignal


class AppSignals(QObject):
    """
    Central signal bus.  Instantiated once by KMApp; passed by reference to
    every component that needs to emit or receive events.

    Plugin events
    ─────────────
    plugin_activated(name)       Plugin added to the active set (others stay active)
    plugin_deactivated(name)     Plugin removed from the active set
    device_connected(name)       Physical device appeared (USB hotplug)
    device_disconnected(name)    Physical device disappeared
    plugin_error(name, message)  Plugin reported a non-fatal error

    Profile events  (profiles are global — no plugin_name arg)
    ──────────────
    profile_changed(name)        Profile data was edited (not yet applied)
    active_profile_switched(name) Active profile changed + applied to all active devices
    profile_saved(name)          Profile written to disk
    profile_deleted(name)        Profile removed

    Macro library events
    ────────────────────
    macro_library_changed()      Any add/update/delete in the global library

    Device canvas events
    ────────────────────
    button_clicked(plugin, button_id)        User clicked a button on a device canvas
    button_event(plugin, button_id, pressed) Physical button pressed/released on device

    UI utility
    ──────────
    status_message(text)         Display in status bar / tray tooltip
    """

    # ── Plugin ────────────────────────────────────────────────────────────────
    plugin_activated      = pyqtSignal(str)        # plugin_name
    plugin_deactivated    = pyqtSignal(str)        # plugin_name
    device_connected      = pyqtSignal(str)        # plugin_name
    device_disconnected   = pyqtSignal(str)        # plugin_name
    plugin_error          = pyqtSignal(str, str)   # plugin_name, message
    device_reset          = pyqtSignal(str)        # plugin_name

    # ── Profile (global — no plugin_name) ─────────────────────────────────────
    profile_changed           = pyqtSignal(str)    # profile_name
    active_profile_switched   = pyqtSignal(str)    # profile_name
    profile_saved             = pyqtSignal(str)    # profile_name
    profile_deleted           = pyqtSignal(str)    # profile_name

    # ── Macro library ─────────────────────────────────────────────────────────
    macro_library_changed = pyqtSignal()

    # ── Device canvas ─────────────────────────────────────────────────────────
    button_clicked = pyqtSignal(str, str)          # plugin_name, button_id
    button_event   = pyqtSignal(str, str, bool)    # plugin_name, button_id, pressed

    # ── UI utility ────────────────────────────────────────────────────────────
    status_message = pyqtSignal(str)
