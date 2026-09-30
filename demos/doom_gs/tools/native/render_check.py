#!/usr/bin/env python3
"""The harness of the native renderer front end (milestone 7,
docs/RENDER.md section 4): checkpoint A on the captured frames, routine
mode (checkpoint B = acceptance 2) on the wall calls, and frame mode
(checkpoint C = acceptance 1) with its timing report.

Usage:  python3 tools/native/render_check.py [--frames NAME,...]
                 [--sets m5,newgame,title,tour] [--jobs 2] [--timing]
                 [--obj DIR] [--no-build] [--json FILE]
        python3 tools/native/render_check.py --frame-mode [--frames ...]
                 [--sets ...] [--timing] [--report FILE]
        python3 tools/native/render_check.py --routines checkpoint|all
                 [--cases FRAME/wKK,...] [--kinds wall,seg]
        python3 tools/native/render_check.py --routine-timing [--sets ...]
        python3 tools/native/render_check.py --sizes

Frame mode (stage C, RENDER.md 4.3, 5.3; acceptance 1): each captured
frame, twice ($A5, $5A), on the whole front end (the build rwall): the
render window's image (rwall.w's code and the level's W tables) in its
RamWorks bank, W itself filled; the driver's drv_wframe turns the VBL
interrupt on, loads the window with the phase loader (far_wload) and
calls nr_frame, which runs R_FillStamps, the setup and clears, the
seam's clip pass, the weapon skip, the walk with the real wall setup and
seg loops, the sky, and flushes the last batch. At the walk's entry
(nr_bsp) checkpoint A's values and stage C's stamps and weapon skip must
equal P0b's; at the end every output of RENDER.md 2.4 must equal the
reference's at drawMasked (rcanon.frame_truth: the records of the frame
by column, the clips, the drawsegs and their openings, the spans, the
stamps, the weapon skip, validcount and every sector's, the lines
mapped, rw_scalestep, the vertex angles computed); the write log holds
no write outside the allowed set (the render code's, the loader's: W
only, the driver's). --timing then runs the profiling build rwprof under
f121 and fastpath and reports each phase (1 the window load, 2 the
frame setup, 3 the walk, 9 the wall setup, 10 the seg loops): ms, 65C02
cycles and soft-switch accesses (a2vm's phase_cycles, phase_io), with
the correctness run's far windows, bytes staged and lowest S; --report
writes build/native/render/report.md.

Routine mode (stage B, RENDER.md 4.3): each case of tools/native/
routinecap.py (a wall call of a captured frame, with its seg loop call)
or tools/native/routinesynth.py (a synthetic one), for each routine and
each fill ($A5, $5A): the native state from the reference's at the call
(tools/native/segdesc.py), the stage B build (rwall) running
nr_storewall or nr_segloop through the driver's drv_wall or drv_seg
(synced to a VBL so that the next falls inside the call), the outputs
(tools/native/rcanon.py's routine mode) equal to the reference's at the
return, no write outside stage B's allowed set. A call that reaches a
sky column was stage B's deferred case: stage C draws it, so every
call must now be equal; the synthetic cases of RULED must take their
rules of our own (RENDER.md 3.9) and equal upstream wherever it stays
in its tables. `checkpoint` is 1,000 calls evenly over the captured
calls without a sky, the calls a path or loop of the coverage report
needs, every call with a sky (the 62 stage B deferred), and the
synthetic cases but the ruled ones; `all` every case.

For each frame of tools/native/rendercap.py (build/native/render/frames),
twice, once with every byte the frame does not define filled with $A5 and
once with $5A (RENDER.md 4.2): the level (levelconv.py), the tables
(rtables.py), the code (src/native/render.mk's rtest build) and the frame
(framestate.py) go into an a2vm image; the driver (src/native/rdriver.s)
turns the mouse card's VBL interrupt on and calls nr_frame, whose wall
calls go to the lockstep stub. a2vm runs the exact W65C02S core with a
VBL every 17,030 cycles (--speed 1, so the interrupt comes several times
a frame), a cycle limit, --irq-bounds on the stub's handler, --lowest-s-in
over the render code, a snapshot at nr_bsp's entry and at the frame's
end, and a write log of every storage but the stack page. Checkpoint A
(RENDER.md 5.1, item 4) passes on a frame when, in both runs:

  - the run ends at the driver's halt, with at least one interrupt taken
    and the frame's status 0;
  - the list of wall calls (start, stop, seg, front sector, floor and
    ceiling colours, worldbottom) equals ref816's call log;
  - validcount and every sector's stamp equal P3's (drawMasked);
  - the vertex angles computed equal ref816's vtxAngle calls;
  - at nr_bsp's entry the clears (CEILCLIP, FLOORCLIP after the seam,
    SOLIDCOL, the drawseg count, lastopening) and the frame block's
    derived values (LT_BASE, LT_FIXED, viewsin, viewcos, validcount, the
    vertex cache's map unit) equal P0b's (R_RenderBSPNode's entry); the
    map unit at the end equals P3's;
  - the write log holds no write outside the allowed set of
    tools/native/rlayout.py (the render code's, by the writing PC), the
    driver's and its interrupt handler's.

--timing also runs the profiling build (rprof) under a2vm's cost model,
f121 and fastpath (tools/a2vm/README.md, "The cost model"; derived from
the RTL, not measured on the card), and reports the phases: 2 setup and
clears, 3 the BSP walk, 9 the wall calls (here the lockstep stub, a
harness cost), 11 the sprites' place (a stub).

All runs are bounded (a cycle limit, a wall-time limit, a file-size
limit), under nice, at most two at a time, in a temporary directory
under build/ deleted after each run.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from a2vm import costs  # noqa: E402
from bridge import linkmap as blink  # noqa: E402
from native import framestate as FS, levelconv, rcanon, rlayout as R  # noqa: E402
from native import routinecap as RCP, segdesc as SD  # noqa: E402
from ref816 import bounded  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
RENDER = BUILD / 'native' / 'render'
OBJ = RENDER / 'obj'
TABLES = RENDER / 'tables'
A2VM = BUILD / 'a2vm' / 'a2vm'
SOURCE = ROOT / 'src' / 'native'
FILLS = (0xA5, 0x5A)
CYCLE_LIMIT = 400_000_000
RUN_TIMEOUT = 300.0
WRITE_LOG_LIMIT = 2_000_000
MAX_FILE = 256 << 20
DRV_STACK = 0xEF
IRQ_BOUNDS = '0000-01FF,C0A0-C0AF,E000-FFFF'
WRITE_LOG = 'main:0000-00FF,main:0200-FFFF,lc,lc1,aux0-127,cpu:C000-C0FF'
SNAP_RANGES = ('main:0000-03FF,main:0C00-13FF,main:1800-18FF,'
               'aux%d:%04X-%04X,aux%d:%04X-%04X' % (
                   R.LVMAP, R.VAL, R.SECTORS.end - 1, R.SEAM, R.SEAM_HDR,
                   R.SEAM_SOLID - 1))
IO_RENDER = {0xC002, 0xC003, 0xC004, 0xC005, 0xC008, 0xC009, 0xC073}
IO_DRIVER = IO_RENDER | {0xC0AE, 0xC0AF}


class CheckError(Exception):
    pass


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------

class Build(NamedTuple):
    obj: Path
    name: str                   # rtest or rprof
    labels: Dict[str, int]
    segments: Dict[str, Tuple[int, int]]


def make(obj: Path = OBJ, source: Path = SOURCE,
         variables: Sequence[str] = ()) -> None:
    result = bounded.run(['nice', '-n', '10', 'make', '-s', '-C',
                          str(source), '-f', 'render.mk',
                          'OUT=%s' % obj, 'ROOT=%s' % ROOT] +
                         list(variables),
                         timeout=300, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, universal_newlines=True)
    if result.returncode:
        raise CheckError('the build failed:\n' + result.stdout)
    if 'arning' in result.stdout:
        raise CheckError('the build warns:\n' + result.stdout)


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


def code_ranges(b: Build) -> List[Tuple[int, int]]:
    """The render code's PC ranges (inclusive), the driver's and the phase
    loader's excluded."""
    return [b.segments[s] for s in ('RENDERW', 'MATHW', 'MATHLC',
                                    'MATHFAR', 'RFAR') if s in b.segments]


LOADER_WRITES = [('main', 0, 0x6000, R.TXTAB_END),    # the phase loader: W,
                 ('main', 0, R.ZP_FAR[0], R.ZP_FAR[1])]   # its pointer


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
                      ('RFAR', 'far'), ('RLOAD', 'far')):
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
    recs.append((2, 0, 0xC000, bytes(lc)))
    recs.append((3, 0, 0xD000, bytes(lc1)))
    w = (b.obj / ('%s.w' % b.name)).read_bytes()
    wend = b.segments['MATHW'][1]
    if window:
        recs.append((1, R.WCODE_BANK, 0x6000, w[:wend + 1 - 0x6000]))
    else:
        recs.append((0, 0, 0x6000, w[:wend + 1 - 0x6000]))
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


