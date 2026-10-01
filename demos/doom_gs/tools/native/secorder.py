#!/usr/bin/env python3
"""The synthetic setup `secorder` (milestone 9, the verification of stage
C; docs/LEVELS.md "Verification of stage C", defect 4): map things of
E1M1 moved to block corners where the order of P_CreateSecNodeList's
block walk shows.

At setup no E1 thing's box spans two blocks whose lines add two new
sectors in an order that depends on the walk's order (x outer and y
inner, as upstream's lineBlocks), so the 54 captured setups cannot tell a
walk with y outer. This module finds, on the host, block corners of
E1M1 where the two orders give different sector lists (the touching
list of the thing put there), and moves some of E1M1's spawned things
there; tools/native/setupcap.py's run `secorder` pokes them into
upstream's THINGS lump at the first P_SpawnMapThing (newgame.script), and
setupcheck.py puts the same coordinates into the store's THINGS block of
the native run. The model here only chooses the places: what is compared
is ref816's setup against the native one, and the planted walk with y
outer must fail on it (tests/test_native_level_setup.py).

The model (from upstream's walk as gpos.s describes it): the box of a
thing at (x, y) of radius r (whole units) is left x - r, bottom y - r,
right x + r - 1, top y + r - 1 for the overlap tests; each block's list
after its first entry; a line stamped once a walk; a line whose box
overlaps the thing's box crosses it if it is horizontal or vertical, and
if slanted when its corners (the box's) are on two sides; the crossed
line's front, then its back sector, each added at the head of the list
unless it is in it. A place is kept only when the box grown and shrunk by
a unit gives the same lists (no edge case decides it).

Usage:  python3 tools/native/secorder.py      # the chosen places
"""

import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

BASE_SETUP = 'newgame-01'       # E1M1 at skill 2 (newgame.script)
GAMEMAP = 1
MOVED = 4                       # the things moved, at most (E1M1: 3 places)
MIN_RADIUS = 20
BLOCK = 128


def _index(ref) -> Optional[int]:
    return None if ref is None else ref.id


