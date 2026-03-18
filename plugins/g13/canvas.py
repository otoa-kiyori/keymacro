"""
plugins/g13/canvas.py — Visual G13 device layout canvas.

Adapted from g13d_gui/g13d_gui.py DeviceCanvas.
Emits signals.button_clicked(plugin_name, button_id) via the AppSignals bus
instead of a direct callback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from PyQt6.QtWidgets import QWidget, QPushButton

if TYPE_CHECKING:
    from core.signals import AppSignals

# ─── Colors ───────────────────────────────────────────────────────────────────

COLORS = {
    "device":        "#e0e0e0",
    "g_key":         "#c8daf5",
    "g_key_border":  "#6a9fd8",
    "m_key":         "#fde8b0",
    "m_key_border":  "#c8960a",
    "l_key":         "#dac8f0",
    "l_key_border":  "#9a6ad8",
    "stick":         "#b8e8c8",
    "stick_border":  "#2a9a4a",
    "special":       "#d8d8d8",
    "special_border":"#888888",
    "text":          "#1a1a1a",
    "text_dim":      "#888888",
    "highlight":     "#c87000",
}


def _key_style(bg: str, border: str) -> str:
    return f"""
        QPushButton {{
            background-color: {bg};
            border: 1px solid {border};
            border-radius: 4px;
            color: {COLORS["text"]};
            font-family: 'Courier New', monospace;
            font-size: 11px;
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
    "g":       _key_style(COLORS["g_key"],       COLORS["g_key_border"]),
    "m":       _key_style(COLORS["m_key"],       COLORS["m_key_border"]),
    "l":       _key_style(COLORS["l_key"],       COLORS["l_key_border"]),
    "stick":   _key_style(COLORS["stick"],       COLORS["stick_border"]),
    "special": _key_style(COLORS["special"],     COLORS["special_border"]),
}

_KEY_DISPLAY = {
    "STICK_UP":    "↑",
    "STICK_DOWN":  "↓",
    "STICK_LEFT":  "←",
    "STICK_RIGHT": "→",
}


def _zone_for(key: str) -> str:
    if key.startswith("G"):              return "g"
    if key.startswith("M"):             return "m"
    if key in ("L1", "L2", "L3", "L4"): return "l"
    if key.startswith("STICK"):         return "stick"
    return "special"


# ─── Layout geometry ──────────────────────────────────────────────────────────

_GX = [18 + i * 81 for i in range(7)]   # 7 G-key columns
_GW, _GH = 77, 42
_LX = 114
_LW = 90
_LP = 94

# (key_name, x, y, w, h)
_KEY_POSITIONS = [
    ("TOP",  57,        32, 53, 44),
    ("L1",  _LX,        20, _LW, 32), ("L2", _LX+_LP,   20, _LW, 32),
    ("L3",  _LX+_LP*2,  20, _LW, 32), ("L4", _LX+_LP*3, 20, _LW, 32),

    ("M1",  _LX,        56, _LW, 32), ("M2", _LX+_LP,   56, _LW, 32),
    ("M3",  _LX+_LP*2,  56, _LW, 32), ("MR", _LX+_LP*3, 56, _LW, 32),

    ("G1",  _GX[0], 98, _GW, _GH),  ("G2",  _GX[1], 98, _GW, _GH),
    ("G3",  _GX[2], 98, _GW, _GH),  ("G4",  _GX[3], 98, _GW, _GH),
    ("G5",  _GX[4], 98, _GW, _GH),  ("G6",  _GX[5], 98, _GW, _GH),
    ("G7",  _GX[6], 98, _GW, _GH),

    ("G8",  _GX[0], 146, _GW, _GH), ("G9",  _GX[1], 146, _GW, _GH),
    ("G10", _GX[2], 146, _GW, _GH), ("G11", _GX[3], 146, _GW, _GH),
    ("G12", _GX[4], 146, _GW, _GH), ("G13", _GX[5], 146, _GW, _GH),
    ("G14", _GX[6], 146, _GW, _GH),

    ("G15", _GX[1], 194, _GW, _GH), ("G16", _GX[2], 194, _GW, _GH),
    ("G17", _GX[3], 194, _GW, _GH), ("G18", _GX[4], 194, _GW, _GH),
    ("G19", _GX[5], 194, _GW, _GH),

    ("G20", _GX[2], 244, _GW, _GH),
    ("G21", _GX[3], 244, _GW, _GH),
    ("G22", _GX[4], 244, _GW, _GH),

    ("LEFT",        384, 296, 104, 34),
    ("STICK_UP",    492, 296, 104, 34),
    ("STICK_LEFT",  384, 334, 104, 34),
    ("STICK_RIGHT", 492, 334, 104, 34),
    ("STICK_DOWN",  438, 372, 104, 34),
    ("BD",          438, 410, 104, 34),
]


class G13Canvas(QWidget):
    """
    Visual G13 layout.  Click any button → emits signals.button_clicked("g13", key).
    Call update_bindings(bindings) to refresh button labels.

    bindings: {key_name: value_string}  — same format as g13d bind file values.
    """

    def __init__(self, plugin_name: str, signals: "AppSignals", parent=None):
        super().__init__(parent)
        self._plugin_name = plugin_name
        self._signals = signals
        self.setFixedSize(600, 452)
        self.setStyleSheet(
            f"background-color: {COLORS['device']}; "
            "border-radius: 16px; border: 2px solid #aaaaaa;"
        )
        self.buttons: dict[str, QPushButton] = {}
        for key, x, y, w, h in _KEY_POSITIONS:
            btn = QPushButton(self)
            btn.setGeometry(x, y, w, h)
            btn.setStyleSheet(_ZONE_STYLES[_zone_for(key)])
            btn.setToolTip(key)
            btn.clicked.connect(lambda checked, k=key: self._on_click(k))
            self.buttons[key] = btn

    def _on_click(self, key: str) -> None:
        self._signals.button_clicked.emit(self._plugin_name, key)

    def update_bindings(self, bindings: dict[str, str]) -> None:
        for key, btn in self.buttons.items():
            val = bindings.get(key, "")
            btn.setText(self._short_label(key, val))
            zone = _zone_for(key)
            style = _ZONE_STYLES[zone]
            if not val:
                style = style.replace(
                    f"color: {COLORS['text']}", f"color: {COLORS['text_dim']}"
                )
            btn.setStyleSheet(style)

    @staticmethod
    def _short_label(key: str, val: str) -> str:
        display = _KEY_DISPLAY.get(key, key)
        if not val:
            return f"{display}\n—"
        v = (val.replace("KEY_LEFTCTRL+", "^")
                .replace("KEY_LEFTSHIFT+", "⇧")
                .replace("KEY_LEFTALT+", "⌥")
                .replace("KEY_", ""))
        if v.startswith("!profile "):
            v = "»" + v[9:]
        if len(v) > 9:
            v = v[:8] + "…"
        return f"{display}\n{v}"
