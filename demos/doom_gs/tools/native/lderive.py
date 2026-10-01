"""The level load's static derivations on the host (docs/LEVELS.md 2.3):
the bytes the 65C02 steps LINES, GROUP, FLOOD and CMAPS must leave, as
upstream's loadLineDefs, groupLines and P_InitFlood make them
(p_setup65.s:259-404, :742-1102; p_pspr65.s:1253-1380). lstore.py writes
them into each map's expected window (window.img); stage B's loader is
checked against that. Here they are checked first against ref816's
canonical state at every end of setup (R dumps, tools/bridge):

    lines       v1, v2, dx, dy, the sides, the box (the signed compares
                with the overflow flip), tag and special (sign-extended
                bytes), flags (the low byte), the slope type
    subsectors  the sector of the first seg with a side
    sectors     the line count, the line table (each line in its front
                sector's, then its back sector's when that differs, in
                line order; the tables in sector order), the sound origin
                (M_AddToBox with its else-if, halfSum: each 32-bit side
                shifted right arithmetically, then the sum), the tag and
                old special as loaded
    flood       per sector, the other sectors of its two-sided lines with
                two sectors: the lines walked from the last to the first;
                for each, the back into the front's list then the front
                into the back's; without ML_SOUNDBLOCK appended up from
                the first entry (the bridge's `flood`, in that order),
                with it put down from the end (`flood_sb`, read upward)

`check_all` (level_check.py --derive) runs the comparison on every R
dump of tools/native/setupcap.py, and levelconv.py's check that no
sector sits at an address whose low word is 0 (bspSub's "no sector"),
which the converter from the WAD cannot make (the address is upstream's
zone's).
"""

import json
import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import llayout as LL, maplumps as ML  # noqa: E402

ST_HORIZONTAL, ST_VERTICAL, ST_POSITIVE, ST_NEGATIVE = 0, 1, 2, 3
ML_TWOSIDED, ML_SOUNDBLOCK = 4, 64
NO_INDEX = 0xFFFF


class DeriveError(Exception):
    pass


def s16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def s32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


def sx8(v: int) -> int:
    v &= 0xFF
    return v - 256 if v & 0x80 else v


# ---------------------------------------------------------------------------
# LINES (loadLineDefs)
# ---------------------------------------------------------------------------

def line_fields(ln: Sequence[int]) -> Dict[str, Any]:
    """One line of the game's form (maplumps' Line) as loadLineDefs makes
    it."""
    v1x, v1y, v2x, v2y, s0, s1, flags, special, tag = ln
    dx = s16(v2x - v1x)
    dy = s16(v2y - v1y)
    # v1.y - v2.y < 0: upstream's 16-bit subtraction with the overflow
    # flipped (bvc/eor #$8000) is the true signed compare
    if v1y < v2y:
        top, bottom = v2y, v1y
    else:
        top, bottom = v1y, v2y
    if v1x < v2x:
        left, right = v1x, v2x
    else:
        left, right = v2x, v1x
    if dx == 0:
        slope = ST_VERTICAL
    elif dy == 0:
        slope = ST_HORIZONTAL
    elif (dy < 0) != (dx < 0):         # the sign of dy ^ dx
        slope = ST_NEGATIVE
    else:
        slope = ST_POSITIVE
    return {'v1': [v1x, v1y], 'v2': [v2x, v2y], 'dx': dx, 'dy': dy,
            'sidenum': [s16(s0), s16(s1)], 'bbox': [top, bottom, left,
                                                    right],
            'tag': sx8(tag), 'special': sx8(special), 'flags': flags & 0xFF,
            'slopetype': slope}


def line_record(f: Dict[str, Any]) -> bytes:
    rec = bytearray(LL.LINE_SIZE)
    L = LL.LINE
    for key, value in (('V1X', f['v1'][0]), ('V1Y', f['v1'][1]),
                       ('V2X', f['v2'][0]), ('V2Y', f['v2'][1]),
                       ('DX', f['dx']), ('DY', f['dy']),
                       ('SIDE0', f['sidenum'][0]), ('SIDE1', f['sidenum'][1]),
                       ('TOP', f['bbox'][0]), ('BOTTOM', f['bbox'][1]),
                       ('LEFT', f['bbox'][2]), ('RIGHT', f['bbox'][3])):
        rec[L[key]:L[key] + 2] = struct.pack('<H', value & 0xFFFF)
    rec[L['TAG']] = f['tag'] & 0xFF
    rec[L['SPECIAL']] = f['special'] & 0xFF
    rec[L['FLAGS']] = f['flags']
    rec[L['SLOPE']] = f['slopetype']
    return bytes(rec)


# ---------------------------------------------------------------------------
# GROUP (groupLines, soundOrigins)
# ---------------------------------------------------------------------------

INT32_MIN, INT32_MAX = -0x80000000, 0x7FFFFFFF