def to_window(recs: Sequence[Tuple[int, int, int, bytes]]
              ) -> List[Tuple[int, int, int, bytes]]:
    """A case's records with its W tables (main $AFC0-$B8FF, from the
    level's wtables.img) moved into the render window's image bank: the
    phase loader brings them in (frame mode)."""
    out = []
    for kind, bank, address, data in recs:
        if kind == 0 and R.FLATCM <= address < R.TXTAB_END:
            if address + len(data) > R.TXTAB_END:
                raise CheckError('a W table record past $%04X'
                                 % R.TXTAB_END)
            out.append((1, R.WCODE_BANK, address, data))
        else:
            out.append((kind, bank, address, data))
    return out


def image_bytes(recs: Sequence[Tuple[int, int, int, bytes]]) -> bytes:
    img = levelconv.Image()
    for kind, bank, address, data in recs:
        img.add(kind, bank, address, data)
    return img.bytes()


class Case(NamedTuple):
    frame: FS.Frame
    level_dir: Path
    level: Dict[str, Any]
    records: List[Tuple[int, int, int, bytes]]
    truth: Dict[str, Any]


def prepare(directory: Path, sym: blink.Symbols) -> Case:
    frame = FS.Frame(directory)
    level_dir = FS.level_of(frame, sym)
    level = json.loads((level_dir / 'level.json').read_text())
    inputs = FS.read_inputs(frame, sym, level)
    recs = []
    for name in ('level.img', 'wtables.img'):
        recs += levelconv.Image.parse((level_dir / name).read_bytes())
    recs += FS.records(frame, inputs, level) + FS.seam_records(frame, sym)
    return Case(frame, level_dir, level, recs, rcanon.reference(frame, sym))


# ---------------------------------------------------------------------------
# A run
# ---------------------------------------------------------------------------

def a2vm_run(b: Build, recs, work: Path, events: Sequence[str],
             extra: Sequence[str], start: str = 'drv_frame',
             cycles: int = CYCLE_LIMIT, timeout: float = RUN_TIMEOUT
             ) -> Dict:
    work.mkdir(parents=True, exist_ok=True)
    (work / 'image.bin').write_bytes(image_bytes(recs))
    rom = work / 'rom.bin'
    rom.write_bytes(bytes(0x4000))
    lab = b.labels
    args = ['nice', '-n', '10', str(A2VM), '--rom', str(rom),
            '--core', 'w65c02s', '--image', str(work / 'image.bin'),
            '--switch', 'lc_read=1', '--switch', 'lc_write=1',
            '--switch', 'lc_bank2=0',
            '--reg', 'pc=%X' % lab[start], '--reg', 's=%X' % DRV_STACK,
            '--reg', 'p=34',
            '--stop-pc', '%X' % lab['drv_halt'],
            '--stop-pc', '%X' % lab['drv_crash'],
            '--cycles', str(cycles),
            '--state', str(work / 'state.json'),
            '--snapshot-dir', str(work)] + list(extra)
    if events:
        (work / 'events.txt').write_text('\n'.join(events) + '\n')
        args += ['--input', str(work / 'events.txt')]
    try:
        result = bounded.run(args, timeout=timeout, max_bytes=MAX_FILE,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True)
    except subprocess.TimeoutExpired:
        raise CheckError('a2vm did not finish in %d s' % timeout)
    state_path = work / 'state.json'
    if not state_path.exists():
        raise CheckError('a2vm failed: %s' % result.stdout[-2000:])
    return json.loads(state_path.read_text())


def snapshot(work: Path, name: str) -> rcanon.Snapshot:
    path = work / (name + '.img')
    if not path.exists():
        raise CheckError('no snapshot %s' % name)
    return rcanon.Snapshot(levelconv.Image.parse(path.read_bytes()))


class Write(NamedTuple):
    pc: int
    address: int
    storage: str
    bank: int
    offset: int


def read_writes(path: Path) -> List[Write]:
    out = []
    with open(str(path)) as handle:
        for line in handle:
            if line.startswith('#'):
                continue
            f = line.split()
            io = f[5] == 'io'
            out.append(Write(int(f[3], 16), int(f[4], 16), f[5],
                             0 if io else int(f[6]),
                             int(f[4], 16) if io else int(f[7], 16)))
    return out


def allowed_sets(b: Build, level: Dict[str, Any], stage_b: bool = False
                 ) -> Dict[str, List]:
    """(storage, bank, start, end) the render code may write, and the
    driver."""
    c = level['counts']
    allowed = R.allowed_writes_b if stage_b else R.allowed_writes
    render = [(s, bank, lo, hi) for s, bank, lo, hi, _ in
              allowed(c['sectors'], c['vertices'])]
    lab = b.labels
    for name in ('axv_rd', 'axt_b2', 'axt_b3', 'ax3_lo', 'ax3_hi',
                 'ax4_b0', 'ax4_b1', 'ax4_b2', 'ax4_b3'):
        render.append(('main', 0, lab[name] + 2, lab[name] + 3))
    render.append(('main', 0, lab['ax_out'], lab['ax_out'] + 4))
    for name in ('mt_far_count', 'mt_far_stride'):
        render.append(('lc1', 0, lab[name] + 1, lab[name] + 2))
    # the vertex gather's entries (far.s: vg_n, then six arrays of VG_MAX
    # to the end of vg_d): the only data of the card's far layer; the rest
    # of $DC00-$DFFF is code, the phase loader's included
    render.append(('lc1', 0, lab['vg_n'], lab['vg_d'] + R.VG_MAX))
    driver = [('aux', R.SEAM, 0, 0x10000),
              ('main', 0, R.SOLIDCOL, R.SOLIDCOL + 160),
              ('main', 0, R.FLOORCLIP, R.FLOORCLIP + 160),
              ('main', 0, R.FRVIS, R.FRVIS + R.VIS_SIZE),
              ('main', 0, 0xD8, 0x100),
              ('main', 0, R.PHASE, R.PHASE + 1),
              ('lc', 0, 0xFFFE, 0x10000),
              ('main', 0, R.FB, R.FB_END),
              ('main', 0, R.NODEF, R.NODEF + 8)]
    if 'RT_SPIN' in lab:
        driver.append(('lc', 0, lab['RT_SPIN'], lab['RT_SPIN'] + 2))
    return {'render': render, 'driver': driver}


def stack_problem(depth: Optional[int]) -> List[str]:
    """The render code's stack below the driver's S, with the IRQ's
    allowance on top, within the render budget (MEMORY_MAP.md 2)?"""
    if depth is None:
        return ['no stack depth measured']
    if depth + R.IRQ_STACK > R.RENDER_STACK:
        return ['stack %d B + %d B for the IRQ over the render budget of '
                '%d B' % (depth, R.IRQ_STACK, R.RENDER_STACK)]
    return []


def stray(writes: Sequence[Write], b: Build, level: Dict[str, Any],
          stage_b: bool = False) -> List[str]:
    sets = allowed_sets(b, level, stage_b)
    code = code_ranges(b)
    drv = [b.segments['DRIVER'], b.segments['DESC']]
    loader = [b.segments['RLOAD']] if 'RLOAD' in b.segments else []

    def inside(w: Write, allowed) -> bool:
        storage = 'main' if w.storage == 'main' else w.storage
        for s, bank, lo, hi in allowed:
            if s == storage and (s != 'aux' or bank == w.bank) and \
                    lo <= w.offset < hi:
                return True
        return False
    out = []
    for w in writes:
        in_code = any(lo <= w.pc <= hi for lo, hi in code)
        in_drv = any(lo <= w.pc <= hi for lo, hi in drv)
        in_loader = any(lo <= w.pc <= hi for lo, hi in loader)
        if w.storage == 'io':
            ok = ((in_code or in_loader) and w.address in IO_RENDER) or \
                (in_drv and w.address in IO_DRIVER)
        elif in_loader:
            ok = inside(w, LOADER_WRITES)
        elif in_code:
            ok = inside(w, sets['render'])
        elif in_drv:
            ok = inside(w, sets['driver'])
        else:
            ok = False
        if not ok:
            out.append('pc $%04X wrote %s %d $%04X' % (
                w.pc, w.storage, w.bank, w.offset))
    return out


