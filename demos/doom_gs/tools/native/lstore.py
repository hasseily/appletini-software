"""The native level store (docs/LEVELS.md): its format and its builder
from wadconv.py's conversions.

    python3 tools/native/wadconv.py --store

builds, in build/native/levels/store/:

    TEXELS.1, PATCHES.1, MAPS.1, TABLES.1
                 bank files ("A2DM", version 1, a segment count, 5 bytes a
                 segment: bank, address, length; zero padding to 256 bytes; the bytes)
    store.json   every block (bank, address, length, codec), the shared
                 stores, each map's level part and load program, the
                 apply and undo variant lists, the bank tally

The shared stores (docs/LEVELS.md):

  texel store   one block a texture any map can show (made at a load, or
                in play: made on a copy of the model after the load, as
                needColumns would) and the sky (SKY1's 256 columns): 128
                bytes a column, the canonical bytes of each column the
                most common over the nine maps (ties: the lowest map);
                first fit, largest first, into the TEX banks
  patch store   every lump a map stores (levelconv.py's rule), whole,
                then its canonical 128-byte tail (the most common); its
                global index (PHDR) by lump number from 1, 0 the
                placeholder; first fit, largest first, into the SPR banks
  PHDR, WPRO    global: SPRT's PHDR, WPRO's WPIDX and profiles by global
                index (wadconv.weapon_part's rules)

Each map's level part (STORE banks, after the texel banks' slack): the
blocks of BLOCK_KINDS, its header (the counts, the blocks, the LVG1
bases), the apply and undo lists (128-byte columns and tails: the bytes
where the map differs from the canonical stores, and the canonical bytes
of the same places), and its load program: the steps of
docs/LEVELS.md's load and the memory-API requests (llayout.py: COPY and
FILL descriptors, PRIVATE for main and aux 0, at most 16 a request and
45 KB of data).
"""

import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import levelconv as LC, lderive as LD, llayout as LL, \
    rlayout as R, umodel as U, wadconv as WC  # noqa: E402

ROOT = HERE.parent.parent
STORE = ROOT / 'build' / 'native' / 'levels' / 'store'
FORMAT = 'level-store 1'
SLOT = LC.SLOT
TAIL = LC.TAIL
MAPS = tuple(range(1, 10))
NUMMOBJTYPES = 50
MTF_SKILLS = 7
# the lumps after a map's name lump (p_setup65.s ML_REJECT, ML_BLOCKMAP)
ML_REJECT, ML_BLOCKMAP = 8, 9


class StoreError(Exception):
    pass


def pack16(v: int) -> bytes:
    return (v & 0xFFFF).to_bytes(2, 'little')


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------

class Packer:
    """First fit into areas (bank, start, end); no block crosses a bank."""

    def __init__(self, banks: Sequence[int]):
        self.free: List[List[int]] = [[b, LL.ROOM[0], LL.ROOM[1]]
                                      for b in banks]

    def place(self, size: int, what: str) -> Tuple[int, int]:
        if size > LL.ROOM_BYTES:
            raise StoreError('%s: %d bytes do not fit a bank' % (what, size))
        for area in self.free:
            if area[2] - area[1] >= size:
                at = area[1]
                area[1] += size
                return area[0], at
        raise StoreError('%s: %d bytes: no room left' % (what, size))

    def slack(self) -> int:
        return sum(a[2] - a[1] for a in self.free)

    def used_banks(self) -> List[int]:
        return sorted(a[0] for a in self.free if a[1] > LL.ROOM[0])


class Banks:
    """RamWorks banks being filled (levelconv.Banks' rules)."""

    def __init__(self):
        self.b = LC.Banks()

    def put(self, bank: int, address: int, data: bytes) -> None:
        self.b.put(bank, address, data)

    def runs(self):
        for bank in sorted(self.b.data):
            for address, data in self.b.runs(bank):
                yield bank, address, data


# ---------------------------------------------------------------------------
# The maps' conversions and the in-play textures
# ---------------------------------------------------------------------------

class MapConv(NamedTuple):
    gamemap: int
    ld: U.Load
    level: LC.Level
    facts: Dict[str, Any]
    inplay: Dict[str, Any]
    columns: Dict[str, Dict[int, bytes]]    # 't' (or 'sky') -> col -> 128
    flagged: Dict[int, List[int]]           # t -> patchless columns
    widthmask: Dict[int, int]


def inplay_columns(ld: U.Load, textures: Sequence[int]
                   ) -> Tuple[Dict[int, Dict[int, bytes]],
                              Dict[int, List[int]], Dict[int, int]]:
    """The columns of the textures upstream makes only in play, made on a
    copy of the model after the load in their order (cold: into the holes
    first, else appended; needColumns' R_MakeTextureColumns)."""
    if not textures:
        return {}, {}, {}
    old = ld.columns
    mem = ld.mem.copy()
    cols = U.Columns.__new__(U.Columns)
    cols.__dict__.update(old.__dict__)
    cols.mem = mem
    cols.holes = [list(h) for h in old.holes]
    cols.lost_holes = list(old.lost_holes)
    cols.made = list(old.made)
    cols.loaded = set(old.loaded)
    cols.blocks = list(old.blocks)
    out, flagged, wms = {}, {}, {}
    for t in textures:
        cols.make(t)
        table, wm = cols.coldir(t)
        wms[t] = wm
        out[t] = {}
        flagged[t] = []
        for c in range(wm + 1):
            e = mem.read(table + 4 * c, 4)
            if e[3]:
                flagged[t].append(c)
                out[t][c] = bytes(SLOT)
                continue
            ptr = e[0] | e[1] << 8 | e[2] << 16
            out[t][c] = mem.read(ptr, SLOT)
    return out, flagged, wms


