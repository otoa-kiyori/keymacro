"""
ui/main_window.py — Main settings window for keymacro.

Tabbed layout:
  Device  — global profile selector + one canvas group per active plugin
  Macros  — global macro library browser/editor
  Plugins — plugin list, status, install hints, activate/deactivate
"""

from __future__ import annotations

import threading
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

        self._update_title(store.get_active_name())
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
                        plugin_bindings = profile.bindings.get(plugin_name, {}) if profile is not None else {}
                        canvas.update_bindings(self._binding_labels(plugin_bindings))
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
        panel = PluginPanel(self._signals, self._pm, self._active_plugins, self._store)
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
        self._signals.profile_changed.connect(self._update_title)
        self._signals.status_message.connect(self._on_status_message)
        self._signals.plugin_error.connect(self._on_plugin_error)
        self._signals.button_clicked.connect(self._on_button_clicked)
        self._signals.device_reset.connect(self._on_device_reset)

    def _update_title(self, profile_name: str | None) -> None:
        if not profile_name or profile_name == "Default":
            self.setWindowTitle("KeyMacro")
        else:
            self.setWindowTitle(f"KM: {profile_name}")

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
                    canvas.update_bindings(self._binding_labels(plugin_bindings))

    def _on_status_message(self, msg: str) -> None:
        if msg == "open_window":
            self.show()
            self.raise_()
            self.activateWindow()
        else:
            self._status.showMessage(msg, 4000)

    def _on_device_reset(self, plugin_name: str) -> None:
        plugin = self._active_plugins.get(plugin_name)
        if plugin is None:
            return
        self._status.showMessage(f"Resetting {plugin_name}…", 0)

        def _worker() -> None:
            try:
                plugin.reset()
                self._signals.status_message.emit(f"{plugin_name} reset OK")
            except Exception as e:
                self._signals.plugin_error.emit(plugin_name, f"Reset failed: {e}")

        threading.Thread(target=_worker, daemon=True).start()

    def _on_plugin_error(self, plugin_name: str, error: str) -> None:
        self._status.showMessage(f"[{plugin_name}] {error}", 6000)

    def _on_button_clicked(self, plugin_name: str, button_id: str) -> None:
        """Open a button edit dialog when a canvas button is clicked."""
        # Re-check plugin is still active — it may have been deactivated after
        # the canvas was built but before the button was clicked.
        plugin = self._active_plugins.get(plugin_name)
        if plugin is None:
            return
        # Refuse to edit hardware-locked buttons (e.g. G600 LMB / RMB)
        locked: set[str] = getattr(plugin, "LOCKED_BUTTONS", set())  # type: ignore[assignment]
        if button_id in locked:
            return
        profile = self._store.get_active()
        if profile is None:
            return
        self._open_button_edit(plugin_name, button_id, profile)

    def _binding_labels(self, plugin_bindings: dict) -> dict[str, str]:
        """Produce {button_id: display_label} from a plugin's binding dict.

        The label is the macro's display_name (falling back to its name).
        Buttons with no binding or whose macro was deleted are omitted.
        """
        labels: dict[str, str] = {}
        for btn_id, ref in plugin_bindings.items():
            if ref and ref.macro_name:
                macro = self._macro_library.get(ref.macro_name)
                if macro:
                    labels[btn_id] = macro.display_name or macro.name
                else:
                    labels[btn_id] = f"? {ref.macro_name}"  # macro deleted
        return labels

    def _open_button_edit(self, plugin_name: str, button_id: str, profile) -> None:
        """Open the full macro editor/picker dialog to assign a macro to a button."""
        from PyQt6.QtWidgets import QDialog
        from ui.macro_assign_dialog import MacroAssignDialog
        from core.profile_store import MacroRef

        plugin_bindings = profile.bindings.get(plugin_name, {})
        current_ref = plugin_bindings.get(button_id)
        current_name = current_ref.macro_name if current_ref else ""

        dlg = MacroAssignDialog(
            signals            = self._signals,
            library            = self._macro_library,
            plugin_name        = plugin_name,
            button_id          = button_id,
            current_macro_name = current_name,
            parent             = self,
        )

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        nested = profile.bindings.setdefault(plugin_name, {})
        name = dlg.result_name
        if name:
            nested[button_id] = MacroRef(macro_name=name)
        else:
            nested.pop(button_id, None)

        self._store.save(profile)
        self._signals.profile_saved.emit(profile.name)

        # Re-apply profile so the capture thread picks up the new routing
        self._signals.active_profile_switched.emit(profile.name)

        # Refresh canvas labels for this plugin
        canvas = self._canvases.get(plugin_name)
        if canvas and hasattr(canvas, "update_bindings"):
            canvas.update_bindings(self._binding_labels(nested))

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
