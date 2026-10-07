#!/usr/bin/env python3
"""The level converter (docs/LEVELS.md): DOOM1.WAD
and the release's level store to the native levels and the shared store,
with no reference run.

Usage:  python3 tools/native/wadconv.py --store

The inputs (docs/LEVELS.md): DOOM1.WAD for every lump it holds,
through our own transforms (maplumps.py); the release (build/release/
doom-hd.hdv) for what upstream's build invented: each map's placement of
its lumps in the level window (the store's entries), the per-map colour
tables GSVIEWn and GSFLATn, the flat numbering (paired with the game
SECTORS), the lump directory's order, and CM_COLD (r_data65.s: the
textures whose composed columns avoid the replay's cache pages); the
game's constant tables (states, weaponinfo, sprnames) from the release's
memory by symbol. umodel.py rebuilds upstream's memory at the end of the
load from them; this tool converts from that model, and --store writes
the game layout (docs/LEVELS.md: the shared texel and patch
stores, each map's level part and load program, store.json and the bank
files; lstore.py).

Where upstream's RAM holds history that no load of the map determines,
the converter writes what the map's own load gives (docs/LEVELS.md):

  TXHT      upstream's textureheight is never cleared: it holds every
            texture loaded since the boot. The converter writes every
            texture's height (TEXTURE1's).
  FLATCM    levelFlats writes the map's flats only (GSFLATn's count);
            the columns past them keep the map before's. The converter
            writes 0 there.
  SPRFR     a frame past a sprite's frames (flagged SPRFR_BAD: no map
            thing shows it) reads upstream's memory after the sprite's
            frames for its rotate and flipmask bytes; the converter
            writes 0 for both.
"""

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import levelconv as LC, rlayout as R, umodel as U  # noqa: E402

ROOT = HERE.parent.parent
FORMAT = LC.FORMAT
SLOT = LC.SLOT
TAIL = LC.TAIL
SKY_COLUMNS = LC.SKY_COLUMNS
MAXSPRITEFRAMES = 29


class ConvError(Exception):
    pass


def pack16(v: int) -> bytes:
    return (v & 0xFFFF).to_bytes(2, 'little')


# ---------------------------------------------------------------------------
# The map's objects, decoded from the game's lumps (the canonical fields the
# renderer reads, as upstream's P_SetupLevel makes them: p_setup65.s)
# ---------------------------------------------------------------------------

class MapData:
    def __init__(self, ld: U.Load):
        g = ld.game
        self.segs = g.seg_list()
        self.lines = g.lines                    # maplumps' Line lists
        self.sides = g.sides
        self.nodes = g.node_list()
        self.sectors = g.sector_list()
        self.subs = []
        for count, first in g.subsector_list():
            sector = None
            for k in range(first, first + count):
                side = self.segs[k]['sidenum']
                if side != 0xFFFF:
                    sector = self.sides[side][5] & 0xFF
                    break
            if sector is None:
                raise ConvError('a subsector with no side')
            self.subs.append((sector, count, first))

    def sector_obj(self, i: int) -> Dict[str, Any]:
        fh, ch, fpic, cpic, light, special, tag = self.sectors[i]
        return {'floorheight': fh << 16, 'ceilingheight': ch << 16,
                'floorpic': fpic, 'ceilingpic': cpic,
                'lightlevel': light & 0xFF, 'validcount': 0}

    def side_obj(self, i: int) -> Dict[str, Any]:
        toff, roff, top, bottom, mid, sector = self.sides[i]
        return {'textureoffset': toff, 'rowoffset': roff & 0xFF,
                'toptexture': top, 'bottomtexture': bottom,
                'midtexture': mid}


# ---------------------------------------------------------------------------
# Sprites: R_InitSprites from the game's directory
# ---------------------------------------------------------------------------

class Frame:
    def __init__(self):
        self.rotate = -1
        self.lumps = [-1] * 8
        self.flip = 0


