"""
plugins/g600/raw_capture.py — Pure evdev capture for the Logitech G600.

Opens and exclusively grabs every interface listed in buttons.csv.
The device names in the CSV are the exact by-id suffix strings
(e.g. "event-mouse", "if01-event-kbd", "event-if01"); the serial-number
portion is wildcarded so the code works on any G600 unit.

Signal detection uses (device_suffix, ev_type, ev_code / bitmask) directly
from the CSV — no name translation layer.

No external daemon or system service required.
"""

from __future__ import annotations

import glob as _glob
import select
import threading
import time

try:
    import evdev
    from evdev import ecodes, UInput
    _EVDEV_OK = True
except ImportError:
    _EVDEV_OK = False

from core.macro_queue import get_queue

from plugins.g600.button_map import BUTTONS, BY_ID, DEVICE_NAMES, KEY_BTNS, ABS_BTNS

# by-id path prefix common to all G600 interfaces (serial number wildcarded)
_BY_ID_PREFIX = "/dev/input/by-id/usb-Logitech_Gaming_Mouse_G600_*-"

# Derived from button_map — exported so plugin.py can check device presence
_MOUSE_GLOB = _BY_ID_PREFIX + "event-mouse"
_KBD_GLOB   = _BY_ID_PREFIX + "if01-event-kbd"
_IF01_GLOB  = _BY_ID_PREFIX + "event-if01"


def _find_device(suffix: str) -> str:
    """Return the first by-id path matching the given suffix, or raise."""
    matches = _glob.glob(_BY_ID_PREFIX + suffix)
    if not matches:
        raise RuntimeError(
            f"G600 interface not found: *-{suffix}\n"
            f"Is the G600 plugged in?"
        )
    return matches[0]


