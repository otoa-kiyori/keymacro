"""
ui/plugin_panel.py — Plugin list and status panel for keymacro.

Multiple plugins can be active simultaneously.
Activate adds to the active set; Deactivate removes from it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QTextEdit, QSplitter,
)
from PyQt6.QtCore import Qt

if TYPE_CHECKING:
    from core.signals        import AppSignals
    from core.plugin_manager import PluginManager


class PluginPanel(QWidget):
    """
    Left: list of all discovered plugins with status icons.
    Right: info pane — display_name, description, status, install hint,
           Activate / Deactivate buttons.

    Active plugin set is tracked locally via signals so the panel stays
    in sync without holding a direct reference to _active_plugins.
    """

    def __init__(
        self,
        signals:        "AppSignals",
        plugin_manager: "PluginManager",
        active_plugins: dict,          # shared reference to KMApp._active_plugins
        parent=None,
    ):
        super().__init__(parent)
        self._signals        = signals
        self._pm             = plugin_manager
        # Track active set locally — kept in sync via signals
        self._active_names: set[str] = set(active_plugins.keys())
        self._build_ui()
        self._populate()
        self._connect_signals()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: plugin list ──
        self._list = QListWidget()
        self._list.setFixedWidth(220)
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
        current_name = self._current_plugin_name()
        self._list.blockSignals(True)
        self._list.clear()
        for name in self._pm.get_all_names():
            plugin = self._pm.get_plugin(name)
            err    = self._pm.get_load_error(name)
            is_active = name in self._active_names
            if err:
                label = f"⚠ {name}"
            elif is_active:
                label = f"● {plugin.display_name}"
            elif plugin and plugin.is_available():
                label = f"○ {plugin.display_name}"
            else:
                label = f"○ {plugin.display_name if plugin else name}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._list.addItem(item)
        self._list.blockSignals(False)

        # Restore selection
        if current_name:
            for i in range(self._list.count()):
                if self._list.item(i).data(Qt.ItemDataRole.UserRole) == current_name:
                    self._list.setCurrentRow(i)
                    return
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _on_selection_changed(self, row: int) -> None:
        if row < 0:
            self._clear_info()
            return
        name = self._list.item(row).data(Qt.ItemDataRole.UserRole)
        self._show_info(name)

    def _show_info(self, name: str) -> None:
        plugin    = self._pm.get_plugin(name)
        err       = self._pm.get_load_error(name)
        is_active = name in self._active_names

        if err:
            self._lbl_name.setText(name)
            self._lbl_desc.setText("")
            self._lbl_status.setText("<span style='color:red'>Load error</span>")
            self._hint_box.setVisible(True)
            self._hint_box.setPlainText(err)
            self._btn_activate.setEnabled(False)
            self._btn_deactivate.setEnabled(False)
            return

        if not plugin:
            self._clear_info()
            return

        available = plugin.is_available()
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
        self._signals.plugin_activated.connect(self._on_plugin_activated)
        self._signals.plugin_deactivated.connect(self._on_plugin_deactivated)

    def _on_plugin_activated(self, plugin_name: str) -> None:
        self._active_names.add(plugin_name)
        self._populate()

    def _on_plugin_deactivated(self, plugin_name: str) -> None:
        self._active_names.discard(plugin_name)
        self._populate()