def check_frame(case: Case, b: Build, fill: int, base: Sequence,
                keep: Optional[Path] = None) -> Dict[str, Any]:
    work = Path(tempfile.mkdtemp(prefix='tmp-render-check-',
                                 dir=str(BUILD)))
    try:
        lab = b.labels
        events = ['pc %X snapshot bsp' % lab['nr_bsp'],
                  'pc %X snapshot end' % lab['drv_ret']]
        ranges = ','.join('%X-%X' % r for r in code_ranges(b))
        extra = ['--speed', '1', '--snapshot-ranges', SNAP_RANGES,
                 '--irq-bounds', IRQ_BOUNDS, '--lowest-s-in', ranges,
                 '--write-log', WRITE_LOG, '--write-log-file',
                 str(work / 'writes.log'), '--write-log-limit',
                 str(WRITE_LOG_LIMIT)]
        state = a2vm_run(b, list(base) + case.records, work, events, extra)
        problems = []
        if state.get('end') != 'stop-pc' or state.get('pc') != \
                lab['drv_halt']:
            problems.append('the run ended with %s at $%04X' % (
                state.get('end'), state.get('pc', -1)))
            return {'frame': case.frame.name, 'fill': fill,
                    'problems': problems, 'state': state}
        bsp, end = snapshot(work, 'bsp'), snapshot(work, 'end')
        nat = rcanon.native(bsp, end, case.level['counts']['sectors'])
        calls = end.main(0xF2, 1)[0]          # LS_K
        nat['calls'] = rcanon.native_calls(end, calls)
        irqs = int.from_bytes(end.main(0xD8, 2), 'little')
        diffs = rcanon.diff(case.truth, nat)
        problems += diffs
        if irqs == 0:
            problems.append('no interrupt was taken')
        writes = read_writes(work / 'writes.log')
        strays = stray(writes, b, case.level)
        if strays:
            problems.append('%d stray writes: %s' % (len(strays),
                                                     '; '.join(strays[:5])))
        lows = state.get('lowest_s', {})
        low = None
        for r in lows.get('ranges', []):
            if r.get('s') is not None:
                low = r['s'] if low is None else min(low, r['s'])
        if keep is not None:
            shutil.copytree(str(work), str(keep), dirs_exist_ok=True)
        problems += stack_problem(None if low is None else DRV_STACK - low)
        return {'frame': case.frame.name, 'fill': fill,
                'problems': problems, 'walls': len(case.truth['calls']),
                'vtxangle': case.truth['vtxangle'], 'irqs': irqs,
                'writes': len(writes), 'lowest_s': low,
                'stack_bytes': None if low is None else DRV_STACK - low,
                'cycles': state.get('cycles')}
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def timing(case: Case, b: Build, base: Sequence) -> Dict[str, Any]:
    out = {}
    for profile in ('f121', 'fastpath'):
        work = Path(tempfile.mkdtemp(prefix='tmp-render-time-',
                                     dir=str(BUILD)))
        try:
            (work / 'cost.txt').write_text(costs.text(profile))
            report = work / 'cost.json'
            extra = ['--cost', str(work / 'cost.txt'), '--cost-timed',
                     '--cost-phase', '%X' % R.PHASE, '--cost-report',
                     str(report)]
            state = a2vm_run(b, list(base) + case.records, work, [], extra)
            if state.get('pc') != b.labels['drv_halt']:
                raise CheckError('%s: the timing run ended at $%04X' % (
                    case.frame.name, state.get('pc', -1)))
            text = report.read_text()
            cost = json.loads(text[text.rfind('{"final"'):])['cost']
            mhz = costs.parameters(profile)['fabric_mhz']
            out[profile] = {str(k): round(v / (mhz * 1000.0), 3)
                            for k, v in enumerate(cost['phases']) if v}
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    return out


# ---------------------------------------------------------------------------
# Frame mode (stage C, RENDER.md 4.3, 5.3; acceptance 1)
# ---------------------------------------------------------------------------

FRAME_SNAP = ','.join([
    'main:0000-1FFF', 'aux0:%04X-%04X' % (R.OPENLO,
                                          R.OPENLO + R.MAXOPENINGS - 1),
    'aux0:%04X-%04X' % (R.STAGE, R.STAGE_END - 1),
    'aux%d:%04X-%04X' % (R.RENDB, R.DRAWSEGS, R.OPENHI + R.MAXOPENINGS - 1),
    'aux%d:%04X-%04X' % (R.LVMAP, R.VAL, R.SECTORS.end - 1)]
    + ['aux%d:0200-BFFF' % b for b in R.RECSP])
WINDOW_SWITCHES = {0xC003: 'read', 0xC005: 'write', 0xC009: 'altzp',
                   0xC073: 'bank'}


class FullCase(NamedTuple):
    case: Case
    truth: Dict[str, Any]           # rcanon.frame_truth
    slots: Dict[Tuple[int, int], int]
    nlines: int
    sky: frozenset                  # upstream's texel pointers of the sky


def prepare_full(directory: Path, sym: blink.Symbols) -> FullCase:
    case = prepare(directory, sym)
    nlines = case.level['counts']['lines']
    texmap = json.loads((case.level_dir / 'texmap.json').read_text())
    sky = frozenset(v for k, v in texmap['slots'].items()
                    if k.startswith('sky:'))
    return FullCase(case, rcanon.frame_truth(case.frame, sym, nlines),
                    rcanon.slot_map(case.level_dir), nlines, sky)


def entry_diff(truth: Dict[str, Any], nat: Dict[str, Any]) -> List[str]:
    """The comparisons at the walk's entry (checkpoint A's, and stage C's
    stamps and weapon skip): P0b against the native nr_bsp snapshot."""
    out = []
    for key, want in truth['bsp_entry'].items():
        got = nat['bsp_entry'][key]
        if got != want:
            if isinstance(want, list):
                bad = [i for i, (x, y) in enumerate(zip(want, got)) if x != y]
                out.append('bsp_entry %s: %d differ (first %d: native %r, '
                           'reference %r)' % (key, len(bad), bad[0],
                                              got[bad[0]], want[bad[0]]))
            else:
                out.append('bsp_entry %s: native %r, reference %r'
                           % (key, got, want))
    return out