def convert_map(gd: U.GameData, gamemap: int) -> MapConv:
    ld = U.load(gd, gamemap)
    level, facts = WC.convert(gd, ld)
    inplay = WC.in_play(gd, ld, level)
    columns: Dict[str, Dict[int, bytes]] = {}
    flagged: Dict[int, List[int]] = {}
    wms: Dict[int, int] = {}
    info = level.info
    for t_text, e in info['textures'].items():
        t = int(t_text)
        wm = e['widthmask']
        wms[t] = wm
        flagged[t] = list(e['patchless'])
        columns[t_text] = {c: level.banks.get(e['bank'], e['base'] + SLOT * c,
                                              SLOT) for c in range(wm + 1)}
    sky = info['sky']
    columns['sky'] = {c: level.banks.get(sky['bank'], sky['base'] + SLOT * c,
                                         SLOT) for c in range(sky['columns'])}
    extra, xflag, xwm = inplay_columns(ld, [t['texture'] for t in
                                            inplay['textures']])
    for t, cols in extra.items():
        columns[str(t)] = cols
        flagged[t] = xflag[t]
        wms[t] = xwm[t]
    return MapConv(gamemap, ld, level, facts, inplay, columns, flagged, wms)


# ---------------------------------------------------------------------------
# The shared stores
# ---------------------------------------------------------------------------

def canonical(variants: Dict[int, bytes]) -> bytes:
    """The most common bytes over the maps (ties: the lowest map)."""
    counts = Counter(variants.values())
    best = max(counts.values())
    for m in sorted(variants):
        if counts[variants[m]] == best:
            return variants[m]
    raise StoreError('no variant')


class Shared(NamedTuple):
    tex_blocks: Dict[str, Tuple[int, int, int]]     # key -> bank, base, cols
    tex_canon: Dict[str, Dict[int, bytes]]
    lumps: Dict[int, Dict[str, Any]]                # lump -> entry
    index: Dict[int, int]                           # lump -> global index
    banks: Banks
    tex_packer: Packer
    spr_packer: Packer
    variants: Dict[int, List[Dict[str, Any]]]       # map -> [variant]
    wpro: Dict[str, Any]


