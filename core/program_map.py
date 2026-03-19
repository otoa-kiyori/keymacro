"""
core/program_map.py — Program → Profile mapping store.

Maps window resource class names (e.g. "steam", "code", "firefox") to profile
names.  Stored at ~/.config/keymacro/programs.json as {resource_class: profile}.

Resource class is the lowercase class reported by KWin (window.resourceClass).
"""

from __future__ import annotations

import json
from core.config import PROGRAMS_FILE, ensure_dirs


class ProgramProfileMap:
    """Persistent mapping from window resource class to profile name."""

    def __init__(self) -> None:
        self._map: dict[str, str] = {}   # resource_class (lower) → profile_name

    def load_from_disk(self) -> None:
        if PROGRAMS_FILE.exists():
            try:
                self._map = json.loads(PROGRAMS_FILE.read_text(encoding="utf-8"))
            except Exception:
                self._map = {}

    def save_to_disk(self) -> None:
        ensure_dirs()
        PROGRAMS_FILE.write_text(
            json.dumps(self._map, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

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