def check_full(fc: FullCase, b: Build, fill: int, base: Sequence,
               keep: Optional[Path] = None,
               collect: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Frame mode: one frame on the whole front end (module docstring).
    collect: a dict that gets the snapshot at the frame's end ('end')."""
    case = fc.case
    work = Path(tempfile.mkdtemp(prefix='tmp-render-frame-',
                                 dir=str(BUILD)))
    try:
        lab = b.labels
        events = ['pc %X snapshot bsp' % lab['nr_bsp'],
                  'pc %X snapshot end' % lab['drv_ret'],
                  'pc %X snapshot crash' % lab['drv_crash']]
        ranges = ','.join('%X-%X' % r for r in code_ranges(b))
        extra = ['--speed', '1', '--snapshot-ranges', FRAME_SNAP,
                 '--irq-bounds', IRQ_BOUNDS, '--lowest-s-in', ranges,
                 '--write-log', WRITE_LOG, '--write-log-file',
                 str(work / 'writes.log'), '--write-log-limit',
                 str(WRITE_LOG_LIMIT)]
        state = a2vm_run(b, list(base) + to_window(case.records), work,
                         events, extra, start='drv_wframe')
        out: Dict[str, Any] = {'frame': case.frame.name, 'fill': fill,
                               'problems': []}
        if state.get('pc') == lab['drv_crash']:
            try:
                status = snapshot(work, 'crash').main(R.FRAME['STATUS'],
                                                      1)[0]
            except CheckError:
                status = None
            out['problems'].append('the frame stopped (BRK), status %s: %s'
                                   % (status, STATUS_NAMES.get(status, '?')))
            return out
        if state.get('end') != 'stop-pc' or state.get('pc') != \
                lab['drv_halt']:
            out['problems'].append('the run ended with %s at $%04X' % (
                state.get('end'), state.get('pc', -1)))
            return out
        bsp, end = snapshot(work, 'bsp'), snapshot(work, 'end')
        if collect is not None:
            collect['end'] = end
        nsec = case.level['counts']['sectors']
        nat_a = rcanon.native(bsp, end, nsec)
        out['problems'] += entry_diff(case.truth, nat_a)
        try:
            nat = rcanon.frame_native(end, fc.slots, nsec, fc.nlines)
        except rcanon.CanonError as e:      # a record naming no slot
            out['problems'].append('the native outputs: %s' % e)
            return out
        if 'vtxangle' not in fc.truth:      # a synthetic frame: no count
            del nat['vtxangle']
        out['problems'] += rcanon.diff_frame(fc.truth, nat)
        irqs = int.from_bytes(end.main(0xD8, 2), 'little')
        if irqs == 0:
            out['problems'].append('no interrupt was taken')
        writes = read_writes(work / 'writes.log')
        strays = stray(writes, b, case.level, stage_b=True)
        if strays:
            out['problems'].append('%d stray writes: %s' % (
                len(strays), '; '.join(strays[:5])))
        code = code_ranges(b) + [b.segments['RLOAD']]
        windows = {k: 0 for k in WINDOW_SWITCHES.values()}
        for w in writes:
            if w.storage == 'io' and w.address in WINDOW_SWITCHES and \
                    any(lo <= w.pc <= hi for lo, hi in code):
                windows[WINDOW_SWITCHES[w.address]] += 1
        low = None
        for r in state.get('lowest_s', {}).get('ranges', []):
            if r.get('s') is not None:
                low = r['s'] if low is None else min(low, r['s'])
        F = R.FRAME
        stg_bank = end.main(F['STG_BANK'], 1)[0]
        stg_ptr = int.from_bytes(end.main(F['STG_PTR'], 2), 'little')
        staged = len(rcanon.staged_bytes(end, stg_bank, stg_ptr))
        out.update({'walls': len(case.truth['calls']),
                    'records': sum(len(v) for v in
                                   fc.truth['records'].values()),
                    'drawsegs': fc.truth['dscount'],
                    'sky': sum(1 for v in fc.truth['records'].values()
                               for r in v if r[0] == 'tex' and
                               r[7] in fc.sky),
                    'vtxangle': fc.truth.get('vtxangle'), 'irqs': irqs,
                    'writes': len(writes), 'windows': windows,
                    'staged': staged,
                    'stack_bytes': None if low is None else DRV_STACK - low,
                    'cycles': state.get('cycles')})
        out['problems'] += stack_problem(out['stack_bytes'])
        return out
    finally:
        if keep is not None:
            shutil.copytree(str(work), str(keep), dirs_exist_ok=True)
        shutil.rmtree(str(work), ignore_errors=True)


PHASES = {1: 'window', 2: 'setup', 3: 'walk', 9: 'walls', 10: 'segs',
          11: 'sprites', 0: 'driver'}


def timing_full(fc: FullCase, b: Build, base: Sequence) -> Dict[str, Any]:
    """Frame mode under the cost model (the profiling build rwprof), f121
    and fastpath (derived from the RTL, not measured on the card): by
    phase, ms, 65C02 cycles and soft-switch accesses."""
    out: Dict[str, Any] = {}
    for profile in ('f121', 'fastpath'):
        work = Path(tempfile.mkdtemp(prefix='tmp-render-ftime-',
                                     dir=str(BUILD)))
        try:
            (work / 'cost.txt').write_text(costs.text(profile))
            report = work / 'cost.json'
            extra = ['--cost', str(work / 'cost.txt'), '--cost-timed',
                     '--cost-phase', '%X' % R.PHASE, '--cost-report',
                     str(report)]
            state = a2vm_run(b, list(base) + to_window(fc.case.records),
                             work, [], extra, start='drv_wframe')
            if state.get('pc') != b.labels['drv_halt']:
                raise CheckError('%s: the timing run ended at $%04X' % (
                    fc.case.frame.name, state.get('pc', -1)))
            text = report.read_text()
            cost = json.loads(text[text.rfind('{"final"'):])['cost']
            mhz = costs.parameters(profile)['fabric_mhz']
            res = {}
            for k, name in PHASES.items():
                res[name] = {'ms': round(cost['phases'][k] /
                                         (mhz * 1000.0), 4),
                             'cycles': cost['phase_cycles'][k],
                             'io': cost['phase_io'][k]}
            front = sum(res[n]['ms'] for n in ('setup', 'walk', 'walls',
                                               'segs', 'sprites'))
            res['front_ms'] = round(front, 4)
            res['total_ms'] = round(sum(cost['phases']) /
                                    (mhz * 1000.0), 4)
            res['irqs'] = state.get('irqs', 0)
            out[profile] = res
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    return out


# ---------------------------------------------------------------------------
# Routine mode (stage B, RENDER.md 4.3; acceptance 2)
# ---------------------------------------------------------------------------

ROUTINES = RENDER / 'routines'
ROUTINE_SNAP = ','.join([
    'main:0000-1FFF', 'main:B900-BFFF', 'aux0:%04X-%04X' % (
        R.OPENLO, R.OPENLO + R.MAXOPENINGS - 1),
    'aux0:%04X-%04X' % (R.STAGE, R.STAGE_END - 1),
    'aux%d:%04X-%04X' % (R.RENDB, R.DRAWSEGS, R.OPENHI + R.MAXOPENINGS - 1)]
    + ['aux%d:0200-BFFF' % b for b in R.RECSP])
VBL = 17030                     # cycles a VBL at --speed 1
STATUS_NAMES = {R.ST_DEPTH: 'the node frames are full',
                R.ST_RECORDS: 'the staging is full',
                R.ST_TEXTURE: 'a texture without slots'}


class Routine(NamedTuple):
    name: str                   # FRAME/wKK
    kind: str                   # 'wall' or 'seg'
    records: List[Tuple[int, int, int, bytes]]
    truth: Dict[str, Any]
    info: Dict[str, Any]
    slots: Dict[Tuple[int, int], int]
    lnmap: bytes
    level: Dict[str, Any]


def routine_cases(names: Optional[str] = None) -> List[Path]:
    paths = sorted(ROUTINES.glob('*/w*.case.z')) if ROUTINES.exists() \
        else []
    if names:
        wanted = set(names.split(','))
        paths = [p for p in paths if '%s/%s' % (
            p.parent.name, p.name.split('.')[0]) in wanted]
    return paths


def case_name(path: Path) -> str:
    return '%s/%s' % (path.parent.name, path.name.split('.')[0])


SEGVAR = {2, 4, 5, 6, 7, 8, 10, 12, 13, 14, 15, 20, 28}


def loop_of(case: RCP.Case) -> Optional[str]:
    """The loop upstream's R_RenderSegLoop takes for the case's seg (from
    its entry's WPAGE, r_seg65.s:466-495): vNN, genLoop, vMask, or
    segDone (nothing to draw)."""
    sle = case.points.get('SLE')
    if sle is None:
        return None

    def w(o: int) -> int:
        return int.from_bytes(sle.get(0x000A00 + o, 2), 'little')
    mc, mf, mid, top, bot, masked = (w(0xC0), w(0xC2), w(0xC6), w(0xC8),
                                     w(0xCA), w(0xCC))
    if masked:
        return 'genLoop' if (mc or mf or top or bot) else 'vMask'
    k = (8 if mf else 0) + (4 if mc else 0)
    k += 16 if mid else (2 if bot else 0) + (1 if top else 0)
    if k == 0:
        return 'segDone'
    return 'v%02d' % k if k in SEGVAR else 'genLoop'


_PATHS: Dict[Tuple[str, int], List[str]] = {}


def paths_of(case: RCP.Case) -> List[str]:
    """The paths of the coverage report the case takes: upstream's
    (routinecap.PATHS, from the survey's call log) for a captured call,
    the spec's name for a synthetic one."""
    if case.header.get('synthetic'):
        return ['synth:' + case.header['synthetic']]
    if not _PATHS:
        for w in walls_index():
            _PATHS[(w['frame'], w['k'])] = sorted(w['paths'])
    return _PATHS.get((case.header['frame'], case.header['k']), [])


def prepare_routine(path: Path, kind: str, sym: blink.Symbols) -> Routine:
    case = RCP.load_case(path)
    built = SD.wall_state(case, sym) if kind == 'wall' else \
        SD.seg_state(case, sym)
    info = dict(built.info)
    frame = SD.frame_of(case)
    p0, p3 = frame.dump('p0'), frame.dump('p3')
    info['segs'] = p0.u(sym.address('_g_segs'), 3)
    if kind == 'wall':
        lines = p3.u(sym.address('_g_lines'), 3)
        flags = p3.u(lines + rcanon.SIZEOF_LINE * info['line'] +
                     rcanon.OFS_LINE_R_FLAGS, 2)
        info['mapped_p3'] = bool(flags & rcanon.ML_MAPPED)
    level_dir = levelconv.LEVELS / info['level']
    level = json.loads((level_dir / 'level.json').read_text())
    lnmap = b''
    for k, bank, address, data in built.records:
        if k == 0 and address == R.LNMAP:
            lnmap = data
    if kind == 'wall':
        line = info['line']
        info['mapped_in'] = bool(lnmap[line >> 3] & (1 << (line & 7)))
    truth = rcanon.ref_routine(case, kind, sym, info)
    info['loop'] = loop_of(case)
    info['paths'] = paths_of(case)
    recs = list(built.records)
    for k, bank, address, data in levelconv.Image.parse(
            (level_dir / 'level.img').read_bytes()) + \
            levelconv.Image.parse((level_dir / 'wtables.img').read_bytes()):
        recs.insert(0, (k, bank, address, data))
    return Routine(case_name(path), kind, recs, truth, info,
                   rcanon.slot_map(level_dir), lnmap, level)


def check_routine(rt: Routine, b: Build, fill: int, base: Sequence,
                  keep: Optional[Path] = None) -> Dict[str, Any]:
    work = Path(tempfile.mkdtemp(prefix='tmp-render-rout-',
                                 dir=str(BUILD)))
    try:
        lab = b.labels
        # where the VBL falls inside the routine: spread over the cases
        into = 100 + (sum(rt.name.encode()) * 97 + len(rt.kind)) % 4000
        spin = max(0, (VBL - 400 - into) // 16)
        drv = [(2, 0, lab['RT_SPIN'], spin.to_bytes(2, 'little'))]
        if rt.kind == 'wall':
            drv.append((2, 0, lab['RT_A'], bytes([rt.info['start'],
                                                  rt.info['stop']])))
        events = ['pc %X snapshot end' % lab['drv_ret'],
                  'pc %X snapshot crash' % lab['drv_crash']]
        ranges = ','.join('%X-%X' % r for r in code_ranges(b))
        extra = ['--speed', '1', '--snapshot-ranges', ROUTINE_SNAP,
                 '--irq-bounds', IRQ_BOUNDS, '--lowest-s-in', ranges,
                 '--write-log', WRITE_LOG, '--write-log-file',
                 str(work / 'writes.log'), '--write-log-limit',
                 str(WRITE_LOG_LIMIT)]
        state = a2vm_run(b, list(base) + rt.records + drv, work, events,
                         extra, start='drv_wall' if rt.kind == 'wall'
                         else 'drv_seg', cycles=40_000_000)
        out = {'case': rt.name, 'kind': rt.kind, 'fill': fill,
               'problems': []}
        end_pc = state.get('pc')
        if end_pc == lab['drv_crash']:
            try:
                status = snapshot(work, 'crash').main(
                    R.FRAME['STATUS'], 1)[0]
            except CheckError:
                status = None
            out['problems'].append('the routine stopped (BRK), status %s: '
                                   '%s' % (status, STATUS_NAMES.get(
                                       status, '?')))
            return out
        if state.get('end') != 'stop-pc' or end_pc != lab['drv_halt']:
            out['problems'].append('the run ended with %s at $%04X' % (
                state.get('end'), end_pc or -1))
            return out
        end = snapshot(work, 'end')
        status = end.main(R.FRAME['STATUS'], 1)[0]
        if status:
            out['problems'].append('status %d: %s' % (
                status, STATUS_NAMES.get(status, '?')))
            return out
        nat = rcanon.native_routine(end, rt.kind, rt.info, rt.slots,
                                    rt.lnmap)
        rules = end.main(R.FRAME['RULES'], 1)[0]
        out['rules'] = rules
        if rules:
            out['problems'].append(rcanon.rules_problem(rules))
        ruled = RULED.get(spec_of(rt.name) or '', {}).get(rt.kind)
        out['problems'] += rcanon.diff_routine(rt.truth, nat)
        irqs = int.from_bytes(end.main(0xD8, 2), 'little')
        writes = read_writes(work / 'writes.log')
        strays = stray(writes, b, rt.level, stage_b=True)
        if strays:
            out['problems'].append('%d stray writes: %s' % (
                len(strays), '; '.join(strays[:5])))
        if ruled is not None:           # its own comparison, stray writes
            out['ruled'] = ruled_diff(rt, nat, ruled[1]) + (  # included
                [out['problems'][-1]] if strays else [])
        low = None
        for r in state.get('lowest_s', {}).get('ranges', []):
            if r.get('s') is not None:
                low = r['s'] if low is None else min(low, r['s'])
        out.update({'loop': rt.info.get('loop'),
                    'paths': rt.info.get('paths', []),
                    'irqs': irqs, 'writes': len(writes),
                    'stack_bytes': None if low is None else DRV_STACK - low,
                    'cycles': state.get('cycles'),
                    'records': sum(len(v) for v in
                                   rt.truth['records'].values())})
        deep = stack_problem(out['stack_bytes'])
        out['problems'] += deep
        if 'ruled' in out:
            out['ruled'] += deep
        if keep is not None:
            shutil.copytree(str(work), str(keep), dirs_exist_ok=True)
        return out
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


CHECKPOINT = 1000               # RENDER.md 5.2: 1,000 calls of each
# synthetic cases where upstream leaves its tables (routinesynth.py: a
# wall with its first, last or every column seen from behind) and the
# native code takes a rule of our own instead (RENDER.md 3.9): by kind,
# the rules the call must take and the end of the wall they apply at. Not
# in the checkpoint; ruled_diff checks them against upstream wherever
# upstream stays in its tables (tests/test_native_render_walls.py too).
RULED = {
    'negsine': {'wall': (R.RULE_SINE, 'both')},
    'grazefirst': {'wall': (R.RULE_SINE | R.RULE_TANGENT, 'first'),
                   'seg': (R.RULE_TANGENT, 'first')},
    'grazelast': {'wall': (R.RULE_SINE | R.RULE_TANGENT, 'last'),
                  'seg': (R.RULE_TANGENT, 'last')},
}
RULE_SCALE = 256                # RULE_SINE's scale
RULE_SPAN = 8                   # the columns a texture u span interpolates


def spec_of(name: str) -> Optional[str]:
    """The synthetic spec of a case name (synth-SPEC/w00), else None."""
    head = name.split('/')[0]
    return head[len('synth-'):] if head.startswith('synth-') else None


def ruled_diff(rt: 'Routine', nat: Dict[str, Any], end: str) -> List[str]:
    """A ruled call against upstream where upstream stays in its tables
    (empty when equal). A wall: its drawseg, every field upstream's but
    the scale of a ruled end, RULE_SCALE, and the step between the two
    (scaleSlow's, truncated as C), rw_scalestep the same; the rest of the
    wall follows from those scales. A seg loop (upstream's scales): every
    output upstream's, the records of the columns within RULE_SPAN of the
    ruled end left out (their texture u is interpolated from the ruled
    column's)."""
    ref = rt.truth
    if rt.kind == 'wall':
        tr, ds = ref.get('drawseg'), nat.get('drawseg')
        if not tr or not ds:
            return ['no drawseg: native %r, reference %r' % (ds, tr)]
        want = dict(tr)
        if end in ('first', 'both'):
            want['scale1'] = RULE_SCALE
        if end in ('last', 'both'):
            want['scale2'] = RULE_SCALE
        out = []
        if 'scalestep' in tr:
            n = want['scale2'] - want['scale1']
            q = abs(n) // (tr['x2'] - tr['x1'])
            want['scalestep'] = (q if n >= 0 else -q) & 0xFFFFFFFF
            if nat.get('rw_step') != want['scalestep']:
                out.append('rw_step %r, the rule\'s %d' % (
                    nat.get('rw_step'), want['scalestep']))
        bad = sorted(k for k in set(want) | set(ds)
                     if want.get(k) != ds.get(k))
        if bad:
            out.append('drawseg: %s: native %s, by the rule %s' % (
                ','.join(bad), [ds.get(k) for k in bad],
                [want.get(k) for k in bad]))
        return out
    x, stopx = rt.info['x'], rt.info['stopx']
    col = x if end == 'first' else stopx - 1

    def far(recs: Dict) -> Dict:
        return {c: v for c, v in (recs or {}).items()
                if abs(int(c) - col) >= RULE_SPAN}
    kept = far(ref.get('records'))
    if not kept:
        return ['no column farther than %d from the ruled one' % RULE_SPAN]
    return rcanon.diff_routine(dict(ref, records=kept),
                               dict(nat, records=far(nat.get('records'))))


def ruled_ok(spec: str, r: Dict[str, Any]) -> List[str]:
    """What is wrong with a run of a RULED case (empty when right): it
    ran to its end, took exactly its rules, and ruled_diff found nothing."""
    want = RULED.get(spec, {}).get(r.get('kind'))
    if want is None:
        return ['not a ruled case']
    if r.get('rules') != want[0]:
        return ['rules %s, not %d: %s' % (r.get('rules'), want[0],
                                          '; '.join(r['problems'][:3]))]
    if r.get('ruled') is None:
        return ['not compared']
    return list(r['ruled'])


def walls_index() -> List[Dict[str, Any]]:
    """Every captured wall call, in the runs' order, with its paths
    (routinecap.py's index)."""
    index = json.loads((ROUTINES / 'index.json').read_text())
    out = []
    for run in ('newgame', 'm5demo', 'title', 'tour', 'lights'):
        for w in index.get(run, {}).get('walls', []):
            out.append(w)
    return out


def checkpoint_cases() -> Tuple[List[Path], Dict[str, Any]]:
    """The checkpoint's cases (RENDER.md 4.1, 5.2): CHECKPOINT wall calls
    chosen evenly over the captured frames' calls that draw no sky (stage
    B's choice, kept); every call that draws a sky (stage B deferred them,
    stage C closes them); for each path of the coverage report they miss,
    the first call that takes it; every synthetic case
    (routinesynth.py)."""
    walls = walls_index()
    for w in walls:                     # the loop too, as a path
        case = RCP.load_case(ROUTINES / w['frame'] / ('w%02d.case.z'
                                                      % w['k']))
        w['paths'] = dict(w['paths'], **{'loop:%s' % loop_of(case): 1})
    plain = [i for i, w in enumerate(walls) if 'skyColumn' not in
             w['paths']]
    sky = [i for i, w in enumerate(walls) if 'skyColumn' in w['paths']]
    if len(plain) < CHECKPOINT:
        raise CheckError('%d captured calls without a sky, not %d'
                         % (len(plain), CHECKPOINT))
    n = len(plain)
    chosen = sorted({plain[round(i * (n - 1) / (CHECKPOINT - 1))]
                     for i in range(CHECKPOINT)})
    have = set()
    for i in chosen:
        have |= set(walls[i]['paths'])
    added = {}
    for i in plain:
        for key in walls[i]['paths']:
            if key not in have:
                have.add(key)
                added[key] = i
                chosen.append(i)
    chosen = sorted(set(chosen) | set(sky))
    paths = [ROUTINES / walls[i]['frame'] / ('w%02d.case.z' % walls[i]['k'])
             for i in chosen]
    synth = sorted(p for p in ROUTINES.glob('synth-*/w*.case.z')
                   if p.parent.name[len('synth-'):] not in RULED)
    paths += synth
    return paths, {'captured': len(walls), 'chosen': len(chosen),
                   'with_sky': len(sky),
                   'synthetic': [p.parent.name for p in synth],
                   'added_for': {k: '%s/w%02d' % (walls[i]['frame'],
                                                  walls[i]['k'])
                                 for k, i in added.items()}}


def routines_main(args) -> int:
    sym = blink.Symbols()
    b = load_build(args.obj, 'rwall')
    fills = [int(f, 16) for f in args.fills.split(',')]
    bases = {f: base_records(b, f) for f in fills}
    kinds = args.kinds.split(',')
    extra = {}
    if args.cases:
        paths = routine_cases(args.cases)
    elif args.routines == 'all':
        paths = routine_cases()
    else:
        paths, extra = checkpoint_cases()
    if not paths:
        print('no routine cases: run python3 tools/native/routinecap.py',
              file=sys.stderr)
        return 1
    results = []

    def one(path: Path) -> List[Dict[str, Any]]:
        out = []
        for kind in kinds:
            try:
                loaded = RCP.load_case(path)
                if kind == 'wall' and 'SWE' not in loaded.points:
                    continue            # a synthetic case of a seg loop
                if kind == 'seg' and 'SLE' not in loaded.points:
                    continue            # a wall that returns early
                rt = prepare_routine(path, kind, sym)
            except (SD.StateError, FS.FrameError, levelconv.ConvError,
                    rcanon.CanonError, RCP.CaptureError) as e:
                out.append({'case': case_name(path), 'kind': kind,
                            'problems': ['prepare: %s' % e]})
                continue
            for f in fills:
                try:
                    out.append(check_routine(rt, b, f, bases[f],
                                             args.keep and args.keep / (
                                                 '%s-%s-%s-%02X' % (
                                                     path.parent.name,
                                                     path.stem, kind, f))))
                except CheckError as e:
                    out.append({'case': rt.name, 'kind': kind, 'fill': f,
                                'problems': [str(e)]})
        return out
    counts = {k: {'equal': 0, 'failed': 0, 'ruled': 0} for k in kinds}
    irq_cases = 0
    with ThreadPoolExecutor(max(1, min(2, args.jobs))) as pool:
        for rs in pool.map(one, paths):
            for r in rs:
                results.append(r)
                k = r['kind']
                spec = r['case'].split('/')[0][len('synth-'):]
                if k in RULED.get(spec, {}):
                    wrong = ruled_ok(spec, r)
                    if not wrong:
                        counts[k]['ruled'] += 1
                        continue
                    r['problems'] = wrong + r['problems']
                if r['problems']:
                    counts[k]['failed'] += 1
                    status = 'DIFFERS'
                else:
                    counts[k]['equal'] += 1
                    status = 'equal'
                irq_cases += bool(r.get('irqs'))
                if r['problems'] or getattr(args, 'verbose', False):
                    print('%-16s %-4s %s: %s' % (
                        r['case'], k, '%02X' % r['fill'] if 'fill' in r
                        else '--', status), flush=True)
                    for p in r['problems'][:6]:
                        print('    ' + p)
    nruns = len(results)
    per_call = {k: {kk: v // max(1, len(fills)) for kk, v in c.items()}
                for k, c in counts.items()}
    loops: Dict[str, int] = {}
    covered: Dict[str, int] = {}
    for r in results:
        if r['problems'] or r.get('fill') != fills[0]:
            continue
        if r.get('loop') and r['kind'] == 'seg':
            loops[r['loop']] = loops.get(r['loop'], 0) + 1
        if r['kind'] == 'wall':
            for p in r.get('paths', []):
                covered[p] = covered.get(p, 0) + 1
    print('seg loop calls equal, by loop: %s' % json.dumps(
        dict(sorted(loops.items()))))
    print('wall calls equal, by path: %s' % json.dumps(
        dict(sorted(covered.items()))))
    print('%d cases, %d runs; by call (both fills): %s; runs with an '
          'interrupt inside: %d' % (len(paths), nruns, json.dumps(per_call),
                                    irq_cases))
    if extra:
        print('checkpoint: %d calls chosen of %d captured; added for paths: '
              '%s' % (extra['chosen'], extra['captured'],
                      json.dumps(extra['added_for'])))
    if args.json:
        args.json.write_text(json.dumps({'results': results, 'counts':
                                         counts, 'selection': extra,
                                         'loops': loops, 'paths': covered},
                                        indent=1) + '\n')
    failed = sum(c['failed'] for c in counts.values())
    return 1 if failed or not irq_cases else 0


def routine_timing(rt: Routine, b: Build, base: Sequence
                   ) -> Dict[str, Any]:
    """A wall case under a2vm's cost model (the profiling build rwprof):
    ms of phase 9 (wall setup) and 10 (the seg loop), f121 and fastpath
    (derived from the RTL, not measured on the card). Each case starts
    with the model's caches cold."""
    out: Dict[str, Any] = {}
    lab = b.labels
    drv = [(2, 0, lab['RT_SPIN'], (0).to_bytes(2, 'little')),
           (2, 0, lab['RT_A'], bytes([rt.info['start'], rt.info['stop']])),
           (0, 0, R.PHASE, b'\0')]
    for profile in ('f121', 'fastpath'):
        work = Path(tempfile.mkdtemp(prefix='tmp-render-rtime-',
                                     dir=str(BUILD)))
        try:
            (work / 'cost.txt').write_text(costs.text(profile))
            report = work / 'cost.json'
            extra = ['--speed', '1', '--cost', str(work / 'cost.txt'),
                     '--cost-phase', '%X' % R.PHASE, '--cost-report',
                     str(report)]
            state = a2vm_run(b, list(base) + rt.records + drv, work, [],
                             extra, start='drv_wall', cycles=40_000_000)
            if state.get('pc') != lab['drv_halt']:
                raise CheckError('%s: the timing run ended at $%04X'
                                 % (rt.name, state.get('pc', -1)))
            text = report.read_text()
            cost = json.loads(text[text.rfind('{"final"'):])['cost']
            mhz = costs.parameters(profile)['fabric_mhz']
            ph = cost['phases']
            out[profile] = {'wall': ph[9] / (mhz * 1000.0),
                            'seg': ph[10] / (mhz * 1000.0)}
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    return out


def timing_main(args) -> int:
    """--routine-timing: wall setup and seg loops of each captured frame
    of the sets, summed over its wall calls (routine mode's cases, each
    verified by --routines)."""
    sym = blink.Symbols()
    b = load_build(args.obj, 'rwprof')
    base = base_records(b, 0xA5)
    walls = walls_index()
    sets = args.sets.split(',') if args.sets else None
    groups = {'m5': ('still', 'demo', 'e1m3')}
    prefixes = []
    for k in sets or ():
        prefixes += groups.get(k, (k,))
    frames: Dict[str, List[Dict[str, Any]]] = {}
    for w in walls:
        if prefixes and w['frame'].rsplit('-', 1)[0] not in prefixes:
            continue
        frames.setdefault(w['frame'], []).append(w)

    def one(item):
        name, ws = item
        total = {'f121': {'wall': 0.0, 'seg': 0.0},
                 'fastpath': {'wall': 0.0, 'seg': 0.0}}
        for w in ws:
            path = ROUTINES / w['frame'] / ('w%02d.case.z' % w['k'])
            rt = prepare_routine(path, 'wall', sym)
            t = routine_timing(rt, b, base)
            for prof in total:
                for k in total[prof]:
                    total[prof][k] += t[prof][k]
        return name, len(ws), total
    results = []
    with ThreadPoolExecutor(max(1, min(2, args.jobs))) as pool:
        for name, n, total in pool.map(one, sorted(frames.items())):
            results.append({'frame': name, 'walls': n, 'ms': total})
            print('%-12s %3d walls: wall setup %.2f ms, seg loops %.2f ms '
                  '(f121); %.2f, %.2f (fastpath)' % (
                      name, n, total['f121']['wall'], total['f121']['seg'],
                      total['fastpath']['wall'], total['fastpath']['seg']),
                  flush=True)
    if args.json:
        args.json.write_text(json.dumps(results, indent=1) + '\n')
    return 0


def frame_main(args) -> int:
    """--frame-mode (acceptance 1), and with --timing the report."""
    dirs = frame_dirs(args.frames, args.sets)
    if not dirs:
        print('no frames: run python3 tools/native/rendercap.py',
              file=sys.stderr)
        return 1
    sym = blink.Symbols()
    b = load_build(args.obj, 'rwall')
    fills = [int(f, 16) for f in args.fills.split(',')]
    bases = {f: base_records(b, f, window=True) for f in fills}
    prof = load_build(args.obj, 'rwprof') if args.timing else None
    pbase = base_records(prof, 0xA5, window=True) if prof else None
    results = []

    def one(d: Path) -> List[Dict[str, Any]]:
        try:
            fc = prepare_full(d, sym)
        except (FS.FrameError, levelconv.ConvError, rcanon.CanonError,
                CheckError) as e:
            return [{'frame': d.name, 'problems': ['prepare: %s' % e]}]
        out = []
        for f in fills:
            try:
                out.append(check_full(fc, b, f, bases[f], args.keep and
                                      args.keep / ('%s-%02X' % (d.name, f))))
            except CheckError as e:
                out.append({'frame': d.name, 'fill': f,
                            'problems': [str(e)]})
        if prof is not None:
            try:
                out[0]['timing'] = timing_full(fc, prof, pbase)
            except CheckError as e:
                out[0]['problems'].append(str(e))
        return out
    failed = 0
    with ThreadPoolExecutor(max(1, min(2, args.jobs))) as pool:
        for rs in pool.map(one, dirs):
            for r in rs:
                results.append(r)
                ok = not r['problems']
                failed += not ok
                line = '%-12s %s: %s' % (
                    r['frame'], '%02X' % r['fill'] if 'fill' in r else '--',
                    'equal' if ok else 'DIFFERS')
                if 'records' in r:
                    line += (' (%d walls, %d records, %d sky, %d drawsegs, '
                             '%s angles, %d irqs, %d writes, stack %s, %d B '
                             'staged)' % (r['walls'], r['records'], r['sky'],
                                          r['drawsegs'],
                                          '-' if r['vtxangle'] is None
                                          else r['vtxangle'],
                                          r['irqs'], r['writes'],
                                          r['stack_bytes'], r['staged']))
                if 'timing' in r:
                    t = r['timing']['f121']
                    line += ' f121 ms: ' + ', '.join(
                        '%s %.2f' % (k, t[k]['ms']) for k in
                        ('window', 'setup', 'walk', 'walls', 'segs'))
                print(line, flush=True)
                for p in r['problems'][:8]:
                    print('    ' + p)
    frames = len({r['frame'] for r in results})
    print('%d frames, %d runs, %d failed' % (frames, len(results), failed))
    if args.json:
        args.json.write_text(json.dumps(results, indent=1) + '\n')
    if args.report and prof is not None:
        args.report.write_text(timing_report(results))
        print('report: %s' % args.report)
    return 1 if failed else 0


# The estimates the report sets the measures beside (RENDER.md 4.4, from
# docs/research/native-memory.md 7 on NATIVE.md 1.2's inputs): F1.2.1 ms,
# still and demo; and upstream's 65816 cycles (PROFILE.md)
ESTIMATES = {'setup': ((0.2, 0.5), (0.2, 0.5), 10641, 11472),
             'window': ((5.0, 7.1), (6.0, 8.5), None, None),
             'walk': ((3.4, 7.1), (0.8, 1.6), 99575, 23056),
             'walls': ((4.0, 8.7), (0.7, 1.5), 115381, 21364),
             'segs': ((7.4, 14.8), (3.1, 6.2), 367549, 143498)}
SET_ORDER = ('still', 'demo', 'e1m3', 'newgame', 'title', 'tour', 'lights')


def _median(values: List[float]) -> float:
    v = sorted(values)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def _counts(values: List[float]) -> str:
    """Median (range) of counts."""
    return '%g (%g-%g)' % (_median(values), min(values), max(values))


def timing_report(results: List[Dict[str, Any]]) -> str:
    """The markdown report of frame mode's timing (RENDER.md 4.4)."""
    timed = [r for r in results if 'timing' in r]
    by_set: Dict[str, List[Dict[str, Any]]] = {}
    for r in timed:
        by_set.setdefault(r['frame'].rsplit('-', 1)[0], []).append(r)
    runs = {(r['frame']): r for r in results
            if r.get('fill') == 0xA5 and 'staged' in r}
    lines = ['# The native front end: time by phase (a2vm, not the card)', '',
             'Generated by `python3 tools/native/render_check.py '
             '--frame-mode --timing --report ...` (milestone 7, stage C; '
             'docs/RENDER.md 4.4). Each frame of acceptance 1 on the '
             'profiling build `rwprof` from its `R_FillStamps` to '
             '`drawMasked`, under a2vm\'s cost model on its own clock '
             '(`--cost-timed`): `f121` is F1.2.1 as it is, `fastpath` the '
             'firmware design without the zero-page pair. The model is '
             'derived from the RTL; milestone 0 has not measured it on the '
             'card. ms, median (range) over the set\'s frames.', '',
             'Phases: 1 the render window load (the phase loader, '
             '`far_wload`), 2 frame setup (`R_FillStamps`, setup, clears, '
             'the weapon skip; the seam\'s copy of the clip pass included), '
             '3 the BSP walk, 9 wall setup, 10 seg loops (with the fills, '
             'the sky and the records), 11 the sprites\' place (a stub). '
             '"Front end" is 2 + 3 + 9 + 10 + 11.', '']
    names = [('window', 'Window load'), ('setup', 'Setup'),
             ('walk', 'BSP walk'), ('walls', 'Wall setup'),
             ('segs', 'Seg loops')]

    def cell(values: List[float]) -> str:
        if not values:
            return ''
        return '%.2f (%.2f-%.2f)' % (_median(values), min(values),
                                     max(values))
    for profile in ('f121', 'fastpath'):
        lines += ['## %s, ms a frame' % profile, '',
                  '| Set | Frames | ' + ' | '.join(n for _, n in names) +
                  ' | Front end | All |',
                  '| --- | ---: |' + ' ---: |' * (len(names) + 2)]
        for s in SET_ORDER:
            rs = by_set.get(s)
            if not rs:
                continue
            row = [s, str(len(rs))]
            for key, _ in names:
                row.append(cell([r['timing'][profile][key]['ms']
                                 for r in rs]))
            row.append(cell([r['timing'][profile]['front_ms'] for r in rs]))
            row.append(cell([r['timing'][profile]['total_ms'] for r in rs]))
            lines.append('| ' + ' | '.join(row) + ' |')
        lines.append('')
    irqs = [r['timing']['f121']['irqs'] for r in timed]
    if irqs:
        # ms a cycle of fast-memory code: the setup phase's
        per = _median([r['timing']['f121']['setup']['ms'] /
                       r['timing']['f121']['setup']['cycles'] for r in timed])
        lines += ['The VBL interrupt of the harness (the mouse card\'s, on '
                  'the model\'s clock) came %d to %d times in a timed frame; '
                  'its stub handler (`drv_irq`, about 40 cycles with the '
                  'entry) counts in the phase it interrupts: at most about '
                  '%.3f ms a frame (at the setup phase\'s %.1f ns a cycle).'
                  % (min(irqs), max(irqs), max(irqs) * 40 * per,
                     per * 1e6), '']
    lines += ['## 65C02 cycles and soft-switch accesses a frame (f121)', '',
              'Median over the set. Soft-switch accesses are a2vm\'s '
              '`io_accesses` of the phase (reads and writes of `$C0xx`, '
              'the `$C08x` reads of the aux card\'s bank 2 among them).', '',
              '| Set | ' + ' | '.join('%s cycles | %s switches' % (n, n)
                                    for _, n in names) + ' |',
              '| --- |' + ' ---: | ---: |' * len(names)]
    for s in SET_ORDER:
        rs = by_set.get(s)
        if not rs:
            continue
        row = [s]
        for key, _ in names:
            row.append('%d' % _median([r['timing']['f121'][key]['cycles']
                                       for r in rs]))
            row.append('%d' % _median([r['timing']['f121'][key]['io']
                                       for r in rs]))
        lines.append('| ' + ' | '.join(row) + ' |')
    lines += ['', '## Windows, records, stack (the correctness runs)', '',
              'Far windows a frame by the soft switch that opens them '
              '(RAMRD on `$C003`, RAMWRT on `$C005`, ALTZP on `$C009`) and '
              'the `$C073` writes, by the render code and the phase '
              'loader; the bytes staged (records with their column byte); '
              'the stack below the driver\'s S. Median (range).', '',
              '| Set | Read windows | Write windows | Aux-card windows | '
              '`$C073` writes | Bytes staged | Stack |',
              '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for s in SET_ORDER:
        rs = [runs[r['frame']] for r in by_set.get(s, [])
              if r['frame'] in runs]
        if not rs:
            continue
        row = [s]
        for key in ('read', 'write', 'altzp', 'bank'):
            row.append(_counts([r['windows'][key] for r in rs]))
        row.append(_counts([r['staged'] for r in rs]))
        row.append(_counts([r['stack_bytes'] for r in rs]))
        lines.append('| ' + ' | '.join(row) + ' |')
    lines += ['', '## Against the estimates (F1.2.1)', '',
              'RENDER.md 4.4\'s estimates (from docs/research/'
              'native-memory.md 7, on NATIVE.md 1.2\'s inputs) for standing '
              'still in E1M1 and the title demo, beside the medians of '
              '`still` and `title` (demo3 in E1M7; the estimate\'s demo '
              'column is labelled E1M3 there). The "Design + pair" '
              'estimates are milestone 13\'s build and are not compared '
              'with `fastpath`. Upstream\'s 65816 cycles are PROFILE.md\'s '
              '(an ideal 65816).', '',
              '| Phase | 65816 cycles still / demo | Estimate still | '
              'Measured `still` | Estimate demo | Measured `title` | '
              '65C02 cycles `still` / `title` |',
              '| --- | --- | --- | ---: | --- | ---: | --- |']
    for key, name in names:
        est = ESTIMATES[key]
        st = [r['timing']['f121'][key] for r in by_set.get('still', [])]
        ti = [r['timing']['f121'][key] for r in by_set.get('title', [])]
        lines.append('| %s | %s | %.1f-%.1f | %s | %.1f-%.1f | %s | %s |' % (
            name, '%s / %s' % (est[2], est[3]) if est[2] else '',
            est[0][0], est[0][1], cell([x['ms'] for x in st]),
            est[1][0], est[1][1], cell([x['ms'] for x in ti]),
            '%d / %d' % (_median([x['cycles'] for x in st]) if st else 0,
                         _median([x['cycles'] for x in ti]) if ti else 0)))
    lines.append('')
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Sizes
# ---------------------------------------------------------------------------

BUDGETS = {                     # RENDER.md 3.8 (stage A's parts)
    'rframe.o': ('RENDERW', 500),
    'rbsp.o+rlight.o': ('RENDERW', 3400),
    'auxlc.o': ('RENDERW', 200),
    'math-r.o': ('MATHW', 1700),
}
BUDGETS_B = dict(BUDGETS, **{   # and stage B's and C's (the rwall build)
    'rwall.o': ('RENDERW', 5500),
    'rseg.o+rrec.o': ('RENDERW', 3800),
    'segloops.o': ('RENDERW', 2860),
    # stage C: rsky.s, nr_fillstamps and nr_wskip 900 (RENDER.md 3.8) on
    # top of the frame driver's 500
    'rframe.o+rsky.o': ('RENDERW', 500 + 900),
})
W_BUDGET_AB = 500 + 3400 + 200 + 1700 + 5500 + 3800 + 2860 + 750
CARD_BUDGET = 850               # far.s in card bank 1 (RENDER.md 3.8)


def module_sizes(obj: Path = OBJ, name: str = 'rtest') -> Dict[str, Dict]:
    text = (obj / (name + '.map')).read_text()
    part = text.split('Modules list:', 1)[1].split('Segment list:', 1)[0]
    out: Dict[str, Dict[str, int]] = {}
    module = None
    for line in part.splitlines():
        m = re.match(r'^(\S+\.o):$', line.strip())
        if m:
            module = m.group(1)
            continue
        m = re.match(r'^\s+(\w+)\s+Offs=\w+\s+Size=(\w+)', line)
        if m and module:
            out.setdefault(module, {})[m.group(1)] = int(m.group(2), 16)
    return out


def print_sizes() -> int:
    for name, budgets in (('rtest', BUDGETS), ('rwall', BUDGETS_B)):
        print('build %s:' % name)
        print_sizes_of(name, budgets)
    return 0


def print_sizes_of(name: str, budgets: Dict[str, Tuple[str, int]]) -> int:
    b = load_build(OBJ, name)
    mods = module_sizes(OBJ, name)
    print('area                         used      of   left')
    for name, (lo, hi) in sorted(b.segments.items(), key=lambda x: x[1]):
        print('%-10s $%04X-$%04X %6d' % (name, lo, hi, hi - lo + 1))
    w_used = b.segments['MATHW'][1] + 1 - 0x6000
    print('W code $6000-$AFBF: %d of %d bytes, %d left' % (
        w_used, R.WCODE_END - R.WCODE, R.WCODE_END - R.WCODE - w_used))
    card = max(b.segments[s][1] for s in ('RFAR', 'RLOAD')
               if s in b.segments) + 1 - 0xDC00
    print('card bank 1 $DC00-$DFFF: %d of 1024 bytes (MATHFAR and far.s)'
          % card)
    for key, (seg, budget) in budgets.items():
        used = sum(mods.get(m, {}).get(seg, 0) for m in key.split('+'))
        print('%-18s %5d of %5d budgeted (RENDER.md 3.8)' % (key, used,
                                                               budget))
    far = sum(mods['far.o'].values())
    print('far.o %d of %d (RENDER.md 3.4, 3.8: far layer 500, vertex gather '
          '100, FSTEP gather 250; the phase loader %d)'
          % (far, CARD_BUDGET, mods['far.o'].get('RLOAD', 0)))
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def is_synthetic(d: Path) -> bool:
    """A frame of tools/native/framesynth.py: no call log (checkpoint A
    cannot run on it)."""
    return 'synthetic' in json.loads((d / 'frame.json').read_text())


def frame_dirs(names: Optional[str], sets: Optional[str]) -> List[Path]:
    root = RENDER / 'frames'
    dirs = sorted(p for p in root.iterdir() if (p / 'frame.json').exists()) \
        if root.exists() else []
    if names:
        wanted = names.split(',')
        dirs = [root / n for n in wanted]
    if sets:
        keep = sets.split(',')
        groups = {'m5': ('still', 'demo', 'e1m3')}
        prefixes = []
        for k in keep:
            prefixes += groups.get(k, (k,))
        dirs = [d for d in dirs if d.name.rsplit('-', 1)[0] in prefixes]
    return dirs


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames')
    parser.add_argument('--sets')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--fills', default='a5,5a')
    parser.add_argument('--timing', action='store_true')
    parser.add_argument('--obj', type=Path, default=OBJ)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--json', type=Path)
    parser.add_argument('--keep', type=Path)
    parser.add_argument('--sizes', action='store_true')
    parser.add_argument('--routines', choices=('checkpoint', 'all'),
                        help='routine mode (acceptance 2): the checkpoint\'s '
                        'cases, or every captured call')
    parser.add_argument('--cases', help='routine mode: FRAME/wKK,...')
    parser.add_argument('--kinds', default='wall,seg')
    parser.add_argument('--routine-timing', action='store_true',
                        help='wall setup and seg loops a frame, summed over '
                        'its wall calls (--sets to choose the frames)')
    parser.add_argument('--frame-mode', action='store_true',
                        help='frame mode (acceptance 1): the whole front '
                        'end on each frame; with --timing, the phases')
    parser.add_argument('--report', type=Path,
                        help='frame mode with --timing: write the timing '
                        'report (markdown) here')
    args = parser.parse_args(argv)
    if not args.no_build:
        make(args.obj, args.source)
    if args.sizes:
        return print_sizes()
    if not A2VM.exists():
        print('%s is missing: make -C tools/a2vm' % A2VM, file=sys.stderr)
        return 1
    if args.routine_timing:
        return timing_main(args)
    if args.routines or args.cases:
        return routines_main(args)
    if args.frame_mode:
        return frame_main(args)
    dirs = [d for d in frame_dirs(args.frames, args.sets)
            if not is_synthetic(d)]         # (checkpoint A: the call logs)
    if not dirs:
        print('no frames: run python3 tools/native/rendercap.py',
              file=sys.stderr)
        return 1
    sym = blink.Symbols()
    b = load_build(args.obj)
    fills = [int(f, 16) for f in args.fills.split(',')]
    bases = {f: base_records(b, f) for f in fills}
    results = []
    failed = 0

    def one(d: Path) -> List[Dict[str, Any]]:
        try:
            case = prepare(d, sym)
        except (FS.FrameError, levelconv.ConvError, rcanon.CanonError) as e:
            return [{'frame': d.name, 'problems': ['prepare: %s' % e]}]
        out = []
        for f in fills:
            try:
                out.append(check_frame(case, b, f, bases[f], args.keep and
                                       args.keep / ('%s-%02X' % (d.name, f))))
            except CheckError as e:
                out.append({'frame': d.name, 'fill': f,
                            'problems': [str(e)]})
        if args.timing:
            prof = load_build(args.obj, 'rprof')
            out[0]['timing'] = timing(case, prof, base_records(prof, 0xA5))
        return out
    with ThreadPoolExecutor(max(1, min(2, args.jobs))) as pool:
        for rs in pool.map(one, dirs):
            for r in rs:
                results.append(r)
                ok = not r['problems']
                failed += not ok
                line = '%-12s %s: %s' % (
                    r['frame'], '%02X' % r['fill'] if 'fill' in r else '--',
                    'equal' if ok else 'DIFFERS')
                if 'walls' in r:
                    line += ' (%d walls, %d angles, %d irqs, %d writes, ' \
                        'stack %s)' % (r['walls'], r['vtxangle'], r['irqs'],
                                       r['writes'], r['stack_bytes'])
                if 'timing' in r:
                    line += ' ms ' + json.dumps(r['timing'])
                print(line, flush=True)
                for p in r['problems'][:6]:
                    print('    ' + p)
    frames = len({r['frame'] for r in results})
    print('%d frames, %d runs, %d failed' % (frames, len(results), failed))
    if args.json:
        args.json.write_text(json.dumps(results, indent=1) + '\n')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
