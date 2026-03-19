"""
ui/profile_panel.py — Global profile list and CRUD panel.

Profiles are now global (not per-device). Switching a profile applies it
to ALL currently active devices via the signal bus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QInputDialog, QMessageBox,
)
from PyQt6.QtCore import Qt

if TYPE_CHECKING:
    from core.signals       import AppSignals
    from core.profile_store import ProfileStore


class ProfilePanel(QWidget):
    """Global profile list with CRUD + active-profile switching."""

    def __init__(
        self,
        signals: "AppSignals",
        store:   "ProfileStore",
        parent=None,
    ):
        super().__init__(parent)
        self._signals = signals
        self._store   = store
        self._build_ui()
        self._refresh()
        self._connect_signals()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addWidget(QLabel("Profile:"))

        self._list = QListWidget()
        self._list.setMaximumHeight(120)
        self._list.currentRowChanged.connect(self._update_buttons)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        self._btn_switch = QPushButton("⚡ Switch")
        self._btn_new    = QPushButton("+ New")
        self._btn_dup    = QPushButton("Duplicate")
        self._btn_del    = QPushButton("Delete")
        self._btn_switch.setToolTip("Apply this profile to all active devices")
        self._btn_switch.clicked.connect(self._switch_profile)
        self._btn_new.clicked.connect(self._new_profile)
        self._btn_dup.clicked.connect(self._duplicate_profile)
        self._btn_del.clicked.connect(self._delete_profile)
        for btn in (self._btn_switch, self._btn_new, self._btn_dup, self._btn_del):
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        active = self._store.get_active_name()
        for p in self._store.get_all():
            label = f"● {p.name}" if p.name == active else f"   {p.name}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, p.name)
            self._list.addItem(item)
        # Re-select active
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole) == active:
                self._list.setCurrentRow(i)
                break
        self._list.blockSignals(False)
        self._update_buttons()

    def _update_buttons(self) -> None:
        selected = self._current_name()
        active   = self._store.get_active_name()
        self._btn_switch.setEnabled(bool(selected) and selected != active)
        self._btn_dup.setEnabled(bool(selected))
        self._btn_del.setEnabled(bool(selected) and self._list.count() > 1)

    def _current_name(self) -> str | None:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _on_double_click(self, item: QListWidgetItem) -> None:
        name = item.data(Qt.ItemDataRole.UserRole)
        if name:
            self._signals.active_profile_switched.emit(name)

    def _switch_profile(self) -> None:
        name = self._current_name()
        if name:
            self._signals.active_profile_switched.emit(name)

    def _new_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "New Profile", "Profile name:")
        if not (ok and name.strip()):
            return
        name = name.strip()
        try:
            self._store.create(name)
            self._signals.profile_saved.emit(name)
            self._refresh()
        except ValueError as e:
            QMessageBox.warning(self, "Error", str(e))

    def _duplicate_profile(self) -> None:
        src = self._current_name()
        if not src:
            return
        name, ok = QInputDialog.getText(
            self, "Duplicate Profile", f"New name for copy of '{src}':"
        )
        if not (ok and name.strip()):
            return
        try:
            self._store.duplicate(src, name.strip())
            self._signals.profile_saved.emit(name.strip())
            self._refresh()
        except ValueError as e:
            QMessageBox.warning(self, "Error", str(e))

    def _delete_profile(self) -> None:
        name = self._current_name()
        if not name:
            return
        reply = QMessageBox.question(
            self, "Delete Profile", f"Delete profile '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._store.delete(name)
            self._signals.profile_deleted.emit(name)
            self._refresh()
        except ValueError as e:
            QMessageBox.warning(self, "Error", str(e))

    # ── Signal connections ────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        # Use profile_changed (emitted after store.set_active) not
        # active_profile_switched (emitted before) — avoids reading stale state.
        self._signals.profile_changed.connect(lambda _: self._refresh())
        self._signals.profile_saved.connect(lambda _: self._refresh())
        self._signals.profile_deleted.connect(lambda _: self._refresh())
