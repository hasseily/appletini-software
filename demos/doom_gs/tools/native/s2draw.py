#!/usr/bin/env python3
"""The host model of upstream's 2D drawing rules (docs/SCREENS.md 1.4;
part s2draw, docs/m11-parts/s2draw.md): the nibble rule of IIGS_DrawPatch
with its clipping and marks (markPatch, markRect), capPost's CAPVAL and
CAPMSK, drawRawData through pairByte, V_DrawBackground, copyToBuffer and
markVP, and showDirty's publish of the marked bytes. Written from
upstream's src/iigs/patch65.s and i_viigs65.s (the routines' behaviour,
16-bit arithmetic as theirs); ref816's runs of the same routines are the
truth it is checked against (tools/native/s2drawcase.py), and the native
drawers (src/native/s2_draw.s, s2_pub.s) are compared with ref816.

The screen is upstream's back buffer, 200 rows of 160 bytes. The tables:
NIBTAB (16 palettes of 1 KB: left even, left odd, right even, right odd
pages), each row's page iigs_rowpageL/R (palette * 4 + parity, + 2 for the
right pixel) and iigs_rowbase (the left page << 8).

Usage:  python3 tools/native/s2draw.py --columns
        (every 2D patch of DOOM1.WAD: the longest column, against the
        drawers' 256-byte contract)
"""

import argparse
import struct
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

ROWS = 200
ROW = 160
SCREEN = ROWS * ROW
COLUMN_LIMIT = 256          # a column's bytes the drawer can hold at once
# the lumps of the 2D screens: the status bar's, the menus', the
# intermission's (and the fonts STCFN*, among ST*)
PREFIXES = ('ST', 'M_', 'WI')


def u16(b: bytes, at: int) -> int:
    return b[at] | b[at + 1] << 8


def s16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


class Marks:
    """Upstream's DRB, DRE (a byte each row) and DRY0, DRY1."""

    def __init__(self, drb: bytes = bytes(ROWS), dre: bytes = bytes(ROWS),
                 dry0: int = 0, dry1: int = 0):
        self.drb = bytearray(drb)
        self.dre = bytearray(dre)
        self.dry0 = dry0
        self.dry1 = dry1

    def copy(self) -> 'Marks':
        return Marks(self.drb, self.dre, self.dry0, self.dry1)


class Tables(NamedTuple):
    nibtab: bytes               # 16 KB
    rowl: bytes                 # iigs_rowpageL, 200
    rowr: bytes                 # iigs_rowpageR, 200
    rowbase: Tuple[int, ...]    # iigs_rowbase, 200 words


def consistent(t: Tables) -> List[str]:
    """Rows whose tables are not one palette's (rowbase = rowpageL << 8,
    rowpageR = rowpageL + 2, the left page even or odd of its palette): the
    native row tables (ROWL, ROWR) hold the same pages only then."""
    out = []
    for r in range(ROWS):
        if t.rowbase[r] != t.rowl[r] << 8 or t.rowr[r] != t.rowl[r] + 2 or \
                t.rowl[r] & 2:
            out.append('row %d: rowpageL $%02X rowpageR $%02X rowbase $%04X'
                       % (r, t.rowl[r], t.rowr[r], t.rowbase[r]))
    return out


def mark_rect(m: Marks, first: int, end: int, b0: int, b1: int) -> None:
    """markRect: rows first .. end - 1, bytes b0 .. b1."""
    if first >= end:
        return
    if m.dry1 == 0:
        m.dry0, m.dry1 = first, end
    else:
        if first < m.dry0:
            m.dry0 = first
        if end >= m.dry1:
            m.dry1 = end
    for r in range(first, end):
        if m.dre[r] == 0:
            m.drb[r] = b0
            m.dre[r] = (b1 + 1) & 0xFF
        else:
            if b0 < m.drb[r]:
                m.drb[r] = b0
            if (b1 + 1) & 0xFF >= m.dre[r]:
                m.dre[r] = (b1 + 1) & 0xFF


