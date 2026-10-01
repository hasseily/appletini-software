#!/usr/bin/env python3
"""The level converter of the native renderer (milestone 7,
docs/RENDER.md sections 1.3, 1.4 and 1.10; milestone 8,
docs/RENDER-MASKED.md 1.3-1.5 and 1.11): a reference state holding a
level becomes the native level, format "render-level 3" ("render-level
2" with the side's sector in byte 7 of its record: milestone 9,
docs/LEVELS.md 1.3; "render-level 2" was "render-level 1" and the sprite
part).

Usage:  python3 tools/native/levelconv.py SOURCE... [--out DIR] [--check]
        python3 tools/native/levelconv.py --all [--check]

A SOURCE is a level source of tools/native/rendercap.py
(build/native/render/levels/src/NAME.ram.z: all RAM at an R_FillStamps),
a ref816 memory image (a bridge dump's entry.img), or a --dump-ram file.
--all converts every level source of rendercap.py and, as the second
dump of each level load, the bridge's tour dumps (build/bridge/dumps/
tour-NN/entry.img) of the same maps.

Upstream's objects are read with the bridge (tools/bridge/upstream.py
Reader: sectors, lines, sides, subsectors, segs, nodes by identity), its
renderer tables by symbol (COLDIR at MM_COLDIR, the column tables, FLATCM,
textureheight, texturetranslation, skypatchnum's lump, skywidthmask,
skyflatnum, numnodes, the seg vertex numbers MM_SEGVTX), never by a
guessed address. Output, in build/native/render/levels/MAP-KEY/ (KEY: the
first 16 hex digits of the SHA-256 of every source range):

    level.img     A2VMIMG1 records of the RamWorks banks: LVSEG (segs),
                  LVMAP (nodes, subsectors, the vertex cache with every
                  stamp 0, sectors, sides, the patchless bitmaps), the
                  texel banks (one 128-byte slot per texture column, the
                  sky's 256 slots)
    wtables.img   the per-level tables of the render window W: FLATCM,
                  TXBANK, TXLO, TXHI, TXWM, TXHT
    level.json    format "render-level 1": the map, counts, each array's
                  bank, base and stride, each texture's bank, base,
                  widthmask and height, the sky's slots, skyflatnum,
                  skywidthmask, the converted texture numbers, the BSP
                  depth, the banks used, upstream's vertex number of each
                  native vertex, the open-ended slots, the SHA-256 of
                  every source range, and the checks' results
    texmap.json   each slot's upstream source address
    sectors-sides.json
                  a bridge-port-layout manifest of the sectors' and
                  sides' render fields (records with a stride: the
                  bridge's `stride`), which bridge.py from-port reads

and, milestone 8 (RENDER-MASKED.md 1.3, 1.4, 1.11):

    level.img     also the patch store (banks SPR_FIRST..: each patch lump
                  the level's sprites use and the first patch of each
                  texture a masked mid texture can show, upstream's bytes
                  whole, each followed by the 128 bytes that follow it in
                  the reference's memory; no lump crosses a bank), and in
                  bank SPRT the patch headers (PHDR: width, leftoffset,
                  topoffset, the store bank and address, upstream's lump;
                  index 0 is upstream's placeholder, a patch of width 0)
                  and the sprite frames (SPRFR: rotate, flipmask, the store
                  index of each rotation's lump, a flag for a frame that
                  is not one: SFIRST[s] + f, the frames the states use)
    mtables.img   the masked image's per-level table: TXMP, the store index
                  of each texture's first patch ($FFFF: none)
    patchmap.json each stored lump's store range and upstream address
                  (rcanon.py maps a record's texels back through it)
    level.json    also the patch store's entries, the placeholder, the
                  frames per sprite and the frames that are not, TXMP's
                  textures, and --overrun's measure

Checks, each a failure (the tool exits 1): every count within its native
limit; no sector at an address whose low word is 0 (bspSub's "no sector"
of CN_LSEC); the native level decoded back through rlayout.py equals
upstream's canonical objects in every rendered field; every made texture
column has its slot and every slot's 128 bytes equal the reference's RAM
at the column's texel pointer (read again from COLDIR, not from the
texture map); skypatchnum names a lump of the WAD directory; with a
second dump of the same level load, the static fields equal; milestone
8: the WAD directory has one placeholder; every sprite frame's lumps
resolve to a store index or the placeholder (a frame whose lump numbers
leave the directory is flagged, not converted); each stored lump's bytes
and tail equal the reference's RAM at its address (read back from the
banks); no lump crosses a store bank; the first patch of every texture a
masked mid texture can show (the closure through switchlist and the
slime frames of animated_texture_basepic) is stored, or listed with TXMP
$FFFF when upstream has not loaded the texture or its lump is not
resident; the counts fit the native tables.

    python3 tools/native/levelconv.py --overrun

measures, over the records of every captured frame (their lists at
R_DrawLists, P4, and the early flushes' P2) that read a stored lump, how
far a record's texels reach past its post's last texel and past its
lump's end (an upper bound from its rows and step: RENDER-MASKED.md 1.3),
and writes it into each level's level.json and levels/overrun.json.
"""

import argparse
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from bridge import linkmap as blink, memory as bmem, upstream  # noqa: E402
from native import rlayout as R  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
RENDER = BUILD / 'native' / 'render'
LEVELS = RENDER / 'levels'
SOURCES = LEVELS / 'src'
BRIDGE_DUMPS = BUILD / 'bridge' / 'dumps'
FORMAT = 'render-level 3'

MM_COLDIR = 0x250000
MM_SEGVTX = 0x240000
MM_WAD_BANK = 0x10
FI_SIZE_BYTES = 16
OVERREAD = 128
SLOT = 128
SKY_COLUMNS = 256
SIZEOF_SEC = 58
BSP_DEPTH_MAX = R.NODEF_DEPTH
ML_DONTPEGTOP, ML_DONTPEGBOTTOM, ML_MAPPED = 8, 16, 256
TXFLAT_INDEX = R.TXFLAT             # 256 bytes: bitmap slot of texture t
TXFLAT_MAPS = R.TXFLAT + 0x100      # 32 bytes a bitmap
TXFLAT_SLOTS = (R.TXFLAT_END - TXFLAT_MAPS) // 32
# milestone 8: the sprite data (offsets.inc, info.inc, memmap.inc)
FI_ENTRY = 16                   # filelump_t: filepos (4), size (4), name
OFS_SF_FLIPMASK, OFS_SF_ROTATE, SIZEOF_SF = 16, 17, 19
OFS_TEX_PATCHES, OFS_TP_PATCHNUM = 8, 4
OFS_TEX_WIDTHMASK = 0
NUMSTATES, STATE_SIZE = 314, 16
NUMSWITCHES2 = 38               # p_switch65.s NUMSW2
TAIL = 128                      # the bytes after a lump a record can read
# stage C: the weapons' profiles (RENDER-MASKED.md 1.5; r_sprite65.s:737-758,
# :884-1178; offsets.inc: weaponinfo_t, state_t; info.inc STATE_SIZE)
OFS_ST_NEXTSTATE = 10
NUMWEAPONS, SIZEOF_WI = 9, 12
OFS_WI_STATES = (2, 4, 6, 8, 10)        # up, down, ready, attack, flash
MM_WPROF = 0x0AC800
WP_NONE_ADDR = 0xC84C                   # MM_WPROF + $4C: a profile of width 0
WP_ARENAS = ((0xD000, 0xE400), (0xED00, 0xFF00))
# the spectre fuzz table, per level (i_viigs65.s FUZZ_DARKEN): the replay's
# FUZZDARK (MEMORY_MAP.md 5)
MM_FUZZ_DARKEN = 0x01A000
# The conversion's revision within format "render-level 3": a level of an
# older one is converted again (framestate.level_of)
REVISION = 1


class ConvError(Exception):
    pass


def symbols() -> blink.Symbols:
    return blink.Symbols()


def load_memory(path: Path) -> bmem.Memory:
    """A level source: rendercap's .ram.z, a ref816 image or a RAM dump."""
    path = Path(path)
    if path.name.endswith('.ram.z'):
        data = zlib.decompress(path.read_bytes())
        if len(data) != 130 * 0x10000:
            raise ConvError('%s is not a whole RAM' % path)
        m = bmem.Memory()
        for i in range(130):
            bank = i if i < 0x80 else 0xE0 + i - 0x80
            m.banks[bank] = bytearray(data[i * 0x10000:(i + 1) * 0x10000])
        return m
    head = path.read_bytes()[:8]
    if head == b'REF816I1':
        return bmem.Memory.from_image(path)
    return bmem.Memory.from_dump(path)


