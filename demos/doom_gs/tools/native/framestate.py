#!/usr/bin/env python3
"""One captured frame as the native renderer's a2vm input (milestone 7,
docs/RENDER.md 2.3).

Usage:  python3 tools/native/framestate.py FRAME [--show]

FRAME is a frame directory of tools/native/rendercap.py
(build/native/render/frames/SET-NN). The reference's state at the frame's
R_FillStamps (its P0 dump) is read directly, by symbol and by upstream's
record offsets (offsets.inc, as the bridge's schema has them): P0 is a
partial dump, which the bridge's Reader cannot take (RENDER.md 2.3). On
the frame whose P0 is the moment of its level source (a full dump), the
Reader also reads the source, and the render fields of both reads must
be equal: that checks the direct reader.

What it writes (`records`): the render inputs (the player's view: RIN),
the frame block's inputs (viewtop, viewbottom, nukage, skyflatnum, the
automap mode, the psprite flags, validcount, numnodes, the span stamps,
the weapon skip's, the vertex cache's map unit and stamp, the vertex
count, the sky's slots; the renderer's state kept from frame to frame:
rw_scalestep, the fill bytes and their plane colours; everything else of
the block is left to the fill, so a field read before the frame writes
it shows), the dynamic level fields in LVMAP (every sector's and side's
render part), the vertex cache (the native stamp 1 and upstream's angle
for each vertex whose MM_SEGSTAMP equals VA_FRAME, 0 for the others, as
RENDER.md 2.3), TEXTRANS, LNMAP, the fill spans and covered ranges, the
weapon skip, the colormaps, and the seam bank SEAM: floorclip, FR_VIS
and MM_WPOK after the weapon's clip pass (P1) and, for the lockstep stub
of checkpoint A, the reference's R_StoreWallRange count and solidcol
after each call (calls.json). The level (levelconv.py), the tables
(rtables.py) and the code are the harness's (render_check.py).

Milestone 8 (docs/RENDER-MASKED.md 2.3), stage A, adds: the render
things (RTHING, bank RTH: every mobj on a sector's thing list, by pool
slot; a zone mobj past the pool takes the next slot in the order the
sectors' lists first reach it) and each sector's list head in its record;
each psprite's sprite, frame, sx and sy, the player's sector light and
invisibility power (render inputs); SPRBOUND ($22:7800, into bank SPRT:
upstream makes it at the first frame after a level load, RENDER-MASKED.md
0.3); FZ_POS (FZPOS). `slot_map` gives upstream's mobj pointers' slots
(rcanon.py compares a vissprite's thing by it).

Values the native layout cannot hold are refused (FrameError): a pic the
byte encoding of levelconv.py does not hold, a light index outside SMAP,
a view that is not the full view; milestone 8: a thing whose sprite or
frame the states do not use, more things than RTH's slots, FZ_POS past
49.
"""

import argparse
import json
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from bridge import linkmap as blink, upstream  # noqa: E402
from native import levelconv, rendercap, rlayout as R  # noqa: E402

ROOT = HERE.parent.parent
RENDER = ROOT / 'build' / 'native' / 'render'
FRAMES = RENDER / 'frames'

# upstream's record offsets (offsets.inc)
SIZEOF_SEC, SIZEOF_SIDE, SIZEOF_LINE = 58, 14, 36
OFS_SEC = {'floorheight': 0, 'ceilingheight': 4, 'validcount': 20,
           'floorpic': 44, 'ceilingpic': 46, 'lightlevel': 48}
OFS_SIDE = {'textureoffset': 4, 'rowoffset': 6, 'toptexture': 8,
            'bottomtexture': 10, 'midtexture': 12}
