"""
core/macro_queue.py — Shared macro execution queue for all plugins.

A single worker thread serialises all macro executions across every device.
Held-key state persists across queue entries — a key held down in one macro
stays held until an explicit release token in a later entry, or until
cancel_all() releases everything (e.g. on app switch).

Public API
----------
get_queue() → MacroQueue     module-level singleton; all plugins share one queue

MacroQueue.submit(tokens, uinput)
    Push a token list onto the queue.  Non-blocking, returns immediately.

MacroQueue.submit_macro(button_id, pressed, macro, uinput)
    Route a button press/release event through a NamedMacro.
    Handles all three modes: complete, press_release, toggle.

MacroQueue.cancel_all()
    Clear pending queue, abort in-flight macro, release all held keys.
    Call on app switch or profile change.

MacroQueue.reset_toggle(button_ids=None)
    Reset toggle state for given buttons (None = all).
    Call on profile switch so toggles start fresh.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.macro_library import NamedMacro

try:
    from evdev import ecodes as _ecodes
    _EVDEV_OK = True
except ImportError:
    _EVDEV_OK = False

import functools

from core.macro_token import expand_token, _WAIT_RE, derive_release


@functools.lru_cache(maxsize=512)
def _resolve_token(token: str) -> tuple[str, int] | None:
    """
    Cached token → (action, evdev_int_code) resolver.

    Combines expand_token() (keymacro name → evdev name) and the ecodes
    dict lookup (evdev name → int code) into a single cached call.
    The cache is process-lifetime: token strings are immutable so the
    result never changes.

    Returns None for wait tokens, unknown tokens, or unknown evdev names.
    """
    if not _EVDEV_OK:
        return None
    expanded = expand_token(token)
    if expanded is None:
        return None
    action, evdev_name = expanded
    code = _ecodes.ecodes.get(evdev_name)
    if code is None:
        return None
    return (action, code)


class MacroQueue:
    """Single-worker macro execution queue shared by all plugins."""

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self._held: dict[int, object] = {}         # evdev code → uinput device
        self._toggle: dict[str, bool] = {}         # button_id → False=A, True=B
        self._cancel = threading.Event()
        self._lock   = threading.Lock()
        self._library = None                       # set via set_library()
        self._worker = threading.Thread(
            target=self._run, daemon=True, name="MacroQueue"
        )
        self._worker.start()

    def set_library(self, library) -> None:
        """Attach the MacroLibrary so composite macro tokens can be expanded."""
        self._library = library

    # ── Public API ────────────────────────────────────────────────────────────

    def submit(self, tokens: list[str], uinput) -> None:
        """Push a token list onto the queue. Non-blocking."""
        if tokens:
            self._q.put((list(tokens), uinput))

    def submit_macro(
        self,
        button_id: str,
        pressed: bool,
        macro: "NamedMacro",
        uinput,
    ) -> None:
        """
        Route a button event through a NamedMacro, respecting its mode.

        complete      — submit press sequence on button-down only
        press_release — submit press on down, release (or auto-derived) on up
        toggle        — alternate between press (A) and release (B) sequences
        """
        mode = macro.mode

        if mode == "complete":
            if pressed and macro.press:
                self.submit(macro.press, uinput)

        elif mode == "press_release":
            if pressed:
                if macro.press:
                    self.submit(macro.press, uinput)
            else:
                rel = derive_release(macro.press) if macro.release_auto else macro.release
                if rel:
                    self.submit(rel, uinput)

        elif mode == "toggle":
            if pressed:
                with self._lock:
                    state = self._toggle.get(button_id, False)
                    self._toggle[button_id] = not state
                seq = macro.release if state else macro.press
                if seq:
                    self.submit(seq, uinput)

    def cancel_all(self) -> None:
        """
        Clear pending queue, abort in-flight macro, release all held keys.
        Call on app switch so the new app starts with a clean keyboard state.
        """
        self._cancel.set()

        # Drain pending entries
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

        # Release all held keys grouped by uinput device
        if self._held:
            by_dev: dict[int, tuple] = {}
            with self._lock:
                for code, dev in list(self._held.items()):
                    dev_id = id(dev)
                    if dev_id not in by_dev:
                        by_dev[dev_id] = (dev, [])
                    by_dev[dev_id][1].append(code)
                self._held.clear()
            for dev, codes in by_dev.values():
                for code in codes:
                    try:
                        dev.write(_ecodes.EV_KEY, code, 0)
                    except Exception:
                        pass
                try:
                    dev.syn()
                except Exception:
                    pass

        self._cancel.clear()

    def reset_toggle(self, button_ids: list[str] | None = None) -> None:
        """Reset toggle parity. None = reset all buttons."""
        with self._lock:
            if button_ids is None:
                self._toggle.clear()
            else:
                for bid in button_ids:
                    self._toggle.pop(bid, None)

    # ── Meta-macro expansion ──────────────────────────────────────────────────

    def _expand_macro_token(self, tok: str) -> list[str] | None:
        """
        Expand a named-macro reference token into its constituent evdev tokens.

        Recognises three suffix forms:
          MacroName+   → press sequence (hold all keys)
          MacroName-   → release sequence (reverse of press, LIFO order)
          MacroName    → tap: press sequence + auto-derived release

        Returns None if tok does not refer to a known named macro, so the
        caller can fall through to normal evdev resolution / skip logic.
        """
        if self._library is None:
            return None
        if tok.startswith('+'):
            base, suffix = tok[1:], '+'
        elif tok.startswith('-'):
            base, suffix = tok[1:], '-'
        else:
            base, suffix = tok, ''
        macro = self._library.get(base)
        if macro is None or not macro.press:
            return None
        release = (derive_release(macro.press)
                   if macro.release_auto else macro.release)
        if suffix == '+':
            return list(macro.press)
        elif suffix == '-':
            return list(release)
        else:
            return list(macro.press) + list(release)

    def _flatten_tokens(self, tokens: list[str], _depth: int = 8) -> list[str]:
        """
        Recursively expand any named-macro tokens until the list stabilises
        (or the depth limit is reached to prevent infinite loops).

        Tokens that resolve directly via evdev (_resolve_token returns non-None)
        or are wait tokens are left untouched.  Everything else is checked
        against the library and expanded if found.
        """
        if _depth == 0 or self._library is None:
            return tokens
        result: list[str] = []
        changed = False
        for tok in tokens:
            if _WAIT_RE.match(tok) or _resolve_token(tok) is not None:
                result.append(tok)
                continue
            expanded = self._expand_macro_token(tok)
            if expanded is not None:
                result.extend(expanded)
                changed = True
            else:
                result.append(tok)
        return self._flatten_tokens(result, _depth - 1) if changed else result

    # ── Worker thread ─────────────────────────────────────────────────────────

    def _run(self) -> None:
        while True:
            tokens, uinput = self._q.get()
            self._execute(tokens, uinput)

    def _execute(self, tokens: list[str], uinput) -> None:
        if not _EVDEV_OK:
            return
        self._cancel.clear()

        tokens = self._flatten_tokens(tokens)

        for tok in tokens:
            if self._cancel.is_set():
                break

            # Wait token — sleep in small chunks so cancel can interrupt
            m = _WAIT_RE.match(tok)
            if m:
                end = time.monotonic() + int(m.group(1)) / 1000.0
                while time.monotonic() < end:
                    if self._cancel.is_set():
                        return
                    time.sleep(0.01)
                continue

            resolved = _resolve_token(tok)
            if resolved is None:
                continue
            action, code = resolved

            try:
                if action == 'down':
                    uinput.write(_ecodes.EV_KEY, code, 1)
                    uinput.syn()
                    with self._lock:
                        self._held[code] = uinput
                elif action == 'up':
                    uinput.write(_ecodes.EV_KEY, code, 0)
                    uinput.syn()
                    with self._lock:
                        self._held.pop(code, None)
                else:  # tap
                    uinput.write(_ecodes.EV_KEY, code, 1)
                    uinput.syn()
                    uinput.write(_ecodes.EV_KEY, code, 0)
                    uinput.syn()
            except Exception:
                pass


# ── Module-level singleton ────────────────────────────────────────────────────

_SHARED: MacroQueue | None = None


def get_queue() -> MacroQueue:
    """Return the shared MacroQueue, creating it on first call."""
    global _SHARED
    if _SHARED is None:
        _SHARED = MacroQueue()
    return _SHARED