def s16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


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


# ---------------------------------------------------------------------------
# Upstream's level, by symbol
# ---------------------------------------------------------------------------

class Upstream:
    def __init__(self, memory: bmem.Memory, sym: blink.Symbols):
        self.m = memory
        self.sym = sym
        reader = upstream.Reader(memory)
        self.state = reader.read()
        if reader.problems:
            raise ConvError('the bridge reader: %s' % '; '.join(
                reader.problems[:5]))
        self.objects = self.state['objects']

    def g(self, name: str, size: int = 2) -> int:
        return self.m.uint(self.sym.address(name), size)

    def ptr(self, name: str) -> int:
        return self.m.uint(self.sym.address(name), 3)

    def count(self, kind: str) -> int:
        return len(self.objects.get(kind, {}))

    def ordered(self, kind: str) -> List[Dict[str, Any]]:
        objs = self.objects.get(kind, {})
        if sorted(objs) != list(range(len(objs))):
            raise ConvError('%s identities are not 0 to n - 1' % kind)
        return [objs[i] for i in range(len(objs))]


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
    manifest: Dict[str, Any]
    mtables: Dict[int, bytes] = {}      # the masked image's W tables
    patchmap: Dict[str, Any] = {}
    fuzzdark: bytes = b''               # stage C: FUZZ_DARKEN (the replay)


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


def pic_value(byte: int) -> int:
    return -2 if byte == SKY_PIC else byte


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
    # milestone 8: the thing list's head (framestate.py's; none in the
    # level itself)
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


