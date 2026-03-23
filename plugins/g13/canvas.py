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


def _adjust_hex(hex_color: str, factor: float) -> str:
    """Lighten (factor > 1.0) or darken (factor < 1.0) a #rrggbb color."""
    h = hex_color.lstrip("#")
    r = min(255, max(0, int(int(h[0:2], 16) * factor)))
    g = min(255, max(0, int(int(h[2:4], 16) * factor)))
    b = min(255, max(0, int(int(h[4:6], 16) * factor)))
    return f"#{r:02x}{g:02x}{b:02x}"


def _key_style_raised(bg: str, border: str) -> str:
    highlight = _adjust_hex(bg, 1.30)
    shadow    = _adjust_hex(border, 0.70)
    return f"""
        QPushButton {{
            background-color: {bg};
            border-top:    2px solid {highlight};
            border-left:   2px solid {highlight};
            border-bottom: 2px solid {shadow};
            border-right:  2px solid {shadow};
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
    """


def _key_style_sunken(bg: str, border: str) -> str:
    highlight = _adjust_hex(bg, 1.30)
    shadow    = _adjust_hex(border, 0.70)
    bg_dark   = _adjust_hex(bg, 0.85)
    return f"""
        QPushButton {{
            background-color: {bg_dark};
            border-top:    2px solid {shadow};
            border-left:   2px solid {shadow};
            border-bottom: 2px solid {highlight};
            border-right:  2px solid {highlight};
            border-radius: 4px;
            color: {COLORS["text"]};
            font-family: 'Courier New', monospace;
            font-size: 11px;
            font-weight: 500;
            padding-top: 3px; padding-left: 3px;
            padding-bottom: 1px; padding-right: 1px;
        }}
    """


_ZONE_STYLES_RAISED = {
    "g":       _key_style_raised(COLORS["g_key"],       COLORS["g_key_border"]),
    "m":       _key_style_raised(COLORS["m_key"],       COLORS["m_key_border"]),
    "l":       _key_style_raised(COLORS["l_key"],       COLORS["l_key_border"]),
    "stick":   _key_style_raised(COLORS["stick"],       COLORS["stick_border"]),
    "special": _key_style_raised(COLORS["special"],     COLORS["special_border"]),
}
_ZONE_STYLES_SUNKEN = {
    "g":       _key_style_sunken(COLORS["g_key"],       COLORS["g_key_border"]),
    "m":       _key_style_sunken(COLORS["m_key"],       COLORS["m_key_border"]),
    "l":       _key_style_sunken(COLORS["l_key"],       COLORS["l_key_border"]),
    "stick":   _key_style_sunken(COLORS["stick"],       COLORS["stick_border"]),
    "special": _key_style_sunken(COLORS["special"],     COLORS["special_border"]),
}
_ZONE_STYLES = _ZONE_STYLES_RAISED   # backwards-compat alias

_KEY_DISPLAY = {
    "STICK_UP":    "↑",
    "STICK_DOWN":  "↓",
    "STICK_LEFT":  "←",
    "STICK_RIGHT": "→",
}


_STYLE_RESET = """
    QPushButton {
        background-color: #f5d0c8;
        border-top:    2px solid #f8e8e4;
        border-left:   2px solid #f8e8e4;
        border-bottom: 2px solid #8c2c16;
        border-right:  2px solid #8c2c16;
        border-radius: 4px;
        color: #601000;
        font-family: 'Courier New', monospace;
        font-size: 10px;
        font-weight: 600;
        padding: 2px;
    }
    QPushButton:hover {
        background-color: #e89080;
        border-top:    2px solid #f0a090;
        border-left:   2px solid #f0a090;
        border-bottom: 2px solid #702010;
        border-right:  2px solid #702010;
    }
    QPushButton:pressed {
        background-color: #d8b0a8;
        border-top:    2px solid #8c2c16;
        border-left:   2px solid #8c2c16;
        border-bottom: 2px solid #f8e8e4;
        border-right:  2px solid #f8e8e4;
        padding-top: 3px; padding-left: 3px;
        padding-bottom: 1px; padding-right: 1px;
    }
"""


def _zone_for(key: str) -> str:
    if key.startswith("G"):              return "g"
    if key.startswith("M"):             return "m"
    if key in ("L1", "L2", "L3", "L4"): return "l"
    if key.startswith("STICK"):         return "stick"
    return "special"


# ─── Layout geometry ──────────────────────────────────────────────────────────

_GX = [21 + i * 93 for i in range(7)]   # 7 G-key columns (×1.15 scaled)
_GW, _GH = 89, 42
_LX = 131
_LW = 104
_LP = 108

# (key_name, x, y, w, h)
_KEY_POSITIONS = [
    ("CIRCLE",  8,         32, 104, 32),
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

    ("LEFT",        441, 296, 120, 34),
    ("STICK_UP",    565, 296, 120, 34),
    ("STICK_LEFT",  441, 334, 120, 34),
    ("STICK_RIGHT", 565, 334, 120, 34),
    ("STICK_DOWN",  504, 372, 120, 34),
    ("BD",          504, 410, 120, 34),
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
        self.setFixedSize(690, 452)
        self.setStyleSheet(
            f"background-color: {COLORS['device']}; "
            "border-radius: 16px; border: 2px solid #aaaaaa;"
        )
        self.buttons: dict[str, QPushButton] = {}
        self._current_raised: dict[str, str] = {}
        for key, x, y, w, h in _KEY_POSITIONS:
            btn = QPushButton(self)
            btn.setGeometry(x, y, w, h)
            style = _ZONE_STYLES_RAISED[_zone_for(key)]
            btn.setStyleSheet(style)
            btn.setToolTip(key)
            btn.clicked.connect(lambda checked, k=key: self._on_click(k))
            self.buttons[key] = btn
            self._current_raised[key] = style

        # Reset button — bottom-left, below the G-key block
        reset_btn = QPushButton("↺ Reset", self)
        reset_btn.setGeometry(8, 418, 115, 26)
        reset_btn.setStyleSheet(_STYLE_RESET)
        reset_btn.setToolTip("Hard-reset the G13 (USB cycle + restart capture)")
        reset_btn.clicked.connect(self._on_reset)

        signals.button_event.connect(self._on_button_event)

    def _on_reset(self) -> None:
        self._signals.device_reset.emit(self._plugin_name)

    def _on_click(self, key: str) -> None:
        self._signals.button_clicked.emit(self._plugin_name, key)

    def _on_button_event(self, plugin_name: str, button_id: str, pressed: bool) -> None:
        if plugin_name != self._plugin_name:
            return
        btn = self.buttons.get(button_id)
        if btn is None:
            return
        try:
            if pressed:
                btn.setStyleSheet(_ZONE_STYLES_SUNKEN[_zone_for(button_id)])
            else:
                btn.setStyleSheet(self._current_raised[button_id])
        except RuntimeError:
            pass  # canvas destroyed while capture thread still running

    def update_bindings(self, bindings: dict[str, str]) -> None:
        for key, btn in self.buttons.items():
            val = bindings.get(key, "")
            btn.setText(self._short_label(key, val))
            zone = _zone_for(key)
            style = _ZONE_STYLES_RAISED[zone]
            if not val:
                style = style.replace(
                    f"color: {COLORS['text']}", f"color: {COLORS['text_dim']}"
                )
            btn.setStyleSheet(style)
            self._current_raised[key] = style

    @staticmethod
    def _short_label(key: str, val: str) -> str:
        """val is already a human-readable display name — use it directly."""
        display = _KEY_DISPLAY.get(key, key)
        if not val:
            return f"{display}\n—"
        return f"{display}\n{val}"
