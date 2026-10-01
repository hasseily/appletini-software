#!/usr/bin/env python3
"""The card test of the whole native renderer (milestone 8, acceptance 2;
docs/RENDER-MASKED.md 4.6): a bootable ProDOS disk that renders 100
consecutive demo3 frames from injected states and checks each frame's
screen against the reference's CRC.

Usage:  python3 tools/native/rdisk.py [--frames N] [--first K]
                [--results FILE] [--out FILE] [--check]
                [--profiles f121,fastpath] [--modes chained,full]
                [--wait N] [--no-build]

It builds build/native/RENDER.hdv (or --out), a ProDOS volume RENDER made
with the existing port's disk writer (demos/doom/tools/build_disk.py, as
tools/native/disk.py makes REPLAY.hdv), holding:

  RENDER.SYSTEM  src/native/rrunner.s's boot code (build rcard: rcard.boot
                 at $2000), then the card image: main card bank 1
                 $D000-$DFFF (the quarter squares, the math's products,
                 the far layer, the phase loader, the masked phase's card
                 loops), bank 2 $D000-$DFFF (milestone 5's row blocks and
                 draw pass), $E000-$FFFF (the runner, the replay's $F900
                 part and the bucket pass's, the vectors)
  CATALOG        the frames, the data files, the PRIVATE descriptors of
                 the static tables, the store banks, each frame's data
                 positions and expected CRC (src/native/rrunner.s)
  LEVEL          records of RamWorks banks: the level (levelconv.py:
                 segs, map, texel slots, the patch store, the sprite
                 frames, patch headers and weapon profiles), the render
                 window's images (the front end's with its W tables in
                 bank 112, the masked phase's with TXMP and the bucket
                 pass's BKFAR in 113), the tables (rtables.py: the scale
                 records, FSTEP, the math's; the aux card's trig tables,
                 destination $FE), and two staging banks of the static
                 tables the runner copies by PRIVATE into their
                 write-expensive pages (main: colormaps, CMPA/CMPB, TEXLO,
                 TEXHI, xtoviewangle; aux 0: the drawers, FUZZDARK, the
                 row tables and the fuzz directions)
  FRAMES         records of the store banks: each frame's data, run-length
                 coded records of a destination (main, aux 0, a RamWorks
                 bank), an address and a length: its chained data (the
                 game's state of the frame that changed since the frame
                 before: of the render inputs, the frame block's game
                 fields (validcount, the display's W_FSG and W_FSW, the
                 view window, the psprites' flags), the sectors, sides,
                 things, TEXTRANS and SPRBOUND the bytes that differ from
                 the frame before's, and every byte the renderer's code
                 may write (rlayout's allowed sets: every sector's
                 validcount stamp); and the screen patch: where the
                 frame's input screen differs from the reference's screen
                 at the frame before's end), and its full data (everything
                 tools/native/framestate.py injects, the renderer's state
                 and the whole input screen included)

The frames: --frames (100) consecutive demo3 frames, from --first, or by
default the window with the most shadow vissprites, then the most sprite
columns (sum of x2 - x1 + 1 at drawMasked), among the windows whose frames
share one level source and have no early flush (P2) and, with --results
(tools/native/frame8.py's JSON of demo3), none whose RULES is not 0 (a
known divergence) or whose check failed. The input screen of RENDER-
MASKED.md 2.3 item 4 is P4's (no flush in the window); the expected CRC is
zlib's CRC-32 of the screen at R_DrawLists' return (P5).

Each frame's data are applied and their SHR bytes put out (SHR left and
entered again, then a $Cxxx read) before the frame's VBL count starts.

--check runs the disk's own RENDER.SYSTEM on a2vm end to end: its MLI trap
serves the files, its memory API (--amem) the PRIVATE copies, the mouse
card's VBL interrupt the clock, under the cost model on the model's clock
(--profiles, f121 and fastpath), each mode (--modes: chained, then full
by a key F at the table): every CRC must equal the reference's, every
interrupt keep the IRQ contract (--irq-bounds: docs/MEMORY_MAP.md rule 2),
the static load make no CPU store into a write-expensive page (a2vm's
video writes less its SHR writes over the load: 0) and leave main
$0878-$087F untouched (rule 8), one memory-API request; it prints each
mode's VBLs and frames a second (50 Hz; NTSC x 60 / 50) and writes
build/native/render/rdisk.json. The owner runs the same disk on the card
at milestone 12: its CRCs must equal these.
"""

import argparse
import importlib.util
import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from a2vm import costs  # noqa: E402
from bridge import linkmap as blink  # noqa: E402
from native import a2run, framestate as FS, layout as L5, levelconv, \
    rcanon, render_check as RC, rlayout as R  # noqa: E402
from ref816 import bounded  # noqa: E402