def mark_patch(m: Marks, x: int, y: int, w: int, h: int) -> None:
    """markPatch: the patch's rectangle clipped to the screen."""
    first = 0 if x & 0x8000 else x & 0xFFFF
    if first >= 320:
        return
    b0 = first >> 1
    last = (x + w - 1) & 0xFFFF
    if last & 0x8000:
        return
    b1 = min(last, 319) >> 1
    if b1 < b0:
        return
    end = (y + h) & 0xFFFF
    if end & 0x8000 or end == 0:
        return
    end = min(end, 200)
    top = 0 if y & 0x8000 else y & 0xFFFF
    mark_rect(m, top, end, b0, b1)


class Capture:
    """CAPVAL, CAPMSK by the back buffer's offset (0 .. 31,999)."""

    def __init__(self, val: bytes = bytes(SCREEN), msk: bytes = bytes(SCREEN)):
        self.val = bytearray(val)
        self.msk = bytearray(msk)


def columns(patch: bytes) -> List[int]:
    """Each column's offset (columnofs' low word)."""
    w = u16(patch, 0)
    return [u16(patch, 8 + 4 * c) for c in range(w)]


def column_bytes(patch: bytes, offset: int) -> int:
    """A column's bytes: its posts and the $FF that ends them."""
    p = offset
    while patch[p] != 0xFF:
        p += patch[p + 1] + 4
    return p + 1 - offset


def draw_patch(buf: bytearray, m: Marks, patch: bytes, x: int, y: int,
               t: Tables, cap: Optional[Capture] = None) -> int:
    """IIGS_DrawPatch at (x, y), the offsets applied; the pixels written."""
    x &= 0xFFFF
    y &= 0xFFFF
    w, h = u16(patch, 0), u16(patch, 2)
    mark_patch(m, x, y, w, h)
    n = 0
    for col in range(w):
        px = (x + col) & 0xFFFF
        if px >= 320:
            continue
        left, odd = px >> 1, px & 1
        mask = 0xF0 if odd else 0x0F
        pages = t.rowr if odd else t.rowl
        p = u16(patch, 8 + 4 * col)
        while patch[p] != 0xFF:
            row = (patch[p] + y) & 0xFFFF
            length = patch[p + 1]
            if row >= 200:
                break               # (upstream: the column ends there)
            cnt = 200 - row if row + length >= 201 else length
            for i in range(cnt):
                r = row + i
                v = t.nibtab[pages[r] << 8 | patch[p + 3 + i]]
                o = r * ROW + left
                buf[o] = buf[o] & mask | v
                n += 1
                if cap is not None:
                    cap.val[o] = cap.val[o] & mask | v
                    cap.msk[o] |= ~mask & 0xFF
            p = (p + length + 4) & 0xFFFF
    return n


def vpatch_position(patch: bytes, x: int, y: int) -> Tuple[int, int]:
    """V_DrawPatchNotScaled: the position less the patch's offsets."""
    return (x - u16(patch, 4)) & 0xFFFF, (y - u16(patch, 6)) & 0xFFFF


def pair_byte(t: Tables, row: int, left: int, right: int) -> int:
    base = t.rowbase[row]
    return (t.nibtab[(base + left) & 0x3FFF] |
            t.nibtab[(base + 0x200 + right) & 0x3FFF]) & 0xFF


def draw_raw(buf: bytearray, m: Marks, lump: bytes, offset: int,
             length: int, t: Tables) -> None:
    """drawRawData: `length` bytes of pairs from the offset of a 320-wide
    screen (rows past 199 are left out: upstream writes them past the
    screen), then markRows(first, min(row, 200))."""
    x, y = offset % 320, offset // 320
    y0, done = y, 0
    while done < length:
        while x < 320 and done < length:
            a = lump[done] if done < len(lump) else 0
            b = lump[done + 1] if done + 1 < len(lump) else 0
            if y < ROWS:
                buf[y * ROW + (x >> 1)] = pair_byte(t, y, a, b)
            done += 2
            x += 2
        x = 0
        y += 1
    mark_rect(m, y0, min(y, 200), 0, 159)


