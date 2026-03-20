"""
core/macro_library.py — Global named macro store for keymacro.

Macros are the single source of truth for all sequences.  Profiles and
button bindings reference macros by name — no sequences are stored inside
profiles.

Stored at: ~/.keymacro/macros.yaml  (user-defined macros only)

Built-in macros
---------------
On startup MacroLibrary.load_builtins() is called with KEY_REFERENCE_CSV.
It generates one locked press/release macro per key (named exactly like the
keymacro token: "A", "LeftCtrl", "F1", "Num0", "BTN_LEFT", …).

Locked macros:
  - Visible in all macro lists / pickers
  - Cannot be deleted, renamed, or have their sequences changed
  - Never written to macros.yaml

Modes
-----
  complete      press fires on button-down.  release is ignored.
  press_release press fires on button-down, release fires on button-up.
                release_auto=True → release is auto-derived from press
                (hold tokens reversed and flipped to up).
  toggle        press (A) fires on odd presses, release (B) on even presses.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from core.config import MACROS_FILE, _MACROS_JSON, ensure_dirs
from core.macro_token import to_new_format


@dataclass
class NamedMacro:
    name:         str                        # machine key — unique, used in bindings
    display_name: str                        # human label shown in picker / UI
    mode:         str        = "complete"    # "complete" | "press_release" | "toggle"
    press:        list[str]  = field(default_factory=list)   # complete / press / toggle-A
    release:      list[str]  = field(default_factory=list)   # press_release / toggle-B
    release_auto: bool       = True          # press_release: auto-derive release from press
    description:  str        = ""
    locked:       bool       = False         # True = built-in; cannot be edited or deleted

    def to_dict(self) -> dict:
        d: dict = {
            "name":         self.name,
            "display_name": self.display_name,
            "mode":         self.mode,
            "press":        self.press,
            "release":      self.release,
            "release_auto": self.release_auto,
            "description":  self.description,
        }
        # "locked" is never written to disk — it's always derived from the
        # built-in generation path, not from stored data.
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "NamedMacro":
        # Normalize token lists to keymacro new format (strips KEY_* prefix,
        # applies aliases).  Wait tokens (t50) pass through unchanged.
        def _norm(tokens: list) -> list[str]:
            return [to_new_format(t) for t in tokens]

        # Backward compat: old format had a flat "tokens" list
        if "tokens" in d and "press" not in d:
            return cls(
                name         = d["name"],
                display_name = d.get("display_name", d["name"]),
                mode         = "complete",
                press        = _norm(d.get("tokens", [])),
                description  = d.get("description", ""),
            )
        return cls(
            name         = d["name"],
            display_name = d.get("display_name", d["name"]),
            mode         = d.get("mode", "complete"),
            press        = _norm(d.get("press", [])),
            release      = _norm(d.get("release", [])),
            release_auto = d.get("release_auto", True),
            description  = d.get("description", ""),
        )

    def matches_search(self, query: str) -> bool:
        """Return True if query matches name, display_name, description, or tokens."""
        q = query.lower()
        return (
            q in self.name.lower()
            or q in self.display_name.lower()
            or q in self.description.lower()
            or any(q in t.lower() for t in self.press)
            or any(q in t.lower() for t in self.release)
        )


class MacroLibrary:
    """
    Global named macro collection with JSON persistence.

    Two tiers:
      _builtins   locked single-key macros generated from key_reference.csv;
                  never written to disk, always regenerated at startup.
      _macros     user-defined macros; stored in macros.yaml.

    get_all() / get() / search() cover both tiers.
    add() / update() / delete() only operate on user macros; they raise
    ValueError if a locked (built-in) name is targeted.
    """

    def __init__(self):
        self._builtins: list[NamedMacro] = []
        self._macros:   list[NamedMacro] = []

    # ── Built-in generation ───────────────────────────────────────────────────

    def load_builtins(self, csv_path: Path) -> None:
        """
        Parse key_reference.csv and create one locked press/release macro per row.

        CSV columns: macro_name, evdev_name, category, description
        Lines starting with # are comments; blank lines are skipped.

        The macro press sequence is ["{macro_name}+"] and release_auto=True,
        so holding the button holds the key and releasing lifts it.

        The category string is stored as ._category on each NamedMacro so
        the UI can insert visual group-separator rows between categories.
        """
        self._builtins = []
        if not csv_path.exists():
            return
        try:
            with open(csv_path, newline="", encoding="utf-8") as f:
                data_lines = [ln for ln in f
                              if not ln.lstrip().startswith("#") and ln.strip()]
            reader = csv.DictReader(data_lines)
            for row in reader:
                name    = (row.get("macro_name")    or "").strip()
                desc    = (row.get("description")   or "").strip()
                cat     = (row.get("category")      or "").strip()
                display = (row.get("display_name")  or "").strip()
                press_s = (row.get("press")         or "").strip()
                if not name:
                    continue
                press = press_s.split() if press_s else [f"+{name}"]
                m = NamedMacro(
                    name         = name,
                    display_name = display or name,
                    mode         = "press_release",
                    press        = press,
                    release      = [],
                    release_auto = True,
                    description  = desc,
                    locked       = True,
                )
                m._category = cat   # lightweight tag used by the list UI
                self._builtins.append(m)
        except Exception as e:
            print(f"[MacroLibrary] load_builtins error: {e}")

    # ── Persistence ───────────────────────────────────────────────────────────

    def load_from_disk(self) -> None:
        ensure_dirs()
        # One-time migration: JSON → YAML
        if not MACROS_FILE.exists() and _MACROS_JSON.exists():
            self._migrate_json(_MACROS_JSON)
            return
        if not MACROS_FILE.exists():
            return
        try:
            with open(MACROS_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or []
            self._macros = [NamedMacro.from_dict(m) for m in data]
        except Exception as e:
            print(f"[MacroLibrary] load error: {e}")

    def _migrate_json(self, json_path) -> None:
        """Load the legacy JSON file, re-save as YAML, and delete the JSON."""
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._macros = [NamedMacro.from_dict(m) for m in data]
            self.flush_to_disk()
            json_path.unlink(missing_ok=True)
            print(f"[MacroLibrary] migrated {json_path.name} → macros.yaml")
        except Exception as e:
            print(f"[MacroLibrary] migration error: {e}")

    def flush_to_disk(self) -> None:
        """Write only user-defined macros to disk.  Built-ins are never stored."""
        ensure_dirs()
        try:
            data = [m.to_dict() for m in self._macros]
            with open(MACROS_FILE, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False,
                          default_flow_style=False)
        except Exception as e:
            print(f"[MacroLibrary] save error: {e}")

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def get_all(self) -> list[NamedMacro]:
        """Return built-ins first, then user macros."""
        return list(self._builtins) + list(self._macros)

    def get(self, name: str) -> NamedMacro | None:
        for m in self._builtins:
            if m.name == name:
                return m
        for m in self._macros:
            if m.name == name:
                return m
        return None

    def search(self, query: str) -> list[NamedMacro]:
        """Return all macros matching query (name, display_name, description, tokens)."""
        if not query.strip():
            return self.get_all()
        return [m for m in self.get_all() if m.matches_search(query)]

    def add(self, macro: NamedMacro) -> None:
        if self.get(macro.name):
            raise ValueError(f"Macro '{macro.name}' already exists")
        self._macros.append(macro)
        self.flush_to_disk()

    def update(self, name: str, macro: NamedMacro) -> None:
        # Refuse to overwrite a built-in
        if any(m.name == name for m in self._builtins):
            raise ValueError(f"'{name}' is a built-in macro and cannot be modified")
        for i, m in enumerate(self._macros):
            if m.name == name:
                self._macros[i] = macro
                self.flush_to_disk()
                return
        raise ValueError(f"Macro '{name}' not found")

    def delete(self, name: str) -> None:
        if any(m.name == name for m in self._builtins):
            raise ValueError(f"'{name}' is a built-in macro and cannot be deleted")
        before = len(self._macros)
        self._macros = [m for m in self._macros if m.name != name]
        if len(self._macros) == before:
            raise ValueError(f"Macro '{name}' not found")
        self.flush_to_disk()

    def names(self) -> list[str]:
        return [m.name for m in self.get_all()]