DOOM_TOOLS = ROOT.parent / 'doom' / 'tools'
BUILD = ROOT / 'build'
OUT = BUILD / 'native' / 'RENDER.hdv'
RESULTS = BUILD / 'native' / 'render' / 'rdisk.json'
VOLUME = 'RENDER'
SYSTEM = 'RENDER.SYSTEM'
FRAMES = 100
D_END, D_MAIN, D_AUX0, D_AUXLC = 0x00, 0xFF, 0x80, 0xFE
CAT_MAX = 0x0680                # rrunner.s
C_NAMES, F_ENTRY = 16, 12
SCREEN = 0x2000
E1 = 0xE12000
BOOT_SIZE = 0x0800
IMAGE_SIZE = 0x4000
HOLE_SENTINEL = bytes(range(0xB0, 0xB8))
FABRIC_HZ = 133_333_333
CHECK_TIMEOUT = 7200
# The static tables: [start, end) of main and aux 0 the runner copies by
# PRIVATE (never main $0878-$087F: MEMORY_MAP.md rule 8)
STATIC_MAIN = ((0x0400, 0x0844), (0x0900, 0x0B94), (0x2000, 0x6000))
STATIC_AUX0 = ((0x0200, 0x02C0), (0x0800, 0x09FA), (0x0A00, 0x0AC8))


class DiskError(Exception):
    pass


# ---------------------------------------------------------------------------
# Records and the run-length code
# ---------------------------------------------------------------------------

def rle(data: bytes) -> bytes:
    """rrunner.s's code: a token t < $80, t + 1 bytes; t >= $80, the next
    byte t - $80 + 3 times (3-130)."""
    out = bytearray()
    lit = bytearray()
    i, n = 0, len(data)

    def flush():
        while lit:
            part = lit[:128]
            out.append(len(part) - 1)
            out.extend(part)
            del lit[:len(part)]
    while i < n:
        j = i
        while j < n and data[j] == data[i] and j - i < 130:
            j += 1
        if j - i >= 3:
            flush()
            out.append(0x80 + j - i - 3)
            out.append(data[i])
            i = j
        else:
            lit.append(data[i])
            i += 1
    flush()
    return bytes(out)


def unrle(code: bytes, length: int) -> bytes:
    out = bytearray()
    at = 0
    while len(out) < length:
        t = code[at]
        at += 1
        if t < 0x80:
            out += code[at:at + t + 1]
            at += t + 1
        else:
            out += bytes([code[at]]) * (t - 0x80 + 3)
            at += 1
    if len(out) != length:
        raise DiskError('a run passes its record\'s end')
    return bytes(out)


def data_record(dest: int, address: int, data: bytes) -> bytes:
    """A frame's record: destination, address, length, the coded bytes;
    pieces of 32 KB at most, never across a runner page's batch."""
    out = bytearray()
    for at in range(0, len(data), 0x8000):
        part = data[at:at + 0x8000]
        out += struct.pack('<BHH', dest, address + at, len(part))
        out += rle(part)
    return bytes(out)


def file_record(dest: int, address: int, data: bytes) -> bytes:
    """A data file's record (the boot's): destination, address, length,
    the bytes as they are."""
    out = bytearray()
    for at in range(0, len(data), 0xFF00):
        part = data[at:at + 0xFF00]
        out += struct.pack('<BHH', dest, address + at, len(part)) + part
    return bytes(out)


# ---------------------------------------------------------------------------
# The frames
# ---------------------------------------------------------------------------

def demo3_dirs() -> List[Path]:
    root = RC.RENDER / 'frames'
    return sorted(d for d in root.glob('demo3-*') if (d / 'p5.dump.z')
                  .exists())


def frame_score(d: Path, sym: blink.Symbols) -> Tuple[int, int]:
    """(shadow vissprites, sprite columns) at drawMasked (P3)."""
    p3 = FS.Frame(d).dump('p3')
    n = p3.u(sym.address('num_vissprite'), 2)
    base = sym.address('vissprites')
    cols = shadows = 0
    for i in range(n):
        at = base + 42 * i
        x1, x2 = p3.u(at, 2), p3.u(at + 2, 2)
        cols += max(0, x2 - x1 + 1)
        shadows += p3.u(at + 38, 3) == 0
    return shadows, cols


