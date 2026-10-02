"""The native level store (milestone 9, docs/LEVELS.md 1.3-1.7, 2.2): its
format, its builder from wadconv.py's conversions, its reader.

    python3 tools/native/wadconv.py --store

builds, in build/native/levels/store/:

    TEXELS.1, PATCHES.1, MAPS.1, TABLES.1
                 bank files (demos/doom/src/kernel/loader.s's format: "A2DM",
                 version 1, a segment count, 5 bytes a segment: bank,
                 address, length; zero padding to 256 bytes; the bytes)
    store.json   every block (bank, address, length, codec), the shared
                 stores, each map's level part and load program, the
                 apply and undo variant lists, the bank tally
    e1mN/window.img, e1mN/mask.img
                 the expected state after the load of map N
                 (docs/LEVELS.md 6.1): A2VMIMG1 records of every byte the
                 loader leaves in the level window (LVSEG, LVMAP, LVG0-2,
                 LVC, SPRT's PHDR and SPRFR, the W tables in CODE banks
                 112 and 113, main's colormaps, aux 0's FUZZDARK,
                 LV_VARMAP) and of every byte of the shared stores the
                 variants change; the stores' other bytes are the bank
                 files'. mask.img: $FF on each byte stage C writes (the
                 spawn, the specials, the sector nodes' stamps)
    e1mN/texmap.json, e1mN/patchmap.json
                 each harness slot (levelconv.py's "t:c", "sky:c") and
                 each stored lump with its game-layout bank and address
                 and its upstream address, for stage B's read-back

The shared stores (docs/LEVELS.md 1.3, 1.4):

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
of the same places), and its load program: the steps of docs/LEVELS.md
2.2 and the memory-API requests (llayout.py: COPY and FILL descriptors,
PRIVATE for main and aux 0, at most 16 a request and 45 KB of data).
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
    maplumps as ML, rlayout as R, umodel as U, wadconv as WC  # noqa: E402

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
    """A map's level part: its blocks, its expected window."""

    def __init__(self, gamemap: int):
        self.gamemap = gamemap
        self.blocks: Dict[str, bytes] = {}
        self.where: Dict[str, Tuple[int, int]] = {}
        self.header: Dict[str, Any] = {}
        self.window = Banks()               # RamWorks banks
        self.main: Dict[int, bytes] = {}    # main memory
        self.aux0: Dict[int, bytes] = {}    # aux bank 0
        self.mask = Banks()
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
    # -- LVSEG, LVMAP: the harness images (the same records)
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
    # -- the expected window
    W = part.window
    W.put(R.LVSEG, R.SEGS.base, segs)
    if nodes:
        W.put(R.LVMAP, R.NODES.base, nodes)
    W.put(R.LVMAP, R.SUBS.base, bytes(subs))
    for plane in (R.VAL, R.VAH, R.VAS):
        W.put(R.LVMAP, plane, bytes(c['vertices']))
    W.put(R.LVMAP, R.SECTORS.base, sectors)
    W.put(R.LVMAP, R.SIDES.base, sides)
    W.put(R.LVMAP, R.TXFLAT, txflat)
    group = LD.Group(game)
    flood = LD.Flood(game, group)
    lvg0 = b''.join(LD.line_record(LD.line_fields(ln)) for ln in game.lines)
    W.put(LL.LVG0, LL.LINES.base, lvg0)
    secg = bytearray()
    for s, (fh, ch, fp, cp, light, special, tag) in enumerate(
            game.sector_list()):
        rec = bytearray(LL.SECG_SIZE)
        S = LL.SECG
        rec[S['SOUNDX']:S['SOUNDX'] + 4] = struct.pack(
            '<i', group.soundorg[s][0])
        rec[S['SOUNDY']:S['SOUNDY'] + 4] = struct.pack(
            '<i', group.soundorg[s][1])
        rec[S['TARGET']:S['TARGET'] + 2] = pack16(LL.NO_HANDLE)
        rec[S['LCOUNT']:S['LCOUNT'] + 2] = pack16(len(group.tables[s]))
        rec[S['LFIRST']:S['LFIRST'] + 2] = pack16(group.first[s])
        for k in ('FLOORD', 'CEILD', 'TOUCH'):
            rec[S[k]:S[k] + 2] = pack16(LL.NO_HANDLE)
        rec[S['SPECIAL']] = special & 0xFF
        rec[S['OLDSPECIAL']] = special & 0xFF
        rec[S['TAG']:S['TAG'] + 2] = pack16(tag)
        secg += rec
    W.put(LL.LVG1, LL.SECGS.base, bytes(secg))
    at = LL.SECGS.base + len(secg)
    ltab = b''.join(pack16(i) for t in group.tables for i in t)
    flidx, flent = flood.layout()
    bm = game.lumps['BLOCKMAP']
    _, _, bcols, brows = struct.unpack_from('<hhhh', bm, 0)
    nblocks = bcols * brows
    bases = {}
    for name, data in (('LTAB', ltab), ('FLIDX', flidx), ('FLENT', flent),
                       ('BLINKS', b'\xff\xff' * nblocks)):
        bases[name] = at
        if data:
            W.put(LL.LVG1, at, data)
        at += len(data)
    if at > LL.ROOM[1]:
        raise StoreError('LVG1 needs $%04X' % at)
    W.put(LL.LVG2, LL.BLOCKMAP, bm)
    reject_at = LL.BLOCKMAP + len(bm)
    if game.lumps['REJECT']:
        W.put(LL.LVG2, reject_at, game.lumps['REJECT'])
    if reject_at + len(game.lumps['REJECT']) > LL.ROOM[1]:
        raise StoreError('LVG2: the blockmap and reject pass $BFFF')
    cmapa, cmapb = mc.facts['colormaps']
    W.put(LL.LVC, LL.LVC_CMAPA, cmapa)
    W.put(LL.LVC, LL.LVC_CMAPB, cmapb)
    W.put(LL.LVC, LL.LVC_GSVIEW, gsview)
    W.put(LL.LVC, LL.LVC_FUZZ, level.fuzzdark)
    W.put(R.SPRT, R.SPRFRS.base, bytes(sprfr))
    W.put(R.WCODE_BANK, R.FLATCM, level.wtables[R.FLATCM])
    W.put(R.WCODE_BANK, R.TXBANK, wtab[len(level.wtables[R.FLATCM]):])
    W.put(R.MCODE_BANK, R.TXMP, bytes(txmp_lo) + bytes(txmp_hi))
    for v in var:
        W.put(v['bank'], v['address'], v['data'])
    part.main = {R.LVCOUNT: pack16(c['sectors']) + pack16(c['sides']),
                 LL.LVCOUNT2: pack16(c['lines']) + pack16(c['subsectors']) +
                 pack16(c['segs']) + pack16(c['nodes']),
                 LL.MAIN_CMAPA: cmapa[:LL.CMAP_LOW],
                 LL.MAIN_CMAPB: cmapb[:LL.CMAP_LOW],
                 LL.MAIN_CMAPA_HI: cmapa[LL.CMAP_LOW:],
                 LL.MAIN_CMAPB_HI: cmapb[LL.CMAP_LOW:],
                 LL.LV_VARMAP: bytes([m])}
    part.aux0 = {LL.AUX0_FUZZ: level.fuzzdark}
    # what stage C writes: the sectors' thing heads, the sectors' game
    # part's dynamic fields, the blocklinks, the lines' stamps
    M = part.mask
    for s in range(c['sectors']):
        a = R.SECTORS.address(s) + R.SEC['THINGS']
        M.put(R.LVMAP, a, b'\xff\xff')
        base = LL.SECGS.address(s)
        for k, n in (('TARGET', 2), ('FLOORD', 2), ('CEILD', 2),
                     ('TOUCH', 2), ('SPECIAL', 1), ('TRAVERSED', 1)):
            M.put(LL.LVG1, base + LL.SECG[k], b'\xff' * n)
    if nblocks:
        M.put(LL.LVG1, bases['BLINKS'], b'\xff' * (2 * nblocks))
    for i in range(c['lines']):
        a = LL.LINES.address(i)
        M.put(LL.LVG0, a + LL.LINE['VALID'], b'\xff\xff')
        M.put(LL.LVG0, a + LL.LINE['RVALID'], b'\xff\xff')
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
# The load program (docs/LEVELS.md 2.2)
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


