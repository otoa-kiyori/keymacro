"""
core/window_watcher.py — Watches the active window on KDE Plasma Wayland.

Uses KWin's scripting D-Bus API to install a tiny JS watcher that fires
callDBus() into our app whenever the focused window changes.

Emits active_app_changed(resource_class: str).
  resource_class — lowercase window class, e.g. "steam", "code", "firefox"
  empty string   — no window focused

Falls back gracefully: if KWin scripting is unavailable, is_running stays
False and the Programs tab shows an appropriate status message.

No extra dependencies beyond PyQt6 (uses PyQt6.QtDBus, included in PyQt6).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage


# ── KWin script injected into the KWin scripting engine ───────────────────────
# Connects to workspace.windowActivated and calls our D-Bus slot each time
# the active window changes.  Empty string means no window is focused.

_KWIN_SCRIPT = """\
(function() {
    function _kmNotify(w) {
        var cls = (w && w.resourceClass) ? w.resourceClass : "";
        callDBus("org.keymacro.watcher", "/", "", "onWindowActivated", cls);
    }
    workspace.windowActivated.connect(_kmNotify);
    _kmNotify(workspace.activeWindow);
})();
"""

_SCRIPT_PLUGIN_NAME = "keymacro-watcher"


class WindowWatcher(QObject):
    """
    Installs a KWin script watcher and translates active-window changes into
    the active_app_changed Qt signal.
    """

    active_app_changed = pyqtSignal(str)   # resource_class; "" = no window

    #: Resource class(es) that belong to keymacro itself — ignored when
    #: updating last_external_class and when deciding whether to auto-switch.
    OWN_CLASSES: frozenset[str] = frozenset({"keymacro", "python3", "python"})

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._running              = False
        self._script_path: Path | None = None
        self._last_class           = ""   # most recent class (including own)
        self._last_external_class  = ""   # most recent class that is NOT our own app

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """
        Register our D-Bus receiver and load the KWin watcher script.
        Returns True on success, False if KWin scripting is unavailable.
        """
        conn = QDBusConnection.sessionBus()

        # Register D-Bus service so KWin can call back into us.
        # It's fine if registration fails (e.g. previous instance didn't clean
        # up) — Qt will still dispatch incoming calls to the registered object.
        conn.registerService("org.keymacro.watcher")

        ok = conn.registerObject(
            "/", self,
            QDBusConnection.RegisterOption.ExportAllSlots,
        )
        if not ok:
            return False

        # Write script to a temp file.
        tmp = tempfile.NamedTemporaryFile(
            suffix=".js", prefix="keymacro_kwin_", delete=False
        )
        tmp.write(_KWIN_SCRIPT.encode())
        tmp.close()
        self._script_path = Path(tmp.name)

        # Talk to KWin's scripting interface.
        scripting = QDBusInterface(
            "org.kde.KWin", "/Scripting",
            "org.kde.kwin.Scripting",
            conn,
        )
        if not scripting.isValid():
            self._cleanup_script_file()
            return False

        # Remove stale instance from a previous run (ignore errors).
        scripting.call("unloadScript", _SCRIPT_PLUGIN_NAME)

        reply: QDBusMessage = scripting.call(
            "loadScript", str(self._script_path), _SCRIPT_PLUGIN_NAME
        )
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            self._cleanup_script_file()
            return False

        # start() tells KWin to begin executing newly loaded scripts.
        scripting.call("start")

        self._running = True
        return True

    def stop(self) -> None:
        if not self._running:
            return
        conn = QDBusConnection.sessionBus()
        scripting = QDBusInterface(
            "org.kde.KWin", "/Scripting",
            "org.kde.kwin.Scripting", conn,
        )
        if scripting.isValid():
            scripting.call("unloadScript", _SCRIPT_PLUGIN_NAME)
        conn.unregisterObject("/")
        conn.unregisterService("org.keymacro.watcher")
        self._cleanup_script_file()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_class(self) -> str:
        """Resource class of the most recently seen active window (may be our own)."""
        return self._last_class

    @property
    def last_external_class(self) -> str:
        """Resource class of the last active window that was NOT keymacro itself."""
        return self._last_external_class

    def is_own_class(self, resource_class: str) -> bool:
        return resource_class.lower() in self.OWN_CLASSES

    # ── D-Bus slot called by the KWin script ──────────────────────────────────

    @pyqtSlot(str)
    def onWindowActivated(self, resource_class: str) -> None:
        self._last_class = resource_class
        if resource_class and not self.is_own_class(resource_class):
            self._last_external_class = resource_class
        self.active_app_changed.emit(resource_class)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _cleanup_script_file(self) -> None:
        if self._script_path and self._script_path.exists():
            try:
                self._script_path.unlink()
            except Exception:
                pass
        self._script_path = None