OFS_LINE_R_FLAGS = 32
OFS_PL_MO, OFS_PL_VIEWZ = 0, 11
OFS_PL_EXTRALIGHT, OFS_PL_FIXEDCOLORMAP = 125, 127
OFS_PL_PSPRITES, SIZEOF_PSP = 129, 12
OFS_MO_X, OFS_MO_Y, OFS_MO_ANGLE = 12, 16, 32
# milestone 8: the things (offsets.inc) and the player
OFS_MO_Z, OFS_MO_SNEXT, OFS_MO_SPRITE, OFS_MO_FRAME = 20, 24, 36, 38
OFS_MO_SUBSECTOR, OFS_MO_FLAGS = 48, 94
SIZEOF_MO = 120
MF_SHADOW = 1 << 18
OFS_SEC_THINGLIST = 22
OFS_SUB_SECTOR = 0
OFS_PSP_STATE, OFS_PSP_SX, OFS_PSP_SY = 0, 6, 8
OFS_ST_SPRITE, OFS_ST_FRAME = 0, 2
OFS_PL_POWERS, PW_INVISIBILITY = 41, 2
MM_SPRBOUND = 0x227800
FUZZ_POSITIONS = 50
ML_MAPPED = 256
WPAGE = 0x000A00
W = {'W_FSC': 0xE8, 'W_FSP': 0xE9, 'W_TOPR': 0xEA, 'W_BOTR': 0xEB,
     'W_FSG': 0xEC, 'W_FSW': 0xED, 'W_WSK': 0xB0}
WPLANE = {'W_CEILW': 0xE4, 'W_FLOORW': 0xE6, 'W_LCC': 0xEE, 'W_LFC': 0xF0}
MM_SEGANGLE, MM_SEGSTAMP = 0x230000, 0x234000
MM_FS = 0x23EF00
MM_WCLIP = 0x0AC500
MM_WPOK = 0x0AC84A
VW_CUR = 0x0AB802
FULL_VIEW = 0xA50A


class FrameError(Exception):
    pass


def s16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def s32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


class Dump:
    """A stored dump read by address (rendercap.load_dump)."""

    def __init__(self, path: Path):
        self.d = rendercap.load_dump(path)
        self.header = self.d.header

    def read(self, address: int, length: int) -> bytes:
        return self.d.get(address, length)

    def u(self, address: int, size: int) -> int:
        return int.from_bytes(self.read(address, size), 'little')


class Frame:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.meta = json.loads((self.dir / 'frame.json').read_text())
        self.name = self.meta['name']
        self.calls = json.loads((self.dir / 'calls.json').read_text())
        self._dumps: Dict[str, Dump] = {}

    def dump(self, what: str) -> Dump:
        if what not in self._dumps:
            self._dumps[what] = Dump(self.dir / (what + '.dump.z'))
        return self._dumps[what]


# ---------------------------------------------------------------------------
# The level of a frame
# ---------------------------------------------------------------------------

_LEVEL_LOCK = threading.Lock()


# A hook that replaces the converted level of a source by another level
# directory of the same layout (frame8.py --levels loaded, milestone 9:
# the natively loaded level read back, tools/native/lrun.py): called
# with levelconv.py's directory and the source's name, under the lock
LEVEL_HOOK = None


def level_of(frame: Frame, sym: blink.Symbols) -> Path:
    """The converted level of the frame's level source (levelconv.py),
    converted now when it is not yet (one thread at a time; the index
    replaced whole); through LEVEL_HOOK when one is set."""
    src = frame.meta['level_src']
    index = levelconv.LEVELS / 'by-source.json'
    with _LEVEL_LOCK:
        table = json.loads(index.read_text()) if index.exists() else {}
        got = table.get(src)
        if got and (Path(got) / 'level.json').exists():
            info = json.loads((Path(got) / 'level.json').read_text())
            if info.get('format') == levelconv.FORMAT and \
                    info.get('revision') == levelconv.REVISION:
                return LEVEL_HOOK(Path(got), src) if LEVEL_HOOK else \
                    Path(got)
        res = levelconv.run_one(levelconv.SOURCES / (src + '.ram.z'), sym)
        table[src] = res['dir']
        tmp = index.with_suffix('.tmp')
        tmp.write_text(json.dumps(table, indent=1) + '\n')
        tmp.replace(index)
        return LEVEL_HOOK(Path(res['dir']), src) if LEVEL_HOOK else \
            Path(res['dir'])


# ---------------------------------------------------------------------------
# The reference's render inputs at R_FillStamps
# ---------------------------------------------------------------------------

