#!/usr/bin/env python3
"""
keymacro — KDE Plasma Wayland input device macro manager.

Entry point. Creates QApplication, initialises KMApp, runs event loop.

Usage:
    python keymacro.py

Wayland-native: QSystemTrayIcon uses StatusNotifierItem D-Bus protocol
(KDE Plasma 6.x, Qt 6.3+). No X11 or Xwayland required.
"""

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
    app.setApplicationDisplayName("keymacro")

    # Keep running in tray after the settings window is closed
    app.setQuitOnLastWindowClosed(False)

    km = KMApp(app)
    km.start()
    km._window.show()

    # Shut down while the event loop is still running so D-Bus cleanup works.
    app.aboutToQuit.connect(km.shutdown)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
