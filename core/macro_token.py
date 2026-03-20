"""
core/macro_token.py — Macro token format parser, validator, and serializer.

Token grammar — two equivalent styles are accepted:

  New (preferred):
    A               tap KEY_A       (press + release)
    +A              hold KEY_A down
    -A              release KEY_A
    +LeftCtrl       hold Left Ctrl
    +BTN_LEFT       hold left mouse button
    t50             wait 50 ms

  Legacy (still accepted for migration):
    KEY_A           tap
    +KEY_A          hold
    -KEY_A          release
    A+              hold  (old new-format, converted on load)
    A-              release (old new-format, converted on load)

The key names are Linux evdev key names with the KEY_ prefix stripped for
keyboard keys.  Mouse button names keep the BTN_ prefix to avoid collision
(e.g. BTN_LEFT vs KEY_LEFT arrow).

Use expand_token() to convert any token — old or new format — into a
(action, evdev_name) pair that translation backends can use directly.

No Qt dependency — pure Python.
"""

from __future__ import annotations

import functools
import re

# ── Keymacro virtual aliases ──────────────────────────────────────────────────
# User-facing names that differ from raw evdev names.
# Stored in profiles as-is; expand_token() resolves them at execution time.
_KM_ALIASES: dict[str, str] = {
    # Numpad
    "Num0":     "KEY_KP0",
    "Num1":     "KEY_KP1",
    "Num2":     "KEY_KP2",
    "Num3":     "KEY_KP3",
    "Num4":     "KEY_KP4",
    "Num5":     "KEY_KP5",
    "Num6":     "KEY_KP6",
    "Num7":     "KEY_KP7",
    "Num8":     "KEY_KP8",
    "Num9":     "KEY_KP9",
    # Numpad operators — new short names (user-visible, with special chars)
    "Num+":  "KEY_KPPLUS",
    "Num-":  "KEY_KPMINUS",
    "Num*":  "KEY_KPASTERISK",
    "Num/":  "KEY_KPSLASH",
    "Num.":  "KEY_KPDOT",
    # Legacy names kept so existing YAML files still migrate correctly
    "NumPlus":  "KEY_KPPLUS",
    "NumMinus": "KEY_KPMINUS",
    "NumMul":   "KEY_KPASTERISK",
    "NumDiv":   "KEY_KPSLASH",
    "NumDot":   "KEY_KPDOT",
    "NumEnter": "KEY_KPENTER",
    # Mouse buttons — friendly names
    "LeftButton":    "BTN_LEFT",
    "RightButton":   "BTN_RIGHT",
    "MiddleButton":  "BTN_MIDDLE",
    "BackButton":    "BTN_SIDE",
    "ForwardButton": "BTN_EXTRA",
    # Modifiers (compound words that .capitalize() can't split correctly)
    "LeftCtrl":   "KEY_LEFTCTRL",
    "RightCtrl":  "KEY_RIGHTCTRL",
    "LeftShift":  "KEY_LEFTSHIFT",
    "RightShift": "KEY_RIGHTSHIFT",
    "LeftAlt":    "KEY_LEFTALT",
    "RightAlt":   "KEY_RIGHTALT",
    "LeftMeta":   "KEY_LEFTMETA",
    "RightMeta":  "KEY_RIGHTMETA",
    # Navigation
    "PageUp":   "KEY_PAGEUP",
    "PageDown": "KEY_PAGEDOWN",
    # Special
    "CapsLock":   "KEY_CAPSLOCK",
    "ScrollLock": "KEY_SCROLLLOCK",
    "NumLock":    "KEY_NUMLOCK",
    "PrintScreen": "KEY_SYSRQ",
    "SysRq":       "KEY_SYSRQ",   # legacy alias
    "Escape":     "KEY_ESC",
    # Symbols
    "LeftBrace":  "KEY_LEFTBRACE",
    "RightBrace": "KEY_RIGHTBRACE",
    # Media
    "VolumeUp":   "KEY_VOLUMEUP",
    "VolumeDown": "KEY_VOLUMEDOWN",
    "NextSong":   "KEY_NEXTSONG",
    "PrevSong":   "KEY_PREVIOUSSONG",
    "PlayPause":  "KEY_PLAYPAUSE",
    "StopCd":     "KEY_STOPCD",
}
# Build reverse map — first occurrence wins so new short names (Num+, Num-, …)
# take priority over legacy aliases (NumPlus, NumMinus, …) that appear later.
_KM_ALIAS_REV: dict[str, str] = {}
for _alias_k, _alias_v in _KM_ALIASES.items():
    if _alias_v not in _KM_ALIAS_REV:
        _KM_ALIAS_REV[_alias_v] = _alias_k