def build_shared(gd: U.GameData, convs: Dict[int, MapConv]) -> Shared:
    banks = Banks()
    # -- texels
    keys = sorted({k for mc in convs.values() for k in mc.columns},
                  key=lambda k: (k != 'sky', int(k) if k != 'sky' else 0))
    canon: Dict[str, Dict[int, bytes]] = {}
    for key in keys:
        ncols = {len(mc.columns[key]) for mc in convs.values()
                 if key in mc.columns}
        if len(ncols) != 1:
            raise StoreError('texture %s has %s columns in the maps'
                             % (key, sorted(ncols)))
        canon[key] = {}
        for c in range(ncols.pop()):
            canon[key][c] = canonical({m: mc.columns[key][c]
                                       for m, mc in convs.items()
                                       if key in mc.columns})
    tex_packer = Packer(LL.TEX_BANKS)
    blocks: Dict[str, Tuple[int, int, int]] = {}
    for key in sorted(keys, key=lambda k: (-len(canon[k]), keys.index(k))):
        n = len(canon[key])
        bank, base = tex_packer.place(SLOT * n, 'texture %s' % key)
        blocks[key] = (bank, base, n)
        for c in range(n):
            banks.put(bank, base + SLOT * c, canon[key][c])
    # -- the patch store
    lumps: Dict[int, Dict[str, Any]] = {}
    tails: Dict[int, Dict[int, bytes]] = {}
    for m, mc in convs.items():
        for e in mc.level.info['sprites']['store']:
            data = mc.level.banks.get(e['bank'], e['at'], e['size'] + TAIL)
            body, tail = data[:e['size']], data[e['size']:]
            got = lumps.setdefault(e['lump'], {'lump': e['lump'],
                                               'name': e['name'],
                                               'size': e['size'],
                                               'body': body})
            if got['body'] != body:
                raise StoreError('lump %d differs between maps' % e['lump'])
            tails.setdefault(e['lump'], {})[m] = tail
    order = sorted(lumps)
    index = {lump: k + 1 for k, lump in enumerate(order)}
    if len(order) + 1 > R.PHDRS.capacity:
        raise StoreError('%d patches: PHDR holds %d' % (len(order) + 1,
                                                       R.PHDRS.capacity))
    spr_packer = Packer(LL.SPR_BANKS)
    for lump in sorted(order, key=lambda x: (-lumps[x]['size'], x)):
        e = lumps[lump]
        e['tail'] = canonical(tails[lump])
        bank, at = spr_packer.place(e['size'] + TAIL, 'lump %d' % lump)
        e['bank'], e['at'] = bank, at
        e['index'] = index[lump]
        banks.put(bank, at, e['body'] + e['tail'])
    # PHDR (global)
    any_conv = convs[min(convs)]
    m0 = any_conv.ld.mem
    phdr = bytearray()

    def header(read_at: int, bank_: int, where: int, lump: int) -> bytes:
        rec = bytearray(R.PHDR_SIZE)
        src = m0.read(read_at, 8)
        for k, key in (('WIDTH', 0), ('LEFT', 4), ('TOP', 6)):
            rec[R.PHDR[k]:R.PHDR[k] + 2] = src[key:key + 2]
        rec[R.PHDR['BANK']] = bank_
        rec[R.PHDR['ADDR']:R.PHDR['ADDR'] + 2] = pack16(where)
        rec[R.PHDR['LUMP']:R.PHDR['LUMP'] + 2] = pack16(lump)
        return bytes(rec)
    phdr += header(any_conv.ld.placeholder, 0, 0, 0xFFFF)
    for lump in order:
        e = lumps[lump]
        rec = bytearray(R.PHDR_SIZE)
        for k, key in (('WIDTH', 0), ('LEFT', 4), ('TOP', 6)):
            rec[R.PHDR[k]:R.PHDR[k] + 2] = e['body'][key:key + 2]
        rec[R.PHDR['BANK']] = e['bank']
        rec[R.PHDR['ADDR']:R.PHDR['ADDR'] + 2] = pack16(e['at'])
        rec[R.PHDR['LUMP']:R.PHDR['LUMP'] + 2] = pack16(lump)
        phdr += rec
    banks.put(R.SPRT, R.PHDRS.base, bytes(phdr))
    # WPRO (global): wadconv.weapon_part over the global indexes, from the
    # stored bytes (a lump's bytes are the same in every map)
    sym = U.symbols()
    frames = []
    defs = WC.sprite_defs(gd)
    nframes = LC.sprite_frames(m0, sym)
    for s in range(R.NUMSPRITES):
        for f in range(nframes[s]):
            if f < len(defs[s]):
                fr = defs[s][f]
                frames.append((s, f, fr.rotate, fr.flip, fr.lumps if
                               fr.rotate else fr.lumps[:1], True))
    wbanks = LC.Banks()
    store_mem = gd.rel.memory.copy()      # (states, weaponinfo)
    for lump in order:
        e = lumps[lump]
        store_mem.write(e['bank'] << 16 | e['at'], e['body'] + e['tail'])

    class StoreLoad:
        mem = store_mem
        lump_addr = {lump: lumps[lump]['bank'] << 16 | lumps[lump]['at']
                     for lump in order}
    wpro = WC.weapon_part(StoreLoad, sym, frames, index,
                          lambda lump: lump in lumps, wbanks,
                          gd.rel.names)
    for address, data in wbanks.runs(R.WPRO):
        banks.put(R.WPRO, address, data)
    wpro.pop('checks')
    # -- the variants of each map
    variants: Dict[int, List[Dict[str, Any]]] = {}
    for m, mc in convs.items():
        out = []
        for key, cols in mc.columns.items():
            bank, base, _ = blocks[key]
            for c, data in sorted(cols.items()):
                if data != canon[key][c]:
                    out.append({'what': '%s:%d' % (key, c), 'bank': bank,
                                'address': base + SLOT * c, 'data': data,
                                'canonical': canon[key][c]})
        for e in mc.level.info['sprites']['store']:
            g = lumps[e['lump']]
            tail = tails[e['lump']][m]
            if tail != g['tail']:
                out.append({'what': 'tail %s' % e['name'], 'bank': g['bank'],
                            'address': g['at'] + g['size'], 'data': tail,
                            'canonical': g['tail']})
        variants[m] = out
    return Shared(blocks, canon, lumps, index, banks, tex_packer, spr_packer,
                  variants, wpro)


# ---------------------------------------------------------------------------
# A map's level part
# ---------------------------------------------------------------------------

BLOCK_KINDS = ('SEGS', 'NODES', 'SUBS', 'SECTORS', 'SIDES', 'TXFLAT',
               'LINES', 'SECC', 'BLOCKMAP', 'REJECT', 'THINGS', 'WTAB',
               'TXMP', 'SPRFR', 'GSVIEW', 'FUZZ', 'APPLY', 'UNDO',
               'APPLYREQ', 'UNDOREQ', 'PROGRAM')
# the blocks placed after the others (they name the others' places)
LATE_KINDS = ('APPLYREQ', 'UNDOREQ', 'PROGRAM')
HEADER_SIZE = 4 + 2 * 11 + 6 * len(BLOCK_KINDS) + 8 + 2 + 8 + 3 + 4


class Part:
    """A map's level part: its blocks, its header, its load program."""

    def __init__(self, gamemap: int):
        self.gamemap = gamemap
        self.blocks: Dict[str, bytes] = {}
        self.where: Dict[str, Tuple[int, int]] = {}
        self.header: Dict[str, Any] = {}
        self.requests: List[List[bytes]] = []
        self.steps: List[Tuple[str, int]] = []


def thing_kind(mobjinfo: bytes, kind: int, options: int) -> int:
    """The map thing's mobj type as P_SpawnMapThing finds it (type 1: the
    player; a thing with no skill flag: never; else P_FindDoomedNum)."""
    if kind == 1:
        return LL.MT_PLAYER_START
    if not options & MTF_SKILLS:
        return LL.MT_NEVER
    for i in range(NUMMOBJTYPES):
        if struct.unpack_from('<h', mobjinfo, LL.INFO_SIZE * i)[0] == kind:
            return i
    raise StoreError('a map thing of the unknown type %d' % kind)


