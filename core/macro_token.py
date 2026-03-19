"""
core/macro_token.py — Macro token format parser, validator, and serializer.

Token grammar — two equivalent styles are accepted:

  New (preferred):
    A               tap KEY_A       (press + release)
    A+              hold KEY_A down
    A-              release KEY_A
    LEFTCTRL+       hold KEY_LEFTCTRL
    BTN_LEFT        tap BTN_LEFT mouse button
    BTN_LEFT+       hold BTN_LEFT
    t50             wait 50 ms

  Legacy (still valid, used in stored profiles):
    KEY_A           tap
    +KEY_A          hold
    -KEY_A          release
    BTN_LEFT        tap mouse button
    t50             wait

The key names are Linux evdev key names with the KEY_ prefix stripped for
keyboard keys.  Mouse button names keep the BTN_ prefix to avoid collision
(e.g. BTN_LEFT vs KEY_LEFT arrow).

Use expand_token() to convert any token — old or new format — into a
(action, evdev_name) pair that translation backends can use directly.

No Qt dependency — pure Python.
"""

from __future__ import annotations

import re

# ── Regexes ───────────────────────────────────────────────────────────────────

# Old format
_KEY_RE  = re.compile(r'^KEY_[A-Z0-9_]+$')
_BTN_RE  = re.compile(r'^BTN_[A-Z0-9_]+$')
_HOLD_RE = re.compile(r'^[+\-](KEY_[A-Z0-9_]+)$')
_WAIT_RE = re.compile(r'^t(\d+)$')

# New format: LEFTCTRL+, A-, BTN_LEFT+, F1, 1, 1+, 0- …
# Digits allowed at start (KEY_1, KEY_0, etc.).
# Lowercase t is NOT in [A-Z0-9] so t50 wait tokens are never matched here.
_NEWKEY_RE = re.compile(r'^([A-Z0-9][A-Z0-9_]*)([+-]?)$')


# ── Core utility ──────────────────────────────────────────────────────────────

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

    # ── New format ────────────────────────────────────────────────────────────

    m = _NEWKEY_RE.match(token)
    if m:
        name, suffix = m.group(1), m.group(2)
        # KEY_* in this position means old-format token that somehow slipped
        # through — treat as unknown to avoid KEY_KEY_A confusion.
        if name.startswith('KEY_'):
            return None
        # Derive evdev name
        evdev_name = name if name.startswith('BTN_') else ('KEY_' + name)
        if suffix == '+':
            return ('down', evdev_name)
        elif suffix == '-':
            return ('up', evdev_name)
        else:
            return ('tap', evdev_name)

    return None


def to_new_format(token: str) -> str:
    """
    Convert any valid token to the preferred new A / A+ / A- style.
    Wait tokens and unknown tokens are returned unchanged.

    KEY_A       → A
    +KEY_A      → A+
    -KEY_A      → A-
    BTN_LEFT    → BTN_LEFT   (BTN_ prefix kept to avoid LEFT-arrow collision)
    BTN_LEFT+   → BTN_LEFT+
    t50         → t50
    """
    if _WAIT_RE.match(token):
        return token
    expanded = expand_token(token)
    if expanded is None:
        return token  # unknown — leave as-is
    action, evdev_name = expanded
    short = evdev_name[4:] if evdev_name.startswith('KEY_') else evdev_name
    if action == 'tap':
        return short
    elif action == 'down':
        return short + '+'
    else:
        return short + '-'


# ── Public API ────────────────────────────────────────────────────────────────

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
