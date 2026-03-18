"""
core/app.py — KMApp: top-level application controller for keymacro.

Owns:
  - AppSignals  (central signal bus)
  - PluginManager  (discover + load plugins)
  - MacroLibrary  (global named macros)
  - ProfileStore per active plugin
  - MainWindow and KMTrayIcon
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThreadPool, QRunnable, QObject, pyqtSignal

from core.signals        import AppSignals
from core.plugin_manager import PluginManager
from core.macro_library  import MacroLibrary
from core.profile_store  import ProfileStore
from core.config         import get_settings


class _ApplyProfileRunnable(QRunnable):
    """Worker that calls plugin.apply_profile() on a thread pool thread."""

    class _Signals(QObject):
        error = pyqtSignal(str, str)   # plugin_name, message
        done  = pyqtSignal(str, str)   # plugin_name, profile_name

    def __init__(self, plugin, profile, signals: AppSignals):
        super().__init__()
        self._plugin  = plugin
        self._profile = profile
        self._app_signals = signals
        self.signals = self._Signals()

    def run(self):
        try:
            self._plugin.apply_profile(self._profile)
            self.signals.done.emit(self._plugin.name, self._profile.name)
        except Exception as e:
            self.signals.error.emit(self._plugin.name, str(e))


class KMApp:
    """
    Top-level application controller.

    Lifecycle:
        km = KMApp(qapp)
        km.start()         # discovers plugins, loads profiles, shows tray
        sys.exit(qapp.exec())
    """

    def __init__(self, qapp: QApplication):
        self._qapp = qapp
        self.signals  = AppSignals()
        self.macro_library = MacroLibrary()
        self.plugin_manager = PluginManager()
        self._stores: dict[str, ProfileStore] = {}
        self._active_plugin_name: str | None = None
        self._window = None
        self._tray   = None
        self._thread_pool = QThreadPool.globalInstance()

    def start(self) -> None:
        # Load global macro library
        self.macro_library.load_from_disk()

        # Discover all plugins
        self.plugin_manager.discover()

        # Restore previously active plugin (or pick first available)
        self._restore_active_plugin()

        # Build UI
        from ui.main_window import MainWindow
        from ui.tray import KMTrayIcon

        self._window = MainWindow(
            signals=self.signals,
            plugin_manager=self.plugin_manager,
            profile_stores=self._stores,
            macro_library=self.macro_library,
            active_plugin_name=self._active_plugin_name,
        )

        self._tray = KMTrayIcon(
            signals=self.signals,
            profile_stores=self._stores,
            plugin_manager=self.plugin_manager,
            active_plugin_name=self._active_plugin_name,
        )
        self._tray.show()

        self._connect_signals()

    # ── Plugin management ─────────────────────────────────────────────────────

    def _restore_active_plugin(self) -> None:
        saved = get_settings().value("General/active_plugin", "")
        # Try saved plugin first
        if saved:
            plugin = self.plugin_manager.get_plugin(saved)
            if plugin:
                try:
                    if plugin.is_available():
                        self._activate_plugin_internal(plugin)
                        return
                except Exception:
                    pass
        # Fall back to first available plugin
        for plugin in self.plugin_manager.get_all():
            try:
                if plugin.is_available():
                    self._activate_plugin_internal(plugin)
                    return
            except Exception:
                continue

    def _activate_plugin_internal(self, plugin) -> None:
        """Internal activation — called before UI is built."""
        if self._active_plugin_name:
            old = self.plugin_manager.get_plugin(self._active_plugin_name)
            if old:
                try:
                    old.deactivate()
                except Exception:
                    pass

        plugin.activate(self.signals)
        self._active_plugin_name = plugin.name

        # Ensure a ProfileStore exists for this plugin
        if plugin.name not in self._stores:
            store = ProfileStore(plugin.name)
            store.load_from_disk()
            if not store.get_all():
                store.create("default")
            self._stores[plugin.name] = store

        get_settings().setValue("General/active_plugin", plugin.name)

    def _activate_plugin(self, plugin_name: str) -> None:
        """Called from signal handler after UI is built."""
        plugin = self.plugin_manager.get_plugin(plugin_name)
        if not plugin:
            return
        try:
            self._activate_plugin_internal(plugin)
        except Exception as e:
            self.signals.plugin_error.emit(plugin_name, str(e))
            return
        self.signals.plugin_activated.emit(plugin_name)
        self.signals.status_message.emit(f"Plugin activated: {plugin.display_name}")

    # ── Profile apply ─────────────────────────────────────────────────────────

    def _apply_profile(self, plugin_name: str, profile_name: str) -> None:
        store  = self._stores.get(plugin_name)
        plugin = self.plugin_manager.get_plugin(plugin_name)
        if store is None or plugin is None:
            return

        profile = store.get(profile_name)
        if profile is None:
            self.signals.plugin_error.emit(plugin_name, f"Profile '{profile_name}' not found")
            return

        store.set_active(profile_name)

        runnable = _ApplyProfileRunnable(plugin, profile, self.signals)
        runnable.signals.done.connect(
            lambda pn, prn: self.signals.status_message.emit(f"Profile applied: {prn}")
        )
        runnable.signals.error.connect(
            lambda pn, err: self.signals.plugin_error.emit(pn, err)
        )
        self._thread_pool.start(runnable)

    # ── Signal connections ────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        # Plugin panel requests activation
        self.signals.plugin_activated.connect(self._on_plugin_activated_request)
        # Tray / profile panel requests profile switch
        self.signals.active_profile_switched.connect(self._on_profile_switch_requested)
        # Open window from tray
        self.signals.status_message.connect(self._on_status_message)

    def _on_plugin_activated_request(self, plugin_name: str) -> None:
        if plugin_name != self._active_plugin_name:
            self._activate_plugin(plugin_name)

    def _on_profile_switch_requested(self, plugin_name: str, profile_name: str) -> None:
        self._apply_profile(plugin_name, profile_name)

    def _on_status_message(self, msg: str) -> None:
        if msg == "open_window" and self._window:
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Clean deactivation of the active plugin before exit."""
        if self._active_plugin_name:
            plugin = self.plugin_manager.get_plugin(self._active_plugin_name)
            if plugin:
                try:
                    plugin.deactivate()
                except Exception:
                    pass
