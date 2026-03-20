"""
plugins/g13/raw_capture.py — Pure USB HID capture for the Logitech G13.

Reads 8-byte interrupt reports directly from USB endpoint 0x81.
Button definitions are loaded entirely from buttons.csv — no hardcoded
button data in this file.

Report format (8 bytes):
    byte 0 : report ID (always 0x01)
    byte 1 : joystick X  (0=left … 255=right, centre ≈ 127)
    byte 2 : joystick Y  (0=up   … 255=down,  centre ≈ 127)
    bytes 3–7 : 40-bit button bitmask

Public API matches G600's raw_capture.py:
    start()                      begin capture thread
    stop()                       request stop
    update_routing_map(routing)  {button_id: NamedMacro}
    set_raw_callback(fn)         fn(button_id, pressed) on every event

UInput is decoupled from capture: the thread starts and fires button
callbacks regardless of whether /dev/uinput is available.  UInput is
attempted at startup and retried every _UINPUT_RETRY_S seconds; macros
are silently skipped until it succeeds.

Dependencies: pyusb  (pip install pyusb / sudo apt install python3-usb)
              evdev  (pip install evdev  / sudo apt install python3-evdev)
"""

from __future__ import annotations

import threading
import time

try:
    import usb.core
    import usb.util
    _USB_OK = True
except ImportError:
    _USB_OK = False

try:
    import evdev
    from evdev import ecodes, UInput
    _EVDEV_OK = True
except ImportError:
    _EVDEV_OK = False

from core.macro_queue import get_queue

from plugins.g13.button_map import BUTTONS, BY_ID, BIT_BTNS, STICK_BTNS

# ── Constants ─────────────────────────────────────────────────────────────────

G13_VENDOR  = 0x046d
G13_PRODUCT = 0xc21c
G13_IFACE   = 0
G13_EP_IN   = 0x81
REPORT_SIZE = 8
MAX_PACKET  = 64   # G13 batches multiple 8-byte reports per USB read

STICK_LOW  = 50    # axis value below this  → UP or LEFT
STICK_HIGH = 205   # axis value above this  → DOWN or RIGHT

_UINPUT_RETRY_S = 5.0  # retry /dev/uinput every N seconds if unavailable at startup