def build_part(gd: U.GameData, mc: MapConv, sh: Shared) -> Part:
    m = mc.gamemap
    part = Part(m)
    level = mc.level
    game = mc.ld.game
    hb = level.banks
    c = level.info['counts']
    # -- LVSEG, LVMAP: the renderer's level images (the same records)
    segs = hb.get(R.LVSEG, R.SEGS.base, R.SEG_SIZE * c['segs'])
    nodes = hb.get(R.LVMAP, R.NODES.base, R.NODE_SIZE * c['nodes'])
    subs = bytearray(hb.get(R.LVMAP, R.SUBS.base, R.SUB_SIZE * c['subsectors']))
    sectors = hb.get(R.LVMAP, R.SECTORS.base, R.SEC_SIZE * c['sectors'])
    sides = hb.get(R.LVMAP, R.SIDES.base, R.SIDE_SIZE * c['sides'])
    # TXFLAT and the W tables for every texture the map can show
    can_show = sorted({int(k) for k in mc.columns if k != 'sky'})
    txbank, txlo, txhi = bytearray(256), bytearray(256), bytearray(256)
    txwm = bytearray(level.wtables[R.TXWM])
    flat_index = bytearray(b'\xff' * 256)
    flat_maps = bytearray()
    for t in can_show:
        bank, base, n = sh.tex_blocks[str(t)]
        txbank[t], txlo[t], txhi[t] = bank, base & 0xFF, base >> 8
        if txwm[t] not in (0, mc.widthmask[t]):
            raise StoreError('texture %d: two width masks' % t)
        txwm[t] = mc.widthmask[t]
        if mc.flagged[t]:
            k = len(flat_maps) // 32
            bitmap = bytearray(32)
            for col in mc.flagged[t]:
                bitmap[col >> 3] |= 1 << (col & 7)
            flat_maps += bitmap
            flat_index[t] = k
            txbank[t] |= 0x80
    txflat = bytes(flat_index) + bytes(flat_maps)
    if len(txflat) > R.TXFLAT_END - R.TXFLAT:
        raise StoreError('TXFLAT holds %d bitmaps' % len(flat_maps))
    wtab = level.wtables[R.FLATCM] + bytes(txbank) + bytes(txlo) + \
        bytes(txhi) + bytes(txwm) + level.wtables[R.TXHT]
    # TXMP and SPRFR with the global indexes
    local = {e['index']: e['lump'] for e in level.info['sprites']['store']}

    def glob(k: int) -> int:
        return 0 if k == 0 else sh.index[local[k]]
    mt = level.mtables[R.TXMP]
    txmp_lo, txmp_hi = bytearray(mt[:256]), bytearray(mt[256:])
    for t in range(256):
        k = txmp_lo[t] | txmp_hi[t] << 8
        if k != 0xFFFF:
            g = glob(k)
            txmp_lo[t], txmp_hi[t] = g & 0xFF, g >> 8
    nfr = sum(level.info['sprites']['frames_per_sprite'])
    sprfr = bytearray(hb.get(R.SPRT, R.SPRFRS.base, R.SPRFR_SIZE * nfr))
    for k in range(nfr):
        at = R.SPRFR_SIZE * k + R.SPRFR['LUMPS']
        for r in range(8):
            v = sprfr[at + 2 * r] | sprfr[at + 2 * r + 1] << 8
            sprfr[at + 2 * r:at + 2 * r + 2] = pack16(glob(v))
    # the compact lines, sectors, things; the blockmap and reject
    lines = game.lumps['LINEDEFS']
    secc = b''.join(struct.pack('<bh', s[5], s[6]) for s in
                    game.sector_list())
    mobjinfo = gd.rel.table('mobjinfo', NUMMOBJTYPES * LL.INFO_SIZE)
    things = bytearray()
    for x, y, kind, angle, options in game.thing_list():
        rec = bytearray(LL.MTHING_SIZE)
        rec[0:2], rec[2:4] = pack16(x), pack16(y)
        rec[LL.MTHING['ANGLE']] = angle & 0xFF
        rec[LL.MTHING['OPTIONS']] = options & 0xFF
        rec[LL.MTHING['KIND']] = thing_kind(mobjinfo, kind, options & 0xFF)
        things += rec
    gsview = WC.lump_bytes(mc.ld, gd.rel.index('GSVIEW%d' % m))
    if len(gsview) != LL.GSVIEW_SIZE:
        raise StoreError('GSVIEW%d is %d bytes' % (m, len(gsview)))
    var = sh.variants[m]
    apply = b''.join(struct.pack('<BH', v['bank'], v['address']) + v['data']
                     for v in var)
    undo = b''.join(struct.pack('<BH', v['bank'], v['address']) +
                    v['canonical'] for v in var)
    subs_store = bytearray(subs)
    for i in range(c['subsectors']):
        subs_store[R.SUB_SIZE * i + R.SUB['SECTOR']] = 0xFF
    part.blocks = {
        'SEGS': segs, 'NODES': nodes, 'SUBS': bytes(subs_store),
        'SECTORS': sectors, 'SIDES': sides, 'TXFLAT': txflat,
        'LINES': lines, 'SECC': secc, 'BLOCKMAP': game.lumps['BLOCKMAP'],
        'REJECT': game.lumps['REJECT'], 'THINGS': bytes(things),
        'WTAB': wtab, 'TXMP': bytes(txmp_lo) + bytes(txmp_hi),
        'SPRFR': bytes(sprfr), 'GSVIEW': gsview, 'FUZZ': level.fuzzdark,
        'APPLY': apply, 'UNDO': undo}
    # -- the game part's tables (LVG0-2)
    group = LD.Group(game)
    flood = LD.Flood(game, group)
    at = LL.SECGS.base + LL.SECG_SIZE * len(game.sector_list())
    ltab = b''.join(pack16(i) for t in group.tables for i in t)
    flidx, flent = flood.layout()
    bm = game.lumps['BLOCKMAP']
    _, _, bcols, brows = struct.unpack_from('<hhhh', bm, 0)
    nblocks = bcols * brows
    bases = {}
    for name, data in (('LTAB', ltab), ('FLIDX', flidx), ('FLENT', flent),
                       ('BLINKS', b'\xff\xff' * nblocks)):
        bases[name] = at
        at += len(data)
    if at > LL.ROOM[1]:
        raise StoreError('LVG1 needs $%04X' % at)
    reject_at = LL.BLOCKMAP + len(bm)
    if reject_at + len(game.lumps['REJECT']) > LL.ROOM[1]:
        raise StoreError('LVG2: the blockmap and reject pass $BFFF')
    orgx, orgy = struct.unpack_from('<hh', bm, 0)
    part.header = {
        'map': m, 'counts': dict(c, things=len(things) // LL.MTHING_SIZE,
                                 blocks=nblocks, linetable=group.entries,
                                 flood=len(flent)),
        'lvg1': bases, 'reject': reject_at,
        'blockmap': {'orgx': orgx, 'orgy': orgy, 'columns': bcols,
                     'rows': brows},
        'sky': list(sh.tex_blocks['sky'][:2]),
        'lumps': {'BLOCKMAP': gd.rel.index('E1M%d' % m) + ML_BLOCKMAP,
                  'REJECT': gd.rel.index('E1M%d' % m) + ML_REJECT},
        'variants': len(var), 'can_show': can_show}
    return part


