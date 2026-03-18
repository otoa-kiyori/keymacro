"""
ui/main_window.py — Main settings window for keymacro.

Tabbed layout:
  Device  — device canvas + profile selector + optional device settings widget
  Macros  — global macro library browser/editor
  Plugins — plugin list, status, install hints, activate/deactivate
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QStatusBar, QPushButton,
)
from PyQt6.QtCore import Qt, QByteArray

from ui.profile_panel        import ProfilePanel
from ui.macro_library_panel  import MacroLibraryPanel
from ui.plugin_panel         import PluginPanel
from core.config             import get_settings

if TYPE_CHECKING:
    from core.signals        import AppSignals
    from core.plugin_manager import PluginManager
    from core.profile_store  import ProfileStore
    from core.macro_library  import MacroLibrary


class MainWindow(QMainWindow):
    """keymacro main settings window."""

    def __init__(
        self,
        signals:          "AppSignals",
        plugin_manager:   "PluginManager",
        profile_stores:   dict[str, "ProfileStore"],
        macro_library:    "MacroLibrary",
        active_plugin_name: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._signals          = signals
        self._pm               = plugin_manager
        self._stores           = profile_stores
        self._macro_library    = macro_library
        self._active_plugin    = active_plugin_name

        self.setWindowTitle("keymacro")
        self.setMinimumSize(760, 520)

        self._status = QStatusBar()
        self.setStatusBar(self._status)

        self._tabs = QTabWidget()
        self.setCentralWidget(self._tabs)

        self._device_tab_widget:  QWidget | None = None
        self._canvas_widget:      QWidget | None = None
        self._profile_panel:      ProfilePanel | None = None
        self._device_settings_widget: QWidget | None = None

        self._build_device_tab()
        self._build_macros_tab()
        self._build_plugins_tab()

        self._connect_signals()
        self._restore_geometry()

    # ── Tab: Device ───────────────────────────────────────────────────────────

    def _build_device_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        plugin_name = self._active_plugin
        plugin = self._pm.get_plugin(plugin_name) if plugin_name else None

        if plugin and plugin.is_available():
            # Profile selector
            store = self._stores.get(plugin_name)
            if store:
                self._profile_panel = ProfilePanel(
                    self._signals, store, plugin_name
                )
                layout.addWidget(self._profile_panel)

            # Device canvas (scrollable via HBox centering)
            canvas_row = QHBoxLayout()
            canvas_row.addStretch()
            try:
                canvas = plugin.create_canvas()
                self._canvas_widget = canvas
                canvas_row.addWidget(canvas)
            except Exception as e:
                err_label = QLabel(f"Canvas error: {e}")
                canvas_row.addWidget(err_label)
            canvas_row.addStretch()
            layout.addLayout(canvas_row)

            # Optional device-specific settings widget (DPI, LED, etc.)
            try:
                dsw = plugin.create_settings_widget()
                if dsw:
                    self._device_settings_widget = dsw
                    layout.addWidget(dsw)
            except Exception:
                pass

            layout.addStretch()
        else:
            msg = "No device active." if not plugin else f"{plugin.display_name} is not available."
            lbl = QLabel(msg)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #888; font-size: 14px;")
            layout.addStretch()
            layout.addWidget(lbl)
            layout.addStretch()

        self._device_tab_widget = tab
        idx = self._tabs.indexOf(tab)
        if idx < 0:
            self._tabs.insertTab(0, tab, "Device")
        self._tabs.setCurrentIndex(0)

    def _rebuild_device_tab(self) -> None:
        """Replace the Device tab after plugin activation."""
        idx = self._tabs.indexOf(self._device_tab_widget) if self._device_tab_widget else 0
        if idx < 0:
            idx = 0
        self._tabs.removeTab(idx)
        self._canvas_widget = None
        self._profile_panel = None
        self._device_settings_widget = None
        self._build_device_tab()
        self._tabs.insertTab(idx, self._device_tab_widget, "Device")
        self._tabs.setCurrentIndex(idx)

    # ── Tab: Macros ───────────────────────────────────────────────────────────

    def _build_macros_tab(self) -> None:
        panel = MacroLibraryPanel(self._signals, self._macro_library)
        self._tabs.addTab(panel, "Macros")

    # ── Tab: Plugins ──────────────────────────────────────────────────────────

    def _build_plugins_tab(self) -> None:
        panel = PluginPanel(self._signals, self._pm, self._active_plugin)
        self._tabs.addTab(panel, "Plugins")

    # ── Signal connections ────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._signals.plugin_activated.connect(self._on_plugin_activated)
        self._signals.active_profile_switched.connect(self._on_profile_switched)
        self._signals.status_message.connect(self._on_status_message)
        self._signals.plugin_error.connect(self._on_plugin_error)
        self._signals.button_clicked.connect(self._on_button_clicked)

    def _on_plugin_activated(self, plugin_name: str) -> None:
        self._active_plugin = plugin_name
        self._rebuild_device_tab()

    def _on_profile_switched(self, plugin_name: str, profile_name: str) -> None:
        if plugin_name == self._active_plugin:
            self._status.showMessage(f"Profile: {profile_name}", 3000)

    def _on_status_message(self, msg: str) -> None:
        if msg == "open_window":
            self.show()
            self.raise_()
            self.activateWindow()
        else:
            self._status.showMessage(msg, 4000)

    def _on_plugin_error(self, plugin_name: str, error: str) -> None:
        self._status.showMessage(f"[{plugin_name}] {error}", 6000)

    def _on_button_clicked(self, plugin_name: str, button_id: str) -> None:
        """Open a button edit dialog when a canvas button is clicked."""
        if plugin_name != self._active_plugin:
            return
        store = self._stores.get(plugin_name)
        if store is None:
            return
        profile = store.get_active()
        if profile is None:
            return
        self._open_button_edit(plugin_name, button_id, profile, store)

    def _open_button_edit(self, plugin_name, button_id, profile, store) -> None:
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QDialogButtonBox, QLabel
        from ui.macro_editor import MacroEditorWidget
        from core.profile_store import MacroRef

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Edit button: {button_id}")
        dlg.setMinimumWidth(500)
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel(f"Button: <b>{button_id}</b>"))
        layout.addWidget(QLabel("Token sequence (leave empty to unbind):"))

        editor = MacroEditorWidget()
        ref = profile.bindings.get(button_id)
        if ref and ref.inline_tokens:
            editor.set_tokens(ref.inline_tokens)
        layout.addWidget(editor)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            tokens = editor.get_tokens()
            if tokens:
                profile.bindings[button_id] = MacroRef(inline_tokens=tokens)
            else:
                profile.bindings.pop(button_id, None)
            store.save(profile)
            self._signals.profile_saved.emit(plugin_name, profile.name)
            # Refresh canvas labels
            if self._canvas_widget and hasattr(self._canvas_widget, "update_bindings"):
                raw = {k: " ".join(v.inline_tokens or []) for k, v in profile.bindings.items()}
                self._canvas_widget.update_bindings(raw)

    # ── Geometry persistence ──────────────────────────────────────────────────

    def _restore_geometry(self) -> None:
        s = get_settings()
        geom = s.value("MainWindow/geometry")
        if geom:
            self.restoreGeometry(geom)

    def closeEvent(self, event) -> None:
        s = get_settings()
        s.setValue("MainWindow/geometry", self.saveGeometry())
        event.accept()   # hide, not quit (QuitOnLastWindowClosed=False)
