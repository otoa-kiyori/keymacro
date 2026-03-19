"""
core/config.py — XDG config paths and QSettings wrapper for keymacro.
"""

from pathlib import Path
from PyQt6.QtCore import QSettings, QStandardPaths

APP_NAME  = "keymacro"
ORG_NAME  = "otoa-kiyori"

# ~/.config/keymacro/
CONFIG_DIR = Path(
    QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation
    )
)

MACROS_FILE    = CONFIG_DIR / "macros.json"
PROFILES_FILE  = CONFIG_DIR / "profiles.json"   # single global profile store
PROGRAMS_FILE  = CONFIG_DIR / "programs.json"   # program → profile mapping
SETTINGS_FILE  = CONFIG_DIR / "settings.ini"


def ensure_dirs() -> None:
    """Create config directories if they don't exist yet."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def get_settings() -> QSettings:
    """Return a QSettings object backed by ~/.config/keymacro/settings.ini."""
    ensure_dirs()
    return QSettings(str(SETTINGS_FILE), QSettings.Format.IniFormat)
