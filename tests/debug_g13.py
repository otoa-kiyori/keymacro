#!/usr/bin/env python3
"""
debug_g13.py — Dump every G13 button event to stdout.

Run from the repo root (keymacro must NOT be running — it holds the USB device):

    python debug_g13.py

Uses exactly the same USB read loop and bitmask decode as
plugins/g13/raw_capture.py.  Press Ctrl-C to quit.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import usb.core
    import usb.util
except ImportError:
    sys.exit("pyusb not installed — run: pip install pyusb")

# Button map is the authoritative source — same as the plugin uses
from plugins.g13.button_map import BIT_BTNS, STICK_BTNS

G13_VENDOR  = 0x046d
G13_PRODUCT = 0xc21c
G13_IFACE   = 0
G13_EP_IN   = 0x81
REPORT_SIZE = 8
MAX_PACKET  = 64     # read up to 64 bytes — catches non-standard reports

STICK_LOW  = 50
STICK_HIGH = 205


def main() -> None:
    print("Looking for G13 (keymacro must not be running)...")

    dev = usb.core.find(idVendor=G13_VENDOR, idProduct=G13_PRODUCT)
    if dev is None:
        sys.exit("G13 not found — is it plugged in?")

    print(f"  Found: {dev.manufacturer} {dev.product}  "
          f"(bus {dev.bus}, addr {dev.address})")

    if dev.is_kernel_driver_active(G13_IFACE):
        dev.detach_kernel_driver(G13_IFACE)

    dev.set_configuration()
    usb.util.claim_interface(dev, G13_IFACE)

    prev_bits  = 0
    prev_stick = {("y", "low"): False, ("y", "high"): False,
                  ("x", "low"): False, ("x", "high"): False}

    print("\nListening — press buttons on the G13.  Ctrl-C to quit.\n")
    print(f"{'DIR':4}  {'BUTTON':20}  RAW")
    print("-" * 50)

    try:
        while True:
            try:
                data = dev.read(G13_EP_IN, MAX_PACKET, timeout=100)
            except usb.core.USBTimeoutError:
                continue

            raw_buf = bytes(data)

            # G13 batches multiple 8-byte reports per USB read — split and process each
            if len(raw_buf) % REPORT_SIZE != 0:
                hex_str = " ".join(f"{b:02x}" for b in raw_buf)
                print(f"???   {'?report':20}  len={len(raw_buf)}  raw=[{hex_str}]  ← ODD LENGTH")
                continue

            reports = [raw_buf[i:i+REPORT_SIZE] for i in range(0, len(raw_buf), REPORT_SIZE)]

            # always-on hardware bits — never represent a button press
            ALWAYS_ON = (1 << 23) | (1 << 39)

            for raw_bytes in reports:
                # ── Bitmask buttons (bytes 3–7) ───────────────────────────────
                curr_bits = (
                    raw_bytes[3]
                    | (raw_bytes[4] << 8)
                    | (raw_bytes[5] << 16)
                    | (raw_bytes[6] << 24)
                    | (raw_bytes[7] << 32)
                )
                changed = curr_bits ^ prev_bits

                if changed:
                    for bit_idx in range(40):
                        mask = 1 << bit_idx
                        if not (changed & mask) or (mask & ALWAYS_ON):
                            continue
                        pressed = bool(curr_bits & mask)
                        arrow   = "▼" if pressed else "▲"
                        raw     = f"id={raw_bytes[0]:02x}  byte3-7=0x{curr_bits:010x}  bit={bit_idx}  mask=0x{mask:010x}"
                        defn    = BIT_BTNS.get(bit_idx)
                        if defn:
                            print(f"{arrow:4}  {defn.button_id:20}  {raw}")
                        else:
                            print(f"{arrow:4}  {'?bit'+str(bit_idx):20}  {raw}  ← UNKNOWN")

                prev_bits = curr_bits

                # ── Joystick (bytes 1–2) ──────────────────────────────────────
                x, y = raw_bytes[1], raw_bytes[2]
                stick_now = {
                    ("y", "low"):  y < STICK_LOW,
                    ("y", "high"): y > STICK_HIGH,
                    ("x", "low"):  x < STICK_LOW,
                    ("x", "high"): x > STICK_HIGH,
                }
                for key, pressed in stick_now.items():
                    if pressed != prev_stick[key]:
                        defn = STICK_BTNS.get(key)
                        if defn:
                            arrow = "▼" if pressed else "▲"
                            axis, _dir = key
                            raw   = f"axis={axis}  val={y if axis=='y' else x}"
                            print(f"{arrow:4}  {defn.button_id:20}  {raw}")
                prev_stick = stick_now

    except KeyboardInterrupt:
        print("\nDone.")
    finally:
        try:
            usb.util.release_interface(dev, G13_IFACE)
            usb.util.dispose_resources(dev)
        except Exception:
            pass


if __name__ == "__main__":
    main()