# ---------------------------------------------------------------------------
# The load program (docs/LEVELS.md)
# ---------------------------------------------------------------------------

def descriptor(op: int, src: Optional[Tuple[int, int, int]],
               dst: Tuple[int, int, int], size: int, fill: int = 0
               ) -> bytes:
    """A memory-API descriptor: endpoints (space, bank, address): space 0
    main (bank 0), 1 a RamWorks bank; PRIVATE when the destination is
    main or aux 0."""
    for e in ([src] if src else []) + [dst]:
        space, bank, address = e
        if space > 1 or (space == 0 and bank) or bank > 126 or \
                address < LL.ROOM[0] or address + size > LL.ROOM[1] or \
                not size:
            raise StoreError('a descriptor endpoint %r of %d bytes' % (e,
                                                                      size))
    flags = LL.AMEM_PRIVATE if dst[0] == 0 or dst[1] == 0 else 0
    d = bytearray(16)
    d[0], d[1] = op, flags
    if src:
        d[2], d[3] = src[0], src[1]
        d[4:6] = pack16(src[2])
    d[6], d[7] = dst[0], dst[1]
    d[8:10] = pack16(dst[2])
    d[10:12] = pack16(size)
    d[12] = fill
    return bytes(d)


def requests_of(copies: List[Tuple[Optional[Tuple[int, int, int]],
                                   Tuple[int, int, int], int, int]]
                ) -> List[List[bytes]]:
    """Copies and fills grouped into requests (16 descriptors and
    REQUEST_BYTES of data at most), each split where it must."""
    out: List[List[bytes]] = []
    cur: List[bytes] = []
    size = 0
    for src, dst, n, fill in copies:
        done = 0
        while done < n:
            room = LL.REQUEST_BYTES - size
            if len(cur) == LL.AMEM_MAX or room <= 0:
                out.append(cur)
                cur, size = [], 0
                room = LL.REQUEST_BYTES
            k = min(n - done, room)
            s = None if src is None else (src[0], src[1], src[2] + done)
            d = (dst[0], dst[1], dst[2] + done)
            cur.append(descriptor(LL.AMEM_COPY if src else LL.AMEM_FILL,
                                  s, d, k, fill))
            size += k
            done += k
    if cur:
        out.append(cur)
    return out


def requests_bytes(reqs: Sequence[Sequence[bytes]]) -> bytes:
    """A list of requests: their count, then each request's descriptor
    count and descriptors."""
    out = bytearray([len(reqs)])
    for req in reqs:
        out += bytes([len(req)]) + b''.join(req)
    return bytes(out)


def variant_requests(part: Part, kind: str) -> bytes:
    """The memory-API COPY requests of a variant list (APPLY or UNDO, as
    placed: 3 bytes of bank and address, then 128 bytes, a variant): one
    descriptor a variant, from the list's bytes to its place in the
    shared stores (docs/LEVELS.md)."""
    bank, at = part.where.get(kind, (0, 0))
    data = part.blocks[kind]
    copies = []
    k = 0
    while k < len(data):
        dbank, daddr = struct.unpack_from('<BH', data, k)
        copies.append(((1, bank, at + k + 3), (1, dbank, daddr), SLOT, 0))
        k += 3 + SLOT
    return requests_bytes(requests_of(copies) if copies else [])


