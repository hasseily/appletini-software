#!/usr/bin/env python3
"""The //e key table and the key names (part plinput;
docs/SCREENS.md, the keys). GPL-2, the
port's own.

The //e delivers a key code 1-127 at $C000; src/native/pl_input.s folds
$61-$7A to upper case, so four of those codes carry the pseudo-keys
(docs/SCREENS.md): $70 the mouse's button 1 (MOUSE 2), $71 its
button 0 (MOUSE 1), $72 Open Apple, $73 Solid Apple. Upstream's key table has 128 entries of a
Doom key and a character [R i_iigs65.s:83, :98-108]; this one has the
same format, so it is poked 1:1 into ref816's keyTable (docs/SCREENS.md):

  the Doom key   the defaults: the arrows, W/S move, A/D and ,/.
                 strafe, 1-7 the weapons, E, SPACE and RETURN use, ESC the
                 menu, TAB the map, -/= zoom, Open Apple fire, Solid Apple
                 use, MOUSE 1 fire, MOUSE 2 strafe; NOKEY ($FF) elsewhere
  the character  as upstream's [R i_iigs65.s:109-246]: a letter's lower
                 case, a digit, and the menu keys KEYC_UP, KEYC_DOWN,
                 KEYC_LEFT, KEYC_RIGHT (the arrows), KEYC_ENTER (RETURN),
                 KEYC_BACK (DELETE) [R keys.inc:23-28]; 0 elsewhere
  the name       at most 7 characters and a 0, 8 bytes a name as
                 upstream's keyNames [R m_menu65.s:252-253, :1369-1381]:
                 CTRL-A..., LEFT, TAB, DOWN, UP, RETURN, RIGHT, ESC, SPACE,
                 DELETE, the printable characters, MOUSE 2, MOUSE 1,
                 O-APPLE, S-APPLE; empty for 0 and the other folded codes

pl_input.s holds the Doom keys at run time in PL_KEYTAB (128 B)
and computes the characters (pl_chr); its defaults are written
there by hand, equal to this table.

Usage:  python3 tools/native/plkeys.py --inc OUT    (gen/plkeys.inc for
        the menus: the names, the Doom keys, the characters, as macros)
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

# the Doom keys [R keys.inc:5-21]
KEY = {'SPEED': 0, 'USE': 1, 'FIRE': 2, 'STRAFELEFT': 3, 'STRAFERIGHT': 4,
       'UP': 5, 'DOWN': 6, 'LEFT': 7, 'RIGHT': 8, 'ESCAPE': 9, 'MAP': 10,
       'ZOOMOUT': 11, 'ZOOMIN': 12, 'WEAPONDOWN': 13, 'WEAPONUP': 14,
       'STRAFE': 15, 'WEAPON1': 16}
NUMKEYS = 23
NOKEY = 0xFF                            # [R i_iigs65.s:44]
# the menu keys' characters [R keys.inc:23-28]
KEYC = {'UP': 0x80, 'DOWN': 0x81, 'LEFT': 0x82, 'RIGHT': 0x83,
        'ENTER': 0x84, 'BACK': 0x85}
CODES, NAME_SIZE = 128, 8

# the //e's special codes
LEFT, TAB, DOWN, UP, RETURN, RIGHT, ESC, SPACE, DELETE = \
    0x08, 0x09, 0x0A, 0x0B, 0x0D, 0x15, 0x1B, 0x20, 0x7F
# the pseudo-keys in the folded lower-case codes (docs/SCREENS.md)
MOUSE2, MOUSE1, OAPPLE, SAPPLE = 0x70, 0x71, 0x72, 0x73
PSEUDO = (MOUSE2, MOUSE1, OAPPLE, SAPPLE)   # PL_BUTTONS bits 0-3

SPECIAL_NAMES = {LEFT: 'LEFT', TAB: 'TAB', DOWN: 'DOWN', UP: 'UP',
                 RETURN: 'RETURN', RIGHT: 'RIGHT', ESC: 'ESC',
                 SPACE: 'SPACE', DELETE: 'DELETE', MOUSE2: 'MOUSE 2',
                 MOUSE1: 'MOUSE 1', OAPPLE: 'O-APPLE', SAPPLE: 'S-APPLE'}
MENU_CHARS = {UP: KEYC['UP'], DOWN: KEYC['DOWN'], LEFT: KEYC['LEFT'],
              RIGHT: KEYC['RIGHT'], RETURN: KEYC['ENTER'],
              DELETE: KEYC['BACK']}

# the defaults (docs/SCREENS.md): (//e code, Doom key)
DEFAULTS: Tuple[Tuple[int, int], ...] = tuple(
    [(UP, KEY['UP']), (DOWN, KEY['DOWN']), (LEFT, KEY['LEFT']),
     (RIGHT, KEY['RIGHT']), (ord('W'), KEY['UP']), (ord('S'), KEY['DOWN']),
     (ord('A'), KEY['STRAFELEFT']), (ord('D'), KEY['STRAFERIGHT']),
     (ord(','), KEY['STRAFELEFT']), (ord('.'), KEY['STRAFERIGHT']),
     (ord('E'), KEY['USE']), (SPACE, KEY['USE']), (RETURN, KEY['USE']),
     (ESC, KEY['ESCAPE']), (TAB, KEY['MAP']), (ord('-'), KEY['ZOOMOUT']),
     (ord('='), KEY['ZOOMIN']), (OAPPLE, KEY['FIRE']),
     (SAPPLE, KEY['USE']), (MOUSE1, KEY['FIRE']), (MOUSE2, KEY['STRAFE'])] +
    [(ord('1') + i, KEY['WEAPON1'] + i) for i in range(7)])


def char(code: int) -> int:
    """The character of a folded code (0: none)."""
    if 0x30 <= code <= 0x39:
        return code
    if 0x41 <= code <= 0x5A:
        return code + 0x20
    return MENU_CHARS.get(code, 0)


def doom_keys() -> List[int]:
    """The Doom-key column: the defaults, NOKEY elsewhere."""
    keys = [NOKEY] * CODES
    for code, k in DEFAULTS:
        keys[code] = k
    return keys


def table() -> List[Tuple[int, int]]:
    """The 128 entries (Doom key, character), upstream's keyTable format."""
    keys = doom_keys()
    return [(keys[c], char(c)) for c in range(CODES)]