def sprite_defs(gd: U.GameData) -> List[List[Frame]]:
    """Each sprite's frames from the sprite lumps' names (S_START to
    S_END): the 4 letters, a frame letter and a rotation digit, maybe a
    second frame and rotation for the flipped lump (Doom's
    R_InitSpriteDefs, R_InstallSpriteLump)."""
    rel = gd.rel
    names = rel.names
    start, end = names.index('S_START'), names.index('S_END')
    raw = rel.table('sprnames', 4 * R.NUMSPRITES)
    sprnames = [raw[4 * i:4 * i + 4].decode('latin-1')
                for i in range(R.NUMSPRITES)]
    out = []
    for s, prefix in enumerate(sprnames):
        frames = [Frame() for _ in range(MAXSPRITEFRAMES)]
        maxframe = -1

        def install(lump: int, frame: int, rotation: int, flipped: bool
                    ) -> None:
            nonlocal maxframe
            if not 0 <= frame < MAXSPRITEFRAMES or not 0 <= rotation <= 8:
                raise ConvError('bad frame of lump %d' % lump)
            maxframe = max(maxframe, frame)
            f = frames[frame]
            if rotation == 0:
                if f.rotate != -1:
                    raise ConvError('sprite %s frame %d: rotation 0 twice '
                                    'or with others' % (prefix, frame))
                f.rotate = 0
                f.lumps = [lump] * 8
                f.flip = 0xFF if flipped else 0
                return
            if f.rotate == 0:
                raise ConvError('sprite %s frame %d: rotations and 0'
                                % (prefix, frame))
            f.rotate = 1
            r = rotation - 1
            if f.lumps[r] != -1:
                raise ConvError('sprite %s frame %d: two lumps for '
                                'rotation %d' % (prefix, frame, rotation))
            f.lumps[r] = lump
            if flipped:
                f.flip |= 1 << r
        for lump in range(start + 1, end):
            n = names[lump]
            if n[:4] != prefix or rel.directory[lump].size == 0:
                continue
            install(lump, ord(n[4]) - 65, ord(n[5]) - 48, False)
            if len(n) >= 8:
                install(lump, ord(n[6]) - 65, ord(n[7]) - 48, True)
        for f in range(maxframe + 1):
            fr = frames[f]
            if fr.rotate == -1 or (fr.rotate == 1 and -1 in fr.lumps):
                raise ConvError('sprite %s frame %d is incomplete'
                                % (prefix, f))
        out.append(frames[:maxframe + 1])
    return out


def masked_textures(gd: U.GameData, md: MapData) -> List[int]:
    """levelconv.masked_textures from the map's lines and sides: the mid
    textures of two-sided lines' sides, their switch partners, and all
    three slime frames when one is among them."""
    mids = set()
    for ln in md.lines:
        s0, s1 = ln[4], ln[5]
        if s1 == 0xFFFF:
            continue
        for s in (s0, s1):
            tex = md.sides[s][4]
            if tex:
                mids.add(tex)
    sw = gd.switchlist
    out = set(mids)
    for tex in mids:
        for i, x in enumerate(sw):
            if x == tex:
                out.add(sw[i ^ 1])
    base = gd.basepic
    if any(base <= tex <= base + 2 for tex in out):
        out |= {base, base + 1, base + 2}
    return sorted(out)


# ---------------------------------------------------------------------------
# Colour tables (i_viigs65.s I_SetLevelPalette, levelFlats)
# ---------------------------------------------------------------------------

PALREC_A = 14 * 16 * 2 + 256


def colormaps(gsview: bytes, colormap: bytes) -> Tuple[bytes, bytes]:
    a = gsview[PALREC_A:PALREC_A + 256]
    b = gsview[PALREC_A + 256:PALREC_A + 512]
    return (bytes(a[c] for c in colormap[:34 * 256]),
            bytes(b[c] for c in colormap[:34 * 256]))


def flatcm(gsflat: bytes, colormap: bytes) -> Tuple[bytes, int]:
    """FLATCM[cm * 32 + f] = fullcolormap[cm * 256 + colour[f]] for the
    map's flats f; the columns past them 0 (upstream keeps the map
    before's there)."""
    out = bytearray(34 * 32)
    n = len(gsflat)
    if n > 32:
        raise ConvError('%d flats: FLATCM holds 32' % n)
    for f in range(n):
        for cm in range(34):
            out[cm * 32 + f] = colormap[cm * 256 + gsflat[f]]
    return bytes(out), n