def program(part: Part) -> None:
    """The steps and the requests of a map's load from its placed
    blocks (part.where)."""
    w = part.where
    h = part.header
    c = h['counts']
    copies = []

    def cp(block: str, dst: Tuple[int, int, int]) -> None:
        if part.blocks[block]:
            bank, at = w[block]
            copies.append(((1, bank, at), dst, len(part.blocks[block]), 0))
    cp('SEGS', (1, R.LVSEG, R.SEGS.base))
    cp('NODES', (1, R.LVMAP, R.NODES.base))
    cp('SUBS', (1, R.LVMAP, R.SUBS.base))
    for plane in (R.VAL, R.VAH, R.VAS):
        copies.append((None, (1, R.LVMAP, plane), c['vertices'], 0))
    cp('SECTORS', (1, R.LVMAP, R.SECTORS.base))
    cp('SIDES', (1, R.LVMAP, R.SIDES.base))
    cp('TXFLAT', (1, R.LVMAP, R.TXFLAT))
    cp('BLOCKMAP', (1, LL.LVG2, LL.BLOCKMAP))
    cp('REJECT', (1, LL.LVG2, h['reject']))
    if c['blocks']:
        copies.append((None, (1, LL.LVG1, h['lvg1']['BLINKS']),
                       2 * c['blocks'], 0xFF))
    cp('SPRFR', (1, R.SPRT, R.SPRFRS.base))
    bank, at = w['WTAB']
    copies.append(((1, bank, at), (1, R.WCODE_BANK, R.FLATCM), 34 * 32, 0))
    copies.append(((1, bank, at + 34 * 32), (1, R.WCODE_BANK, R.TXBANK),
                   5 * 256, 0))
    cp('TXMP', (1, R.MCODE_BANK, R.TXMP))
    cp('GSVIEW', (1, LL.LVC, LL.LVC_GSVIEW))
    cp('FUZZ', (1, LL.LVC, LL.LVC_FUZZ))
    reqs = requests_of(copies)
    low, high = LL.CMAP_LOW, LL.CMAP_SIZE - LL.CMAP_LOW
    hb, ha = w['HEADER']
    priv = requests_of([
        ((1, hb, ha + 4), (0, 0, R.LVCOUNT), 4, 0),
        ((1, hb, ha + 8), (0, 0, LL.LVCOUNT2), 8, 0),
        ((1, LL.LVC, LL.LVC_CMAPA), (0, 0, LL.MAIN_CMAPA), low, 0),
        ((1, LL.LVC, LL.LVC_CMAPB), (0, 0, LL.MAIN_CMAPB), low, 0),
        ((1, LL.LVC, LL.LVC_CMAPA + low), (0, 0, LL.MAIN_CMAPA_HI), high, 0),
        ((1, LL.LVC, LL.LVC_CMAPB + low), (0, 0, LL.MAIN_CMAPB_HI), high, 0),
        ((1, LL.LVC, LL.LVC_FUZZ), (1, 0, LL.AUX0_FUZZ), 256, 0)])
    part.requests = reqs + priv
    steps = [('VARIANTS', part.gamemap)]
    steps += [('COPYREQ', k) for k in range(len(reqs))]
    steps += [('LINES', 0), ('GROUP', 0), ('FLOOD', 0), ('CMAPS', 0)]
    steps += [('PRIVREQ', len(reqs) + k) for k in range(len(priv))]
    # GTABS (LVS's tables) before the spawn, which reads them
    steps += [('GTABS', 0), ('SPAWN', 0), ('SPECIALS', 0), ('END', 0)]
    part.steps = steps


def program_bytes(part: Part) -> bytes:
    """The program block: 'LP', the map, the step count, the request
    count; the steps (opcode, argument word); each request (its
    descriptor count, then the descriptors)."""
    out = bytearray(b'LP') + bytes([part.gamemap, len(part.steps),
                                    len(part.requests), 0])
    for name, arg in part.steps:
        out += bytes([LL.STEPS[name]]) + pack16(arg)
    for req in part.requests:
        out += bytes([len(req)]) + b''.join(req)
    return bytes(out)


def header_bytes(part: Part) -> bytes:
    """The map's header: its counts and every block's bank, address and
    length (BLOCK_KINDS' order), the LVG1 bases, REJECT's address, the
    blockmap's origin and size, the sky block (bank, address), and
    the BLOCKMAP and REJECT lumps' numbers in the release's directory."""
    h = part.header
    c = h['counts']
    out = bytearray(b'LH') + bytes([part.gamemap, 0])
    for k in ('sectors', 'sides', 'lines', 'subsectors', 'segs', 'nodes',
              'vertices', 'things', 'blocks', 'linetable', 'flood'):
        out += pack16(c[k])
    for kind in BLOCK_KINDS:
        bank, at = part.where.get(kind, (0, 0))
        n = len(part.blocks.get(kind, b''))
        out += bytes([bank, LL.CODEC_RAW]) + pack16(at) + pack16(n)
    for k in ('LTAB', 'FLIDX', 'FLENT', 'BLINKS'):
        out += pack16(h['lvg1'][k])
    out += pack16(h['reject'])
    b = h['blockmap']
    out += pack16(b['orgx']) + pack16(b['orgy']) + pack16(b['columns']) + \
        pack16(b['rows'])
    out += bytes([h['sky'][0]]) + pack16(h['sky'][1])
    out += pack16(h['lumps']['BLOCKMAP']) + pack16(h['lumps']['REJECT'])
    if len(out) != LL.LH_SIZE:
        raise StoreError('a header of %d bytes, not %d' % (len(out),
                                                            LL.LH_SIZE))
    return bytes(out)