def choose(count: int, first: Optional[int], results: Optional[Path],
           sym: blink.Symbols) -> Tuple[List[Path], Dict[str, Any]]:
    dirs = demo3_dirs()
    bad = set()
    if results and results.exists():
        for r in json.loads(results.read_text()):
            if r.get('known') or r.get('problems'):
                bad.add(r['frame'])
    usable = []
    for d in dirs:
        meta = json.loads((d / 'frame.json').read_text())
        usable.append(not meta.get('flushes') and not meta.get('mflushes')
                      and d.name not in bad)
    srcs = [json.loads((d / 'frame.json').read_text())['level_src']
            for d in dirs]
    if first is not None:
        k = [i for i, d in enumerate(dirs)
             if d.name == 'demo3-%03d' % first]
        if not k:
            raise DiskError('no frame demo3-%03d' % first)
        window = dirs[k[0]:k[0] + count]
        if len(window) != count or not all(usable[k[0]:k[0] + count]) or \
                len(set(srcs[k[0]:k[0] + count])) != 1:
            raise DiskError('the frames from demo3-%03d are not %d usable '
                            'consecutive frames of one level' % (first,
                                                                 count))
        scores = [frame_score(d, sym) for d in window]
        return window, {'shadows': sum(s for s, _ in scores),
                        'columns': sum(c for _, c in scores)}
    scores = [frame_score(d, sym) for d in dirs]
    best = None
    for k in range(len(dirs) - count + 1):
        if not all(usable[k:k + count]) or \
                len(set(srcs[k:k + count])) != 1:
            continue
        idx = [int(d.name.rsplit('-', 1)[1]) for d in dirs[k:k + count]]
        if idx != list(range(idx[0], idx[0] + count)):
            continue
        key = (sum(s for s, _ in scores[k:k + count]),
               sum(c for _, c in scores[k:k + count]))
        if best is None or key > best[0]:
            best = (key, k)
    if best is None:
        raise DiskError('no %d consecutive usable demo3 frames' % count)
    (shadows, columns), k = best
    return dirs[k:k + count], {'shadows': shadows, 'columns': columns}


# The frame block's fields and their owners (RENDER-MASKED.md 4.6): the
# game's (injected into every frame of both modes) or the renderer's own
# state (the full mode only: in the chained mode it carries from frame to
# frame as in the game)
FB_GAME = ('VIEWTOP', 'VIEWBOT', 'NUKAGE', 'SKYFLAT', 'AUTOMAP', 'PSPF',
           'VALIDCOUNT', 'NUMNODES', 'W_FSG', 'W_FSW', 'NVERT', 'STATUS',
           'RULES', 'VA_COUNT', 'SKYBANK', 'SKYLO', 'SKYHI')
FB_RENDERER = ('W_FSC', 'W_FSP', 'W_TOPR', 'W_BOTR', 'W_WSK', 'FR_SKIP',
               'MM_WPOK', 'VA_VX', 'VA_VY', 'VA_STAMP', 'FZPOS', 'RW_STEP',
               'W_LCC', 'W_LFC', 'W_CEILW', 'W_FLOORW')


def owner(kind: int, bank: int, address: int) -> str:
    """'game', 'renderer' or 'static' of a framestate.records record."""
    if kind == 0:
        if R.RIN <= address < R.RIN_END or address == R.LVCOUNT:
            return 'game'
        if R.FB <= address < R.FB_END:
            for name in FB_GAME:
                if address == R.FRAME[name]:
                    return 'game'
            for name in FB_RENDERER:
                if address == R.FRAME[name]:
                    return 'renderer'
            raise DiskError('a frame block record at $%04X' % address)
        if address == R.TEXTRANS:
            return 'game'
        if address in (R.LNMAP, R.SPANS, R.CVFIRST, R.WCLIP, R.WPREV,
                       R.FRVIS, R.WTMP):
            return 'renderer'
        if address in (0x2000, 0x4000, 0x0400, 0x0600):
            return 'static'             # the colormaps
        raise DiskError('a main record at $%04X' % address)
    if bank == R.LVMAP and address in (R.VAL, R.VAH, R.VAS):
        return 'renderer'
    if bank in (R.LVMAP, R.RTH, R.SPRT):
        return 'game'
    raise DiskError('a record of bank %d $%04X' % (bank, address))


def renderer_writes(level: Dict[str, Any]
                    ) -> Dict[Tuple[int, int], List[Tuple[int, int]]]:
    """Every range the whole frame's code may write (rlayout's allowed
    sets of the front end, the masked phase, nm_bkload and the bucket
    pass), by (kind, bank) as framestate.records names them (kind 0 main,
    1 a RamWorks bank): a game byte there is sent on every chained frame,
    as the renderer may have changed it (the sectors' validcount stamps)."""
    c = level['counts']
    out: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for space, bank, lo, hi, _ in (
            R.allowed_writes_b(c['sectors'], c['vertices']) +
            R.allowed_writes_masked() + R.allowed_writes_bkload() +
            R.allowed_writes_bucket()):
        key = (0, 0) if space == 'main' else (1, bank)
        out.setdefault(key, []).append((lo, hi))
    return out


def runs_of(marks: Sequence[int], gap: int = 16) -> List[List[int]]:
    """[start, end) runs of the marked offsets, runs closer than `gap`
    joined (a record's header costs 5 bytes)."""
    runs: List[List[int]] = []
    for i in marks:
        if runs and i - runs[-1][1] <= gap:
            runs[-1][1] = i + 1
        else:
            runs.append([i, i + 1])
    return runs


