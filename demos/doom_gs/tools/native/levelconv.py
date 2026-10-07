#!/usr/bin/env python3
"""The native level format of the renderer, format "render-level 3"
(docs/RENDER.md and docs/RENDER-MASKED.md): the shared pieces of the
level conversion that wadconv.py and lstore.py make from the WAD.

  Image          A2VMIMG1 records (level.img, wtables.img, mtables.img)
  Banks          RamWorks banks being filled
  Level          a converted level: info, banks, W tables, texture map,
                 TXMP, FUZZDARK
  sector_record, side_record
                 the render parts of a sector and a side (rlayout.py)
  native_vertices, bsp_depth, pic_byte
  sprite_frames, weapon_sprites, wb_make
                 the frames the states use, the psprites' sprites, and
                 wbMake's weapon profiles (r_sprite65.s:1009-1178)
"""

import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from bridge import linkmap as blink  # noqa: E402
from native import rlayout as R, umodel  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
RENDER = BUILD / 'native' / 'render'
LEVELS = RENDER / 'levels'
SOURCES = LEVELS / 'src'
FORMAT = 'render-level 3'

SLOT = 128
SKY_COLUMNS = 256
BSP_DEPTH_MAX = R.NODEF_DEPTH
ML_DONTPEGTOP, ML_DONTPEGBOTTOM = 8, 16
TXFLAT_INDEX = R.TXFLAT             # 256 bytes: bitmap slot of texture t
TXFLAT_MAPS = R.TXFLAT + 0x100      # 32 bytes a bitmap
TXFLAT_SLOTS = (R.TXFLAT_END - TXFLAT_MAPS) // 32
# the sprite data (offsets.inc, info.inc, memmap.inc)
NUMSTATES, STATE_SIZE = 314, 16
TAIL = 128                      # the bytes after a lump a record can read
# the weapons' profiles (docs/RENDER-MASKED.md; r_sprite65.s:737-758,
# :884-1178; offsets.inc: weaponinfo_t, state_t; info.inc STATE_SIZE)
OFS_ST_NEXTSTATE = 10
NUMWEAPONS, SIZEOF_WI = 9, 12
OFS_WI_STATES = (2, 4, 6, 8, 10)        # up, down, ready, attack, flash
WP_ARENAS = ((0xD000, 0xE400), (0xED00, 0xFF00))
# The conversion's revision within format "render-level 3"
REVISION = 1


class ConvError(Exception):
    pass


class Image:
    """A2VMIMG1 records (tools/a2vm/README.md, "Running it")."""

    def __init__(self):
        self.records: List[Tuple[int, int, int, bytes]] = []

    def add(self, kind: int, bank: int, address: int, data: bytes) -> None:
        for at in range(0, len(data), 0x8000):
            self.records.append((kind, bank, address + at,
                                 bytes(data[at:at + 0x8000])))

    def bytes(self) -> bytes:
        out = bytearray(b'A2VMIMG1')
        for kind, bank, address, data in self.records:
            out += struct.pack('<BBHI', kind, bank, address, len(data))
            out += data
        return bytes(out)

    @staticmethod
    def parse(data: bytes) -> List[Tuple[int, int, int, bytes]]:
        if data[:8] != b'A2VMIMG1':
            raise ValueError('not an A2VMIMG1 image')
        out, at = [], 8
        while at < len(data):
            kind, bank, address, length = struct.unpack_from('<BBHI', data,
                                                             at)
            at += 8
            out.append((kind, bank, address, data[at:at + length]))
            at += length
        return out


class Banks:
    """RamWorks banks being filled (a bytearray and a used map each)."""

    def __init__(self):
        self.data: Dict[int, bytearray] = {}
        self.used: Dict[int, bytearray] = {}

    def put(self, bank: int, address: int, data: bytes) -> None:
        if not (R.BANK_ROOM[0] <= address and
                address + len(data) <= R.BANK_ROOM[1]):
            raise ConvError('bank %d $%04X+%d is outside $0200-$BFFF'
                            % (bank, address, len(data)))
        mem = self.data.setdefault(bank, bytearray(0x10000))
        used = self.used.setdefault(bank, bytearray(0x10000))
        mem[address:address + len(data)] = data
        used[address:address + len(data)] = b'\x01' * len(data)

    def get(self, bank: int, address: int, length: int) -> bytes:
        return bytes(self.data[bank][address:address + length])

    def runs(self, bank: int) -> List[Tuple[int, bytes]]:
        used, mem = self.used[bank], self.data[bank]
        out, at = [], 0
        while at < 0x10000:
            if used[at]:
                end = at
                while end < 0x10000 and used[end]:
                    end += 1
                out.append((at, bytes(mem[at:end])))
                at = end
            else:
                at += 1
        return out


