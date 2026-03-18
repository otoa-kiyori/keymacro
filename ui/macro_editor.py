#!/usr/bin/env python3
"""
ui/macro_editor.py — Reusable macro sequence editor widget for keymacro.

Provides MacroEditorWidget: a QWidget that lets the user compose a
macro token sequence using category/token/mode dropdowns plus a plain-text
editor that can also be typed in directly.

Token format:
  KEY_F1            — tap F1 (press + release)
  +KEY_LEFTSHIFT    — hold Shift down
  -KEY_LEFTSHIFT    — release Shift
  BTN_LEFT          — click left mouse button (requires plugin software remap)
  t300              — wait 300 ms

Adapted from g13d_gui/macro_editor.py — BTN_* warning text is now generic.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QPlainTextEdit, QSpinBox,
)
from PyQt6.QtGui import QFont, QTextCursor

# ─── Token catalog ────────────────────────────────────────────────────────────
# Each entry: (category_name, [(display_label, raw_token), ...])

TOKEN_CATEGORIES: list[tuple[str, list[tuple[str, str]]]] = [
    ("Letters", [(k[4:], k) for k in [
        "KEY_A", "KEY_B", "KEY_C", "KEY_D", "KEY_E", "KEY_F", "KEY_G",
        "KEY_H", "KEY_I", "KEY_J", "KEY_K", "KEY_L", "KEY_M", "KEY_N",
        "KEY_O", "KEY_P", "KEY_Q", "KEY_R", "KEY_S", "KEY_T", "KEY_U",
        "KEY_V", "KEY_W", "KEY_X", "KEY_Y", "KEY_Z",
    ]]),
    ("Digits", [(k[4:], k) for k in [
        "KEY_0", "KEY_1", "KEY_2", "KEY_3", "KEY_4",
        "KEY_5", "KEY_6", "KEY_7", "KEY_8", "KEY_9",
    ]]),
    ("Function Keys", [(k[4:], k) for k in [
        "KEY_F1",  "KEY_F2",  "KEY_F3",  "KEY_F4",  "KEY_F5",  "KEY_F6",
        "KEY_F7",  "KEY_F8",  "KEY_F9",  "KEY_F10", "KEY_F11", "KEY_F12",
        "KEY_F13", "KEY_F14", "KEY_F15", "KEY_F16", "KEY_F17", "KEY_F18",
        "KEY_F19", "KEY_F20", "KEY_F21", "KEY_F22", "KEY_F23", "KEY_F24",
    ]]),
    ("Modifiers", [
        ("Left Ctrl",    "KEY_LEFTCTRL"),
        ("Right Ctrl",   "KEY_RIGHTCTRL"),
        ("Left Shift",   "KEY_LEFTSHIFT"),
        ("Right Shift",  "KEY_RIGHTSHIFT"),
        ("Left Alt",     "KEY_LEFTALT"),
        ("Right Alt",    "KEY_RIGHTALT"),
        ("Left Win/⌘",   "KEY_LEFTMETA"),
        ("Right Win/⌘",  "KEY_RIGHTMETA"),
    ]),
    ("Navigation", [
        ("↑ Up",         "KEY_UP"),
        ("↓ Down",       "KEY_DOWN"),
        ("← Left",       "KEY_LEFT"),
        ("→ Right",      "KEY_RIGHT"),
        ("Home",         "KEY_HOME"),
        ("End",          "KEY_END"),
        ("Page Up",      "KEY_PAGEUP"),
        ("Page Down",    "KEY_PAGEDOWN"),
        ("Insert",       "KEY_INSERT"),
        ("Delete",       "KEY_DELETE"),
    ]),
    ("Special Keys", [
        ("Escape",       "KEY_ESC"),
        ("Tab",          "KEY_TAB"),
        ("Backspace",    "KEY_BACKSPACE"),
        ("Enter",        "KEY_ENTER"),
        ("Space",        "KEY_SPACE"),
        ("Caps Lock",    "KEY_CAPSLOCK"),
        ("Print Screen", "KEY_SYSRQ"),
        ("Scroll Lock",  "KEY_SCROLLLOCK"),
        ("Pause/Break",  "KEY_PAUSE"),
        ("Num Lock",     "KEY_NUMLOCK"),
    ]),
    ("Symbols", [
        ("— Minus",      "KEY_MINUS"),
        ("= Equal",      "KEY_EQUAL"),
        ("[ L-Brace",    "KEY_LEFTBRACE"),
        ("] R-Brace",    "KEY_RIGHTBRACE"),
        ("; Semicolon",  "KEY_SEMICOLON"),
        ("' Apostrophe", "KEY_APOSTROPHE"),
        ("` Grave",      "KEY_GRAVE"),
        ("\\ Backslash", "KEY_BACKSLASH"),
        (", Comma",      "KEY_COMMA"),
        (". Dot",        "KEY_DOT"),
        ("/ Slash",      "KEY_SLASH"),
    ]),
    ("Numpad", [
        ("KP 0",         "KEY_KP0"),
        ("KP 1",         "KEY_KP1"),
        ("KP 2",         "KEY_KP2"),
        ("KP 3",         "KEY_KP3"),
        ("KP 4",         "KEY_KP4"),
        ("KP 5",         "KEY_KP5"),
        ("KP 6",         "KEY_KP6"),
        ("KP 7",         "KEY_KP7"),
        ("KP 8",         "KEY_KP8"),
        ("KP 9",         "KEY_KP9"),
        ("KP +",         "KEY_KPPLUS"),
        ("KP −",         "KEY_KPMINUS"),
        ("KP ×",         "KEY_KPASTERISK"),
        ("KP ÷",         "KEY_KPSLASH"),
        ("KP .",         "KEY_KPDOT"),
        ("KP Enter",     "KEY_KPENTER"),
    ]),
    ("Media", [
        ("Mute",         "KEY_MUTE"),
        ("Volume Up",    "KEY_VOLUMEUP"),
        ("Volume Down",  "KEY_VOLUMEDOWN"),
        ("Next Track",   "KEY_NEXTSONG"),
        ("Prev Track",   "KEY_PREVIOUSSONG"),
        ("Play / Pause", "KEY_PLAYPAUSE"),
        ("Stop",         "KEY_STOPCD"),
    ]),
    ("Mouse Buttons", [
        ("Left Button",     "BTN_LEFT"),
        ("Right Button",    "BTN_RIGHT"),
        ("Middle Button",   "BTN_MIDDLE"),
        ("Side / Back",     "BTN_SIDE"),
        ("Extra / Forward", "BTN_EXTRA"),
    ]),
]

# Action modes: (display label, token prefix)
_KEY_MODES = [("Tap",   ""), ("↓ Down", "+"), ("↑ Up",   "-")]
_BTN_MODES = [("Click", ""), ("↓ Down", "+"), ("↑ Up",   "-")]
_MOUSE_CAT = "Mouse Buttons"


class MacroEditorWidget(QWidget):
    """
    Composite widget for composing a macro token sequence.

    Public API:
        get_tokens()          → list[str]
        set_tokens(list[str])
        get_macro_string()    → str   (space-joined tokens)
        set_macro_string(str)
        editor                — the underlying QPlainTextEdit
                                (connect .textChanged for live preview)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # ── Public API ────────────────────────────────────────────────────────────

    def get_tokens(self) -> list[str]:
        return [t.strip() for t in self.editor.toPlainText().splitlines() if t.strip()]

    def set_tokens(self, tokens: list[str]):
        self.editor.setPlainText("\n".join(tokens))

    def get_macro_string(self) -> str:
        return " ".join(self.get_tokens())

    def set_macro_string(self, macro: str):
        self.set_tokens(macro.split() if macro.strip() else [])

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── Insert row: [Category v] [Token v] [Mode v] [Insert ↵] ──
        ins = QHBoxLayout()

        self.cat_combo = QComboBox()
        self.cat_combo.setFixedWidth(128)
        for name, _ in TOKEN_CATEGORIES:
            self.cat_combo.addItem(name)
        ins.addWidget(self.cat_combo)

        self.tok_combo = QComboBox()
        self.tok_combo.setMinimumWidth(150)
        ins.addWidget(self.tok_combo)

        self.mode_combo = QComboBox()
        self.mode_combo.setFixedWidth(82)
        ins.addWidget(self.mode_combo)

        btn_ins = QPushButton("Insert ↵")
        btn_ins.setFixedWidth(76)
        btn_ins.clicked.connect(self._insert_token)
        ins.addWidget(btn_ins)
        ins.addStretch()
        layout.addLayout(ins)

        # ── Mouse Button note (shown only when Mouse Buttons category is active) ──
        self.mouse_warn = QLabel(
            "\u2699  BTN_* tokens require software remap — "
            "the active device plugin must support it."
        )
        self.mouse_warn.setStyleSheet("color: #0060a0; font-size: 10px;")
        self.mouse_warn.setWordWrap(True)
        self.mouse_warn.setVisible(False)
        layout.addWidget(self.mouse_warn)

        # ── Pause row: [Pause / wait:] [spinbox ms] [Insert Pause] ──
        pause_row = QHBoxLayout()
        pause_row.addWidget(QLabel("Pause / wait:"))
        self.pause_spin = QSpinBox()
        self.pause_spin.setRange(1, 60000)
        self.pause_spin.setValue(100)
        self.pause_spin.setSingleStep(50)
        self.pause_spin.setSuffix(" ms")
        self.pause_spin.setFixedWidth(110)
        pause_row.addWidget(self.pause_spin)
        btn_pause = QPushButton("Insert Pause")
        btn_pause.setFixedWidth(100)
        btn_pause.clicked.connect(self._insert_pause)
        pause_row.addWidget(btn_pause)
        pause_row.addStretch()
        layout.addLayout(pause_row)

        # ── Sequence editor (one token per line) ──
        self.editor = QPlainTextEdit()
        self.editor.setFixedHeight(120)
        self.editor.setFont(QFont("Courier New", 10))
        self.editor.setPlaceholderText(
            "One token per line — e.g.\n"
            "+KEY_LEFTSHIFT\n"
            "KEY_A\n"
            "-KEY_LEFTSHIFT\n"
            "t50"
        )
        layout.addWidget(self.editor)

        # ── Line manipulation: [↑ Up] [↓ Down] [✕ Delete] ──
        line_row = QHBoxLayout()
        line_row.addWidget(QLabel("Selected line:"))
        btn_up   = QPushButton("↑ Up")
        btn_down = QPushButton("↓ Down")
        btn_del  = QPushButton("✕ Delete")
        btn_up.setFixedWidth(56)
        btn_down.setFixedWidth(66)
        btn_del.setFixedWidth(66)
        btn_up.clicked.connect(self._move_up)
        btn_down.clicked.connect(self._move_down)
        btn_del.clicked.connect(self._delete_line)
        line_row.addWidget(btn_up)
        line_row.addWidget(btn_down)
        line_row.addWidget(btn_del)
        line_row.addStretch()
        layout.addLayout(line_row)

        # Connect category signal and initialise token/mode combos
        self.cat_combo.currentIndexChanged.connect(self._on_cat_changed)
        self._on_cat_changed(0)

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _on_cat_changed(self, idx: int):
        name, tokens = TOKEN_CATEGORIES[idx]
        is_btn = (name == _MOUSE_CAT)
        self.mouse_warn.setVisible(is_btn)

        self.tok_combo.blockSignals(True)
        self.tok_combo.clear()
        for display, raw in tokens:
            self.tok_combo.addItem(display, raw)
        self.tok_combo.blockSignals(False)

        self.mode_combo.blockSignals(True)
        self.mode_combo.clear()
        for label, prefix in (_BTN_MODES if is_btn else _KEY_MODES):
            self.mode_combo.addItem(label, prefix)
        self.mode_combo.blockSignals(False)

    def _insert_token(self):
        raw    = self.tok_combo.currentData()
        prefix = self.mode_combo.currentData() or ""
        if raw:
            self._append_line(f"{prefix}{raw}")

    def _insert_pause(self):
        self._append_line(f"t{self.pause_spin.value()}")

    def _append_line(self, token: str):
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self.editor.toPlainText():
            cursor.insertText(f"\n{token}")
        else:
            cursor.insertText(token)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()

    def _current_line_idx(self) -> int:
        return self.editor.textCursor().blockNumber()

    def _move_up(self):
        lines = self.editor.toPlainText().splitlines()
        idx   = self._current_line_idx()
        if idx <= 0 or not lines:
            return
        lines[idx - 1], lines[idx] = lines[idx], lines[idx - 1]
        self.editor.setPlainText("\n".join(lines))
        self._goto_line(idx - 1)

    def _move_down(self):
        lines = self.editor.toPlainText().splitlines()
        idx   = self._current_line_idx()
        if idx >= len(lines) - 1 or not lines:
            return
        lines[idx], lines[idx + 1] = lines[idx + 1], lines[idx]
        self.editor.setPlainText("\n".join(lines))
        self._goto_line(idx + 1)

    def _delete_line(self):
        lines = self.editor.toPlainText().splitlines()
        idx   = self._current_line_idx()
        if not lines:
            return
        del lines[idx]
        self.editor.setPlainText("\n".join(lines))
        if lines:
            self._goto_line(min(idx, len(lines) - 1))

    def _goto_line(self, line_idx: int):
        block = self.editor.document().findBlockByLineNumber(line_idx)
        if block.isValid():
            cursor = self.editor.textCursor()
            cursor.setPosition(block.position())
            self.editor.setTextCursor(cursor)