def convert(memory: bmem.Memory, sym: blink.Symbols,
            source_name: str = '') -> Level:
    up = Upstream(memory, sym)
    m = memory
    checks: List[str] = []
    ranges: List[Dict[str, Any]] = []

    def source(what: str, address: int, length: int) -> None:
        ranges.append({'what': what, 'address': address, 'length': length,
                       'sha256': hashlib.sha256(m.read(address, length))
                       .hexdigest()})

    sectors = up.ordered('sector')
    sides = up.ordered('side')
    lines = up.ordered('line')
    subs = up.ordered('subsector')
    segs = up.ordered('seg')
    nodes = up.ordered('node')
    numnodes = up.g('numnodes')
    gamemap = up.g('_g_gamemap')
    if numnodes != len(nodes):
        raise ConvError('numnodes %d, %d nodes' % (numnodes, len(nodes)))

    # -- limits
    limits = [('sector', len(sectors), R.SECTORS.capacity),
              ('side', len(sides), R.SIDES.capacity),
              ('line', len(lines), R.LNMAP_LINES),
              ('subsector', len(subs), R.SUBS.capacity),
              ('seg', len(segs), R.SEGS.capacity),
              ('node', len(nodes), R.NODES.capacity)]
    points, ends = native_vertices(segs)
    limits.append(('vertex', len(points), R.VTX_CAP))
    for what, n, cap in limits:
        if n > cap:
            raise ConvError('%d %ss: the native layout holds %d'
                            % (n, what, cap))
    depth = bsp_depth(nodes, (numnodes - 1) & 0xFFFF) if nodes else 0
    if depth > BSP_DEPTH_MAX:
        raise ConvError('BSP depth %d: the node frames hold %d'
                        % (depth, BSP_DEPTH_MAX))
    checks.append('counts within the native limits')

    # -- CN_LSEC: bspSub's "no sector" is a pointer whose low word is 0
    sec_base = up.ptr('_g_sectors')
    for i in range(len(sectors)):
        if (sec_base + SIZEOF_SEC * i) & 0xFFFF == 0:
            raise ConvError('sector %d at $%06X: bspSub would take it for '
                            'no sector' % (i, sec_base + SIZEOF_SEC * i))
    checks.append('no sector address has a low word of 0')

    # -- upstream's vertex numbers of the seg ends (MM_SEGVTX)
    up_vertex: Dict[int, int] = {}
    for i, (n1, n2) in enumerate(ends):
        u1 = m.u16(MM_SEGVTX + 4 * i)
        u2 = m.u16(MM_SEGVTX + 4 * i + 2)
        for native, u in ((n1, u1), (n2, u2)):
            if up_vertex.setdefault(native, u) != u:
                raise ConvError('vertex %d has two upstream numbers' % native)
    if len(set(up_vertex.values())) != len(up_vertex):
        raise ConvError('two native vertices share an upstream number')
    source('MM_SEGVTX', MM_SEGVTX, 4 * len(segs))
    checks.append('upstream numbers the seg ends one to one')

    banks = Banks()
    # -- segs (LVSEG)
    data = bytearray()
    for i, s in enumerate(segs):
        line = lines[s['linenum']]
        pegs = line['flags'] & (ML_DONTPEGTOP | ML_DONTPEGBOTTOM)
        back = s['backsectornum']
        rec = bytearray(R.SEG_SIZE)
        for key, value in (('V1X', s['v1'][0]), ('V1Y', s['v1'][1]),
                           ('V2X', s['v2'][0]), ('V2Y', s['v2'][1]),
                           ('OFFSET', s['offset']), ('ANGLE', s['angle']),
                           ('SIDE', s['sidenum']), ('LINE', s['linenum']),
                           ('V1N', ends[i][0]), ('V2N', ends[i][1])):
            rec[R.SEG[key]:R.SEG[key] + 2] = pack16(value)
        rec[R.SEG['FRONT']] = s['frontsectornum']
        rec[R.SEG['BACK']] = back
        rec[R.SEG['PEGS']] = pegs
        data += rec
    banks.put(R.LVSEG, R.SEGS.base, bytes(data))
    source('segs', up.ptr('_g_segs'), 18 * len(segs))
    # the lines' peg flags the segs take (milestone 8: a level source with
    # other flags is another level; the rest of a line record changes in
    # play, ML_MAPPED and the validcounts, and is not converted)
    ranges.append({'what': 'line pegs', 'address': up.ptr('_g_lines'),
                   'length': len(lines), 'sha256': hashlib.sha256(bytes(
                       ln['flags'] & (ML_DONTPEGTOP | ML_DONTPEGBOTTOM)
                       for ln in lines)).hexdigest()})

    # -- nodes, subsectors (LVMAP)
    data = bytearray()
    for n in nodes:
        rec = bytearray(R.NODE_SIZE)
        vals = [n['x'], n['y'], n['dx'], n['dy']] + list(n['bbox']) + \
            list(n['children'])
        for k, v in enumerate(vals):
            rec[2 * k:2 * k + 2] = pack16(v)
        data += rec
    if data:
        banks.put(R.LVMAP, R.NODES.base, bytes(data))
    source('nodes', up.ptr('nodes'), 28 * len(nodes))
    data = bytearray()
    for s in subs:
        sector = ref_index(s['sector'], 'sector')
        if s['numlines'] > 255:
            raise ConvError('a subsector of %d segs' % s['numlines'])
        data += bytes([sector, s['numlines']]) + pack16(s['firstline'])
    banks.put(R.LVMAP, R.SUBS.base, bytes(data))
    source('subsectors', up.ptr('_g_subsectors'), 8 * len(subs))
    # the vertex cache: every stamp 0 (framestate.py injects upstream's)
    nv = len(points)
    for plane in (R.VAL, R.VAH, R.VAS):
        banks.put(R.LVMAP, plane, bytes(nv))

    # -- sectors and sides: the render parts
    data = bytearray()
    for i, s in enumerate(sectors):
        rec = sector_record(s, i)
        data += rec
    banks.put(R.LVMAP, R.SECTORS.base, bytes(data))
    data = bytearray()
    for i, s in enumerate(sides):
        data += side_record(s, i)
    banks.put(R.LVMAP, R.SIDES.base, bytes(data))

    # -- textures: one slot per column (RENDER.md 1.4)
    numtextures = up.g('numtextures')
    if numtextures > 256:
        raise ConvError('%d textures: the byte indexes hold 256'
                        % numtextures)
    th_base = up.ptr('textureheight')
    heights = [m.u16(th_base + 2 * t) for t in range(numtextures)]
    source('textureheight', th_base, 2 * numtextures)
    # TXHT holds every texture's height, made or not (0 until upstream
    # makes it): R_StoreWallRange reads the height of a side's texture
    # and of its translation (rowMod, midTex), made or not
    bad = [t for t, h in enumerate(heights) if not 0 <= h < 256]
    if bad:
        raise ConvError('texture %d has height %d: TXHT holds bytes'
                        % (bad[0], heights[bad[0]]))
    source('COLDIR', MM_COLDIR, 4 * 256)
    colmem = up.ptr('colmem')
    made = []
    for t in range(256):
        entry = m.read(MM_COLDIR + 4 * t, 4)
        if entry[2] == 0 and entry[3] == 0:
            continue
        if t >= numtextures:
            raise ConvError('COLDIR has texture %d of %d' % (t, numtextures))
        made.append(t)
    txbank, txlo, txhi = bytearray(256), bytearray(256), bytearray(256)
    txwm, txht = bytearray(256), bytearray(256)
    txht[:numtextures] = bytes(heights)
    flat_index = bytearray(b'\xff' * 256)
    flat_maps = bytearray()
    textures = {}
    slots: Dict[str, int] = {}
    open_ended = []
    next_bank, next_at = R.TEX_FIRST, R.BANK_ROOM[0]

    def place(size: int) -> Tuple[int, int]:
        nonlocal next_bank, next_at
        if size > R.BANK_ROOM[1] - R.BANK_ROOM[0]:
            raise ConvError('%d bytes do not fit a bank' % size)
        if next_at + size > R.BANK_ROOM[1]:
            next_bank += 1
            next_at = R.BANK_ROOM[0]
        if next_bank > R.TEX_LAST:
            raise ConvError('the texels need more than banks %d-%d'
                            % (R.TEX_FIRST, R.TEX_LAST))
        at = next_at
        next_at += size
        return next_bank, at

    def slot_source(ptr: int, where: str) -> bytes:
        slots[where] = ptr
        if ptr < colmem < ptr + SLOT:
            open_ended.append({'slot': where, 'source': ptr,
                               'past_end': ptr + SLOT - colmem})
        return m.read(ptr, SLOT)

    for t in made:
        entry = m.read(MM_COLDIR + 4 * t, 4)
        table = entry[0] | entry[1] << 8 | entry[2] << 16
        wm = entry[3]
        h = heights[t]
        if not 0 < h < 256:
            raise ConvError('texture %d has height %d' % (t, h))
        source('column table %d' % t, table, 4 * (wm + 1))
        bank, base = place(SLOT * (wm + 1))
        flat_cols = []
        for c in range(wm + 1):
            e = m.read(table + 4 * c, 4)
            ptr = e[0] | e[1] << 8 | e[2] << 16
            if e[3]:
                flat_cols.append(c)
                banks.put(bank, base + SLOT * c, bytes(SLOT))
                continue
            banks.put(bank, base + SLOT * c,
                      slot_source(ptr, '%d:%d' % (t, c)))
        txbank[t], txlo[t], txhi[t] = bank, base & 0xFF, base >> 8
        txwm[t], txht[t] = wm, h
        if flat_cols:
            k = len(flat_maps) // 32
            if k >= TXFLAT_SLOTS:
                raise ConvError('more than %d textures with patchless '
                                'columns' % TXFLAT_SLOTS)
            bitmap = bytearray(32)
            for c in flat_cols:
                bitmap[c >> 3] |= 1 << (c & 7)
            flat_maps += bitmap
            flat_index[t] = k
            txbank[t] |= 0x80
        textures[str(t)] = {'bank': bank, 'base': base, 'widthmask': wm,
                            'height': h, 'patchless': flat_cols}
    banks.put(R.LVMAP, TXFLAT_INDEX, bytes(flat_index))
    if flat_maps:
        banks.put(R.LVMAP, TXFLAT_MAPS, bytes(flat_maps))
    # the sky: the lump of skypatchnum, in place (W_TryGetLumpByNum)
    skypatchnum = up.g('skypatchnum')
    skywidthmask = up.g('skywidthmask')
    numlumps = up.g('numlumps')
    if not 0 <= skypatchnum < numlumps:
        raise ConvError('skypatchnum %d: the WAD has %d lumps'
                        % (skypatchnum, numlumps))
    fileinfo = up.ptr('fileinfo')
    fi = fileinfo + FI_SIZE_BYTES * skypatchnum
    lo, hi = m.u16(fi), m.u16(fi + 2)
    sky = (((hi + MM_WAD_BANK) & 0xFF) << 16) | lo
    if skywidthmask != SKY_COLUMNS - 1:
        raise ConvError('skywidthmask %d, not 255' % skywidthmask)
    sky_bank, sky_base = place(SLOT * SKY_COLUMNS)
    for c in range(SKY_COLUMNS):
        colofs = m.u16(sky + 8 + 4 * c)
        ptr = (sky & 0xFF0000) | ((lo + colofs + 3) & 0xFFFF)
        banks.put(sky_bank, sky_base + SLOT * c,
                  slot_source(ptr, 'sky:%d' % c))
    source('sky patch', sky, 8 + 4 * SKY_COLUMNS)
    checks.append('skypatchnum names a lump of the WAD directory')

    # -- W tables: FLATCM and the texture directory
    flatcm = m.read(sym.address('FLATCM'), 34 * 32)
    source('FLATCM', sym.address('FLATCM'), 34 * 32)
    wtables = {R.FLATCM: flatcm,
               R.TXBANK: bytes(txbank), R.TXLO: bytes(txlo),
               R.TXHI: bytes(txhi), R.TXWM: bytes(txwm),
               R.TXHT: bytes(txht)}

    # -- milestone 8: the sprite data (RENDER-MASKED.md 1.3-1.4)
    sprite = sprite_part(up, m, sym, lines, sides, banks)
    checks += sprite['checks']
    # the width mask of each texture a masked mid texture can show (TXWM:
    # the made textures' already, the same value)
    for tex, wm in sprite['txmp_wm'].items():
        if wm > 255:
            raise ConvError('texture %d has width mask %d: TXWM holds '
                            'bytes' % (tex, wm))
        if tex in made and txwm[tex] != wm:
            raise ConvError('texture %d: its width mask %d, its column '
                            'tables\' %d' % (tex, wm, txwm[tex]))
        txwm[tex] = wm
    wtables[R.TXWM] = bytes(txwm)
    ranges.append(sprite['source'])
    # stage C: the spectre fuzz table of the level's palette, the replay's
    # FUZZDARK (aux 0 $0800, MEMORY_MAP.md 5; i_viigs65.s:1014-1017)
    fuzzdark = m.read(MM_FUZZ_DARKEN, 256)
    source('FUZZ_DARKEN', MM_FUZZ_DARKEN, 256)

    key = hashlib.sha256(json.dumps(
        [(r['what'], r['address'], r['length'], r['sha256'])
         for r in ranges]).encode()).hexdigest()[:16]
    skyflat = up.g('skyflatnum')
    info = {
        'format': FORMAT, 'revision': REVISION, 'source': source_name,
        'map': 'E1M%d' % gamemap,
        'gamemap': gamemap, 'key': key,
        'counts': {'sectors': len(sectors), 'sides': len(sides),
                   'lines': len(lines), 'subsectors': len(subs),
                   'segs': len(segs), 'nodes': len(nodes),
                   'vertices': nv, 'textures': len(made),
                   'numtextures': numtextures},
        'arrays': {a.name: {'bank': a.bank, 'base': a.base,
                            'stride': a.stride, 'capacity': a.capacity}
                   for a in (R.SEGS, R.NODES, R.SUBS, R.SECTORS,
                             R.SIDES)},
        'vertex_cache': {'bank': R.LVMAP, 'low': R.VAL, 'high': R.VAH,
                         'stamp': R.VAS, 'capacity': R.VTX_CAP},
        'txflat': {'bank': R.LVMAP, 'index': TXFLAT_INDEX,
                   'maps': TXFLAT_MAPS},
        'textures': textures, 'converted': made,
        'sky': {'bank': sky_bank, 'base': sky_base, 'columns': SKY_COLUMNS,
                'lump': skypatchnum, 'address': sky},
        'skyflatnum': skyflat, 'skywidthmask': skywidthmask,
        'numnodes': numnodes, 'bsp_depth': depth,
        'banks': sorted(banks.data),
        'upstream_vertex': [up_vertex[i] for i in range(nv)],
        'open_ended': open_ended, 'colmem': colmem,
        'sources': ranges, 'checks': checks,
        'sector_base': sec_base,
        'sprites': sprite['info'],
    }
    texmap = {'format': 'render-texmap 1', 'slots': slots}
    return Level(info, banks, wtables, texmap, sector_side_manifest(),
                 sprite['mtables'], sprite['patchmap'], fuzzdark)


# ---------------------------------------------------------------------------
# Milestone 8: the patch store, the sprite frames, the patch headers, TXMP
# (RENDER-MASKED.md 1.3, 1.4, 1.11)
# ---------------------------------------------------------------------------

