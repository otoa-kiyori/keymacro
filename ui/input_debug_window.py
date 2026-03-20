"""
ui/input_debug_window.py — Live button-event debug window.

Opens on demand from the Plugins tab.  While open:
  - The capture's routing map is cleared → no macros fire.
  - A raw callback streams every button press/release into the log.

Closing the window clears the callback and re-applies the active profile,
returning the device to normal operation.

Cross-thread delivery
---------------------
The capture thread calls _raw_cb() which puts events into a SimpleQueue
(always thread-safe, never raises).  A QTimer on the main thread drains
the queue every 30 ms.  Avoids pyqtSignal.emit() from a plain Python thread,
which can raise exceptions that are silently swallowed by the dispatch layer.

Rendering
---------
QTextEdit is set read-only so the user cannot type in it.
QTextEdit.textCursor().insertHtml() silently no-ops when read-only.
The fix: QTextCursor(document) creates a cursor that writes directly to the
underlying QTextDocument, which has no knowledge of the widget's read-only
state, so insertHtml/insertBlock always work.
"""

from __future__ import annotations

import queue as _queue
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel,
)
from PyQt6.QtCore import Qt, QTime, QTimer
from PyQt6.QtGui import QTextCursor

if TYPE_CHECKING:
    from core.signals       import AppSignals
    from core.profile_store import ProfileStore


class InputDebugWindow(QDialog):
    """
    Non-modal live-event log for a single device plugin.

    open  → update_routing_map({}) + set_debug_mode(True) + set_raw_callback
    close → set_raw_callback(None) + set_debug_mode(False) + re-apply profile
    """

    def __init__(
        self,
        capture,                # G600/G13 RawCapture instance
        plugin_id:    str,      # internal name e.g. "g600" — for signal matching
        display_name: str,      # human label e.g. "Logitech G600 Gaming Mouse"
        signals:      "AppSignals",
        store:        "ProfileStore",
        parent=None,
    ):
        super().__init__(parent)
        self._capture     = capture
        self._plugin_id   = plugin_id
        self._signals     = signals
        self._store       = store

        # Thread-safe queue: capture thread puts, main-thread timer drains.
        self._event_queue: _queue.SimpleQueue = _queue.SimpleQueue()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(30)
        self._poll_timer.timeout.connect(self._drain_queue)

        self.setWindowTitle(f"Input Debug — {display_name}")
        self.setMinimumSize(420, 340)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)

        self._build_ui()
        signals.plugin_deactivated.connect(self._on_plugin_deactivated)
        self._enter_debug()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        banner = QLabel("⚠  Macro engine paused — close this window to resume")
        banner.setStyleSheet("color: #c08040; font-size: 11px;")
        layout.addWidget(banner)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFontFamily("Courier New, monospace")
        self._log.setFontPointSize(10)
        layout.addWidget(self._log)

        btn_row = QHBoxLayout()
        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self._log.clear)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    # ── Debug mode lifecycle ──────────────────────────────────────────────────

    def _enter_debug(self) -> None:
        if self._capture is None:
            return
        if not self._capture.is_alive():
            err = getattr(self._capture, "error", None) or "Capture thread is not running."
            self._append_html(
                f'<span style="color:#cc3333;"><b>⚠ Capture thread is not running</b></span>'
            )
            self._append_html(
                f'<span style="color:#888888;">{err}</span>'
            )
            self._append_html(
                '<span style="color:#888888;"><i>Check that /dev/uinput is accessible '
                'and udev rules are installed. See README for details.</i></span>'
            )
            return
        self._capture.update_routing_map({})
        self._capture.set_debug_mode(True)
        self._capture.set_raw_callback(self._raw_cb)
        self._poll_timer.start()
        self._append_html(
            '<span style="color:#888888;"><i>⏱  Waiting for input events…</i></span>'
        )

    def _exit_debug(self) -> None:
        self._poll_timer.stop()
        if self._capture is None:
            return
        self._capture.set_raw_callback(None)
        self._capture.set_debug_mode(False)
        active = self._store.get_active()
        if active:
            self._signals.active_profile_switched.emit(active.name)

    # ── Raw callback (called from capture thread — must be lock-free) ─────────

    def _raw_cb(self, button_id: str, pressed: bool) -> None:
        print(f"[DBG3-raw_cb] {button_id} {'▼' if pressed else '▲'}", flush=True)
        self._event_queue.put((button_id, pressed))
        print(f"[DBG3-raw_cb] queued — queue size now ~{self._event_queue.qsize()}", flush=True)

    # ── Main-thread queue drain (called by QTimer every 30 ms) ───────────────

    def _drain_queue(self) -> None:
        while True:
            try:
                button_id, pressed = self._event_queue.get_nowait()
            except _queue.Empty:
                break
            print(f"[DBG4-drain] dequeued {button_id} pressed={pressed}", flush=True)
            self._on_event(button_id, pressed)

    # ── Event display ─────────────────────────────────────────────────────────

    def _append_html(self, html: str) -> None:
        """Write HTML to the log, bypassing the read-only guard on the widget.

        QTextEdit.textCursor() returns a cursor whose inserts are blocked when
        the widget is read-only.  QTextCursor(document) writes directly to the
        underlying QTextDocument, which has no read-only concept.
        """
        doc    = self._log.document()
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        before = doc.toPlainText()
        if not doc.isEmpty():
            cursor.insertBlock()
        cursor.insertHtml(html)
        after = doc.toPlainText()
        print(f"[DBG6-append] doc chars before={len(before)} after={len(after)}", flush=True)
        self._log.ensureCursorVisible()

    def _on_event(self, button_id: str, pressed: bool) -> None:
        print(f"[DBG5-on_event] {button_id} pressed={pressed}", flush=True)
        ts    = QTime.currentTime().toString("HH:mm:ss.zzz")
        arrow = "▼" if pressed else "▲"

        if button_id.startswith("?"):
            html = (f'<span style="color:#888888;"><i>{arrow} {button_id}</i></span>'
                    f'<span style="color:#666666;">&nbsp;&nbsp;&nbsp;{ts}</span>')
        else:
            color = "#00cc44" if pressed else "#ff5555"
            html = (f'<span style="color:{color};"><b>{arrow} {button_id}</b></span>'
                    f'<span style="color:#888888;">&nbsp;&nbsp;&nbsp;{ts}</span>')

        self._append_html(html)

    def _on_plugin_deactivated(self, plugin_name: str) -> None:
        if plugin_name == self._plugin_id:
            self._capture = None   # capture is dead; skip _exit_debug teardown
            self.close()

    def closeEvent(self, event) -> None:
        try:
            self._signals.plugin_deactivated.disconnect(self._on_plugin_deactivated)
        except (TypeError, RuntimeError):
            pass   # already disconnected — safe to ignore
        self._exit_debug()
        super().closeEvent(event)