def read_inputs(frame: Frame, sym: blink.Symbols,
                level: Dict[str, Any]) -> Dict[str, Any]:
    p0 = frame.dump('p0')
    a = sym.address
    g2 = lambda n: p0.u(a(n), 2)  # noqa: E731
    ptr = lambda n: p0.u(a(n), 3)  # noqa: E731
    c = level['counts']
    out: Dict[str, Any] = {}
    if p0.u(VW_CUR, 2) != FULL_VIEW:
        raise FrameError('%s: not the full view (VW_CUR $%04X)'
                         % (frame.name, p0.u(VW_CUR, 2)))
    pl = a('_g_player')
    mo = p0.u(pl + OFS_PL_MO, 3)
    out['player'] = {
        'x': p0.u(mo + OFS_MO_X, 4), 'y': p0.u(mo + OFS_MO_Y, 4),
        'angle': p0.u(mo + OFS_MO_ANGLE, 4),
        'viewz': p0.u(pl + OFS_PL_VIEWZ, 4),
        'extralight': p0.u(pl + OFS_PL_EXTRALIGHT, 2),
        'fixedcolormap': p0.u(pl + OFS_PL_FIXEDCOLORMAP, 2)}
    psp = [p0.u(pl + OFS_PL_PSPRITES + SIZEOF_PSP * k, 4) for k in (0, 1)]
    out['psprites'] = (1 if psp[0] else 0) | (2 if psp[1] else 0)
    for name in ('_g_gamma', 'viewtop', 'viewbottom', 'nukage',
                 'skyflatnum', 'validcount', 'numnodes', 'automapmode'):
        out[name] = g2(name)
    if out['numnodes'] != c['nodes']:
        raise FrameError('%s: numnodes %d, the level %d' % (
            frame.name, out['numnodes'], c['nodes']))
    lightmax = 15 + out['_g_gamma'] + 16
    if not (0 <= out['_g_gamma'] and lightmax < 64):
        raise FrameError('%s: gamma %d: SMAP holds 64' % (frame.name,
                                                          out['_g_gamma']))
    if out['nukage'] > 255:
        raise FrameError('%s: nukage %d' % (frame.name, out['nukage']))
    out['skyflat'] = levelconv.pic_byte(s16(out['skyflatnum']),
                                        'skyflatnum', True)
    for k, off in W.items():
        out[k] = p0.u(WPAGE + off, 2 if k == 'W_WSK' else 1)
    if out['W_WSK'] > 255:
        raise FrameError('%s: W_WSK $%04X' % (frame.name, out['W_WSK']))
    # stage C: the native clip pass takes no wclipSprite (wclip.s): W_WSK is
    # 0 at every frame's start, as every frame's end leaves it
    if out['W_WSK']:
        raise FrameError('%s: W_WSK %d at R_FillStamps' % (frame.name,
                                                           out['W_WSK']))
    out['FR_SKIP'] = g2('FR_SKIP')
    # the renderer's state kept from frame to frame (RENDER.md 2.2):
    # rw_scalestep (a one-column wall of scaleSlow reads the last one), the
    # fill bytes and their plane colours (R_FillStamps resets the colours'
    # high bytes)
    out['rw_scalestep'] = p0.u(a('rw_scalestep'), 4)
    for k, off in WPLANE.items():
        out[k] = p0.u(WPAGE + off, 2)
    out['MM_WPOK'] = p0.u(MM_WPOK, 2)
    # stage C: the weapon's vissprite (FR_VIS, persistent: a frame that does
    # not write it keeps it) and WPREV, in their native 12 bytes
    # (RENDER-MASKED.md 1.7 as built)
    index = store_index(level)
    full = a('fullcolormap')
    out['frvis'] = native_vis(p0.read(a('FR_VIS'), SIZEOF_VIS), index, full)
    out['wprev'] = native_vis(p0.read(MM_WCLIP + 0x180, SIZEOF_VIS), index,
                              full)
    out['VA_FRAME'] = g2('VA_FRAME')
    out['VA_VX'] = g2('VA_VX')
    out['VA_VY'] = g2('VA_VY')
    # the level's dynamic fields
    secs = ptr('_g_sectors')
    if secs != level['sector_base']:
        raise FrameError('%s: the sectors moved from the level source'
                         % frame.name)
    sectors = []
    for i in range(c['sectors']):
        base = secs + SIZEOF_SEC * i
        sectors.append({
            'floorheight': s32(p0.u(base + OFS_SEC['floorheight'], 4)),
            'ceilingheight': s32(p0.u(base + OFS_SEC['ceilingheight'], 4)),
            'floorpic': s16(p0.u(base + OFS_SEC['floorpic'], 2)),
            'ceilingpic': s16(p0.u(base + OFS_SEC['ceilingpic'], 2)),
            'lightlevel': s16(p0.u(base + OFS_SEC['lightlevel'], 2)),
            'validcount': s16(p0.u(base + OFS_SEC['validcount'], 2))})
    out['sectors'] = sectors
    sides_at = ptr('_g_sides')
    sides = []
    for i in range(c['sides']):
        base = sides_at + SIZEOF_SIDE * i
        sides.append({k: s16(p0.u(base + o, 2)) for k, o in
                      OFS_SIDE.items()})
    out['sides'] = sides
    lines_at = ptr('_g_lines')
    out['mapped'] = [bool(p0.u(lines_at + SIZEOF_LINE * i +
                               OFS_LINE_R_FLAGS, 2) & ML_MAPPED)
                     for i in range(c['lines'])]
    tt = ptr('texturetranslation')
    n = level['counts']['numtextures']
    trans = [p0.u(tt + 2 * t, 2) for t in range(n + 1)]
    if max(trans) > 255:
        raise FrameError('%s: texturetranslation holds %d' % (
            frame.name, max(trans)))
    out['texturetranslation'] = trans
    # the vertex cache (MM_SEGANGLE, MM_SEGSTAMP by upstream's numbers)
    upv = level['upstream_vertex']
    cache = []
    for u in upv:
        stamp = p0.u(MM_SEGSTAMP + 2 * u, 2)
        valid = out['VA_FRAME'] != 0 and stamp == out['VA_FRAME']
        cache.append(p0.u(MM_SEGANGLE + 2 * u, 2) if valid else None)
    out['vertex_cache'] = cache
    out['spans'] = p0.read(MM_FS, 0xC00)
    out['weapon'] = p0.read(MM_WCLIP, 0x300)     # WCLIP, WPREV, WTMP
    out['colormaps'] = p0.read(a('iigs_shrcmapA'), 2 * 34 * 256)
    out['flatcm'] = p0.read(a('FLATCM'), 34 * 32)
    # milestone 8 (RENDER-MASKED.md 2.3): the things, the psprites, the
    # player's sector light and invisibility, SPRBOUND, FZ_POS
    heads, things, slots = read_things(p0, sym, secs, c['sectors'], level)
    out['heads'], out['things'], out['slots'] = heads, things, slots
    for i, s in enumerate(sectors):
        s['things'] = heads[i]
    pspr = []
    for k in (0, 1):
        at = pl + OFS_PL_PSPRITES + SIZEOF_PSP * k
        state = p0.u(at + OFS_PSP_STATE, 4) & 0xFFFFFF
        spr = p0.u(state + OFS_ST_SPRITE, 2) if state else 0xFF
        frm = p0.u(state + OFS_ST_FRAME, 2) if state else 0xFFFF
        if spr > 255:
            raise FrameError('%s: psprite %d has sprite %d' % (frame.name,
                                                                k, spr))
        pspr.append({'sprite': spr, 'frame': frm,
                     'sx': p0.u(at + OFS_PSP_SX, 2),
                     'sy': p0.u(at + OFS_PSP_SY, 4)})
    out['pspr'] = pspr
    sub = p0.u(mo + OFS_MO_SUBSECTOR, 4) & 0xFFFFFF
    sec = p0.u(sub + OFS_SUB_SECTOR, 4) & 0xFFFFFF
    light = p0.u(sec + OFS_SEC['lightlevel'], 2)
    if light > 255:
        raise FrameError('%s: the player\'s sector light %d' % (frame.name,
                                                               light))
    out['player_light'] = light
    out['invis'] = p0.u(pl + OFS_PL_POWERS + 2 * PW_INVISIBILITY, 2)
    out['sprbound'] = p0.read(MM_SPRBOUND, 4 * R.NUMSPRITES)
    fz = p0.u(a('FZ_POS'), 2)
    if fz >= FUZZ_POSITIONS:
        raise FrameError('%s: FZ_POS %d' % (frame.name, fz))
    out['fzpos'] = fz
    return out