def fuzzdark(gsview: bytes) -> bytes:
    """FUZZ_DARKEN: each colour's nearest (3 dr^2 + 4 dg^2 + 2 db^2, the
    first of the least) to 3/4 of its red, green and blue."""
    cols = [u16_le(gsview, 2 * k) for k in range(16)]

    def rgb(c: int) -> Tuple[int, int, int]:
        return (c >> 8) & 15, (c >> 4) & 15, c & 15
    darker = []
    for c in cols:
        r, g, b = (x * 3 // 4 for x in rgb(c))
        best, dist = 0, 0x7FFF
        for k, q in enumerate(cols):
            qr, qg, qb = rgb(q)
            d = 3 * (qr - r) ** 2 + 4 * (qg - g) ** 2 + 2 * (qb - b) ** 2
            if d < dist:
                best, dist = k, d
        darker.append(best)
    return bytes(darker[x >> 4] << 4 | darker[x & 15] for x in range(256))


def u16_le(b: bytes, at: int) -> int:
    return b[at] | b[at + 1] << 8


# ---------------------------------------------------------------------------
# The conversion, the renderer's level layout (levelconv.py's)
# ---------------------------------------------------------------------------

def lump_bytes(ld: U.Load, lump: int) -> bytes:
    return ld.mem.read(ld.lump_addr[lump], ld.lump_size[lump])


def convert(gd: U.GameData, ld: U.Load) -> Tuple[LC.Level, Dict[str, Any]]:
    """The level in levelconv.py's layout, and the facts inplay.json
    needs (the textures loaded, the slots' sources)."""
    rel = gd.rel
    m = ld.mem
    md = MapData(ld)
    checks: List[str] = []
    sectors, sides, lines = md.sectors, md.sides, md.lines
    subs, segs, nodes = md.subs, md.segs, md.nodes
    limits = [('sector', len(sectors), R.SECTORS.capacity),
              ('side', len(sides), R.SIDES.capacity),
              ('line', len(lines), R.LNMAP_LINES),
              ('subsector', len(subs), R.SUBS.capacity),
              ('seg', len(segs), R.SEGS.capacity),
              ('node', len(nodes), R.NODES.capacity)]
    seg_objs = [{'v1': s['v1'], 'v2': s['v2']} for s in segs]
    points, ends = LC.native_vertices(seg_objs)
    limits.append(('vertex', len(points), R.VTX_CAP))
    for what, n, cap in limits:
        if n > cap:
            raise ConvError('%d %ss: the native layout holds %d'
                            % (n, what, cap))
    node_objs = [{'children': [n[12], n[13]]} for n in nodes]
    numnodes = len(nodes)
    depth = LC.bsp_depth(node_objs, (numnodes - 1) & 0xFFFF) \
        if nodes else 0
    if depth > LC.BSP_DEPTH_MAX:
        raise ConvError('BSP depth %d: the node frames hold %d'
                        % (depth, LC.BSP_DEPTH_MAX))
    checks.append('counts within the native limits')
    banks = LC.Banks()
    # -- segs
    data = bytearray()
    for i, s in enumerate(segs):
        line = lines[s['linenum']]
        rec = bytearray(R.SEG_SIZE)
        for key, value in (('V1X', s['v1'][0]), ('V1Y', s['v1'][1]),
                           ('V2X', s['v2'][0]), ('V2Y', s['v2'][1]),
                           ('OFFSET', s['offset']), ('ANGLE', s['angle']),
                           ('SIDE', s['sidenum']), ('LINE', s['linenum']),
                           ('V1N', ends[i][0]), ('V2N', ends[i][1])):
            rec[R.SEG[key]:R.SEG[key] + 2] = pack16(value)
        rec[R.SEG['FRONT']] = s['front']
        rec[R.SEG['BACK']] = s['back']
        rec[R.SEG['PEGS']] = line[6] & (LC.ML_DONTPEGTOP |
                                        LC.ML_DONTPEGBOTTOM)
        data += rec
    banks.put(R.LVSEG, R.SEGS.base, bytes(data))
    # -- nodes, subsectors
    data = bytearray()
    for n in nodes:
        rec = bytearray(R.NODE_SIZE)
        for k, v in enumerate(n):
            rec[2 * k:2 * k + 2] = pack16(v)
        data += rec
    if data:
        banks.put(R.LVMAP, R.NODES.base, bytes(data))
    data = bytearray()
    for sector, count, first in subs:
        data += bytes([sector, count]) + pack16(first)
    banks.put(R.LVMAP, R.SUBS.base, bytes(data))
    nv = len(points)
    for plane in (R.VAL, R.VAH, R.VAS):
        banks.put(R.LVMAP, plane, bytes(nv))
    # -- sectors and sides
    data = bytearray()
    for i in range(len(sectors)):
        data += LC.sector_record(md.sector_obj(i), i)
    banks.put(R.LVMAP, R.SECTORS.base, bytes(data))
    data = bytearray()
    for i in range(len(sides)):
        rec = LC.side_record(md.side_obj(i), i)
        rec[R.SIDE['SECTOR']] = sides[i][5] & 0xFF
        data += rec
    banks.put(R.LVMAP, R.SIDES.base, bytes(data))
    # -- textures: one slot per column
    textures = gd.textures
    numtextures = len(textures)
    if numtextures > 256:
        raise ConvError('%d textures: the byte indexes hold 256'
                        % numtextures)
    heights = [t.height for t in textures]
    bad = [t for t, h in enumerate(heights) if not 0 <= h < 256]
    if bad:
        raise ConvError('texture %d has height %d: TXHT holds bytes'
                        % (bad[0], heights[bad[0]]))
    cols = ld.columns
    colmem = cols.colmem
    made = [t for t in range(256) if cols.made_t(t)]
    for t in made:
        if t >= numtextures:
            raise ConvError('COLDIR has texture %d of %d' % (t, numtextures))
    txbank, txlo, txhi = bytearray(256), bytearray(256), bytearray(256)
    txwm, txht = bytearray(256), bytearray(256)
    txht[:numtextures] = bytes(heights)
    flat_index = bytearray(b'\xff' * 256)
    flat_maps = bytearray()
    tex_info = {}
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
        try:
            return m.read(ptr, SLOT)
        except U.ModelError as error:
            raise ConvError('slot %s at $%06X: %s' % (where, ptr, error))

    for t in made:
        table, wm = cols.coldir(t)
        h = heights[t]
        if not 0 < h < 256:
            raise ConvError('texture %d has height %d' % (t, h))
        bank, base = place(SLOT * (wm + 1))
        flat_cols = []
        for c in range(wm + 1):
            e = m.read(table + 4 * c, 4)
            ptr = e[0] | e[1] << 8 | e[2] << 16
            if e[3]:
                flat_cols.append(c)
                banks.put(bank, base + SLOT * c, bytes(SLOT))
                continue
            banks.put(bank, base + SLOT * c, slot_source(ptr, '%d:%d'
                                                          % (t, c)))
        txbank[t], txlo[t], txhi[t] = bank, base & 0xFF, base >> 8
        txwm[t], txht[t] = wm, h
        if flat_cols:
            k = len(flat_maps) // 32
            if k >= LC.TXFLAT_SLOTS:
                raise ConvError('more than %d textures with patchless '
                                'columns' % LC.TXFLAT_SLOTS)
            bitmap = bytearray(32)
            for c in flat_cols:
                bitmap[c >> 3] |= 1 << (c & 7)
            flat_maps += bitmap
            flat_index[t] = k
            txbank[t] |= 0x80
        tex_info[str(t)] = {'bank': bank, 'base': base, 'widthmask': wm,
                            'height': h, 'patchless': flat_cols}
    banks.put(R.LVMAP, LC.TXFLAT_INDEX, bytes(flat_index))
    if flat_maps:
        banks.put(R.LVMAP, LC.TXFLAT_MAPS, bytes(flat_maps))
    # the sky: SKY1's first patch (initSky), in place
    sky_t = U.texture_number(gd.tex_names, U.SKY_TEXTURE)
    skypatchnum = rel.index(gd.patch_names[textures[sky_t].patches[0][2]])
    skywidthmask = cols.widthmask(sky_t)
    if skywidthmask != SKY_COLUMNS - 1:
        raise ConvError('skywidthmask %d, not 255' % skywidthmask)
    sky = ld.lump_addr[skypatchnum]
    if sky == ld.placeholder:
        raise ConvError('the sky\'s patch is not in memory')
    sky_bank, sky_base = place(SLOT * SKY_COLUMNS)
    lo = sky & 0xFFFF
    for c in range(SKY_COLUMNS):
        colofs = m.u16(sky + 8 + 4 * c)
        ptr = (sky & 0xFF0000) | ((lo + colofs + 3) & 0xFFFF)
        banks.put(sky_bank, sky_base + SLOT * c,
                  slot_source(ptr, 'sky:%d' % c))
    checks.append('skypatchnum names a lump of the WAD directory')
    # -- W tables: FLATCM and the texture directory
    gsflat = lump_bytes(ld, rel.index('GSFLAT%d' % ld.gamemap))
    gsview = lump_bytes(ld, rel.index('GSVIEW%d' % ld.gamemap))
    colormap = gd.wad_by_name['COLORMAP']
    fcm, nflats = flatcm(gsflat, colormap)
    wtables = {R.FLATCM: fcm,
               R.TXBANK: bytes(txbank), R.TXLO: bytes(txlo),
               R.TXHI: bytes(txhi), R.TXWM: bytes(txwm),
               R.TXHT: bytes(txht)}
    # -- the sprite data
    sprite = sprite_part(gd, ld, md, banks)
    checks += sprite['checks']
    for tex, wm in sprite['txmp_wm'].items():
        if wm > 255:
            raise ConvError('texture %d has width mask %d: TXWM holds '
                            'bytes' % (tex, wm))
        if tex in made and txwm[tex] != wm:
            raise ConvError('texture %d: its width mask %d, its column '
                            'tables\' %d' % (tex, wm, txwm[tex]))
        txwm[tex] = wm
    wtables[R.TXWM] = bytes(txwm)
    fz = fuzzdark(gsview)
    sources = [{'what': 'DOOM1.WAD and the release', 'map': ld.gamemap}]
    key = hashlib.sha256(b''.join(
        [b'wadconv', bytes([ld.gamemap])] +
        [bytes(d) for b in sorted(banks.data)
         for _, d in banks.runs(b)])).hexdigest()[:16]
    info = {
        'format': FORMAT, 'revision': LC.REVISION,
        'source': 'wadconv E1M%d' % ld.gamemap,
        'map': 'E1M%d' % ld.gamemap,
        'gamemap': ld.gamemap, 'key': key,
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
        'txflat': {'bank': R.LVMAP, 'index': LC.TXFLAT_INDEX,
                   'maps': LC.TXFLAT_MAPS},
        'textures': tex_info, 'converted': made,
        'sky': {'bank': sky_bank, 'base': sky_base, 'columns': SKY_COLUMNS,
                'lump': skypatchnum, 'address': sky},
        'skyflatnum': u16_le(rel.table('skyflatnum', 2), 0),
        'skywidthmask': skywidthmask,
        'numnodes': numnodes, 'bsp_depth': depth,
        'banks': sorted(banks.data),
        # I_InitSegVertices numbers the seg ends in order of first
        # appearance, as native_vertices does (i_viigs65.s:1975-2025)
        'upstream_vertex': list(range(nv)),
        'open_ended': open_ended, 'colmem': colmem,
        'sources': sources, 'checks': checks,
        'sector_base': None,
        'sprites': sprite['info'],
    }
    texmap = {'format': 'render-texmap 1', 'slots': slots}
    level = LC.Level(info, banks, wtables, texmap, sprite['mtables'], fz)
    facts = {'loaded': sorted(cols.loaded), 'flats': nflats,
             'bad_frames': sprite['bad_frames'],
             'colormaps': colormaps(gsview, colormap)}
    return level, facts


def sprite_part(gd: U.GameData, ld: U.Load, md: MapData,
                banks: LC.Banks) -> Dict[str, Any]:
    """levelconv.sprite_part's output from the model."""
    rel = gd.rel
    m = ld.mem
    checks: List[str] = []
    nlumps = len(rel.directory)
    placeholder = ld.placeholder

    def resident(lump: int) -> bool:
        return ld.lump_size[lump] > 0 and ld.lump_addr[lump] != placeholder
    defs = sprite_defs(gd)
    sym = U.symbols()
    nframes = LC.sprite_frames(m, sym)
    frames = []
    bad_frames = []
    for s in range(R.NUMSPRITES):
        for f in range(nframes[s]):
            if f < len(defs[s]):
                fr = defs[s][f]
                lumps = fr.lumps if fr.rotate else fr.lumps[:1]
                frames.append((s, f, fr.rotate, fr.flip, lumps, True))
            else:
                frames.append((s, f, 0, 0, [], False))
                bad_frames.append([s, f])
    if len(frames) > R.SPRFRS.capacity:
        raise ConvError('%d sprite frames: SPRFR holds %d'
                        % (len(frames), R.SPRFRS.capacity))
    # the masked textures' first patches
    txmp_tex = masked_textures(gd, md)
    loaded = ld.columns.loaded
    txmp: Dict[int, Tuple[Optional[int], str]] = {}
    txmp_wm: Dict[int, int] = {}
    for tex in txmp_tex:
        if tex not in loaded:
            txmp[tex] = (None, 'not loaded by upstream')
            continue
        txmp_wm[tex] = ld.columns.widthmask(tex)
        lump = rel.index(gd.patch_names[gd.textures[tex].patches[0][2]])
        if lump >= nlumps or not resident(lump):
            txmp[tex] = (None, 'its first patch (lump %d) is not '
                               'resident' % lump)
            continue
        txmp[tex] = (lump, 'stored')
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
        address, size, name = ld.lump_addr[lump], ld.lump_size[lump], \
            rel.names[lump]
        need = size + TAIL
        if need > R.BANK_ROOM[1] - R.BANK_ROOM[0]:
            raise ConvError('lump %d (%s) of %d bytes does not fit a bank'
                            % (lump, name, size))
        if at + need > R.BANK_ROOM[1]:
            bank, at = bank + 1, R.BANK_ROOM[0]
        if bank > R.SPR_LAST:
            raise ConvError('the patch store needs more than banks %d-%d'
                            % (R.SPR_FIRST, R.SPR_LAST))
        try:
            banks.put(bank, at, m.read(address, need))
        except U.ModelError as error:
            raise ConvError('the tail of lump %d (%s) at $%06X: %s'
                            % (lump, name, address, error))
        store.append({'index': index[lump], 'lump': lump, 'name': name,
                      'address': address, 'size': size, 'bank': bank,
                      'at': at})
        phdr += header(address, bank, at, lump)
        at += need
    banks.put(R.SPRT, R.PHDRS.base, bytes(phdr))
    checks.append('%d patch lumps stored in banks %d-%d (%d bytes and '
                  '%d-byte tails)' % (len(order), R.SPR_FIRST, bank,
                                      sum(e['size'] for e in store), TAIL))
    data = bytearray()
    for s, f, rotate, flip, lumps, ok in frames:
        rec = bytearray(R.SPRFR_SIZE)
        if ok:
            rec[R.SPRFR['ROT']] = rotate
            rec[R.SPRFR['FLIP']] = flip
            for r, lump in enumerate(lumps):
                k = index.get(lump, 0)
                if resident(lump) and not k:
                    raise ConvError('sprite %d frame %d: lump %d is not '
                                    'stored' % (s, f, lump))
                rec[R.SPRFR['LUMPS'] + 2 * r:R.SPRFR['LUMPS'] + 2 * r + 2] \
                    = pack16(k)
        else:
            rec[R.SPRFR['FLAGS']] = R.SPRFR_BAD
        data += rec
    banks.put(R.SPRT, R.SPRFRS.base, bytes(data))
    checks.append('%d sprite frames resolve to a store index or the '
                  'placeholder; %d are not frames (%s)' % (
                      len(frames) - len(bad_frames), len(bad_frames),
                      ', '.join('sprite %d frame %d' % tuple(x)
                                for x in bad_frames)))
    lo, hi = bytearray(b'\xff' * 256), bytearray(b'\xff' * 256)
    for tex, (lump, why) in txmp.items():
        if lump is not None:
            lo[tex], hi[tex] = index[lump] & 0xFF, index[lump] >> 8
    mtables = {R.TXMP: bytes(lo) + bytes(hi)}
    checks.append('TXMP: %d textures a masked mid texture can show, %d '
                  'stored' % (len(txmp), sum(1 for v in txmp.values()
                                             if v[0] is not None)))
    weapons = weapon_part(ld, sym, frames, index, resident, banks,
                          rel.names)
    checks += weapons.pop('checks')
    info = {'placeholder': placeholder,
            'frames_per_sprite': nframes, 'not_frames': bad_frames,
            'store': store, 'store_banks': [R.SPR_FIRST, bank],
            'store_bytes': sum(e['size'] + TAIL for e in store),
            'txmp': {str(tex): {'lump': lump, 'why': why}
                     for tex, (lump, why) in txmp.items()},
            'tail': TAIL, 'weapons': weapons}
    return {'checks': checks, 'info': info, 'mtables': mtables,
            'txmp_wm': txmp_wm,
            'bad_frames': bad_frames}


def weapon_part(ld: U.Load, sym, frames, index, resident,
                banks: LC.Banks, names: Sequence[str]) -> Dict[str, Any]:
    """levelconv.weapon_part's profiles (wbMake's rules, LC.wb_make),
    without its check of a reference's arenas."""
    m = ld.mem
    wsprites = LC.weapon_sprites(m, sym)
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
        address = ld.lump_addr[lump]
        e['name'] = names[lump]
        e['index'] = index[lump]

        def read(off: int, n: int, a=address) -> bytes:
            return m.read(a + off, n)
        status, _ = LC.wb_make(read, LC.WP_ARENAS[0][0], LC.WP_ARENAS[0][1])
        if status:
            e['profile'] = None
            e['why'] = 'no room in an empty arena' if status == 1 else \
                'the patch does not fit a profile'
            continue
        status, data = LC.wb_make(read, at, R.WPROF_END)
        if status:
            raise ConvError('the weapon profiles do not fit bank %d'
                            % R.WPRO)
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
    return {'checks': checks, 'sprites': wsprites,
            'lumps': {str(k): v for k, v in sorted(lumps.items())},
            'not_resident': not_resident, 'profiles': made,
            'bytes': at - R.WPROF, 'checked': 0}


# ---------------------------------------------------------------------------
# inplay.json (docs/LEVELS.md)
# ---------------------------------------------------------------------------

def in_play(gd: U.GameData, ld: U.Load, level: LC.Level) -> Dict[str, Any]:
    """The textures upstream makes only in play (a side's texture, its
    switch partner, the slime frames, not made at the load), and the
    slots and tails whose bytes such a run-time allocation can change:
    those whose 128 bytes reach the free part of a hole, or colmem and
    after (umodel.free_parts)."""
    md = MapData(ld)
    can_show = set()
    for s in md.sides:
        for t in (s[2], s[3], s[4]):
            if t:
                can_show.add(t)
    sw = gd.switchlist
    for t in list(can_show):
        for i, x in enumerate(sw):
            if x == t:
                can_show.add(sw[i ^ 1])
    base = gd.basepic
    if any(base <= t <= base + 2 for t in can_show):
        can_show |= {base, base + 1, base + 2}
    made = {t for t in range(256) if ld.columns.made_t(t)}
    later = sorted(can_show - made)
    free = U.free_parts(ld)

    def reaches(start: int, length: int) -> bool:
        return any(start < b and a < start + length for a, b in free)
    slots = sorted(k for k, ptr in level.texmap['slots'].items()
                   if reaches(ptr, SLOT))
    tails = sorted(e['name'] for e in level.info['sprites']['store']
                   if reaches(e['address'], e['size'] + TAIL))
    out = {'format': 'level-inplay 1', 'map': 'E1M%d' % ld.gamemap,
           'textures': [{'texture': t, 'name': gd.textures[t].name,
                         'height': gd.textures[t].height} for t in later],
           'free': [[a, b] for a, b in free],
           'slots_reaching_free': slots, 'tails_reaching_free': tails}
    out['changeable_slots'] = slots if later else []
    out['changeable_tails'] = tails if later else []
    out['known_differences'] = (['texture %d (%s) is %d high' % (
        t['texture'], t['name'], t['height']) for t in out['textures']
        if t['height'] < 128] + ['slot %s' % s for s in
                                 out['changeable_slots']] +
        ['tail of %s' % s for s in out['changeable_tails']])
    if not later:
        out['proof'] = 'no texture is made in play: no run-time allocation'
    elif not slots and not tails:
        out['proof'] = 'no slot\'s or tail\'s bytes reach a free byte'
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--store', action='store_true', required=True)
    parser.parse_args(argv)
    for path in (U.RELEASE, U.WAD_PATH, U.LINKMAP):
        if not path.exists():
            print('%s is missing: run python3 tools/fetch_upstream.py and '
                  'python3 tools/v816/imgmatch.py first' % path,
                  file=sys.stderr)
            return 1
    from native import lstore
    return lstore.main_store(U.game_data())


if __name__ == '__main__':
    sys.exit(main())
