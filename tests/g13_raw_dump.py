"""
tests/g13_raw_dump.py — Raw HID byte dump for G13 button mapping discovery.

Press any button on the G13 and see exactly which bits change.
Use this to verify or correct KEY_BITS in hid_capture.py.

Run with:
    .venv/bin/python tests/g13_raw_dump.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import usb.core
    import usb.util
except ImportError:
    sys.exit("pyusb not installed — run: pip install pyusb")

G13_VENDOR  = 0x046d
G13_PRODUCT = 0xc21c
G13_IFACE   = 0
G13_EP_IN   = 0x81
REPORT_SIZE = 8

dev = usb.core.find(idVendor=G13_VENDOR, idProduct=G13_PRODUCT)
if dev is None:
    sys.exit("G13 not found — is it plugged in?")

if dev.is_kernel_driver_active(G13_IFACE):
    dev.detach_kernel_driver(G13_IFACE)

dev.set_configuration()
usb.util.claim_interface(dev, G13_IFACE)

print("G13 raw HID dump — press buttons to see which bits change.")
print("Ctrl+C to quit.\n")
print(f"{'bytes 3-7 (binary)':50s}  changed bits")
print("-" * 70)

prev = 0

try:
    while True:
        try:
            data = bytes(dev.read(G13_EP_IN, REPORT_SIZE, timeout=100))
        except usb.core.USBTimeoutError:
            continue

        # Print ALL packets — show raw hex and, for 8-byte reports, the bitmask diff
        raw_hex = " ".join(f"{b:02x}" for b in data)

        if len(data) == REPORT_SIZE:
            curr = (
                data[3]
                | (data[4] << 8)
                | (data[5] << 16)
                | (data[6] << 24)
                | (data[7] << 32)
            )
            if curr == prev:
                continue
            changed = curr ^ prev
            prev = curr

            bits_str = " ".join(f"{data[i]:08b}" for i in range(3, 8))
            changed_indices = [i for i in range(40) if changed & (1 << i)]
            pressed_indices  = [i for i in changed_indices if curr & (1 << i)]
            released_indices = [i for i in changed_indices if not (curr & (1 << i))]
            parts = []
            if pressed_indices:
                parts.append(f"DOWN bits: {pressed_indices}")
            if released_indices:
                parts.append(f"UP   bits: {released_indices}")
            print(f"[8B] {bits_str}  {', '.join(parts)}")
        else:
            # Short/unexpected packet — show everything
            print(f"[{len(data)}B] raw: {raw_hex}")

except KeyboardInterrupt:
    print("\nDone.")
finally:
    usb.util.release_interface(dev, G13_IFACE)
    usb.util.dispose_resources(dev)