def parse_requests(data: bytes) -> List[List[bytes]]:
    n, at, out = data[0], 1, []
    for _ in range(n):
        k = data[at]
        at += 1
        out.append([data[at + 16 * i:at + 16 * i + 16] for i in range(k)])
        at += 16 * k
    if at != len(data):
        raise StoreError('a request list of %d bytes, %d read'
                         % (len(data), at))
    return out


def variant_requests(part: Part, kind: str) -> bytes:
    """The memory-API COPY requests of a variant list (APPLY or UNDO, as
    placed: 3 bytes of bank and address, then 128 bytes, a variant): one
    descriptor a variant, from the list's bytes to its place in the
    shared stores (docs/LEVELS.md 1.4)."""
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
    # milestone 10: GTABS (LVS's tables) before the spawn, which reads them
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
    blockmap's origin and size, the sky block (bank, address); stage C:
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


def image(records: Sequence[Tuple[int, int, int, bytes]]) -> bytes:
    img = LC.Image()
    for kind, bank, address, data in records:
        img.add(kind, bank, address, data)
    return img.bytes()


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
    # reads (llayout.STORE_DIR; stage B: it was the first free place)
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
        d = out / ('e1m%d' % m)
        d.mkdir(exist_ok=True)
        recs = [(1, b, a, data) for b, a, data in part.window.runs()]
        recs += [(0, 0, a, data) for a, data in sorted(part.main.items())]
        recs += [(1, 0, a, data) for a, data in sorted(part.aux0.items())]
        (d / 'window.img').write_bytes(image(recs))
        (d / 'mask.img').write_bytes(image(
            [(1, b, a, data) for b, a, data in part.mask.runs()]))
        level = result['convs'][m].level
        slots = {}
        for key, upstream_address in level.texmap['slots'].items():
            t, c = key.split(':')
            bank, base, _ = sh.tex_blocks[t]
            slots[key] = [bank, base + SLOT * int(c), upstream_address]
        (d / 'texmap.json').write_text(json.dumps(
            {'format': 'game-texmap 1', 'map': 'E1M%d' % m,
             'slots': slots}) + '\n')
        entries = []
        for e in level.info['sprites']['store']:
            g = sh.lumps[e['lump']]
            entries.append([g['bank'], g['at'], e['size'] + TAIL,
                            e['address'], e['lump'], g['index']])
        (d / 'patchmap.json').write_text(json.dumps(
            {'format': 'game-patchmap 1', 'map': 'E1M%d' % m,
             'entries': entries}) + '\n')
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