def wad_directory(m: bmem.Memory, sym: blink.Symbols
                  ) -> Tuple[List[Tuple[int, int, str]], int]:
    """The game's lump directory in RAM (fileinfo, numlumps): each lump's
    (address, size, name), and the placeholder's address: the filepos
    that several lumps of non-zero size share (upstream's empty patch for a
    lump that is not resident, build/upstream/tools/levelimg.py)."""
    fileinfo = m.uint(sym.address('fileinfo'), 3)
    count = m.u16(sym.address('numlumps'))
    out = []
    starts: Dict[int, int] = {}
    for i in range(count):
        e = fileinfo + FI_ENTRY * i
        pos, size = m.u32(e), m.u32(e + 4)
        name = m.read(e + 8, 8).split(b'\0')[0].decode('latin-1')
        address = (MM_WAD_BANK << 16) + pos & 0xFFFFFF
        out.append((address, size, name))
        if size:
            starts[address] = starts.get(address, 0) + 1
    shared = [a for a, n in starts.items() if n > 1]
    if len(shared) != 1:
        raise ConvError('the WAD directory has %d shared lump addresses, not '
                        'one placeholder' % len(shared))
    return out, shared[0]


def sprite_frames(m: bmem.Memory, sym: blink.Symbols) -> List[int]:
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


def frame_address(m: bmem.Memory, sprites: int, sprite: int, f: int) -> int:
    """sprites[sprite].spriteframes + 19 f as upstream adds it: 19 (f &
    $7FFF) & $7FFF to the pointer's low word (r_thing65.s:319-343)."""
    sf = m.uint(sprites + 4 * sprite, 4)
    low = (sf + ((19 * (f & 0x7FFF)) & 0x7FFF)) & 0xFFFF
    return (sf & 0xFF0000) | low


def masked_textures(m: bmem.Memory, sym: blink.Symbols, lines, sides
                    ) -> List[int]:
    """The textures a masked mid texture can show (RENDER-MASKED.md 1.3):
    the mid textures of the two-sided lines' sides, their switch partners
    (switchlist: a switch changes a side's textures), and all three slime
    frames when one of those is one (animated_texture_basepic: the only
    textures upstream animates through texturetranslation)."""
    mids = set()
    for ln in lines:
        s0, s1 = ln['sidenum']
        if s1 in (-1, 0xFFFF):
            continue
        for s in (s0, s1):
            tex = sides[s]['midtexture']
            if tex:
                mids.add(tex)
    sw = [m.u16(sym.address('switchlist') + 2 * i)
          for i in range(NUMSWITCHES2)]
    out = set(mids)
    for tex in mids:
        for i, x in enumerate(sw):
            if x == tex:
                out.add(sw[i ^ 1])
    base = m.u16(sym.address('animated_texture_basepic'))
    if any(base <= tex <= base + 2 for tex in out):
        out |= {base, base + 1, base + 2}
    return sorted(out)


def sprite_part(up: 'Upstream', m: bmem.Memory, sym: blink.Symbols,
                lines, sides, banks: Banks) -> Dict[str, Any]:
    checks: List[str] = []
    directory, placeholder = wad_directory(m, sym)
    nlumps = len(directory)

    def resident(lump: int) -> bool:
        a, size, _ = directory[lump]
        return size > 0 and a != placeholder
    # the sprite frames
    sprites = m.uint(sym.address('sprites'), 3)
    nframes = sprite_frames(m, sym)
    frames = []                         # (sprite, f, rotate, flip, lumps, ok)
    for s in range(R.NUMSPRITES):
        for f in range(nframes[s]):
            a = frame_address(m, sprites, s, f)
            rotate = m.read(a + OFS_SF_ROTATE, 1)[0]
            flip = m.read(a + OFS_SF_FLIPMASK, 1)[0]
            lumps = [m.u16(a + 2 * r) for r in range(8)]
            used = lumps if rotate else lumps[:1]
            ok = all(lump < nlumps for lump in used)
            frames.append((s, f, rotate, flip, lumps if rotate else
                           lumps[:1], ok))
    if len(frames) > R.SPRFRS.capacity:
        raise ConvError('%d sprite frames: SPRFR holds %d'
                        % (len(frames), R.SPRFRS.capacity))
    # the masked textures' first patches
    tex_ptrs = m.uint(sym.address('textures'), 3)
    txmp_tex = masked_textures(m, sym, lines, sides)
    txmp: Dict[int, Tuple[Optional[int], str]] = {}
    txmp_wm: Dict[int, int] = {}
    for tex in txmp_tex:
        ptr = m.uint(tex_ptrs + 4 * tex, 4) & 0xFFFFFF
        if not ptr:
            txmp[tex] = (None, 'not loaded by upstream')
            continue
        # its width mask (maskedRange's FR_WMASK, r_frame65.s:532-534)
        txmp_wm[tex] = m.u16(ptr + OFS_TEX_WIDTHMASK)
        lump = m.u16(ptr + OFS_TEX_PATCHES + OFS_TP_PATCHNUM)
        if lump >= nlumps or not resident(lump):
            txmp[tex] = (None, 'its first patch (lump %d) is not '
                               'resident' % lump)
            continue
        txmp[tex] = (lump, 'stored')
    # the store: every resident lump of a converted frame and of TXMP, in
    # lump order; index 0 the placeholder
    wanted = set()
    for _, _, _, _, lumps, ok in frames:
        if ok:
            wanted |= {x for x in lumps if resident(x)}
    wanted |= {lump for lump, _ in txmp.values() if lump is not None}
    order = sorted(wanted)
    index = {lump: k + 1 for k, lump in enumerate(order)}
    if len(order) + 1 > R.PHDRS.capacity:
        raise ConvError('%d patches: PHDR holds %d' % (len(order) + 1,
                                                      R.PHDRS.capacity))
    bank, at = R.SPR_FIRST, R.BANK_ROOM[0]
    store = []
    phdr = bytearray()

    def header(address: int, bank_: int, where: int, lump: int) -> bytes:
        rec = bytearray(R.PHDR_SIZE)
        for k, key in (('WIDTH', 0), ('LEFT', 4), ('TOP', 6)):
            rec[R.PHDR[k]:R.PHDR[k] + 2] = m.read(address + key, 2)
        rec[R.PHDR['BANK']] = bank_
        rec[R.PHDR['ADDR']:R.PHDR['ADDR'] + 2] = pack16(where)
        rec[R.PHDR['LUMP']:R.PHDR['LUMP'] + 2] = pack16(lump)
        return bytes(rec)
    phdr += header(placeholder, 0, 0, 0xFFFF)
    for lump in order:
        address, size, name = directory[lump]
        need = size + TAIL
        if need > R.BANK_ROOM[1] - R.BANK_ROOM[0]:
            raise ConvError('lump %d (%s) of %d bytes does not fit a bank'
                            % (lump, name, size))
        if at + need > R.BANK_ROOM[1]:
            bank, at = bank + 1, R.BANK_ROOM[0]
        if bank > R.SPR_LAST:
            raise ConvError('the patch store needs more than banks %d-%d'
                            % (R.SPR_FIRST, R.SPR_LAST))
        banks.put(bank, at, m.read(address, need))
        store.append({'index': index[lump], 'lump': lump, 'name': name,
                      'address': address, 'size': size, 'bank': bank,
                      'at': at})
        phdr += header(address, bank, at, lump)
        at += need
    banks.put(R.SPRT, R.PHDRS.base, bytes(phdr))
    checks.append('%d patch lumps stored in banks %d-%d (%d bytes and '
                  '%d-byte tails)' % (len(order), R.SPR_FIRST, bank,
                                      sum(e['size'] for e in store), TAIL))
    # SPRFR
    data = bytearray()
    bad = []
    for s, f, rotate, flip, lumps, ok in frames:
        rec = bytearray(R.SPRFR_SIZE)
        rec[R.SPRFR['ROT']] = rotate
        rec[R.SPRFR['FLIP']] = flip
        if ok:
            for r, lump in enumerate(lumps):
                k = index.get(lump, 0)
                if resident(lump) and not k:
                    raise ConvError('sprite %d frame %d: lump %d is not '
                                    'stored' % (s, f, lump))
                rec[R.SPRFR['LUMPS'] + 2 * r:R.SPRFR['LUMPS'] + 2 * r + 2] \
                    = pack16(k)
        else:
            rec[R.SPRFR['FLAGS']] = R.SPRFR_BAD
            bad.append([s, f])
        data += rec
    banks.put(R.SPRT, R.SPRFRS.base, bytes(data))
    checks.append('%d sprite frames resolve to a store index or the '
                  'placeholder; %d are not frames (%s)' % (
                      len(frames) - len(bad), len(bad),
                      ', '.join('sprite %d frame %d' % tuple(x)
                                for x in bad)))
    # the masked image's TXMP (store index, $FFFF: none)
    lo, hi = bytearray(b'\xff' * 256), bytearray(b'\xff' * 256)
    for tex, (lump, why) in txmp.items():
        if lump is not None:
            lo[tex], hi[tex] = index[lump] & 0xFF, index[lump] >> 8
    mtables = {R.TXMP: bytes(lo) + bytes(hi)}
    checks.append('TXMP: %d textures a masked mid texture can show, %d '
                  'stored' % (len(txmp), sum(1 for v in txmp.values()
                                             if v[0] is not None)))
    # stage C: the weapons' profiles (RENDER-MASKED.md 1.5)
    weapons = weapon_part(m, sym, frames, index, directory, resident,
                          banks)
    checks += weapons.pop('checks')
    info = {'placeholder': placeholder,
            'frames_per_sprite': nframes, 'not_frames': bad,
            'store': store, 'store_banks': [R.SPR_FIRST, bank],
            'store_bytes': sum(e['size'] + TAIL for e in store),
            'txmp': {str(tex): {'lump': lump, 'why': why}
                     for tex, (lump, why) in txmp.items()},
            'tail': TAIL, 'weapons': weapons}
    patchmap = {'format': 'render-patchmap 1',
                'entries': [[e['bank'], e['at'], e['size'] + TAIL,
                             e['address']] for e in store]}
    digest = hashlib.sha256()
    digest.update(bytes(phdr))
    digest.update(bytes(data))
    for e in store:
        digest.update(m.read(e['address'], e['size'] + TAIL))
    source = {'what': 'sprite data (the stored lumps and tails, PHDR, '
                      'SPRFR)', 'address': 0,
              'length': len(phdr) + len(data) + info['store_bytes'],
              'sha256': digest.hexdigest()}
    return {'checks': checks, 'info': info, 'mtables': mtables,
            'patchmap': patchmap, 'source': source, 'txmp_wm': txmp_wm}


