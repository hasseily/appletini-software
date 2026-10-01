#!/usr/bin/env python3
"""A host model of upstream's sprite projection and sort (milestone 8,
stage A; docs/RENDER-MASKED.md 0.3, 1.6-1.8): R_AddSprites and
R_ProjectSprite (r_thing65.s:155-707, :713-821, :1008-1245), R_WallFrame's
G parts and prFrame (r_wall65.s:1873-1917, r_thing65.s:1096-1189),
sortSprites and sortSkip (r_frame65.s:288-347, :995-1015), written from
the sources with the same integer steps, on the reference's own state.

Usage:  python3 tools/native/projmodel.py [--sets ...] [--frames ...]

It is not the port: the native code is src/native/mproj.s. The model
exists to check what this stage reads of upstream before the native code
is compared with it: on each captured frame its vissprites must equal
ref816's at drawMasked (P3) and its order, FR_SKIP and W_WSK those after
sortSkip (P3s). It reads the frame's P0 (the things, sectors, SPRBOUND,
the player), P0b (setupFrame's viewsin, viewcos, LT_BASE, fixedcolormap),
the level source (the sprite frames, the patches, the scale tables) and
the call log's R_AddSprites calls (the sectors, in walk order).

Its pieces are shared: `vissprites_ref` reads upstream's vissprites in a
dump in canonical form (rcanon.py uses it), `qmulh` and `fixmul` are the
MATH.md host models.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import mathdefs as MD  # noqa: E402

M16, M32 = 0xFFFF, 0xFFFFFFFF
SIZEOF_VIS = 42
OFS_VIS = {'x1': 0, 'x2': 2, 'gx': 4, 'gy': 8, 'gz': 12, 'startfrac': 16,
           'scale': 20, 'xiscale': 24, 'texturemid': 28, 'fracstep': 32,
           'lump': 34, 'topoffset': 36, 'colormap': 38}
OFS_MO = {'x': 12, 'y': 16, 'z': 20, 'snext': 24, 'angle': 32,
          'sprite': 36, 'frame': 38, 'flags': 94}
OFS_SEC_THINGLIST, OFS_SEC_LIGHTLEVEL = 22, 48
SIZEOF_SEC = 58
OFS_SF_FLIPMASK, OFS_SF_ROTATE, SIZEOF_SF = 16, 17, 19
MF_SHADOW_HI = 4
FF_FULLBRIGHT = 0x8000
MAXVISSPRITES = 80
VIEWWIDTH = 160
MAXZ_HI = 1280
SPRXSCALE, SPRYSCALE, SPRISCALE, FQ = 0x220000, 0x222000, 0x224000, \
    0x226000
SPRBOUND = 0x227800
WAD = 0x100000
CMAPA_PAGE = 0x46
WPAGE_W_WSK = 0x000AB0


def s16(v: int) -> int:
    v &= M16
    return v - 0x10000 if v & 0x8000 else v


def s32(v: int) -> int:
    v &= M32
    return v - 0x100000000 if v & 0x80000000 else v


def qmulh(a: int, b: int) -> int:
    return MD.m_qmulh(a & M16, b & M16)


def fixmul(a: int, b: int) -> int:
    return MD.m_fixmul(a & M32, b & M32)


def smul(h: int, c: int) -> int:
    """A signed 16-bit h times a signed 32-bit c, modulo 2^32 (gTZ's and
    gTX's products)."""
    return (s16(h) * s32(c)) & M32


def gpart(low: int, b: int, exact: bool) -> int:
    """G(L, b) = hi16(L * b.lo) - (b.hi != 0 ? L : 0) as a 32-bit value
    (GPART of r_wall65.s with qmulL, exact; gGZ and gGX of r_thing65.s
    with qmulh)."""
    low &= M16
    hi = ((low * (b & M16)) >> 16) if exact else qmulh(low, b)
    if (b >> 16) & M16:
        return (hi - low) & M32
    return hi


def frame_view(p0b, sym) -> Dict[str, int]:
    """setupFrame's outputs at R_RenderBSPNode (P0b)."""
    a = sym.address
    return {'viewx': p0b.u(a('viewx'), 4), 'viewy': p0b.u(a('viewy'), 4),
            'viewz': p0b.u(a('viewz'), 4),
            'viewsin': p0b.u(a('viewsin'), 4),
            'viewcos': p0b.u(a('viewcos'), 4),
            'lt_base': p0b.u(a('LT_BASE'), 2),
            'fixedcolormap': p0b.u(a('fixedcolormap'), 4)}


def g_parts(v: Dict[str, int]) -> Tuple[int, int]:
    """R_WallFrame's PR_GZ, PR_GX: the G parts of a thing at whole map
    units (the low words of tr_x, tr_y are -viewx.lo, -viewy.lo)."""
    t = (-v['viewx']) & M16
    eh = (-v['viewy']) & M16
    c, s = v['viewcos'], v['viewsin']
    gz = (gpart(t, c, True) + gpart(eh, s, True)) & M32
    gx = (gpart(t, s, True) - gpart(eh, c, True)) & M32
    return gz, gx


class Sprites:
    """The sprite data of a level source (all RAM), read as upstream's
    projection reads it."""

    def __init__(self, mem, sym):
        self.m = mem
        self.sym = sym
        self.fileinfo = mem.uint(sym.address('fileinfo'), 3)
        self.sprites = mem.uint(sym.address('sprites'), 3)

    def frame_address(self, sprite: int, frame: int) -> int:
        sf = self.m.uint(self.sprites + 4 * sprite, 4)
        # 19 * (frame & $7FFF) & $7FFF added to the pointer's low word
        low = (sf + ((19 * (frame & 0x7FFF)) & 0x7FFF)) & M16
        return (sf & 0xFF0000) | low

    def lump_address(self, lump: int) -> int:
        e = self.fileinfo + 16 * lump
        lo, hi = self.m.u16(e), self.m.u16(e + 2)
        return (((hi + (WAD >> 16)) & M16) << 16 | lo) & 0xFFFFFF


def vissprites_ref(d, sym, count: Optional[int] = None) -> List[Dict]:
    """Upstream's vissprites in a dump (P3), raw fields."""
    a = sym.address
    n = d.u(a('num_vissprite'), 2) if count is None else count
    base = a('vissprites')
    out = []
    for i in range(n):
        at = base + SIZEOF_VIS * i
        rec = {}
        for k, o in OFS_VIS.items():
            size = 2 if k in ('x1', 'x2', 'fracstep', 'lump',
                              'topoffset') else 4
            rec[k] = d.u(at + o, size)
        out.append(rec)
    return out


def project(p0, p0b, level_mem, sym, sectors: Sequence[Tuple[int, int]]
            ) -> Tuple[List[Dict], List[str]]:
    """Upstream's projection of the listed sectors (pointer, light) on the
    frame's state: its vissprites (raw fields, as vissprites_ref) and the
    paths taken."""
    v = frame_view(p0b, sym)
    gz0, gx0 = g_parts(v)
    spr = Sprites(level_mem, sym)
    a = sym.address
    lt_base = v['lt_base']
    smap = [level_mem.u16(a('SMAP') + 2 * i) for i in range(64)]
    cmo = [level_mem.u16(a('CMO') + 2 * i) for i in range(85)]
    fullcm = a('fullcolormap')
    c, s = v['viewcos'], v['viewsin']
    csign, ssign = c >> 31, s >> 31
    out: List[Dict] = []
    paths: List[str] = []
    for sec, light in sectors:
        th = p0.u(sec + OFS_SEC_THINGLIST, 4) & 0xFFFFFF
        pr_s = smap[(light >> 4) + lt_base]
        steps = 0
        while th:
            steps += 1
            if steps > 10000:
                raise ValueError('a thing list without its end')
            vis = project_one(p0, th, v, gz0, gx0, spr, pr_s, cmo, fullcm,
                              csign, ssign, len(out), paths, level_mem, sym)
            if vis is not None:
                out.append(vis)
            th = p0.u(th + OFS_MO['snext'], 4) & 0xFFFFFF
    return out, paths


def project_one(p0, th, v, gz0, gx0, spr, pr_s, cmo, fullcm, csign, ssign,
                nvis, paths, lm, sym) -> Optional[Dict]:
    x = p0.u(th + OFS_MO['x'], 4)
    y = p0.u(th + OFS_MO['y'], 4)
    trx = (x - v['viewx']) & M32
    try_ = (y - v['viewy']) & M32
    txh, tyh = trx >> 16, try_ >> 16
    # behind the view: TXH and c of opposite signs, and TYH and s
    if (txh >> 15) != csign and (tyh >> 15) != ssign:
        paths.append('reject:behind')
        return None
    whole = (x & M16) == 0 and (y & M16) == 0
    if whole:
        gz, gx = gz0, gx0
    else:
        paths.append('gGZ')
        txl, tyl = trx & M16, try_ & M16
        gz = (gpart(txl, v['viewcos'], False) +
              gpart(tyl, v['viewsin'], False)) & M32
        gx = (gpart(txl, v['viewsin'], False) -
              gpart(tyl, v['viewcos'], False)) & M32
    tz = (smul(txh, v['viewcos']) + smul(tyh, v['viewsin']) + gz) & M32
    tzh = tz >> 16
    if not (((tzh - 4) & M16) < MAXZ_HI - 4 or
            (tzh == MAXZ_HI and tz & M16 == 0)):
        paths.append('reject:tz')
        return None
    tx = (smul(txh, v['viewsin']) - smul(tyh, v['viewcos']) + gx) & M32
    sprite = p0.u(th + OFS_MO['sprite'], 2)
    e = p0.u(SPRBOUND + 4 * sprite, 2)
    k = ((tzh >> 6) + e + 1 + tzh + 1) & M16
    txhi = tx >> 16
    if txhi & 0x8000:
        test = (k + txhi) & M16
    else:
        test = (k - txhi - 1) & M16
    if test & 0x8000:
        paths.append('reject:sprbound')
        return None
    if tzh < p0.u(SPRBOUND + 4 * sprite + 2, 2):
        paths.append('labsTZ')
        t4 = (tz << 2) & M32
        val = (t4 - tx) & M32 if not txhi & 0x8000 else (t4 + tx) & M32
        if val & 0x80000000:
            paths.append('reject:labsTZ')
            return None
    frame = p0.u(th + OFS_MO['frame'], 2)
    sf = spr.frame_address(sprite, frame)
    rot = 0
    rotate = lm.read(sf + OFS_SF_ROTATE, 1)[0]
    if rotate:
        from native.mathdefs import m_pta16
        tanto = _tanto(lm, sym)
        ang = m_pta16(x >> 16, y >> 16, v['viewx'] >> 16, v['viewy'] >> 16,
                      tanto)
        ang = (ang - (p0.u(th + OFS_MO['angle'] + 2, 2)) + 0x9000) & M16
        rot = (ang >> 13) & 7
        paths.append('rotate')
    flip = (1 << rot) & lm.read(sf + OFS_SF_FLIPMASK, 1)[0]
    lump = lm.u16(sf + 2 * rot)
    pt = spr.lump_address(lump)
    width = lm.u16(pt)
    left = lm.u16(pt + 4)
    top = lm.u16(pt + 6)
    sub = ((width - left) & M16) if flip else left
    tx = ((((tx >> 16) - sub) & M16) << 16) | (tx & M16)
    tables = _scale_tables()
    xscale = tables.u32(SPRXSCALE + 4 * tzh)
    w = (width * xscale) & M32
    if w < 0x14001:
        paths.append('reject:small')
        return None
    if xscale >> 16 == 0:
        txl, txhs = tx & M16, s16(tx >> 16)
        hs = qmulh(txl, xscale)
        hi_prod = (txhs * (xscale & M16)) & M32     # TXH * xs.lo, signed
        xl = (hi_prod + hs) & M32
        if xl & M16 == 0 or (xl + w) & M16 == 0:
            paths.append('fixmulx:xl' if xl & M16 == 0 else 'fixmulx:xr')
            xl = fixmul(tx, xscale)
    else:
        xl = fixmul(tx, xscale)
        paths.append('wHi')
    x1 = s16((xl >> 16) + VIEWWIDTH // 2)
    xl = (xl & M16) | ((x1 & M16) << 16)
    if x1 > VIEWWIDTH:
        paths.append('reject:x1')
        return None
    xr = (xl + w - 0x10000) & M32
    if xr & 0x80000000:
        paths.append('reject:xr')
        return None
    if nvis >= MAXVISSPRITES:
        paths.append('reject:maxvis')
        return None
    z = p0.u(th + OFS_MO['z'], 4)
    tmid = (z - v['viewz'] + ((top & M16) << 16)) & M32
    scale = tables.u32(SPRYSCALE + 4 * tzh)
    t = (tz >> 12) & 15
    q, r = tables.u16(FQ + 4 * tzh), tables.u16(FQ + 4 * tzh + 2)
    fracstep = (q + (r + t) // 5) & M16
    iscale = tables.u32(SPRISCALE + 4 * tzh)
    if flip:
        xiscale = (-iscale) & M32
        startfrac = (((width - 1) & M16) << 16) | 0xFFFF
        paths.append('flip')
    else:
        xiscale = iscale
        startfrac = 0
    if x1 < 0:
        startfrac = (startfrac + xiscale * (-x1)) & M32
        paths.append('x1neg')
    flags = p0.u(th + OFS_MO['flags'], 4)
    fixed = v['fixedcolormap']
    if (flags >> 16) & MF_SHADOW_HI:
        colormap = 0
        paths.append('shadow')
    elif fixed:
        colormap = fixed
        paths.append('fixed')
    elif frame & FF_FULLBRIGHT:
        colormap = fullcm
        paths.append('fullbright')
    else:
        idx = ((scale >> 8) & M16) >> 5
        idx = 23 if idx >= 24 else idx
        colormap = fullcm + cmo[pr_s - idx]
    return {'x1': max(x1, 0) & M16,
            'x2': min(xr >> 16, VIEWWIDTH - 1),
            'gx': th, 'gy': pt, 'gz': z, 'startfrac': startfrac,
            'scale': scale, 'xiscale': xiscale, 'texturemid': tmid,
            'fracstep': fracstep, 'lump': lump, 'topoffset': top,
            'colormap': colormap}


_TANTO: Dict[int, List[int]] = {}


def _tanto(lm, sym) -> List[int]:
    key = id(lm)
    if key not in _TANTO:
        base = sym.address('tantoangleTable')
        _TANTO[key] = [lm.u32(base + 4 * i) for i in range(2049)]
    return _TANTO[key]


def sort_skip(vis: List[Dict], fr_skip: int, w_wsk: int
              ) -> Tuple[List[int], int, int]:
    """sortSprites (the insertion sort of the scales, largest first, equal
    ones in their order) and sortSkip: the order as vissprite indexes,
    FR_SKIP and W_WSK."""
    order = list(range(len(vis)))
    for i in range(1, len(order)):
        temp = order[i]
        j = i
        while j > 0 and s32(vis[order[j - 1]]['scale']) < \
                s32(vis[temp]['scale']):
            order[j] = order[j - 1]
            j -= 1
        order[j] = temp
    if fr_skip and vis and any(v['colormap'] == 0 for v in vis):
        fr_skip, w_wsk = 0, 0
    return order, fr_skip, w_wsk


def check_frame(directory: Path, sym) -> List[str]:
    from native import framestate as FS, levelconv as LC
    frame = FS.Frame(directory)
    p0, p0b, p3 = frame.dump('p0'), frame.dump('p0b'), frame.dump('p3')
    lm = _level_memory(frame.meta['level_src'])
    calls = listed_sectors(frame)
    if calls is None:
        return ['no R_AddSprites calls (capture again)']
    got, _ = project(p0, p0b, lm, sym, calls)
    want = vissprites_ref(p3, sym)
    out = []
    if len(got) != len(want):
        out.append('%d vissprites, reference %d' % (len(got), len(want)))
    for i, (g, w) in enumerate(zip(got, want)):
        if g != w:
            keys = [k for k in w if g.get(k) != w[k]]
            out.append('vissprite %d: %s: model %s, reference %s' % (
                i, keys, [g.get(k) for k in keys], [w[k] for k in keys]))
            break
    p3s = frame.dump('p3s')
    a = sym.address
    order, skip, wsk = sort_skip(want, p3.u(a('FR_SKIP'), 2),
                                 p3.u(WPAGE_W_WSK, 2))
    ref_order = [p3s.u(a('FR_ORDER') + 2 * i, 2) // SIZEOF_VIS
                 for i in range(len(want))]
    if order != ref_order:
        out.append('order %s, reference %s' % (order, ref_order))
    if (skip, wsk) != (p3s.u(a('FR_SKIP'), 2), p3s.u(WPAGE_W_WSK, 2)):
        out.append('FR_SKIP, W_WSK %s, reference %s' % (
            (skip, wsk), (p3s.u(a('FR_SKIP'), 2), p3s.u(WPAGE_W_WSK, 2))))
    return out


_LM: Dict[str, Any] = {}
_TABLES: Dict[str, Any] = {}


def _scale_tables():
    """A level source whose frame made SPRISCALE and FQ (PR_IOK 1:
    R_InitSpriteIScales runs at the first frame after a level load)."""
    if 'm' not in _TABLES:
        from bridge import linkmap as blink
        from native import levelconv as LC
        sym = blink.Symbols()
        for path in sorted(LC.SOURCES.glob('*.ram.z')):
            m = LC.load_memory(path)
            if m.u16(sym.address('PR_IOK')):
                _TABLES['m'] = m
                break
        else:
            raise ValueError('no level source made the sprite tables')
    return _TABLES['m']


def _level_memory(src: str):
    from native import levelconv as LC
    if src not in _LM:
        _LM.clear()
        _LM[src] = LC.load_memory(LC.SOURCES / (src + '.ram.z'))
    return _LM[src]


def listed_sectors(frame) -> Optional[List[Tuple[int, int]]]:
    """The frame's R_AddSprites calls (sector, light), or its base
    frame's for a synthetic frame (framesynth.py's pokes move things, not
    the walk)."""
    if 'addsprites' in frame.calls:
        return frame.calls['addsprites']
    base = frame.meta.get('base')
    if base:
        from native import framestate as FS, rendercap as RC
        return FS.Frame(RC.FRAMES / base).calls.get('addsprites')
    return None


def coverage(dirs, sym) -> Dict[str, Dict[str, int]]:
    """The projection's paths (and rejections) by set: frames that take
    each, the count of things (RENDER-MASKED.md 4.1's coverage)."""
    from native import framestate as FS
    out: Dict[str, Dict[str, int]] = {}
    for d in dirs:
        frame = FS.Frame(d)
        sectors = listed_sectors(frame)
        if sectors is None:
            continue
        lm = _level_memory(frame.meta['level_src'])
        vis, paths = project(frame.dump('p0'), frame.dump('p0b'), lm, sym,
                             sectors)
        key = d.name.rsplit('-', 1)[0]
        row = out.setdefault(key, {})
        for p in set(paths):
            row['frames:' + p] = row.get('frames:' + p, 0) + 1
        for p in paths:
            row[p] = row.get(p, 0) + 1
        scales = [v['scale'] for v in vis]
        if len(scales) != len(set(scales)):
            row['frames:ties'] = row.get('frames:ties', 0) + 1
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    from bridge import linkmap as blink
    from native import render_check as RCK
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames')
    parser.add_argument('--sets')
    parser.add_argument('--coverage', type=Path,
                        help='write the paths the frames take (JSON)')
    args = parser.parse_args(argv)
    sym = blink.Symbols()
    dirs = RCK.frame_dirs(args.frames, args.sets)
    dirs.sort(key=lambda d: json.loads((d / 'frame.json').read_text())
              ['level_src'])
    if args.coverage:
        cov = coverage(dirs, sym)
        args.coverage.write_text(json.dumps(cov, indent=1) + '\n')
        total: Dict[str, int] = {}
        for row in cov.values():
            for k, n in row.items():
                if k.startswith('frames:'):
                    total[k[7:]] = total.get(k[7:], 0) + n
        print('frames by path: %s' % json.dumps(dict(sorted(total.items()))))
    bad = 0
    for d in dirs:
        problems = check_frame(d, sym)
        if problems:
            bad += 1
            print('%s: %s' % (d.name, '; '.join(problems[:3])))
    print('%d frames, %d differ' % (len(dirs), bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
