"""
tests/test_g13_capture.py — Interactive hardware test for G13HidCapture.

Each button is tested for three actions, in sequence:
  1. PRESS  — hold the button down
  2. RELEASE — release the button
  3. TAP    — quick press-and-release

Run with:
    pytest -v -s tests/test_g13_capture.py

Requirements:
  - G13 plugged in with USB access (udev rule or run as root)
  - pyusb + python3-evdev installed
  - No other process grabbing the G13 (g13d must not be running)

The test prompts you on stdout for each action and waits up to TIMEOUT_S seconds.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Generator

import pytest

# ── Path setup ───────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Timeout ───────────────────────────────────────────────────────────────────
TIMEOUT_S = 20   # seconds to wait for each hardware event


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def capture():
    """Start G13HidCapture once for the whole test session."""
    try:
        from plugins.g13.hid_capture import G13HidCapture
    except ImportError as e:
        pytest.skip(f"hid_capture import failed: {e}")

    try:
        cap = G13HidCapture()
    except RuntimeError as e:
        pytest.skip(str(e))

    cap.start()
    time.sleep(0.5)   # give the thread a moment to claim the device

    if cap.error:
        cap.stop()
        pytest.skip(f"G13HidCapture failed to start: {cap.error}")

    yield cap

    cap.stop()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wait_for_event(
    capture,
    expected_label: str,
    expected_pressed: bool,
    timeout: float = TIMEOUT_S,
) -> tuple[bool, list[tuple[str, bool]]]:
    """
    Block until the capture thread fires (expected_label, expected_pressed).
    Returns (success, all_events_received).
    """
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


def _prompt_and_wait(
    capture,
    label: str,
    action: str,
    expected_pressed: bool,
) -> None:
    """Print a user prompt, wait for the event, assert it arrived."""
    verb = {
        "press":   f"HOLD DOWN  [ {label} ]",
        "release": f"RELEASE    [ {label} ]",
        "tap":     f"TAP        [ {label} ]  (quick press-and-release)",
    }[action]

    print(f"\n  >>> {verb}  (you have {TIMEOUT_S}s) <<<", flush=True)

    ok, got = _wait_for_event(capture, label, expected_pressed)

    if not ok:
        unique = list(dict.fromkeys(got))   # deduplicate preserving order
        if unique:
            print(f"\n  RECEIVED: {unique}", flush=True)
            print(f"  EXPECTED: ({label!r}, {expected_pressed})", flush=True)
        else:
            print(f"\n  RECEIVED: nothing", flush=True)
        pytest.fail(
            f"Timed out waiting for {label!r} {'press' if expected_pressed else 'release'} "
            f"(action={action}). Got: {unique}"
        )


# ── Button list (mirrors _G13_BUTTON_SPECS order) ─────────────────────────────

_ALL_BUTTONS: list[str] = (
    [f"G{i}"  for i in range(1, 23)]   # G1–G22
    + [f"L{i}" for i in range(1, 5)]   # L1–L4
    + [f"M{i}" for i in range(1, 4)]   # M1–M3
    + ["MR"]
    + ["STICK_UP", "STICK_DOWN", "STICK_LEFT", "STICK_RIGHT"]
    + ["LEFT", "BD", "TOP", "DOWN"]
)


# ── Parametrised test ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("label", _ALL_BUTTONS)
def test_button(capture, label: str) -> None:
    """
    Interactive test for one G13 button:
      1. PRESS   — wait for pressed=True
      2. RELEASE — wait for pressed=False
      3. TAP     — wait for pressed=True then pressed=False
    """
    print(f"\n{'─' * 60}")
    print(f"  BUTTON: {label}")
    print(f"{'─' * 60}")

    # 1. Press
    _prompt_and_wait(capture, label, "press",   expected_pressed=True)

    # 2. Release
    _prompt_and_wait(capture, label, "release", expected_pressed=False)

    # 3. Tap (press)
    _prompt_and_wait(capture, label, "tap",     expected_pressed=True)
    # 3. Tap (release) — automatic, just need to see it come through
    print(f"  (waiting for release of tap…)", flush=True)
    ok, got = _wait_for_event(capture, label, False, timeout=5)
    if not ok:
        pytest.fail(f"Tap-release not received for {label} within 5s. Got: {got}")

    print(f"  ✓ {label} OK")
