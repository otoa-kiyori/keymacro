#!/usr/bin/env python3
"""
keymacro — KDE Plasma Wayland input device macro manager.

Entry point. Creates QApplication, initialises KMApp, runs event loop.

Usage:
    python keymacro.py

Wayland-native: QSystemTrayIcon uses StatusNotifierItem D-Bus protocol
(KDE Plasma 6.x, Qt 6.3+). No X11 or Xwayland required.
"""

import signal
import sys
from pathlib import Path

# Ensure project root is on sys.path so `core`, `ui`, `plugins` are importable
sys.path.insert(0, str(Path(__file__).parent))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from core.app import KMApp


def main() -> int:
    # Wayland-native hints
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)
    app.setApplicationName("keymacro")
    app.setOrganizationName("otoa-kiyori")
    app.setApplicationDisplayName("")  # suppress KDE auto-appending app name to title

    # Keep running in tray after the settings window is closed
    app.setQuitOnLastWindowClosed(False)

    km = KMApp(app)
    km.start()
    km._window.show()

    # Shut down while the event loop is still running so D-Bus cleanup works.
    app.aboutToQuit.connect(km.shutdown)

    # Route SIGTERM and SIGINT through Qt's event loop so aboutToQuit fires and
    # km.shutdown() runs before Python starts tearing down modules.  Without this,
    # SIGTERM (sent by VS Code / systemd / kill) exits the process immediately
    # and evdev's InputDevice.__del__ fires after asyncio.get_event_loop becomes
    # None during module teardown, causing TypeError spam.
    signal.signal(signal.SIGTERM, lambda _s, _f: app.quit())
    signal.signal(signal.SIGINT,  lambda _s, _f: app.quit())

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
