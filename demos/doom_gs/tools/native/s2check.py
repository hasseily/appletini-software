#!/usr/bin/env python3
"""The comparison of milestone 11's 2D screens (docs/SCREENS.md 6.3): a
native screen against the reference's in a part's region, every other
byte its injected value or its poison, the named exclusions X1-X4
counted, and the publish order (1.3, 1.5.8) judged on a run's write log.

A screen here is aux 0 $2000-$9FFF (32,768 bytes: the pixels, the SCBs
at $9D00, the reserved $9DC8-$9DFF, the palettes at $9E00), as bytes.
A region is s2layout.Region (rows and byte ranges, SCBs, palettes).

`compare(ref_after, before, after, region, exclusions)`:
  - in the region, but the excluded bytes, the native byte equals the
    reference's after the frame (PD1);
  - outside the region, every byte keeps the value the native run started
    with (the injected screen, or the poison);
  - a "black" exclusion (X2: rows that must be black natively) compares
    with 0 instead; a "skip" exclusion (X1, X3) is not compared at all;
  - each exclusion's bytes are counted by name.

`order(writes, black)` judges one frame's aux-0 stores in the order the
write log has them: (black) the 512 palette bytes written 0, each once,
first; then newColors (palette and SCB stores); then the bands (pixel
stores); then the picture's colours (palette stores). So no band store
comes before the last black palette store or the last SCB store, and no
picture colour store before the last band store; MEMORY_MAP.md rule 10:
no store of a value other than 0 to $9DC8-$9DFF.

Standard library only.
"""

import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import s2layout as S  # noqa: E402

SCREEN = S.SHR
SCREEN_SIZE = S.SCREEN_END - S.SHR          # 32,768
PIXELS_END = S.SCB
SCB_END = S.RESERVED[0]


class Exclusion(NamedTuple):
    name: str                   # X1 ... X4
    why: str
    mode: str                   # 'skip' or 'black'
    region: Optional[S.Region]  # the screen bytes (None: X4, not a screen)


EXCLUSIONS = {
    'X1': 'the view\'s rows in a level frame (the renderer\'s; milestones '
          '8 and 10 compare them)',
    'X2': 'the benchmark page\'s CPU, CACHE, ROM rows: ZipGS and TransWarp '
          'dropped; natively black',
    'X3': 'the first title page\'s first frame\'s palette (titleWipe: no '
          'gray boot title natively)',
    'X4': 'calls where upstream\'s startSound failed: the native decision '
          'compared, the reference\'s stop of the channel injected',
}


def x1(viewtop: int) -> Exclusion:
    """X1 for a level frame by the reference's viewtop (point PV): rows
    0-167 when it is $FFFF, rows 10-167 when it is 9."""
    if viewtop == 0xFFFF:
        rg = S.REGIONS['view-full']
    elif viewtop == S.STRIP_ROWS - 1:
        rg = S.REGIONS['view']
    else:
        raise ValueError('viewtop %d' % viewtop)
    return Exclusion('X1', EXCLUSIONS['X1'], 'skip', rg)


def x2(rows_: Sequence[Tuple[int, int]]) -> Exclusion:
    """X2 for the benchmark page's rows (row ranges, inclusive)."""
    return Exclusion('X2', EXCLUSIONS['X2'], 'black', S.Region(
        'benchmark', 's2menu2', tuple((r0, r1, 0, S.ROW_BYTES - 1)
                                      for r0, r1 in rows_)))


def x3() -> Exclusion:
    return Exclusion('X3', EXCLUSIONS['X3'], 'skip', S.Region(
        'title palettes', 's2fin', (), None, tuple(range(16))))


class Result(NamedTuple):
    compared: int               # region bytes compared
    differ: List[Tuple[int, int, int]]      # (address, native, reference)
    outside: List[Tuple[int, int, int]]     # (address, native, before)
    black: List[Tuple[int, int]]            # (address, native)
    excluded: Dict[str, int]                # name -> bytes

    @property
    def ok(self) -> bool:
        return not (self.differ or self.outside or self.black)

    def problems(self, limit: int = 8) -> List[str]:
        out = ['$%04X: native $%02X, reference $%02X' % d
               for d in self.differ[:limit]]
        out += ['$%04X outside the region: native $%02X, it held $%02X' % o
                for o in self.outside[:limit]]
        out += ['$%04X must be black: native $%02X' % b
                for b in self.black[:limit]]
        return out


def offsets(region: S.Region) -> List[int]:
    """The aux-0 addresses of a region (its rows' byte ranges, its SCBs,
    its palettes; every bound inclusive), sorted."""
    out = set()
    for r0, r1, b0, b1 in region.rows:
        for row in range(r0, r1 + 1):
            at = S.SHR + S.ROW_BYTES * row
            out.update(range(at + b0, at + b1 + 1))
    if region.scbs is not None:
        out.update(range(S.SCB + region.scbs[0], S.SCB + region.scbs[1] + 1))
    for p in region.palettes:
        out.update(range(S.PALETTES + 32 * p, S.PALETTES + 32 * (p + 1)))
    return sorted(out)


