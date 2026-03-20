"""
core/program_map.py — Program → Profile mapping store.

Maps window resource class names (e.g. "steam", "code", "firefox") to profile
names.  Stored at ~/.config/keymacro/programs.json as {resource_class: profile}.

Resource class is the lowercase class reported by KWin (window.resourceClass).
"""

from __future__ import annotations

import json

import yaml

from core.config import PROGRAMS_FILE, _PROGRAMS_JSON, ensure_dirs


class ProgramProfileMap:
    """Persistent mapping from window resource class to profile name."""

    def __init__(self) -> None:
        self._map: dict[str, str] = {}   # resource_class (lower) → profile_name

    def load_from_disk(self) -> None:
        # One-time migration: JSON → YAML
        if not PROGRAMS_FILE.exists() and _PROGRAMS_JSON.exists():
            try:
                self._map = json.loads(_PROGRAMS_JSON.read_text(encoding="utf-8"))
                self.save_to_disk()
                _PROGRAMS_JSON.unlink(missing_ok=True)
                print("[ProgramProfileMap] migrated programs.json → programs.yaml")
            except Exception:
                self._map = {}
            return
        if PROGRAMS_FILE.exists():
            try:
                with open(PROGRAMS_FILE, "r", encoding="utf-8") as f:
                    self._map = yaml.safe_load(f) or {}
            except Exception:
                self._map = {}

    def save_to_disk(self) -> None:
        ensure_dirs()
        with open(PROGRAMS_FILE, "w", encoding="utf-8") as f:
            yaml.dump(self._map, f, allow_unicode=True, sort_keys=True,
                      default_flow_style=False)

    def get_all(self) -> dict[str, str]:
        """Return a copy of the full mapping."""
        return dict(self._map)

    def set(self, resource_class: str, profile_name: str) -> None:
        self._map[resource_class.lower()] = profile_name
        self.save_to_disk()

    def remove(self, resource_class: str) -> None:
        self._map.pop(resource_class.lower(), None)
        self.save_to_disk()

    def get_profile_for(self, resource_class: str) -> str | None:
        """Return the mapped profile name, or None if not mapped."""
        return self._map.get(resource_class.lower())
