"""
ui/main_window.py — Main settings window for keymacro.

Tabbed layout:
  Device  — global profile selector + one canvas group per active plugin
  Macros  — global macro library browser/editor
  Plugins — plugin list, status, install hints, activate/deactivate
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QStatusBar, QScrollArea, QGroupBox,
)
from PyQt6.QtCore import Qt

from ui.profile_panel        import ProfilePanel
from ui.macro_library_panel  import MacroLibraryPanel
from ui.plugin_panel         import PluginPanel
from ui.programs_panel       import ProgramsPanel
from core.config             import get_settings

if TYPE_CHECKING:
    from core.signals        import AppSignals
    from core.plugin_manager import PluginManager
    from core.profile_store  import ProfileStore
    from core.macro_library  import MacroLibrary
    from core.program_map    import ProgramProfileMap
    from core.window_watcher import WindowWatcher


class MainWindow(QMainWindow):
    """keymacro main settings window."""

    def __init__(
        self,
        signals:        "AppSignals",
        plugin_manager: "PluginManager",
        store:          "ProfileStore",
        macro_library:  "MacroLibrary",
        active_plugins: dict,          # shared reference to KMApp._active_plugins
        program_map:    "ProgramProfileMap | None" = None,
        watcher:        "WindowWatcher | None" = None,
        parent=None,
    ):
        super().__init__(parent)
        self._signals        = signals
        self._pm             = plugin_manager
        self._store          = store
        self._macro_library  = macro_library
        self._active_plugins = active_plugins   # shared reference — stays current
        self._program_map    = program_map
        self._watcher        = watcher

        self._canvases: dict[str, QWidget] = {}  # plugin_name → canvas widget
        self._device_tab_widget: QWidget | None = None

        self.setWindowTitle("keymacro")
        self.setMinimumSize(760, 520)

        self._status = QStatusBar()
        self.setStatusBar(self._status)

        self._tabs = QTabWidget()
        self.setCentralWidget(self._tabs)

        self._build_device_tab()
        self._build_macros_tab()
        self._build_plugins_tab()
        self._build_programs_tab()

        self._connect_signals()
        self._restore_geometry()

    # ── Tab: Device ───────────────────────────────────────────────────────────

    def _build_device_tab(self) -> None:
        self._canvases.clear()

        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # Global profile selector at the top
        profile_panel = ProfilePanel(self._signals, self._store)
        outer.addWidget(profile_panel)

        if self._active_plugins:
            # Scrollable area containing one group box per active plugin
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)

            container = QWidget()
            container_layout = QVBoxLayout(container)
            container_layout.setSpacing(12)
            container_layout.setContentsMargins(0, 0, 0, 0)

            for plugin_name, plugin in self._active_plugins.items():
                group = QGroupBox(plugin.display_name)
                group_layout = QVBoxLayout(group)
                group_layout.setSpacing(6)

                # Canvas (centered)
                canvas_row = QHBoxLayout()
                canvas_row.addStretch()
                try:
                    canvas = plugin.create_canvas()
                    self._canvases[plugin_name] = canvas
                    # Populate labels from the current active profile immediately
                    profile = self._store.get_active()
                    if hasattr(canvas, "update_bindings"):
                        plugin_bindings = profile.bindings.get(plugin_name, {}) if profile else {}
                        raw = {k: " ".join(v.inline_tokens or []) for k, v in plugin_bindings.items()}
                        canvas.update_bindings(raw)
                    canvas_row.addWidget(canvas)
                except Exception as e:
                    canvas_row.addWidget(QLabel(f"Canvas error: {e}"))
                canvas_row.addStretch()
                group_layout.addLayout(canvas_row)

                # Optional device-specific settings widget (DPI, LED, etc.)
                try:
                    dsw = plugin.create_settings_widget()
                    if dsw:
                        group_layout.addWidget(dsw)
                except Exception:
                    pass

                container_layout.addWidget(group)

            container_layout.addStretch()
            scroll.setWidget(container)
            outer.addWidget(scroll, stretch=1)
        else:
            lbl = QLabel("No device active.\nActivate a plugin in the Plugins tab.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #888; font-size: 14px;")
            outer.addStretch()
            outer.addWidget(lbl)
            outer.addStretch()

        self._device_tab_widget = tab
        idx = self._tabs.indexOf(tab)
        if idx < 0:
            self._tabs.insertTab(0, tab, "Device")
        self._tabs.setCurrentIndex(0)

    def _rebuild_device_tab(self) -> None:
        old_tab = self._device_tab_widget
        idx = self._tabs.indexOf(old_tab) if old_tab else 0
        if idx < 0:
            idx = 0
        if old_tab:
            self._tabs.removeTab(idx)
            old_tab.deleteLater()
        self._build_device_tab()
        self._tabs.insertTab(idx, self._device_tab_widget, "Device")
        self._tabs.setCurrentIndex(idx)

    # ── Tab: Macros ───────────────────────────────────────────────────────────

    def _build_macros_tab(self) -> None:
        panel = MacroLibraryPanel(self._signals, self._macro_library)
        self._tabs.addTab(panel, "Macros")

    # ── Tab: Plugins ──────────────────────────────────────────────────────────

    def _build_plugins_tab(self) -> None:
        panel = PluginPanel(self._signals, self._pm, self._active_plugins)
        self._tabs.addTab(panel, "Plugins")

    # ── Tab: Programs ─────────────────────────────────────────────────────────

    def _build_programs_tab(self) -> None:
        if self._program_map is None or self._watcher is None:
            return
        panel = ProgramsPanel(
            self._signals, self._program_map, self._store, self._watcher
        )
        self._tabs.addTab(panel, "Programs")

    # ── Signal connections ────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._signals.plugin_activated.connect(self._on_plugin_activated)
        self._signals.plugin_deactivated.connect(self._on_plugin_deactivated)
        self._signals.active_profile_switched.connect(self._on_profile_switched)
        self._signals.status_message.connect(self._on_status_message)
        self._signals.plugin_error.connect(self._on_plugin_error)
        self._signals.button_clicked.connect(self._on_button_clicked)

    def _on_plugin_activated(self, plugin_name: str) -> None:
        self._rebuild_device_tab()

    def _on_plugin_deactivated(self, plugin_name: str) -> None:
        self._rebuild_device_tab()

    def _on_profile_switched(self, profile_name: str) -> None:
        self._status.showMessage(f"Profile: {profile_name}", 3000)
        # Refresh all canvas labels
        profile = self._store.get(profile_name)
        if profile:
            for plugin_name, canvas in self._canvases.items():
                if hasattr(canvas, "update_bindings"):
                    plugin_bindings = profile.bindings.get(plugin_name, {})
                    raw = {
                        k: " ".join(v.inline_tokens or [])
                        for k, v in plugin_bindings.items()
                    }
                    canvas.update_bindings(raw)

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
        if plugin_name not in self._active_plugins:
            return
        # Refuse to edit hardware-locked buttons (e.g. G600 LMB / RMB)
        plugin = self._active_plugins[plugin_name]
        locked: set[str] = getattr(plugin, "LOCKED_BUTTONS", set())
        if button_id in locked:
            return
        profile = self._store.get_active()
        if profile is None:
            return
        self._open_button_edit(plugin_name, button_id, profile)

    def _open_button_edit(self, plugin_name: str, button_id: str, profile) -> None:
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QDialogButtonBox, QLabel
        from ui.macro_editor import MacroEditorWidget
        from core.profile_store import MacroRef

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Edit button: {button_id}")
        dlg.setMinimumWidth(500)
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel(f"Plugin: <b>{plugin_name}</b>  Button: <b>{button_id}</b>"))
        layout.addWidget(QLabel("Token sequence (leave empty to unbind):"))

        editor = MacroEditorWidget()
        plugin_bindings = profile.bindings.get(plugin_name, {})
        ref = plugin_bindings.get(button_id)
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
            nested = profile.bindings.setdefault(plugin_name, {})
            if tokens:
                nested[button_id] = MacroRef(inline_tokens=tokens)
            else:
                nested.pop(button_id, None)
            self._store.save(profile)
            self._signals.profile_saved.emit(profile.name)
            # Refresh canvas labels for this plugin
            canvas = self._canvases.get(plugin_name)
            if canvas and hasattr(canvas, "update_bindings"):
                raw = {
                    k: " ".join(v.inline_tokens or [])
                    for k, v in nested.items()
                }
                canvas.update_bindings(raw)

    # ── Geometry persistence ──────────────────────────────────────────────────

    def _restore_geometry(self) -> None:
        s = get_settings()
        geom = s.value("MainWindow/geometry")
        if geom:
            self.restoreGeometry(geom)

    def closeEvent(self, event) -> None:
        s = get_settings()
        s.setValue("MainWindow/geometry", self.saveGeometry())
        # Ignore the close — just hide. The window object must stay alive so
        # "Open keymacro…" from the tray can call show() again.
        # The only way to fully quit is via the tray Quit action.
        event.ignore()
        self.hide()