# ── Regexes ───────────────────────────────────────────────────────────────────

# Old format
_KEY_RE  = re.compile(r'^KEY_[A-Z0-9_]+$')
_BTN_RE  = re.compile(r'^BTN_[A-Z0-9_]+$')
_HOLD_RE = re.compile(r'^[+\-](KEY_[A-Z0-9_]+)$')
_WAIT_RE = re.compile(r'^t(\d+)$')

# New format: LEFTCTRL+, A-, BTN_LEFT+, F1, 1, MiddleButton, MiddleButton+ …
# Digits allowed at start (KEY_1, KEY_0, etc.).
# Lowercase t is NOT matched at start so t50 wait tokens are never matched here.
_NEWKEY_RE = re.compile(r'^([A-Z0-9][A-Za-z0-9_]*)([+-]?)$')


# ── Core utility ──────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=512)
def expand_token(token: str) -> tuple[str, str] | None:
    """
    Parse any valid token (old or new format) into (action, evdev_name).
    Returns None for wait tokens (t50) or unrecognised tokens.

    action:     'tap' | 'down' | 'up'
    evdev_name: full Linux evdev name e.g. 'KEY_A', 'BTN_LEFT'
    """
    if not token:
        return None

    # Wait token — caller handles timing
    if _WAIT_RE.match(token):
        return None

    # ── Old format ────────────────────────────────────────────────────────────

    # +KEY_A / -KEY_A  (hold / release)
    if token[0] in ('+', '-'):
        m = _HOLD_RE.match(token)
        if m:
            action = 'down' if token[0] == '+' else 'up'
            return (action, token[1:])
        # New prefix format: +A, +LeftCtrl, -NumPlus, +BTN_LEFT …
        rest = token[1:]
        if rest:
            base_result = expand_token(rest)   # recurse on the bare name
            if base_result is not None:
                action = 'down' if token[0] == '+' else 'up'
                return (action, base_result[1])
        return None

    # KEY_A  (tap)
    if token.startswith('KEY_'):
        if _KEY_RE.match(token):
            return ('tap', token)
        return None

    # BTN_LEFT  (tap, old style — no trailing + or -)
    if token.startswith('BTN_') and token[-1] not in ('+', '-'):
        if _BTN_RE.match(token):
            return ('tap', token)
        return None

    # ── Exact alias match (highest priority for special-char names) ───────────
    # Must come before _NEWKEY_RE so that names containing +, -, *, /, .
    # (e.g. Num+, Num-, Num*, Num/, Num.) are resolved as aliases, not
    # misread as "name + hold/release suffix" by the regex.

    if token in _KM_ALIASES:
        return ('tap', _KM_ALIASES[token])

    # ── New format ────────────────────────────────────────────────────────────

    m = _NEWKEY_RE.match(token)
    if m:
        name, suffix = m.group(1), m.group(2)
        # KEY_* in this position means old-format token that somehow slipped
        # through — treat as unknown to avoid KEY_KEY_A confusion.
        if name.startswith('KEY_'):
            return None
        # Derive evdev name (keymacro alias takes priority)
        if name in _KM_ALIASES:
            evdev_name = _KM_ALIASES[name]
        elif name.startswith('BTN_'):
            evdev_name = name.upper()
        else:
            evdev_name = 'KEY_' + name.upper()  # Enter→KEY_ENTER, F1→KEY_F1
        if suffix == '+':
            return ('down', evdev_name)
        elif suffix == '-':
            return ('up', evdev_name)
        else:
            return ('tap', evdev_name)

    return None