def _check_screen(name: str, data: bytes) -> None:
    if len(data) != SCREEN_SIZE:
        raise ValueError('%s: %d bytes, a screen is %d' % (name, len(data),
                                                           SCREEN_SIZE))


def compare(ref_after: bytes, before: bytes, after: bytes,
            region: S.Region, exclusions: Sequence[Exclusion] = ()
            ) -> Result:
    """The native screen `after` (the run started from `before`) against
    the reference's `ref_after` in `region`; see the module's text."""
    for n, d in (('ref_after', ref_after), ('before', before),
                 ('after', after)):
        _check_screen(n, d)
    inside = set(offsets(region))
    skip: Dict[int, str] = {}
    black: Dict[int, str] = {}
    counts: Dict[str, int] = {}
    for ex in exclusions:
        counts.setdefault(ex.name, 0)
        if ex.region is None:
            continue
        for a in offsets(ex.region):
            (skip if ex.mode == 'skip' else black)[a] = ex.name
    differ, outside, blk = [], [], []
    compared = 0
    for i in range(SCREEN_SIZE):
        a = SCREEN + i
        if a in skip:
            counts[skip[a]] += 1
            continue
        if a in black:
            counts[black[a]] += 1
            if after[i] != 0:
                blk.append((a, after[i]))
            continue
        if a in inside:
            compared += 1
            if after[i] != ref_after[i]:
                differ.append((a, after[i], ref_after[i]))
        elif after[i] != before[i]:
            outside.append((a, after[i], before[i]))
    return Result(compared, differ, outside, blk, counts)


# ---------------------------------------------------------------------------
# The publish order on the write log
# ---------------------------------------------------------------------------

class Store(NamedTuple):
    offset: int                 # aux 0 address
    value: int


def screen_stores(writes) -> List[Store]:
    """The aux-0 stores to $2000-$9FFF of a write log (s2run.Write), in
    order."""
    return [Store(w.offset, w.new) for w in writes
            if w.storage == 'aux' and w.bank == 0 and
            SCREEN <= w.offset < S.SCREEN_END]


def kind(offset: int) -> str:
    if offset < PIXELS_END:
        return 'band'
    if offset < SCB_END:
        return 'scb'
    if offset < S.PALETTES:
        return 'reserved'
    return 'palette'


def order(stores: Sequence[Store], black: bool) -> List[str]:
    """The problems of one frame's stores against upstream's order (see
    the module's text); [] when it holds."""
    out: List[str] = []
    k = 0
    if black:
        seen = set()
        while k < len(stores) and len(seen) < 512:
            s = stores[k]
            if kind(s.offset) != 'palette' or s.value != 0:
                out.append('store %d ($%04X, a %s store of $%02X) before the '
                           'last black palette store' % (
                               k, s.offset, kind(s.offset), s.value))
                return out
            if s.offset in seen:
                out.append('store %d: $%04X blacked twice' % (k, s.offset))
                return out
            seen.add(s.offset)
            k += 1
        if len(seen) < 512:
            out.append('the black step wrote %d of the 512 palette bytes'
                       % len(seen))
            return out
    phase = 'colors'            # newColors, then the bands, then pictures
    last_band = None
    for i in range(k, len(stores)):
        s = stores[i]
        t = kind(s.offset)
        if t == 'reserved':
            if s.value != 0:
                out.append('store %d: $%02X to $%04X (MEMORY_MAP.md rule 10)'
                           % (i, s.value, s.offset))
            continue
        if phase == 'colors':
            if t == 'band':
                phase, last_band = 'bands', i
        elif phase == 'bands':
            if t == 'band':
                last_band = i
            elif t == 'scb':
                out.append('store %d: an SCB store after the first band '
                           'store (%d)' % (i, last_band))
            else:
                phase = 'pictures'
        else:
            if t != 'palette':
                out.append('store %d: a %s store after a picture colour '
                           'store (before the last band store)' % (i, t))
    return out


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def report(results: Sequence[Tuple[str, Result]],
           x4: int = 0) -> List[str]:
    """Each case's verdict, then the exclusions by name and count."""
    out = []
    totals: Dict[str, int] = {n: 0 for n in EXCLUSIONS}
    totals['X4'] += x4
    for name, r in results:
        out.append('%-24s %s, %d bytes compared%s' % (
            name, 'equal' if r.ok else 'DIFFERS', r.compared,
            ''.join(', %s %d' % kv for kv in sorted(r.excluded.items()))))
        out += ['    ' + p for p in r.problems()]
        for n, c in r.excluded.items():
            totals[n] += c
    out.append('Exclusions:')
    for n in sorted(EXCLUSIONS):
        out.append('  %s %8d  %s' % (n, totals[n], EXCLUSIONS[n]))
    return out
