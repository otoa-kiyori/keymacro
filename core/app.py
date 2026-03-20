"""
core/app.py — KMApp: top-level application controller for keymacro.

Owns:
  - AppSignals          central signal bus
  - PluginManager       discover + load plugins
  - MacroLibrary        global named macros
  - ProfileStore        single global profile store
  - dict of ALL currently active plugins (multiple can run simultaneously)
  - MainWindow and KMTrayIcon
"""

from __future__ import annotations

import json

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThreadPool, QRunnable, QObject, pyqtSignal, QTimer

# Resource classes that belong to transient / system UI — gaining focus from
# one of these should NOT alter the active profile.  Treated identically to
# keymacro's own window (OWN_CLASSES in WindowWatcher).
_TRANSIENT_CLASSES: frozenset[str] = frozenset({
    "plasmashell",    # KDE panels, desktop, notification popups
    "krunner",        # KDE application launcher
    "ksmserver",      # KDE session-manager dialogs
    "kwin_wayland",   # internal KWin compositor UI
    "latte-dock",     # Latte Dock (if used)
    "lattedock",
})

from core.signals        import AppSignals
from core.plugin_manager import PluginManager
from core.macro_library  import MacroLibrary
from core.profile_store  import ProfileStore
from core.program_map    import ProgramProfileMap
from core.window_watcher import WindowWatcher
from core.config         import get_settings, KEY_REFERENCE_CSV


class _ApplyProfileRunnable(QRunnable):
    """Worker: calls plugin.apply_profile() on a thread-pool thread."""

    class _Signals(QObject):
        error = pyqtSignal(str, str)   # plugin_name, message
        done  = pyqtSignal(str, str)   # plugin_name, profile_name

    def __init__(self, plugin, profile, app_signals: AppSignals, library=None):
        super().__init__()
        self._plugin       = plugin
        self._profile      = profile
        self._app_signals  = app_signals
        self._library      = library
        self.signals       = self._Signals()

    def run(self):
        try:
            self._plugin.apply_profile(self._profile, self._library)
            self.signals.done.emit(self._plugin.name, self._profile.name)
        except Exception as e:
            self.signals.error.emit(self._plugin.name, str(e))


