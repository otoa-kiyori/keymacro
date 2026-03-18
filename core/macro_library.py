"""
core/macro_library.py — Global named macro store for keymacro.

Stored at: ~/.config/keymacro/macros.json
Format:
[
  {"name": "ctrl_click", "tokens": ["+KEY_LEFTCTRL", "BTN_LEFT", "-KEY_LEFTCTRL"],
   "description": "Ctrl + left click"}
]
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from core.config import MACROS_FILE, ensure_dirs


@dataclass
class NamedMacro:
    name:        str
    tokens:      list[str]
    description: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "tokens": self.tokens, "description": self.description}

    @classmethod
    def from_dict(cls, d: dict) -> "NamedMacro":
        return cls(name=d["name"], tokens=d.get("tokens", []), description=d.get("description", ""))


class MacroLibrary:
    """Global named macro collection with JSON persistence."""

    def __init__(self):
        self._macros: list[NamedMacro] = []

    # ── Persistence ───────────────────────────────────────────────────────────

    def load_from_disk(self) -> None:
        ensure_dirs()
        if not MACROS_FILE.exists():
            return
        try:
            with open(MACROS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._macros = [NamedMacro.from_dict(m) for m in data]
        except Exception as e:
            print(f"[MacroLibrary] load error: {e}")

    def flush_to_disk(self) -> None:
        ensure_dirs()
        try:
            with open(MACROS_FILE, "w", encoding="utf-8") as f:
                json.dump([m.to_dict() for m in self._macros], f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[MacroLibrary] save error: {e}")

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def get_all(self) -> list[NamedMacro]:
        return list(self._macros)

    def get(self, name: str) -> NamedMacro | None:
        for m in self._macros:
            if m.name == name:
                return m
        return None

    def add(self, macro: NamedMacro) -> None:
        if self.get(macro.name):
            raise ValueError(f"Macro '{macro.name}' already exists")
        self._macros.append(macro)
        self.flush_to_disk()

    def update(self, name: str, macro: NamedMacro) -> None:
        for i, m in enumerate(self._macros):
            if m.name == name:
                self._macros[i] = macro
                self.flush_to_disk()
                return
        raise ValueError(f"Macro '{name}' not found")

    def delete(self, name: str) -> None:
        before = len(self._macros)
        self._macros = [m for m in self._macros if m.name != name]
        if len(self._macros) == before:
            raise ValueError(f"Macro '{name}' not found")
        self.flush_to_disk()

    def names(self) -> list[str]:
        return [m.name for m in self._macros]