def names() -> List[str]:
    out = ['' for _ in range(CODES)]
    for c in range(1, 0x20):
        out[c] = 'CTRL-%c' % (0x40 + c)
    for c in list(range(0x20, 0x61)) + list(range(0x7B, 0x7F)):
        out[c] = chr(c)
    for c, n in SPECIAL_NAMES.items():
        out[c] = n
    return out


def problems() -> List[str]:
    """The table's own rules."""
    out = []
    nm = names()
    for c, n in enumerate(nm):
        if len(n) > NAME_SIZE - 1:
            out.append('$%02X: the name %r is longer than 7' % (c, n))
        if not all(0x20 <= ord(x) < 0x7F for x in n):
            out.append('$%02X: the name %r is not printable' % (c, n))
    for c in range(0x61, 0x7B):
        if c not in PSEUDO and (nm[c] or doom_keys()[c] != NOKEY):
            out.append('$%02X is folded: no name, no key' % c)
    for c, k in DEFAULTS:
        if not (0 < c < CODES and 0 <= k < NUMKEYS):
            out.append('a default ($%02X, %d) out of range' % (c, k))
        if 0x61 <= c <= 0x7A and c not in PSEUDO:
            out.append('a default on the folded code $%02X' % c)
    if len({c for c, _ in DEFAULTS}) != len(DEFAULTS):
        out.append('a code bound twice')
    return out


def inc_text() -> str:
    """gen/plkeys.inc: the constants and three macros that emit the
    columns (each 128 bytes) and the names (128 x 8 bytes)."""
    lines = ['; Generated by tools/native/plkeys.py (docs/SCREENS.md, the',
             '; keys): the //e key table and names. Do not edit.',
             'PLK_CODES     = %d' % CODES,
             'PLK_NAMESIZE  = %d' % NAME_SIZE,
             'PLK_NOKEY     = $%02X' % NOKEY,
             'PLK_NUMKEYS   = %d' % NUMKEYS]
    for name, code in (('MOUSE2', MOUSE2), ('MOUSE1', MOUSE1),
                       ('OAPPLE', OAPPLE), ('SAPPLE', SAPPLE)):
        lines.append('PLK_%-10s = $%02X' % (name, code))
    tb = table()

    def rows(values: Sequence[int]) -> List[str]:
        return ['        .byte ' + ','.join('$%02X' % v for v in
                                            values[i:i + 16])
                for i in range(0, len(values), 16)]
    lines.append('.macro plk_keys       ; the Doom keys (the defaults)')
    lines += rows([k for k, _ in tb])
    lines.append('.endmacro')
    lines.append('.macro plk_chars      ; the characters')
    lines += rows([c for _, c in tb])
    lines.append('.endmacro')
    lines.append('.macro plk_names      ; 8 bytes a name, 0-terminated')
    for c, n in enumerate(names()):
        raw = list(n.encode('ascii')) + [0] * (NAME_SIZE - len(n))
        lines.append('        .byte ' + ','.join('$%02X' % v for v in raw) +
                     '   ; $%02X' % c)
    lines.append('.endmacro')
    return '\n'.join(lines) + '\n'


def write_if_changed(path: Path, text: str) -> None:
    if path.exists() and path.read_text() == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text)
    tmp.replace(path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--inc', type=Path)
    args = parser.parse_args(argv)
    bad = problems()
    if bad:
        print('\n'.join(bad), file=sys.stderr)
        return 1
    if args.inc:
        write_if_changed(args.inc, inc_text())
    return 0


if __name__ == '__main__':
    sys.exit(main())