def frame_data(d: Path, sym: blink.Symbols, prev: Optional[Dict[str, Any]]
               ) -> Dict[str, Any]:
    """A frame's chained and full data, its expected CRC, its colormaps.

    The chained data (RENDER-MASKED.md 4.6): of the game's records, the
    bytes that differ from the frame before's and every byte the
    renderer may write (renderer_writes; a record the frame before did
    not have is sent whole), then the screen patch. A byte not sent holds
    the frame before's injected value, which is this frame's: nothing
    but the runner's records and the renderer's code writes there."""
    frame = FS.Frame(d)
    level_dir = FS.level_of(frame, sym)
    level = json.loads((level_dir / 'level.json').read_text())
    inputs = FS.read_inputs(frame, sym, level)
    recs = FS.records(frame, inputs, level)
    screen = frame.dump('p4').read(E1, 0x8000)
    truth = frame.dump('p5').read(E1, 0x8000)
    game, renderer, static = bytearray(), bytearray(), {}
    delta = bytearray()
    game_recs: Dict[Tuple[int, int, int], bytes] = {}
    writes = renderer_writes(level)
    for kind, bank, address, data in recs:
        who = owner(kind, bank, address)
        dest = D_MAIN if kind == 0 else bank
        rec = data_record(dest, address, data)
        if who == 'game':
            game += rec
            game_recs[(kind, bank, address)] = data
            before = prev['game_recs'].get((kind, bank, address)) \
                if prev else None
            if before is None or len(before) != len(data):
                delta += rec
                continue
            hot = bytearray(len(data))
            for lo, hi in writes.get((kind, bank if kind else 0), ()):
                for a in range(max(lo, address), min(hi, address +
                                                     len(data))):
                    hot[a - address] = 1
            marks = [i for i in range(len(data))
                     if hot[i] or data[i] != before[i]]
            for a, b in runs_of(marks):
                delta += data_record(dest, address + a, data[a:b])
        elif who == 'renderer':
            renderer += rec
        else:
            static[address] = data
    full = bytes(game) + bytes(renderer) + data_record(D_AUX0, SCREEN,
                                                       screen) + b'\0'
    patch = bytearray()
    runs: List[List[int]] = []
    if prev is not None:
        prev_truth = prev['truth']
        runs = runs_of([i for i in range(0x8000)
                        if screen[i] != prev_truth[i]])
        for a, b in runs:
            patch += data_record(D_AUX0, SCREEN + a, screen[a:b])
    chained = bytes(delta) + bytes(patch) + b'\0'
    return {'name': d.name, 'level_dir': level_dir, 'level': level,
            'chained': chained, 'full': full, 'truth': truth,
            'crc': zlib.crc32(truth) & 0xFFFFFFFF, 'colormaps': static,
            'game_recs': game_recs, 'game_bytes': len(game),
            'patch_bytes': sum(b - a for a, b in runs)}


# ---------------------------------------------------------------------------
# The level, the tables, the images
# ---------------------------------------------------------------------------

