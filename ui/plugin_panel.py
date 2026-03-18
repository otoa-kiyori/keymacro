"""
ui/plugin_panel.py — Plugin list and status panel for keymacro.

Shows all discovered plugins with their availability status.
Allows activating/deactivating plugins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QTextEdit, QSplitter,
)
from PyQt6.QtCore import Qt

if TYPE_CHECKING:
    from core.signals import AppSignals
    from core.plugin_manager import PluginManager


class PluginPanel(QWidget):
    """
    Left: list of all discovered plugins with status icons.
    Right: info pane with display_name, description, status, install hint,
           and Activate / Deactivate buttons.
    """

    def __init__(
        self,
        signals: "AppSignals",
        plugin_manager: "PluginManager",
        active_plugin_name: str | None,
        parent=None,
    ):
        super().__init__(parent)
        self._signals = signals
        self._pm = plugin_manager
        self._active_plugin_name = active_plugin_name
        self._build_ui()
        self._populate()
        self._connect_signals()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: plugin list ──
        self._list = QListWidget()
        self._list.setFixedWidth(200)
        self._list.currentRowChanged.connect(self._on_selection_changed)
        splitter.addWidget(self._list)

        # ── Right: info pane ──
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)

        self._lbl_name   = QLabel()
        self._lbl_name.setStyleSheet("font-weight: bold; font-size: 14px;")
        self._lbl_desc   = QLabel()
        self._lbl_desc.setWordWrap(True)
        self._lbl_status = QLabel()
        self._lbl_status.setWordWrap(True)

        self._hint_box = QTextEdit()
        self._hint_box.setReadOnly(True)
        self._hint_box.setVisible(False)
        self._hint_box.setMaximumHeight(120)
        self._hint_box.setStyleSheet("font-size: 11px; color: #805000;")

        btn_row = QHBoxLayout()
        self._btn_activate   = QPushButton("Activate")
        self._btn_deactivate = QPushButton("Deactivate")
        self._btn_activate.clicked.connect(self._on_activate)
        self._btn_deactivate.clicked.connect(self._on_deactivate)
        btn_row.addWidget(self._btn_activate)
        btn_row.addWidget(self._btn_deactivate)
        btn_row.addStretch()

        rl.addWidget(self._lbl_name)
        rl.addWidget(self._lbl_desc)
        rl.addWidget(self._lbl_status)
        rl.addWidget(self._hint_box)
        rl.addLayout(btn_row)
        rl.addStretch()

        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter)

    def _populate(self) -> None:
        self._list.clear()
        for name in self._pm.get_all_names():
            plugin  = self._pm.get_plugin(name)
            err     = self._pm.get_load_error(name)
            if err:
                label = f"⚠ {name}"
            elif plugin and plugin.is_available():
                label = f"✓ {plugin.display_name}"
            else:
                label = f"○ {plugin.display_name if plugin else name}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._list.addItem(item)

        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _on_selection_changed(self, row: int) -> None:
        if row < 0:
            self._clear_info()
            return
        item = self._list.item(row)
        name = item.data(Qt.ItemDataRole.UserRole)
        self._show_info(name)

    def _show_info(self, name: str) -> None:
        plugin = self._pm.get_plugin(name)
        err    = self._pm.get_load_error(name)

        if err:
            self._lbl_name.setText(name)
            self._lbl_desc.setText("")
            self._lbl_status.setText(f"<span style='color:red'>Load error</span>")
            self._hint_box.setVisible(True)
            self._hint_box.setPlainText(err)
            self._btn_activate.setEnabled(False)
            self._btn_deactivate.setEnabled(False)
            return

        if not plugin:
            self._clear_info()
            return

        available = plugin.is_available()
        is_active = name == self._active_plugin_name

        self._lbl_name.setText(plugin.display_name)
        self._lbl_desc.setText(plugin.description)

        if is_active:
            status = "<span style='color:green'>● Active</span>"
        elif available:
            status = "<span style='color:#005080'>○ Available</span>"
        else:
            status = "<span style='color:#a04000'>⚠ Unavailable</span>"
        self._lbl_status.setText(status)

        if not available:
            self._hint_box.setVisible(True)
            self._hint_box.setPlainText(plugin.get_install_hint())
        else:
            self._hint_box.setVisible(False)

        self._btn_activate.setEnabled(available and not is_active)
        self._btn_deactivate.setEnabled(is_active)

    def _clear_info(self) -> None:
        self._lbl_name.clear()
        self._lbl_desc.clear()
        self._lbl_status.clear()
        self._hint_box.setVisible(False)
        self._btn_activate.setEnabled(False)
        self._btn_deactivate.setEnabled(False)

    def _current_plugin_name(self) -> str | None:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_activate(self) -> None:
        name = self._current_plugin_name()
        if name:
            self._signals.plugin_activated.emit(name)

    def _on_deactivate(self) -> None:
        name = self._current_plugin_name()
        if name:
            self._signals.plugin_deactivated.emit(name)

    def _connect_signals(self) -> None:
        self._signals.plugin_activated.connect(self._on_plugin_state_changed)
        self._signals.plugin_deactivated.connect(self._on_plugin_state_changed)

    def _on_plugin_state_changed(self, plugin_name: str) -> None:
        self._active_plugin_name = plugin_name if self._signals.sender() else self._active_plugin_name
        # Re-read from app state by repopulating
        self._populate()