# ---------------------------------------------------------------------------
# The reader: a host model of the load (the store's semantics for stage B)
# ---------------------------------------------------------------------------

HEADER_COUNTS = ('sectors', 'sides', 'lines', 'subsectors', 'segs', 'nodes',
                 'vertices', 'things', 'blocks', 'linetable', 'flood')


def parse_header(data: bytes) -> Dict[str, Any]:
    if data[:2] != b'LH':
        raise StoreError('not a level header')
    out: Dict[str, Any] = {'map': data[2], 'counts': {}, 'blocks': {}}
    at = 4
    for k in HEADER_COUNTS:
        out['counts'][k] = struct.unpack_from('<H', data, at)[0]
        at += 2
    for kind in BLOCK_KINDS:
        bank, codec, address, length = struct.unpack_from('<BBHH', data, at)
        if codec != LL.CODEC_RAW:
            raise StoreError('block %s: codec %d' % (kind, codec))
        out['blocks'][kind] = (bank, address, length)
        at += 6
    out['lvg1'] = dict(zip(('LTAB', 'FLIDX', 'FLENT', 'BLINKS'),
                           struct.unpack_from('<4H', data, at)))
    at += 8
    out['reject'] = struct.unpack_from('<H', data, at)[0]
    at += 2
    out['blockmap'] = dict(zip(('orgx', 'orgy', 'columns', 'rows'),
                               struct.unpack_from('<hhhh', data, at)))
    at += 8
    out['sky'] = (data[at], struct.unpack_from('<H', data, at + 1)[0])
    at += 3
    out['lumps'] = dict(zip(('BLOCKMAP', 'REJECT'),
                            struct.unpack_from('<HH', data, at)))
    out['size'] = at + 4
    return out


