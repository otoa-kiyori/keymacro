"""
core/macro_token.py — Macro token format parser, validator, and serializer.

Token grammar:
    sequence   ::= token (' ' token)*
    token      ::= hold_down | hold_up | tap_key | tap_btn | wait
    hold_down  ::= '+' key_name        # press and hold
    hold_up    ::= '-' key_name        # release held key
    tap_key    ::= key_name            # press + release
    tap_btn    ::= btn_name            # press + release (requires plugin software remap)
    wait       ::= 't' digits          # wait N ms (1–60000)
    key_name   ::= 'KEY_' [A-Z0-9_]+
    btn_name   ::= 'BTN_' [A-Z0-9_]+
    digits     ::= [0-9]+

No Qt dependency — pure Python.
"""

import re

_KEY_RE   = re.compile(r'^KEY_[A-Z0-9_]+$')
_BTN_RE   = re.compile(r'^BTN_[A-Z0-9_]+$')
_WAIT_RE  = re.compile(r'^t(\d+)$')
_HOLD_RE  = re.compile(r'^[+\-](KEY_[A-Z0-9_]+)$')


def is_valid_token(token: str) -> bool:
    """Return True if *token* matches the macro token grammar."""
    if not token:
        return False
    if token[0] in ('+', '-'):
        return bool(_HOLD_RE.match(token))
    if token.startswith('KEY_'):
        return bool(_KEY_RE.match(token))
    if token.startswith('BTN_'):
        return bool(_BTN_RE.match(token))
    m = _WAIT_RE.match(token)
    if m:
        n = int(m.group(1))
        return 1 <= n <= 60000
    return False


def parse(macro_string: str) -> list[str]:
    """Split a space-separated macro string into a list of tokens.

    Empty string → empty list. Consecutive spaces are collapsed.
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
      - Unknown tokens
      - Wait values out of range
      - Unbalanced hold-down / hold-up pairs (warning only)
    """
    warnings: list[str] = []
    held: dict[str, int] = {}   # key_name → count held

    for i, tok in enumerate(tokens):
        if not tok:
            warnings.append(f"Token {i}: empty string ignored")
            continue

        if tok[0] == '+':
            m = _HOLD_RE.match(tok)
            if not m:
                warnings.append(f"Token {i} '{tok}': invalid hold-down syntax")
            else:
                held[m.group(1)] = held.get(m.group(1), 0) + 1
            continue

        if tok[0] == '-':
            m = _HOLD_RE.match(tok)
            if not m:
                warnings.append(f"Token {i} '{tok}': invalid hold-up syntax")
            else:
                key = m.group(1)
                if held.get(key, 0) <= 0:
                    warnings.append(
                        f"Token {i} '{tok}': releasing '{key}' that was never held")
                else:
                    held[key] -= 1
            continue

        if tok.startswith('KEY_'):
            if not _KEY_RE.match(tok):
                warnings.append(f"Token {i} '{tok}': invalid KEY_ name")
            continue

        if tok.startswith('BTN_'):
            if not _BTN_RE.match(tok):
                warnings.append(f"Token {i} '{tok}': invalid BTN_ name")
            continue

        m = _WAIT_RE.match(tok)
        if m:
            n = int(m.group(1))
            if not (1 <= n <= 60000):
                warnings.append(
                    f"Token {i} '{tok}': wait value {n} out of range 1–60000")
            continue

        warnings.append(f"Token {i} '{tok}': unrecognized token")

    # Unbalanced holds
    for key, count in held.items():
        if count > 0:
            warnings.append(
                f"'{key}' is held down {count} time(s) with no matching release "
                f"(will auto-release at execution time)")

    return warnings