SIZEOF_VIS = 42                 # upstream's vissprite_t (offsets.inc)
OFS_VIS = {'X1': 0, 'X2': 2, 'TMID': 28, 'SFRAC': 16, 'LUMP': 34,
           'COLORMAP': 38}
UNKNOWN_PATCH = 0xFFFE          # a lump no stored patch is (a stale field)


def store_index(level: Dict[str, Any]) -> Dict[int, int]:
    """Each stored lump's patch store index (levelconv.py)."""
    return {e['lump']: e['index'] for e in level['sprites']['store']}


def native_vis(data: bytes, index: Dict[int, int], full: int) -> bytes:
    """Upstream's vissprite_t of the weapon (FR_VIS, WPREV) as the native
    12 bytes (rlayout.FV): the lump as its patch store index ($FFFF stays,
    WPREV's none; a lump no stored patch is, a field no frame has written
    yet, UNKNOWN_PATCH), texturemid, x1 (its low byte), x2, startfrac's
    high word, the colormap as its record page (0: NULL; $FF: no colormap
    page, a stale field). The fields pspSprite does not write are its
    constants or never written (RENDER-MASKED.md 1.7), so the compare of
    the 42 bytes is the compare of these."""
    def u(o: int, n: int) -> int:
        return int.from_bytes(data[o:o + n], 'little')
    lump = u(OFS_VIS['LUMP'], 2)
    patch = 0xFFFF if lump == 0xFFFF else index.get(lump, UNKNOWN_PATCH)
    cm = u(OFS_VIS['COLORMAP'], 3)
    if cm == 0:
        page = 0
    elif (cm - full) % 256 == 0 and 0 <= (cm - full) // 256 < 34:
        page = 0x46 + (cm - full) // 256
    else:
        page = 0xFF
    out = bytearray(R.FV_SIZE)
    F = R.FV
    out[F['PATCH']:F['PATCH'] + 2] = patch.to_bytes(2, 'little')
    out[F['TMID']:F['TMID'] + 4] = data[OFS_VIS['TMID']:OFS_VIS['TMID'] + 4]
    out[F['X1']] = data[OFS_VIS['X1']]
    out[F['X2']:F['X2'] + 2] = data[OFS_VIS['X2']:OFS_VIS['X2'] + 2]
    out[F['SFRAC']:F['SFRAC'] + 2] = data[OFS_VIS['SFRAC'] + 2:
                                          OFS_VIS['SFRAC'] + 4]
    out[F['PAGE']] = page
    return bytes(out)


