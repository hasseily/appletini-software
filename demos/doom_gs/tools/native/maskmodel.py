#!/usr/bin/env python3
"""A host model of upstream's masked phase (milestone 8, stage B;
docs/RENDER-MASKED.md 0.3, 2.4, 3.4): drawMasked's two loops from the
state after sortSkip (P3s) to playerSkip (P3w), written from the sources
with the same integer steps: R_DrawSprite with dsVisible
(r_sprite65.s:481-561, :1460-1716), R_PointOnSegSide (r_data65.s:768),
R_DrawVisSprite with visCol, visPost, visFill (r_seg65.s:2698-3145),
wclipSprite and the magnified loop visColD, vrCol, vrPost (r_frame65.s:
966-990, :1696-2038), the shadows' visColF (r_sprite65.s:568-719),
R_RenderMaskedSegRange with maskedRange, lineFlags, higher, lower,
smul48 and mwCols (r_frame65.s:357-637, :1060-1648), the records'
allocation with its extra pages and flush (r_list65.s:256-323), FSCUT
and CVSET (lists.inc).

Usage:  python3 tools/native/maskmodel.py [--sets ...] [--frames ...]
                 [--coverage FILE]

It is not the port: the native code is src/native/msprite.s, mvis.s,
mwall.s. The model exists to check what stage B reads of upstream before
the native code is compared with it, and to name the paths each frame
takes (the coverage of RENDER-MASKED.md 4.1). On each captured frame its
records must equal the lists at P3w past those at P3, and its covered
ranges, spans, page offsets (COLW), XPNEXT, FZ_POS, floorclip,
ceilingclip, rw_scalestep and masked-column marks P3w's; the clips it
gives each R_DrawVisSprite call must equal the call log's.

The state it starts from is the level source (all RAM: the WAD's patches,
the textures, the tables), then P3 (the lists, the drawsegs, openings,
clips, spans, the level's dynamic fields), then P3s (the sort).
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
SIZEOF_VIS, SIZEOF_DS, SIZEOF_SEG, SIZEOF_SEC, SIZEOF_SIDE = 42, 42, 18, \
    58, 14
SIZEOF_LINE = 36
OFS_LINE_FLAGS = 26
DS = {'curline': 0, 'x1': 4, 'x2': 6, 'scale1': 8, 'scale2': 12,
      'scalestep': 16, 'sil': 20, 'bsil': 22, 'tsil': 26, 'topclip': 30,
      'botclip': 34, 'masked': 38}
VIS = {'x1': 0, 'x2': 2, 'gx': 4, 'gy': 8, 'gz': 12, 'startfrac': 16,
       'scale': 20, 'xiscale': 24, 'texturemid': 28, 'fracstep': 32,
       'lump': 34, 'topoffset': 36, 'colormap': 38}
OFS_MO_X, OFS_MO_Y = 12, 16
OFS_SEG = {'v1': 0, 'v2': 4, 'angle': 10, 'side': 12, 'line': 14,
           'front': 16, 'back': 17}
OFS_SIDE_ROWOFFSET, OFS_SIDE_MIDTEXTURE = 6, 12
OFS_SEC_FLOOR, OFS_SEC_CEIL, OFS_SEC_LIGHT = 0, 4, 48
OFS_TEX_WIDTHMASK, OFS_TEX_PATCHNUM = 0, 8 + 4
ML_DONTPEGBOTTOM = 16
DS_COUNT, DSX1, DSX2 = 0x0AB600, 0x0AB500, 0x0AB580
MM_FS = 0x23EF00
FS_ROW, CV_ROW, CV_REC = MM_FS, MM_FS + 0x800, MM_FS + 0xA00
MM_WCLIP = 0x0AC500
WCLIP, WTMP = MM_WCLIP, MM_WCLIP + 0x1C0
WPAGE = 0x000A00
W_WSK = WPAGE + 0xB0
RECBANK = 0x1D0000
MM_FSTEP = 0x1B0000
MM_B3F = 0x210000
CORE_LN36, CORE_SEC58 = MM_B3F + 0x6200, MM_B3F + 0xA000
MM_WAD = 0x100000
CENTERY = 84
VIEWWIDTH, VIEWHEIGHT = 160, 168
PAGE_ROOM = 254
XP_FIRST = 0xCE
K_TEX, K_FILL, K_TEXC, K_FUZZ, K_OVL, K_NEXT = 0, 2, 6, 8, 10, 12
UP_SIZES = {K_TEX: 11, K_FILL: 5, K_TEXC: 7, K_FUZZ: 4, K_OVL: 4,
            K_NEXT: 2}
CMAPA_PAGE = 0x46


class ModelError(Exception):
    pass


def s16(v: int) -> int:
    v &= M16
    return v - 0x10000 if v & 0x8000 else v


def s32(v: int) -> int:
    v &= M32
    return v - 0x100000000 if v & 0x80000000 else v


def colpage(c: int) -> int:
    """COLPAGE of lists.inc."""
    if c < 9:
        return c
    c += 0x17
    if c >= 0x89:
        c += 0x17
    return c


class Mem:
    """Upstream's RAM as the masked phase sees it: a level source (all
    RAM) with dumps laid over it, writable (the model's own changes)."""

    def __init__(self, base, dumps=()):
        self.base = base
        self.banks: Dict[int, bytearray] = {}
        for d in dumps:
            at = 0
            for start, size in d.d.ranges():
                self.write(start, d.d.data[at:at + size])
                at += size

    def _bank(self, b: int) -> bytearray:
        if b not in self.banks:
            src = self.base.banks.get(b)
            self.banks[b] = bytearray(src) if src is not None else \
                bytearray(0x10000)
        return self.banks[b]

    def read(self, address: int, n: int) -> bytes:
        out = bytearray()
        while n > 0:
            b, o = address >> 16, address & M16
            k = min(n, 0x10000 - o)
            if b in self.banks:
                out += self.banks[b][o:o + k]
            else:
                out += self.base.read(address, k)
            address += k
            n -= k
        return bytes(out)

    def u(self, address: int, n: int) -> int:
        return int.from_bytes(self.read(address, n), 'little')

    def write(self, address: int, data: bytes) -> None:
        at = 0
        while at < len(data):
            b, o = (address + at) >> 16, (address + at) & M16
            k = min(len(data) - at, 0x10000 - o)
            self._bank(b)[o:o + k] = data[at:at + k]
            at += k

    def put(self, address: int, value: int, n: int) -> None:
        self.write(address, (value & ((1 << (8 * n)) - 1)).to_bytes(n,
                                                                    'little'))


class Model:
    """drawMasked's loops on one frame's state (module docstring)."""

    def __init__(self, mem: Mem, sym, recip: Sequence[int]):
        self.m = mem
        self.sym = sym
        self.recip = recip
        a = sym.address
        self.a = a
        m = mem
        self.floorclip = [m.u(a('floorclip') + 2 * c, 1) for c in range(160)]
        self.ceilclip = [m.u(a('ceilingclip') + 2 * c, 1)
                         for c in range(160)]
        self.fstop = [m.u(FS_ROW + 2 * c, 1) for c in range(160)]
        self.fsbot = [m.u(FS_ROW + 2 * c + 1, 1) for c in range(160)]
        self.cvfirst = [m.u(CV_ROW + 2 * c, 1) for c in range(160)]
        self.cvend = [m.u(CV_ROW + 2 * c + 1, 1) for c in range(160)]
        self.cvrec: Dict[int, Tuple[int, int]] = {}   # column -> (flushes,
        #   the record's index in its column's appended records)
        colw = m.read(a('COLW'), 320)
        self.upofs = [colw[2 * c] for c in range(160)]
        self.xpnext = m.u(a('XPNEXT'), 1)
        self.flushes = 0
        self.records: Dict[int, List[Tuple]] = {}     # appended, by column
        self.fzpos = m.u(a('FZ_POS'), 2)
        self.w_wsk = m.u(W_WSK, 2)
        self.rw_step = m.u(a('rw_scalestep'), 4)
        self.viewtop = s16(m.u(a('viewtop'), 2))
        self.viewbottom = s16(m.u(a('viewbottom'), 2))
        self.spr_top = (self.viewtop + 1) & 0xFF
        self.spr_bot = (self.viewbottom + 1) & 0xFF
        self.sha = (self.viewbottom + 1) & M16      # screenheightarray
        self.lt_fixed = m.u(a('LT_FIXED'), 2)
        self.lt_base = m.u(a('LT_BASE'), 2)
        self.viewz = m.u(a('viewz'), 4)
        self.full = a('fullcolormap')
        self.drawvis: List[Dict[str, Any]] = []       # R_DrawVisSprite calls
        self.paths: List[str] = []
        self.wtmp = [m.u(WTMP + 2 * c, 1) for c in range(160)]
        self.wclip = [m.u(WCLIP + 2 * c, 1) for c in range(160)]
        self.dscount = m.u(DS_COUNT, 2)

    # -- the records ------------------------------------------------------
    def alloc(self, c: int, kind: int) -> None:
        """recAlloc/newPage's page model for a record of `kind` at the end
        of column c's list: an extra page, or a flush of all lists."""
        size = UP_SIZES[kind]
        if self.upofs[c] + size > PAGE_ROOM:
            if self.xpnext:
                self.xpnext = (self.xpnext + 1) & 0xFF
                self.upofs[c] = 0
                self.paths.append('extra page')
            else:
                self.flush()
        self.upofs[c] += size

    def flush(self) -> None:
        self.paths.append('flush')
        self.flushes += 1
        self.upofs = [0] * 160
        self.xpnext = XP_FIRST
        self.cvfirst = [0] * 160
        self.cvend = [0] * 160
        self.cvrec = {}

    def append(self, c: int, rec: Tuple) -> int:
        lst = self.records.setdefault(c, [])
        lst.append(rec)
        return len(lst) - 1

    def fscut(self, c: int, first: int, end: int) -> None:
        if end > self.fsbot[c]:
            self.fsbot[c] = end
        if first < self.fstop[c]:
            self.fstop[c] = first

    def cvset(self, c: int, first: int, end: int, index: int) -> None:
        size = (self.cvend[c] - self.cvfirst[c]) & 0xFF
        t = size + first
        if t > 0xFF or t >= end:
            return
        self.cvfirst[c], self.cvend[c] = first, end
        self.cvrec[c] = (self.flushes, index)

    # -- drawMasked -----------------------------------------------------
    def run(self, order: Sequence[int], nvis: int) -> None:
        a = self.a
        self.vis = [self.read_vis(i) for i in range(nvis)]
        for i in reversed(order):
            self.draw_sprite(self.vis[i])
        for k in range(self.dscount - 1, -1, -1):
            ds = self.ds_addr(k)
            if self.m.u(ds + DS['masked'], 4) & 0xFFFFFF:
                self.paths.append('masked drawseg')
                x1 = self.m.u(ds + DS['x1'], 2)
                x2 = self.m.u(ds + DS['x2'], 2)
                self.masked_range(ds, s16(x1), s16(x2))
        del a

    def read_vis(self, i: int) -> Dict[str, int]:
        at = self.a('vissprites') + SIZEOF_VIS * i
        out = {'index': i}
        for k, o in VIS.items():
            n = 2 if k in ('x1', 'x2', 'fracstep', 'lump', 'topoffset') \
                else 4
            out[k] = self.m.u(at + o, n)
        return out

    def ds_addr(self, k: int) -> int:
        return self.a('_s_drawsegs') + SIZEOF_DS * k

    def ds(self, addr: int, key: str) -> int:
        n = 2 if key in ('x1', 'x2', 'sil') else 4
        return self.m.u(addr + DS[key], n)

    def clip_value(self, ptr: int, x: int) -> int:
        """Column x of a clip array (sprtopclip, sprbottomclip): its low
        byte (the arrays hold words with a high byte of 0)."""
        return self.m.u((ptr & 0xFFFFFF) + 2 * x, 1)

    # R_DrawSprite
    def draw_sprite(self, v: Dict[str, int]) -> None:
        m = self.m
        gzt_hi = ((v['gz'] >> 16) + v['topoffset']) & M16
        x1, x2 = v['x1'] & 0xFF, v['x2'] & 0xFF
        for x in range(x1, x2 + 1):
            self.floorclip[x] = self.spr_bot
            self.ceilclip[x] = self.spr_top
        x2p1 = (x2 + 1) & 0xFF
        for k in range(self.dscount - 1, -1, -1):
            dx1 = m.u(DSX1 + k, 1)
            dx2 = m.u(DSX2 + k, 1)
            if dx1 >= x2p1 or dx2 < x1:
                continue
            r1 = dx1 if dx1 >= x1 else x1
            r2 = dx2 if dx2 < x2 else x2
            ds = self.ds_addr(k)
            sc = s32(v['scale'])
            lt1 = s32(self.ds(ds, 'scale1')) < sc
            lt2 = s32(self.ds(ds, 'scale2')) < sc
            if lt1 and lt2:
                self.paths.append('ds behind (scales)')
                behind = True
            elif not lt1 and not lt2:
                behind = False
                self.paths.append('ds clips (scales)')
            else:
                side = self.point_on_seg_side(v, ds)
                behind = not side
                self.paths.append('side test %s' % ('back' if side
                                                    else 'front'))
            if behind:
                if self.ds(ds, 'masked') & 0xFFFFFF:
                    self.paths.append('masked range from a sprite')
                    self.masked_range(ds, r1, r2)
                continue
            sil = self.ds(ds, 'sil') & 0xFF
            if sil & 1 and s32(v['gz']) < s32(self.ds(ds, 'bsil')):
                self.paths.append('bottom silhouette')
                ptr = self.ds(ds, 'botclip')
                for x in range(r1, r2 + 1):
                    if self.floorclip[x] == self.spr_bot:
                        self.floorclip[x] = self.clip_value(ptr, x)
            if sil & 2:
                gzt = (gzt_hi << 16) | (v['gz'] & M16)
                if s32(self.ds(ds, 'tsil')) < s32(gzt):
                    self.paths.append('top silhouette')
                    ptr = self.ds(ds, 'topclip')
                    for x in range(r1, r2 + 1):
                        if self.ceilclip[x] == self.spr_top:
                            self.ceilclip[x] = self.clip_value(ptr, x)
        if not self.ds_visible(v):
            self.paths.append('not visible')
            return
        self.draw_vis(v, self.floorclip, self.ceilclip)

    def point_on_seg_side(self, v: Dict[str, int], ds: int) -> bool:
        """R_PointOnSegSide(thing->x, thing->y, ds->curline): True for
        the back."""
        m = self.m
        th = v['gx'] & 0xFFFFFF
        x = m.u(th + OFS_MO_X, 4)
        y = m.u(th + OFS_MO_Y, 4)
        seg = self.ds(ds, 'curline') & 0xFFFFFF
        lx, ly = m.u(seg + 0, 2), m.u(seg + 2, 2)
        ldx = (m.u(seg + 4, 2) - lx) & M16
        ldy = (m.u(seg + 6, 2) - ly) & M16
        if not ldx:
            # x <= lx << 16 ? ldy > 0 : ldy < 0 (a signed compare: the
            # sign of (lx << 16) - x corrected by the overflow)
            if s16(lx) * 0x10000 - s32(x) >= 0:
                return s16(ldy) > 0
            return s16(ldy) < 0
        if not ldy:
            if s16(ly) * 0x10000 - s32(y) >= 0:
                return s16(ldx) < 0
            return s16(ldx) > 0
        xh = ((x >> 16) - lx) & M16
        yh = ((y >> 16) - ly) & M16
        x = (xh << 16) | (x & M16)
        y = (yh << 16) | (y & M16)
        if (yh ^ xh ^ ldx ^ ldy) & 0x8000:
            return bool((ldy ^ xh) & 0x8000)
        left = MD.m_fixmul3216(y, ldx)
        right = MD.m_fixmul3216(x, ldy)
        return s32(left) >= s32(right)

    def ds_visible(self, v: Dict[str, int]) -> bool:
        """dsVisible: an open column in x1 .. x2 + 1 (and x2 + 2 at
        most), or a texture column past them that the draw can reach."""
        x1, x2 = v['x1'] & 0xFF, v['x2'] & 0xFF
        r2 = min(x2 + 2, VIEWWIDTH)
        for x in range(x1, r2):
            if self.open_col(x):
                return True
        x = r2
        if x >= VIEWWIDTH:
            return False
        width = self.m.u(v['gy'] & 0xFFFFFF, 2)
        xh = v['xiscale'] >> 16
        if width < 512 and xh not in (0, M16):
            self.paths.append('dsVisible: the column after x2 + 1')
            return self.open_col(x)
        self.paths.append('dsVisible: exact')
        prod = MD.m_fixmul(v['xiscale'], ((x - x1) & M16) << 16)
        hi = ((prod + v['startfrac']) & M32) >> 16
        if hi & 0x8000:
            return False
        return hi < width

    def open_col(self, x: int) -> bool:
        fc = self.floorclip[x]
        if fc == 0:
            return False
        return fc - 1 > self.ceilclip[x]

    # R_DrawVisSprite
    def draw_vis(self, v: Dict[str, int], fcp: List[int],
                 ccp: List[int]) -> None:
        self.drawvis.append({'vis': v['index'], 'floorclip': list(fcp),
                             'ceilclip': list(ccp)})
        cm = v['colormap'] & 0xFFFFFF
        cmp_ = 0 if cm == 0 else CMAPA_PAGE + (cm - self.full) // 256
        ss = v['scale']
        tm = v['texturemid']
        stop = ((CENTERY << 16) - MD.m_fixmul(tm, ss)) & M32
        e = (stop - ss - 1) & M32          # E - 1 of row -1
        st = {'cmp': cmp_, 'frac': v['startfrac'], 'xis': v['xiscale'],
              'x': v['x1'] & M16, 'x2': v['x2'] & 0xFF, 'ss': ss, 'e': e,
              'yht': [], 'tn': 0,
              'unit': ss == 0x10000,
              'yh0': ((stop - 1) & M32) >> 16,
              'patch': v['gy'] & 0xFFFFFF,
              'tm7': (tm >> 7) & M16, 'fstep': v['fracstep'] & M16}
        st['width'] = self.m.u(st['patch'], 2)
        f = st['fstep']
        st['s2'] = f >> 1
        st['k'] = (st['tm7'] - (CENTERY + 1) * f) & M16
        st['yhtm'] = (e >> 16) & M16       # YHTABM
        st['fcp'] = fcp
        st['ccp'] = ccp
        if cmp_ == 0:
            self.paths.append('shadow')
            self.fuzz_cols(st)
            return
        if self.w_wsk:
            self.paths.append('wclipSprite')
            end = min((v['x2'] & 0xFF) + 2, VIEWWIDTH)
            wtmp = list(self.wtmp)
            for x in range(st['x'], end):
                wtmp[x] = min(self.wclip[x], fcp[x])
            self.wtmp = wtmp
            st['fcp'] = wtmp
        xis = st['xis']
        mag = (xis >> 16 == 0 and (xis & M16) < 0xC000) or \
            (xis >> 16 == M16 and (xis & M16) >= 0x4001)
        if mag and not st['unit']:
            self.paths.append('magnified')
            self.vr_cols(st)
        else:
            if st['unit']:
                self.paths.append('unit scale')
            self.vis_cols(st)

    def yhtab(self, st: Dict, t: int) -> int:
        """YHTAB[t]: (E - 1) >> 16 of texel row t, filled lazily."""
        while st['tn'] <= t:
            st['e'] = (st['e'] + st['ss']) & M32
            st['yht'].append(st['e'] >> 16)
            st['tn'] += 1
        return st['yht'][t]

    def column(self, st: Dict) -> int:
        idx = (4 * (st['frac'] >> 16) + 8) & M16
        ofs = self.m.u(st['patch'] + idx, 2)
        return (st['patch'] & 0xFF0000) | (((st['patch'] & M16) + ofs) &
                                           M16)

    def posts(self, col: int):
        """The posts of a column: (address, topdelta, length)."""
        m = self.m
        guard = 0
        while True:
            td = m.u(col, 1)
            if td == 0xFF:
                return
            n = m.u(col + 1, 1)
            yield col, td, n
            col = (col & 0xFF0000) | ((col + n + 4) & M16)
            guard += 1
            if guard > 256:
                raise ModelError('a column of more than 256 posts')

    def next_col(self, st: Dict) -> bool:
        st['frac'] = (st['frac'] + st['xis']) & M32
        hi = st['frac'] >> 16
        if hi & 0x8000 or hi >= st['width']:
            return False
        st['x'] += 1
        return True

    def post_rows(self, st: Dict, td: int, n: int, lo: int, hi: int
                  ) -> Optional[Tuple[int, int]]:
        """visPost's rows of a post in rows lo .. hi - 1: (yl, yh + 1)."""
        t = td + n
        yh = (st['yh0'] + t) & M16 if st['unit'] else self.yhtab(st, t)
        if yh & 0x8000 or yh < lo:
            return None
        if yh >= hi:
            yh = hi - 1
        yh1 = yh + 1
        y = (st['yh0'] + td) & M16 if st['unit'] else self.yhtab(st, td)
        if y & 0x8000:
            yl = lo
        else:
            yl = (y + 1) & M16
            if yl >= hi:
                return None
            if yl < lo:
                yl = lo
        if yh1 - yl <= 0:
            return None
        return yl, yh1

    def vis_cols(self, st: Dict) -> None:
        while st['x'] < VIEWWIDTH:
            x = st['x']
            fc = st['fcp'][x]
            if fc:
                hi = fc - 1
                lo = st['ccp'][x]
                if lo < hi:
                    for col, td, n in self.posts(self.column(st)):
                        rows = self.post_rows(st, td, n, lo, hi)
                        if rows is None:
                            continue
                        if x > st['x2']:
                            self.paths.append('a column past x2')
                        self.tex_record(st, x, rows, col, td, False)
            if not self.next_col(st):
                return

    def tex_record(self, st: Dict, x: int, rows: Tuple[int, int],
                   col: int, td: int, mag: bool) -> int:
        yl, yh1 = rows
        self.fscut(x, yl, yh1)
        self.alloc(x, K_TEX)
        f = st['fstep']
        if mag:
            frac = (st['k'] - 512 * td + yl * (f & 0xFF)) & M16
        else:
            frac = (st['tm7'] + (yl - CENTERY - 1) * f - 512 * td) & M16
        frac >>= 1
        src = (col & 0xFF0000) | ((col + 3) & M16)
        rec = ('tex', yl, yh1, frac & 0xFF, frac >> 8, st['s2'] & 0xFF,
               st['s2'] >> 8, src, st['cmp'])
        i = self.append(x, rec)
        self.cvset(x, yl, yh1, i)
        return i

    def vr_cols(self, st: Dict) -> None:
        while st['x'] < VIEWWIDTH:
            x = st['x']
            fc = st['fcp'][x]
            if fc and st['ccp'][x] < fc - 1:
                hi, lo = fc - 1, st['ccp'][x]
                col = self.column(st)
                # the run: the next columns with the same texture column and
                # the same clips
                y = x
                frac = st['frac'] & M16
                while True:
                    y += 1
                    if y >= VIEWWIDTH:
                        break
                    t = frac + (st['xis'] & M16)
                    carry = t >> 16
                    frac = t & M16
                    if ((st['xis'] >> 16) + carry) & M16:
                        frac = (frac - (st['xis'] & M16)) & M16
                        break
                    if st['fcp'][y] - 1 != hi or st['ccp'][y] != lo:
                        frac = (frac - (st['xis'] & M16)) & M16
                        break
                rep = y - x - 1
                if rep:
                    self.paths.append('magnified run')
                for pcol, td, n in self.posts(col):
                    rows = self.post_rows(st, td, n, lo, hi)
                    if rows is None:
                        continue
                    for k in range(rep + 1):
                        self.tex_record(st, x + k, rows, pcol, td, True)
                if rep:
                    st['frac'] = (st['frac'] & 0xFFFF0000) | frac
                    st['x'] += rep
            if not self.next_col(st):
                return

    def fuzz_cols(self, st: Dict) -> None:
        fz = self.fzpos
        while st['x'] < VIEWWIDTH:
            x = st['x']
            fc = st['fcp'][x]
            if fc:
                hi = min(fc - 1, VIEWHEIGHT - 1)
                lo = st['ccp'][x] or 1
                if lo < hi:
                    for col, td, n in self.posts(self.column(st)):
                        t = td + n
                        yh = self.yhtab(st, t)
                        if yh & 0x8000 or yh < lo:
                            continue
                        if yh >= hi:
                            yh = hi - 1
                        yh1 = yh + 1
                        y = self.yhtab(st, td)
                        if y & 0x8000:
                            yl = lo
                        else:
                            yl = (y + 1) & M16
                            if yl >= hi:
                                continue
                            if yl < lo:
                                yl = lo
                        count = yh1 - yl
                        if count <= 0:
                            continue
                        self.alloc(x, K_FUZZ)
                        self.fscut(x, yl, yh1)
                        self.cvfirst[x], self.cvend[x] = 255, 254
                        self.cvrec.pop(x, None)
                        self.append(x, ('fuzz', yl, count, fz))
                        fz = (fz + count) % 50
            st['frac'] = (st['frac'] + st['xis']) & M32
            hi16 = st['frac'] >> 16
            if hi16 & 0x8000 or hi16 >= st['width']:
                break
            st['x'] += 1
        self.fzpos = fz

    # R_RenderMaskedSegRange
    def masked_range(self, ds: int, x1: int, x2: int) -> None:
        m, a = self.m, self.a
        step = self.ds(ds, 'scalestep')
        self.rw_step = step
        d = s16(x1 - self.ds(ds, 'x1'))
        scale = self.ds(ds, 'scale1')
        if d:
            scale = (scale + MD.m_mul32(step, d & M32)) & M32
        seg = self.ds(ds, 'curline') & 0xFFFFFF
        front = m.u(seg + OFS_SEG['front'], 1)
        back = m.u(seg + OFS_SEG['back'], 1)
        secs = m.u(a('_g_sectors'), 3)
        fs, bs = secs + SIZEOF_SEC * front, secs + SIZEOF_SEC * back
        for n, addr in ((front, fs), (back, bs)):
            if m.u(CORE_SEC58 + 2 * n, 2) != addr & M16:
                raise ModelError('CORE_SEC58 %d is not _g_sectors + 58 n'
                                 % n)
        side = m.u(a('_g_sides'), 3) + SIZEOF_SIDE * m.u(seg + 12, 2)
        rowofs = m.u(side + OFS_SIDE_ROWOFFSET, 2)
        mid = m.u(side + OFS_SIDE_MIDTEXTURE, 2)
        tex = m.u(m.u(a('texturetranslation'), 3) + 2 * mid, 2)
        light = m.u(fs + OFS_SEC_LIGHT, 2)
        line = m.u(a('_g_lines'), 3) + SIZEOF_LINE * m.u(seg + 14, 2)
        if m.u(CORE_LN36 + 2 * m.u(seg + 14, 2), 2) != line & M16:
            raise ModelError('CORE_LN36 is not _g_lines + 36 n')
        flags = m.u(line + OFS_LINE_FLAGS, 2) & 0xFF
        if flags & ML_DONTPEGBOTTOM:
            f1, f2 = m.u(fs + OFS_SEC_FLOOR, 4), m.u(bs + OFS_SEC_FLOOR, 4)
            tmid = f1 if s32(f2) < s32(f1) else f2     # the higher
            th = m.u(m.u(a('textureheight'), 3) + 2 * tex, 2)
            tmid = (tmid + (th << 16)) & M32
            self.paths.append('masked: peg bottom')
        else:
            c1, c2 = m.u(fs + OFS_SEC_CEIL, 4), m.u(bs + OFS_SEC_CEIL, 4)
            tmid = c1 if s32(c1) < s32(c2) else c2     # the lower
            self.paths.append('masked: lower ceiling')
        tmid = (tmid - self.viewz + ((rowofs & M16) << 16)) & M32
        # R_WallLight
        angle = (m.u(seg + OFS_SEG['angle'], 2) + 0x4000) & M16
        lt_i = ((light >> 4) + self.lt_base) & M16
        if angle & 0x7FFF == 0:
            lt_i += 1
        elif angle & 0x7FFF == 0x4000:
            lt_i -= 1
        self.lt_i = lt_i & M16
        fixed = self.lt_fixed if not self.lt_fixed & 0x8000 else 0
        cmp_ = CMAPA_PAGE + (fixed >> 8)
        texp = m.u(m.u(a('textures'), 3) + 4 * tex, 4) & 0xFFFFFF
        wmask = m.u(texp + OFS_TEX_WIDTHMASK, 2)
        lump = m.u(texp + OFS_TEX_PATCHNUM, 2)
        fi = m.u(a('fileinfo'), 3) + 16 * lump
        patch = (((m.u(fi + 2, 2) + (MM_WAD >> 16)) & M16) << 16 |
                 m.u(fi, 2)) & 0xFFFFFF
        p = self.smul48(tmid, scale)
        b = self.smul48(tmid, step)
        # the light of the columns
        lvf = 0
        if self.lt_fixed & 0x8000:
            d1 = self.mdlight(self.ds(ds, 'scale1'))
            d2 = self.mdlight(self.ds(ds, 'scale2'))
            smap = m.u(a('SMAP') + 2 * self.lt_i, 2)
            if d1 == d2:
                cmp_ = m.u(a('PGT') + ((smap - d2) & M16), 1)
            else:
                lvf = smap & 0xFF
                self.paths.append('masked: two lights')
        tm7 = (tmid >> 7) & M16
        mtc = self.ds(ds, 'masked') & 0xFFFFFF
        fcp = self.ds(ds, 'botclip') & 0xFFFFFF
        ccp = self.ds(ds, 'topclip') & 0xFFFFFF
        x = x1
        while s16(x - x2) <= 0:
            xc = m.u(mtc + 2 * x, 2)
            if xc != 0x7FFF:
                m.put(mtc + 2 * x, 0x7FFF, 2)
                self.mw_col(x, xc & wmask, patch, ccp, fcp, scale, p, lvf,
                            cmp_, tm7)
            else:
                self.paths.append('masked: column drawn already')
            x += 1
            scale = (scale + step) & M32
            p = (p + b) & 0xFFFFFFFFFFFF

    @staticmethod
    def mdlight(scale: int) -> int:
        c = (scale >> 8) & M16
        if c >= 24 << 5:
            c = 23 << 5
        return c >> 5

    @staticmethod
    def smul48(a: int, b: int) -> int:
        return (s32(a) * s32(b)) & 0xFFFFFFFFFFFF

    def mw_col(self, x: int, xc: int, patch: int, ccp: int, fcp: int,
               scale: int, p: int, lvf: int, cmp_: int, tm7: int) -> None:
        m = self.m
        cc1 = m.u(ccp + 2 * x, 2)
        fcl = (m.u(fcp + 2 * x, 2) - 1) & M16
        if fcl & 0x8000 or fcl <= cc1:
            return
        ofs = m.u(patch + ((8 + 4 * xc) & M16), 2)
        col = (patch & 0xFF0000) | (((patch & M16) + ofs) & M16)
        stop = ((CENTERY << 16) - (p >> 16)) & M32
        cl = (stop + 0xFFFF) & M32
        if lvf:
            d = self.mdlight(scale)
            cmp_ = m.u(self.a('PGT') + ((lvf - d) & 0xFF), 1)
        if scale >> 16 == 0:
            step = m.u(MM_FSTEP + 2 * (scale & M16), 2)
        else:
            self.paths.append('masked: recip step')
            r = MD.m_recip(scale, self.recip)
            step = (r >> 7) & M16
        s2 = step >> 1
        k = (tm7 - (CENTERY + 1) * step) & M16
        cont = False

        def hrow(b: int) -> int:
            # H(b) from the bytes s0, s1, s2 of spryscale (mwCols: byte 3
            # is left out)
            return s16(((cl + (scale & 0xFFFFFF) * b) & M32) >> 16)
        for pcol, td, n in self.posts(col):
            yl = hrow(td)
            if yl < 0 or yl < cc1:
                yl = cc1
            if yl >= fcl:
                cont = False
                continue
            if td + n > 255:
                raise ModelError('a masked post ends after row 255')
            end = hrow(td + n)
            if end < 0:
                cont = False
                continue
            if end >= fcl:
                end = fcl
            if end <= yl:
                cont = False
                continue
            self.fscut(x, yl, end)
            frac = ((yl * step + k) & M16) >> 1
            tf, ti = frac & 0xFF, ((frac >> 8) - td) & 0x7F
            if cont and self.upofs[x] + UP_SIZES[K_TEXC] <= PAGE_ROOM:
                self.alloc(x, K_TEXC)
                src = (pcol + 3) & M16
                i = self.append(x, ('texc', yl, end, tf, ti, src))
                self.paths.append('K_TEXC')
            else:
                if cont:
                    self.paths.append('K_TEXC refused (the page\'s end)')
                self.alloc(x, K_TEX)
                src = (pcol + 3) & 0xFFFFFF
                i = self.append(x, ('tex', yl, end, tf, ti, s2 & 0xFF,
                                    s2 >> 8, src, cmp_))
            self.cvset(x, yl, end, i)
            cont = True


# ---------------------------------------------------------------------------
# The reference's side, and the comparison
# ---------------------------------------------------------------------------

def ref_lists(d, sym, base_len: Optional[Dict[int, int]] = None
              ) -> Tuple[Dict[int, List[Tuple]], Dict[int, Dict[int, int]]]:
    """Upstream's lists in a dump: each column's records from its first
    page through K_NEXT (dropped), canonical; and each record's address
    -> its index (for CV_REC). A K_TEXC's texels are (its chain's bank,
    R_TCSRC)."""
    colw = d.read(sym.address('COLW'), 320)
    out: Dict[int, List[Tuple]] = {}
    where: Dict[int, Dict[int, int]] = {}
    for c in range(160):
        end = colw[2 * c] | colw[2 * c + 1] << 8
        page, off = colpage(c), 0
        recs: List[Tuple] = []
        idx: Dict[int, int] = {}
        bank = None
        steps = 0
        while (page << 8 | off) != end:
            steps += 1
            if steps > 8192 or off >= 256:
                raise ModelError('column %d: the list does not reach its '
                                 'end' % c)
            at = RECBANK + (page << 8) + off
            kind = d.read(at, 1)[0]
            if kind == K_NEXT:
                page, off = d.read(at + 1, 1)[0], 0
                continue
            if kind not in UP_SIZES:
                raise ModelError('column %d: a record of kind %d' % (c, kind))
            r = d.read(at, UP_SIZES[kind])
            idx[(page << 8) | off] = len(recs)
            if kind == K_TEX:
                src = r[7] | r[8] << 8 | r[9] << 16
                bank = r[9]
                recs.append(('tex', r[1], r[2], r[3], r[4], r[5], r[6], src,
                             r[10]))
            elif kind == K_FILL:
                recs.append(('fill', r[1], r[2], r[3], r[4]))
            elif kind == K_TEXC:
                if bank is None:
                    raise ModelError('column %d: a K_TEXC first' % c)
                recs.append(('texc', r[1], r[2], r[3], r[4],
                             r[5] | r[6] << 8))
            elif kind == K_FUZZ:
                recs.append(('fuzz', r[1], r[2], r[3]))
            else:
                recs.append(('ovl', r[1], r[2], r[3]))
            off += UP_SIZES[kind]
        if recs:
            out[c] = recs
        where[c] = idx
    return out, where


def check(frame, sym, lm, recip) -> Tuple[List[str], Dict[str, Any]]:
    """The model on one frame against P3w (module docstring)."""
    a = sym.address
    p3, p3s, p3w = frame.dump('p3'), frame.dump('p3s'), frame.dump('p3w')
    problems: List[str] = []
    if frame.meta.get('flushes'):
        return (['the frame flushes before drawMasked (%d): not modelled '
                 'here' % frame.meta.get('flushes')], {})
    # the flushes of the masked phase before playerSkip (P2 dumps): their
    # lists, then P3w's, are the records after drawMasked
    cyc = p3w.header['cycles']
    flush_dumps = [frame.dump('p2m-%d' % k)
                   for k in range(frame.meta.get('mflushes', 0))]
    flush_dumps = [d for d in flush_dumps if d.header['cycles'] < cyc]
    mem = Mem(lm, (p3, p3s))
    nvis = p3.u(a('num_vissprite'), 2)
    order = [p3s.u(a('FR_ORDER') + 2 * i, 2) // SIZEOF_VIS
             for i in range(nvis)]
    model = Model(mem, sym, recip)
    model.run(order, nvis)
    before, _ = ref_lists(p3, sym)
    after, where = ref_lists(p3w, sym)
    if flush_dumps:
        joined: Dict[int, List[Tuple]] = {}
        for d in flush_dumps:
            for c, recs in ref_lists(d, sym)[0].items():
                joined.setdefault(c, []).extend(recs)
        for c, recs in after.items():
            joined.setdefault(c, []).extend(recs)
        after = joined
        if model.flushes != len(flush_dumps):
            problems.append('flushes: model %d, reference %d' % (
                model.flushes, len(flush_dumps)))
    for c in range(160):
        b, w = before.get(c, []), after.get(c, [])
        if w[:len(b)] != b:
            problems.append('column %d: the lists at P3 are not the start '
                            'of those at P3w' % c)
            break
        got = model.records.get(c, [])
        if w[len(b):] != got:
            k = next(i for i in range(max(len(got), len(w) - len(b)))
                     if i >= len(got) or i >= len(w) - len(b) or
                     got[i] != w[len(b) + i])
            problems.append('column %d record %d: model %s, reference %s' % (
                c, k, got[k] if k < len(got) else None,
                w[len(b) + k] if len(b) + k < len(w) else None))
            break
    colw = p3w.read(a('COLW'), 320)
    if [colw[2 * c] for c in range(160)] != model.upofs:
        bad = [c for c in range(160) if colw[2 * c] != model.upofs[c]]
        problems.append('COLW offsets: %d differ (column %d: model %d, '
                        'reference %d)' % (len(bad), bad[0],
                                           model.upofs[bad[0]],
                                           colw[2 * bad[0]]))
    if p3w.u(a('XPNEXT'), 1) != model.xpnext:
        problems.append('XPNEXT: model $%02X, reference $%02X'
                        % (model.xpnext, p3w.u(a('XPNEXT'), 1)))
    sp = p3w.read(MM_FS, 0xC00)
    if [sp[2 * c] for c in range(160)] != model.fstop or \
            [sp[2 * c + 1] for c in range(160)] != model.fsbot:
        problems.append('the spans\' rows differ')
    cvf = [sp[0x800 + 2 * c] for c in range(160)]
    cve = [sp[0x800 + 2 * c + 1] for c in range(160)]
    if cvf != model.cvfirst or cve != model.cvend:
        bad = [c for c in range(160) if (cvf[c], cve[c]) !=
               (model.cvfirst[c], model.cvend[c])]
        problems.append('covered ranges: %d differ (column %d: model %s, '
                        'reference %s)' % (len(bad), bad[0],
                                           (model.cvfirst[bad[0]],
                                            model.cvend[bad[0]]),
                                           (cvf[bad[0]], cve[bad[0]])))
    for c in range(160 if not flush_dumps else 0):
        if cvf[c] < cve[c]:
            rec = sp[0xA00 + 2 * c] | sp[0xA00 + 2 * c + 1] << 8
            idx = where[c].get(rec)
            got = model.cvrec.get(c)
            want = None if idx is None else idx - len(before.get(c, []))
            if got is None or got[1] != want:
                problems.append('column %d: the covering record: model %s, '
                                'reference %s' % (c, got, want))
                break
    if p3w.u(a('FZ_POS'), 2) != model.fzpos:
        problems.append('FZ_POS: model %d, reference %d' % (
            model.fzpos, p3w.u(a('FZ_POS'), 2)))
    if p3w.u(a('rw_scalestep'), 4) != model.rw_step:
        problems.append('rw_scalestep differs')
    fc = [p3w.u(a('floorclip') + 2 * c, 1) for c in range(160)]
    cc = [p3w.u(a('ceilingclip') + 2 * c, 1) for c in range(160)]
    if fc != model.floorclip or cc != model.ceilclip:
        problems.append('floorclip or ceilingclip at P3w differ')
    # the masked columns' marks: the openings as the model left them
    op = a('openings')
    if p3w.read(op, 2 * 2560) != mem.read(op, 2 * 2560):
        problems.append('the openings (masked-column marks) differ')
    # the clips of each R_DrawVisSprite call against the call log
    calls = [c for c in frame.calls.get('drawvis', [])
             if int.from_bytes(bytes.fromhex(c['in']['mem'][1]),
                               'little') == 0]
    vbase = a('vissprites')
    sprite_calls = []
    for c in calls:
        ptr = int.from_bytes(bytes.fromhex(c['in']['mem'][0]), 'little')
        ptr &= 0xFFFFFF
        if vbase <= ptr < vbase + SIZEOF_VIS * 80:
            sprite_calls.append(c)
    if 'drawvis' in frame.calls:
        if len(sprite_calls) != len(model.drawvis):
            problems.append('R_DrawVisSprite calls: model %d, reference %d'
                            % (len(model.drawvis), len(sprite_calls)))
        for k, (c, g) in enumerate(zip(sprite_calls, model.drawvis)):
            ptr = int.from_bytes(bytes.fromhex(c['in']['mem'][0]),
                                 'little') & 0xFFFFFF
            fl = bytes.fromhex(c['in']['mem'][4])
            ce = bytes.fromhex(c['in']['mem'][5])
            want = {'vis': (ptr - vbase) // SIZEOF_VIS,
                    'floorclip': [fl[2 * x] for x in range(160)],
                    'ceilclip': [ce[2 * x] for x in range(160)]}
            if want != g:
                keys = [k2 for k2 in want if want[k2] != g[k2]]
                problems.append('R_DrawVisSprite call %d: %s differ' % (
                    k, keys))
                break
    return problems, {'paths': model.paths,
                      'records': sum(len(v) for v in model.records.values()),
                      'calls': len(model.drawvis)}


_LM: Dict[str, Any] = {}


def level_memory(src: str):
    from native import levelconv as LC
    if src not in _LM:
        _LM.clear()
        _LM[src] = LC.load_memory(LC.SOURCES / (src + '.ram.z'))
    return _LM[src]


def recip_table() -> List[int]:
    return [MD.recip_entry(i) for i in range(32768)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    from bridge import linkmap as blink
    from native import framestate as FS, render_check as RCK
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames')
    parser.add_argument('--sets')
    parser.add_argument('--coverage', type=Path)
    args = parser.parse_args(argv)
    sym = blink.Symbols()
    dirs = RCK.frame_dirs(args.frames, args.sets)
    dirs.sort(key=lambda d: json.loads((d / 'frame.json').read_text())
              ['level_src'])
    recip = recip_table()
    bad = 0
    cov: Dict[str, Dict[str, int]] = {}
    for d in dirs:
        frame = FS.Frame(d)
        lm = level_memory(frame.meta['level_src'])
        try:
            problems, info = check(frame, sym, lm, recip)
        except ModelError as e:
            problems, info = ['model: %s' % e], {}
        if problems:
            bad += 1
            print('%s: %s' % (d.name, '; '.join(problems[:3])), flush=True)
        key = d.name.rsplit('-', 1)[0]
        row = cov.setdefault(key, {})
        for p in set(info.get('paths', [])):
            row['frames:' + p] = row.get('frames:' + p, 0) + 1
        for p in info.get('paths', []):
            row[p] = row.get(p, 0) + 1
    total: Dict[str, int] = {}
    for row in cov.values():
        for k, n in row.items():
            if k.startswith('frames:'):
                total[k[7:]] = total.get(k[7:], 0) + n
    print('frames by path: %s' % json.dumps(dict(sorted(total.items()))))
    if args.coverage:
        args.coverage.write_text(json.dumps(cov, indent=1) + '\n')
    print('%d frames, %d differ' % (len(dirs), bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