def ref_index(ref: Any, kind: str) -> int:
    if isinstance(ref, (list, tuple)) and len(ref) == 3 and ref[0] == kind:
        return ref[1]
    if hasattr(ref, 'kind') and ref.kind == kind:
        return ref.id
    raise ConvError('not a reference to a %s: %r' % (kind, ref))


# ---------------------------------------------------------------------------
# The conversion
# ---------------------------------------------------------------------------

class Level(NamedTuple):
    info: Dict[str, Any]
    banks: Banks
    wtables: Dict[int, bytes]           # W address -> bytes
    texmap: Dict[str, Any]
    mtables: Dict[int, bytes] = {}      # the masked image's W tables
    fuzzdark: bytes = b''               # FUZZ_DARKEN (the replay)


def native_vertices(segs: Sequence[Dict[str, Any]]) -> Tuple[
        List[Tuple[int, int]], List[Tuple[int, int]]]:
    """The distinct seg end points in order of first appearance, and each
    seg's (v1, v2) numbers among them."""
    points: Dict[Tuple[int, int], int] = {}
    ends = []
    for s in segs:
        pair = []
        for key in ('v1', 'v2'):
            p = (s[key][0], s[key][1])
            if p not in points:
                points[p] = len(points)
            pair.append(points[p])
        ends.append(tuple(pair))
    return list(points), ends


def bsp_depth(nodes: Sequence[Dict[str, Any]], root: int) -> int:
    """The longest chain of nodes from the root (a subsector adds none)."""
    depth = {}

    def walk(n: int) -> int:
        if n & 0x8000:
            return 0
        if n in depth:
            return depth[n]
        c0, c1 = nodes[n]['children']
        depth[n] = 1 + max(walk(c0 & 0xFFFF), walk(c1 & 0xFFFF))
        return depth[n]
    sys.setrecursionlimit(10000)
    return walk(root & 0xFFFF) if nodes else 0


def pack16(v: int) -> bytes:
    return (v & 0xFFFF).to_bytes(2, 'little')


SKY_PIC = 0xFE                  # a pic of -2 (skyflatnum's "flat colour")


def pic_byte(value: int, what: str, ceiling: bool) -> int:
    """A floor or ceiling pic as a signed byte: 0-127, or -2 (the sky
    flat of r_data65.s, $FE) for a ceiling only. A floor of -2 would make
    bspSub read 2 bytes before FLATCM, which the native W does not hold
    (flatColor: FLATCM + BS_CM + pic)."""
    if 0 <= value < 128:
        return value
    if value == -2 and ceiling:
        return SKY_PIC
    raise ConvError('%s of %d: the byte pics hold 0-127 and a ceiling '
                    'of -2' % (what, value))


def sector_record(s: Dict[str, Any], i: int) -> bytearray:
    """The render part of sector i (rlayout.SEC), from its canonical
    fields."""
    if not 0 <= s['lightlevel'] <= 255:
        raise ConvError('sector %d: light level %d' % (i, s['lightlevel']))
    rec = bytearray(R.SEC_SIZE)
    rec[0:4] = (s['floorheight'] & 0xFFFFFFFF).to_bytes(4, 'little')
    rec[4:8] = (s['ceilingheight'] & 0xFFFFFFFF).to_bytes(4, 'little')
    rec[R.SEC['FPIC']] = pic_byte(s['floorpic'], 'sector %d floor' % i,
                                  False)
    rec[R.SEC['CPIC']] = pic_byte(s['ceilingpic'], 'sector %d ceiling' % i,
                                  True)
    rec[R.SEC['LIGHT']] = s['lightlevel']
    rec[R.SEC['VALID']:R.SEC['VALID'] + 2] = pack16(s['validcount'])
    # the thing list's head (none in the level itself)
    rec[R.SEC['THINGS']:R.SEC['THINGS'] + 2] = pack16(
        s.get('things', R.NO_THING))
    return rec


def side_record(s: Dict[str, Any], i: int) -> bytearray:
    """The render part of side i; its sector (byte 7, "render-level 3")
    when the canonical side has one (a reference to a sector)."""
    for key in ('toptexture', 'bottomtexture', 'midtexture'):
        if not 0 <= s[key] <= 255:
            raise ConvError('side %d: %s %d' % (i, key, s[key]))
    rec = bytearray(R.SIDE_SIZE)
    rec[0:2] = pack16(s['textureoffset'])
    rec[2:4] = pack16(s['rowoffset'])
    rec[R.SIDE['TOP']] = s['toptexture']
    rec[R.SIDE['BOTTOM']] = s['bottomtexture']
    rec[R.SIDE['MID']] = s['midtexture']
    if 'sector' in s:
        sector = ref_index(s['sector'], 'sector')
        if not 0 <= sector < 255:
            raise ConvError('side %d: sector %d' % (i, sector))
        rec[R.SIDE['SECTOR']] = sector
    return rec


