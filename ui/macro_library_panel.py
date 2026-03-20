"""
ui/macro_library_panel.py — Global macro library browser and editor.

Left panel: searchable list of named macros.
Right panel: full NamedMacroEditorWidget (mode + press + release + warnings).

Supports all three macro modes:
  complete      — single sequence fires on press
  press_release — separate press/release sequences (with auto-derive)
  toggle        — A on odd presses, B on even presses
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QInputDialog, QMessageBox, QSplitter,
    QLineEdit, QApplication, QStyleOptionViewItem, QStyle,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRectF
from PyQt6.QtGui import (
    QTextDocument, QAbstractTextDocumentLayout, QPalette, QColor,
)

from PyQt6.QtWidgets import QStyledItemDelegate

from ui.macro_editor import NamedMacroEditorWidget


# ── Mode-badge HTML delegate ──────────────────────────────────────────────────

_MODE_SUFFIX_HTML: dict[str, str] = {
    "press_release": ' <span style="color: #c08080; font-size: 0.82em;">(P/R)</span>',
    "toggle":        ' <span style="color: #7080c0; font-size: 0.82em;">(T)</span>',
}


class _MacroListDelegate(QStyledItemDelegate):
    """Renders list items as HTML so mode-badge suffixes can be coloured."""

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        style = opt.widget.style() if opt.widget else QApplication.style()

        # Draw the background / selection highlight (without text)
        opt_bg = QStyleOptionViewItem(opt)
        opt_bg.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt_bg, painter)

        # Render HTML text
        doc = QTextDocument()
        doc.setHtml(opt.text)
        doc.setDocumentMargin(1)

        text_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget
        )

        ctx = QAbstractTextDocumentLayout.PaintContext()
        if opt.state & QStyle.StateFlag.State_Selected:
            ctx.palette.setColor(
                QPalette.ColorRole.Text,
                opt.palette.color(QPalette.ColorGroup.Active,
                                  QPalette.ColorRole.HighlightedText),
            )

        painter.save()
        painter.translate(text_rect.topLeft())
        # Vertically centre the text in the row
        y_off = max(0.0, (text_rect.height() - doc.size().height()) / 2)
        painter.translate(0.0, y_off)
        painter.setClipRect(QRectF(0, 0, text_rect.width(), text_rect.height()))
        doc.documentLayout().draw(painter, ctx)
        painter.restore()

    def sizeHint(self, option, index):
        # Use the default size (standard row height); badges don't change row height
        return super().sizeHint(option, index)

if TYPE_CHECKING:
    from core.signals import AppSignals
    from core.macro_library import MacroLibrary, NamedMacro


class MacroLibraryPanel(QWidget):
    """
    Left: searchable list of named macros.
    Right: macro editor (mode + display_name + press/release + description) + Save/Delete.

    Signals
    -------
    macro_activated(name)
        Emitted when the user double-clicks a macro in the list.
        Used by MacroAssignDialog to assign-on-double-click.
    """

    macro_activated = pyqtSignal(str)   # macro name, on double-click

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

    # ── Public helpers for MacroAssignDialog ──────────────────────────────────

    @property
    def current_macro_name(self) -> str | None:
        """Name of the macro currently selected in the list."""
        return self._current_name

    def select_macro(self, name: str) -> None:
        """Scroll to and select the macro with the given name."""
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole) == name:
                self._list.setCurrentRow(i)
                self._list.scrollToItem(self._list.item(i))
                return

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: search + list + New button ──────────────────────────────────
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)

        ll.addWidget(QLabel("Macro Library:"))

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search by name or token…")
        self._search.textChanged.connect(self._refresh_list)
        ll.addWidget(self._search)

        self._list = QListWidget()
        self._list.setItemDelegate(_MacroListDelegate(self._list))
        self._list.currentRowChanged.connect(self._on_selection_changed)
        self._list.itemDoubleClicked.connect(
            lambda item: self.macro_activated.emit(
                item.data(Qt.ItemDataRole.UserRole) or ""
            )
        )
        ll.addWidget(self._list, stretch=1)

        self._btn_new = QPushButton("+ New Macro")
        self._btn_new.clicked.connect(self._new_macro)
        ll.addWidget(self._btn_new)

        left.setMinimumWidth(180)
        left.setMaximumWidth(240)
        splitter.addWidget(left)

        # ── Right: editor panel ────────────────────────────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        rl.setSpacing(6)

        # Machine name (key used in bindings — not editable after creation)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name (key):"))
        self._name_label = QLabel("—")
        self._name_label.setStyleSheet("font-family: monospace; color: #666;")
        name_row.addWidget(self._name_label)
        name_row.addStretch()
        rl.addLayout(name_row)

        # Locked / built-in banner (hidden for user macros)
        self._locked_banner = QLabel("🔒  Built-in macro — read only")
        self._locked_banner.setStyleSheet(
            "color: #888; font-style: italic; font-size: 11px;"
            "background: #f4f0e8; border-radius: 3px; padding: 2px 6px;"
        )
        self._locked_banner.setVisible(False)
        rl.addWidget(self._locked_banner)

        self._disp_edit = QLineEdit()
        self._disp_edit.setPlaceholderText("<Display Name>")
        rl.addWidget(self._disp_edit)

        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText("<Optional Description>")
        rl.addWidget(self._desc_edit)

        # Mode + sequence editors
        self._macro_editor = NamedMacroEditorWidget()
        self._macro_editor.set_library(self._library)
        rl.addWidget(self._macro_editor, stretch=1)

        # Buttons
        btn_row = QHBoxLayout()
        self._btn_save   = QPushButton("💾 Save")
        self._btn_rename = QPushButton("Rename…")
        self._btn_delete = QPushButton("Delete")
        self._btn_save.clicked.connect(self._save_macro)
        self._btn_rename.clicked.connect(self._rename_macro)
        self._btn_delete.clicked.connect(self._delete_macro)
        btn_row.addWidget(self._btn_save)
        btn_row.addWidget(self._btn_rename)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_delete)
        rl.addLayout(btn_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter)

        self._set_editor_enabled(False)

    # ── List management ───────────────────────────────────────────────────────

    def _refresh_list(self) -> None:
        query = self._search.text().strip()
        macros = self._library.search(query) if query else self._library.get_all()

        self._list.blockSignals(True)
        self._list.clear()
        last_category: str = ""
        for m in macros:
            # Insert a non-selectable separator when the category changes
            # (only for built-ins that have a category tag; user macros get
            # a single "My Macros" header on the first one)
            cat = getattr(m, "_category", "")
            if m.locked and cat and cat != last_category:
                sep = QListWidgetItem(f"── {cat} ──")
                sep.setFlags(Qt.ItemFlag.NoItemFlags)   # not selectable/clickable
                sep.setForeground(QColor("#888888"))
                self._list.addItem(sep)
                last_category = cat
            elif not m.locked and last_category != "__user__":
                sep = QListWidgetItem("── My Macros ──")
                sep.setFlags(Qt.ItemFlag.NoItemFlags)
                sep.setForeground(QColor("#888888"))
                self._list.addItem(sep)
                last_category = "__user__"

            base = m.display_name or m.name
            if m.locked:
                # Muted grey for built-ins — entire label including mode badge
                badge = _MODE_SUFFIX_HTML.get(m.mode, "")
                # Replace vivid badge colours with a uniform muted tone
                badge_grey = (
                    badge
                    .replace("#c08080", "#aaaaaa")
                    .replace("#7080c0", "#aaaaaa")
                )
                html = f'<span style="color: #999999;">{base}</span>{badge_grey}'
            else:
                html = f"{base}{_MODE_SUFFIX_HTML.get(m.mode, '')}"
            item = QListWidgetItem(html)
            item.setData(Qt.ItemDataRole.UserRole, m.name)
            tooltip = m.description or m.name
            if m.locked:
                tooltip = f"[Built-in]  {tooltip}"
            item.setToolTip(tooltip)
            self._list.addItem(item)
        self._list.blockSignals(False)

        # Reselect current item
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
        item = self._list.item(row)
        if item is None:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        macro = self._library.get(name)
        if macro is None:
            return
        self._current_name = name
        self._name_label.setText(macro.name)
        self._disp_edit.setText(macro.display_name)
        self._desc_edit.setText(macro.description)
        self._macro_editor.set_macro(macro)
        self._set_editor_enabled(True, locked=macro.locked)

    def _set_editor_enabled(self, enabled: bool, locked: bool = False) -> None:
        editable = enabled and not locked
        self._locked_banner.setVisible(enabled and locked)
        self._disp_edit.setEnabled(editable)
        self._desc_edit.setEnabled(editable)
        # For locked macros the editor is still shown (so content is visible)
        # but set to read-only so nothing can be changed.
        self._macro_editor.setEnabled(enabled)
        if enabled:
            self._macro_editor.setProperty("readOnlyOverride", locked)
            # Lock/unlock each sub-editor inside NamedMacroEditorWidget
            self._macro_editor._press_editor.set_read_only(locked)
            for rb in self._macro_editor._mode_radios:
                rb.setEnabled(not locked)
            self._macro_editor._auto_check.setEnabled(not locked)
            if not locked:
                # Re-apply normal mode UI so release editor enable state is correct
                mode = self._macro_editor._current_mode()
                auto = self._macro_editor._auto_check.isChecked()
                self._macro_editor._apply_mode_ui(mode, auto)
            else:
                # For locked: also lock release editor
                self._macro_editor._release_editor.set_read_only(True)
        self._btn_save.setEnabled(editable)
        self._btn_rename.setEnabled(editable)
        self._btn_delete.setEnabled(editable)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def _new_macro(self) -> None:
        name, ok = QInputDialog.getText(self, "New Macro", "Macro name (no spaces):")
        if not (ok and name.strip()):
            return
        name = name.strip().replace(" ", "_")
        from core.macro_library import NamedMacro
        try:
            self._library.add(NamedMacro(name=name, display_name=name))
            self._signals.macro_library_changed.emit()
            self._current_name = name
            self._refresh_list()
        except ValueError as e:
            QMessageBox.warning(self, "Error", str(e))

    def _save_macro(self) -> None:
        if not self._current_name:
            return
        from core.macro_library import NamedMacro
        data = self._macro_editor.get_macro_data()
        display = self._disp_edit.text().strip() or self._current_name
        macro = NamedMacro(
            name         = self._current_name,
            display_name = display,
            description  = self._desc_edit.text().strip(),
            mode         = data["mode"],
            press        = data["press"],
            release      = data["release"],
            release_auto = data["release_auto"],
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
        updated = NamedMacro(
            name         = new_name,
            display_name = old.display_name if old.display_name != old.name else new_name,
            description  = old.description,
            mode         = old.mode,
            press        = old.press,
            release      = old.release,
            release_auto = old.release_auto,
        )
        try:
            # Add first; if that succeeds, remove the old one.
            self._library.add(updated)
            self._library.delete(self._current_name)
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
            f"Delete macro '{self._current_name}'?\n"
            "Any profiles referencing it will lose the binding.",
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

    # ── Signals ───────────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._signals.macro_library_changed.connect(self._refresh_list)