# ---------------------------------------------------------------------------
# The whole store
# ---------------------------------------------------------------------------

def gtab(gd: U.GameData) -> bytes:
    rel = gd.rel
    parts = {
        'STATES': rel.table('states', LL.NUMSTATES * LL.STATE_SIZE),
        'MOBJINFO': rel.table('mobjinfo', LL.NUMMOBJTYPES * LL.INFO_SIZE),
        'COLORMAP': gd.wad_by_name['COLORMAP'][:34 * 256],
        'SWITCHLIST': b''.join(pack16(t) for t in gd.switchlist),
        'SW_IDX': gd.sw_idx,
        'BASEPIC': pack16(gd.basepic)}
    out = bytearray()
    for name, (at, size) in sorted(LL.GT.items(), key=lambda x: x[1][0]):
        if len(parts[name]) != size or at != LL.ROOM[0] + len(out):
            raise StoreError('GTAB %s' % name)
        out += parts[name]
    return bytes(out)


def bank_file(segments: Sequence[Tuple[int, int, bytes]]) -> bytes:
    if not 1 <= len(segments) <= LL.BANKFILE_MAX_SEGS:
        raise StoreError('%d segments in a bank file' % len(segments))
    head = bytearray(LL.BANKFILE_MAGIC) + bytes([1, len(segments), 0, 0])
    for bank, address, data in segments:
        if not 1 <= bank <= 126 or address < LL.ROOM[0] or \
                address + len(data) > LL.ROOM[1] or not data:
            raise StoreError('a segment of bank %d at $%04X' % (bank,
                                                                address))
        head += bytes([bank]) + pack16(address) + pack16(len(data))
    if len(head) > 256:
        raise StoreError('the bank file header passes 256 bytes')
    head += bytes(256 - len(head))
    return bytes(head) + b''.join(d for _, _, d in segments)


def read_bank_file(data: bytes) -> List[Tuple[int, int, bytes]]:
    if data[:4] != LL.BANKFILE_MAGIC or data[4] != 1:
        raise StoreError('not a bank file')
    n = data[5]
    out, at = [], 256
    for k in range(n):
        bank, address, length = struct.unpack_from('<BHH', data, 8 + 5 * k)
        out.append((bank, address, data[at:at + length]))
        at += length
    if at != len(data):
        raise StoreError('a bank file of %d bytes, %d read' % (len(data), at))
    return out


def build(gd: U.GameData, maps: Sequence[int] = MAPS) -> Dict[str, Any]:
    convs = {m: convert_map(gd, m) for m in maps}
    sh = build_shared(gd, convs)
    parts = {m: build_part(gd, convs[m], sh) for m in maps}
    # the level parts: the texel banks' slack first, then STORE
    packer = Packer(list(LL.TEX_BANKS) + list(LL.STORE_BANKS))
    packer.free = [list(a) for a in sh.tex_packer.free] + \
        [[b, LL.ROOM[0], LL.ROOM[1]] for b in LL.STORE_BANKS]
    store = Banks()                     # the level parts, GTAB
    # the directory: STORE0's first bytes, the fixed place the loader
    # reads (llayout.STORE_DIR)
    if len(maps) > LL.STORE_DIR_MAPS:
        raise StoreError('%d maps: the directory holds %d'
                         % (len(maps), LL.STORE_DIR_MAPS))
    dir_bank, dir_at = LL.STORE_DIR_BANK, LL.STORE_DIR
    for area in packer.free:
        if area[0] == dir_bank:
            if area[1] != dir_at:
                raise StoreError('the directory\'s place is taken')
            area[1] = dir_at + LL.STORE_DIR_SIZE
    for m in maps:
        part = parts[m]
        order = sorted((k for k in BLOCK_KINDS if part.blocks.get(k) and
                        k not in LATE_KINDS),
                       key=lambda k: -len(part.blocks[k]))
        for kind in order:
            part.where[kind] = packer.place(len(part.blocks[kind]),
                                            'E1M%d %s' % (m, kind))
        # the header's place first (the program copies its counts), then
        # the program, then the header's bytes (they name the program)
        part.where['HEADER'] = packer.place(HEADER_SIZE, 'E1M%d header' % m)
        for kind, data in (('APPLYREQ', 'APPLY'), ('UNDOREQ', 'UNDO')):
            part.blocks[kind] = variant_requests(part, data)
            part.where[kind] = packer.place(len(part.blocks[kind]),
                                            'E1M%d %s' % (m, kind))
        program(part)
        part.blocks['PROGRAM'] = program_bytes(part)
        part.where['PROGRAM'] = packer.place(len(part.blocks['PROGRAM']),
                                             'E1M%d program' % m)
        part.blocks['HEADER'] = header_bytes(part)
        if len(part.blocks['HEADER']) != HEADER_SIZE:
            raise StoreError('the header is %d bytes'
                             % len(part.blocks['HEADER']))
        for kind, (bank, at) in part.where.items():
            store.put(bank, at, part.blocks[kind])
    directory = bytearray(LL.STORE_MAGIC) + bytes([LL.STORE_VERSION,
                                                   len(maps)]) + bytes(10)
    for m in maps:
        bank, at = parts[m].where['HEADER']
        directory += bytes([m, bank]) + pack16(at)
    store.put(dir_bank, dir_at, bytes(directory))
    gt = gtab(gd)
    store.put(LL.GTAB, LL.ROOM[0], gt)
    return {'convs': convs, 'shared': sh, 'parts': parts, 'store': store,
            'directory': (dir_bank, dir_at), 'packer': packer}


