"""The labels and segments of a native link (load_build: its .lbl and
.map, such as the render card's build in OBJ), and base_records, the
image records of a render build: the fill, the tables (rtables.py's
TABLES) and the code (pldisk.py takes the window-mode records).
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import levelconv, rlayout as R  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
RENDER = BUILD / 'native' / 'render'
OBJ = RENDER / 'obj'
TABLES = RENDER / 'tables'


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------

class Build(NamedTuple):
    obj: Path
    name: str                   # rtest or rprof
    labels: Dict[str, int]
    segments: Dict[str, Tuple[int, int]]


def load_build(obj: Path = OBJ, name: str = 'rtest') -> Build:
    labels = {}
    for line in (obj / (name + '.lbl')).read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == 'al':
            labels[parts[2].lstrip('.')] = int(parts[1], 16)
    segs = {}
    text = (obj / (name + '.map')).read_text()
    for m in re.finditer(r'^(\w+)\s+([0-9A-F]{6})\s+([0-9A-F]{6})\s+'
                         r'([0-9A-F]{6})', text, re.M):
        segs[m.group(1)] = (int(m.group(2), 16), int(m.group(3), 16))
    return Build(obj, name, labels, segs)


def w_end(b: Build) -> int:
    """The last byte of the front end's W image (MATHW, AUXW, then
    RENDERW: render.cfg)."""
    return max(b.segments[s][1] for s in ('MATHW', 'AUXW', 'RENDERW')
               if s in b.segments)


# ---------------------------------------------------------------------------
# The image
# ---------------------------------------------------------------------------

def base_records(b: Build, fill: int, window: bool = False
                 ) -> List[Tuple[int, int, int, bytes]]:
    """The fill, the tables and the code (not the level, not the frame).
    window: the W code goes into the render window's image bank
    (WCODE_BANK, at its own addresses) for the phase loader, W itself
    keeps the fill (frame mode)."""
    recs: List[Tuple[int, int, int, bytes]] = []
    pattern = bytes([fill]) * 0x10000
    recs.append((0, 0, 0x0000, pattern[:0xC000]))
    for bank in range(128):
        recs.append((1, bank, 0, pattern))
    lc = bytearray(pattern[:0x4000])          # kind 2: $C000-$FFFF
    lc1 = bytearray(pattern[:0x1000])         # kind 3: bank 1 $D000
    squares = (TABLES / 'math' / 'squares.bin').read_bytes()
    lc1[0:len(squares)] = squares
    for seg, part in (('MATHLC', 'lc1'), ('MATHFAR', 'far'),
                      ('RFAR', 'far'), ('RLOAD', 'far'), ('MFAR', 'far')):
        if seg not in b.segments:
            continue
        start, end = b.segments[seg]
        data = (b.obj / ('%s.%s' % (b.name, part))).read_bytes()
        base = 0xD800 if part == 'lc1' else 0xDC00
        lc1[start - 0xD000:end + 1 - 0xD000] = \
            data[start - base:end + 1 - base]
    start, end = b.segments['DRIVER']
    data = (b.obj / ('%s.lce' % b.name)).read_bytes()
    lc[start - 0xC000:end + 1 - 0xC000] = data[:end + 1 - start]
    # the whole frame's builds: the record replay
    # (card bank 2 $D000-$DFFF, its $F900 part) and the bucket pass's card
    # part after it; the main and aux 0 tables and drawers below
    for seg, part, base in (('TEXBLK', 'lc2', 0xD000),
                            ('FILLE', 'lc2', 0xD000),
                            ('FILLO', 'lc2', 0xD000),
                            ('RHOT', 'lc2', 0xD000),
                            ('RCODE', 'rc', 0xF900),
                            ('BKNEAR', 'rc', 0xF900)):
        if seg not in b.segments:
            continue
        start, end = b.segments[seg]
        data = (b.obj / ('%s.%s' % (b.name, part))).read_bytes()
        lc[start - 0xC000:end + 1 - 0xC000] = data[start - base:
                                                   end + 1 - base]
    recs.append((2, 0, 0xC000, bytes(lc)))
    if 'MAINTAB' in b.segments:
        from native import layout as L5
        m08 = (b.obj / ('%s.m08' % b.name)).read_bytes()
        for lo, hi in L5.MAIN_TABLE_RANGES:
            recs.append((0, 0, lo, m08[lo - L5.MAIN_TABLES:
                                       hi - L5.MAIN_TABLES]))
        a02 = (b.obj / ('%s.a02' % b.name)).read_bytes()
        recs.append((1, 0, L5.AUXCODE, a02))
        a08 = (b.obj / ('%s.a08' % b.name)).read_bytes()
        for lo, hi in L5.AUX_TABLE_RANGES:
            recs.append((1, 0, lo, a08[lo - L5.AUX_TABLES:
                                       hi - L5.AUX_TABLES]))
    recs.append((3, 0, 0xD000, bytes(lc1)))
    w = (b.obj / ('%s.w' % b.name)).read_bytes()
    wend = w_end(b)
    if window:
        recs.append((1, R.WCODE_BANK, 0x6000, w[:wend + 1 - 0x6000]))
    else:
        recs.append((0, 0, 0x6000, w[:wend + 1 - 0x6000]))
    if 'MASKW' in b.segments:           # the masked image
        start, end = b.segments['MASKW']   # (with the bucket
        wm = (b.obj / ('%s.wm' % b.name)).read_bytes()  # pass's BKFAR
        recs.append((1, R.MCODE_BANK, start, wm))       # after the code)
    for kind, bank, address, data in levelconv.Image.parse(
            (TABLES / 'tables.img').read_bytes()):
        recs.append((kind, bank, address, data))
    m = TABLES / 'math'
    t = R.MT_TBANK
    recs.append((1, t, 0x2000, (m / 'sinelo.bin').read_bytes()))
    recs.append((1, t, 0x4000, (m / 'sinehi.bin').read_bytes()))
    for k in range(4):
        recs.append((1, t, 0x6000 + 256 * 9 * k,
                     (m / ('tanto%d.bin' % k)).read_bytes()))
    recs.append((1, t, 0x8400, (m / 'quartlo.bin').read_bytes()))
    recs.append((1, t, 0x8C00, (m / 'quarthi.bin').read_bytes()))
    recs.append((1, R.MT_RLO, 0x2000, (m / 'reciplo.bin').read_bytes()))
    recs.append((1, R.MT_RHI, 0x2000, (m / 'reciphi.bin').read_bytes()))
    return recs