def level_records(b: RC.Build, level_dir: Path, fuzzdark: bytes,
                  colormaps: Dict[int, bytes], stage: Tuple[int, int]
                  ) -> Tuple[bytes, List[bytes], List[int]]:
    """LEVEL's records, the PRIVATE descriptors of the static tables (their
    staging banks `stage`), the banks it fills."""
    out = bytearray()
    banks = set()

    def bank_rec(bank: int, address: int, data: bytes) -> None:
        nonlocal out
        if not (R.BANK_ROOM[0] <= address and
                address + len(data) <= R.BANK_ROOM[1]):
            raise DiskError('bank %d $%04X+%d outside $0200-$BFFF' % (
                bank, address, len(data)))
        out += file_record(bank, address, data)
        banks.add(bank)
    for kind, bank, address, data in levelconv.Image.parse(
            (level_dir / 'level.img').read_bytes()):
        bank_rec(bank, address, data)
    for kind, bank, address, data in levelconv.Image.parse(
            (level_dir / 'wtables.img').read_bytes()):
        bank_rec(R.WCODE_BANK, address, data)
    for kind, bank, address, data in levelconv.Image.parse(
            (level_dir / 'mtables.img').read_bytes()):
        bank_rec(R.MCODE_BANK, address, data)
    w = (b.obj / ('%s.w' % b.name)).read_bytes()
    bank_rec(R.WCODE_BANK, 0x6000, w[:RC.w_end(b) + 1 - 0x6000])
    wm = (b.obj / ('%s.wm' % b.name)).read_bytes()
    bank_rec(R.MCODE_BANK, R.MCODE, wm)
    main = bytearray(0x10000)
    aux0 = bytearray(0x10000)
    for kind, bank, address, data in levelconv.Image.parse(
            (RC.TABLES / 'tables.img').read_bytes()):
        if kind == 0:
            main[address:address + len(data)] = data
        elif bank == 0 and address >= 0xC000:
            out += file_record(D_AUXLC, address, data)
        else:
            bank_rec(bank, address, data)
    m = RC.TABLES / 'math'
    t = R.MT_TBANK
    bank_rec(t, 0x2000, (m / 'sinelo.bin').read_bytes())
    bank_rec(t, 0x4000, (m / 'sinehi.bin').read_bytes())
    for k in range(4):
        bank_rec(t, 0x6000 + 256 * 9 * k, (m / ('tanto%d.bin' % k))
                 .read_bytes())
    bank_rec(t, 0x8400, (m / 'quartlo.bin').read_bytes())
    bank_rec(t, 0x8C00, (m / 'quarthi.bin').read_bytes())
    bank_rec(R.MT_RLO, 0x2000, (m / 'reciplo.bin').read_bytes())
    bank_rec(R.MT_RHI, 0x2000, (m / 'reciphi.bin').read_bytes())
    # the static tables: main's (the build's CMPA .. TEXHI, xtoviewangle,
    # the colormaps), aux 0's (the drawers, the tables, FUZZDARK)
    m08 = (b.obj / ('%s.m08' % b.name)).read_bytes()
    for lo, hi in L5.MAIN_TABLE_RANGES:
        main[lo:hi] = m08[lo - L5.MAIN_TABLES:hi - L5.MAIN_TABLES]
    for address, data in colormaps.items():
        main[address:address + len(data)] = data
    a02 = (b.obj / ('%s.a02' % b.name)).read_bytes()
    aux0[L5.AUXCODE:L5.AUXCODE + len(a02)] = a02
    a08 = (b.obj / ('%s.a08' % b.name)).read_bytes()
    for lo, hi in L5.AUX_TABLE_RANGES:
        aux0[lo:hi] = a08[lo - L5.AUX_TABLES:hi - L5.AUX_TABLES]
    aux0[L5.FUZZDARK:L5.FUZZDARK + 256] = fuzzdark
    descs = []
    for space, ranges, image, bank in ((0, STATIC_MAIN, main, stage[0]),
                                       (1, STATIC_AUX0, aux0, stage[1])):
        for lo, hi in ranges:
            if space == 0 and lo < 0x0880 and hi > 0x0878:
                raise DiskError('a static range over $0878-$087F')
            bank_rec(bank, lo, bytes(image[lo:hi]))
            descs.append(struct.pack('<BBBBHBBHHI', 1, 1, 1, bank, lo, space,
                                     0, lo, hi - lo, 0))
    return bytes(out) + b'\0', descs, sorted(banks)


def card_image(b: RC.Build) -> bytes:
    """The main card: bank 1 $D000-$DFFF, bank 2 $D000-$DFFF,
    $E000-$FFFF (rrunner.s's boot copies them in that order)."""
    seg = b.segments
    bank1 = bytearray(0x1000)
    squares = (RC.TABLES / 'math' / 'squares.bin').read_bytes()
    bank1[:len(squares)] = squares
    for name, part, base in (('MATHLC', 'lc1', 0xD800),
                             ('MATHFAR', 'far', 0xDC00),
                             ('RFAR', 'far', 0xDC00),
                             ('RLOAD', 'far', 0xDC00),
                             ('MFAR', 'far', 0xDC00)):
        lo, hi = seg[name]
        data = (b.obj / ('%s.%s' % (b.name, part))).read_bytes()
        bank1[lo - 0xD000:hi + 1 - 0xD000] = data[lo - base:hi + 1 - base]
    bank2 = bytearray(0x1000)
    lc2 = (b.obj / ('%s.lc2' % b.name)).read_bytes()
    bank2[:len(lc2)] = lc2[:0x1000]
    high = bytearray(0x2000)
    for name, part, base in (('DRIVER', 'lce', 0xE000),
                             ('RCODE', 'rc', 0xF900),
                             ('BKNEAR', 'rc', 0xF900),
                             ('VECTORS', 'vec', 0xFFFA)):
        lo, hi = seg[name]
        data = (b.obj / ('%s.%s' % (b.name, part))).read_bytes()
        high[lo - 0xE000:hi + 1 - 0xE000] = data[lo - base:hi + 1 - base]
    return bytes(bank1 + bank2 + high)


def system_file(b: RC.Build) -> bytes:
    boot = (b.obj / ('%s.boot' % b.name)).read_bytes()
    if len(boot) != BOOT_SIZE:
        raise DiskError('rcard.boot is %d bytes, not %d' % (len(boot),
                                                            BOOT_SIZE))
    data = boot + card_image(b)
    # ProDOS loads the file at $2000 with CPU stores: never the firmware's
    # A2Li signature at $4078 (MEMORY_MAP.md rule 8)
    if data[0x4078 - 0x2000:0x407C - 0x2000] == bytes((0xC1, 0xB2, 0xCC,
                                                       0xE9)):
        raise DiskError('RENDER.SYSTEM holds the A2Li signature at $4078')
    return data


# ---------------------------------------------------------------------------
# The disk
# ---------------------------------------------------------------------------

