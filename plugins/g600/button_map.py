"""
plugins/g600/button_map.py — Load G600 button definitions from buttons.csv.

The CSV `device` column uses the exact by-id suffix that Linux assigns to each
G600 interface (e.g. "event-mouse", "if01-event-kbd", "event-if01").  These
suffixes are determined by the HID descriptor and are hardware-stable across
reboots and reconnects; only the serial-number portion of the full by-id path
varies between individual units (handled by a glob in raw_capture.py).

Public API
----------
BUTTONS          list[ButtonDef]   all buttons in CSV row order
BY_ID            dict[str, ButtonDef]
DEVICE_NAMES     set[str]          unique device suffixes used in the CSV
KEY_BTNS         dict[(device, ev_code), ButtonDef]   EV_KEY buttons
ABS_BTNS         dict[(device, press_value), ButtonDef]  EV_ABS bitmask buttons
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

_CSV_PATH = Path(__file__).parent / "buttons.csv"


@dataclass(frozen=True)
class ButtonDef:
    button_id:     str    # profile / routing key and display name  e.g. "G9", "GS"
    device:        str    # by-id suffix: "event-mouse" | "if01-event-kbd" | "event-if01"
    ev_type:       int    # 1 = EV_KEY,  3 = EV_ABS
    ev_code:       int    # key code (EV_KEY) or ABS axis code (EV_ABS)
    press_value:   int    # EV_KEY: 1;  EV_ABS: bitmask (e.g. 32 for GS bit 5)
    release_value: int    # EV_KEY: 0;  EV_ABS: 0 (bit clears)
    locked:        bool   # True → never reassignable (LMB, RMB)
    zone:          str    # UI grouping: "main" | "thumb" | "control"


def _load(path: Path) -> list[ButtonDef]:
    with open(path, newline="") as f:
        data_lines = [ln for ln in f if not ln.lstrip().startswith("#")]
    buttons: list[ButtonDef] = []
    for row in csv.DictReader(data_lines):
        if not row.get("button_id", "").strip():
            continue
        buttons.append(ButtonDef(
            button_id     = row["button_id"].strip(),
            device        = row["device"].strip(),
            ev_type       = int(row["ev_type"]),
            ev_code       = int(row["ev_code"]),
            press_value   = int(row["press_value"]),
            release_value = int(row["release_value"]),
            locked        = row["locked"].strip().lower() == "true",
            zone          = row["zone"].strip(),
        ))
    return buttons


BUTTONS: list[ButtonDef] = _load(_CSV_PATH)
BY_ID:   dict[str, ButtonDef] = {b.button_id: b for b in BUTTONS}

# All unique device suffix names referenced by the CSV
DEVICE_NAMES: set[str] = {b.device for b in BUTTONS}

# (device_suffix, ev_code) → ButtonDef  for EV_KEY buttons
KEY_BTNS: dict[tuple[str, int], ButtonDef] = {
    (b.device, b.ev_code): b for b in BUTTONS if b.ev_type == 1
}

# (device_suffix, press_value/bitmask) → ButtonDef  for EV_ABS bitmask buttons
ABS_BTNS: dict[tuple[str, int], ButtonDef] = {
    (b.device, b.press_value): b for b in BUTTONS if b.ev_type == 3
}
