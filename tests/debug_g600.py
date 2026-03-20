#!/usr/bin/env python3
"""
debug_g600.py — Dump every G600 button event to stdout.

Uses the same G600RawCapture thread as the keymacro plugin — one capture
component, shared between debug and runtime.

Run from the repo root (keymacro must NOT be running — it holds an exclusive
grab on the evdev devices):

    python tests/debug_g600.py

Press Ctrl-C to quit.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from plugins.g600.raw_capture import G600RawCapture
except ImportError as e:
    sys.exit(f"Import error: {e}")


def main() -> None:
    print("Starting G600RawCapture (keymacro must not be running)...")

    try:
        capture = G600RawCapture()
    except RuntimeError as e:
        sys.exit(str(e))

    print(f"\n{'DIR':4}  {'BUTTON':20}")
    print("-" * 30)

    def on_event(button_id: str, pressed: bool) -> None:
        arrow = "▼" if pressed else "▲"
        print(f"{arrow:4}  {button_id}", flush=True)

    capture.set_raw_callback(on_event)
    capture.start()

    print("Listening — press buttons on the G600.  Ctrl-C to quit.\n")

    try:
        while capture.is_alive():
            time.sleep(0.1)
        if capture.error:
            print(f"\nCapture thread error: {capture.error}")
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        capture.stop()
        capture.join(timeout=2.0)
        print("Done.")


if __name__ == "__main__":
    main()
