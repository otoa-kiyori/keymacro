#!/usr/bin/env python3
"""
ui/macro_editor.py — Reusable macro sequence editor widget for keymacro.

Provides MacroEditorWidget: a QWidget that lets the user compose a
macro token sequence using category/token/mode dropdowns plus a plain-text
editor that can also be typed in directly.

Token format:
  F1                — tap F1 (press + release)
  +LeftShift        — hold Shift down
  -LeftShift        — release Shift
  Num1              — tap numpad 1
  BTN_LEFT          — click left mouse button (requires plugin software remap)
  t300              — wait 300 ms

Adapted from g13d_gui/macro_editor.py — BTN_* warning text is now generic.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QPlainTextEdit, QSpinBox,
)
from PyQt6.QtGui import (
    QFont, QTextCursor, QSyntaxHighlighter, QTextCharFormat, QColor,
)

from core.macro_token import to_new_format

# ─── Token catalog ────────────────────────────────────────────────────────────
# Each entry: (category_name, [(display_label, raw_token), ...])

TOKEN_CATEGORIES: list[tuple[str, list[tuple[str, str]]]] = [
    ("Letters", [(c, c) for c in [
        "A","B","C","D","E","F","G","H","I","J","K","L","M",
        "N","O","P","Q","R","S","T","U","V","W","X","Y","Z",
    ]]),
    ("Digits", [(c, c) for c in [
        "0","1","2","3","4","5","6","7","8","9",
    ]]),
    ("Shifted Digits", [
        ("!  Exclamation",  "Exclaim"),
        ("@  At sign",      "At"),
        ("#  Hash",         "Hash"),
        ("$  Dollar",       "Dollar"),
        ("%  Percent",      "Percent"),
        ("^  Caret",        "Caret"),
        ("&  Ampersand",    "Ampersand"),
        ("*  Asterisk",     "Asterisk"),
        ("(  Left paren",   "LeftParen"),
        (")  Right paren",  "RightParen"),
    ]),
    ("Function Keys", [(c, c) for c in [
        "F1","F2","F3","F4","F5","F6","F7","F8","F9","F10","F11","F12",
        "F13","F14","F15","F16","F17","F18","F19","F20","F21","F22","F23","F24",
    ]]),
    ("Modifiers", [
        ("Left Ctrl",    "LeftCtrl"),
        ("Right Ctrl",   "RightCtrl"),
        ("Left Shift",   "LeftShift"),
        ("Right Shift",  "RightShift"),
        ("Left Alt",     "LeftAlt"),
        ("Right Alt",    "RightAlt"),
        ("Left Win/⌘",   "LeftMeta"),
        ("Right Win/⌘",  "RightMeta"),
    ]),
    ("Navigation", [
        ("↑ Up",         "Up"),
        ("↓ Down",       "Down"),
        ("← Left",       "Left"),
        ("→ Right",      "Right"),
        ("Home",         "Home"),
        ("End",          "End"),
        ("Page Up",      "PageUp"),
        ("Page Down",    "PageDown"),
        ("Insert",       "Insert"),
        ("Delete",       "Delete"),
    ]),
    ("Special Keys", [
        ("Escape",       "Escape"),
        ("Tab",          "Tab"),
        ("Backspace",    "Backspace"),
        ("Enter",        "Enter"),
        ("Space",        "Space"),
        ("Caps Lock",    "CapsLock"),
        ("Print Screen", "PrintScreen"),
        ("Scroll Lock",  "ScrollLock"),
        ("Pause/Break",  "Pause"),
        ("Num Lock",     "NumLock"),
    ]),
    ("Symbols", [
        ("-  Minus",      "Minus"),
        ("=  Equal",      "Equal"),
        ("[  L-Brace",    "LeftBrace"),
        ("]  R-Brace",    "RightBrace"),
        (";  Semicolon",  "Semicolon"),
        ("'  Apostrophe", "Apostrophe"),
        ("`  Grave",      "Grave"),
        ("\\  Backslash", "Backslash"),
        (",  Comma",      "Comma"),
        (".  Dot",        "Dot"),
        ("/  Slash",      "Slash"),
    ]),
    ("Shifted Symbols", [
        ("_  Underscore",    "Underscore"),
        ("+  Plus",          "Plus"),
        ("{  Left curly",    "LeftCurly"),
        ("}  Right curly",   "RightCurly"),
        (":  Colon",         "Colon"),
        ("\"  Double quote", "DoubleQuote"),
        ("~  Tilde",         "Tilde"),
        ("|  Pipe",          "Pipe"),
        ("<  Less-than",     "LessThan"),
        (">  Greater-than",  "GreaterThan"),
        ("?  Question",      "Question"),
    ]),
    ("Numpad", [
        ("Num 0",        "Num0"),
        ("Num 1",        "Num1"),
        ("Num 2",        "Num2"),
        ("Num 3",        "Num3"),
        ("Num 4",        "Num4"),
        ("Num 5",        "Num5"),
        ("Num 6",        "Num6"),
        ("Num 7",        "Num7"),
        ("Num 8",        "Num8"),
        ("Num 9",        "Num9"),
        ("Num +",        "Num+"),
        ("Num -",        "Num-"),
        ("Num *",        "Num*"),
        ("Num /",        "Num/"),
        ("Num .",        "Num."),
        ("Num Enter",    "NumEnter"),
    ]),
    ("Media", [
        ("Mute",         "Mute"),
        ("Volume Up",    "VolumeUp"),
        ("Volume Down",  "VolumeDown"),
        ("Next Track",   "NextSong"),
        ("Prev Track",   "PrevSong"),
        ("Play / Pause", "PlayPause"),
        ("Stop",         "StopCd"),
    ]),
    ("Mouse Buttons", [
        ("Left Button",     "LeftButton"),
        ("Right Button",    "RightButton"),
        ("Middle Button",   "MiddleButton"),
        ("Back Button",     "BackButton"),
        ("Forward Button",  "ForwardButton"),
    ]),
]

# Action modes: (display label, token prefix)
_KEY_MODES = [("Tap",    ""), ("↓ Hold",    "+"), ("↑ Release", "-")]
_BTN_MODES = [("Click",  ""), ("↓ Hold",    "+"), ("↑ Release", "-")]
_MOUSE_CAT = "Mouse Buttons"


# ── Meta-macro syntax highlighter ─────────────────────────────────────────────

class _MetaMacroHighlighter(QSyntaxHighlighter):
    """
    Bolds any token line whose base name resolves to a composite (multi-token)
    named macro in the library.  Colour is amber to hint at potential side-effects.

    A "composite" macro is one whose press sequence contains more than one token
    (e.g. Plus → [LeftShift+, Equal+]).  Single-key built-ins like A, F5,
    LeftCtrl are NOT highlighted even though they are named macros.
    """

    _FMT_COMPOSITE = None   # initialised lazily so Qt app exists first

    @classmethod
    def _get_fmt(cls) -> QTextCharFormat:
        if cls._FMT_COMPOSITE is None:
            fmt = QTextCharFormat()
            fmt.setFontWeight(QFont.Weight.Bold)
            fmt.setForeground(QColor("#a06000"))   # warm amber
            cls._FMT_COMPOSITE = fmt
        return cls._FMT_COMPOSITE

    def __init__(self, document):
        super().__init__(document)
        self._library = None

    def set_library(self, library) -> None:
        self._library = library
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        if self._library is None:
            return
        tok = text.strip()
        if not tok:
            return
        # Resolve the macro name from the token:
        # 1. Try the full token as a macro name (handles Num+, Num-, Num*, …)
        # 2. Strip a single leading +/- (prefix hold/release) and try again
        macro = self._library.get(tok)
        if macro is None and tok and tok[0] in '+-':
            macro = self._library.get(tok[1:])
        if macro is not None and len(macro.press) > 1:
            self.setFormat(0, len(text), self._get_fmt())


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
        self._highlighter = _MetaMacroHighlighter(self.editor.document())

    def set_library(self, library) -> None:
        """Attach the MacroLibrary so composite macro tokens are highlighted."""
        self._highlighter.set_library(library)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_tokens(self) -> list[str]:
        """
        Parse the editor content into a flat token list.
        Both newlines and commas are treated as delimiters, so users can write:
            +LeftShift, +Equal      (comma-inline style)
            +LeftShift              (one-per-line style)
            +Equal
        or mix the two freely — the result is identical.
        """
        tokens = []
        for line in self.editor.toPlainText().splitlines():
            for part in line.split(","):
                t = part.strip()
                if t:
                    tokens.append(t)
        return tokens

    def set_tokens(self, tokens: list[str], inline: bool = False) -> None:
        """
        Populate the editor from a token list.

        inline=False (default) — one token per line (user-editable style).
        inline=True            — all tokens on one line, comma-separated
                                 (used for auto-derived sequences and locked
                                  multi-token press sequences so they read as
                                  a single logical unit).
        Tokens are always normalised to the current format on load.
        """
        normalised = [to_new_format(t) for t in tokens]
        if inline:
            self.editor.setPlainText(", ".join(normalised))
        else:
            self.editor.setPlainText("\n".join(normalised))

    def get_macro_string(self) -> str:
        return " ".join(self.get_tokens())

    def set_macro_string(self, macro: str):
        self.set_tokens(macro.split() if macro.strip() else [])

    def set_read_only(self, read_only: bool) -> None:
        """
        Make the editor read-only (content visible but not editable).
        Also disables the insert / move / delete controls so they match.
        """
        self.editor.setReadOnly(read_only)
        # Walk all child widgets except the editor itself and toggle them
        for child in self.findChildren(QWidget):
            if child is not self.editor:
                child.setEnabled(not read_only)

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
            "Tokens separated by newlines or commas — e.g.\n"
            "+LeftShift, A, -LeftShift\n"
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
        raw  = self.tok_combo.currentData()
        mode = self.mode_combo.currentData() or ""
        if not raw:
            return
        token = (mode + raw) if mode else raw
        self._append_line(token)

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


# ─── Named macro editor (mode + press + release) ──────────────────────────────

from PyQt6.QtWidgets import QCheckBox, QFrame, QRadioButton, QButtonGroup

from core.macro_token import validate


class NamedMacroEditorWidget(QWidget):
    """
    Full editor for a NamedMacro: mode selector, press editor, optional
    release editor, auto-derive checkbox, and live validation warnings.

    Public API:
        set_macro(named_macro)  populate all fields from a NamedMacro
        get_macro_data() → dict  {mode, press, release, release_auto}
    """

    # (internal_key, radio label, tooltip)
    MODES: list[tuple[str, str, str]] = [
        ("complete",      "Complete",
         "Single sequence fires on button press"),
        ("press_release", "Press / Release",
         "Separate sequences for button down (↓) and button up (↑)"),
        ("toggle",        "Toggle",
         "A sequence on odd presses, B sequence on even presses"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._library = None
        self._build_ui()
        self._on_mode_changed(0)

    def set_library(self, library) -> None:
        """Propagate the MacroLibrary to both sequence editors and re-validate."""
        self._library = library
        self._press_editor.set_library(library)
        self._release_editor.set_library(library)
        self._update_warnings()

    def _current_mode(self) -> str:
        """Return the internal key for the currently selected mode."""
        return self.MODES[self._mode_group.checkedId()][0]

    # ── Public API ────────────────────────────────────────────────────────────

    def set_macro(self, macro) -> None:
        """Populate from a NamedMacro (or any object with .mode/.press/.release/.release_auto)."""
        mode = getattr(macro, "mode", "complete")
        release_auto = getattr(macro, "release_auto", True)

        # Block signals while we reconfigure so _on_mode_changed / _on_auto_changed
        # don't fire intermediate updates
        self._mode_group.blockSignals(True)
        self._auto_check.blockSignals(True)

        for i, (key, _, _tip) in enumerate(self.MODES):
            if key == mode:
                self._mode_radios[i].setChecked(True)
                break

        press = getattr(macro, "press", [])
        locked = getattr(macro, "locked", False)
        # Multi-token press on locked (built-in) macros shown inline so the
        # whole chord reads as one logical unit, e.g. "+LeftShift, +Equal"
        self._press_editor.set_tokens(press, inline=locked and len(press) > 1)
        self._auto_check.setChecked(release_auto)

        # For press_release + auto-derive, show derived tokens; otherwise use stored
        if mode == "press_release" and release_auto:
            self._refresh_auto_release()
        else:
            self._release_editor.set_tokens(getattr(macro, "release", []))

        self._mode_group.blockSignals(False)
        self._auto_check.blockSignals(False)

        self._apply_mode_ui(mode, release_auto)
        self._update_warnings()

    def get_macro_data(self) -> dict:
        """Return a dict with keys: mode, press, release, release_auto."""
        mode         = self._current_mode()
        release_auto = self._auto_check.isChecked()
        # Don't store auto-derived tokens — they're always recomputed at load
        release = [] if (mode == "press_release" and release_auto) \
                     else self._release_editor.get_tokens()
        return {
            "mode":         mode,
            "press":        self._press_editor.get_tokens(),
            "release":      release,
            "release_auto": release_auto,
        }

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Mode selector — three radio buttons
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self._mode_group = QButtonGroup(self)
        self._mode_radios: list[QRadioButton] = []
        for i, (_, label, tip) in enumerate(self.MODES):
            rb = QRadioButton(label)
            rb.setToolTip(tip)
            self._mode_group.addButton(rb, i)
            self._mode_radios.append(rb)
            mode_row.addWidget(rb)
        self._mode_radios[0].setChecked(True)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # Press / A editor
        self._lbl_press = QLabel("Sequence:")
        layout.addWidget(self._lbl_press)
        self._press_editor = MacroEditorWidget()
        layout.addWidget(self._press_editor)

        # Release / B section (hidden for Complete mode)
        self._release_frame = QFrame()
        rel_layout = QVBoxLayout(self._release_frame)
        rel_layout.setContentsMargins(0, 4, 0, 0)
        rel_layout.setSpacing(4)

        rel_hdr = QHBoxLayout()
        self._lbl_release = QLabel("Release sequence:")
        rel_hdr.addWidget(self._lbl_release)
        self._auto_check = QCheckBox("Auto-derive from press")
        self._auto_check.setToolTip(
            "Reverses the hold tokens from the press sequence and flips\n"
            "+ → − so the same keys are released in the correct order.\n"
            "Uncheck to write the release sequence manually."
        )
        rel_hdr.addWidget(self._auto_check)
        rel_hdr.addStretch()
        rel_layout.addLayout(rel_hdr)

        self._release_editor = MacroEditorWidget()
        rel_layout.addWidget(self._release_editor)
        layout.addWidget(self._release_frame)

        # Validation warnings
        self._warn_label = QLabel()
        self._warn_label.setWordWrap(True)
        self._warn_label.setStyleSheet("color: #c06000; font-size: 10px;")
        self._warn_label.setVisible(False)
        layout.addWidget(self._warn_label)

        # Connections
        self._mode_group.idClicked.connect(self._on_mode_changed)
        self._auto_check.stateChanged.connect(self._on_auto_changed)
        self._press_editor.editor.textChanged.connect(self._on_press_changed)
        self._release_editor.editor.textChanged.connect(self._update_warnings)

    # ── Mode switching ────────────────────────────────────────────────────────

    def _on_mode_changed(self, idx: int) -> None:
        mode = self.MODES[idx][0]
        auto = self._auto_check.isChecked()
        self._apply_mode_ui(mode, auto)
        if mode == "press_release" and auto:
            self._refresh_auto_release()
        self._update_warnings()

    def _on_auto_changed(self, _: int) -> None:
        mode = self._current_mode()
        auto = self._auto_check.isChecked()
        if mode == "press_release":
            if auto:
                self._refresh_auto_release()
            self._release_editor.set_read_only(auto)
        self._update_warnings()

    def _apply_mode_ui(self, mode: str, release_auto: bool) -> None:
        """Set labels, visibility, and read-only state for the current mode."""
        if mode == "complete":
            self._lbl_press.setText("Sequence:")
            self._release_frame.setVisible(False)

        elif mode == "press_release":
            self._lbl_press.setText("Press sequence (↓ down):")
            self._lbl_release.setText("Release sequence (↑ up):")
            self._auto_check.setVisible(True)
            self._release_frame.setVisible(True)
            self._release_editor.set_read_only(release_auto)

        elif mode == "toggle":
            self._lbl_press.setText("A sequence (odd press):")
            self._lbl_release.setText("B sequence (even press):")
            self._auto_check.setVisible(False)
            self._release_frame.setVisible(True)
            self._release_editor.set_read_only(False)

    # ── Auto-derive ───────────────────────────────────────────────────────────

    def _refresh_auto_release(self) -> None:
        """Recompute and display the auto-derived release sequence (read-only)."""
        from core.macro_token import derive_release
        derived = derive_release(self._press_editor.get_tokens())
        # Block release editor signals so this write doesn't trigger warnings loop
        self._release_editor.editor.blockSignals(True)
        # Show inline (comma-separated) so the derived chord reads as one unit
        self._release_editor.set_tokens(derived, inline=len(derived) > 1)
        self._release_editor.editor.blockSignals(False)

    def _on_press_changed(self) -> None:
        """Called whenever press editor text changes."""
        mode = self._current_mode()
        if mode == "press_release" and self._auto_check.isChecked():
            self._refresh_auto_release()
        self._update_warnings()

    # ── Validation ────────────────────────────────────────────────────────────

    def _meta_bleed_warnings(self, tokens: list[str]) -> list[str]:
        """
        Warn when a composite macro token with a hold (+) suffix appears
        alongside other tokens.  The composite macro expands to multiple evdev
        events (e.g. Plus+ → LeftShift+, Equal+), so any token that follows
        will be executed while those modifiers are still held down.

        A standalone held composite is fine (the whole sequence IS the expansion).
        The danger arises when other tokens surround the held composite token.
        """
        if not self._library:
            return []
        # Collect positions of composite hold-tokens
        composite_hold_positions = []
        for i, tok in enumerate(tokens):
            if tok.startswith('+'):
                base = tok[1:]
                macro = self._library.get(base)
                if macro is not None and len(macro.press) > 1:
                    composite_hold_positions.append((i, tok))
        if not composite_hold_positions:
            return []
        # If EVERY token in the sequence is from the same composite hold/release
        # pair, no bleed occurs (it's a self-contained press_release macro).
        # Otherwise warn.
        warnings = []
        for idx, tok in composite_hold_positions:
            # Check whether there's anything else around this hold token
            others = [t for j, t in enumerate(tokens) if j != idx]
            # The auto-derived release of the same macro is fine (no bleed)
            base = tok[1:]   # strip leading + prefix
            macro = self._library.get(base)
            from core.macro_token import derive_release
            own_release = set(derive_release(macro.press))
            risky = [t for t in others if t not in own_release]
            if risky:
                warnings.append(
                    f"'{tok}' is a composite macro (expands to "
                    f"{', '.join(macro.press)}) — "
                    f"its modifiers stay held while adjacent tokens execute, "
                    f"which may produce unintended key combinations."
                )
        return warnings

    def _update_warnings(self) -> None:
        from core.macro_token import derive_release
        mode = self._current_mode()
        press = self._press_editor.get_tokens()

        if mode == "complete":
            warnings = validate(press)
            warnings += self._meta_bleed_warnings(press)

        elif mode == "press_release":
            # Validate press + release as one combined sequence so paired
            # hold/release tokens don't generate false "unmatched" warnings.
            if self._auto_check.isChecked():
                rel = derive_release(press)
            else:
                rel = self._release_editor.get_tokens()
            warnings = validate(press + rel)
            warnings += self._meta_bleed_warnings(press)
            warnings += self._meta_bleed_warnings(rel)

        else:  # toggle
            warnings = validate(press)
            warnings += self._meta_bleed_warnings(press)
            rel = self._release_editor.get_tokens()
            for w in validate(rel):
                warnings.append(f"B: {w}")
            for w in self._meta_bleed_warnings(rel):
                warnings.append(f"B: {w}")

        if warnings:
            self._warn_label.setText("⚠  " + "\n⚠  ".join(warnings))
            self._warn_label.setVisible(True)
        else:
            self._warn_label.setVisible(False)