def slot_map(p0, sym: blink.Symbols, sector_base: int, nsectors: int
             ) -> Dict[int, int]:
    """Each mobj on a sector's thing list, upstream's pointer to its
    RTHING slot: a mobj of the pool (_g_thingPool) its index, as
    upstream's pool slot policy keeps it (NATIVE.md 6); a zone mobj past
    the pool the next free slot, in the order the sectors' lists (sector
    0 first) first reach it."""
    a = sym.address
    pool = p0.u(a('_g_thingPool'), 3)
    size = p0.u(a('_g_thingPoolSize'), 2)
    out: Dict[int, int] = {}
    extra = size
    for i in range(nsectors):
        ptr = p0.u(sector_base + SIZEOF_SEC * i + OFS_SEC_THINGLIST, 4) & \
            0xFFFFFF
        steps = 0
        while ptr:
            steps += 1
            if steps > 10000 or ptr in out:
                raise FrameError('sector %d: its thing list does not end'
                                 % i)
            if pool <= ptr < pool + SIZEOF_MO * size and \
                    (ptr - pool) % SIZEOF_MO == 0:
                out[ptr] = (ptr - pool) // SIZEOF_MO
            else:
                out[ptr] = extra
                extra += 1
            ptr = p0.u(ptr + OFS_MO_SNEXT, 4) & 0xFFFFFF
    if extra > R.RTHINGS.capacity:
        raise FrameError('%d thing slots: RTH holds %d'
                         % (extra, R.RTHINGS.capacity))
    return out


