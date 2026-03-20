#!/usr/bin/env python3
"""
debug_g600.py — Dump every G600 button event to stdout.

Run from the repo root (keymacro must NOT be running — it holds an exclusive grab):

    python debug_g600.py

Uses exactly the same device discovery and button identification as
plugins/g600/raw_capture.py.  Press Ctrl-C to quit.
"""

import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import select
import sys

try:
    import evdev
    from evdev import ecodes
except ImportError:
    sys.exit("evdev not installed — run: pip install evdev")

# Button map is the authoritative source — same as the plugin uses
from plugins.g600.button_map import DEVICE_NAMES, KEY_BTNS, ABS_BTNS

_BY_ID_PREFIX = "/dev/input/by-id/usb-Logitech_Gaming_Mouse_G600_*-"


def find_device(suffix: str) -> str:
    matches = glob.glob(_BY_ID_PREFIX + suffix)
    if not matches:
        sys.exit(f"G600 interface not found: *-{suffix}\nIs the G600 plugged in?")
    return matches[0]


def main() -> None:
    print("Opening G600 interfaces (keymacro must not be running)...")

    devs: dict[str, evdev.InputDevice] = {}
    for suffix in DEVICE_NAMES:
        path = find_device(suffix)
        devs[suffix] = evdev.InputDevice(path)
        print(f"  {suffix:30s}  {path}")

    # Track EV_ABS bitmask state per device
    abs_state: dict[str, int] = {}

    print("\nListening — press buttons on the G600.  Ctrl-C to quit.\n")
    print(f"{'DIR':4}  {'BUTTON':20}  RAW")
    print("-" * 50)

    fd_to_suffix = {dev.fd: suffix for suffix, dev in devs.items()}
    fds = list(fd_to_suffix)

    try:
        while True:
            r, _, _ = select.select(fds, [], [], 0.5)
            for fd in r:
                suffix = fd_to_suffix[fd]
                for event in devs[suffix].read():

                    # ── EV_ABS bitmask buttons ────────────────────────────────
                    if event.type == ecodes.EV_ABS:
                        prev    = abs_state.get(suffix, 0)
                        changed = prev ^ event.value
                        abs_state[suffix] = event.value
                        for (dev, mask), defn in ABS_BTNS.items():
                            if dev != suffix or not (changed & mask):
                                continue
                            pressed = bool(event.value & mask)
                            arrow   = "▼" if pressed else "▲"
                            raw     = f"EV_ABS  dev={suffix}  mask=0x{mask:02x}  val={event.value}"
                            print(f"{arrow:4}  {defn.button_id:20}  {raw}")
                        continue

                    # ── EV_KEY buttons ────────────────────────────────────────
                    if event.type == ecodes.EV_KEY:
                        defn    = KEY_BTNS.get((suffix, event.code))
                        btn_id  = defn.button_id if defn else f"?(code={event.code})"
                        raw     = f"EV_KEY  dev={suffix}  code={event.code}  val={event.value}"

                        if defn and event.value in (defn.press_value, defn.release_value):
                            pressed = (event.value == defn.press_value)
                            arrow   = "▼" if pressed else "▲"
                            print(f"{arrow:4}  {btn_id:20}  {raw}")
                        elif not defn and event.value in (0, 1):
                            arrow = "▼" if event.value else "▲"
                            print(f"{arrow:4}  {btn_id:20}  {raw}")
                        # value==2 is key-repeat — skip

    except KeyboardInterrupt:
        print("\nDone.")
    finally:
        for dev in devs.values():
            try:
                dev.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