def half(v: int) -> int:
    """A 32-bit value shifted right one bit, arithmetically."""
    return s32(v) >> 1


class Group:
    def __init__(self, game: ML.GameMap):
        lines = game.lines
        sides = game.sides
        nsec = len(game.lumps['SECTORS']) // 12
        segs = game.seg_list()
        self.subsector_sectors = []
        for count, first in game.subsector_list():
            sector = None
            for k in range(first, first + count):
                side = segs[k]['sidenum']
                if side != NO_INDEX:
                    sector = sides[side][5] & 0xFF
                    break
            if sector is None:
                raise DeriveError('a subsector with no side')
            self.subsector_sectors.append(sector)
        tables: List[List[int]] = [[] for _ in range(nsec)]
        for i, ln in enumerate(lines):
            front = sides[ln[4]][5] & 0xFF
            back = sides[ln[5]][5] & 0xFF if ln[5] != NO_INDEX else None
            tables[front].append(i)
            if back is not None and back != front:
                tables[back].append(i)
        self.tables = tables
        self.first = []
        at = 0
        for t in tables:
            self.first.append(at)
            at += len(t)
        self.entries = at
        self.soundorg = []
        for s in range(nsec):
            top, right = INT32_MIN, INT32_MIN
            bottom, left = INT32_MAX, INT32_MAX
            for i in tables[s]:
                ln = lines[i]
                for x, y in ((ln[0], ln[1]), (ln[2], ln[3])):
                    vx, vy = x << 16, y << 16
                    if vx < left:
                        left = vx
                    elif vx > right:
                        right = vx
                    if vy < bottom:
                        bottom = vy
                    elif vy > top:
                        top = vy
            self.soundorg.append([s32(half(right) + half(left)),
                                  s32(half(top) + half(bottom))])


# ---------------------------------------------------------------------------
# FLOOD (P_InitFlood)
# ---------------------------------------------------------------------------

class Flood:
    def __init__(self, game: ML.GameMap, group: Group):
        lines, sides = game.lines, game.sides
        nsec = len(group.tables)
        self.free: List[List[int]] = [[] for _ in range(nsec)]
        self.block: List[List[int]] = [[] for _ in range(nsec)]   # fill
        for i in range(len(lines) - 1, -1, -1):
            ln = lines[i]
            if ln[5] == NO_INDEX:
                continue
            front = sides[ln[4]][5] & 0xFF
            back = sides[ln[5]][5] & 0xFF
            if front == back or not ln[6] & ML_TWOSIDED:
                continue
            target = self.block if ln[6] & ML_SOUNDBLOCK else self.free
            target[front].append(back)
            target[back].append(front)
        self.rooms = [len(t) for t in group.tables]
        for s in range(nsec):
            if len(self.free[s]) + len(self.block[s]) > self.rooms[s]:
                raise DeriveError('sector %d: its flood entries pass its '
                                  'room' % s)

    def sequences(self, s: int) -> Tuple[List[int], List[int]]:
        """The bridge's `flood` and `flood_sb` of sector s."""
        return list(self.free[s]), list(reversed(self.block[s]))

    def layout(self) -> Tuple[bytes, bytes]:
        """FLIDX (8 bytes a sector: first, end of the free part, first of
        the block part, end) and the entries (a byte each), the rooms in
        sector order."""
        idx = bytearray()
        ent = bytearray()
        for s in range(len(self.rooms)):
            first = len(ent)
            room = self.rooms[s]
            region = bytearray(room)
            for k, other in enumerate(self.free[s]):
                region[k] = other
            for k, other in enumerate(self.block[s]):
                region[room - 1 - k] = other
            ent += region
            idx += struct.pack('<HHHH', first, first + len(self.free[s]),
                               first + room - len(self.block[s]),
                               first + room)
        return bytes(idx), bytes(ent)


# ---------------------------------------------------------------------------
# The check against ref816's canonical state
# ---------------------------------------------------------------------------

def ref_id(v: Any, kind: str) -> Optional[int]:
    if v is None:
        return None
    if hasattr(v, 'kind'):
        if v.kind != kind:
            raise DeriveError('a reference to %s, not %s' % (v.kind, kind))
        return v.id
    if isinstance(v, (list, tuple)) and len(v) == 3 and v[0] == kind:
        return v[1]
    raise DeriveError('not a reference: %r' % (v,))


