"""
core/profile_store.py — Per-device profile storage for keymacro.

Profiles are stored as JSON at:
    ~/.config/keymacro/profiles/<plugin_name>.json

Format:
{
  "active": "gaming",
  "profiles": [
    {
      "name": "gaming",
      "device_plugin": "g13",
      "bindings": {
        "G1": {"inline_tokens": ["KEY_A"]},
        "G2": {"library_name": "ctrl_click"}
      },
      "plugin_data": {"g13": {}}
    }
  ]
}

plugin_data is opaque to core — each plugin serializes/deserializes its own
section. Core only stores and retrieves it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any

from core.config import PROFILES_DIR, ensure_dirs


@dataclass
class MacroRef:
    """Binding for one button: inline token list OR named library macro."""
    inline_tokens: list[str] | None = None
    library_name:  str | None       = None

    def to_dict(self) -> dict:
        d: dict = {}
        if self.inline_tokens is not None:
            d["inline_tokens"] = self.inline_tokens
        if self.library_name is not None:
            d["library_name"] = self.library_name
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MacroRef":
        return cls(
            inline_tokens=d.get("inline_tokens"),
            library_name=d.get("library_name"),
        )


@dataclass
class ProfileData:
    """
    A single named profile.

    bindings:    button_id → MacroRef
    plugin_data: opaque device-specific dict, keyed by plugin name
                 e.g. {"g600": {"dpi": 1200, "led_mode": "on", ...}}
    """
    name:          str
    device_plugin: str
    bindings:      dict[str, MacroRef] = field(default_factory=dict)
    plugin_data:   dict[str, Any]      = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "device_plugin": self.device_plugin,
            "bindings": {k: v.to_dict() for k, v in self.bindings.items()},
            "plugin_data": self.plugin_data,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProfileData":
        bindings = {
            k: MacroRef.from_dict(v)
            for k, v in d.get("bindings", {}).items()
        }
        return cls(
            name=d["name"],
            device_plugin=d["device_plugin"],
            bindings=bindings,
            plugin_data=d.get("plugin_data", {}),
        )

    def copy(self, new_name: str) -> "ProfileData":
        import copy
        dup = copy.deepcopy(self)
        dup.name = new_name
        return dup


class ProfileStore:
    """
    Per-device profile collection with JSON persistence.

    One instance per plugin. Backed by:
        ~/.config/keymacro/profiles/<plugin_name>.json
    """

    def __init__(self, plugin_name: str):
        self._plugin_name = plugin_name
        self._profiles: list[ProfileData] = []
        self._active: str | None = None
        self._path = PROFILES_DIR / f"{plugin_name}.json"

    # ── Persistence ───────────────────────────────────────────────────────────

    def load_from_disk(self) -> None:
        ensure_dirs()
        if not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._profiles = [ProfileData.from_dict(p) for p in data.get("profiles", [])]
            self._active   = data.get("active")
        except Exception as e:
            print(f"[ProfileStore:{self._plugin_name}] load error: {e}")

    def flush_to_disk(self) -> None:
        ensure_dirs()
        data = {
            "active":   self._active,
            "profiles": [p.to_dict() for p in self._profiles],
        }
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ProfileStore:{self._plugin_name}] save error: {e}")

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def get_all(self) -> list[ProfileData]:
        return list(self._profiles)

    def get(self, name: str) -> ProfileData | None:
        for p in self._profiles:
            if p.name == name:
                return p
        return None

    def create(self, name: str) -> ProfileData:
        if self.get(name):
            raise ValueError(f"Profile '{name}' already exists")
        p = ProfileData(name=name, device_plugin=self._plugin_name)
        self._profiles.append(p)
        if self._active is None:
            self._active = name
        self.flush_to_disk()
        return p

    def duplicate(self, source_name: str, new_name: str) -> ProfileData:
        src = self.get(source_name)
        if src is None:
            raise ValueError(f"Profile '{source_name}' not found")
        if self.get(new_name):
            raise ValueError(f"Profile '{new_name}' already exists")
        dup = src.copy(new_name)
        self._profiles.append(dup)
        self.flush_to_disk()
        return dup

    def delete(self, name: str) -> None:
        before = len(self._profiles)
        self._profiles = [p for p in self._profiles if p.name != name]
        if len(self._profiles) == before:
            raise ValueError(f"Profile '{name}' not found")
        if self._active == name:
            self._active = self._profiles[0].name if self._profiles else None
        self.flush_to_disk()

    def save(self, profile: ProfileData) -> None:
        """Update an existing profile in the store and flush to disk."""
        for i, p in enumerate(self._profiles):
            if p.name == profile.name:
                self._profiles[i] = profile
                self.flush_to_disk()
                return
        # Not found — add it
        self._profiles.append(profile)
        self.flush_to_disk()

    # ── Active profile ────────────────────────────────────────────────────────

    def get_active_name(self) -> str | None:
        return self._active

    def get_active(self) -> ProfileData | None:
        if self._active is None:
            return None
        return self.get(self._active)

    def set_active(self, name: str) -> None:
        if self.get(name) is None:
            raise ValueError(f"Profile '{name}' not found")
        self._active = name
        self.flush_to_disk()
