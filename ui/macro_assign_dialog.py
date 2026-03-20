"""
ui/macro_assign_dialog.py — Button macro assignment dialog.

Embeds a full MacroLibraryPanel so the user can create, edit, and assign
macros to a device button without leaving the dialog.

Usage
-----
    dlg = MacroAssignDialog(
        signals, library,
        plugin_name="g600", button_id="G9",
        current_macro_name="ctrl_z",   # pre-selects that macro; "" for unbound
        parent=self,
    )
    if dlg.exec() == QDialog.DialogCode.Accepted:
        name = dlg.result_name   # str = assigned macro; "" = cleared
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel,
)
from PyQt6.QtCore import Qt

from ui.macro_library_panel import MacroLibraryPanel

if TYPE_CHECKING:
    from core.signals import AppSignals
    from core.macro_library import MacroLibrary


class MacroAssignDialog(QDialog):
    """
    Full macro editor / picker dialog for assigning a macro to one button.

    The left panel lists and searches macros; the right panel lets the user
    edit or create them.  At the bottom: Assign, Clear binding, and Cancel.

    Double-clicking a macro in the list is equivalent to clicking Assign.

    result_name  str   name of the selected macro ("" means clear binding)
    """

    def __init__(
        self,
        signals:            "AppSignals",
        library:            "MacroLibrary",
        plugin_name:        str,
        button_id:          str,
        current_macro_name: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Assign macro — {plugin_name} / {button_id}")
        self.setMinimumSize(860, 580)
        self.result_name = current_macro_name   # updated on accept

        self._build_ui(signals, library, plugin_name, button_id, current_macro_name)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(
        self,
        signals:            "AppSignals",
        library:            "MacroLibrary",
        plugin_name:        str,
        button_id:          str,
        current_macro_name: str,
    ) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QLabel(
            f"Device: <b>{plugin_name}</b> &nbsp;·&nbsp; Button: <b>{button_id}</b>"
        )
        hdr.setTextFormat(Qt.TextFormat.RichText)
        hdr.setStyleSheet("font-size: 13px; padding-bottom: 4px;")
        layout.addWidget(hdr)

        # ── Full macro library panel ───────────────────────────────────────────
        self._panel = MacroLibraryPanel(signals, library, parent=self)
        layout.addWidget(self._panel, stretch=1)

        # Pre-select the currently assigned macro (if any)
        if current_macro_name:
            self._panel.select_macro(current_macro_name)

        # ── Bottom button row ─────────────────────────────────────────────────
        btn_row = QHBoxLayout()

        self._btn_assign = QPushButton("✓  Assign selected macro")
        self._btn_assign.setDefault(True)
        self._btn_assign.setMinimumWidth(180)

        btn_clear = QPushButton("Clear binding")
        btn_cancel = QPushButton("Cancel")

        btn_row.addWidget(self._btn_assign)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        # ── Connections ───────────────────────────────────────────────────────
        self._btn_assign.clicked.connect(self._assign_current)
        btn_clear.clicked.connect(self._clear_binding)
        btn_cancel.clicked.connect(self.reject)

        # Double-click in the list → assign immediately
        self._panel.macro_activated.connect(self._assign_by_name)

        # Keep Assign button enabled/disabled based on selection
        self._panel._list.currentRowChanged.connect(self._update_assign_button)
        self._update_assign_button()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _update_assign_button(self) -> None:
        self._btn_assign.setEnabled(self._panel.current_macro_name is not None)

    def _assign_current(self) -> None:
        name = self._panel.current_macro_name
        if name:
            self._assign_by_name(name)

    def _assign_by_name(self, name: str) -> None:
        self.result_name = name
        self.accept()

    def _clear_binding(self) -> None:
        self.result_name = ""
        self.accept()
