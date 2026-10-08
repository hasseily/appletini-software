# SPDX-License-Identifier: GPL-2.0-only
"""Map a finite set of physical keyboard codes to complete controller state.

This module has no machine or browser side effects. Both the JSONL debugger
and browser viewer can pass its events to the native input API. A fresh call
emits every axis and button, so releasing the last key clears held controls.
"""

from __future__ import annotations


DIRECTION_CODES = frozenset({
    "KeyQ", "KeyW", "KeyE", "KeyA", "KeyS", "KeyD", "KeyZ", "KeyX", "KeyC",
})
BUTTON_BITS = {
    "Space": 0, "KeyK": 1, "Tab": 2, "Enter": 3,
    "KeyJ": 8, "KeyU": 9, "KeyI": 10, "KeyO": 11,
}
VALID_CODES = DIRECTION_CODES | frozenset(BUTTON_BITS)
CENTER = 128


def events(codes) -> list[dict[str, int | str]]:
    """Return paddle/button/first-player pad events for held KeyboardEvent codes.

    QWE/ASD/ZXC form the direction grid; S centers both axes. Opposite
    directions cancel. Unknown codes, non-string codes and unbounded iterables
    are rejected rather than silently turning typing into controller input.
    """
    if not isinstance(codes, (list, tuple, set, frozenset)):
        raise ValueError("codes must be a finite list or set of physical keyboard codes")
    if len(codes) > len(VALID_CODES):
        raise ValueError("too many keyboard codes")
    if any(not isinstance(code, str) for code in codes):
        raise ValueError("keyboard codes must be strings")
    held = set(codes)
    unknown = held - VALID_CODES
    if unknown:
        raise ValueError("unsupported joystick keys: " + ", ".join(sorted(unknown)))

    dx = int(bool(held & {"KeyE", "KeyD", "KeyC"})) - int(
        bool(held & {"KeyQ", "KeyA", "KeyZ"}))
    dy = int(bool(held & {"KeyZ", "KeyX", "KeyC"})) - int(
        bool(held & {"KeyQ", "KeyW", "KeyE"}))
    if "KeyS" in held:
        dx = dy = 0
    axes = {-1: 0, 0: CENTER, 1: 255}
    pad = sum(1 << bit for code, bit in BUTTON_BITS.items() if code in held)
    if dy < 0:
        pad |= 1 << 4
    elif dy > 0:
        pad |= 1 << 5
    if dx < 0:
        pad |= 1 << 6
    elif dx > 0:
        pad |= 1 << 7

    return [
        {"kind": "paddle", "x": 0, "y": axes[dx]},
        {"kind": "paddle", "x": 1, "y": axes[dy]},
        {"kind": "button", "x": 0, "y": int("Space" in held)},
        {"kind": "button", "x": 1, "y": int("KeyJ" in held)},
        {"kind": "button", "x": 2, "y": int("KeyK" in held)},
        {"kind": "pad", "x": 0, "y": pad},
    ]
