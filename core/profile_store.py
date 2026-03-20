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

import yaml

from core.config import PROFILES_FILE, _PROFILES_JSON, ensure_dirs


@dataclass
class MacroRef:
    """
    A button binding — references a named macro in the global MacroLibrary.

    Profiles never store sequences directly; they store the macro name.
    The actual mode/press/release data lives in NamedMacro.
    """
    macro_name: str = ""    # references NamedMacro.name in MacroLibrary

    def to_dict(self) -> dict:
        return {"macro_name": self.macro_name}

    @classmethod
    def from_dict(cls, d: dict) -> "MacroRef":
        # Backward compat: old format used inline_tokens or library_name
        if "macro_name" not in d:
            name = d.get("library_name") or ""
            return cls(macro_name=name)
        return cls(macro_name=d["macro_name"])


@dataclass
class ProfileData:
    """
    A single unified keymacro profile covering ALL devices.

    bindings:       {plugin_name: {button_id: MacroRef}}
    plugin_data:    {plugin_name: opaque device-specific dict}
    associated_apps: list of window resource classes that auto-switch to this
                    profile when the app becomes focused  (1-to-many)
                    e.g. ["steam", "firefox", "code"]
    """
    name:            str
    bindings:        dict[str, dict[str, MacroRef]] = field(default_factory=dict)
    plugin_data:     dict[str, Any]                 = field(default_factory=dict)
    associated_apps: list[str]                      = field(default_factory=list)

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "name":            self.name,
            "bindings": {
                plugin: {btn: ref.to_dict() for btn, ref in btns.items()}
                for plugin, btns in self.bindings.items()
            },
            "plugin_data":     self.plugin_data,
            "associated_apps": self.associated_apps,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProfileData":
        bindings: dict[str, dict[str, MacroRef]] = {}
        for plugin, btns in d.get("bindings", {}).items():
            bindings[plugin] = {btn: MacroRef.from_dict(ref) for btn, ref in btns.items()}
        return cls(
            name            = d["name"],
            bindings        = bindings,
            plugin_data     = d.get("plugin_data", {}),
            associated_apps = d.get("associated_apps", []),
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
        # One-time migration: JSON → YAML
        if not PROFILES_FILE.exists() and _PROFILES_JSON.exists():
            self._migrate_json(_PROFILES_JSON)
            return
        if not PROFILES_FILE.exists():
            return
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self._profiles = [ProfileData.from_dict(p) for p in data.get("profiles", [])]
            self._active   = data.get("active")
        except Exception as e:
            print(f"[ProfileStore] load error: {e}")

    def _migrate_json(self, json_path) -> None:
        """Load the legacy JSON file, re-save as YAML, and delete the JSON."""
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._profiles = [ProfileData.from_dict(p) for p in data.get("profiles", [])]
            self._active   = data.get("active")
            self.flush_to_disk()
            json_path.unlink(missing_ok=True)
            print(f"[ProfileStore] migrated {json_path.name} → profiles.yaml")
        except Exception as e:
            print(f"[ProfileStore] migration error: {e}")

    def flush_to_disk(self) -> None:
        ensure_dirs()
        data = {
            "active":   self._active,
            "profiles": [p.to_dict() for p in self._profiles],
        }
        try:
            with open(PROFILES_FILE, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False,
                          default_flow_style=False)
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

    def find_by_app(self, resource_class: str) -> ProfileData | None:
        """Return the first profile whose associated_apps contains resource_class."""
        rc = resource_class.lower()
        for p in self._profiles:
            if rc in [a.lower() for a in p.associated_apps]:
                return p
        return None

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