def level_of(state: Dict[str, Any]) -> Dict[str, Any]:
    """The walk's inputs from a canonical state: the blockmap's origin,
    size and lists (after each list's first entry), each line's bbox,
    slope type, ends, front and back sectors."""
    o = state['objects']
    raw = bytes.fromhex(o['blockmap'][0]['bytes'])
    words = struct.unpack('<%dh' % (len(raw) // 2), raw)
    orgx, orgy, w, h = words[0:4]
    lists = []
    for b in range(w * h):
        at = words[4 + b] & 0xFFFF
        out = []
        k = at + 1
        while words[k] >= 0:
            out.append(words[k])
            k += 1
        lists.append(out)
    sides = o['side']
    lines = []
    for i in range(len(o['line'])):
        ln = o['line'][i]
        s0, s1 = ln['sidenum']
        front = _index(sides[s0]['sector'])
        back = _index(sides[s1]['sector']) if s1 >= 0 else None
        lines.append({'bbox': ln['bbox'], 'slope': ln['slopetype'],
                      'v1': ln['v1'], 'v2': ln['v2'], 'front': front,
                      'back': back})
    return {'orgx': orgx, 'orgy': orgy, 'w': w, 'h': h, 'lists': lists,
            'lines': lines}


def _side(px: int, py: int, ln: Dict[str, Any]) -> int:
    (x1, y1), (x2, y2) = ln['v1'], ln['v2']
    return 1 if (py - y1) * (x2 - x1) >= (px - x1) * (y2 - y1) else 0


def crosses(box: Tuple[int, int, int, int], ln: Dict[str, Any]) -> bool:
    left, bottom, right, top = box
    bt, bb, bl, br = ln['bbox']         # top, bottom, left, right
    if bottom >= bt or top <= bb or right <= bl or left >= br:
        return False
    if ln['slope'] < 2:                 # horizontal or vertical
        return True
    if ln['slope'] == 2:                # positive: (left, top), (right, bottom)
        a, b = _side(left, top, ln), _side(right, bottom, ln)
    else:                               # negative: (right, top), (left, bottom)
        a, b = _side(right, top, ln), _side(left, bottom, ln)
    return a != b


def walk(level: Dict[str, Any], x: int, y: int, r: int, own: int,
         x_outer: bool = True, grow: int = 0) -> List[int]:
    """The thing's sector list, head first."""
    left, bottom = x - r - grow, y - r - grow
    right, top = x + r - 1 + grow, y + r - 1 + grow
    xl = max(0, (left - level['orgx']) >> 7)
    xh = min(level['w'] - 1, (right - level['orgx']) >> 7)
    yl = max(0, (bottom - level['orgy']) >> 7)
    yh = min(level['h'] - 1, (top - level['orgy']) >> 7)
    order = [(bx, by) for bx in range(xl, xh + 1)
             for by in range(yl, yh + 1)] if x_outer else \
        [(bx, by) for by in range(yl, yh + 1) for bx in range(xl, xh + 1)]
    seen, out = set(), []
    for bx, by in order:
        for n in level['lists'][by * level['w'] + bx]:
            if n in seen:
                continue
            seen.add(n)
            ln = level['lines'][n]
            if not crosses((left, bottom, right, top), ln):
                continue
            for s in (ln['front'], ln['back']):
                if s is not None and s not in out:
                    out.insert(0, s)
    if own not in out:
        out.insert(0, own)
    return out


def sector_at(state: Dict[str, Any], x: int, y: int) -> int:
    """R_PointInSubsector's sector on the canonical nodes (whole units;
    a child with bit 15 a subsector)."""
    o = state['objects']
    n = len(o['node']) - 1
    while True:
        nd = o['node'][n]
        child = nd['children'][1 if _point_back(x, y, nd) else 0]
        if child & 0x8000:
            return _index(o['subsector'][child & 0x7FFF]['sector'])
        n = child


def _point_back(x: int, y: int, nd: Dict[str, Any]) -> bool:
    nx, ny, dx, dy = (nd[k] for k in ('x', 'y', 'dx', 'dy'))
    if dx == 0:
        return (dy > 0) if x <= nx else (dy < 0)
    if dy == 0:
        return (dx < 0) if y <= ny else (dx > 0)
    return (y - ny) * dx >= (x - nx) * dy


def places(state: Dict[str, Any], r: int, count: int
           ) -> List[Tuple[int, int, List[int], List[int]]]:
    """Block corners (x, y) where the two orders differ for a thing of
    radius r, robustly; the corners with the most lines first, at most
    one a block column and row."""
    level = level_of(state)
    found = []
    for bx in range(1, level['w']):
        for by in range(1, level['h']):
            x, y = level['orgx'] + BLOCK * bx, level['orgy'] + BLOCK * by
            try:
                own = sector_at(state, x, y)
            except (KeyError, IndexError, TypeError):
                continue
            lists = []
            for grow in (-1, 0, 1):
                a = walk(level, x, y, r, own, True, grow)
                b = walk(level, x, y, r, own, False, grow)
                lists.append((a, b))
            if any(a == b for a, b in lists) or \
                    any(p != lists[1] for p in lists):
                continue
            found.append((len(lists[1][0]), bx, by, x, y) + lists[1])
    found.sort(key=lambda f: (-f[0], f[1], f[2]))
    out, cols, rows = [], set(), set()
    for _, bx, by, x, y, a, b in found:
        if bx in cols or by in rows:
            continue
        cols.add(bx)
        rows.add(by)
        out.append((x, y, a, b))
        if len(out) == count:
            break
    return out


def map_things(rm, symbols) -> Tuple[int, List[Tuple[int, ...]]]:
    """Upstream's THINGS lump of the loaded map (p_setup65.s SU_T, which
    loadThings2 leaves pointing at it) and its records (x, y, type, angle,
    options)."""
    at = struct.unpack('<I', bytes(rm.read(
        symbols.address('p_setup65.s:SU_T'), 4)))[0]
    n = struct.unpack('<H', bytes(rm.read(
        symbols.address('p_setup65.s:_g_thingPoolSize'), 2)))[0]
    return at, [struct.unpack('<hhhbb', bytes(rm.read(at + 8 * i, 8)))
                for i in range(n)]


def choose(setups: Path) -> Dict[str, Any]:
    """The moves: from BASE_SETUP's R dump, MOVED things of E1M1 that
    spawn there (not the player), of radius MIN_RADIUS or more, in map
    order, each to one of `places`."""
    from bridge import upstream
    from native import levelconv as LC
    d = setups / BASE_SETUP
    rm = LC.load_memory(d / 'r.ram.z')
    state = upstream.Reader(rm).read()
    at, things = map_things(rm, upstream.Schema().symbols)
    mobjs = [m for m in state['objects']['mobj'].values() if not m['free']]
    pick = []
    for i, (x, y, kind, _, _) in enumerate(things):
        if kind == 1:
            continue
        m = [mo for mo in mobjs if mo['x'] == x << 16 and mo['y'] == y << 16]
        if len(m) != 1 or m[0]['radius'] >> 16 < MIN_RADIUS or \
                m[0]['radius'] & 0xFFFF:
            continue
        pick.append((i, m[0]['radius'] >> 16))
    radii = sorted({r for _, r in pick})
    moves = []
    used = set()
    for r in radii:
        cands = [i for i, rr in pick if rr == r]
        for (x, y, a, b), i in zip(places(state, r, MOVED - len(moves)),
                                   cands):
            if (x, y) in used:
                continue
            used.add((x, y))
            moves.append({'thing': i, 'x': x, 'y': y, 'radius': r,
                          'x_outer': a, 'y_outer': b})
        if len(moves) >= MOVED:
            break
    if not moves:
        raise ValueError('no place where the walk\'s order shows')
    return {'base': BASE_SETUP, 'gamemap': GAMEMAP, 'things_at': at,
            'moves': moves}


def main() -> int:
    from native import setupcap
    out = choose(setupcap.SETUPS)
    print('THINGS at $%06X' % out['things_at'])
    for m in out['moves']:
        print('thing %(thing)d (radius %(radius)d) to (%(x)d, %(y)d): '
              'sectors x outer %(x_outer)s, y outer %(y_outer)s' % m)
    return 0


if __name__ == '__main__':
    sys.exit(main())