@functools.lru_cache(maxsize=512)
def to_new_format(token: str) -> str:
    """
    Convert any valid token to the preferred new +A / A / -A style.
    Wait tokens and unknown tokens are returned unchanged.

    KEY_A       → A
    +KEY_A      → +A
    -KEY_A      → -A
    BTN_LEFT    → BTN_LEFT   (BTN_ prefix kept to avoid LEFT-arrow collision)
    BTN_LEFT+   → +BTN_LEFT   (backward compat input, prefix output)
    t50         → t50
    """
    if _WAIT_RE.match(token):
        return token
    expanded = expand_token(token)
    if expanded is None:
        return token  # unknown — leave as-is
    action, evdev_name = expanded
    # Prefer keymacro alias (Num1) over raw evdev short name (KP1)
    if evdev_name in _KM_ALIAS_REV:
        short = _KM_ALIAS_REV[evdev_name]
    elif evdev_name.startswith('KEY_'):
        raw = evdev_name[4:]
        # ALLCAPS single-word → capitalize first letter (ENTER→Enter, F1→F1)
        short = raw.capitalize() if raw == raw.upper() else raw
    else:
        short = evdev_name
    if action == 'tap':
        return short
    elif action == 'down':
        return '+' + short
    else:
        return '-' + short


# ── Display helpers ───────────────────────────────────────────────────────────

# Modifier evdev names → compact symbol
_MOD_SYMS: dict[str, str] = {
    "KEY_LEFTCTRL":   "^", "KEY_RIGHTCTRL":  "^",
    "KEY_LEFTSHIFT":  "⇧", "KEY_RIGHTSHIFT": "⇧",
    "KEY_LEFTALT":    "⌥", "KEY_RIGHTALT":   "⌥",
    "KEY_LEFTMETA":   "⊞", "KEY_RIGHTMETA":  "⊞",
}


def _friendly_name(token: str) -> str:
    """
    Convert a normalized (new-format) token to a short human-readable label.

    Rules:
      - Wait tokens (t50)           → "…"
      - PascalCase names            → kept as-is  (MiddleButton → MiddleButton)
      - ALL_CAPS / ALL_CAPS+digits  → capitalize first letter (ENTER → Enter, NUM1 → Num1)
    """
    if _WAIT_RE.match(token):
        return "…"
    # Strip leading and trailing +/- to handle both old and new format
    name = token.strip("+-")
    # Check alias reverse — already normalized names stay as-is
    if name == name.upper():
        return name.capitalize()   # ALL_CAPS  → Enter, Num1, F1…
    return name                    # PascalCase → MiddleButton etc.


def format_macro_label(token_str: str) -> str:
    """
    Produce a compact (~12 char) human-readable summary of a macro token
    sequence, suitable for display on a small canvas button.

    - Normalizes all tokens to new format first (handles legacy KEY_* / BTN_*)
    - Modifier hold/release tokens become prefix symbols (^, ⇧, ⌥, ⊞)
    - Single-action tokens display the virtual keycode name with friendly casing
    - Multi-action sequences are joined; truncated at 12 chars with "…"
    - Profile-switch tokens (!profile ...) shown as »<name>
    """
    tokens = token_str.split()
    if not tokens:
        return ""

    # Normalize each token to new format
    tokens = [to_new_format(t) for t in tokens]

    # Profile-switch shortcut
    if len(tokens) == 1 and tokens[0].startswith("!profile "):
        return "»" + tokens[0][9:]

    mods = ""
    parts: list[str] = []

    for tok in tokens:
        if not tok:
            continue
        # New-format modifier hold/release: +LeftCtrl / -LeftCtrl
        if tok and tok[0] in ("+", "-"):
            evdev = expand_token(tok)
            if evdev and evdev[1] in _MOD_SYMS:
                if tok[0] == "+":
                    mods += _MOD_SYMS[evdev[1]]
                continue  # release — skip
        # Wait token
        if _WAIT_RE.match(tok):
            parts.append("…")
            continue
        parts.append(_friendly_name(tok))

    result = mods + " ".join(parts)
    if len(result) > 12:
        result = result[:11] + "…"
    return result


