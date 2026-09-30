#!/usr/bin/env python3
"""Synthetic record streams for the native replay, with upstream's truth.

Usage:  python3 tools/native/synth.py [--out DIR] [--styles a,b,...]
                                      [--seed N] [--make-base]

Writes one directory a stream into build/native/synth/ (or --out), in the
format of tools/ref816/capture.py's captures, so tools/native/loader.py
and tools/native/replay_check.py take them as they take captured frames:
the record pages of bank $1D, COLW, the spans with the covered ranges,
the weapon skip, the colormaps, the fuzz table, the screen (and the
drawers' buffer, the same bytes), the texels, and screen-after.bin, the
truth: ref816 --call of upstream's R_DrawLists on that state. The rest
of the machine is a real R_DrawLists entry (build/native/base-entry.img,
all of RAM when the replay of a demo frame starts; --make-base captures
it again).

Each style stresses part of the record format (lists.inc), always within
what upstream's producers make (a K_TEXC follows its chain's record and
never starts a page; a shadow's rows are 1-166; a covered range names a
record of its column):

  mixed      every kind, random rows, steps, colormaps, cuts
  chains     sprite posts: K_TEX then K_TEXC chains, covered ranges
  fuzz       shadows at every fuzz position, over walls and fills
  overlay    automap pixels (K_OVL) over the view
  rows       every covered-range case at both row parities, one case a
             column, nothing after the covering record repainting its
             rows; K_TEXC covering records, K_TEXC chains behind a
             skipped K_TEX; rows 0-168
  steps      whole steps 0-127, fraction extremes, texels near 127,
             records of over 128 rows
  colormaps  all 34 light levels
  pages      long lists: K_NEXT into the extra pages
  batches    over 8 KB of records: several batches
  strips     texel spans over the 16 KB stage: several strips
  fuzzedge   the fuzz queue's rule (tools/native/loader.py mark_fuzz):
             in each column a shadow, then a later record of every kind
             that paints the row just above it or just below it (so the
             shadow must be drawn in place), or inside it, or one row
             clear of it (so it may wait in the queue); the shadow reads
             the neighbour row the later record paints. In some columns
             the later record is a shadow and a third record paints the
             row next to it, away from the first, so the later shadow is
             drawn in place and the first must be too when they touch
  fuzzfull   the fuzz queue full: 3-4 shadows a column over walls, in two
             strips, several times the queue's FQMAX records a strip,
             some of them under a later record

The generator is deterministic (its own xorshift, not Python's random).
Standard library only.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from native import layout as L  # noqa: E402
from ref816 import capture as refcapture, lists, refimage, title  # noqa: E402

BUILD = ROOT / 'build'
BASE = BUILD / 'native' / 'base-entry.img'
BASE_CALL = BUILD / 'native' / 'base-call.json'
OUT = BUILD / 'native' / 'synth'
FORMAT = 'native-synthetic 1'
TEXEL_BANKS = range(0x30, 0x38)      # in the level window, empty in the base
STYLES = ('mixed', 'chains', 'fuzz', 'overlay', 'rows', 'steps',
          'colormaps', 'pages', 'batches', 'strips', 'fuzzedge', 'fuzzfull')


class Rng:
    """xorshift64*: the same numbers on every Python."""

    def __init__(self, seed: int):
        self.state = (seed * 0x9E3779B97F4A7C15 + 1) & (2 ** 64 - 1) or 1

    def next(self) -> int:
        x = self.state
        x ^= x >> 12
        x ^= (x << 25) & (2 ** 64 - 1)
        x ^= x >> 27
        self.state = x
        return (x * 0x2545F4914F6CDD1D) & (2 ** 64 - 1)

    def below(self, n: int) -> int:
        return (self.next() >> 11) % n

    def range(self, low: int, high: int) -> int:
        """low .. high inclusive."""
        return low + self.below(high - low + 1)

    def chance(self, p: float) -> bool:
        return (self.next() >> 11) / float(1 << 53) < p

    def pick(self, items):
        return items[self.below(len(items))]

    def bytes(self, n: int) -> bytes:
        return bytes(self.next() >> 56 for _ in range(n))


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------

class Gen:
    """Makes the records of one stream, column by column."""

    def __init__(self, rng: Rng, style: str):
        self.rng = rng
        self.style = style
        self.windows: List[int] = []     # texel windows (24-bit addresses)

    # -- fields --
    def rows(self, low=0, high=L.VIEW_ROWS, longest=L.VIEW_ROWS):
        r = self.rng
        if r.chance(0.15):
            a = r.pick([low, low + 1, high - 2, high - 1])
            a = max(low, min(a, high - 1))
        else:
            a = r.range(low, high - 1)
        e = min(high, a + r.range(1, longest))
        if r.chance(0.1):
            e = high
        return a, e

    def step(self):
        r = self.rng
        if self.style == 'steps':
            si = r.pick([0, 0, 1, 1, 2, 3, 4, 7, 31, 63, 64, 100, 126, 127])
            sf = r.pick([0, 1, 127, 128, 129, 254, 255, r.range(0, 255)])
        elif self.style == 'strips':
            si, sf = r.pick([0, 1]), r.range(0, 255)
        else:
            si = r.pick([0, 0, 0, 1, 1, 2, 3, 4, 5, r.range(0, 127)])
            sf = r.range(0, 255)
        return sf, si

    def position(self):
        r = self.rng
        tf = r.range(0, 255)
        ti = r.pick([0, 1, 126, 127]) if r.chance(0.2) else r.range(0, 127)
        if self.style == 'strips':
            ti = r.range(100, 127)
        return tf, ti

    def cmp(self):
        return L.CMAP_FIRST + self.rng.range(0, L.CMAP_LEVELS - 1)

    def window(self, bank: Optional[int] = None) -> int:
        r = self.rng
        bank = r.pick(list(TEXEL_BANKS)) if bank is None else bank
        address = bank << 16 | r.range(0, 0xFF7F)
        self.windows.append(address)
        return address

    # -- records --
    def tex(self, a, e, chain=None):
        tf, ti = self.position()
        sf, si = self.step()
        src = self.window()
        rec = [L.K_TEX, a, e, tf, ti, sf, si, src & 0xff, (src >> 8) & 0xff,
               src >> 16, self.cmp()]
        return {'kind': L.K_TEX, 'bytes': rec}

    def texc(self, a, e, chain):
        tf, ti = self.position()
        src = self.window(chain['bytes'][9])
        rec = [L.K_TEXC, a, e, tf, ti, src & 0xff, (src >> 8) & 0xff]
        return {'kind': L.K_TEXC, 'bytes': rec}

    def fill(self, a, e):
        r = self.rng
        return {'kind': L.K_FILL, 'bytes': [L.K_FILL, a, e, r.range(0, 255),
                                            r.range(0, 255)]}

    def fuzz(self):
        r = self.rng
        a, e = self.rows(1, L.VIEW_ROWS - 1)   # rows 1-166, as visColF
        return {'kind': L.K_FUZZ, 'bytes': [L.K_FUZZ, a, e - a,
                                            r.range(0, 49)]}

    def ovl(self):
        r = self.rng
        keep = r.pick([0x0F, 0xF0, 0x00, 0xFF, r.range(0, 255)])
        colour = r.range(0, 255) & (~keep & 0xff)
        return {'kind': L.K_OVL, 'bytes': [L.K_OVL, r.range(0, 167), keep,
                                           colour]}

    def sprite(self, first=None):
        """A masked column: a K_TEX and a chain of K_TEXC below it."""
        r = self.rng
        top = r.range(0, 150) if first is None else first
        out = []
        chain = None
        row = top
        for _ in range(r.range(1, 5)):
            if row >= L.VIEW_ROWS:
                break
            a = row
            e = min(L.VIEW_ROWS, a + r.range(1, 30))
            rec = self.tex(a, e) if chain is None else self.texc(a, e, chain)
            if chain is None:
                chain = rec
            out.append(rec)
            row = e + r.range(0, 6)
        return out

    def column(self, c: int) -> Tuple[List[Dict], Optional[Tuple]]:
        """The records of column c and its covered range (first, end,
        index of the covering record) or None."""
        r, s = self.rng, self.style
        recs: List[Dict] = []
        if s == 'rows':
            return self.rows_column(c)
        if s == 'fuzzedge':
            return self.edge_column(c), None
        if s == 'fuzzfull':
            return self.full_column(c), None
        count = {'mixed': (0, 8), 'chains': (1, 4), 'fuzz': (1, 5),
                 'overlay': (1, 4), 'steps': (1, 6), 'colormaps': (1, 5),
                 'pages': (1, 4), 'batches': (5, 12),
                 'strips': (1, 3)}[s]
        if s == 'pages' and c % 10 == 3:        # some lists fill 2-3 pages
            count = (35, 50)
        for _ in range(r.range(*count)):
            k = r.below(100)
            if s == 'pages':
                recs.append(self.tex(*self.rows()) if k < 50 else
                            self.fill(*self.rows()))
            elif s == 'chains':
                recs += self.sprite() if k < 60 else [self.fill(*self.rows())]
            elif s == 'fuzz':
                recs.append(self.fuzz() if k < 50 else
                            self.tex(*self.rows()) if k < 80 else
                            self.fill(*self.rows()))
            elif s == 'overlay':
                recs.append(self.tex(*self.rows()) if k < 40 else
                            self.fill(*self.rows()))
            elif s == 'strips':
                recs.append(self.tex(*self.rows(0, L.VIEW_ROWS, 120)))
            elif s in ('steps', 'colormaps'):
                recs.append(self.tex(*self.rows()) if k < 80 else
                            self.fill(*self.rows()))
            else:
                recs += (self.sprite() if k < 20 else
                         [self.tex(*self.rows())] if k < 55 else
                         [self.fill(*self.rows())] if k < 85 else
                         [self.fuzz()] if k < 93 else [self.ovl()])
        if s in ('overlay', 'mixed') and r.chance(0.6 if s == 'overlay'
                                                   else 0.1):
            recs += [self.ovl() for _ in range(r.range(1, 12))]
        cut = None
        textures = [i for i, x in enumerate(recs)
                    if x['kind'] in (L.K_TEX, L.K_TEXC)]
        if textures and r.chance(0.35):
            i = r.pick(textures)
            a, e = recs[i]['bytes'][1], recs[i]['bytes'][2]
            if r.chance(0.2):
                a, e = self.rows()
            cut = (a, e, i)
        elif r.chance(0.05):
            cut = r.pick([(255, 254, None), (0, 0, None)])
        return recs, cut

    def fuzz_at(self, a, n, reads=None):
        """A shadow of n rows from row a. reads 'above' or 'below': a
        position whose first row reads the row above it, or whose last
        row reads the row below it (layout.py FUZZ_DIR)."""
        r = self.rng
        while True:
            pos = r.range(0, 49)
            if reads == 'above' and L.FUZZ_DIR[pos] != 0:
                continue
            if reads == 'below' and L.FUZZ_DIR[(pos + n - 1) % 50] != 1:
                continue
            return {'kind': L.K_FUZZ, 'bytes': [L.K_FUZZ, a, n, pos]}

    def painter(self, kind, a, e):
        """A record of this kind painting rows a .. e - 1 (K_OVL: row
        a)."""
        if kind == L.K_TEX:
            return self.tex(a, e)
        if kind == L.K_FILL:
            return self.fill(a, e)
        if kind == L.K_FUZZ:
            return self.fuzz_at(a, e - a)
        rec = self.ovl()
        rec['bytes'][1] = a
        return rec

    # where the later record of a fuzzedge column paints, against the
    # shadow's rows a .. e - 1: (name, the shadow must be drawn in place)
    EDGE_CASES = (('above, touching', True), ('above, clear', False),
                  ('below, touching', True), ('below, clear', False),
                  ('inside', True))
    EDGE_KINDS = (L.K_TEX, L.K_FILL, L.K_OVL, L.K_FUZZ)

    def edge_column(self, c: int) -> List[Dict]:
        """A shadow, then a later record (EDGE_CASES by EDGE_KINDS, in
        turn by column) that paints the row just above or below it,
        inside it, or one row clear of it. For the neighbour cases the
        shadow's first (last) row reads the row above (below), so drawing
        the shadow after the later record would change its pixels. A
        second shadow, far from both, waits in the queue in some
        columns. When the later record is a shadow above or below it, in
        every other run of EDGE_CASES by EDGE_KINDS a third record, a
        one-row fill, paints the row on the later shadow's far side: that
        shadow is then drawn in place, so a first shadow it touches must
        be drawn in place before it (a mark that ignored later shadows
        would queue the first and draw it after the later one), and one
        clear of it may wait (the unmarked pair in the other order)."""
        r = self.rng
        case, touch = self.EDGE_CASES[c % len(self.EDGE_CASES)]
        kind = self.EDGE_KINDS[(c // len(self.EDGE_CASES)) %
                               len(self.EDGE_KINDS)]
        a = r.range(50, 110)        # (clear of the second shadow's rows)
        n = r.range(1, 16)
        e = a + n
        span = r.range(1, 12) if kind != L.K_OVL else 1
        if case.startswith('above'):
            last = a - 1 if touch else a - 2       # its last row
            x0, x1 = max(1, last + 1 - span), last + 1
            shadow = self.fuzz_at(a, n, 'above')
        elif case.startswith('below'):
            x0 = e if touch else e + 1
            x1 = min(L.VIEW_ROWS - 1, x0 + span)
            shadow = self.fuzz_at(a, n, 'below')
        else:
            x0 = r.range(a, e - 1)
            x1 = min(e, x0 + span)
            shadow = self.fuzz_at(a, n)
        # two walls under it: 260 stage bytes a column, so three strips,
        # each with fewer than FQMAX shadows to queue (none is drawn in
        # place for want of room)
        recs = [self.tex(0, L.VIEW_ROWS), self.tex(0, L.VIEW_ROWS)]
        for wall in recs:
            wall['bytes'][6] = r.range(2, 5)
        recs.append(shadow)
        if r.chance(0.125):
            recs.append(self.fuzz_at(r.range(1, 20), r.range(1, 10)))
        recs.append(self.painter(kind, x0, x1))
        cycle = len(self.EDGE_CASES) * len(self.EDGE_KINDS)
        if kind == L.K_FUZZ and case != 'inside' and (c // cycle) % 2:
            row = x0 - 1 if case.startswith('above') else x1
            recs.append(self.fill(row, row + 1))
        return recs

    def full_column(self, c: int) -> List[Dict]:
        """A wall of all 168 rows (its 128 texels take 130 stage bytes, so
        the 160 columns make two strips), then 3-4 shadows with at least
        two rows between them; in one column of five a later record over
        or next to one of them."""
        r = self.rng
        wall = self.tex(0, L.VIEW_ROWS)
        wall['bytes'][6] = r.range(2, 5)    # a whole step of 2 or more
        recs = [wall]
        rows = []
        top = 1
        for _ in range(r.range(3, 4)):
            a = r.range(top, top + 10)
            n = r.range(1, 20)
            if a + n > L.VIEW_ROWS - 1:
                break
            recs.append(self.fuzz_at(a, n))
            rows.append((a, a + n))
            top = a + n + 2
        if rows and c % 5 == 0:
            a, e = r.pick(rows)
            kind = r.pick(self.EDGE_KINDS)
            x0 = r.pick([max(1, a - 1), e, r.range(a, e - 1)])
            x1 = min(L.VIEW_ROWS - 1, x0 + r.range(1, 6))
            if x1 <= x0:
                x0, x1 = a, a + 1
            recs.append(self.painter(kind, x0, x1))
        return recs

    ROW_CASES = ('before', 'end-in', 'end-at', 'spans', 'inside', 'exact',
                 'start-in', 'after', 'whole', 'texc-behind-skipped',
                 'start-in-all')

    def rows_column(self, c: int):
        """One case of cutTex and cutFill (r_list65.s) around a covered range
        c0 .. c1 - 1 in column c (the cases in turn, their edges at random
        parities): the record of the case, the covering record (a K_TEX, or
        a K_TEXC of the case's chain), then a record inside the range, which
        the cut must no longer touch. Nothing after the case's record paints
        its rows outside the range, so the rows it keeps and loses show in
        the pixels; the rows it loses inside the range show only in the
        count of screen stores (the covering record paints them again)."""
        r = self.rng
        case = self.ROW_CASES[c % len(self.ROW_CASES)]
        d = lambda: r.range(0, 1)       # noqa: E731 (an edge moves by 0-1)
        c0 = r.range(2, 120)
        c1 = min(L.VIEW_ROWS - 2, c0 + r.range(1, 40))
        if case == 'start-in-all':      # an odd first row, an even c1
            c0 |= 1
            c1 = min(L.VIEW_ROWS - 2, c0 + 1 + 2 * r.range(1, 20))
            c1 &= ~1
        edges = {
            'before': (max(0, c0 - 5 - d()), c0 - d()),
            'end-in': (max(0, c0 - 3 - d()), min(c1, c0 + 1 + d())),
            'end-at': (max(0, c0 - 2 - d()), c1),
            'spans': (max(0, c0 - 1 - d()),
                      min(L.VIEW_ROWS, c1 + 1 + d())),
            'inside': (min(c1 - 1, c0 + d()), min(c1, c0 + 2 + d())),
            'exact': (c0, c1),
            'start-in': (min(c1 - 1, c0 + d()),
                         min(L.VIEW_ROWS, c1 + 1 + r.range(0, 5))),
            'after': (c1 + d(), min(L.VIEW_ROWS, c1 + 2 + r.range(0, 5))),
            'whole': (0, L.VIEW_ROWS),
            'texc-behind-skipped': (min(c1 - 1, c0 + d()),
                                    min(L.VIEW_ROWS, c1 + 1 + d())),
            'start-in-all': (c0, min(L.VIEW_ROWS, c1 + 10 + r.range(0, 5))),
        }
        a, e = edges[case]
        recs = []
        if case == 'texc-behind-skipped':
            # a K_TEX inside the range (skipped whole), its K_TEXC after it
            head = self.tex(c0, min(c1, c0 + 1 + d()))
            recs += [head, self.texc(a, e, head)]
        elif case == 'start-in-all':
            # a unit or zero whole step from a texel near 127: the span
            # passes texel 127, so the gather copies all 128 bytes
            rec = self.tex(a, e)
            rec['bytes'][4] = r.range(115, 127)
            rec['bytes'][6] = 1
            recs.append(rec)
        else:
            k = r.below(3)
            if k == 0:
                recs.append(self.fill(a, e))
            elif k == 1:
                recs.append(self.tex(a, e))
            else:
                # a K_TEXC case behind its chain's K_TEX, which the range
                # hides (inside it) or which ends above the case
                if r.chance(0.5):
                    head = self.tex(c0, min(c1, c0 + 1 + d()))
                else:
                    top = max(0, a - r.range(1, 4))
                    head = self.tex(top, max(top + 1, a))
                recs += [head, self.texc(a, e, head)]
        last = recs[-1]
        if last['kind'] in (L.K_TEX, L.K_TEXC) and r.chance(0.5):
            chain = next(x for x in reversed(recs) if x['kind'] == L.K_TEX)
            recs.append(self.texc(c0, c1, chain))   # a K_TEXC covers it
        else:
            recs.append(self.tex(c0, c1))           # the covering record
        cover = len(recs) - 1
        a2 = r.range(c0, c1 - 1)
        e2 = r.range(a2 + 1, c1)
        recs.append(self.fill(a2, e2) if r.chance(0.5) else
                    self.tex(a2, e2))
        return recs, (c0, c1, cover)


# ---------------------------------------------------------------------------
# the lists in bank $1D (recAlloc and newPage of r_list65.s)
# ---------------------------------------------------------------------------

def lay_out(columns: List[Tuple[List[Dict], Optional[Tuple]]], lay
            ) -> Tuple[refimage.Memory, List[int], int, List[Tuple]]:
    """Write the lists; returns the memory, COLW, XPNEXT and each
    column's covered range as (first, end, CV_REC word)."""
    mem = refimage.Memory()
    colw, cvs = [], []
    xp = lay.xp_first
    for c, (recs, cut) in enumerate(columns):
        page, offset = lists.colpage(c), 0
        origins = []
        chain = None
        for rec in recs:
            data = list(rec['bytes'])
            size = len(data)
            if offset + size > L.PAGE_ROOM:
                if xp > 0xFF:
                    raise ValueError('the stream needs more than the %d '
                                     'extra pages' % (0x100 - lay.xp_first))
                mem.put(lay.recbase + (page << 8) + offset,
                        bytes([L.K_NEXT, xp]))
                page, offset = xp, 0
                xp += 1
                if rec['kind'] == L.K_TEXC:     # a page starts with a K_TEX
                    cb = chain['bytes']
                    data = [L.K_TEX, data[1], data[2], data[3], data[4],
                            cb[5], cb[6], data[5], data[6], cb[9], cb[10]]
                    size = len(data)
            if data[0] == L.K_TEX:
                chain = {'bytes': data}
            origins.append(page << 8 | offset)
            mem.put(lay.recbase + (page << 8) + offset, bytes(data))
            offset += size
        colw.append(page << 8 | offset)
        if cut is None:
            cvs.append((0, 0, 0))
        else:
            first, end, index = cut
            cvs.append((first, end, origins[index] if index is not None
                        else 0))
    return mem, colw, (xp if xp <= 0xFF else 0), cvs


# ---------------------------------------------------------------------------
# a stream's directory
# ---------------------------------------------------------------------------

def base_image() -> refimage.Image:
    if not BASE.exists():
        raise FileNotFoundError('%s is missing: run python3 tools/native/'
                                'synth.py --make-base' % BASE)
    return refimage.read(BASE)


def entry_address() -> int:
    return json.loads(BASE_CALL.read_text())['entry']


def write_stream(out: Path, style: str, seed: int, units: Dict,
                 base: refimage.Memory, header: refimage.Image) -> Dict:
    lay = lists.layout(units)
    u = units['r_list65.s']
    rng = Rng(seed)
    gen = Gen(rng, style)
    columns = [gen.column(c) for c in range(lay.columns)]
    records, colw, xpnext, cvs = lay_out(columns, lay)

    if out.exists():
        shutil.rmtree(str(out))
    out.mkdir(parents=True)
    files = []

    def raw(name, address, data, what):
        (out / (name + '.bin')).write_bytes(data)
        files.append(refcapture.file_entry(name, name + '.bin', what,
                                           'before', data, address=address))

    for page, count in lists.record_pages(lay):
        address = lay.recbase + (page << 8)
        raw('records-%02x' % page, address, records.get(address, count << 8),
            'synthetic column records, pages $%02X-$%02X of bank $%02X'
            % (page, page + count - 1, lay.recbase >> 16))
    listing = bytearray(base.get(u['COLW'], u['colOrder'] + 2 * lay.columns
                                 - u['COLW']))
    for c, word in enumerate(colw):
        listing[2 * c:2 * c + 2] = word.to_bytes(2, 'little')
    at = u['XPNEXT'] - u['COLW']
    listing[at:at + 2] = bytes((xpnext, 0))
    raw('lists', u['COLW'], bytes(listing), 'COLW, XPNEXT, colOrder')

    pixels = rng.bytes(L.PIXELS)
    screen = pixels + base.get(refcapture.SCREEN + L.PIXELS,
                               L.SCREEN_SIZE - L.PIXELS)
    raw('screen', refcapture.SCREEN, screen, 'random pixels; the SCBs and '
        'palettes of the base')
    raw('buffer', refcapture.BUFFER, screen, 'the same bytes as the screen')

    stride = u['FS_EVEN'] - u['FS_ROW']
    spans = bytearray(base.get(u['FS_ROW'], u['CV_REC'] + stride -
                               u['FS_ROW']))
    for c, (first, end, rec) in enumerate(cvs):
        at = u['CV_ROW'] - u['FS_ROW'] + 2 * c
        spans[at:at + 2] = bytes((first, end))
        at = u['CV_REC'] - u['FS_ROW'] + 2 * c
        spans[at:at + 2] = rec.to_bytes(2, 'little')
    raw('spans', u['FS_ROW'], bytes(spans), 'the base\'s fill spans; '
        'synthetic covered ranges')
    raw('weapon', u['WCLIP'], base.get(u['WCLIP'], u['WTMP'] + 2 *
                                       lay.columns - u['WCLIP']),
        'the base\'s weapon skip')
    maps = units['drawcol.s']
    raw('colormaps', maps['iigs_shrcmapA'], rng.bytes(2 * L.CMAP_LEVELS * 256),
        'random colormaps A and B')
    raw('fuzz', units['i_viigs65.s']['FUZZ_DARKEN'], rng.bytes(256),
        'a random darkening table')

    texels = refimage.Memory()
    for address in gen.windows:
        for i in range(lists.TEXEL_SPAN):
            if not texels.is_known(address + i):
                texels.put(address + i, rng.bytes(1))
    runs = list(texels.runs())
    data = refimage.image_bytes(header.registers, header.switches, runs)
    (out / 'texels.img').write_bytes(data)
    files.append(refcapture.file_entry(
        'texels', 'texels.img', 'random texels', 'before', data,
        ranges=[(a, len(d)) for a, d in runs]))

    counts = {name: 0 for name in lists.KINDS}
    for recs, _ in columns:
        for rec in recs:
            counts[L.KIND_NAMES[rec['kind']]] += 1
    manifest = {
        'format': FORMAT, 'synthetic': True, 'name': out.name,
        'style': style, 'seed': seed,
        'base': str(BASE.relative_to(ROOT)),
        'entry': {'symbol': refcapture.ENTRY, 'address': entry_address()},
        'files': files,
        'records': dict(counts, extra_pages=(xpnext or 0x100) -
                        lay.xp_first,
                        cuts=sum(1 for f, e, r in cvs if e and f < e)),
    }
    refcapture.write_manifest(out, manifest)
    truth = oracle(out, manifest, screen, out / 'oracle')
    (out / 'screen-after.bin').write_bytes(truth)
    shutil.rmtree(str(out / 'oracle'), ignore_errors=True)
    manifest['files'].append(refcapture.file_entry(
        'screen-after', 'screen-after.bin', 'the screen after upstream\'s '
        'R_DrawLists (ref816 --call)', 'after', truth,
        address=refcapture.SCREEN))
    refcapture.write_manifest(out, manifest)
    return manifest


def oracle(directory: Path, manifest: Dict, screen: bytes,
           scratch: Path) -> bytes:
    """ref816 --call of upstream's R_DrawLists on the base image with the
    stream's files, `screen` in the screen and the buffer: the screen
    after it."""
    scratch.mkdir(parents=True, exist_ok=True)
    screen_path = scratch / 'screen-in.bin'
    screen_path.write_bytes(screen)
    out = scratch / 'screen-out.bin'
    command = [str(title.MACHINE), str(ROOT / manifest['base'])]
    for f in manifest['files']:
        if f['when'] != 'before':
            continue
        if f['format'] == 'raw':
            command += ['--load', '%06X:%s' % (f['address'],
                                               directory / f['file'])]
        else:
            command += ['--load-image', str(directory / f['file'])]
    command += ['--load', '%06X:%s' % (refcapture.SCREEN, screen_path),
                '--load', '%06X:%s' % (refcapture.BUFFER, screen_path),
                '--call', '%06X' % manifest['entry']['address'],
                '--save', '%06X:0x%X:%s' % (refcapture.SCREEN,
                                            L.SCREEN_SIZE, out)]
    result = subprocess.run(command, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True)
    if result.returncode:
        raise RuntimeError('ref816 --call failed: %s' % result.stderr)
    state = json.loads(result.stdout)
    if state['end']['reason'] != 'return':
        raise RuntimeError('ref816 --call did not return: %s'
                           % state['end'])
    return out.read_bytes()


def make_base() -> None:
    """build/native/base-entry.img: all RAM at the last demo frame's
    R_DrawLists entry (tools/ref816/capture.py's demo set, raw)."""
    from ref816 import make_image, script
    title.build_machine()
    title.ensure_image()
    linkmap = json.loads(make_image.LINKMAP.read_text())
    selection = next(s for s in refcapture.SETS if s.key == 'demo')
    work = Path(tempfile.mkdtemp(prefix='native-base-',
                                 dir=str(BUILD / 'native')))
    try:
        refcapture.run_selection(selection, script.Symbols(linkmap),
                                 linkmap['game']['units'], work,
                                 keep_raw=True, check=False)
        hits = sorted((work / 'raw' / 'demo').iterdir())
        BASE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(hits[-1] / 'entry.img'), str(BASE))
        shutil.copyfile(str(hits[-1] / 'call.json'), str(BASE_CALL))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--styles', default=','.join(STYLES))
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--make-base', action='store_true')
    args = parser.parse_args(argv)
    styles = args.styles.split(',')
    unknown = set(styles) - set(STYLES)
    if unknown:
        parser.error('no style %s' % ', '.join(sorted(unknown)))
    if args.make_base or not BASE.exists():
        make_base()
    from ref816 import make_image
    units = json.loads(make_image.LINKMAP.read_text())['game']['units']
    header = base_image()
    base = refimage.load(header)
    for number, style in enumerate(styles):
        seed = args.seed * 1000 + STYLES.index(style)
        manifest = write_stream(args.out / ('synth-%s' % style), style,
                                seed, units, base, header)
        r = manifest['records']
        print('%-16s seed %d: %s' % (manifest['name'], seed, ', '.join(
            '%s %d' % (k, r[k]) for k in r)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
