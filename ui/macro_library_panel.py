"""
ui/macro_library_panel.py — Global macro library browser and editor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QInputDialog, QMessageBox, QSplitter,
    QLineEdit,
)
from PyQt6.QtCore import Qt

from ui.macro_editor import MacroEditorWidget

if TYPE_CHECKING:
    from core.signals import AppSignals
    from core.macro_library import MacroLibrary, NamedMacro


class MacroLibraryPanel(QWidget):
    """
    Left: scrollable list of named macros.
    Right: macro editor + description field + Save/Delete.
    """

    def __init__(
        self,
        signals: "AppSignals",
        library: "MacroLibrary",
        parent=None,
    ):
        super().__init__(parent)
        self._signals = signals
        self._library = library
        self._current_name: str | None = None
        self._build_ui()
        self._refresh_list()
        self._connect_signals()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: list + New button ──
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Macro Library:"))

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_selection_changed)
        ll.addWidget(self._list)

        self._btn_new = QPushButton("+ New Macro")
        self._btn_new.clicked.connect(self._new_macro)
        ll.addWidget(self._btn_new)

        left.setFixedWidth(200)
        splitter.addWidget(left)

        # ── Right: editor ──
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("macro_name")
        name_row.addWidget(self._name_edit)
        rl.addLayout(name_row)

        desc_row = QHBoxLayout()
        desc_row.addWidget(QLabel("Description:"))
        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText("optional description")
        desc_row.addWidget(self._desc_edit)
        rl.addLayout(desc_row)

        rl.addWidget(QLabel("Token sequence:"))
        self._editor = MacroEditorWidget()
        rl.addWidget(self._editor)

        btn_row = QHBoxLayout()
        self._btn_save   = QPushButton("💾 Save")
        self._btn_rename = QPushButton("Rename")
        self._btn_delete = QPushButton("Delete")
        self._btn_save.clicked.connect(self._save_macro)
        self._btn_rename.clicked.connect(self._rename_macro)
        self._btn_delete.clicked.connect(self._delete_macro)
        btn_row.addWidget(self._btn_save)
        btn_row.addWidget(self._btn_rename)
        btn_row.addWidget(self._btn_delete)
        btn_row.addStretch()
        rl.addLayout(btn_row)
        rl.addStretch()

        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter)

        self._set_editor_enabled(False)

    # ── List management ───────────────────────────────────────────────────────

    def _refresh_list(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for m in self._library.get_all():
            item = QListWidgetItem(m.name)
            item.setData(Qt.ItemDataRole.UserRole, m.name)
            self._list.addItem(item)
        self._list.blockSignals(False)
        # Reselect current
        if self._current_name:
            for i in range(self._list.count()):
                if self._list.item(i).data(Qt.ItemDataRole.UserRole) == self._current_name:
                    self._list.setCurrentRow(i)
                    return
        if self._list.count() > 0:
            self._list.setCurrentRow(0)
        else:
            self._set_editor_enabled(False)

    def _on_selection_changed(self, row: int) -> None:
        if row < 0:
            self._current_name = None
            self._set_editor_enabled(False)
            return
        name = self._list.item(row).data(Qt.ItemDataRole.UserRole)
        macro = self._library.get(name)
        if macro is None:
            return
        self._current_name = name
        self._name_edit.setText(macro.name)
        self._desc_edit.setText(macro.description)
        self._editor.set_tokens(macro.tokens)
        self._set_editor_enabled(True)

    def _set_editor_enabled(self, enabled: bool) -> None:
        self._name_edit.setEnabled(enabled)
        self._desc_edit.setEnabled(enabled)
        self._editor.setEnabled(enabled)
        self._btn_save.setEnabled(enabled)
        self._btn_rename.setEnabled(enabled)
        self._btn_delete.setEnabled(enabled)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def _new_macro(self) -> None:
        name, ok = QInputDialog.getText(self, "New Macro", "Macro name (no spaces):")
        if not (ok and name.strip()):
            return
        name = name.strip().replace(" ", "_")
        from core.macro_library import NamedMacro
        try:
            self._library.add(NamedMacro(name=name, tokens=[], description=""))
            self._signals.macro_library_changed.emit()
            self._current_name = name
            self._refresh_list()
        except ValueError as e:
            QMessageBox.warning(self, "Error", str(e))

    def _save_macro(self) -> None:
        if not self._current_name:
            return
        from core.macro_library import NamedMacro
        macro = NamedMacro(
            name=self._current_name,
            tokens=self._editor.get_tokens(),
            description=self._desc_edit.text().strip(),
        )
        try:
            self._library.update(self._current_name, macro)
            self._signals.macro_library_changed.emit()
        except ValueError as e:
            QMessageBox.warning(self, "Error", str(e))

    def _rename_macro(self) -> None:
        if not self._current_name:
            return
        new_name, ok = QInputDialog.getText(
            self, "Rename Macro", "New name:", text=self._current_name
        )
        if not (ok and new_name.strip()):
            return
        new_name = new_name.strip().replace(" ", "_")
        old = self._library.get(self._current_name)
        if old is None:
            return
        from core.macro_library import NamedMacro
        updated = NamedMacro(name=new_name, tokens=old.tokens, description=old.description)
        try:
            self._library.delete(self._current_name)
            self._library.add(updated)
            self._signals.macro_library_changed.emit()
            self._current_name = new_name
            self._refresh_list()
        except ValueError as e:
            QMessageBox.warning(self, "Error", str(e))

    def _delete_macro(self) -> None:
        if not self._current_name:
            return
        reply = QMessageBox.question(
            self, "Delete Macro",
            f"Delete macro '{self._current_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._library.delete(self._current_name)
            self._signals.macro_library_changed.emit()
            self._current_name = None
            self._refresh_list()
        except ValueError as e:
            QMessageBox.warning(self, "Error", str(e))

    # ── Signal connections ────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._signals.macro_library_changed.connect(self._refresh_list)