def compare(game: ML.GameMap, state: Dict[str, Any]) -> Dict[str, int]:
    """The derivations against a canonical state of the same map after
    its setup: the counts compared; raises DeriveError on a difference."""
    objs = state['objects']
    out = {'lines': 0, 'subsectors': 0, 'sectors': 0, 'flood': 0}
    lines = objs['line']
    if len(lines) != len(game.lines):
        raise DeriveError('%d lines, the reference %d' % (len(game.lines),
                                                         len(lines)))
    for i, ln in enumerate(game.lines):
        mine = line_fields(ln)
        ref = lines[i]
        for k, v in mine.items():
            if list(ref[k]) != v if isinstance(v, list) else ref[k] != v:
                raise DeriveError('line %d %s: %r, the reference %r'
                                  % (i, k, v, ref[k]))
        out['lines'] += 1
    group = Group(game)
    subs = objs['subsector']
    for i, sector in enumerate(group.subsector_sectors):
        if ref_id(subs[i]['sector'], 'sector') != sector:
            raise DeriveError('subsector %d: sector %d, the reference %s'
                              % (i, sector, subs[i]['sector']))
        out['subsectors'] += 1
    secs = objs['sector']
    bufs = objs.get('linebuf', {})
    flood = Flood(game, group)
    raw = game.sector_list()
    for s in range(len(group.tables)):
        ref = secs[s]
        if ref['linecount'] != len(group.tables[s]):
            raise DeriveError('sector %d: %d lines, the reference %d'
                              % (s, len(group.tables[s]), ref['linecount']))
        first = ref_id(ref['lines'], 'linebuf') if group.tables[s] else None
        if group.tables[s]:
            if first != group.first[s]:
                raise DeriveError('sector %d: its table starts at %d, the '
                                  'reference\'s at %s' % (
                                      s, group.first[s], first))
            got = [ref_id(bufs[first + k]['line'], 'line')
                   for k in range(len(group.tables[s]))]
            if got != group.tables[s]:
                raise DeriveError('sector %d: lines %s, the reference %s'
                                  % (s, group.tables[s], got))
        if list(ref['soundorg']) != group.soundorg[s]:
            raise DeriveError('sector %d: sound origin %s, the reference '
                              '%s' % (s, group.soundorg[s],
                                      list(ref['soundorg'])))
        if ref['tag'] != raw[s][6] or ref['oldspecial'] != raw[s][5]:
            raise DeriveError('sector %d: tag or old special' % s)
        fl, fsb = flood.sequences(s)
        rfl = [ref_id(x, 'sector') for x in ref['flood']]
        rfsb = [ref_id(x, 'sector') for x in ref['flood_sb']]
        if rfl != fl or rfsb != fsb:
            raise DeriveError('sector %d: flood %s/%s, the reference %s/%s'
                              % (s, fl, fsb, rfl, rfsb))
        out['sectors'] += 1
        out['flood'] += len(fl) + len(fsb)
    if len(bufs) != group.entries:
        raise DeriveError('%d line table entries, the reference %d'
                          % (group.entries, len(bufs)))
    return out


def check_all(maps: Sequence[int]) -> Dict[str, Any]:
    from bridge import upstream
    from native import levelconv as LC, setupcap, umodel as U
    gd = U.game_data()
    win = U.window(gd.rel)
    games: Dict[int, ML.GameMap] = {}
    report: Dict[str, Any] = {'format': 'level-check-derive 1',
                              'setups': {}, 'failures': []}
    for d in setupcap.setup_dirs():
        meta = json.loads((d / 'setup.json').read_text())
        m = meta['gamemap']
        if m not in maps:
            continue
        if m not in games:
            rel_sectors = U.release_lump(gd.rel, m, win, gd.rel.index(
                'E1M%d' % m) + 7)
            numbers = ML.flat_numbers(ML.map_lumps(gd.wad, m)['SECTORS'],
                                      rel_sectors)
            games[m] = ML.GameMap(gd.wad, m, gd.tex_names, numbers)
        memory = LC.load_memory(d / 'r.ram.z')
        reader = upstream.Reader(memory)
        state = reader.read()
        try:
            if reader.problems:
                raise DeriveError('the bridge: %s' % reader.problems[:3])
            res = dict(compare(games[m], state), ok=True)
            # levelconv.py's CN_LSEC check, which a converter from the
            # WAD cannot make (the sectors' zone address): no sector at an
            # address whose low word is 0 (bspSub's "no sector")
            base = memory.uint(U.symbols().address('_g_sectors'), 3)
            for i in range(res['sectors']):
                if (base + LC.SIZEOF_SEC * i) & 0xFFFF == 0:
                    raise DeriveError('sector %d at $%06X: bspSub would '
                                      'take it for no sector' % (
                                          i, base + LC.SIZEOF_SEC * i))
            res['sector_base'] = '$%06X' % base
        except DeriveError as error:
            res = {'ok': False, 'error': str(error)}
            report['failures'].append('%s: %s' % (d.name, error))
        report['setups'][d.name] = dict(res, gamemap=m)
        print('%s E1M%d: %s' % (d.name, m, 'ok %s' % {
            k: v for k, v in res.items() if k != 'ok'} if res['ok'] else
            'FAILED: ' + res['error']), flush=True)
    return report
