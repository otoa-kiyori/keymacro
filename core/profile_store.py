"""
core/profile_store.py — Global unified profile storage for keymacro.

A single ProfileData holds bindings for ALL devices simultaneously.
When a profile is applied, every active plugin reads its own section.

Stored at: ~/.config/keymacro/profiles.json

Format:
{
  "active": "gaming",
  "profiles": [
    {
      "name": "gaming",
      "bindings": {
        "g13":  {"G1": {"inline_tokens": ["KEY_A"]}, "G2": {"library_name": "ctrl_z"}},
        "g600": {"LMB": {"inline_tokens": ["BTN_LEFT"]}}
      },
      "plugin_data": {
        "g13":  {},
        "g600": {"hw_slot": 0, "dpi": 1200, "led_mode": "on", "led_color": "ffffff",
                 "led_duration": 2000, "buttons": {}}
      }
    }
  ]
}

plugin_data[plugin_name] is opaque to core — each plugin serializes/deserializes its own section.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from core.config import PROFILES_FILE, ensure_dirs


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
    A single unified keymacro profile covering ALL devices.

    bindings:    {plugin_name: {button_id: MacroRef}}
    plugin_data: {plugin_name: opaque device-specific dict}
                  e.g. {"g600": {"hw_slot": 0, "dpi": 1200, ...}}
    """
    name: str
    bindings:    dict[str, dict[str, MacroRef]] = field(default_factory=dict)
    plugin_data: dict[str, Any]                 = field(default_factory=dict)

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "bindings": {
                plugin: {btn: ref.to_dict() for btn, ref in btns.items()}
                for plugin, btns in self.bindings.items()
            },
            "plugin_data": self.plugin_data,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProfileData":
        bindings: dict[str, dict[str, MacroRef]] = {}
        for plugin, btns in d.get("bindings", {}).items():
            bindings[plugin] = {btn: MacroRef.from_dict(ref) for btn, ref in btns.items()}
        return cls(
            name=d["name"],
            bindings=bindings,
            plugin_data=d.get("plugin_data", {}),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def copy(self, new_name: str) -> "ProfileData":
        dup = copy.deepcopy(self)
        dup.name = new_name
        return dup

    def plugin_bindings(self, plugin_name: str) -> dict[str, MacroRef]:
        """Return the binding dict for one plugin (empty dict if none set)."""
        return self.bindings.get(plugin_name, {})

    def set_button(self, plugin_name: str, button_id: str, ref: MacroRef) -> None:
        self.bindings.setdefault(plugin_name, {})[button_id] = ref

    def clear_button(self, plugin_name: str, button_id: str) -> None:
        self.bindings.get(plugin_name, {}).pop(button_id, None)


class ProfileStore:
    """
    Global profile collection with JSON persistence.

    Backed by a single file: ~/.config/keymacro/profiles.json
    """

    def __init__(self):
        self._profiles: list[ProfileData] = []
        self._active: str | None = None

    # ── Persistence ───────────────────────────────────────────────────────────

    def load_from_disk(self) -> None:
        ensure_dirs()
        if not PROFILES_FILE.exists():
            return
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._profiles = [ProfileData.from_dict(p) for p in data.get("profiles", [])]
            self._active   = data.get("active")
        except Exception as e:
            print(f"[ProfileStore] load error: {e}")

    def flush_to_disk(self) -> None:
        ensure_dirs()
        data = {
            "active":   self._active,
            "profiles": [p.to_dict() for p in self._profiles],
        }
        try:
            with open(PROFILES_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ProfileStore] save error: {e}")

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
        p = ProfileData(name=name)
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
