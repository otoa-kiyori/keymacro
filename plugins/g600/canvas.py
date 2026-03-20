"""
plugins/g600/canvas.py — Visual G600 device layout canvas.

Adapted from g600_gui/g600_gui.py DeviceCanvas.
Emits signals.button_clicked(plugin_name, button_id) via the AppSignals bus.
button_id is the label string ("LMB", "G9", etc.) for consistency with G13 style.
"""

from __future__ import annotations

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

# Buttons that must never be reassigned (primary mouse clicks).
# They are shown locked with a distinct style and cannot be clicked.
_LOCKED_LABELS: dict[str, str] = {
    "LMB": "LMB\nLeft Click",
    "RMB": "RMB\nRight Click",
}

_STYLE_LOCKED = f"""
    QPushButton {{
        background-color: #e0e0e0;
        border: 1px dashed #999999;
        border-radius: 4px;
        color: #888888;
        font-family: 'Courier New', monospace;
        font-size: 10px;
        font-weight: 500;
        padding: 2px;
    }}
    QPushButton:disabled {{
        background-color: #e0e0e0;
        color: #888888;
    }}
"""


def _dimmed(style: str) -> str:
    return style.replace(f"color: {COLORS['text']}", f"color: {COLORS['text_dim']}")


_STYLE_RESET = """
    QPushButton {
        background-color: #f5d0c8;
        border: 1px solid #c84020;
        border-radius: 4px;
        color: #601000;
        font-family: 'Courier New', monospace;
        font-size: 10px;
        font-weight: 600;
        padding: 2px;
    }
    QPushButton:hover {
        background-color: #e89080;
        border-color: #a02000;
    }
    QPushButton:pressed {
        border: 2px solid #c84020;
    }
"""


# ─── Layout geometry ──────────────────────────────────────────────────────────
# Button widths scaled ×1.15 from original (96→110, 88→101).
# Groups centered in 690px canvas: thumb(338) + gap(12) + main(311) = 661px,
# left margin = 15px, right margin = 14px.

_TW, _TH = 110, 40              # thumb-pad button width/height
_TX = [15, 129, 243]            # thumb-pad column x positions (gap=4)
_TY = [10, 54, 98, 142]         # thumb-pad row y positions (gap=4)

_MX = 365                       # main-button group left edge
_BW = 101                       # main button width
_MH = 50
_CH = 36

# (label, btn_idx, x, y, w, h, zone)
_KEY_POSITIONS = [
    ("LMB",  0, _MX,                   10, _BW, _MH, "main"),
    ("Mid",  2, _MX + _BW + 4,         10, _BW, _MH, "main"),
    ("RMB",  1, _MX + (_BW + 4) * 2,   10, _BW, _MH, "main"),
    ("Back", 3, _MX,                      68, _BW, _CH, "main"),
    ("Fwd",  4, _MX + _BW + 4,           68, _BW, _CH, "main"),
    ("GS",   5, _MX + (_BW + 4) * 2,     68, _BW, _CH, "control"),
    ("G7",  20, _MX,                     108, _BW, _CH, "main"),
    ("G8",  21, _MX + _BW + 4,          108, _BW, _CH, "main"),
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



class G600Canvas(QWidget):
    """
    Visual G600 layout (690×196 px).
    Click any button → emits signals.button_clicked("g600", label).
    Call update_bindings(bindings) to refresh labels.

    bindings: {label → token_string}  e.g. {"G9": "KEY_A", "LMB": "BTN_LEFT"}
    """

    def __init__(self, plugin_name: str, signals: "AppSignals", parent=None):
        super().__init__(parent)
        self._plugin_name = plugin_name
        self._signals = signals
        self._gshift = False
        self.setFixedSize(690, 232)
        self.setStyleSheet(
            f"background-color: {COLORS['device']}; "
            "border-radius: 16px; border: 2px solid #aaaaaa;"
        )
        self.buttons: dict[int, QPushButton] = {}
        for label, idx, x, y, w, h, zone in _KEY_POSITIONS:
            btn = QPushButton(self)
            btn.setGeometry(x, y, w, h)
            if label in _LOCKED_LABELS:
                btn.setStyleSheet(_STYLE_LOCKED)
                btn.setText(_LOCKED_LABELS[label])
                btn.setToolTip(f"{label} — locked (cannot be reassigned)")
                btn.setEnabled(False)
            else:
                btn.setStyleSheet(_ZONE_STYLES[zone])
                btn.setToolTip(label)
                btn.clicked.connect(lambda _c, lbl=label: self._on_click(lbl))
            self.buttons[idx] = btn

        # Reset button — bottom-left of canvas
        reset_btn = QPushButton("↺ Reset", self)
        reset_btn.setGeometry(8, 196, 100, 26)
        reset_btn.setStyleSheet(_STYLE_RESET)
        reset_btn.setToolTip("Hard-reset the G600 (USB cycle + restart capture)")
        reset_btn.clicked.connect(self._on_reset)

    def _on_reset(self) -> None:
        self._signals.device_reset.emit(self._plugin_name)

    def _on_click(self, label: str) -> None:
        if label not in _LOCKED_LABELS:
            self._signals.button_clicked.emit(self._plugin_name, label)

    def update_bindings(self, bindings: dict[str, str]) -> None:
        """
        Update button labels from a {label → display_name} dict.
        Values are already human-readable display names — no further formatting.
        LMB and RMB are skipped — they are locked to their hardware function.
        """
        for label, idx, _x, _y, _w, _h, zone in _KEY_POSITIONS:
            if label in _LOCKED_LABELS:
                continue  # never touch locked buttons
            btn = self.buttons[idx]
            display = bindings.get(label, "")
            if display:
                btn.setStyleSheet(_ZONE_STYLES[zone])
                btn.setText(f"{label}\n{display}")
            else:
                btn.setStyleSheet(_dimmed(_ZONE_STYLES[zone]))
                btn.setText(f"{label}\n—")
