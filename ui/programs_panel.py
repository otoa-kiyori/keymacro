"""
ui/programs_panel.py — Program → Profile auto-switching panel.

When a mapped program becomes the active window, keymacro automatically
switches to its assigned profile.  All other windows fall back to "Default".

The panel manages the ProgramProfileMap store and shows watcher status.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QDialog, QDialogButtonBox, QLineEdit, QComboBox,
    QHeaderView,
)
from PyQt6.QtCore import Qt

if TYPE_CHECKING:
    from core.signals        import AppSignals
    from core.program_map    import ProgramProfileMap
    from core.profile_store  import ProfileStore
    from core.window_watcher import WindowWatcher


class ProgramsPanel(QWidget):
    """
    Table of (resource_class → profile_name) mappings with Add / Remove
    controls and live watcher status.
    """

    def __init__(
        self,
        signals:        "AppSignals",
        program_map:    "ProgramProfileMap",
        store:          "ProfileStore",
        watcher:        "WindowWatcher",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._signals     = signals
        self._map         = program_map
        self._store       = store
        self._watcher     = watcher
        self._build_ui()
        self._refresh()
        self._connect_signals()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        info = QLabel(
            "When a listed program becomes the active window, keymacro "
            "switches to its assigned profile automatically.\n"
            "All other windows → <b>Default</b> profile."
        )
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(info)

        # Mapping table
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Program (resource class)", "Profile"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table, stretch=1)

        # Buttons
        btn_row = QHBoxLayout()
        self._btn_add    = QPushButton("+ Add")
        self._btn_remove = QPushButton("Remove")
        self._btn_add.clicked.connect(self._on_add)
        self._btn_remove.clicked.connect(self._on_remove)
        btn_row.addWidget(self._btn_add)
        btn_row.addWidget(self._btn_remove)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Live detection label
        self._lbl_detected = QLabel("Detected: —")
        self._lbl_detected.setStyleSheet("color: #888; font-style: italic;")
        layout.addWidget(self._lbl_detected)

        # Watcher status + restart button
        status_row = QHBoxLayout()
        self._lbl_status = QLabel()
        self._btn_restart_watcher = QPushButton("↺ Restart watcher")
        self._btn_restart_watcher.setToolTip(
            "Stop and restart the KWin window watcher. "
            "Use this if auto-switching stopped working."
        )
        self._btn_restart_watcher.clicked.connect(self._on_restart_watcher)
        status_row.addWidget(self._lbl_status, stretch=1)
        status_row.addWidget(self._btn_restart_watcher)
        layout.addLayout(status_row)
        self._update_status()

    # ── Populate ──────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        self._table.setRowCount(0)
        for resource_class, profile_name in sorted(self._map.get_all().items()):
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(resource_class))
            self._table.setItem(row, 1, QTableWidgetItem(profile_name))
        self._update_status()

    def _update_status(self) -> None:
        if self._watcher.is_running:
            self._lbl_status.setText(
                "<span style='color:green'>● Watcher active</span>"
                " — auto-switching enabled"
            )
        else:
            self._lbl_status.setText(
                "<span style='color:#a04000'>○ Watcher unavailable</span>"
                " — KWin scripting not accessible; "
                "mappings will apply on next restart if KWin becomes reachable"
            )
        self._lbl_status.setTextFormat(Qt.TextFormat.RichText)

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _on_add(self) -> None:
        dlg = _AddMappingDialog(self._store, self._watcher, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            resource_class, profile_name = dlg.result_mapping()
            if resource_class and profile_name:
                self._map.set(resource_class, profile_name)
                self._refresh()

    def _on_remove(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        item = self._table.item(row, 0)
        if item:
            self._map.remove(item.text())
            self._refresh()

    def _on_restart_watcher(self) -> None:
        self._watcher.stop()
        ok = self._watcher.start()
        self._update_status()
        if ok:
            self._signals.status_message.emit("Window watcher restarted")
        else:
            self._signals.status_message.emit("Window watcher failed to start — KWin scripting unavailable")

    # ── Signal connections ────────────────────────────────────────────────────

    def _on_window_detected(self, resource_class: str) -> None:
        if not resource_class:
            self._lbl_detected.setText("Detected: (no window)")
            return
        profile = self._map.get_profile_for(resource_class)
        if profile:
            self._lbl_detected.setText(
                f"Detected: <b>{resource_class}</b> → {profile}"
            )
            self._lbl_detected.setStyleSheet("color: #4a9; font-style: italic;")
        else:
            self._lbl_detected.setText(
                f"Detected: <b>{resource_class}</b> → Default (no mapping)"
            )
            self._lbl_detected.setStyleSheet("color: #888; font-style: italic;")
        self._lbl_detected.setTextFormat(Qt.TextFormat.RichText)

    def _connect_signals(self) -> None:
        # Refresh profile column when profiles are added/deleted
        self._signals.profile_saved.connect(lambda _: self._refresh())
        self._signals.profile_deleted.connect(lambda _: self._refresh())
        # Live detection display
        self._watcher.active_app_changed.connect(self._on_window_detected)


# ── Add mapping dialog ────────────────────────────────────────────────────────

class _AddMappingDialog(QDialog):
    """Small dialog to capture a (resource_class, profile) pair."""

    def __init__(
        self,
        store:   "ProfileStore",
        watcher: "WindowWatcher",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Program Mapping")
        self.setMinimumWidth(400)
        self._watcher = watcher
        self._build_ui(store)

    def _build_ui(self, store: "ProfileStore") -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Resource class row
        layout.addWidget(QLabel("Program resource class (e.g. steam, code, firefox):"))
        class_row = QHBoxLayout()
        self._edit_class = QLineEdit()
        self._edit_class.setPlaceholderText("resource class")
        self._btn_paste = QPushButton("Paste last window")
        self._btn_paste.setToolTip(
            "Fill with the resource class of the last non-keymacro active window"
        )
        self._btn_paste.clicked.connect(self._paste_last)
        class_row.addWidget(self._edit_class, stretch=1)
        class_row.addWidget(self._btn_paste)
        layout.addLayout(class_row)

        # Profile row
        layout.addWidget(QLabel("Profile to switch to:"))
        self._combo = QComboBox()
        for p in store.get_all():
            self._combo.addItem(p.name, p.name)
        layout.addWidget(self._combo)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _paste_last(self) -> None:
        cls = self._watcher.last_external_class
        if cls:
            self._edit_class.setText(cls)

    def result_mapping(self) -> tuple[str, str]:
        return self._edit_class.text().strip().lower(), self._combo.currentData() or ""
