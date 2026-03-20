"""
core/config.py — XDG config paths and QSettings wrapper for keymacro.
"""

from pathlib import Path
from PyQt6.QtCore import QSettings, QStandardPaths

APP_NAME  = "keymacro"
ORG_NAME  = "otoa-kiyori"

# ~/.keymacro/  — user-visible data directory in home folder
DATA_DIR  = Path.home() / ".keymacro"

# ~/.config/keymacro/  — app settings (window geometry, active plugin, etc.)
CONFIG_DIR = Path(
    QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation
    )
)

MACROS_FILE    = DATA_DIR  / "macros.yaml"
PROFILES_FILE  = DATA_DIR  / "profiles.yaml"
PROGRAMS_FILE  = DATA_DIR  / "programs.yaml"

# Legacy JSON paths — used only for one-time migration on first load
_MACROS_JSON   = DATA_DIR  / "macros.json"
_PROFILES_JSON = DATA_DIR  / "profiles.json"
_PROGRAMS_JSON = DATA_DIR  / "programs.json"
SETTINGS_FILE      = CONFIG_DIR / "settings.ini"

# Built-in single-key reference — same directory as this file
KEY_REFERENCE_CSV  = Path(__file__).parent / "key_reference.csv"


def ensure_dirs() -> None:
    """Create data and config directories if they don't exist yet.

    Directories are created with mode 0o700 (user-only) so profiles and
    macros are not readable by other local accounts.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)


def get_settings() -> QSettings:
    """Return a QSettings object backed by ~/.config/keymacro/settings.ini."""
    ensure_dirs()
    return QSettings(str(SETTINGS_FILE), QSettings.Format.IniFormat)