def read_things(p0, sym: blink.Symbols, sector_base: int, nsectors: int,
                level: Dict[str, Any]) -> Tuple[List[int], Dict[int, Dict],
                                                Dict[int, int]]:
    """Each sector's list head (a slot, NO_THING), each thing's render
    fields by slot, and the pointer-to-slot map."""
    slots = slot_map(p0, sym, sector_base, nsectors)
    nframes = level['sprites']['frames_per_sprite']
    heads: List[int] = []
    things: Dict[int, Dict] = {}
    for i in range(nsectors):
        ptr = p0.u(sector_base + SIZEOF_SEC * i + OFS_SEC_THINGLIST, 4) & \
            0xFFFFFF
        heads.append(slots[ptr] if ptr else R.NO_THING)
        while ptr:
            nxt = p0.u(ptr + OFS_MO_SNEXT, 4) & 0xFFFFFF
            sprite = p0.u(ptr + OFS_MO_SPRITE, 2)
            frm = p0.u(ptr + OFS_MO_FRAME, 2)
            if sprite >= R.NUMSPRITES or (frm & 0x7FFF) >= nframes[sprite]:
                raise FrameError('a thing of sprite %d frame %d, which the '
                                 'states do not use' % (sprite, frm))
            things[slots[ptr]] = {
                'x': p0.u(ptr + OFS_MO_X, 4), 'y': p0.u(ptr + OFS_MO_Y, 4),
                'z': p0.u(ptr + OFS_MO_Z, 4),
                'angle': p0.u(ptr + OFS_MO_ANGLE + 2, 2),
                'sprite': sprite, 'frame': frm,
                'shadow': bool(p0.u(ptr + OFS_MO_FLAGS, 4) & MF_SHADOW),
                'snext': slots[nxt] if nxt else R.NO_THING}
            ptr = nxt
    return heads, things, slots


def rthing_record(th: Dict[str, Any]) -> bytes:
    rec = bytearray(R.RTHING_SIZE)
    T = R.RTHING
    for k, key in (('X', 'x'), ('Y', 'y'), ('Z', 'z')):
        rec[T[k]:T[k] + 4] = th[key].to_bytes(4, 'little')
    rec[T['ANG']:T['ANG'] + 2] = th['angle'].to_bytes(2, 'little')
    rec[T['SPR']] = th['sprite']
    rec[T['FRAME']:T['FRAME'] + 2] = th['frame'].to_bytes(2, 'little')
    rec[T['FLAGS']] = 1 if th['shadow'] else 0
    rec[T['SNEXT']:T['SNEXT'] + 2] = th['snext'].to_bytes(2, 'little')
    return bytes(rec)


def cross_check(frame: Frame, inputs: Dict[str, Any],
                sym: blink.Symbols) -> Optional[str]:
    """On the frame of the level source's moment: the bridge's Reader on
    the full dump against the direct reads (the render fields)."""
    src = rendercap.LEVEL_SOURCES / (frame.meta['level_src'] + '.json')
    info = json.loads(src.read_text())
    if info['cycles'] != frame.dump('p0').header['cycles']:
        return None
    memory = levelconv.load_memory(rendercap.LEVEL_SOURCES /
                                   (frame.meta['level_src'] + '.ram.z'))
    reader = upstream.Reader(memory)
    state = reader.read()
    if reader.problems:
        raise FrameError('the Reader: %s' % reader.problems[:3])
    objs = state['objects']
    for i, s in enumerate(inputs['sectors']):
        u = objs['sector'][i]
        for k, v in s.items():
            if k == 'things':           # (a slot: milestone 8's own)
                continue
            if u[k] != v:
                raise FrameError('%s: sector %d %s: direct %r, Reader %r'
                                 % (frame.name, i, k, v, u[k]))
    for i, s in enumerate(inputs['sides']):
        u = objs['side'][i]
        for k, v in s.items():
            if u[k] != v:
                raise FrameError('%s: side %d %s: direct %r, Reader %r'
                                 % (frame.name, i, k, v, u[k]))
    for i, m in enumerate(inputs['mapped']):
        if bool(objs['line'][i]['r_flags'] & ML_MAPPED) != m:
            raise FrameError('%s: line %d mapped differs' % (frame.name, i))
    return 'the Reader agrees on %d sectors, %d sides, %d lines' % (
        len(inputs['sectors']), len(inputs['sides']), len(inputs['mapped']))


# ---------------------------------------------------------------------------
# The records
# ---------------------------------------------------------------------------

def le(v: int, n: int) -> bytes:
    return (v & ((1 << (8 * n)) - 1)).to_bytes(n, 'little')


