"""
ui/tray.py — System tray icon and profile switcher for keymacro.

Uses QSystemTrayIcon (KDE Plasma Wayland, StatusNotifierItem D-Bus, Qt 6.3+).

Menu:
    Active: G13, G600          ← non-clickable device list
    ────────────────────────
    • gaming                   ← checked = active global profile
      work
      default
    ────────────────────────
    Open keymacro…
    Quit
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu

if TYPE_CHECKING:
    from core.signals        import AppSignals
    from core.profile_store  import ProfileStore
    from core.plugin_manager import PluginManager


class KMTrayIcon(QSystemTrayIcon):
    """
    Tray icon with global profile switcher menu.
    Profiles are global — switching applies to ALL active plugins.
    """

    def __init__(
        self,
        signals:        "AppSignals",
        store:          "ProfileStore",
        plugin_manager: "PluginManager",
        active_plugins: dict,          # plugin_name → DevicePlugin (shared ref)
        parent=None,
    ):
        super().__init__(parent)
        self._signals       = signals
        self._store         = store
        self._pm            = plugin_manager
        self._active_plugins = active_plugins   # shared reference — stays current

        self._menu = QMenu()
        self.setContextMenu(self._menu)
        self._set_icon()
        self.setToolTip("keymacro")

        self._rebuild_menu()
        self._connect_signals()

    # ── Icon ──────────────────────────────────────────────────────────────────

    def _set_icon(self) -> None:
        icon = QIcon.fromTheme("input-keyboard")
        if icon.isNull():
            icon = QIcon.fromTheme("preferences-desktop-keyboard")
        self.setIcon(icon)

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _rebuild_menu(self) -> None:
        self._menu.clear()

        # Active device list
        if self._active_plugins:
            names = ", ".join(
                self._pm.get_plugin(n).display_name
                if self._pm.get_plugin(n) else n
                for n in self._active_plugins
            )
            device_action = QAction(f"Active: {names}", self._menu)
        else:
            device_action = QAction("No device active", self._menu)
        device_action.setEnabled(False)
        self._menu.addAction(device_action)
        self._menu.addSeparator()

        # Global profile list
        active_name = self._store.get_active_name()
        for profile in self._store.get_all():
            action = QAction(profile.name, self._menu)
            action.setCheckable(True)
            action.setChecked(profile.name == active_name)
            action.triggered.connect(
                lambda checked, pname=profile.name: self._switch_profile(pname)
            )
            self._menu.addAction(action)

        if not self._store.get_all():
            empty = QAction("(no profiles)", self._menu)
            empty.setEnabled(False)
            self._menu.addAction(empty)

        self._menu.addSeparator()

        open_action = QAction("Open keymacro…", self._menu)
        open_action.triggered.connect(lambda: self._signals.status_message.emit("open_window"))
        self._menu.addAction(open_action)

        quit_action = QAction("Quit", self._menu)
        quit_action.triggered.connect(self._quit)
        self._menu.addAction(quit_action)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _switch_profile(self, profile_name: str) -> None:
        self._signals.active_profile_switched.emit(profile_name)

    def _quit(self) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()

    # ── Signal connections ────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._signals.plugin_activated.connect(lambda _: self._rebuild_menu())
        self._signals.plugin_deactivated.connect(lambda _: self._rebuild_menu())
        self._signals.active_profile_switched.connect(self._on_profile_switched)
        self._signals.profile_saved.connect(lambda _: self._rebuild_menu())
        self._signals.profile_deleted.connect(lambda _: self._rebuild_menu())
        self._signals.status_message.connect(self._on_status_message)

    def _on_profile_switched(self, profile_name: str) -> None:
        self.setToolTip(f"keymacro — {profile_name}")
        self._rebuild_menu()

    _NOTIFY_SKIP = ("open_window", "failed", "unavailable", "not found", "error")

    def _on_status_message(self, msg: str) -> None:
        if any(kw in msg.lower() for kw in self._NOTIFY_SKIP):
            return
        try:
            subprocess.Popen(
                ["notify-send",
                 "--app-name=keymacro",
                 "--icon=input-gaming",
                 "--expire-time=5000",
                 "keymacro", msg],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass  # notify-send not installed — silent fallback
