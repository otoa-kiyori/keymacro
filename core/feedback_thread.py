"""
core/feedback_thread.py — reusable command-queue thread for core→device feedback.

Plugins that need a dedicated output thread (LED colour, display updates,
force-feedback, etc.) can subclass FeedbackThread and override handle().

Design:
  - Single-slot queue: if a new command arrives before the previous one is
    processed, the stale command is discarded.  Only the latest matters.
  - Daemon thread: exits automatically when the main process exits.
  - Exceptions in handle() are silently swallowed — the thread never crashes.

Usage:
    class MyFeedback(FeedbackThread):
        def handle(self, command):
            # write to device, update LED, etc.
            ...

    fb = MyFeedback(name="MyDevice-Feedback")
    fb.start()
    fb.send("Combat")   # thread-safe, callable from Qt or any thread
    fb.stop()
"""

from __future__ import annotations

import queue
import threading
from typing import Any


class FeedbackThread(threading.Thread):
    """
    Daemon thread with a single-slot command queue.

    send(command)  — thread-safe, callable from any thread; latest wins
    stop()         — signal clean exit and wait for the thread to join
    handle(cmd)    — override in subclass to process each command
    """

    def __init__(self, name: str = "FeedbackThread") -> None:
        super().__init__(daemon=True, name=name)
        self._queue: queue.Queue[Any] = queue.Queue()
        self._stop = threading.Event()

    def send(self, command: Any) -> None:
        """Thread-safe: enqueue command.  Discards any unprocessed pending command."""
        try:
            self._queue.get_nowait()   # drop stale
        except queue.Empty:
            pass
        self._queue.put(command)

    def stop(self) -> None:
        """Signal the thread to exit and unblock its queue.get()."""
        self._stop.set()
        self._queue.put(None)   # unblock

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                cmd = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if cmd is None or self._stop.is_set():
                break
            try:
                self.handle(cmd)
            except Exception:
                pass   # never crash the feedback thread

    def handle(self, command: Any) -> None:
        """Override in subclass to process a command."""
        raise NotImplementedError