class G13RawCapture(threading.Thread):
    """
    Daemon thread that owns the G13 USB device and executes macros.

    Button definitions come entirely from buttons.csv via button_map.
    No button names, bit indices, or axis thresholds are hardcoded here.

    UInput is non-fatal: the thread starts and fires raw callbacks
    (e.g. the debug window) immediately, regardless of /dev/uinput
    availability.  Macro execution resumes automatically once UInput
    becomes available.

    Profile switch: call update_routing_map() from any thread — instant,
                    no restart needed.

    routing map: {button_id: NamedMacro}
    """

    def __init__(self) -> None:
        if not _USB_OK:
            raise RuntimeError(
                "pyusb is not installed.\n"
                "Install with: pip install pyusb\n"
                "           or: sudo apt install python3-usb"
            )
        if not _EVDEV_OK:
            raise RuntimeError(
                "python3-evdev is not installed.\n"
                "Install with: pip install evdev\n"
                "           or: sudo apt install python3-evdev"
            )
        super().__init__(daemon=True, name="G13RawCapture")

        # Routing: button_id → NamedMacro
        self._routing: dict[str, object] = {}
        self._lock       = threading.Lock()
        self._stop_event = threading.Event()
        self._raw_cb     = None

        self._dev    = None   # usb.core.Device
        self._uinput = None   # evdev.UInput  (None until /dev/uinput is ready)

        # Previous state
        self._prev_bits  = 0
        self._prev_stick = {("y", "low"): False, ("y", "high"): False,
                            ("x", "low"): False, ("x", "high"): False}

        self.error: str | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def update_routing_map(self, routing: dict[str, object]) -> None:
        """Thread-safe routing map update.  Call on every profile switch.

        routing: {button_id: NamedMacro}
        """
        q = get_queue()
        q.cancel_all()
        q.reset_toggle(list(routing.keys()))

        with self._lock:
            self._routing = dict(routing)

    def set_raw_callback(self, fn) -> None:
        """Register fn(button_id: str, pressed: bool) — fires on every button event."""
        with self._lock:
            self._raw_cb = fn

    def set_debug_mode(self, enabled: bool) -> None:
        """No-op on G13 — unrouted buttons are already swallowed, nothing to suppress."""
        pass

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
        self._dev = usb.core.find(idVendor=G13_VENDOR, idProduct=G13_PRODUCT)
        if self._dev is None:
            raise RuntimeError("G13 not found — is it plugged in?")

        if self._dev.is_kernel_driver_active(G13_IFACE):
            self._dev.detach_kernel_driver(G13_IFACE)

        self._dev.set_configuration()
        usb.util.claim_interface(self._dev, G13_IFACE)

        # UInput is non-fatal — capture starts immediately regardless.
        # ensure_capture() tries up to 10 times so a recently-loaded uinput
        # module is picked up without a full restart.
        self.ensure_capture()

    def ensure_capture(self) -> None:
        """Try to create the UInput device up to 10 times, sleeping 1 s between
        attempts.  Logs success or final failure to stdout.

        Non-fatal: raw button callbacks and the debug window work regardless.
        Macros begin firing as soon as UInput becomes ready.
        """
        for attempt in range(1, 11):
            self._try_create_uinput()
            if self._uinput is not None:
                print(f"[G13] UInput ready (attempt {attempt}/10)", flush=True)
                return
            print(f"[G13] UInput not ready (attempt {attempt}/10) — "
                  "retrying in 1 s...", flush=True)
            if attempt < 10:
                import time as _t; _t.sleep(1.0)
        print("[G13] UInput unavailable after 10 attempts — "
              "macros disabled.  Run: sudo modprobe uinput", flush=True)

    def _try_create_uinput(self) -> None:
        """Single attempt to open /dev/uinput and create the virtual keyboard device.

        Silently leaves self._uinput = None on failure (e.g. uinput module
        not loaded yet).  Called by ensure_capture() and retried every
        _UINPUT_RETRY_S seconds from the event loop.
        """
        try:
            key_codes: set[int] = set()
            for code in range(ecodes.KEY_ESC, ecodes.KEY_MICMUTE + 1):
                key_codes.add(code)
            for btn in (ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE,
                        ecodes.BTN_SIDE, ecodes.BTN_EXTRA):
                key_codes.add(btn)
            self._uinput = UInput(
                {ecodes.EV_KEY: sorted(key_codes)},
                name="g13-keymacro",
                vendor=G13_VENDOR,
                product=G13_PRODUCT,
            )
        except Exception:
            self._uinput = None

    def _teardown(self) -> None:
        try:
            if self._dev:
                usb.util.release_interface(self._dev, G13_IFACE)
                usb.util.dispose_resources(self._dev)
        except Exception:
            pass
        try:
            if self._uinput:
                self._uinput.close()
        except Exception:
            pass

    # ── Event loop ────────────────────────────────────────────────────────────

    def _event_loop(self) -> None:
        _last_uinput_try = 0.0

        while not self._stop_event.is_set():
            # Retry uinput if it wasn't available at startup
            if self._uinput is None:
                now = time.monotonic()
                if now - _last_uinput_try >= _UINPUT_RETRY_S:
                    _last_uinput_try = now
                    self._try_create_uinput()

            try:
                data = self._dev.read(G13_EP_IN, MAX_PACKET, timeout=100)
            except usb.core.USBTimeoutError:
                continue
            except Exception as e:
                self.error = str(e)
                break

            buf = bytes(data)
            if len(buf) < REPORT_SIZE or len(buf) % REPORT_SIZE != 0:
                continue

            for i in range(0, len(buf), REPORT_SIZE):
                self._process_report(buf[i:i + REPORT_SIZE])

    # ── Report decoding ───────────────────────────────────────────────────────

    def _process_report(self, data: bytes) -> None:
        # ── Bitmask buttons (bytes 3–7) ───────────────────────────────────────
        curr_bits = (
            data[3]
            | (data[4] << 8)
            | (data[5] << 16)
            | (data[6] << 24)
            | (data[7] << 32)
        )
        changed = curr_bits ^ self._prev_bits

        if changed:
            for bit_idx, defn in BIT_BTNS.items():
                mask = 1 << bit_idx
                if not (changed & mask):
                    continue
                pressed = bool(curr_bits & mask)
                self._on_button(defn.button_id, pressed)

        self._prev_bits = curr_bits

        # ── Joystick stick directions (bytes 1–2) ─────────────────────────────
        x, y = data[1], data[2]
        stick_now = {
            ("y", "low"):  y < STICK_LOW,
            ("y", "high"): y > STICK_HIGH,
            ("x", "low"):  x < STICK_LOW,
            ("x", "high"): x > STICK_HIGH,
        }
        for key, pressed in stick_now.items():
            if pressed != self._prev_stick[key]:
                defn = STICK_BTNS.get(key)
                if defn:
                    self._on_button(defn.button_id, pressed)
        self._prev_stick = stick_now

    # ── Button dispatch ───────────────────────────────────────────────────────

    def _on_button(self, button_id: str, pressed: bool) -> None:
        with self._lock:
            cb    = self._raw_cb
            macro = self._routing.get(button_id)

        if cb:
            try:
                cb(button_id, pressed)
            except Exception as e:
                print(f"[G13] raw callback raised: {e!r}", flush=True)

        # Only submit macros when uinput is ready; silently skip otherwise
        if macro is not None and self._uinput is not None:
            get_queue().submit_macro(button_id, pressed, macro, self._uinput)