def disk_writer():
    path = DOOM_TOOLS / 'build_disk.py'
    spec = importlib.util.spec_from_file_location('doom_build_disk_r', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build(count: int, first: Optional[int], results: Optional[Path],
          wait: int, obj: Path) -> Dict[str, Any]:
    sym = blink.Symbols()
    b = RC.load_build(obj, 'rcard')
    dirs, score = choose(count, first, results, sym)
    frames = []
    prev = None
    for d in dirs:
        f = frame_data(d, sym, prev)
        frames.append(f)
        prev = f
    levels = {str(f['level_dir']) for f in frames}
    if len(levels) != 1:
        raise DiskError('the frames take %d level conversions' % len(levels))
    level_dir = frames[0]['level_dir']
    cmaps = frames[0]['colormaps']
    for f in frames:
        if f['colormaps'] != cmaps:
            raise DiskError('%s: the colormaps change in the window'
                            % f['name'])
    fuzzdark = (level_dir / 'fuzzdark.bin').read_bytes()
    # the banks: the level's, the renderer's, the static staging and the
    # frames' store from the rest
    used = set(frames[0]['level']['banks']) | {
        R.LVSEG, R.LVMAP, R.RENDB, R.SPRT, R.WPRO, R.RTH, R.RECW,
        R.SEAM} | set(R.RECSP) | set(R.CODE) | set(R.FSTEP_BANKS) | {
        R.MT_TBANK, R.MT_RLO, R.MT_RHI}
    free = [k for k in range(1, 127) if k not in used]
    stage = (free[0], free[1])
    store = free[2:]
    level, descs, filled = level_records(b, level_dir, fuzzdark, cmaps,
                                         stage)
    # the frames' store: each frame's chained then full data, at a page
    room = R.BANK_ROOM[1] - R.BANK_ROOM[0]
    stream = bytearray()
    positions = []

    def place(data: bytes) -> Tuple[int, int]:
        at = len(stream)
        if at % 256:
            raise DiskError('a frame\'s data not at a page')
        idx, off = divmod(at, room)
        stream.extend(data)
        stream.extend(bytes(-len(stream) % 256))
        return idx, R.BANK_ROOM[0] + off
    for f in frames:
        positions.append((place(f['chained']), place(f['full'])))
    need = -(-len(stream) // room)
    if need > len(store):
        raise DiskError('the frames need %d store banks, %d are free'
                        % (need, len(store)))
    store = store[:need]
    frames_file = bytearray()
    for k, bank in enumerate(store):
        part = bytes(stream[k * room:(k + 1) * room])
        frames_file += file_record(bank, R.BANK_ROOM[0], part)
    frames_file += b'\0'
    names = ['LEVEL', 'FRAMES']
    first_index = int(frames[0]['name'].rsplit('-', 1)[1])
    cat = bytearray(16)
    cat[0], cat[1], cat[2] = len(frames), len(names), 0
    cat[3:5] = first_index.to_bytes(2, 'little')
    cat[5], cat[6], cat[7] = len(descs), len(store), wait
    for n in names:
        entry = bytearray(16)
        entry[0] = len(n)
        entry[1:1 + len(n)] = n.encode('ascii')
        cat += entry
    for dsc in descs:
        cat += dsc
    cat += bytes(store)
    for f, ((ci, ca), (fi, fa)) in zip(frames, positions):
        cat += bytes((ci,)) + ca.to_bytes(2, 'little') + bytes((fi,)) + \
            fa.to_bytes(2, 'little') + f['crc'].to_bytes(4, 'little') + \
            bytes(2)
    if len(cat) > CAT_MAX:
        raise DiskError('the catalog is %d bytes, the runner holds %d'
                        % (len(cat), CAT_MAX))
    files = [(SYSTEM, 0xFF, 0x2000, system_file(b)),
             ('CATALOG', 0x06, 0x0000, bytes(cat)),
             ('LEVEL', 0x06, 0x0000, level),
             ('FRAMES', 0x06, 0x0000, bytes(frames_file))]
    return {'files': files, 'frames': frames, 'score': score, 'store': store,
            'stage': stage, 'descs': descs, 'level_banks': filled,
            'labels': b.labels, 'stream': len(stream)}


def write_disk(files, output: Path) -> None:
    bd = disk_writer()
    bd.VOLUME_NAME = VOLUME
    master = bd.DEFAULT_MASTER
    if not master.is_file():
        raise FileNotFoundError('%s is missing (appletini-one\'s ProDOS; '
                                'set APPLETINI_ROOT)' % master)
    boot, prodos = bd.extract_prodos(master)
    everything = [files[0], ('PRODOS', bd.FILE_TYPE_SYS, 0x0000, prodos)] + \
        files[1:]
    writer = bd.VolumeWriter(VOLUME, bd.volume_size([f[3] for f in
                                                     everything]))
    writer.set_boot_blocks(boot)
    for name, file_type, aux, data in everything:
        writer.add_file(name, data, file_type, aux)
    image = writer.finish()
    expected = {name: (t, aux, data) for name, t, aux, data in everything}
    bd.verify_image(image, expected, order=[f[0] for f in everything])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(image)


# ---------------------------------------------------------------------------
# The check on a2vm
# ---------------------------------------------------------------------------

def check(disk: Dict[str, Any], work: Path, profile: str,
          modes: Sequence[str]) -> Dict[str, Any]:
    """One a2vm run of the disk: the modes in order (the runner's start
    mode is chained; a key F at the table runs the full mode); each
    mode's results from a snapshot of the card at the table."""
    work = work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    lab = disk['labels']
    manifest = []
    for name, file_type, aux, data in disk['files']:
        path = work / name
        path.write_bytes(data)
        manifest.append('%s %02X %04X %s' % (name, file_type, aux, path))
    (work / 'prodos.txt').write_text('\n'.join(manifest) + '\n')
    (work / 'rom.bin').write_bytes(bytes(0x4000))
    (work / 'hole.bin').write_bytes(HOLE_SENTINEL)
    (work / 'cost.txt').write_text(costs.text(profile))
    events = ['pc %X snapshot statics0' % lab['run_start'],
              'pc %X snapshot statics1' % lab['run_again']]
    for k, mode in enumerate(modes):
        events.append('pc %X@%d snapshot table%d' % (lab['run_table'],
                                                     k + 1, k))
        if k + 1 < len(modes):
            events.append('pc %X@%d key %s' % (
                lab['run_table'], k + 1, 'F' if modes[k + 1] == 'full'
                else 'C'))
        else:
            events.append('pc %X@%d stop' % (lab['run_table'], k + 1))
    if modes[0] != 'chained':
        raise DiskError('the runner starts chained')
    (work / 'events.txt').write_text('\n'.join(events) + '\n')
    frames = len(disk['frames'])
    seconds = 30 + frames * len(modes) * 1.0
    args = [str(a2run.A2VM), '--rom', str(work / 'rom.bin'),
            '--core', 'w65c02s', '--amem',
            '--prodos', str(work / 'prodos.txt'),
            '--volume', VOLUME, '--launched', SYSTEM,
            '--load', '2000:%s' % (work / SYSTEM),
            '--load', '0878:%s' % (work / 'hole.bin'),
            '--reg', 'pc=2000', '--reg', 's=FF',
            '--cost', str(work / 'cost.txt'), '--cost-timed',
            '--irq-bounds', '00D8-01FF,C0A0-C0AF,E000-FFFF',
            '--stop-pc', '%X' % lab['run_crash'],
            '--cycles', str(int(seconds * FABRIC_HZ)),
            '--snapshot-dir', str(work),
            '--input', str(work / 'events.txt'),
            '--state', str(work / 'state.json')]
    result = bounded.run(['nice', '-n', '10'] + args,
                         timeout=CHECK_TIMEOUT, max_bytes=1 << 30,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         universal_newlines=True)
    state_path = work / 'state.json'
    if not state_path.exists():
        raise DiskError('a2vm failed: %s' % result.stdout[-1000:])
    state = json.loads(state_path.read_text())
    out: Dict[str, Any] = {'profile': profile, 'end': state.get('end'),
                           'pc': state.get('pc')}
    if state.get('pc') == lab['run_crash']:
        raise DiskError('%s: the runner stopped (its fatal message)' %
                        profile)
    statics = statics_check(work)
    out['statics'] = statics
    results = lab['results'] - 0xC000
    for k, mode in enumerate(modes):
        shot = a2run.read_snapshot(work, 'table%d' % k)
        ram = shot.ram
        rows = []
        for i, f in enumerate(disk['frames']):
            at = a2run.LC + results + 8 * i
            crc = int.from_bytes(ram[at:at + 4], 'little')
            vbls = int.from_bytes(ram[at + 4:at + 6], 'little')
            rows.append({'frame': f['name'], 'crc': '%08X' % crc,
                         'expected': '%08X' % f['crc'],
                         'ok': crc == f['crc'] and ram[at + 6] == 1,
                         'vbls': vbls})
        at = a2run.LC + lab['rn_vbls'] - 0xC000
        total = int.from_bytes(ram[at:at + 2], 'little')
        ok_at = a2run.LC + lab['rn_ok'] - 0xC000
        screen = text_screen(ram)
        for name in ('table%d' % k,):
            for suffix in ('.ram', '.json'):
                p = work / (name + suffix)
                if p.exists():
                    p.unlink()
        out[mode] = {'frames': rows, 'vbls': total,
                     'ok': sum(r['ok'] for r in rows),
                     'runner_ok': ram[ok_at],
                     'fps50': round(frames * 50.0 / total, 2) if total
                     else None,
                     'fps60': round(frames * 60.0 / total, 2) if total
                     else None,
                     'screen': screen}
    return out


def statics_check(work: Path) -> Dict[str, Any]:
    """The static tables' load, from the snapshots around the runner's
    start: its video writes outside aux 0's screen (none may be: rule 3),
    main $0878-$087F (never written: rule 8), the memory-API requests (one,
    with the probe's STATUS: two), main $4078-$407F after it."""
    shots = [a2run.read_snapshot(work, name)
             for name in ('statics0', 'statics1')]
    before, after = (s.state for s in shots)
    other = (after['video_writes'] - before['video_writes']) - \
        (after['shr_writes'] - before['shr_writes'])
    hole = [shots[i].ram[a2run.MAIN + 0x0878:a2run.MAIN + 0x0880]
            for i in (0, 1)]
    requests = after['amem']['requests'] - before['amem']['requests']
    out = {'other_video_writes': other,
           'hole_0878_kept': hole[0] == hole[1] == HOLE_SENTINEL,
           'amem_requests': requests}
    out['ok'] = other == 0 and out['hole_0878_kept'] and requests == 2
    for name in ('statics0', 'statics1'):
        for suffix in ('.ram', '.json'):
            p = work / (name + suffix)
            if p.exists():
                p.unlink()
    return out


def text_screen(ram: bytes) -> List[str]:
    rows = []
    for r in range(24):
        at = 0x0400 + (r % 8) * 0x80 + (r // 8) * 0x28
        rows.append(''.join(chr(b & 0x7F) if 0x20 <= (b & 0x7F) < 0x7F
                            else '?' for b in ram[a2run.MAIN + at:
                                                  a2run.MAIN + at + 40])
                    .rstrip())
    return rows


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames', type=int, default=FRAMES)
    parser.add_argument('--first', type=int)
    parser.add_argument('--results', type=Path,
                        default=RC.RENDER / 'frame8-demo3.json')
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--wait', type=int, default=0)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--profiles', default='f121,fastpath')
    parser.add_argument('--modes', default='chained,full')
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--obj', type=Path, default=RC.OBJ)
    parser.add_argument('--json', type=Path, default=RESULTS)
    args = parser.parse_args(argv)
    if not 1 <= args.frames <= 100:
        parser.error('--frames is 1-100 (the runner\'s results)')
    if not args.no_build:
        RC.make(args.obj)
    try:
        disk = build(args.frames, args.first, args.results, args.wait,
                     args.obj)
        write_disk(disk['files'], args.out)
    except (DiskError, FS.FrameError, levelconv.ConvError,
            rcanon.CanonError, FileNotFoundError) as e:
        print('rdisk: %s' % e, file=sys.stderr)
        return 1
    fr = disk['frames']
    size = args.out.stat().st_size
    print('%s: %d frames %s .. %s (%d shadow vissprites, %d sprite columns), '
          '%d bytes (%d blocks); LEVEL %d B, FRAMES %d B in %d store banks '
          '(%s), static staging banks %d, %d; chained data %d B, full %d B; '
          'screen patches %d B' % (
              args.out, len(fr), fr[0]['name'], fr[-1]['name'],
              disk['score']['shadows'], disk['score']['columns'], size,
              size // 512, len(disk['files'][2][3]),
              len(disk['files'][3][3]), len(disk['store']),
              ','.join(str(b) for b in disk['store']), disk['stage'][0],
              disk['stage'][1], sum(len(f['chained']) for f in fr),
              sum(len(f['full']) for f in fr),
              sum(f['patch_bytes'] for f in fr)))
    report: Dict[str, Any] = {'disk': str(args.out), 'bytes': size,
                              'frames': [f['name'] for f in fr],
                              'crcs': ['%08X' % f['crc'] for f in fr],
                              'score': disk['score'], 'checks': []}
    failed = False
    if args.check:
        modes = args.modes.split(',')
        for profile in args.profiles.split(','):
            work = BUILD / ('tmp-m8-rdisk-%s' % profile)
            try:
                r = check(disk, work, profile, modes)
            except DiskError as e:
                print('  a2vm %s: FAILED: %s' % (profile, e))
                failed = True
                continue
            finally:
                import shutil
                shutil.rmtree(str(work), ignore_errors=True)
            report['checks'].append(r)
            st = r['statics']
            print('  a2vm %s: the static load: %d video writes outside the '
                  'screen, $0878-$087F %s, %d memory-API requests' % (
                      profile, st['other_video_writes'],
                      'untouched' if st['hole_0878_kept'] else 'WRITTEN',
                      st['amem_requests']))
            failed |= not st['ok']
            for mode in modes:
                m = r[mode]
                bad = [x for x in m['frames'] if not x['ok']]
                print('  a2vm %s %s: %d of %d CRCs equal; %d VBLs for %d '
                      'frames: %.2f frames a second at 50 Hz (%.2f NTSC)' % (
                          profile, mode, m['ok'], len(m['frames']),
                          m['vbls'], len(m['frames']), m['fps50'] or 0,
                          m['fps60'] or 0))
                for x in bad[:8]:
                    print('    %s: CRC %s, expected %s' % (
                        x['frame'], x['crc'], x['expected']))
                failed |= bool(bad)
                for text in m['screen']:
                    if text:
                        print('    | ' + text)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=1) + '\n')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