def draw_back(buf: bytearray, m: Marks, flat: bytes, t: Tables) -> None:
    """V_DrawBackground: the 64 x 64 flat tiled, every row marked."""
    for y in range(ROWS):
        f = (y & 63) * 64
        row = [pair_byte(t, y, flat[f + 2 * j], flat[f + 2 * j + 1])
               for j in range(32)]
        for b in range(ROW):
            buf[y * ROW + b] = row[b & 31]
    mark_rect(m, 0, 200, 0, 159)


def rect_empty(y0: int, y1: int, b0: int, b1: int) -> bool:
    """rectEmpty, signed."""
    return s16(y0) >= s16(y1) or s16(b1) < s16(b0)


def copy_rect(buf: bytearray, m: Marks, source, y0: int, y1: int, b0: int,
              b1: int) -> None:
    """copyToBuffer of the rows y0 .. y1 - 1, bytes b0 .. b1 (source(row)
    gives the row's 160 bytes), then markVP."""
    if rect_empty(y0, y1, b0, b1):
        return
    for r in range(y0, y1):
        src = source(r)
        buf[r * ROW + b0:r * ROW + b1 + 1] = src[b0:b1 + 1]
    mark_rect(m, y0, y1, b0, b1)


def publish(screen: bytearray, band: bytes, y0: int, drb: bytes, dre: bytes,
            dry0: int, dry1: int) -> int:
    """showDirty of a band: its rows dry0 .. dry1 - 1 (band rows), the
    bytes drb .. dre - 1 of each with dre not 0, from the band to the
    screen's row y0 + row. The bytes copied."""
    n = 0
    for r in range(dry0, dry1):
        if dre[r]:
            a, b = drb[r], dre[r]
            screen[(y0 + r) * ROW + a:(y0 + r) * ROW + b] = \
                band[r * ROW + a:r * ROW + b]
            n += max(0, b - a)
    return n


# ---------------------------------------------------------------------------
# The WAD's 2D patches
# ---------------------------------------------------------------------------

def is_patch(data: bytes) -> bool:
    """A Doom patch whose every column parses inside the lump."""
    if len(data) < 8:
        return False
    w, h = u16(data, 0), u16(data, 2)
    if not (0 < w <= 320 and 0 < h <= 200) or len(data) < 8 + 4 * w:
        return False
    for off in columns(data):
        p = off
        while True:
            if p >= len(data):
                return False
            if data[p] == 0xFF:
                break
            if p + 1 >= len(data):
                return False
            p += data[p + 1] + 4
    return True


def wad_patches(wad: Optional[Path] = None) -> Dict[str, bytes]:
    """The 2D patches of DOOM1.WAD (ST*, M_*, WI*), by name."""
    from ref816 import lumps
    data = lumps.read_wad(wad) if wad else lumps.read_wad()
    return {n: b for n, b in sorted(data.items())
            if n.startswith(PREFIXES) and is_patch(b)}


def longest_columns(patches: Dict[str, bytes]) -> List[Tuple[int, str]]:
    return sorted(((max(column_bytes(p, o) for o in columns(p)), n)
                   for n, p in patches.items()), reverse=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--columns', action='store_true')
    args = parser.parse_args(argv)
    if args.columns:
        patches = wad_patches()
        longest = longest_columns(patches)
        print('%d patches; the longest columns: %s' % (
            len(patches), ', '.join('%s %d B' % (n, b)
                                    for b, n in longest[:5])))
        over = [n for b, n in longest if b > COLUMN_LIMIT]
        if over:
            print('over %d B: %s' % (COLUMN_LIMIT, ', '.join(over)))
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