# ── Public API ────────────────────────────────────────────────────────────────

def derive_release(press_tokens: list[str]) -> list[str]:
    """
    Auto-derive a release sequence from a press sequence.

    Takes only the hold-down tokens (action == 'down'), reverses their
    order, and flips each to the corresponding release token.

    Examples:
        ["+LeftCtrl"]              → ["-LeftCtrl"]
        ["+LeftCtrl", "+LeftShift"] → ["-LeftShift", "-LeftCtrl"]
        ["+LeftCtrl", "C", "-LeftCtrl"] → []   (all holds already closed)
    """
    holds: list[str] = []
    for tok in press_tokens:
        exp = expand_token(tok)
        if not exp:
            continue
        action, _ = exp
        if action == 'down':
            holds.append(tok)
        elif action == 'up':
            # closed hold — remove the matching down from the stack
            if holds:
                holds.pop()
    # Reverse and flip + → -
    result: list[str] = []
    for tok in reversed(holds):
        if tok.startswith('+'):
            result.append('-' + tok[1:])
        elif tok.endswith('+'):        # old suffix format still in memory
            result.append(tok[:-1] + '-')
    return result


def is_valid_token(token: str) -> bool:
    """Return True if *token* is a recognised macro token."""
    if not token:
        return False
    m = _WAIT_RE.match(token)
    if m:
        return 1 <= int(m.group(1)) <= 60000
    return expand_token(token) is not None


def parse(macro_string: str) -> list[str]:
    """Split a space-separated macro string into a list of tokens.

    Empty string → empty list.  Consecutive spaces are collapsed.
    """
    if not macro_string or not macro_string.strip():
        return []
    return macro_string.split()


def serialize(tokens: list[str]) -> str:
    """Join a token list into a space-separated macro string."""
    return ' '.join(tokens)


def validate(tokens: list[str]) -> list[str]:
    """Return a list of human-readable warning strings (empty = valid).

    Does not raise — always returns a usable result.
    Checks:
      - Unknown / malformed tokens
      - Wait values out of range
      - Unbalanced hold-down / hold-up pairs (warning only)
    """
    warnings: list[str] = []
    held: dict[str, int] = {}   # evdev_name → hold count

    for i, tok in enumerate(tokens):
        if not tok:
            warnings.append(f"Token {i}: empty string ignored")
            continue

        m = _WAIT_RE.match(tok)
        if m:
            n = int(m.group(1))
            if not (1 <= n <= 60000):
                warnings.append(
                    f"Token {i} '{tok}': wait value {n} out of range 1–60000")
            continue

        expanded = expand_token(tok)
        if expanded is None:
            warnings.append(f"Token {i} '{tok}': unrecognised token")
            continue

        action, evdev_name = expanded
        if action == 'down':
            held[evdev_name] = held.get(evdev_name, 0) + 1
        elif action == 'up':
            if held.get(evdev_name, 0) <= 0:
                warnings.append(
                    f"Token {i} '{tok}': releasing '{evdev_name}' "
                    f"that was never held")
            else:
                held[evdev_name] -= 1
        # 'tap' — no hold tracking needed

    for key, count in held.items():
        if count > 0:
            warnings.append(
                f"'{key}' is held {count} time(s) with no matching release "
                f"(will auto-release at execution time)")

    return warnings