# ---------------------------------------------------------------------------
# Stage C: the weapons' profiles (RENDER-MASKED.md 1.5)
# ---------------------------------------------------------------------------

def weapon_sprites(m: bmem.Memory, sym: blink.Symbols) -> List[int]:
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


def weapon_part(m: bmem.Memory, sym: blink.Symbols, frames, index,
                directory, resident, banks: Banks) -> Dict[str, Any]:
    """WPRO: WPIDX and the profile of each lump a psprite can show (lump[0]
    of every frame of the weapon sprites: pspSprite takes the first), made
    by wbMake's rules where upstream makes one: a profile is made exactly
    when it fits an empty first arena ($D000-$E3FF), because each of
    wpBuild's paths tries that arena empty before it gives up (three tries:
    the arena in use, the other one from its start, then after a flush,
    r_sprite65.s:946-1007), and the second arena is the smaller. Checked
    against the reference's arenas wherever they hold a profile."""
    wsprites = weapon_sprites(m, sym)
    lumps: Dict[int, Dict[str, Any]] = {}
    for s, f, rotate, flip, lumpl, ok in frames:
        if s in wsprites and ok:
            lumps.setdefault(lumpl[0], {'sprite': s, 'frame': f})
    not_resident = sorted(x for x in lumps if not resident(x))
    wpidx = bytearray(b'\xff' * (R.WPROF - R.WPIDX))
    at = R.WPROF
    made = 0
    for lump in sorted(lumps):
        e = lumps[lump]
        if not resident(lump):
            e['profile'] = None
            e['why'] = 'not resident'
            continue
        address, size, name = directory[lump]
        e['name'] = name
        e['index'] = index[lump]

        def read(off: int, n: int, a=address) -> bytes:
            return m.read(a + off, n)
        status, _ = wb_make(read, WP_ARENAS[0][0], WP_ARENAS[0][1])
        if status:
            e['profile'] = None
            e['why'] = 'no room in an empty arena' if status == 1 else \
                'the patch does not fit a profile'
            continue
        status, data = wb_make(read, at, R.WPROF_END)
        if status:
            raise ConvError('the weapon profiles do not fit bank %d' % R.WPRO)
        end = data.pop('end')
        blob = bytearray(end - at)
        for k, v in data.items():
            blob[k - at] = v
        banks.put(R.WPRO, at, bytes(blob))
        k = index[lump]
        wpidx[2 * k:2 * k + 2] = pack16(at)
        e['profile'] = at
        e['bytes'] = end - at
        at = end
        made += 1
    banks.put(R.WPRO, R.WPIDX, bytes(wpidx))
    checks = ['%d weapon lumps (sprites %s): %d profiles in bank %d (%d '
              'bytes), %d without%s' % (
                  len(lumps), ','.join(str(s) for s in wsprites), made,
                  R.WPRO, at - R.WPROF, len(lumps) - made,
                  '; not resident: %s' % not_resident if not_resident
                  else '')]
    # the reference's arenas (tags WP_TAGL/WP_TAGB, r_sprite65.s:737-745)
    sig = m.read(MM_WPROF + 0x46, 4)
    checked = 0
    if sig == bytes((0xA5, 0x5A, 0x3C, 0xC3)):
        nt = m.u16(MM_WPROF + 0x40)
        for t in range(min(nt, 32) // 2):
            lump = m.u16(MM_WPROF + 2 * t)
            addr = m.u16(MM_WPROF + 0x20 + 2 * t)
            if lump not in lumps:
                raise ConvError('the reference has a profile of lump %d, '
                                'which no psprite state names' % lump)
            e = lumps[lump]
            if addr == WP_NONE_ADDR:
                if e.get('profile') is not None:
                    raise ConvError('lump %d: the reference has no profile, '
                                    'the converter one' % lump)
                checked += 1
                continue
            if e.get('profile') is None:
                raise ConvError('lump %d: the reference has a profile at '
                                '$%04X, the converter none' % (lump, addr))
            limit = next((hi for lo, hi in WP_ARENAS if lo <= addr < hi),
                         None)
            if limit is None:
                raise ConvError('lump %d: a profile at $%04X, in no arena'
                                % (lump, addr))
            a0 = directory[lump][0]
            status, data = wb_make(lambda off, n: m.read(a0 + off, n),
                                   addr, limit)
            if status:
                raise ConvError('lump %d: the reference made a profile at '
                                '$%04X, the rules none' % (lump, addr))
            data.pop('end')
            for k, v in data.items():
                if m.read((MM_WPROF & 0xFF0000) + k, 1)[0] != v:
                    raise ConvError('lump %d: the profile at $%04X differs '
                                    'from the reference at $%04X'
                                    % (lump, addr, k))
            # and the native copy is the same profile, rebased: its
            # addresses (the tables' and the lists') less its base equal
            # the reference's less theirs, every other byte equal
            nat = banks.get(R.WPRO, e['profile'], e['bytes'])
            width = data[addr] | data[addr + 1] << 8
            words = {R.WPH['TEVEN'], R.WPH['TODD']} | {
                16 + 2 * i for i in range(width)}
            if max(data) - addr + 1 != len(nat):
                raise ConvError('lump %d: the native profile is %d bytes, '
                                'the reference\'s %d' % (
                                    lump, len(nat), max(data) - addr + 1))
            for rel in sorted(k - addr for k in data):
                if rel - 1 in words:
                    continue
                if rel in words:
                    ref = data[addr + rel] | data[addr + rel + 1] << 8
                    got = nat[rel] | nat[rel + 1] << 8
                    if ref - addr != got - e['profile']:
                        raise ConvError('lump %d: the native profile\'s '
                                        'address at +%d differs' % (lump,
                                                                    rel))
                elif nat[rel] != data[addr + rel]:
                    raise ConvError('lump %d: the native profile differs at '
                                    '+%d' % (lump, rel))
            checked += 1
    checks.append('%d profiles of the reference\'s arenas equal the '
                  'converter\'s' % checked)
    return {'checks': checks, 'sprites': wsprites,
            'lumps': {str(k): v for k, v in sorted(lumps.items())},
            'not_resident': not_resident, 'profiles': made,
            'bytes': at - R.WPROF, 'checked': checked}


def check_store(level: Level, memory: bmem.Memory) -> int:
    """Each stored lump's bytes and tail read back from the banks equal
    the reference's RAM at its address; no lump crosses a bank; every
    PHDR and SPRFR entry names a stored lump or the placeholder. The
    lumps' count."""
    b = level.banks
    info = level.info['sprites']
    n = 0
    for e in info['store']:
        need = e['size'] + TAIL
        if e['at'] < R.BANK_ROOM[0] or e['at'] + need > R.BANK_ROOM[1]:
            raise ConvError('lump %d crosses its store bank' % e['lump'])
        if b.get(e['bank'], e['at'], need) != memory.read(e['address'],
                                                           need):
            raise ConvError('lump %d: the store differs from the reference '
                            'at $%06X' % (e['lump'], e['address']))
        ph = b.get(R.SPRT, R.PHDRS.address(e['index']), R.PHDR_SIZE)
        if (ph[R.PHDR['BANK']], u16(ph, R.PHDR['ADDR']),
                u16(ph, R.PHDR['LUMP'])) != (e['bank'], e['at'], e['lump']):
            raise ConvError('PHDR %d does not name lump %d' % (e['index'],
                                                               e['lump']))
        if ph[0:2] != memory.read(e['address'], 2):
            raise ConvError('PHDR %d: the width differs' % e['index'])
        n += 1
    count = sum(info['frames_per_sprite'])
    stored = {e['index'] for e in info['store']} | {0}
    for k in range(count):
        rec = b.get(R.SPRT, R.SPRFRS.address(k), R.SPRFR_SIZE)
        for r in range(8):
            idx = u16(rec, R.SPRFR['LUMPS'] + 2 * r)
            if idx not in stored:
                raise ConvError('SPRFR %d names patch %d, not stored'
                                % (k, idx))
    return n


# ---------------------------------------------------------------------------
# The bridge manifest of the render fields, and the decode check
# ---------------------------------------------------------------------------

def sector_side_manifest() -> Dict[str, Any]:
    """bridge-port-layout 1 with a stride: the sectors' and sides' render
    fields as rlayout.py places them (the bridge's port reader decodes
    them back)."""
    def planes(array, offset, size):
        return ['aux:%02X:%04X' % (array.bank, array.base + offset + k)
                for k in range(size)]

    def leaf(path, offset, size, signed, array):
        return {'path': path, 'enc': {'enc': 'int', 'bytes': size,
                                      'signed': signed},
                'planes': planes(array, offset, size),
                'stride': array.stride}
    sec = R.SECTORS
    side = R.SIDES
    return {
        'format': 'bridge-port-layout 1', 'name': 'render-level-1',
        'note': 'the render parts of the sectors and sides '
                '(tools/native/levelconv.py); their counts at LVCOUNT '
                '(rlayout.py), which framestate.py writes',
        'symbols': [], 'tables': [], 'lists': {}, 'pools': {},
        'kinds': {
            'sector': {'capacity': sec.capacity,
                       'count': ['main:%04X' % R.LVCOUNT,
                                 'main:%04X' % (R.LVCOUNT + 1)],
                       'leaves': [
                           leaf(['floorheight'], 0, 4, True, sec),
                           leaf(['ceilingheight'], 4, 4, True, sec),
                           leaf(['floorpic'], R.SEC['FPIC'], 1, True, sec),
                           leaf(['ceilingpic'], R.SEC['CPIC'], 1, True,
                                sec),
                           leaf(['lightlevel'], R.SEC['LIGHT'], 1, False,
                                sec),
                           leaf(['validcount'], R.SEC['VALID'], 2, True,
                                sec)]},
            'side': {'capacity': side.capacity,
                     'count': ['main:%04X' % (R.LVCOUNT + 2),
                               'main:%04X' % (R.LVCOUNT + 3)],
                     'leaves': [
                         leaf(['textureoffset'], 0, 2, True, side),
                         leaf(['rowoffset'], 2, 2, True, side),
                         leaf(['toptexture'], R.SIDE['TOP'], 1, False, side),
                         leaf(['bottomtexture'], R.SIDE['BOTTOM'], 1, False,
                              side),
                         leaf(['midtexture'], R.SIDE['MID'], 1, False,
                              side)]}},
        'globals': {'leaves': []},
    }


def u16(b: bytes, at: int) -> int:
    return b[at] | b[at + 1] << 8


def decode(level: Level) -> Dict[str, List[Dict[str, Any]]]:
    """The native level read back through rlayout.py alone: every field
    the renderer reads, as upstream's canonical objects have them."""
    b = level.banks
    c = level.info['counts']
    out: Dict[str, List[Dict[str, Any]]] = {}
    segs = []
    points: Dict[int, Tuple[int, int]] = {}
    for i in range(c['segs']):
        r = b.get(R.LVSEG, R.SEGS.address(i), R.SEG_SIZE)
        v1 = [s16(u16(r, 0)), s16(u16(r, 2))]
        v2 = [s16(u16(r, 4)), s16(u16(r, 6))]
        for n, p in ((u16(r, R.SEG['V1N']), v1), (u16(r, R.SEG['V2N']), v2)):
            if points.setdefault(n, tuple(p)) != tuple(p):
                raise ConvError('vertex %d at two places' % n)
        segs.append({'v1': v1, 'v2': v2,
                     'offset': s16(u16(r, R.SEG['OFFSET'])),
                     'angle': u16(r, R.SEG['ANGLE']),
                     'sidenum': s16(u16(r, R.SEG['SIDE'])),
                     'linenum': u16(r, R.SEG['LINE']),
                     'frontsectornum': r[R.SEG['FRONT']],
                     'backsectornum': r[R.SEG['BACK']],
                     'pegs': r[R.SEG['PEGS']]})
    out['seg'] = segs
    nodes = []
    for i in range(c['nodes']):
        r = b.get(R.LVMAP, R.NODES.address(i), R.NODE_SIZE)
        w = [u16(r, 2 * k) for k in range(14)]
        nodes.append({'x': s16(w[0]), 'y': s16(w[1]), 'dx': s16(w[2]),
                      'dy': s16(w[3]), 'bbox': [s16(v) for v in w[4:12]],
                      'children': w[12:14]})
    out['node'] = nodes
    subs = []
    for i in range(c['subsectors']):
        r = b.get(R.LVMAP, R.SUBS.address(i), R.SUB_SIZE)
        subs.append({'sector': r[0], 'numlines': r[1],
                     'firstline': u16(r, 2)})
    out['subsector'] = subs
    secs = []
    for i in range(c['sectors']):
        r = b.get(R.LVMAP, R.SECTORS.address(i), R.SEC_SIZE)
        fh = int.from_bytes(r[0:4], 'little', signed=True)
        ch = int.from_bytes(r[4:8], 'little', signed=True)
        secs.append({'floorheight': fh, 'ceilingheight': ch,
                     'floorpic': pic_value(r[R.SEC['FPIC']]),
                     'ceilingpic': pic_value(r[R.SEC['CPIC']]),
                     'lightlevel': r[R.SEC['LIGHT']],
                     'validcount': s16(u16(r, R.SEC['VALID']))})
    out['sector'] = secs
    sides = []
    for i in range(c['sides']):
        r = b.get(R.LVMAP, R.SIDES.address(i), R.SIDE_SIZE)
        sides.append({'textureoffset': s16(u16(r, 0)),
                      'rowoffset': s16(u16(r, 2)),
                      'toptexture': r[R.SIDE['TOP']],
                      'bottomtexture': r[R.SIDE['BOTTOM']],
                      'midtexture': r[R.SIDE['MID']],
                      'sector': r[R.SIDE['SECTOR']]})
    out['side'] = sides
    return out


def check_decode(level: Level, up_state: Dict[str, Any]) -> int:
    """Differences between the decoded native level and upstream's
    canonical objects, rendered fields only (raises on the first)."""
    got = decode(level)
    objs = up_state['objects']
    lines = objs['line']
    count = 0
    for i, s in enumerate(got['seg']):
        u = objs['seg'][i]
        want = {k: u[k] for k in ('v1', 'v2', 'offset', 'angle', 'sidenum',
                                  'linenum', 'frontsectornum',
                                  'backsectornum')}
        want['v1'], want['v2'] = list(want['v1']), list(want['v2'])
        want['pegs'] = lines[u['linenum']]['flags'] & (ML_DONTPEGTOP |
                                                      ML_DONTPEGBOTTOM)
        if s != want:
            raise ConvError('seg %d: %r, upstream %r' % (i, s, want))
        count += 1
    for i, n in enumerate(got['node']):
        u = objs['node'][i]
        want = {'x': u['x'], 'y': u['y'], 'dx': u['dx'], 'dy': u['dy'],
                'bbox': list(u['bbox']),
                'children': [c & 0xFFFF for c in u['children']]}
        if n != want:
            raise ConvError('node %d: %r, upstream %r' % (i, n, want))
        count += 1
    for i, s in enumerate(got['subsector']):
        u = objs['subsector'][i]
        want = {'sector': ref_index(u['sector'], 'sector'),
                'numlines': u['numlines'], 'firstline': u['firstline']}
        if s != want:
            raise ConvError('subsector %d: %r, upstream %r' % (i, s, want))
        count += 1
    for kind, keys in (('sector', ('floorheight', 'ceilingheight',
                                   'floorpic', 'ceilingpic', 'lightlevel',
                                   'validcount')),
                       ('side', ('textureoffset', 'rowoffset',
                                 'toptexture', 'bottomtexture',
                                 'midtexture'))):
        for i, s in enumerate(got[kind]):
            u = objs[kind][i]
            want = {k: u[k] for k in keys}
            if kind == 'side':
                want['sector'] = ref_index(u['sector'], 'sector')
            if s != want:
                raise ConvError('%s %d: %r, upstream %r' % (kind, i, s,
                                                            want))
            count += 1
    return count


def check_slots(level: Level, memory: bmem.Memory) -> int:
    """Every made column has its slot, with the reference's 128 bytes at
    the column's texel pointer, read again from COLDIR (not from the
    texture map); the sky likewise from its lump. The slots' count."""
    m = memory
    b = level.banks
    n = 0
    txbank = level.wtables[R.TXBANK]
    txlo, txhi = level.wtables[R.TXLO], level.wtables[R.TXHI]
    txwm = level.wtables[R.TXWM]
    for t in range(256):
        entry = m.read(MM_COLDIR + 4 * t, 4)
        if entry[2] == 0 and entry[3] == 0:
            if txbank[t] or txwm[t]:
                raise ConvError('texture %d has a directory entry but no '
                                'columns' % t)
            continue
        table = entry[0] | entry[1] << 8 | entry[2] << 16
        if txwm[t] != entry[3] or not txbank[t]:
            raise ConvError('texture %d: widthmask %d, native %d'
                            % (t, entry[3], txwm[t]))
        base = txlo[t] | txhi[t] << 8
        bank = txbank[t] & 0x7F
        for c in range(entry[3] + 1):
            e = m.read(table + 4 * c, 4)
            if e[3]:
                continue
            ptr = e[0] | e[1] << 8 | e[2] << 16
            if b.get(bank, base + SLOT * c, SLOT) != m.read(ptr, SLOT):
                raise ConvError('texture %d column %d: the slot differs '
                                'from the reference at $%06X' % (t, c, ptr))
            n += 1
    sky = level.info['sky']
    lo = sky['address'] & 0xFFFF
    for c in range(SKY_COLUMNS):
        colofs = m.u16(sky['address'] + 8 + 4 * c)
        ptr = (sky['address'] & 0xFF0000) | ((lo + colofs + 3) & 0xFFFF)
        if b.get(sky['bank'], sky['base'] + SLOT * c, SLOT) != \
                m.read(ptr, SLOT):
            raise ConvError('sky column %d: the slot differs' % c)
        n += 1
    return n


def port_memory(recs, counts: Dict[str, int]):
    """The bridge's PortMemory of a native level's RamWorks records and
    the counts at LVCOUNT."""
    from bridge.memory import MAIN, PortMemory
    pm = PortMemory()
    for kind, bank, address, data in recs:
        if kind == 1:
            pm.write(bank << 16 | address, data)
        elif kind == 0:
            pm.write(MAIN | address, data)
    pm.write(MAIN | R.LVCOUNT, pack16(counts['sectors']) +
             pack16(counts['sides']))
    return pm


def check_bridge(level: Level, up_state: Dict[str, Any]) -> int:
    """The render fields read back by the bridge's port reader through
    the manifest (sectors-sides.json: records with a stride), against
    upstream's canonical objects. The fields compared."""
    from bridge.layout import Manifest
    from bridge.port import PortReader
    recs = [(1, bank, address, data) for bank in sorted(level.banks.data)
            for address, data in level.banks.runs(bank)]
    pm = port_memory(recs, level.info['counts'])
    state = PortReader(Manifest(level.manifest)).read(pm)
    n = 0
    for kind in ('sector', 'side'):
        got = state['objects'].get(kind, {})
        want = up_state['objects'][kind]
        if len(got) != len(want):
            raise ConvError('the bridge reads %d %ss, upstream has %d'
                            % (len(got), kind, len(want)))
        for i, o in got.items():
            for k, v in o.items():
                if want[i][k] != v:
                    raise ConvError('the bridge reads %s %d %s = %r, '
                                    'upstream %r' % (kind, i, k, v,
                                                     want[i][k]))
                n += 1
    return n


STATIC = {'node': None, 'seg': None, 'subsector': None,
          'line': ('v1', 'v2', 'dx', 'dy', 'sidenum', 'bbox', 'flags'),
          'side': ('sector',)}


def static_fields(state: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for kind, keys in STATIC.items():
        objs = state['objects'].get(kind, {})
        out[kind] = {i: (o if keys is None else {k: o[k] for k in keys})
                     for i, o in objs.items()}
    return json.loads(json.dumps(out, default=str))


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def level_dir(info: Dict[str, Any]) -> Path:
    return LEVELS / ('%s-%s' % (info['map'].lower(), info['key']))


def write(level: Level, out: Optional[Path] = None) -> Path:
    out = out or level_dir(level.info)
    out.mkdir(parents=True, exist_ok=True)
    img = Image()
    for bank in sorted(level.banks.data):
        for address, data in level.banks.runs(bank):
            img.add(1, bank, address, data)
    (out / 'level.img').write_bytes(img.bytes())
    w = Image()
    for address in sorted(level.wtables):
        w.add(0, 0, address, level.wtables[address])
    (out / 'wtables.img').write_bytes(w.bytes())
    (out / 'level.json').write_text(json.dumps(level.info, indent=1) + '\n')
    (out / 'texmap.json').write_text(json.dumps(level.texmap) + '\n')
    (out / 'sectors-sides.json').write_text(
        json.dumps(level.manifest, indent=1) + '\n')
    mt = Image()
    for address in sorted(level.mtables):
        mt.add(0, 0, address, level.mtables[address])
    (out / 'mtables.img').write_bytes(mt.bytes())
    (out / 'patchmap.json').write_text(json.dumps(level.patchmap) + '\n')
    (out / 'fuzzdark.bin').write_bytes(level.fuzzdark)
    return out


def run_one(path: Path, sym: blink.Symbols, second: Optional[Path] = None
            ) -> Dict[str, Any]:
    memory = load_memory(path)
    level = convert(memory, sym, path.name)
    up = Upstream(memory, sym)
    n = check_decode(level, up.state)
    level.info['checks'].append('decode equals upstream on %d objects' % n)
    slots = check_slots(level, memory)
    level.info['checks'].append('%d slots equal the reference' % slots)
    lumps = check_store(level, memory)
    level.info['checks'].append('%d stored lumps and their tails equal the '
                                'reference' % lumps)
    fields = check_bridge(level, up.state)
    level.info['checks'].append('the bridge reads %d render fields back'
                                % fields)
    if second is not None:
        other = Upstream(load_memory(second), sym)
        if other.g('_g_gamemap') != up.g('_g_gamemap'):
            raise ConvError('%s is another map' % second)
        a, b = static_fields(up.state), static_fields(other.state)
        if a != b:
            diff = [k for k in a if a[k] != b[k]]
            raise ConvError('the static fields differ from %s: %s'
                            % (second, diff))
        level.info['checks'].append('static fields equal those of %s'
                                    % second.name)
    directory = write(level)
    return {'source': path.name, 'map': level.info['map'],
            'key': level.info['key'], 'dir': str(directory),
            'counts': level.info['counts'],
            'bsp_depth': level.info['bsp_depth'],
            'banks': level.info['banks'],
            'open_ended': len(level.info['open_ended']),
            'slots': slots, 'checks': level.info['checks']}


# ---------------------------------------------------------------------------
# --overrun (RENDER-MASKED.md 1.3): how far past a post's last texel, and
# past its lump's end, the records that read the patch store reach
# ---------------------------------------------------------------------------

UP_KINDS = {0: 11, 2: 5, 6: 7, 8: 4, 10: 4}
K_NEXT_UP = 12
RECBANK = 0x1D0000


def reach(tf: int, ti: int, sf: int, si: int, rows: int) -> int:
    """An upper bound of the texel index a texture record's rows read: its
    position one row before the first and its step as 7.8 values
    (lists.inc:37-45), row k (1 to rows) reads the texel of (P0 + k S) >>
    8, or of it rounded (the pairs' half-way texel of an even row),
    masked to 7 bits as the row blocks do (a record never reads past 127;
    the position before the first row may be below 0: 127 masked)."""
    p0 = ti << 8 | tf
    s = si << 8 | sf
    top = 0
    for k in range(1, rows + 1):
        v = p0 + k * s
        top = max(top, (v >> 8) & 0x7F, ((v + 0x80) >> 8) & 0x7F)
    return top


def overrun_of_frame(frame_dir: Path, store: List[Dict[str, Any]],
                     sym: blink.Symbols, memory: bmem.Memory
                     ) -> Dict[str, Any]:
    """The frame's texture records (its lists at R_DrawLists, P4, and any
    early flush) that read a stored lump: the most rows past a post's last
    texel and bytes past its lump's end they reach (the post's length
    from the level source's memory: the lumps do not change)."""
    from native import rendercap
    dumps = [rendercap.load_dump(frame_dir / 'p4.dump.z')]
    for k in range(64):
        path = frame_dir / ('p2m-%d.dump.z' % k)
        if not path.exists():
            break
        dumps.append(rendercap.load_dump(path))
    lumps = sorted((e['address'], e['address'] + e['size']) for e in store)
    starts = [a for a, _ in lumps]
    import bisect
    out = {'records': 0, 'past_post': 0, 'past_lump': 0, 'posts_past': 0}
    for d in dumps:
        colw = d.get(sym.address('COLW'), 320)
        for c in range(160):
            from ref816 import lists as ulists
            end = colw[2 * c] | colw[2 * c + 1] << 8
            page, off = ulists.colpage(c), 0
            bank = sf = si = 0
            steps = 0
            while (page << 8 | off) != end:
                steps += 1
                if steps > 4096 or off >= 256:
                    raise ConvError('%s: column %d does not end'
                                    % (frame_dir.name, c))
                at = RECBANK + (page << 8) + off
                kind = d.get(at, 1)[0]
                if kind == K_NEXT_UP:
                    page, off = d.get(at + 1, 1)[0], 0
                    continue
                if kind not in UP_KINDS:
                    raise ConvError('%s: a record of kind %d' % (
                        frame_dir.name, kind))
                r = d.get(at, UP_KINDS[kind])
                off += UP_KINDS[kind]
                if kind == 0:
                    bank, sf, si = r[9], r[5], r[6]
                    src = r[7] | r[8] << 8 | r[9] << 16
                elif kind == 6:
                    src = bank << 16 | r[5] | r[6] << 8
                else:
                    continue
                k = bisect.bisect_right(starts, src) - 1
                if k < 0 or src >= lumps[k][1]:
                    continue                    # not the patch store
                out['records'] += 1
                top = reach(r[3], r[4], sf, si, r[2] - r[1])
                length = memory.read(src - 2, 1)[0]
                past = top - (length - 1)
                if past > 0:
                    out['posts_past'] += 1
                    out['past_post'] = max(out['past_post'], past)
                out['past_lump'] = max(out['past_lump'],
                                       src + top - (lumps[k][1] - 1))
    return out


def measure_overrun(frame_dirs: Sequence[Path], sym: blink.Symbols
                    ) -> Dict[str, Any]:
    """--overrun over the frames: by level conversion, written into its
    level.json and into levels/overrun.json."""
    table = json.loads((LEVELS / 'by-source.json').read_text())
    by_level: Dict[str, Dict[str, Any]] = {}
    memories: Dict[str, bmem.Memory] = {}
    for d in sorted(frame_dirs, key=lambda d: json.loads(
            (d / 'frame.json').read_text())['level_src']):
        meta = json.loads((d / 'frame.json').read_text())
        level_dir = Path(table[meta['level_src']])
        info = json.loads((level_dir / 'level.json').read_text())
        if meta['level_src'] not in memories:
            memories.clear()
            memories[meta['level_src']] = load_memory(
                SOURCES / (meta['level_src'] + '.ram.z'))
        res = overrun_of_frame(d, info['sprites']['store'], sym,
                               memories[meta['level_src']])
        acc = by_level.setdefault(level_dir.name, {
            'frames': 0, 'records': 0, 'past_post': 0, 'past_lump': 0,
            'posts_past': 0})
        acc['frames'] += 1
        acc['records'] += res['records']
        acc['posts_past'] += res['posts_past']
        acc['past_post'] = max(acc['past_post'], res['past_post'])
        acc['past_lump'] = max(acc['past_lump'], res['past_lump'])
    for name, acc in by_level.items():
        path = LEVELS / name / 'level.json'
        info = json.loads(path.read_text())
        info['sprites']['overrun'] = acc
        path.write_text(json.dumps(info, indent=1) + '\n')
    summary = {'levels': by_level,
               'past_post': max((a['past_post'] for a in by_level.values()),
                                default=0),
               'past_lump': max((a['past_lump'] for a in by_level.values()),
                                default=0),
               'records': sum(a['records'] for a in by_level.values()),
               'frames': sum(a['frames'] for a in by_level.values())}
    (LEVELS / 'overrun.json').write_text(json.dumps(summary, indent=1) +
                                         '\n')
    return summary


def bridge_dump_of(gamemap: int) -> Optional[Path]:
    """The bridge's tour dump of a map (the same level load as
    rendercap.py's tour run: the same script, deterministic)."""
    for d in sorted(BRIDGE_DUMPS.glob('tour-*')):
        meta = d / 'dump.json'
        if meta.exists() and json.loads(meta.read_text()).get(
                'gamemap') == gamemap:
            return d / 'entry.img'
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('sources', nargs='*', type=Path)
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--second', type=Path)
    parser.add_argument('--overrun', action='store_true',
                        help='measure the records\' reach past their posts '
                        'and lumps over every captured frame')
    args = parser.parse_args(argv)
    sym = symbols()
    if args.overrun:
        from native import rendercap
        dirs = sorted(d for d in rendercap.FRAMES.iterdir()
                      if (d / 'p4.dump.z').exists())
        try:
            s = measure_overrun(dirs, sym)
        except ConvError as error:
            print('overrun: FAILED: %s' % error)
            return 1
        print('%d frames, %d records reading the patch store: at most %d '
              'texels past a post\'s last, %d bytes past a lump\'s end'
              % (s['frames'], s['records'], s['past_post'], s['past_lump']))
        for name, a in sorted(s['levels'].items()):
            print('  %s: %d frames, %d records, %d past their post (at '
                  'most %d), %d past the lump\'s end' % (
                      name, a['frames'], a['records'], a['posts_past'],
                      a['past_post'], a['past_lump']))
        return 0
    todo: List[Tuple[Path, Optional[Path]]] = []
    if args.all:
        found = sorted(SOURCES.glob('*.ram.z'))
        if not found:
            print('no level sources in %s: run python3 '
                  'tools/native/rendercap.py first' % SOURCES,
                  file=sys.stderr)
            return 1
        for path in found:
            second = None
            if path.name.startswith('tour-'):
                gamemap = int(path.name.split('-')[1][3:])
                second = bridge_dump_of(gamemap)
            todo.append((path, second))
    for path in args.sources:
        todo.append((path, args.second))
    if not todo:
        parser.error('no source')
    failed = False
    report = []
    for path, second in todo:
        try:
            res = run_one(path, sym, second)
        except ConvError as error:
            print('%s: FAILED: %s' % (path.name, error))
            failed = True
            continue
        report.append(res)
        c = res['counts']
        print('%s: %s key %s: %d sectors, %d segs, %d nodes, %d vertices, '
              'depth %d, %d textures, %d slots, banks %s, %d open-ended; '
              '%s' % (res['source'], res['map'], res['key'], c['sectors'],
                      c['segs'], c['nodes'], c['vertices'], res['bsp_depth'],
                      c['textures'], res['slots'],
                      ','.join(str(b) for b in res['banks']),
                      res['open_ended'], '; '.join(res['checks'][-2:])))
    LEVELS.mkdir(parents=True, exist_ok=True)
    if args.all:
        (LEVELS / 'levelconv.json').write_text(json.dumps(report, indent=1)
                                               + '\n')
        if not failed:
            # every source's conversion (framestate.py's index), and no
            # conversion of another format or source left behind
            table = {r['source'][:-len('.ram.z')]: r['dir'] for r in report
                     if r['source'].endswith('.ram.z')}
            (LEVELS / 'by-source.json').write_text(
                json.dumps(table, indent=1) + '\n')
            keep = {Path(d).name for d in table.values()}
            for d in LEVELS.iterdir():
                if d.is_dir() and d.name != 'src' and d.name not in keep \
                        and (d / 'level.json').exists():
                    import shutil
                    shutil.rmtree(str(d))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
