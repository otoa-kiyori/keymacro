"""
plugins/g600/canvas.py — Visual G600 device layout canvas.

Adapted from g600_gui/g600_gui.py DeviceCanvas.
Emits signals.button_clicked(plugin_name, button_id) via the AppSignals bus.
button_id is the label string ("LMB", "G9", etc.) for consistency with G13 style.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from PyQt6.QtWidgets import QWidget, QPushButton

if TYPE_CHECKING:
    from core.signals import AppSignals

# ─── Colors ───────────────────────────────────────────────────────────────────

COLORS = {
    "device":           "#dde0e4",
    "main":             "#c8daf5",
    "main_border":      "#6a9fd8",
    "thumb":            "#fde8b0",
    "thumb_border":     "#c8960a",
    "thumb_gs":         "#e8d0f8",
    "thumb_gs_border":  "#9a5ac8",
    "control":          "#b8e8c8",
    "control_border":   "#2a9a4a",
    "control_gs":       "#d8c8f8",
    "control_gs_border":"#7a4ab8",
    "text":             "#1a1a1a",
    "text_dim":         "#aaaaaa",
    "highlight":        "#c87000",
}


def _key_style(bg: str, border: str) -> str:
    return f"""
        QPushButton {{
            background-color: {bg};
            border: 1px solid {border};
            border-radius: 4px;
            color: {COLORS["text"]};
            font-family: 'Courier New', monospace;
            font-size: 10px;
            font-weight: 500;
            padding: 2px;
        }}
        QPushButton:hover {{
            background-color: {border};
            border-color: {COLORS["highlight"]};
        }}
        QPushButton:pressed {{
            border: 2px solid {COLORS["highlight"]};
        }}
    """


_ZONE_STYLES = {
    "main":       _key_style(COLORS["main"],       COLORS["main_border"]),
    "thumb":      _key_style(COLORS["thumb"],      COLORS["thumb_border"]),
    "thumb_gs":   _key_style(COLORS["thumb_gs"],   COLORS["thumb_gs_border"]),
    "control":    _key_style(COLORS["control"],    COLORS["control_border"]),
    "control_gs": _key_style(COLORS["control_gs"], COLORS["control_gs_border"]),
}


def _dimmed(style: str) -> str:
    return style.replace(f"color: {COLORS['text']}", f"color: {COLORS['text_dim']}")


# ─── Layout geometry ──────────────────────────────────────────────────────────

_TW, _TH = 96, 40
_TX = [8, 108, 208]
_TY = [10, 54, 98, 142]

_MX = 316
_BW = 88
_MH = 50
_CH = 36

# (label, btn_idx, x, y, w, h, zone)
_KEY_POSITIONS = [
    ("LMB",  0, _MX,                   10, _BW, _MH, "main"),
    ("Mid",  2, _MX + _BW + 4,         10, _BW, _MH, "main"),
    ("RMB",  1, _MX + (_BW + 4) * 2,   10, _BW, _MH, "main"),
    ("GS",   5, _MX + (_BW + 4) * 3,   10, _BW, _MH, "control"),
    ("Back", 3, _MX,                   68, _BW, _CH, "main"),
    ("Fwd",  4, _MX + _BW + 4,         68, _BW, _CH, "main"),
    ("DPI",  6, _MX,                  108, _BW, _CH, "control"),
    ("Prof", 7, _MX + _BW + 4,        108, _BW, _CH, "control"),
    ("G9",   8,  _TX[0], _TY[0], _TW, _TH, "thumb"),
    ("G10",  9,  _TX[1], _TY[0], _TW, _TH, "thumb"),
    ("G11", 10,  _TX[2], _TY[0], _TW, _TH, "thumb"),
    ("G12", 11,  _TX[0], _TY[1], _TW, _TH, "thumb"),
    ("G13", 12,  _TX[1], _TY[1], _TW, _TH, "thumb"),
    ("G14", 13,  _TX[2], _TY[1], _TW, _TH, "thumb"),
    ("G15", 14,  _TX[0], _TY[2], _TW, _TH, "thumb"),
    ("G16", 15,  _TX[1], _TY[2], _TW, _TH, "thumb"),
    ("G17", 16,  _TX[2], _TY[2], _TW, _TH, "thumb"),
    ("G18", 17,  _TX[0], _TY[3], _TW, _TH, "thumb"),
    ("G19", 18,  _TX[1], _TY[3], _TW, _TH, "thumb"),
    ("G20", 19,  _TX[2], _TY[3], _TW, _TH, "thumb"),
]

# button_idx → label (for button_clicked signal)
_IDX_TO_LABEL = {pos[1]: pos[0] for pos in _KEY_POSITIONS}


@dataclass
class ButtonAction:
    kind: str         # "key" | "macro" | "button" | "special" | "none" | "swremap"
    value: str
    routing_key: str = ""


class G600Canvas(QWidget):
    """
    Visual G600 layout (690×196 px).
    Click any button → emits signals.button_clicked("g600", label).
    Call update_bindings(buttons, gshift) to refresh labels.

    buttons: {btn_idx: ButtonAction}
    gshift:  show G-Shift layer when True
    """

    def __init__(self, plugin_name: str, signals: "AppSignals", parent=None):
        super().__init__(parent)
        self._plugin_name = plugin_name
        self._signals = signals
        self._gshift = False
        self.setFixedSize(690, 196)
        self.setStyleSheet(
            f"background-color: {COLORS['device']}; "
            "border-radius: 16px; border: 2px solid #aaaaaa;"
        )
        self.buttons: dict[int, QPushButton] = {}
        for label, idx, x, y, w, h, zone in _KEY_POSITIONS:
            btn = QPushButton(self)
            btn.setGeometry(x, y, w, h)
            btn.setStyleSheet(_ZONE_STYLES[zone])
            btn.setToolTip(label)
            btn.clicked.connect(lambda _c, lbl=label: self._on_click(lbl))
            self.buttons[idx] = btn

    def _on_click(self, label: str) -> None:
        self._signals.button_clicked.emit(self._plugin_name, label)

    def update_bindings(self, btn_map: dict[int, ButtonAction], gshift: bool = False) -> None:
        self._gshift = gshift
        for label, normal_idx, _x, _y, _w, _h, zone in _KEY_POSITIONS:
            btn = self.buttons[normal_idx]
            effective_zone = self._gs_zone(zone) if gshift else zone

            if gshift and normal_idx != 5:
                actual_idx = normal_idx + 21
            else:
                actual_idx = normal_idx

            action = btn_map.get(actual_idx, ButtonAction("none", ""))

            if gshift and normal_idx == 5:
                btn.setStyleSheet(_dimmed(_ZONE_STYLES[effective_zone]))
                btn.setText(f"{label}\nsecond-mode")
                continue

            if action.kind == "none":
                btn.setStyleSheet(_dimmed(_ZONE_STYLES[effective_zone]))
            else:
                btn.setStyleSheet(_ZONE_STYLES[effective_zone])

            btn.setText(self._short_label(label, action))

    @staticmethod
    def _gs_zone(zone: str) -> str:
        if zone == "thumb":   return "thumb_gs"
        if zone == "control": return "control_gs"
        return zone

    @staticmethod
    def _short_label(label: str, action: ButtonAction) -> str:
        if action.kind == "none":
            return f"{label}\n—"
        v = action.value
        if action.kind in ("key", "macro"):
            v = (v.replace("+KEY_LEFTCTRL", "^")
                  .replace("+KEY_LEFTSHIFT", "⇧")
                  .replace("+KEY_LEFTALT", "⌥")
                  .replace("+KEY_LEFTMETA", "⊞")
                  .replace("-KEY_LEFTCTRL", "")
                  .replace("-KEY_LEFTSHIFT", "")
                  .replace("-KEY_LEFTALT", "")
                  .replace("-KEY_LEFTMETA", "")
                  .replace("KEY_", "")
                  .strip())
        elif action.kind == "swremap":
            tokens = v.split()
            btn_name = next(
                (t.lstrip("+-").replace("BTN_", "") for t in tokens if "BTN_" in t), "?"
            )
            prefix = ""
            for t in tokens:
                if t.startswith("+"):
                    if "CTRL" in t:    prefix += "^"
                    elif "SHIFT" in t: prefix += "⇧"
                    elif "ALT" in t:   prefix += "⌥"
            v = f"SW:{prefix}{btn_name}"
        elif action.kind == "special":
            abbrev = {
                "profile-cycle-up": "→Prof", "dpi-cycle-up": "→DPI",
                "dpi-up": "DPI↑", "dpi-down": "DPI↓",
                "second-mode": "GShift", "disable": "off",
            }
            v = abbrev.get(v, v.replace("-", " "))
        elif action.kind == "button":
            names = {"1": "LMB", "2": "RMB", "3": "Mid", "4": "Back", "5": "Fwd"}
            v = names.get(v, f"btn{v}")
        if len(v) > 9:
            v = v[:8] + "…"
        return f"{label}\n{v}"