# ---------------------------------------------------------------------------
# The sprite frames (docs/RENDER-MASKED.md)
# ---------------------------------------------------------------------------

def sprite_frames(m: umodel.Memory, sym: blink.Symbols) -> List[int]:
    """The frames of each sprite that the states use (boundInit's rule,
    r_thing65.s:887-913; rtables.py writes the same SFIRST)."""
    states = sym.address('states')
    count = [0] * R.NUMSPRITES
    for i in range(NUMSTATES):
        s = m.u16(states + STATE_SIZE * i)
        f = m.u16(states + STATE_SIZE * i + 2)
        if s >= R.NUMSPRITES:
            raise ConvError('state %d has sprite %d' % (i, s))
        count[s] = max(count[s], (f & 0x7FFF) + 1)
    return count


# ---------------------------------------------------------------------------
# The weapons' profiles (docs/RENDER-MASKED.md)
# ---------------------------------------------------------------------------

def weapon_sprites(m: umodel.Memory, sym: blink.Symbols) -> List[int]:
    """The sprites the psprites can show: those of the states reachable
    from weaponinfo's up, down, ready, attack and flash states through
    their next states (p_pspr65.s:1229-1250). A flash state that is chosen
    by offset (the chaingun's CHAINFLASH1 + 1, p_pspr65.s:1153) has its
    base's sprite."""
    states = sym.address('states')
    wi = sym.address('weaponinfo')
    todo = []
    for w in range(NUMWEAPONS):
        for off in OFS_WI_STATES:
            todo.append(m.u16(wi + SIZEOF_WI * w + off))
    seen = set()
    while todo:
        st = todo.pop()
        if st in seen or not 0 < st < NUMSTATES:
            continue
        seen.add(st)
        todo.append(m.u16(states + STATE_SIZE * st + OFS_ST_NEXTSTATE))
    return sorted({m.u16(states + STATE_SIZE * st) for st in seen})


def wb_make(read, base: int, limit: int) -> Tuple[int, Dict[int, int]]:
    """wbMake (r_sprite65.s:1009-1178) of the patch read(offset, n) at
    `base`, below `limit`: (0, the bytes written: address -> byte) when
    made, (1, {}) when there is no room, (2, {}) when the patch does not fit
    the profile (a width of 0 or over 320, posts that overlap or end after
    row 254 of the patch, 15 posts in a column). Every comparison is
    upstream's, the strict ones included."""
    out: Dict[int, int] = {}

    def w16(at: int, v: int) -> None:
        out[at] = v & 0xFF
        out[at + 1] = (v >> 8) & 0xFF

    def r16(off: int) -> int:
        b = read(off & 0xFFFF, 2)
        return b[0] | b[1] << 8
    width = r16(0)
    if width == 0 or width >= 321:
        return 2, {}
    free = base + 2 * width + 16
    if free > 0xFFFF or free >= limit:
        return 1, {}
    neven, nodd = (width + 1) >> 1, width >> 1
    w16(base + R.WPH['NEVEN'], neven)
    w16(base + R.WPH['NODD'], nodd)
    tabs = (base + 16, base + 16 + 2 * neven)
    w16(base + R.WPH['TEVEN'], tabs[0])
    w16(base + R.WPH['TODD'], tabs[1])
    w16(base + R.WPH['EMPTY'], 0)
    mina = 0xFFFF
    for c in range(width):
        ent = tabs[c & 1] + (c & 0xFFFE)
        y = r16(8 + 4 * c)
        pb = 0
        rsa = 0
        posts = []
        while True:
            tl = r16(y)
            if tl & 0xFF == 0xFF:
                break
            a = (tl & 0xFF) + 1
            off = y
            length = tl >> 8
            y = (y + length + 4) & 0xFFFF
            if length == 0:
                continue                # not drawn
            b = length + a
            if b >= 255 or a < pb:
                return 2, {}
            if a != pb:
                rsa = a                 # a new run (else it touches)
            mina = min(mina, a)
            posts.append((a + 1, b + 1, rsa, (off + 3) & 0xFFFF))
            pb = b
            if len(posts) == R.WP_MAXPOSTS + 1:
                return 2, {}
        if not posts:
            w16(ent, base + R.WPH['EMPTY'])
            continue
        if free + R.WP_POST * len(posts) >= limit:
            return 1, {}
        w16(ent, free)
        at = free
        for a1, b1, run, texels in reversed(posts):
            out[at], out[at + 1], out[at + 2] = a1, b1, run & 0xFF
            w16(at + 3, texels)
            at += R.WP_POST
        out[at] = 0
        free = at + 1
    w16(base + R.WPH['MINA'], mina)
    w16(base + R.WPH['WIDTH'], width)
    out['end'] = free          # type: ignore[index]
    return 0, out