def records(frame: Frame, inputs: Dict[str, Any], level: Dict[str, Any]
            ) -> List[Tuple[int, int, int, bytes]]:
    """(kind, bank, address, bytes) records of the frame's state."""
    out: List[Tuple[int, int, int, bytes]] = []

    def main(address: int, data: bytes) -> None:
        out.append((0, 0, address, bytes(data)))

    def aux(bank: int, address: int, data: bytes) -> None:
        out.append((1, bank, address, bytes(data)))
    p = inputs['player']
    rin = R.RINS
    main(rin['PL_X'], le(p['x'], 4))
    main(rin['PL_Y'], le(p['y'], 4))
    main(rin['PL_ANGLE'], le(p['angle'], 4))
    main(rin['PL_VIEWZ'], le(p['viewz'], 4))
    main(rin['PL_XLIGHT'], le(p['extralight'], 2))
    main(rin['PL_FIXCM'], le(p['fixedcolormap'], 2))
    main(rin['GAMMA'], le(inputs['_g_gamma'], 2))
    F = R.FRAME
    main(F['VIEWTOP'], le(inputs['viewtop'], 1))
    main(F['VIEWBOT'], le(inputs['viewbottom'], 1))
    main(F['NUKAGE'], le(inputs['nukage'], 1))
    main(F['SKYFLAT'], bytes([inputs['skyflat']]))
    main(F['AUTOMAP'], le(inputs['automapmode'], 1))
    main(F['PSPF'], bytes([inputs['psprites']]))
    main(F['VALIDCOUNT'], le(inputs['validcount'], 2))
    main(F['NUMNODES'], le(inputs['numnodes'], 2))
    for k in W:
        main(F[k], le(inputs[k], 1))
    main(F['FR_SKIP'], le(inputs['FR_SKIP'], 2))
    main(F['MM_WPOK'], bytes([1 if inputs['MM_WPOK'] == 0x5AA5 else 0]))
    main(F['VA_VX'], le(inputs['VA_VX'], 2))
    main(F['VA_VY'], le(inputs['VA_VY'], 2))
    main(F['VA_STAMP'], bytes([1 if inputs['VA_FRAME'] else 0]))
    main(F['NVERT'], le(level['counts']['vertices'], 2))
    main(R.LVCOUNT, le(level['counts']['sectors'], 2) +
         le(level['counts']['sides'], 2))
    main(F['STATUS'], b'\0')
    main(F['RULES'], b'\0')
    # milestone 8: FZ_POS (persistent), the psprites, the player's sector
    # light and invisibility, SPRBOUND, the render things
    main(F['FZPOS'], bytes([inputs['fzpos']]))
    for k, ps in enumerate(inputs['pspr']):
        pre = 'PSP%d_' % k
        main(rin[pre + 'SPR'], bytes([ps['sprite']]))
        main(rin[pre + 'FRAME'], le(ps['frame'], 2))
        main(rin[pre + 'SX'], le(ps['sx'], 2))
        main(rin[pre + 'SY'], le(ps['sy'], 4))
    main(rin['PL_SECLIGHT'], bytes([inputs['player_light']]))
    main(rin['PL_INVIS'], le(inputs['invis'], 2))
    aux(R.SPRT, R.SPRBOUND_T, inputs['sprbound'])
    for slot in sorted(inputs['things']):
        aux(R.RTH, R.RTHINGS.address(slot),
            rthing_record(inputs['things'][slot]))
    main(F['VA_COUNT'], b'\0\0')
    main(F['RW_STEP'], le(inputs['rw_scalestep'], 4))
    for k in WPLANE:
        main(F[k], le(inputs[k], 2))
    sky = level['sky']
    main(F['SKYBANK'], bytes([sky['bank'], sky['base'] & 0xFF,
                              sky['base'] >> 8]))
    # the dynamic level fields
    data = bytearray()
    for i, s in enumerate(inputs['sectors']):
        data += levelconv.sector_record(s, i)
    aux(R.LVMAP, R.SECTORS.base, data)
    data = bytearray()
    for i, s in enumerate(inputs['sides']):
        data += levelconv.side_record(s, i)
    aux(R.LVMAP, R.SIDES.base, data)
    lo, hi, st = bytearray(), bytearray(), bytearray()
    for angle in inputs['vertex_cache']:
        lo.append(0 if angle is None else angle & 0xFF)
        hi.append(0 if angle is None else angle >> 8)
        st.append(0 if angle is None else 1)
    aux(R.LVMAP, R.VAL, lo)
    aux(R.LVMAP, R.VAH, hi)
    aux(R.LVMAP, R.VAS, st)
    trans = bytearray(256)
    for t, v in enumerate(inputs['texturetranslation'][:256]):
        trans[t] = v
    main(R.TEXTRANS, trans)
    bits = bytearray(R.LNMAP_LINES // 8)
    for i, m in enumerate(inputs['mapped']):
        if m:
            bits[i >> 3] |= 1 << (i & 7)
    main(R.LNMAP, bits)
    # the spans (FS_ROW, FS_EVEN, FS_ODD, FS_STAMP: bytes 2c and 2c + 1 of
    # each, the top and bottom spans) as the 8 planes of MEMORY_MAP 3.3,
    # and the covered ranges; the weapon skip
    sp = inputs['spans']
    planes = []
    for table in range(4):
        base = 0x200 * table
        planes.append(bytes(sp[base + 2 * c] for c in range(160)))
        planes.append(bytes(sp[base + 2 * c + 1] for c in range(160)))
    main(R.SPANS, b''.join(planes))
    cv = bytes(sp[0x800 + 2 * c] for c in range(160)) + \
        bytes(sp[0x800 + 2 * c + 1] for c in range(160))
    main(R.CVFIRST, cv)
    wp = inputs['weapon']
    main(R.WCLIP, bytes(wp[2 * c] for c in range(160)))
    main(R.WPREV, inputs['wprev'])
    main(R.FRVIS, inputs['frvis'])
    # milestone 8, stage B: WTMP, wclipSprite's floor clip, which a sprite
    # drawn past x2 + 1 reads as the sprites before left it (words, their
    # low bytes: the stores are 8-bit)
    main(R.WTMP, bytes(wp[0x1C0 + 2 * c] for c in range(160)))
    # the colormaps: A levels 0-31 at $2000, B at $4000; 32, 33 at $0400
    cm = inputs['colormaps']
    a_maps, b_maps = cm[:34 * 256], cm[34 * 256:]
    main(0x2000, a_maps[:32 * 256])
    main(0x4000, b_maps[:32 * 256])
    main(0x0400, a_maps[32 * 256:])
    main(0x0600, b_maps[32 * 256:])
    return out


def seam_records(frame: Frame, sym: blink.Symbols
                 ) -> List[Tuple[int, int, int, bytes]]:
    """Checkpoint A's lockstep data in bank SEAM (milestone 8's stage C
    made the weapon's clip pass native: the seam of floorclip, FR_VIS and
    MM_WPOK after it is gone)."""
    walls = frame.calls['storewall']
    if len(walls) > R.SEAM_SOLID_MAX:
        raise FrameError('%s: %d walls, the seam holds %d' % (
            frame.name, len(walls), R.SEAM_SOLID_MAX))
    solids = bytearray()
    for call in walls:
        mem = bytes.fromhex(call['out']['mem'][0])
        if len(mem) != 160:
            raise FrameError('a call without its solidcol')
        solids += mem
    out = [(1, R.SEAM, R.SEAM_HDR, bytes([len(walls)]))]
    if solids:
        out.append((1, R.SEAM, R.SEAM_SOLID, bytes(solids)))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('frame', type=Path)
    parser.add_argument('--show', action='store_true')
    args = parser.parse_args(argv)
    sym = blink.Symbols()
    frame = Frame(args.frame)
    try:
        level_dir = level_of(frame, sym)
        level = json.loads((level_dir / 'level.json').read_text())
        inputs = read_inputs(frame, sym, level)
        note = cross_check(frame, inputs, sym)
        recs = records(frame, inputs, level) + seam_records(frame, sym)
    except (FrameError, levelconv.ConvError) as error:
        print('framestate: %s' % error, file=sys.stderr)
        return 1
    print('%s: level %s, %d records, %d bytes%s' % (
        frame.name, level_dir.name, len(recs), sum(len(r[3]) for r in recs),
        '; ' + note if note else ''))
    if args.show:
        p = inputs['player']
        print('  view (%08X, %08X) angle %08X viewz %08X; validcount %d; '
              'VA_FRAME %d; %d cached vertices' % (
                  p['x'], p['y'], p['angle'], p['viewz'],
                  inputs['validcount'], inputs['VA_FRAME'],
                  sum(v is not None for v in inputs['vertex_cache'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