class G600RawCapture(threading.Thread):
    """
    Daemon thread that owns all G600 raw interfaces.

    Devices opened are determined entirely by buttons.csv — no hardcoding
    in Python.  Adding a new interface only requires a new row in the CSV.

    Profile switch:  call update_routing_map() from any thread — instant,
                     no restart needed.

    routing map: {button_id: (press_macro, release_macro)}
    """

    def __init__(self) -> None:
        if not _EVDEV_OK:
            raise RuntimeError(
                "python3-evdev is not installed.\n"
                "Install with: pip install evdev  or  sudo apt install python3-evdev"
            )
        super().__init__(daemon=True, name="G600RawCapture")

        # Routing: (device_suffix, ev_code_or_mask) → NamedMacro
        self._key_routing: dict[tuple[str, int], object] = {}
        self._abs_routing: dict[tuple[str, int], object] = {}
        self._lock       = threading.Lock()
        self._stop_event = threading.Event()

        # Opened devices: suffix → InputDevice
        self._devs: dict[str, "evdev.InputDevice"] = {}
        self._uinput = None

        # Per-device EV_ABS bitmask state
        self._abs_state: dict[str, int] = {}  # device_suffix → current bitmask

        self.error: str | None = None
        self._raw_cb   = None
        self._debug_mode = False   # when True: suppress non-locked button passthrough

    # ── Public API ────────────────────────────────────────────────────────────

    def update_routing_map(self, routing: dict[str, object]) -> None:
        """Thread-safe routing map update.  Call on every profile switch.

        routing: {button_id: NamedMacro}
        """
        q = get_queue()
        q.cancel_all()
        q.reset_toggle(list(routing.keys()))

        key_r: dict[tuple[str, int], object] = {}
        abs_r: dict[tuple[str, int], object] = {}

        for btn_id, macro in routing.items():
            defn = BY_ID.get(btn_id)
            if defn is None or defn.locked:
                continue
            if defn.ev_type == 1:
                key_r[(defn.device, defn.ev_code)] = macro
            elif defn.ev_type == 3:
                abs_r[(defn.device, defn.press_value)] = macro

        with self._lock:
            self._key_routing = key_r
            self._abs_routing = abs_r

    def set_raw_callback(self, fn) -> None:
        """Register fn(button_id: str, pressed: bool) — fires on every button event."""
        with self._lock:
            self._raw_cb = fn

    def set_debug_mode(self, enabled: bool) -> None:
        """When True, non-locked buttons are suppressed (not passed to OS).
        LMB/RMB (locked=True) always pass through regardless."""
        with self._lock:
            self._debug_mode = enabled

    def stop(self) -> None:
        self._stop_event.set()

    # ── Thread lifecycle ──────────────────────────────────────────────────────

    def run(self) -> None:
        try:
            self._setup()
            self._event_loop()
        except Exception as e:
            self.error = str(e)
        finally:
            self._teardown()

    def _setup(self) -> None:
        # Open every device named in the CSV
        for suffix in DEVICE_NAMES:
            self._devs[suffix] = evdev.InputDevice(_find_device(suffix))

        # Collect capabilities for the uinput virtual device
        key_codes: set[int] = set()
        rel_codes: set[int] = set()
        for dev in self._devs.values():
            caps = dev.capabilities(verbose=False)
            key_codes.update(caps.get(ecodes.EV_KEY, []))
            rel_codes.update(caps.get(ecodes.EV_REL, []))

        # Ensure macro emission keys are available
        for code in (
            ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE,
            ecodes.BTN_SIDE, ecodes.BTN_EXTRA, ecodes.BTN_FORWARD, ecodes.BTN_BACK,
            ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL,
            ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT,
            ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT, ecodes.KEY_LEFTMETA,
        ):
            key_codes.add(code)

        self._uinput = UInput(
            {ecodes.EV_KEY: sorted(key_codes), ecodes.EV_REL: sorted(rel_codes)},
            name="g600-keymacro",
            vendor=0x046d,
            product=0xc24a,
        )

        # Grab all devices exclusively — grab earlier ones if a later one fails
        grabbed: list["evdev.InputDevice"] = []
        try:
            for dev in self._devs.values():
                self._grab(dev)
                grabbed.append(dev)
        except OSError:
            for d in grabbed:
                try: d.ungrab()
                except Exception: pass
            raise

    @staticmethod
    def _grab(dev: "evdev.InputDevice") -> None:
        for attempt in range(5):
            try:
                dev.grab()
                return
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(0.25)

    def _teardown(self) -> None:
        for dev in self._devs.values():
            try:
                dev.ungrab()
            except Exception:
                pass
            try:
                dev.close()   # sets dev.fd = -1; must always run so __del__ is a no-op
            except Exception:
                pass
        try:
            if self._uinput:
                self._uinput.close()
        except Exception:
            pass

    # ── Event loop ────────────────────────────────────────────────────────────

    def _event_loop(self) -> None:
        fd_to_suffix = {dev.fd: suffix for suffix, dev in self._devs.items()}
        fds = list(fd_to_suffix)

        while not self._stop_event.is_set():
            r, _, _ = select.select(fds, [], [], 0.1)
            for fd in r:
                suffix = fd_to_suffix[fd]
                try:
                    for event in self._devs[suffix].read():
                        self._dispatch(event, suffix)
                except OSError:
                    return

    # ── Dispatch ──────────────────────────────────────────────────────────────

    def _dispatch(self, event: "evdev.InputEvent", device: str) -> None:
        q = get_queue()

        # ── EV_ABS bitmask buttons (e.g. event-if01: GS) ─────────────────────
        if event.type == ecodes.EV_ABS:
            prev    = self._abs_state.get(device, 0)
            changed = prev ^ event.value
            self._abs_state[device] = event.value
            if not changed:
                return

            with self._lock:
                routing = self._abs_routing
                cb      = self._raw_cb

            for (dev, mask), defn in ABS_BTNS.items():
                if dev != device or not (changed & mask):
                    continue
                pressed = bool(event.value & mask)
                print(f"[DBG2-G600-ABS] {defn.button_id} pressed={pressed}  cb={'set' if cb else 'NONE'}", flush=True)
                if cb:
                    try:
                        cb(defn.button_id, pressed)
                    except Exception as e:
                        print(f"[DBG2-G600-ABS] cb RAISED: {e!r}", flush=True)
                macro = routing.get((device, mask))
                if macro is not None:
                    q.submit_macro(defn.button_id, pressed, macro, self._uinput)
                # ABS buttons have no OS passthrough — swallow if unrouted
            return

        # ── EV_KEY buttons (event-mouse, if01-event-kbd) ─────────────────────
        if event.type != ecodes.EV_KEY:
            self._uinput.write(event.type, event.code, event.value)  # REL/SYN passthrough
            return

        defn = KEY_BTNS.get((device, event.code))
        with self._lock:
            macro = self._key_routing.get((device, event.code))
            cb    = self._raw_cb
            debug = self._debug_mode

        # Only trace press/release (value 0/1), not key-repeat (value 2)
        if event.value in (0, 1):
            label = defn.button_id if defn else f"?{device}:{event.code}"
            print(f"[DBG2-G600-KEY] {label} val={event.value}  cb={'set' if cb else 'NONE'}", flush=True)

        if cb:
            if defn and event.value in (defn.press_value, defn.release_value):
                # Known button — report with its label
                pressed = (event.value == defn.press_value)
                try:
                    cb(defn.button_id, pressed)
                except Exception as e:
                    print(f"[DBG2-G600-KEY] cb RAISED: {e!r}", flush=True)
            elif not defn and event.value in (0, 1):
                # Unknown button — report with raw info so debug window can surface it
                pressed = bool(event.value)
                try:
                    cb(f"?{device}:EV_KEY:{event.code}", pressed)
                except Exception as e:
                    print(f"[DBG2-G600-KEY] cb RAISED (unknown): {e!r}", flush=True)

        if macro is None:
            # In debug mode, suppress non-locked buttons so they don't fire
            # stray key codes into the OS.  Locked buttons (LMB, RMB) always
            # pass through so the mouse remains functional while debugging.
            if not debug or (defn is not None and defn.locked):
                self._uinput.write(event.type, event.code, event.value)
            return

        # Macro-routed: intercept press and release, ignore repeat (value==2)
        press_val   = defn.press_value   if defn else 1
        release_val = defn.release_value if defn else 0

        if event.value == press_val:
            q.submit_macro(defn.button_id if defn else "", True,  macro, self._uinput)
        elif event.value == release_val:
            q.submit_macro(defn.button_id if defn else "", False, macro, self._uinput)
