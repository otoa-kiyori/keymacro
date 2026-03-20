"""
plugins/g13/button_map.py — Load G13 button definitions from buttons.csv.

The G13 communicates via a single USB HID interrupt endpoint (0x81) that
delivers 8-byte reports.  Bytes 3–7 form a 40-bit bitmask where each
defined bit corresponds to one physical button.  Joystick directions are
derived from the analog X (byte 1) and Y (byte 2) values.

Public API
----------
BUTTONS      list[ButtonDef]           all buttons in CSV row order
BY_ID        dict[str, ButtonDef]
BIT_BTNS     dict[int, ButtonDef]      bit_index → ButtonDef  (bitmask buttons)
STICK_BTNS   dict[tuple[str,str], ButtonDef]
             (axis, dir) → ButtonDef   e.g. ('y', 'low') → STICK_UP
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

_CSV_PATH = Path(__file__).parent / "buttons.csv"


@dataclass(frozen=True)
class ButtonDef:
    button_id:  str    # profile / routing key  e.g. "G1", "STICK_UP"
    bit_index:  int    # 0–39 for bitmask buttons; -1 for virtual stick buttons
    stick_axis: str    # 'x' | 'y' | ''  (non-empty only for stick buttons)
    stick_dir:  str    # 'low' | 'high' | ''  (non-empty only for stick buttons)
    locked:     bool   # True → never reassignable
    zone:       str    # UI grouping: 'key' | 'lcd' | 'mode' | 'dpad' | 'stick'


def _load(path: Path) -> list[ButtonDef]:
    with open(path, newline="") as f:
        data_lines = [ln for ln in f if not ln.lstrip().startswith("#")]
    buttons: list[ButtonDef] = []
    for row in csv.DictReader(data_lines):
        if not row.get("button_id", "").strip():
            continue
        buttons.append(ButtonDef(
            button_id  = row["button_id"].strip(),
            bit_index  = int(row["bit_index"]),
            stick_axis = row["stick_axis"].strip(),
            stick_dir  = row["stick_dir"].strip(),
            locked     = row["locked"].strip().lower() == "true",
            zone       = row["zone"].strip(),
        ))
    return buttons


BUTTONS: list[ButtonDef] = _load(_CSV_PATH)
BY_ID:   dict[str, ButtonDef] = {b.button_id: b for b in BUTTONS}

# bit_index → ButtonDef  for bitmask buttons
BIT_BTNS: dict[int, ButtonDef] = {
    b.bit_index: b for b in BUTTONS if b.bit_index >= 0
}

# (axis, direction) → ButtonDef  for virtual joystick buttons
STICK_BTNS: dict[tuple[str, str], ButtonDef] = {
    (b.stick_axis, b.stick_dir): b for b in BUTTONS if b.bit_index == -1
}