def parse_program(data: bytes) -> Tuple[List[Tuple[int, int]],
                                        List[List[bytes]]]:
    if data[:2] != b'LP':
        raise StoreError('not a load program')
    nsteps, nreqs = data[3], data[4]
    at = 6
    steps = []
    for _ in range(nsteps):
        steps.append((data[at], struct.unpack_from('<H', data, at + 1)[0]))
        at += 3
    reqs = []
    for _ in range(nreqs):
        n = data[at]
        at += 1
        reqs.append([data[at + 16 * k:at + 16 * k + 16] for k in range(n)])
        at += 16 * n
    if at != len(data):
        raise StoreError('the program has %d bytes past its requests'
                         % (len(data) - at))
    return steps, reqs


class HostMachine:
    """Main memory and RamWorks banks 0-126 after the boot load of the
    bank files, and the load of a map as stage B's loader must make it:
    the variants, the memory-API requests (COPY, FILL, PRIVATE, every
    validation a2vm makes), and the static steps from the store's bytes
    (lderive.py's rules)."""

    def __init__(self, files: Sequence[Path], directory: Tuple[int, int],
                 poison: int = 0xA5):
        self.main = bytearray([poison]) * 0x10000
        self.aux = {b: bytearray([poison]) * 0x10000 for b in range(127)}
        for path in files:
            for bank, address, data in read_bank_file(path.read_bytes()):
                self.aux[bank][address:address + len(data)] = data
        self.main[LL.LV_VARMAP] = 0
        self.directory = directory
        self.requests_done = 0

    def read(self, bank: int, address: int, n: int) -> bytes:
        return bytes(self.aux[bank][address:address + n])

    def write(self, bank: int, address: int, data: bytes) -> None:
        self.aux[bank][address:address + len(data)] = data

    def header(self, gamemap: int) -> Dict[str, Any]:
        bank, at = self.directory
        d = self.read(bank, at, LL.STORE_DIR_SIZE)
        if d[:4] != LL.STORE_MAGIC or d[5] > LL.STORE_DIR_MAPS:
            raise StoreError('no store directory')
        for k in range(d[5]):
            m, hb, ha = struct.unpack_from('<BBH', d, 16 + 4 * k)
            if m == gamemap:
                return parse_header(self.read(hb, ha, 256))
        raise StoreError('E1M%d is not in the store' % gamemap)

    def block(self, h: Dict[str, Any], kind: str) -> bytes:
        bank, address, length = h['blocks'][kind]
        return self.read(bank, address, length)

    def request(self, descriptors: Sequence[bytes]) -> None:
        """A CONTROL request: every descriptor checked, then run (a2vm's
        rules)."""
        if not 1 <= len(descriptors) <= LL.AMEM_MAX:
            raise StoreError('a request of %d descriptors' % len(descriptors))
        todo = []
        for d in descriptors:
            op, flags = d[0], d[1]
            size = d[10] | d[11] << 8
            if op not in (1, 2) or flags & ~1 or any(d[13:16]) or \
                    (op == 1 and d[12]) or (op == 2 and any(d[2:6])):
                raise StoreError('a malformed descriptor')
            ends = []
            for e in ((2,) if op == 1 else ()) + (6,):
                space, bank = d[e], d[e + 1]
                address = d[e + 2] | d[e + 3] << 8
                if space > 1 or (space == 0 and bank) or bank > 126 or \
                        not size or address < 0x200 or address + size > \
                        0xC000:
                    raise StoreError('a descriptor out of range')
                ends.append((space, bank, address))
            if op == 1 and ends[0][:2] == ends[1][:2] and \
                    ends[0][2] < ends[1][2] + size and \
                    ends[1][2] < ends[0][2] + size:
                raise StoreError('an overlapping copy')
            dst = ends[-1]
            if not flags & 1 and (dst[0] == 0 or dst[1] == 0):
                raise StoreError('PRIVATE required')
            todo.append((op, ends[0] if op == 1 else None, dst, size, d[12]))
        for op, src, dst, size, fill in todo:
            target = self.main if dst[0] == 0 else self.aux[dst[1]]
            if op == 1:
                source = self.main if src[0] == 0 else self.aux[src[1]]
                target[dst[2]:dst[2] + size] = source[src[2]:src[2] + size]
            else:
                target[dst[2]:dst[2] + size] = bytes([fill]) * size
        self.requests_done += 1

    def variants(self, gamemap: int) -> None:
        """VARIANTS: the undo requests of the map LV_VARMAP names (none
        for 0), then this map's apply requests, then LV_VARMAP."""
        old = self.main[LL.LV_VARMAP]
        if old:
            for req in parse_requests(self.block(self.header(old),
                                                 'UNDOREQ')):
                self.request(req)
        for req in parse_requests(self.block(self.header(gamemap),
                                             'APPLYREQ')):
            self.request(req)
        self.main[LL.LV_VARMAP] = gamemap

    def load(self, gamemap: int) -> None:
        h = self.header(gamemap)
        steps, reqs = parse_program(self.block(h, 'PROGRAM'))
        names = {v: k for k, v in LL.STEPS.items()}
        for op, arg in steps:
            name = names[op]
            if name == 'VARIANTS':
                self.variants(arg)
            elif name in ('COPYREQ', 'PRIVREQ'):
                self.request(reqs[arg])
            elif name == 'LINES':
                self.lines(h)
            elif name == 'GROUP':
                self.group(h)
            elif name == 'FLOOD':
                self.flood(h)
            elif name == 'CMAPS':
                self.cmaps(h)
            elif name == 'END':
                break
            # SPAWN, SPECIALS: stage C; GTABS: milestone 10 (game steps:
            # nl_setup's only)

    # -- the static steps, from the store's and the window's bytes
    def game_lines(self, h) -> List[List[int]]:
        d = self.block(h, 'LINES')
        return [list(struct.unpack_from('<hhhhHHbbb', d, 15 * i))
                for i in range(h['counts']['lines'])]

    def side_sectors(self, h) -> List[int]:
        return [self.aux[R.LVMAP][R.SIDES.address(i) + R.SIDE['SECTOR']]
                for i in range(h['counts']['sides'])]

    def lines(self, h) -> None:
        recs = b''.join(LD.line_record(LD.line_fields(ln))
                        for ln in self.game_lines(h))
        self.write(LL.LVG0, LL.LINES.base, recs)

    def tables(self, h):
        lines = self.game_lines(h)
        ssec = self.side_sectors(h)
        tables: List[List[int]] = [[] for _ in range(h['counts']['sectors'])]
        for i, ln in enumerate(lines):
            front = ssec[ln[4]]
            back = ssec[ln[5]] if ln[5] != 0xFFFF else None
            tables[front].append(i)
            if back is not None and back != front:
                tables[back].append(i)
        return lines, ssec, tables

    def group(self, h) -> None:
        c = h['counts']
        segs = self.read(R.LVSEG, R.SEGS.base, R.SEG_SIZE * c['segs'])
        ssec = self.side_sectors(h)
        for i in range(c['subsectors']):
            a = R.SUBS.address(i)
            count, first = self.aux[R.LVMAP][a + 1], \
                struct.unpack_from('<H', self.aux[R.LVMAP], a + 2)[0]
            sector = None
            for k in range(first, first + count):
                side = struct.unpack_from('<H', segs, R.SEG_SIZE * k +
                                          R.SEG['SIDE'])[0]
                if side != 0xFFFF:
                    sector = ssec[side]
                    break
            if sector is None:
                raise StoreError('subsector %d: no side' % i)
            self.aux[R.LVMAP][a] = sector
        lines, ssec, tables = self.tables(h)
        first = 0
        ltab = bytearray()
        secc = self.block(h, 'SECC')
        for s, t in enumerate(tables):
            top = right = LD.INT32_MIN
            bottom = left = LD.INT32_MAX
            for i in t:
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
            special, tag = struct.unpack_from('<bh', secc, 3 * s)
            rec = bytearray(LL.SECG_SIZE)
            S = LL.SECG
            rec[S['SOUNDX']:S['SOUNDX'] + 4] = struct.pack(
                '<i', LD.s32(LD.half(right) + LD.half(left)))
            rec[S['SOUNDY']:S['SOUNDY'] + 4] = struct.pack(
                '<i', LD.s32(LD.half(top) + LD.half(bottom)))
            for k in ('TARGET', 'FLOORD', 'CEILD', 'TOUCH'):
                rec[S[k]:S[k] + 2] = pack16(LL.NO_HANDLE)
            rec[S['LCOUNT']:S['LCOUNT'] + 2] = pack16(len(t))
            rec[S['LFIRST']:S['LFIRST'] + 2] = pack16(first)
            rec[S['SPECIAL']] = rec[S['OLDSPECIAL']] = special & 0xFF
            rec[S['TAG']:S['TAG'] + 2] = pack16(tag)
            self.write(LL.LVG1, LL.SECGS.address(s), bytes(rec))
            ltab += b''.join(pack16(i) for i in t)
            first += len(t)
        if ltab:
            self.write(LL.LVG1, h['lvg1']['LTAB'], bytes(ltab))

    def flood(self, h) -> None:
        lines, ssec, tables = self.tables(h)
        n = len(tables)
        free: List[List[int]] = [[] for _ in range(n)]
        block: List[List[int]] = [[] for _ in range(n)]
        for i in range(len(lines) - 1, -1, -1):
            ln = lines[i]
            if ln[5] == 0xFFFF:
                continue
            front, back = ssec[ln[4]], ssec[ln[5]]
            if front == back or not ln[6] & LD.ML_TWOSIDED:
                continue
            target = block if ln[6] & LD.ML_SOUNDBLOCK else free
            target[front].append(back)
            target[back].append(front)
        idx, ent = bytearray(), bytearray()
        for s in range(n):
            room = len(tables[s])
            region = bytearray(room)
            region[:len(free[s])] = bytes(free[s])
            for k, other in enumerate(block[s]):
                region[room - 1 - k] = other
            f0 = len(ent)
            ent += region
            idx += struct.pack('<HHHH', f0, f0 + len(free[s]),
                               f0 + room - len(block[s]), f0 + room)
        self.write(LL.LVG1, h['lvg1']['FLIDX'], bytes(idx))
        if ent:
            self.write(LL.LVG1, h['lvg1']['FLENT'], bytes(ent))

    def cmaps(self, h) -> None:
        cm = self.read(LL.GTAB, LL.GT['COLORMAP'][0], LL.CMAP_SIZE)
        rec = self.read(LL.LVC, LL.LVC_GSVIEW, LL.GSVIEW_SIZE)
        a = rec[WC.PALREC_A:WC.PALREC_A + 256]
        b = rec[WC.PALREC_A + 256:WC.PALREC_A + 512]
        self.write(LL.LVC, LL.LVC_CMAPA, bytes(a[x] for x in cm))
        self.write(LL.LVC, LL.LVC_CMAPB, bytes(b[x] for x in cm))


