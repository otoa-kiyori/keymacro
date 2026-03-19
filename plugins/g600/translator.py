#!/usr/bin/env python3
"""
plugins/g600/translator.py — Software remap bridge for the Logitech G600.

Grabs the G600's keyboard evdev interface (/dev/input/by-id/...-if01-event-kbd)
exclusively and forwards all events through a virtual uinput device, intercepting
configured "routing keys" to execute macro token sequences — including BTN_* mouse
button events that the G600 firmware cannot fire on its own.

Token format:
    +KEY_LEFTCTRL   hold Ctrl down
    BTN_LEFT        tap left mouse button (press + release)
    KEY_W           tap W
    -KEY_LEFTCTRL   release Ctrl
    t50             wait 50 ms

Copied verbatim from g600_gui/evdev_translator.py.
"""

import glob
import select
import threading
import time

try:
    import evdev
    from evdev import ecodes, UInput
    _EVDEV_OK = True
except ImportError:
    _EVDEV_OK = False

_KBD_GLOB = "/dev/input/by-id/usb-Logitech_Gaming_Mouse_G600_*-if01-event-kbd"


class EvdevTranslator(threading.Thread):
    """
    Background daemon thread that grabs the G600 keyboard interface and
    executes macro sequences for configured routing keys.

    Thread-safe: update_routing_map() may be called from any thread at any time.
    """

    def __init__(self):
        if not _EVDEV_OK:
            raise RuntimeError(
                "python3-evdev is not installed.\n"
                "Install with: sudo apt install python3-evdev"
            )
        super().__init__(daemon=True, name="EvdevTranslator")
        self._routing_map: dict = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._kbd_dev = None
        self._uinput = None
        self.error: str | None = None

    def update_routing_map(self, routing_map: dict):
        """
        Thread-safe update.

        routing_map format:
            {ecodes.KEY_F21: "+KEY_LEFTCTRL BTN_LEFT -KEY_LEFTCTRL",
             ecodes.KEY_F22: "BTN_RIGHT"}
        """
        with self._lock:
            self._routing_map = dict(routing_map)

    def stop(self):
        """Signal the thread to exit and ungrab the keyboard."""
        self._stop_event.set()

    def run(self):
        try:
            self._setup()
            self._event_loop()
        except Exception as e:
            self.error = str(e)
        finally:
            self._teardown()

    def _find_keyboard(self) -> str:
        matches = glob.glob(_KBD_GLOB)
        if not matches:
            raise RuntimeError(
                "G600 keyboard interface not found.\n"
                f"Expected symlink matching: {_KBD_GLOB}"
            )
        return matches[0]

    def _setup(self):
        kbd_path = self._find_keyboard()
        self._kbd_dev = evdev.InputDevice(kbd_path)

        kbd_caps = self._kbd_dev.capabilities(verbose=False)
        key_codes = list(kbd_caps.get(ecodes.EV_KEY, []))

        for btn in (ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE):
            if btn not in key_codes:
                key_codes.append(btn)

        for mod in (ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTSHIFT, ecodes.KEY_LEFTALT,
                    ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTCTRL):
            if mod not in key_codes:
                key_codes.append(mod)

        self._uinput = UInput(
            {ecodes.EV_KEY: key_codes},
            name="g600-swremap",
            vendor=0x046d,
            product=0xc24a,
        )
        for attempt in range(4):
            try:
                self._kbd_dev.grab()
                break
            except OSError:
                if attempt == 3:
                    raise
                time.sleep(0.2)

    def _teardown(self):
        try:
            if self._kbd_dev:
                self._kbd_dev.ungrab()
                self._kbd_dev.close()
        except Exception:
            pass
        try:
            if self._uinput:
                self._uinput.close()
        except Exception:
            pass

    def _event_loop(self):
        fd = self._kbd_dev.fd
        while not self._stop_event.is_set():
            r, _, _ = select.select([fd], [], [], 0.1)
            if not r:
                continue
            try:
                for event in self._kbd_dev.read():
                    self._dispatch(event)
            except OSError:
                break

    def _dispatch(self, event):
        with self._lock:
            routing_map = self._routing_map

        if event.type == ecodes.EV_KEY and event.code in routing_map:
            if event.value == 1:
                self._execute_macro(routing_map[event.code])
        else:
            self._uinput.write(event.type, event.code, event.value)

    def _execute_macro(self, macro: str):
        """
        Execute a macro token sequence.  Accepts both old (KEY_A, +KEY_A)
        and new (A, A+, A-) token styles via expand_token().
        """
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
        from core.macro_token import expand_token, _WAIT_RE

        hold_stack: list[int] = []

        for tok in macro.split():
            m = _WAIT_RE.match(tok)
            if m:
                time.sleep(int(m.group(1)) / 1000.0)
                continue

            expanded = expand_token(tok)
            if expanded is None:
                continue
            action, evdev_name = expanded
            code = ecodes.ecodes.get(evdev_name)
            if code is None:
                continue

            if action == 'down':
                self._uinput.write(ecodes.EV_KEY, code, 1)
                self._uinput.syn()
                hold_stack.append(code)
            elif action == 'up':
                self._uinput.write(ecodes.EV_KEY, code, 0)
                self._uinput.syn()
                if code in hold_stack:
                    hold_stack.remove(code)
            else:  # tap
                self._uinput.write(ecodes.EV_KEY, code, 1)
                self._uinput.syn()
                self._uinput.write(ecodes.EV_KEY, code, 0)
                self._uinput.syn()

        for code in reversed(hold_stack):
            self._uinput.write(ecodes.EV_KEY, code, 0)
        if hold_stack:
            self._uinput.syn()