def write(result: Dict[str, Any], out: Path = STORE) -> Dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    store: Banks = result['store']
    sh: Shared = result['shared']
    parts: Dict[int, Part] = result['parts']
    groups: Dict[str, List[Tuple[int, int, bytes]]] = {
        'TEXELS': [], 'PATCHES': [], 'MAPS': [], 'TABLES': []}
    for bank, address, data in sh.banks.runs():
        if bank in LL.TEX_BANKS:
            groups['TEXELS'].append((bank, address, data))
        elif bank in LL.SPR_BANKS or bank in (R.SPRT, R.WPRO):
            groups['PATCHES'].append((bank, address, data))
        else:
            raise StoreError('bank %d of the shared stores' % bank)
    for bank, address, data in store.runs():
        groups['TABLES' if bank == LL.GTAB else 'MAPS'].append(
            (bank, address, data))
    written = {}
    for name, segs in groups.items():
        k = 0
        while segs:
            chunk, segs = segs[:LL.BANKFILE_MAX_SEGS], \
                segs[LL.BANKFILE_MAX_SEGS:]
            k += 1
            data = bank_file(chunk)
            path = out / ('%s.%d' % (name, k))
            path.write_bytes(data)
            written[path.name] = {'bytes': len(data), 'segments': len(chunk),
                                  'sha256': hashlib.sha256(data).hexdigest()}
    maps_json = {}
    for m, part in sorted(parts.items()):
        maps_json['E1M%d' % m] = {
            'header': part.header,
            'blocks': {k: {'bank': part.where[k][0],
                           'address': part.where[k][1],
                           'length': len(part.blocks[k]),
                           'codec': LL.CODEC_RAW}
                       for k in part.where},
            'level_part_bytes': sum(len(v) for v in part.blocks.values()),
            'steps': part.steps,
            'requests': len(part.requests),
            'request_bytes': sum(struct.unpack_from('<H', d_, 10)[0]
                                 for r in part.requests for d_ in r),
            'variants': [{'what': v['what'], 'bank': v['bank'],
                          'address': v['address']}
                         for v in sh.variants[m]]}
    tex_bytes = sum(SLOT * n for _, _, n in sh.tex_blocks.values())
    spr_bytes = sum(e['size'] + TAIL for e in sh.lumps.values())
    packer: Packer = result['packer']
    store_used = sorted({b for b, _, _ in store.runs()
                         if b in LL.STORE_BANKS})
    level_parts = sum(m_['level_part_bytes'] for m_ in maps_json.values())
    tex_used = sh.tex_packer.used_banks()
    spr_used = sh.spr_packer.used_banks()
    tally = {
        'texel_store': {'blocks': len(sh.tex_blocks), 'bytes': tex_bytes,
                        'banks': len(tex_used), 'of': len(LL.TEX_BANKS),
                        'slack': sh.tex_packer.slack(),
                        'slack_after_level_parts': sum(
                            a[2] - a[1] for a in packer.free
                            if a[0] in LL.TEX_BANKS)},
        'patch_store': {'lumps': len(sh.lumps), 'bytes': spr_bytes,
                        'banks': len(spr_used), 'of': len(LL.SPR_BANKS)},
        'level_parts': {'bytes': level_parts, 'store_banks': len(store_used),
                        'of': len(LL.STORE_BANKS)},
        'variants': {m: len(v) for m, v in sh.variants.items()},
        'variant_columns': sum(1 for v in sh.variants.values() for x in v
                               if not x['what'].startswith('tail')),
        'variant_tails': sum(1 for v in sh.variants.values() for x in v
                             if x['what'].startswith('tail')),
        'banks_used_of_126': LL.used_banks(),
        'spare': list(LL.SPARE),
    }
    meta = {'format': FORMAT, 'files': written, 'maps': maps_json,
            'directory': list(result['directory']), 'tally': tally,
            'texel_blocks': {k: list(v) for k, v in sh.tex_blocks.items()},
            'wpro': sh.wpro}
    (out / 'store.json').write_text(json.dumps(meta, indent=1) + '\n')
    return meta


def main_store(gd: U.GameData) -> int:
    try:
        result = build(gd)
        meta = write(result)
    except (StoreError, WC.ConvError, U.ModelError) as error:
        print('the store: FAILED: %s' % error)
        return 1
    t = meta['tally']
    print('texel store: %d blocks, %d bytes, %d of %d banks' % (
        t['texel_store']['blocks'], t['texel_store']['bytes'],
        t['texel_store']['banks'], t['texel_store']['of']))
    print('patch store: %d lumps, %d bytes, %d of %d banks' % (
        t['patch_store']['lumps'], t['patch_store']['bytes'],
        t['patch_store']['banks'], t['patch_store']['of']))
    print('level parts: %d bytes, %d of %d STORE banks; variants: %d '
          'columns, %d tails' % (
              t['level_parts']['bytes'], t['level_parts']['store_banks'],
              t['level_parts']['of'], t['variant_columns'],
              t['variant_tails']))
    for name, f in sorted(meta['files'].items()):
        print('  %s: %d bytes, %d segments' % (name, f['bytes'],
                                               f['segments']))
    return 0