def compare_window(hm: HostMachine, d: Path) -> int:
    """The machine against the map's window.img outside mask.img: the
    bytes compared; raises on the first difference."""
    mask: Dict[Tuple[int, int], bytes] = {}
    for kind, bank, address, data in LC.Image.parse(
            (d / 'mask.img').read_bytes()):
        mask[(bank, address)] = data
    masked: Dict[int, set] = {}
    for (bank, address), data in mask.items():
        masked.setdefault(bank, set()).update(
            range(address, address + len(data)))
    n = 0
    for kind, bank, address, data in LC.Image.parse(
            (d / 'window.img').read_bytes()):
        got = hm.main[address:address + len(data)] if kind == 0 else \
            hm.aux[bank][address:address + len(data)]
        skip = masked.get(bank, set()) if kind == 1 else set()
        for i in range(len(data)):
            if got[i] != data[i] and address + i not in skip:
                raise StoreError('%s $%04X differs from window.img' % (
                    'main' if kind == 0 else 'bank %d' % bank, address + i))
        n += len(data) - sum(1 for i in range(len(data))
                             if address + i in skip)
    return n


def readback(hm: HostMachine, gamemap: int, d: Path, ref_dir: Path
             ) -> Dict[str, int]:
    """The loaded machine read back into harness form through the map's
    game texmap.json and patchmap.json, against levelconv.py's level of
    the same map (ref_dir): every slot, every stored lump and tail, the
    W tables' textures, TXMP and SPRFR (by lump), PHDR (by lump); the
    counts compared."""
    info = json.loads((ref_dir / 'level.json').read_text())
    recs = LC.Image.parse((ref_dir / 'level.img').read_bytes())
    ref = LC.Banks()
    for kind, bank, address, data in recs:
        ref.put(bank, address, data)
    texmap = json.loads((d / 'texmap.json').read_text())['slots']
    ref_texmap = json.loads((ref_dir / 'texmap.json').read_text())['slots']
    out = {'slots': 0, 'lumps': 0, 'sprfr': 0, 'txmp': 0, 'tx': 0}
    if set(ref_texmap) != set(texmap):
        raise StoreError('the slots differ: %s' % sorted(
            set(ref_texmap) ^ set(texmap))[:5])
    for key, upstream_address in ref_texmap.items():
        bank, address, up = texmap[key]
        if up != upstream_address:
            raise StoreError('slot %s: upstream $%06X, levelconv\'s $%06X'
                             % (key, up, upstream_address))
        t, c = key.split(':')
        if t == 'sky':
            e = info['sky']
            rbank, rbase = e['bank'], e['base']
        else:
            e = info['textures'][t]
            rbank, rbase = e['bank'], e['base']
        want = ref.get(rbank, rbase + SLOT * int(c), SLOT)
        if hm.read(bank, address, SLOT) != want:
            raise StoreError('E1M%d slot %s differs from levelconv\'s'
                             % (gamemap, key))
        out['slots'] += 1
    patchmap = json.loads((d / 'patchmap.json').read_text())['entries']
    store = info['sprites']['store']
    if len(patchmap) != len(store):
        raise StoreError('%d stored lumps, levelconv %d' % (len(patchmap),
                                                           len(store)))
    glob_of = {}
    for (bank, at, n, up, lump, g), e in zip(patchmap, store):
        if (lump, up, n) != (e['lump'], e['address'], e['size'] + TAIL):
            raise StoreError('lump %d: the patch map differs' % lump)
        if hm.read(bank, at, n) != ref.get(e['bank'], e['at'], n):
            raise StoreError('E1M%d lump %s or its tail differs'
                             % (gamemap, e['name']))
        ph = hm.read(R.SPRT, R.PHDRS.address(g), R.PHDR_SIZE)
        rph = ref.get(R.SPRT, R.PHDRS.address(e['index']), R.PHDR_SIZE)
        if ph[0:6] != rph[0:6] or ph[R.PHDR['LUMP']:R.PHDR['LUMP'] + 2] != \
                rph[R.PHDR['LUMP']:R.PHDR['LUMP'] + 2] or \
                ph[R.PHDR['BANK']] != bank or \
                ph[R.PHDR['ADDR']] | ph[R.PHDR['ADDR'] + 1] << 8 != at:
            raise StoreError('PHDR of lump %d differs' % lump)
        glob_of[e['index']] = g
        out['lumps'] += 1
    glob_of[0] = 0
    nfr = sum(info['sprites']['frames_per_sprite'])
    bad = set()
    k = 0
    for s, n in enumerate(info['sprites']['frames_per_sprite']):
        for f in range(n):
            if [s, f] in info['sprites']['not_frames']:
                bad.add(k)
            k += 1
    for k in range(nfr):
        a = R.SPRFRS.address(k)
        got = hm.read(R.SPRT, a, R.SPRFR_SIZE)
        want = bytearray(ref.get(R.SPRT, a, R.SPRFR_SIZE))
        for r in range(8):
            at = R.SPRFR['LUMPS'] + 2 * r
            v = want[at] | want[at + 1] << 8
            want[at:at + 2] = pack16(glob_of[v])
        if k in bad:
            want[R.SPRFR['ROT']] = got[R.SPRFR['ROT']]
            want[R.SPRFR['FLIP']] = got[R.SPRFR['FLIP']]
        if got != bytes(want):
            raise StoreError('E1M%d SPRFR %d differs' % (gamemap, k))
        out['sprfr'] += 1
    rm = {}
    for kind, bank, address, data in LC.Image.parse(
            (ref_dir / 'mtables.img').read_bytes()):
        rm[address] = data
    txmp = hm.read(R.MCODE_BANK, R.TXMP, 512)
    for t in range(256):
        v = rm[R.TXMP][t] | rm[R.TXMP][256 + t] << 8
        g = txmp[t] | txmp[256 + t] << 8
        if (v == 0xFFFF) != (g == 0xFFFF) or (v != 0xFFFF and
                                              glob_of[v] != g):
            raise StoreError('E1M%d TXMP[%d] differs' % (gamemap, t))
        out['txmp'] += 1
    rw = {}
    for kind, bank, address, data in LC.Image.parse(
            (ref_dir / 'wtables.img').read_bytes()):
        rw[address] = data
    for t_text, e in info['textures'].items():
        t = int(t_text)
        bank = hm.aux[R.WCODE_BANK][R.TXBANK + t]
        lo = hm.aux[R.WCODE_BANK][R.TXLO + t]
        hi = hm.aux[R.WCODE_BANK][R.TXHI + t]
        if (bank & 0x80) != (rw[R.TXBANK][t] & 0x80) or \
                hm.aux[R.WCODE_BANK][R.TXWM + t] != rw[R.TXWM][t]:
            raise StoreError('E1M%d texture %d: TXBANK or TXWM' % (gamemap,
                                                                    t))
        base = lo | hi << 8
        for c in range(e['widthmask'] + 1):
            want = ref.get(e['bank'], e['base'] + SLOT * c, SLOT)
            if hm.read(bank & 0x7F, base + SLOT * c, SLOT) != want:
                raise StoreError('E1M%d texture %d column %d through '
                                 'TXBANK' % (gamemap, t, c))
        out['tx'] += 1
    return out
