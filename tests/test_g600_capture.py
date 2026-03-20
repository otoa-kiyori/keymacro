"""
tests/test_g600_capture.py — Interactive hardware test for G600RawCapture.

Each button is tested for three actions, in sequence:
  1. PRESS  — hold the button down
  2. RELEASE — release the button
  3. TAP    — quick press-and-release

Run with:
    .venv/bin/pytest -v -s tests/test_g600_capture.py

LMB and RMB are excluded — they are locked (always passthrough, never routed).

On Ctrl+C or test completion the fixture stops the capture thread, which
releases the exclusive evdev grab so KWin / the compositor regains the device.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

TIMEOUT_S = 20


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def capture():
    try:
        from plugins.g600.raw_capture import G600RawCapture
    except ImportError as e:
        pytest.skip(f"raw_capture import failed: {e}")

    cap = None
    try:
        try:
            cap = G600RawCapture()
        except RuntimeError as e:
            pytest.skip(str(e))

        cap.start()
        time.sleep(1.0)   # allow grab to settle

        if cap.error:
            pytest.skip(f"G600RawCapture failed to start: {cap.error}")

        # Empty routing — no macros fire during testing, only raw callback
        cap.update_routing_map({})

        yield cap

    except KeyboardInterrupt:
        print("\n\n  [interrupted — releasing G600 grab]", flush=True)

    finally:
        # Always release the device so KWin regains control
        if cap is not None:
            cap.stop()
            cap.join(timeout=3.0)
            print("  [G600 released back to system]", flush=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wait_for_event(
    capture,
    expected_label: str,
    expected_pressed: bool,
    timeout: float = TIMEOUT_S,
) -> tuple[bool, list[tuple[str, bool]]]:
    got: list[tuple[str, bool]] = []
    ev = threading.Event()

    def _cb(label: str, pressed: bool) -> None:
        got.append((label, pressed))
        if label == expected_label and pressed == expected_pressed:
            ev.set()

    capture.set_raw_callback(_cb)
    fired = ev.wait(timeout)
    capture.set_raw_callback(None)
    return fired, got


def _prompt_and_wait(capture, label: str, action: str, expected_pressed: bool) -> None:
    verb = {
        "press":   f"HOLD DOWN  [ {label} ]",
        "release": f"RELEASE    [ {label} ]",
        "tap":     f"TAP        [ {label} ]  (quick press-and-release)",
    }[action]

    print(f"\n  >>> {verb}  (you have {TIMEOUT_S}s) <<<", flush=True)

    ok, got = _wait_for_event(capture, label, expected_pressed)

    if not ok:
        unique = list(dict.fromkeys(got))
        if unique:
            print(f"\n  RECEIVED: {unique}", flush=True)
            print(f"  EXPECTED: ({label!r}, {expected_pressed})", flush=True)
        else:
            print(f"\n  RECEIVED: nothing", flush=True)
        pytest.fail(
            f"Timed out waiting for {label!r} "
            f"({'press' if expected_pressed else 'release'}). Got: {unique}"
        )


# ── Button list (locked LMB/RMB excluded) ─────────────────────────────────────

_BUTTONS = [
    "Mid", "Back", "Fwd", "GS",
    "G7", "G8",
    "G9", "G10", "G11", "G12", "G13", "G14",
    "G15", "G16", "G17", "G18", "G19", "G20",
]


# ── Parametrised test ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("label", _BUTTONS)
def test_button(capture, label: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  BUTTON: {label}")
    print(f"{'─' * 60}")

    # 1. Press
    _prompt_and_wait(capture, label, "press",   expected_pressed=True)

    # 2. Release
    _prompt_and_wait(capture, label, "release", expected_pressed=False)

    # 3. Tap (press)
    _prompt_and_wait(capture, label, "tap",     expected_pressed=True)
    # 3. Tap (release)
    print(f"  (waiting for release of tap…)", flush=True)
    ok, got = _wait_for_event(capture, label, False, timeout=5)
    if not ok:
        pytest.fail(f"Tap-release not received for {label} within 5s. Got: {got}")

    print(f"  ✓ {label} OK")
