"""
ui/tray.py — System tray icon and profile switcher for keymacro.

Uses QSystemTrayIcon which works natively on KDE Plasma Wayland via the
StatusNotifierItem D-Bus protocol (no X11 or libappindicator required, Qt 6.3+).

Menu structure:
    [Device: Logitech G13 Gameboard]   ← non-clickable label
    ─────────────────────────────────
    • gaming                           ← bullet = active profile (QAction checked)
      work
      default
    ─────────────────────────────────
    Open keymacro…
    Quit
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu

if TYPE_CHECKING:
    from core.signals import AppSignals
    from core.profile_store import ProfileStore
    from core.plugin_manager import PluginManager


class KMTrayIcon(QSystemTrayIcon):
    """
    System tray icon with profile switcher context menu.
    Rebuilt whenever the active plugin, profile list, or active profile changes.
    """

    def __init__(
        self,
        signals: "AppSignals",
        profile_stores: dict[str, "ProfileStore"],
        plugin_manager: "PluginManager",
        active_plugin_name: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._signals = signals
        self._profile_stores = profile_stores
        self._plugin_manager = plugin_manager
        self._active_plugin_name = active_plugin_name

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

        plugin_name = self._active_plugin_name
        plugin = self._plugin_manager.get_plugin(plugin_name) if plugin_name else None

        # Device label
        device_label = plugin.display_name if plugin else "No device active"
        label_action = QAction(f"Device: {device_label}", self._menu)
        label_action.setEnabled(False)
        self._menu.addAction(label_action)
        self._menu.addSeparator()

        # Profile list
        if plugin_name and plugin_name in self._profile_stores:
            store = self._profile_stores[plugin_name]
            active_name = store.get_active_name()
            for profile in store.get_all():
                action = QAction(profile.name, self._menu)
                action.setCheckable(True)
                action.setChecked(profile.name == active_name)
                action.triggered.connect(
                    lambda checked, pname=profile.name: self._switch_profile(pname)
                )
                self._menu.addAction(action)
        else:
            no_profiles = QAction("(no profiles)", self._menu)
            no_profiles.setEnabled(False)
            self._menu.addAction(no_profiles)

        self._menu.addSeparator()

        open_action = QAction("Open keymacro…", self._menu)
        open_action.triggered.connect(self._open_window)
        self._menu.addAction(open_action)

        quit_action = QAction("Quit", self._menu)
        quit_action.triggered.connect(self._quit)
        self._menu.addAction(quit_action)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _switch_profile(self, profile_name: str) -> None:
        if self._active_plugin_name:
            self._signals.active_profile_switched.emit(
                self._active_plugin_name, profile_name
            )

    def _open_window(self) -> None:
        self._signals.status_message.emit("open_window")

    def _quit(self) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()

    # ── Signal connections ────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._signals.plugin_activated.connect(self._on_plugin_activated)
        self._signals.active_profile_switched.connect(self._on_profile_switched)
        self._signals.profile_saved.connect(self._on_profile_list_changed)
        self._signals.profile_deleted.connect(self._on_profile_list_changed)
        self._signals.status_message.connect(self._on_status_message)

    def _on_plugin_activated(self, plugin_name: str) -> None:
        self._active_plugin_name = plugin_name
        plugin = self._plugin_manager.get_plugin(plugin_name)
        device_label = plugin.display_name if plugin else plugin_name
        self.setToolTip(f"keymacro — {device_label}")
        self._rebuild_menu()

    def _on_profile_switched(self, plugin_name: str, profile_name: str) -> None:
        if plugin_name == self._active_plugin_name:
            self.setToolTip(f"keymacro — {profile_name}")
            self._rebuild_menu()

    def _on_profile_list_changed(self, plugin_name: str, _name: str) -> None:
        if plugin_name == self._active_plugin_name:
            self._rebuild_menu()

    def _on_status_message(self, msg: str) -> None:
        if msg != "open_window":
            self.showMessage("keymacro", msg, QSystemTrayIcon.MessageIcon.Information, 2000)

    # ── Public ────────────────────────────────────────────────────────────────

    def set_active_plugin(self, plugin_name: str) -> None:
        self._active_plugin_name = plugin_name
        self._rebuild_menu()
