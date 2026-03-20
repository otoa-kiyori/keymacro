"""
plugins/g600/raw_capture.py — Pure evdev capture for the Logitech G600.

Opens every interface listed in buttons.csv.  The device names in the CSV
are the exact by-id suffix strings (e.g. "event-mouse", "if01-event-kbd",
"event-if01"); the serial-number portion is wildcarded so the code works
on any G600 unit.

Signal detection uses (device_suffix, ev_type, ev_code / bitmask) directly
from the CSV — no name translation layer.

UInput is decoupled from capture: the thread opens the evdev interfaces and
fires raw callbacks immediately, regardless of /dev/uinput availability.
The exclusive grab (and therefore passthrough) is only enabled once UInput
is successfully created — until then the OS still sees all mouse events.
UInput is retried via ensure_capture() at startup and every _UINPUT_RETRY_S
seconds from the event loop.

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

_UINPUT_RETRY_S = 5.0  # retry /dev/uinput every N seconds if unavailable at startup

# Only these interfaces produce G-key events that need exclusive interception.
# "event-mouse" is intentionally excluded: LMB/RMB/movement must reach the
# Wayland compositor directly via the physical device — grabbing it and
# relaying through a uinput virtual device does not work reliably on Wayland.
_GRAB_SUFFIXES: frozenset[str] = frozenset({"if01-event-kbd", "event-if01"})


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

    UInput is non-fatal: the thread opens evdev devices and fires raw
    callbacks immediately.  Exclusive grab and macro execution only begin
    once UInput is successfully created (ensure_capture() / event loop retry).

    Profile switch:  call update_routing_map() from any thread — instant,
                     no restart needed.

    routing map: {button_id: NamedMacro}
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
        self._uinput  = None   # evdev.UInput (None until /dev/uinput is ready)
        self._grabbed = False  # True once evdev devices are exclusively grabbed

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
        # Open every device named in the CSV — this is the only fatal step
        for suffix in DEVICE_NAMES:
            self._devs[suffix] = evdev.InputDevice(_find_device(suffix))

        # Single non-blocking attempt at startup; the event loop retries every
        # _UINPUT_RETRY_S seconds.  ensure_capture() (8 retries × 0.5 s) is
        # available for callers that want to block-wait (e.g. the debug script).
        self._try_create_uinput()
        if self._uinput is not None:
            print("[G600] UInput ready at startup", flush=True)
        else:
            print("[G600] UInput not ready at startup — will retry in event loop. "
                  "Run: sudo modprobe uinput", flush=True)

    def ensure_capture(self) -> None:
        """Block-wait for UInput: retry up to 8 times with 0.5 s sleep between
        attempts, then log success or final failure to stdout.

        Intended for standalone scripts (debug_g600.py) that want to wait for
        UInput to become ready.  The plugin itself uses the non-blocking
        event-loop retry instead.
        """
        for attempt in range(1, 9):
            self._try_create_uinput()
            if self._uinput is not None:
                print(f"[G600] UInput ready (attempt {attempt}/8)", flush=True)
                return
            print(f"[G600] UInput not ready (attempt {attempt}/8) — "
                  "retrying in 0.5 s...", flush=True)
            if attempt < 8:
                time.sleep(0.5)
        print("[G600] UInput unavailable after 8 attempts — "
              "macros disabled.  Run: sudo modprobe uinput", flush=True)

    def _try_create_uinput(self) -> None:
        """Single attempt to create the UInput virtual device and grab only the
        G-key interfaces (_GRAB_SUFFIXES).

        "event-mouse" is intentionally NOT grabbed — LMB/RMB/movement reach
        the Wayland compositor directly via the physical device.  The grab is
        only needed for G-key interfaces to prevent their raw key codes from
        leaking to other apps.

        If /dev/uinput is unavailable: leaves self._uinput = None and
        self._grabbed = False — devices remain open but un-grabbed.

        Called once at startup (_setup) and retried every _UINPUT_RETRY_S
        seconds from the event loop.
        """
        # Collect capabilities only from grabbed interfaces (no REL — mouse
        # movement is handled by the physical event-mouse, not relayed via uinput)
        key_codes: set[int] = set()
        for suffix, dev in self._devs.items():
            if suffix in _GRAB_SUFFIXES:
                caps = dev.capabilities(verbose=False)
                key_codes.update(caps.get(ecodes.EV_KEY, []))

        # Ensure common macro emission keys are available
        for code in (
            ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE,
            ecodes.BTN_SIDE, ecodes.BTN_EXTRA, ecodes.BTN_FORWARD, ecodes.BTN_BACK,
            ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL,
            ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT,
            ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT, ecodes.KEY_LEFTMETA,
        ):
            key_codes.add(code)

        try:
            uinput = UInput(
                {ecodes.EV_KEY: sorted(key_codes)},
                name="g600-keymacro",
                vendor=0x046d,
                product=0xc24a,
            )
        except Exception:
            return  # /dev/uinput not available yet — try again later

        # UInput succeeded; exclusively grab only the G-key interfaces
        grabbed: list["evdev.InputDevice"] = []
        try:
            for suffix, dev in self._devs.items():
                if suffix in _GRAB_SUFFIXES:
                    self._grab(dev)
                    grabbed.append(dev)
        except OSError:
            for d in grabbed:
                try:
                    d.ungrab()
                except Exception:
                    pass
            uinput.close()
            return  # grab failed — don't commit

        self._uinput  = uinput
        self._grabbed = True

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
        if self._grabbed:
            for dev in self._devs.values():
                try:
                    dev.ungrab()
                except Exception:
                    pass
        for dev in self._devs.values():
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
        _last_uinput_try = 0.0

        while not self._stop_event.is_set():
            # Retry uinput + grab if they weren't available at startup
            if self._uinput is None:
                now = time.monotonic()
                if now - _last_uinput_try >= _UINPUT_RETRY_S:
                    _last_uinput_try = now
                    self._try_create_uinput()
                    if self._uinput is not None:
                        print("[G600] UInput became available — "
                              "grab active, macros enabled", flush=True)

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
                if cb:
                    try:
                        cb(defn.button_id, pressed)
                    except Exception as e:
                        print(f"[G600] ABS callback raised: {e!r}", flush=True)
                macro = routing.get((device, mask))
                if macro is not None and self._uinput is not None:
                    q.submit_macro(defn.button_id, pressed, macro, self._uinput)
                # ABS buttons have no OS passthrough — swallow if unrouted
            return

        # ── EV_KEY / REL / SYN buttons (event-mouse, if01-event-kbd) ────────────
        if event.type != ecodes.EV_KEY:
            # REL/SYN passthrough — only relay for grabbed interfaces.
            # event-mouse is NOT grabbed, so its movement reaches the compositor
            # via the physical device already; relaying would double the events.
            if self._uinput is not None and device in _GRAB_SUFFIXES:
                self._uinput.write(event.type, event.code, event.value)
            return

        defn = KEY_BTNS.get((device, event.code))
        with self._lock:
            macro = self._key_routing.get((device, event.code))
            cb    = self._raw_cb
            debug = self._debug_mode

        if cb:
            if defn and event.value in (defn.press_value, defn.release_value):
                # Known button — report with its label
                pressed = (event.value == defn.press_value)
                try:
                    cb(defn.button_id, pressed)
                except Exception as e:
                    print(f"[G600] KEY callback raised: {e!r}", flush=True)
            elif not defn and event.value in (0, 1):
                # Unknown button — report with raw info so debug window can surface it
                pressed = bool(event.value)
                try:
                    cb(f"?{device}:EV_KEY:{event.code}", pressed)
                except Exception as e:
                    print(f"[G600] KEY callback raised (unknown): {e!r}", flush=True)

        if macro is None:
            # Only relay through uinput for grabbed interfaces.
            # event-mouse (LMB, RMB) is not grabbed — those events already
            # reach the compositor via the physical device.
            if device in _GRAB_SUFFIXES:
                if not debug or (defn is not None and defn.locked):
                    if self._uinput is not None:
                        self._uinput.write(event.type, event.code, event.value)
            return

        # Macro-routed: intercept press and release, ignore repeat (value==2)
        press_val   = defn.press_value   if defn else 1
        release_val = defn.release_value if defn else 0

        if event.value == press_val:
            if self._uinput is not None:
                q.submit_macro(defn.button_id if defn else "", True,  macro, self._uinput)
        elif event.value == release_val:
            if self._uinput is not None:
                q.submit_macro(defn.button_id if defn else "", False, macro, self._uinput)
