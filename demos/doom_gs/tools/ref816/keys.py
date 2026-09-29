"""The keys of the Apple IIgs keyboard by name, as ADB key codes.

The IIgs keyboard (and the Apple Extended Keyboard on the same bus)
sends the codes of Apple's ADB keyboard protocol; the game turns them
into Doom keys and characters with its keyTable (src/iigs/i_iigs65.s).
Names are lower case; letters and digits are their own names, the
keypad keys are "keypad" and the key's name. `code` also takes a code
as a number ("0x35").
"""

from typing import Dict

_LETTERS = 'asdfhgzxcv'   # $00-$09, then $0B-$11 below
KEYS: Dict[str, int] = {c: i for i, c in enumerate(_LETTERS)}
KEYS.update({
    'b': 0x0b, 'q': 0x0c, 'w': 0x0d, 'e': 0x0e, 'r': 0x0f, 'y': 0x10,
    't': 0x11, '1': 0x12, '2': 0x13, '3': 0x14, '4': 0x15, '6': 0x16,
    '5': 0x17, 'equals': 0x18, '9': 0x19, '7': 0x1a, 'minus': 0x1b,
    '8': 0x1c, '0': 0x1d, 'rightbracket': 0x1e, 'o': 0x1f, 'u': 0x20,
    'leftbracket': 0x21, 'i': 0x22, 'p': 0x23, 'return': 0x24, 'l': 0x25,
    'j': 0x26, 'quote': 0x27, 'k': 0x28, 'semicolon': 0x29,
    'backslash': 0x2a, 'comma': 0x2b, 'slash': 0x2c, 'n': 0x2d, 'm': 0x2e,
    'period': 0x2f, 'tab': 0x30, 'space': 0x31, 'grave': 0x32,
    'delete': 0x33, 'escape': 0x35, 'control': 0x36, 'command': 0x37,
    'shift': 0x38, 'capslock': 0x39, 'option': 0x3a, 'left': 0x3b,
    'right': 0x3c, 'down': 0x3d, 'up': 0x3e,
    'keypadperiod': 0x41, 'keypadtimes': 0x43, 'keypadplus': 0x45,
    'keypadclear': 0x47, 'keypaddivide': 0x4b, 'keypadenter': 0x4c,
    'keypadminus': 0x4e, 'keypadequals': 0x51,
    'keypad0': 0x52, 'keypad1': 0x53, 'keypad2': 0x54, 'keypad3': 0x55,
    'keypad4': 0x56, 'keypad5': 0x57, 'keypad6': 0x58, 'keypad7': 0x59,
    'keypad8': 0x5b, 'keypad9': 0x5c,
    'f5': 0x60, 'f6': 0x61, 'f7': 0x62, 'f3': 0x63, 'f8': 0x64, 'f9': 0x65,
    'f11': 0x67, 'f13': 0x69, 'f14': 0x6b, 'f10': 0x6d, 'f12': 0x6f,
    'f15': 0x71, 'help': 0x72, 'home': 0x73, 'pageup': 0x74,
    'forwarddelete': 0x75, 'f4': 0x76, 'end': 0x77, 'f2': 0x78,
    'pagedown': 0x79, 'f1': 0x7a, 'reset': 0x7f,
})

ALIASES = {'esc': 'escape', 'ctrl': 'control', 'enter': 'return',
           'apple': 'command', 'alt': 'option'}

# The keys that give the characters of `type`: each letter and digit.
CHARACTERS = {name: code for name, code in KEYS.items() if len(name) == 1}


def code(name: str) -> int:
    """The ADB key code of the key `name` (or of a number 0-127)."""
    lowered = name.lower()
    lowered = ALIASES.get(lowered, lowered)
    if lowered in KEYS:
        return KEYS[lowered]
    try:
        value = int(name, 0)
    except ValueError:
        raise KeyError('no key is called %r' % name) from None
    if not 0 <= value <= 0x7f:
        raise KeyError('an ADB key code is 0-127, not %s' % name)
    return value