class KMApp:
    """
    Top-level application controller.

    Multiple plugins can be active simultaneously.
    A single global ProfileStore holds all profiles.
    When a profile is switched, it is applied to EVERY active plugin.

    Lifecycle:
        km = KMApp(qapp)
        km.start()
        sys.exit(qapp.exec())
    """

    def __init__(self, qapp: QApplication):
        self._qapp         = qapp
        self.signals       = AppSignals()
        self.macro_library = MacroLibrary()
        self.plugin_manager = PluginManager()
        self.store         = ProfileStore()           # single global store
        self._active_plugins: dict[str, object] = {} # plugin_name → DevicePlugin
        self.program_map   = ProgramProfileMap()
        self.window_watcher = WindowWatcher()
        self._window       = None
        self._tray         = None
        self._thread_pool  = QThreadPool.globalInstance()
        # Timer used to debounce falling back to Default.  The KWin JS only
        # fires callDBus on class *changes*, so a counter never reaches 2 for
        # unmapped windows.  Instead we delay the Default switch by 400 ms;
        # if a mapped class arrives within that window we cancel the timer.
        self._default_timer = QTimer()
        self._default_timer.setSingleShot(True)
        self._default_timer.setInterval(400)
        self._default_timer.timeout.connect(self._switch_to_default)

    # ── Startup ───────────────────────────────────────────────────────────────

    def start(self) -> None:
        self.macro_library.load_from_disk()
        self.macro_library.load_builtins(KEY_REFERENCE_CSV)

        # Give the shared execution queue a reference to the library so that
        # composite (meta) macro tokens like "Plus+" or "DoubleQuote-" are
        # expanded into their constituent evdev tokens at execution time.
        from core.macro_queue import get_queue
        get_queue().set_library(self.macro_library)

        self.plugin_manager.discover()
        self.store.load_from_disk()

        # Ensure at least one profile exists (always keep "Default")
        if not self.store.get_all():
            self.store.create("Default")
        elif not self.store.get("Default"):
            self.store.create("Default")

        self.program_map.load_from_disk()

        # Start window watcher before building UI so the Programs tab shows
        # the correct status immediately on first render.
        self.window_watcher.start()

        # Restore previously active plugins
        self._restore_active_plugins()

        from ui.main_window import MainWindow
        from ui.tray import KMTrayIcon

        self._window = MainWindow(
            signals=self.signals,
            plugin_manager=self.plugin_manager,
            store=self.store,
            macro_library=self.macro_library,
            active_plugins=self._active_plugins,
            program_map=self.program_map,
            watcher=self.window_watcher,
        )

        self._tray = KMTrayIcon(
            signals=self.signals,
            store=self.store,
            plugin_manager=self.plugin_manager,
            active_plugins=self._active_plugins,
        )
        self._tray.show()

        self._connect_signals()

    # ── Plugin management ─────────────────────────────────────────────────────

    def _restore_active_plugins(self) -> None:
        """Re-activate plugins that were active in the previous session."""
        settings = get_settings()
        saved_raw = settings.value("General/active_plugins", "")
        saved_names: list[str] = []
        if saved_raw:
            try:
                saved_names = json.loads(saved_raw)
            except Exception:
                # Backwards-compat: single string from old single-plugin format
                saved_names = [saved_raw]

        activated_any = False
        for name in saved_names:
            plugin = self.plugin_manager.get_plugin(name)
            if plugin:
                try:
                    if plugin.is_available():
                        self._activate_plugin_internal(plugin)
                        activated_any = True
                except Exception:
                    pass

        # If nothing restored, activate all available plugins automatically
        if not activated_any:
            for plugin in self.plugin_manager.get_all():
                try:
                    if plugin.is_available():
                        self._activate_plugin_internal(plugin)
                except Exception:
                    continue

    def _activate_plugin_internal(self, plugin) -> None:
        """Activate a plugin and add it to the active set (no UI side-effects)."""
        if plugin.name in self._active_plugins:
            return   # already active
        plugin.activate(self.signals)
        self._active_plugins[plugin.name] = plugin
        self._persist_active_plugins()

    def _activate_plugin(self, plugin_name: str) -> None:
        """Called from signal handler after UI is built."""
        plugin = self.plugin_manager.get_plugin(plugin_name)
        if not plugin:
            return
        try:
            if plugin.name in self._active_plugins:
                return
            self._activate_plugin_internal(plugin)
        except Exception as e:
            self.signals.plugin_error.emit(plugin_name, str(e))
            return

        # Apply current profile to the newly activated plugin
        active = self.store.get_active()
        if active:
            self._apply_to_plugin(plugin, active)

        self.signals.plugin_activated.emit(plugin_name)
        self.signals.status_message.emit(f"Plugin activated: {plugin.display_name}")

        # Push current profile to device feedback (e.g. LCD) immediately.
        if plugin.supports_feedback():
            active_name = self.store.get_active_name()
            if active_name:
                try:
                    plugin.on_profile_changed(active_name)
                except Exception:
                    pass

    def _deactivate_plugin(self, plugin_name: str) -> None:
        """Remove a plugin from the active set."""
        plugin = self._active_plugins.pop(plugin_name, None)
        if plugin is None:
            return
        try:
            plugin.deactivate()
        except Exception:
            pass
        self._persist_active_plugins()
        self.signals.plugin_deactivated.emit(plugin_name)
        self.signals.status_message.emit(f"Plugin deactivated: {plugin_name}")

    def _persist_active_plugins(self) -> None:
        get_settings().setValue(
            "General/active_plugins",
            json.dumps(list(self._active_plugins.keys()))
        )

    # ── Profile apply ─────────────────────────────────────────────────────────

    def _apply_profile(self, profile_name: str) -> None:
        """Switch to a profile and apply it to ALL active plugins.

        If the requested profile is already active the routing is still
        re-applied (needed e.g. after debug mode clears it) but no UI
        notification is emitted — the user sees nothing.
        """
        profile = self.store.get(profile_name)
        if profile is None:
            self.signals.plugin_error.emit("", f"Profile '{profile_name}' not found")
            return

        is_new = profile_name != self.store.get_active_name()
        self.store.set_active(profile_name)

        # Only tell the UI something changed when we're actually switching.
        if is_new:
            self.signals.profile_changed.emit(profile_name)

        for plugin in list(self._active_plugins.values()):
            self._apply_to_plugin(plugin, profile)

        # One status message from core — not one per plugin.
        if is_new:
            self.signals.status_message.emit(f"Profile: {profile_name}")
            self._notify_feedback(profile_name)

    def _notify_feedback(self, profile_name: str) -> None:
        """Call on_profile_changed() on every active plugin that supports feedback."""
        for plugin in list(self._active_plugins.values()):
            if plugin.supports_feedback():
                try:
                    plugin.on_profile_changed(profile_name)
                except Exception:
                    pass

    def _apply_to_plugin(self, plugin, profile) -> None:
        runnable = _ApplyProfileRunnable(plugin, profile, self.signals, self.macro_library)
        runnable.signals.error.connect(
            lambda pn, err: self.signals.plugin_error.emit(pn, err)
        )
        self._thread_pool.start(runnable)

    # ── Signal connections ────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self.signals.plugin_activated.connect(self._on_plugin_activated)
        self.signals.plugin_deactivated.connect(self._on_plugin_deactivated)
        self.signals.active_profile_switched.connect(self._on_profile_switch)
        self.signals.profile_deleted.connect(self._on_profile_deleted)
        self.signals.status_message.connect(self._on_status_message)
        self.window_watcher.active_app_changed.connect(self._on_active_app_changed)

    def _on_plugin_activated(self, plugin_name: str) -> None:
        if plugin_name not in self._active_plugins:
            self._activate_plugin(plugin_name)

    def _on_plugin_deactivated(self, plugin_name: str) -> None:
        self._deactivate_plugin(plugin_name)

    def _on_profile_switch(self, profile_name: str) -> None:
        self._apply_profile(profile_name)

    def _on_profile_deleted(self, profile_name: str) -> None:
        self._ensure_default()

    def _ensure_default(self) -> None:
        """Recreate the Default profile if it was deleted, then notify the UI."""
        if not self.store.get("Default"):
            self.store.create("Default")
            self.signals.profile_changed.emit("Default")

    def _on_status_message(self, msg: str) -> None:
        if msg == "open_window" and self._window:
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()

    def _on_active_app_changed(self, resource_class: str) -> None:
        """Auto-switch profile based on the active window's resource class."""
        if not self._active_plugins:
            return
        # Ignore keymacro's own windows
        if self.window_watcher.is_own_class(resource_class):
            return
        # Ignore empty class (desktop/no-window) and transient system UI
        # (notifications, panels, launchers).  Neither should alter the profile.
        if not resource_class or resource_class.lower() in _TRANSIENT_CLASSES:
            return

        # Check associated_apps on profiles first (new format), then fall back
        # to the legacy ProgramProfileMap.
        target: str | None = None
        if resource_class:
            profile_match = self.store.find_by_app(resource_class)
            if profile_match:
                target = profile_match.name
            else:
                target = self.program_map.get_profile_for(resource_class)

        if target and self.store.get(target):
            # Known mapped app — cancel any pending Default fallback and switch now
            self._default_timer.stop()
            self._do_switch(target)
        else:
            # Unmapped or empty window.  The KWin JS only fires callDBus on
            # class *changes*, so a counter-based debounce never increments.
            # Use a one-shot timer instead: if no mapped class arrives within
            # 400 ms we fall back to Default.
            if not self._default_timer.isActive():
                self._default_timer.start()

    def _switch_to_default(self) -> None:
        """Called by _default_timer — fall back to Default profile."""
        self._ensure_default()
        self._do_switch("Default")

    def _do_switch(self, profile_name: str) -> None:
        """Emit active_profile_switched only if the profile actually changes."""
        current = self.store.get_active_name()
        if profile_name != current and self.store.get(profile_name):
            self.signals.active_profile_switched.emit(profile_name)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        # Wait for any in-flight apply_profile runnables to finish (cap at 3s).
        self._thread_pool.waitForDone(3000)
        # Stop the KWin watcher while the event loop is still live (needs D-Bus).
        self.window_watcher.stop()
        for plugin in list(self._active_plugins.values()):
            try:
                plugin.deactivate()
            except Exception:
                pass
