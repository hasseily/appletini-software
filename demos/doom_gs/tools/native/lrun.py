#!/usr/bin/env python3
"""The level load on a2vm (milestone 9, stage B; docs/LEVELS.md 5.4,
6.2): the build of src/native/level.mk, the image runs of its test
driver, what a run left read back, and the game layout's window read
back into the harness layout of levelconv.py (format render-level 3).

Usage:  python3 tools/native/lrun.py --sizes
        python3 tools/native/lrun.py --maps 1,7 [--fill a5] [--profile f121]

An image run (`run`): the machine after the boot (the store's bank files
lstore.py wrote, in their banks; the card: the math's tables and code,
the far layer and the phase loader; the load phase's image in bank LCODE
at W's addresses; the persistent globals main $0300-$03EF 0, as the boot
leaves them), every other byte poisoned ($A5 or $5A, as milestones 5-8);
the driver (src/native/ldriver.s) turns the mouse card's VBL interrupt
on, loads the image into W with the phase loader and runs nl_load for
each map of its list, under a2vm's memory API (--amem). Each load ends
at drv_loaded, where a range snapshot takes the level window, main, aux
0's FUZZDARK and the shared stores (SNAP_RANGES); a write log takes every
CPU write but the stack page's; --lowest-s-in measures the load's stack.
`whole_run` is the same sequence with one whole-machine snapshot at the
end instead: every byte it changed must be one the loads may change (the
memory API's copies are not CPU writes, so the write log cannot see
them).

`SnapMachine` is a snapshot read as lstore.HostMachine is (main, aux by
bank), so lstore.compare_window, lstore.readback and level_check.
manifest_check take it.

`harness_level` reads a loaded machine back into a level directory of
levelconv.py's format for a given level directory's layout (its
level.json, texmap.json, patchmap.json): every byte from the machine,
translated where the two layouts differ (each slot and stored lump from
its game place to its harness place by the slot's key and the lump's
number, the patch indexes from global to the level's, TXBANK, TXLO,
TXHI to the harness's blocks; a texture the level does not hold, as one
of the map's textures made only in play, has TXBANK, TXLO, TXHI and TXWM
0, as levelconv.py writes them).

Every run is bounded (cycles, time, file sizes), under nice, in a
directory under build/ deleted after it.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from a2vm import costs  # noqa: E402
from native import levelconv as LC, llayout as LL, lstore, \
    render_check as RC, rlayout as R  # noqa: E402
from ref816 import bounded  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
LEVELS = BUILD / 'native' / 'levels'
OBJ = LEVELS / 'obj'
SOURCE = ROOT / 'src' / 'native'
A2VM = BUILD / 'a2vm' / 'a2vm'
FILLS = (0xA5, 0x5A)
DRV_STACK = 0xEF
CYCLE_LIMIT = 2_000_000_000
RUN_TIMEOUT = 900.0
MAX_FILE = 64 << 20
WRITE_LOG_LIMIT = 4_000_000
# the soft switches the load writes at every far access (not logged: two
# to four a call); every other I/O write is
IO_QUIET = (0xC002, 0xC005, 0xC073)
IRQ_BOUNDS = '0000-01FF,C0A0-C0AF,E000-FFFF'
# what a load's snapshot takes: main, aux 0's FUZZDARK, the level window,
# the per-level tables, the shared stores
WINDOW_BANKS = (R.LVSEG, R.LVMAP, R.SPRT, R.WPRO, LL.LVG0, LL.LVG1,
                LL.LVG2, LL.LVC, R.WCODE_BANK, R.MCODE_BANK)
SNAP_RANGES = ','.join(
    ['main', 'aux0:0800-08FF'] +
    ['aux%d:0200-BFFF' % b for b in WINDOW_BANKS + LL.TEX_BANKS +
     LL.SPR_BANKS])
# stage C: the setup's state too (RTH, the mobjs' game parts, the
# specials, the sector nodes)
GAME_BANKS = (R.RTH,) + LL.MOBJ_BANKS + (LL.ZONE0, LL.ZONE1, LL.GTAB)
SNAP_RANGES_SETUP = SNAP_RANGES + ',' + ','.join(
    'aux%d:0200-BFFF' % b for b in GAME_BANKS)
# the cost phases of the profiling build (lload.s): 2 x n in PHASE
PHASES = {1: 'image', 2: 'variants', 3: 'copies', 4: 'lines', 5: 'group',
          6: 'flood', 7: 'cmaps', 8: 'private', 9: 'spawn', 10: 'specials',
          11: 'setup', 0: 'driver'}
# the size budgets of docs/LEVELS.md 4.4 (stages B and C)
BUDGETS = {'lload': 1200, 'lgeom': 2000, 'lsetup': 500,
           'gspawn+gweap': 2200, 'gpos': 2200, 'gthink+gvalid': 700,
           'gspec': 900}
IO_LOAD = {0xC002, 0xC003, 0xC004, 0xC005, 0xC073, 0xCFF0, 0xCFF1, 0xCFF2,
           0xCFFF}
IO_DRIVER = {0xC006, 0xC0AE, 0xC0AF}


class RunError(Exception):
    pass


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------

def make(obj: Path = OBJ, source: Path = SOURCE) -> None:
    result = bounded.run(['nice', '-n', '10', 'make', '-s', '-C',
                          str(source), '-f', 'level.mk', 'OUT=%s' % obj,
                          'ROOT=%s' % ROOT],
                         timeout=300, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, universal_newlines=True)
    if result.returncode:
        raise RunError('the build failed:\n' + result.stdout)
    if 'arning' in result.stdout:
        raise RunError('the build warns:\n' + result.stdout)


def load_build(obj: Path = OBJ, name: str = 'ltest') -> RC.Build:
    return RC.load_build(obj, name)


def module_sizes(b: RC.Build) -> Dict[str, int]:
    """Each object's bytes in LOADW (the link map's module list)."""
    text = (b.obj / (b.name + '.map')).read_text()
    out: Dict[str, int] = {}
    module = None
    text = text.split('Modules list:', 1)[-1].split('Segment list:', 1)[0]
    for line in text.splitlines():
        if line and not line.startswith(' ') and line.endswith('.o:'):
            module = Path(line[:-1]).stem
            continue
        f = line.split()
        if module and f and f[0] == 'LOADW':
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            key = module.split('-')[0]
            out[key] = out.get(key, 0) + size
    return out


# ---------------------------------------------------------------------------
# The image
# ---------------------------------------------------------------------------

def store_files() -> List[Path]:
    meta = json.loads((lstore.STORE / 'store.json').read_text())
    return [lstore.STORE / n for n in sorted(meta['files'])]


def store_records() -> List[Tuple[int, int, int, bytes]]:
    out = []
    for path in store_files():
        for bank, address, data in lstore.read_bank_file(path.read_bytes()):
            out.append((1, bank, address, data))
    return out


def card_records(b: RC.Build, fill: int) -> List[Tuple[int, int, int,
                                                         bytes]]:
    """The main card: bank 1 $D000-$DFFF (the quarter squares, the math's
    products, the far layer, the phase loader), $C000-$FFFF (the driver
    or the runner)."""
    lc = bytearray([fill]) * 0x4000
    lc1 = bytearray([fill]) * 0x1000
    squares = (RC.TABLES / 'math' / 'squares.bin').read_bytes()
    lc1[0:len(squares)] = squares
    for seg, part, base in (('MATHLC', 'lc1', 0xD800),
                            ('MATHFAR', 'far', 0xDC00),
                            ('RFAR', 'far', 0xDC00),
                            ('RLOAD', 'far', 0xDC00)):
        start, end = b.segments[seg]
        data = (b.obj / ('%s.%s' % (b.name, part))).read_bytes()
        lc1[start - 0xD000:end + 1 - 0xD000] = data[start - base:
                                                    end + 1 - base]
    start, end = b.segments['DRIVER']
    data = (b.obj / ('%s.lce' % b.name)).read_bytes()
    lc[start - 0xC000:end + 1 - 0xC000] = data[:end + 1 - start]
    if 'VECTORS' in b.segments:
        data = (b.obj / ('%s.vec' % b.name)).read_bytes()
        lc[0xFFFA - 0xC000:0x10000 - 0xC000] = data
    return [(2, 0, 0xC000, bytes(lc)), (3, 0, 0xD000, bytes(lc1))]


def load_image(b: RC.Build) -> List[Tuple[int, int, int, bytes]]:
    """The load phase's image in bank LCODE at W's addresses: MATHW and
    AUXW from $6000, LOADW from $6600."""
    w = (b.obj / ('%s.w' % b.name)).read_bytes()
    lw = (b.obj / ('%s.lw' % b.name)).read_bytes()
    start, end = b.segments['LOADW']
    if start != LL.LW_CODE or end >= LL.LW_CODE_END:
        raise RunError('LOADW at $%04X-$%04X' % (start, end))
    return [(1, LL.LCODE, 0x6000, w), (1, LL.LCODE, LL.LW_CODE, lw)]


def base_records(b: RC.Build, fill: int) -> List[Tuple[int, int, int,
                                                         bytes]]:
    pattern = bytes([fill]) * 0x10000
    recs = [(0, 0, 0x0000, pattern[:0xC000])]
    for bank in range(128):
        recs.append((1, bank, 0, pattern))
    recs += card_records(b, fill)
    recs += store_records()
    recs += load_image(b)
    recs.append((0, 0, 0x0300, bytes(0xF0)))    # the persistent globals
    return recs


def map_list(b: RC.Build, maps: Sequence[int],
             pre: Optional[Sequence[int]] = None) -> Tuple[int, int, int,
                                                           bytes]:
    """The driver's list: the maps, and for each its test pre-state's
    index (stage C: nl_setup) or $FF (nl_load alone)."""
    if not 1 <= len(maps) <= LL.DL_MAX:
        raise RunError('%d maps in a run' % len(maps))
    lab = b.labels
    if lab['dl_maps'] != lab['dl_n'] + 1 or \
            lab['dl_pre'] != lab['dl_maps'] + LL.DL_MAX:
        raise RunError('the driver\'s lists are not after its count')
    pre = list(pre) if pre is not None else [0xFF] * len(maps)
    if len(pre) != len(maps) or any(not (0 <= k < LL.PRE_MAX or k == 0xFF)
                                    for k in pre):
        raise RunError('the pre-states %r' % pre)
    return (2, 0, lab['dl_n'], bytes([len(maps)]) + bytes(maps) +
            bytes(LL.DL_MAX - len(maps)) + bytes(pre))


# ---------------------------------------------------------------------------
# A run
# ---------------------------------------------------------------------------

class Run(NamedTuple):
    state: Dict[str, Any]
    work: Path
    labels: Dict[str, int]

    def ended(self) -> str:
        lab = self.labels
        if self.state.get('end') == 'stop-pc':
            if self.state.get('pc') == lab['drv_halt']:
                return 'halt'
            if self.state.get('pc') == lab['drv_crash']:
                return 'crash'
        return '%s at $%04X' % (self.state.get('end'),
                                self.state.get('pc', -1))


def code_ranges(b: RC.Build) -> List[Tuple[int, int]]:
    """The load's code (W and the far layer it calls)."""
    return [b.segments[s] for s in ('LOADW', 'RFAR', 'MATHW', 'AUXW')
            if s in b.segments]


def complement(spans: Sequence[Tuple[int, int]], lo: int = 0,
               end: int = 0x10000) -> List[Tuple[int, int]]:
    """The inclusive ranges of lo .. end - 1 outside the half-open spans."""
    out, at = [], lo
    for start, stop in sorted(spans):
        if start > at:
            out.append((at, min(start, end) - 1))
        at = max(at, stop)
    if at < end:
        out.append((at, end - 1))
    return [r for r in out if r[0] <= r[1]]


def write_log_ranges(b: RC.Build, maps: Sequence[int],
                     setup: bool = False) -> str:
    """a2vm --write-log ranges: everything but the stack page and what
    the loads and the driver may write in bulk (the load's zero page, its
    W, LVG0's lines, LVG1's tables, LVC's colormaps), so the log stays
    small; LVMAP, the card and every other bank are logged whole, and the
    I/O writes but the far layer's soft switches. A logged write is then
    checked by its PC (stray)."""
    from native import lstore
    meta = json.loads((lstore.STORE / 'store.json').read_text())
    main, aux = [(0x0100, 0x0200), (0xC000, 0x10000)], {}
    for m in set(maps):
        h = meta['maps']['E1M%d' % m]['header']
        allowed = LL.allowed_writes_setup(h) if setup else \
            LL.allowed_writes_load(h['counts'], h['lvg1'])
        for s, bank, lo, hi, _ in allowed:
            if s == 'main':
                main.append((lo, hi))
            elif bank not in (R.LVMAP, LL.LVG0):
                aux.setdefault(bank, []).append((lo, hi))
            elif not setup and bank == LL.LVG0:
                aux.setdefault(bank, []).append((lo, hi))
    main += [(0xD8, 0xDA), (R.PHASE, R.PHASE + 1), (0x6000, LL.LW_REQ)]
    items = ['main:%04X-%04X' % r for r in complement(main)]
    for bank in range(128):
        if bank in aux:
            items += ['aux%d:%04X-%04X' % ((bank,) + r)
                      for r in complement(aux[bank])]
        else:
            items.append('aux%d' % bank)
    items += ['lc', 'lc1']
    io = [(a, a + 1) for a in IO_QUIET] + [(0xC003, 0xC005)]
    items += ['cpu:%04X-%04X' % r for r in complement(io, 0xC000, 0xC100)]
    items.append('cpu:C800-CFFF')
    if len(items) > 256:
        raise RunError('%d write-log ranges' % len(items))
    return ','.join(items)


def pre_records(prestates: Sequence[bytes]) -> List[Tuple[int, int, int,
                                                          bytes]]:
    """The test pre-states (stage C) in bank PRE_BANK, PRE_RECORD apart."""
    if len(prestates) > LL.PRE_MAX:
        raise RunError('%d pre-states' % len(prestates))
    out = []
    for k, data in enumerate(prestates):
        if len(data) > LL.PRE_RECORD:
            raise RunError('a pre-state of %d bytes' % len(data))
        out.append((1, LL.PRE_BANK, LL.ROOM[0] + LL.PRE_RECORD * k,
                    bytes(data)))
    return out


def run(b: RC.Build, maps: Sequence[int], fill: int, work: Path,
        snapshots: bool = True, whole: bool = False,
        profile: Optional[str] = None, write_log: bool = True,
        extra_records: Sequence = (), pre: Optional[Sequence[int]] = None,
        prestates: Sequence[bytes] = (), setup: bool = False,
        headers: Optional[Sequence[Dict[str, Any]]] = None) -> Run:
    """One image run of the driver over `maps`. snapshots: a range
    snapshot load-000K after each load; whole: one whole-machine snapshot
    at the end (`end.ram`). Stage C: `prestates` into PRE_BANK and `pre`
    each map's (nl_setup), `setup` the snapshot's and the write log's
    ranges of the game state (`headers`: each map's store header)."""
    work.mkdir(parents=True, exist_ok=True)
    recs = base_records(b, fill) + [map_list(b, maps, pre)] + \
        pre_records(prestates) + list(extra_records)
    (work / 'image.bin').write_bytes(RC.image_bytes(recs))
    (work / 'rom.bin').write_bytes(bytes(0x4000))
    lab = b.labels
    args = ['nice', '-n', '10', str(A2VM), '--rom', str(work / 'rom.bin'),
            '--core', 'w65c02s', '--amem', '--image', str(work / 'image.bin'),
            '--switch', 'lc_read=1', '--switch', 'lc_write=1',
            '--switch', 'lc_bank2=0',
            '--reg', 'pc=%X' % lab['drv_level'], '--reg', 's=%X' % DRV_STACK,
            '--reg', 'p=34',
            '--stop-pc', '%X' % lab['drv_halt'],
            '--stop-pc', '%X' % lab['drv_crash'],
            '--cycles', str(CYCLE_LIMIT),
            '--speed', '1',
            '--irq-bounds', IRQ_BOUNDS,
            '--lowest-s-in', ','.join('%X-%X' % r for r in code_ranges(b)),
            '--state', str(work / 'state.json'),
            '--snapshot-dir', str(work)]
    events = []
    if snapshots:
        events.append('pc %X@* snapshot load' % lab['drv_loaded'])
        events.append('pc %X snapshot crash' % lab['drv_crash'])
        args += ['--snapshot-ranges', SNAP_RANGES_SETUP if setup else
                 SNAP_RANGES, '--every-limit', str(len(maps) + 1)]
    if whole:
        args += ['--final-snapshot']
    if events:
        (work / 'events.txt').write_text('\n'.join(events) + '\n')
        args += ['--input', str(work / 'events.txt')]
    if write_log:
        args += ['--write-log', write_log_ranges(b, maps, setup),
                 '--write-log-file',
                 str(work / 'writes.log'), '--write-log-limit',
                 str(WRITE_LOG_LIMIT)]
    if profile:
        (work / 'cost.txt').write_text(costs.text(profile))
        args += ['--cost', str(work / 'cost.txt'), '--cost-timed',
                 '--cost-phase', '%X' % R.PHASE,
                 '--cost-report', str(work / 'cost.json')]
    try:
        result = bounded.run(args, timeout=RUN_TIMEOUT, max_bytes=MAX_FILE,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True)
    except subprocess.TimeoutExpired:
        raise RunError('a2vm did not finish in %d s' % RUN_TIMEOUT)
    state_path = work / 'state.json'
    if not state_path.exists():
        raise RunError('a2vm failed: %s' % result.stdout[-2000:])
    return Run(json.loads(state_path.read_text()), work, lab)


def status_of(r: Run) -> Optional[int]:
    """LV_STATUS at a stop (the crash snapshot)."""
    p = r.work / 'crash.img'
    if not p.exists():
        return None
    m = SnapMachine.from_image(p)
    return m.main[LL.LV_STATUS]


STATUS_NAMES = {v: k for k, v in LL.LS.items()}


# ---------------------------------------------------------------------------
# A snapshot as a machine
# ---------------------------------------------------------------------------

class SnapMachine:
    """A snapshot read as lstore.HostMachine is: `main` (64 KB) and `aux`
    (bank -> 64 KB); the banks the snapshot does not hold are absent."""

    def __init__(self):
        self.main = bytearray(0x10000)
        self.aux: Dict[int, bytearray] = {}
        self.held: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}

    @classmethod
    def from_image(cls, path: Path) -> 'SnapMachine':
        m = cls()
        for kind, bank, address, data in LC.Image.parse(path.read_bytes()):
            if kind == 0:
                m.main[address:address + len(data)] = data
            elif kind == 1:
                m.aux.setdefault(bank, bytearray(0x10000))[
                    address:address + len(data)] = data
            else:
                continue
            m.held.setdefault((kind, bank), []).append(
                (address, address + len(data)))
        return m

    @classmethod
    def from_ram(cls, path: Path) -> 'SnapMachine':
        ram = path.read_bytes()
        m = cls()
        m.main[:] = ram[0:0x10000]
        for bank in range(128):
            at = 0x15000 + bank * 0x10000
            m.aux[bank] = bytearray(ram[at:at + 0x10000])
        m.card = ram[0x10000:0x15000]
        return m

    def read(self, bank: int, address: int, n: int) -> bytes:
        if bank not in self.aux:
            raise RunError('the snapshot does not hold bank %d' % bank)
        return bytes(self.aux[bank][address:address + n])


def load_snapshots(work: Path) -> List[Path]:
    return sorted(work.glob('load-*.img'))


# ---------------------------------------------------------------------------
# Stray writes
# ---------------------------------------------------------------------------

def allowed_cpu(b: RC.Build, loads: Sequence[Dict[str, Any]],
                setup: bool = False
                ) -> Dict[str, List[Tuple[str, int, int, int]]]:
    """The CPU writes the load's code may make (llayout.allowed_writes_load
    of every map loaded; with setup, allowed_writes_setup) and the
    driver's."""
    load = []
    for h in loads:
        allowed = LL.allowed_writes_setup(h) if setup else \
            LL.allowed_writes_load(h['counts'], h['lvg1'])
        for s, bank, lo, hi, _ in allowed:
            load.append((s, bank, lo, hi))
    lab = b.labels
    desc = b.segments['DESC']
    driver = [('main', 0, 0xD8, 0x100), ('main', 0, R.PHASE, R.PHASE + 1),
              ('lc', 0, 0xFFFE, 0x10000),
              ('lc', 0, desc[0], desc[1] + 1)]
    if setup:                   # the pre-states' copies (drv_pre)
        driver += [('main', 0, R.ZP_FAR[0], R.ZP_FAR[1]),
                   ('main', 0, LL.GBLOCK, LL.GBLOCK_END),
                   ('main', 0, LL.PRND, LL.MRND + 1)]
    del lab
    return {'load': load, 'driver': driver}


def stray(writes: Sequence[RC.Write], b: RC.Build,
          loads: Sequence[Dict[str, Any]], setup: bool = False) -> List[str]:
    sets = allowed_cpu(b, loads, setup)
    code = code_ranges(b)
    drv = [b.segments['DRIVER']]
    loader = [b.segments['RLOAD']]

    def inside(w, allowed) -> bool:
        return any(s == w.storage and (s != 'aux' or bank == w.bank) and
                   lo <= w.offset < hi for s, bank, lo, hi in allowed)
    out = []
    for w in writes:
        in_code = any(lo <= w.pc <= hi for lo, hi in code)
        in_drv = any(lo <= w.pc <= hi for lo, hi in drv)
        in_loader = any(lo <= w.pc <= hi for lo, hi in loader)
        if w.storage == 'io':
            ok = (in_code and w.address in IO_LOAD) or \
                (in_loader and w.address in IO_LOAD) or \
                (in_drv and w.address in IO_DRIVER | IO_LOAD)
        elif in_loader:
            ok = inside(w, [('main', 0, 0x6000, LL.LW_CODE_END)] +
                        [('main', 0, R.ZP_FAR[0], R.ZP_FAR[1])])
        elif in_code:
            ok = inside(w, sets['load'])
        elif in_drv:
            ok = inside(w, sets['driver'])
        else:
            ok = False
        if not ok:
            out.append('pc $%04X wrote %s %d $%04X' % (
                w.pc, w.storage, w.bank, w.offset))
    return out


def split_by_load(writes: Sequence[RC.Write], b: RC.Build, n: int
                  ) -> List[List[RC.Write]]:
    """The write log cut at the end of each of the run's n loads (the
    driver's `inc dl_k` at drv_loaded): n parts, one a load (the driver's
    writes before it included), then the driver's writes after the last."""
    pc, at = b.labels['drv_loaded'], b.labels['dl_k']
    parts: List[List[RC.Write]] = [[]]
    for w in writes:
        parts[-1].append(w)
        if w.pc == pc and w.storage == 'lc' and w.offset == at:
            parts.append([])
    if len(parts) != n + 1:
        raise RunError('the write log holds %d ends of loads, not %d'
                       % (len(parts) - 1, n))
    return parts


def stray_by_load(writes: Sequence[RC.Write], b: RC.Build,
                  loads: Sequence[Dict[str, Any]], setup: bool = False
                  ) -> List[str]:
    """stray() for each load of the run against its own map's places only
    (loads: each load's map header, in the run's order), so a write by one
    map's load into a place only another map of the run uses shows; the
    writes after the last load against the driver's alone."""
    parts = split_by_load(writes, b, len(loads))
    out = []
    for k, part in enumerate(parts):
        own = [loads[k]] if k < len(loads) else []
        out += ['load %d: %s' % (k + 1, s) if k < len(loads) else
                'after the loads: %s' % s
                for s in stray(part, b, own, setup)]
    return out


def image_bytes_at(recs, kind: int, bank: int, size: int) -> bytearray:
    """The initial contents of one storage from the image's records."""
    out = bytearray(size)
    for k, bk, address, data in recs:
        if k == kind and (kind != 1 or bk == bank):
            base = 0xC000 if kind == 2 else 0xD000 if kind == 3 else 0
            out[address - base:address - base + len(data)] = data
    return out


def changed_outside(b: RC.Build, fill: int, maps: Sequence[int],
                    end: SnapMachine, allowed_dma: Dict[int, set],
                    allowed_main: set, limit: int = 8) -> Tuple[int,
                                                                List[str]]:
    """The bytes of main and every aux bank the whole run changed outside
    what the loads may leave (the maps' window.img and the scratch):
    (count, the first few)."""
    recs = base_records(b, fill) + [map_list(b, maps)]
    count, shown = 0, []
    before = image_bytes_at(recs, 0, 0, 0x10000)
    for a in range(0x10000):
        if before[a] != end.main[a] and a not in allowed_main and \
                not 0x0100 <= a < 0x0200:
            count += 1
            if len(shown) < limit:
                shown.append('main $%04X' % a)
    for bank in range(128):
        before = image_bytes_at(recs, 1, bank, 0x10000)
        after = end.aux[bank]
        if before == after:
            continue
        ok = allowed_dma.get(bank, set())
        for a in range(0x10000):
            if before[a] != after[a] and a not in ok:
                count += 1
                if len(shown) < limit:
                    shown.append('aux %d $%04X' % (bank, a))
    return count, shown


# ---------------------------------------------------------------------------
# The harness layout read back (docs/LEVELS.md 5.4, 6.2)
# ---------------------------------------------------------------------------

def harness_level(mach, gamemap: int, target: Path,
                  out: Optional[Path] = None) -> Dict[str, Any]:
    """The loaded machine `mach` (map `gamemap`) read back into the
    harness layout of the level directory `target` (levelconv.py's or
    wadconv.py's): returns {'level.img': records, 'wtables.img': records,
    'mtables.img': records, 'fuzzdark.bin': bytes} and, with `out`, writes
    them with target's level.json, texmap.json and patchmap.json (and
    sectors-sides.json) into `out`."""
    info = json.loads((target / 'level.json').read_text())
    if info['gamemap'] != gamemap:
        raise RunError('%s is E1M%d, not E1M%d' % (target, info['gamemap'],
                                                    gamemap))
    tslots = json.loads((target / 'texmap.json').read_text())['slots']
    gd = lstore.STORE / ('e1m%d' % gamemap)
    gslots = json.loads((gd / 'texmap.json').read_text())['slots']
    gpm = {e[4]: e for e in json.loads(
        (gd / 'patchmap.json').read_text())['entries']}
    recs = LC.Image.parse((target / 'level.img').read_bytes())
    banks = LC.Banks()
    want: Dict[int, set] = {}
    for kind, bank, address, data in recs:
        if kind != 1:
            raise RunError('level.img holds a record of kind %d' % kind)
        want.setdefault(bank, set()).update(range(address,
                                                  address + len(data)))
    got: Dict[int, set] = {}

    def put(bank: int, address: int, data: bytes) -> None:
        banks.put(bank, address, data)
        got.setdefault(bank, set()).update(range(address,
                                                 address + len(data)))
    # LVSEG, LVMAP: the same records at the same places
    for kind, bank, address, data in recs:
        if bank in (R.LVSEG, R.LVMAP):
            put(bank, address, mach.read(bank, address, len(data)))
    # the texel slots, by key
    if set(tslots) != set(k for k in gslots if k in tslots) or \
            not set(tslots) <= set(gslots):
        raise RunError('E1M%d: slots the game layout lacks: %s' % (
            gamemap, sorted(set(tslots) - set(gslots))[:4]))
    for key, upstream in tslots.items():
        t, c = key.split(':')
        e = info['sky'] if t == 'sky' else info['textures'][t]
        gb, ga, gup = gslots[key]
        if gup != upstream:
            raise RunError('slot %s: upstream $%06X, the game map\'s $%06X'
                           % (key, upstream, gup))
        put(e['bank'], e['base'] + LC.SLOT * int(c),
            mach.read(gb, ga, LC.SLOT))
    # the stored lumps with their tails, by lump
    local_of: Dict[int, int] = {0: 0}
    lump_local: Dict[int, int] = {}
    for e in info['sprites']['store']:
        g = gpm.get(e['lump'])
        if g is None or g[2] != e['size'] + LC.TAIL or g[3] != e['address']:
            raise RunError('E1M%d lump %d: the game patch map differs' % (
                gamemap, e['lump']))
        put(e['bank'], e['at'], mach.read(g[0], g[1], g[2]))
        local_of[g[5]] = e['index']
        lump_local[e['lump']] = e['index']
    # PHDR (local) from the global records
    phdr_recs = [(a, len(d)) for k, bk, a, d in recs if bk == R.SPRT and
                 R.PHDRS.base <= a < R.PHDRS.end]
    nloc = 1 + len(info['sprites']['store'])
    by_local = {e['index']: e for e in info['sprites']['store']}
    for k in range(nloc):
        if k == 0:
            rec = mach.read(R.SPRT, R.PHDRS.address(0), R.PHDR_SIZE)
        else:
            e = by_local[k]
            g = gpm[e['lump']][5]
            rec = bytearray(mach.read(R.SPRT, R.PHDRS.address(g),
                                      R.PHDR_SIZE))
            lump = rec[R.PHDR['LUMP']] | rec[R.PHDR['LUMP'] + 1] << 8
            if lump != e['lump']:
                raise RunError('PHDR %d is lump %d, not %d' % (g, lump,
                                                               e['lump']))
            rec[R.PHDR['BANK']] = e['bank']
            rec[R.PHDR['ADDR']:R.PHDR['ADDR'] + 2] = lstore.pack16(e['at'])
            rec = bytes(rec)
        put(R.SPRT, R.PHDRS.address(k), rec)
    del phdr_recs
    # SPRFR: the patch indexes global to local (through the machine's
    # PHDR: each global index's lump)

    def lump_of_global(g: int) -> int:
        rec = mach.read(R.SPRT, R.PHDRS.address(g), R.PHDR_SIZE)
        return rec[R.PHDR['LUMP']] | rec[R.PHDR['LUMP'] + 1] << 8
    glocal: Dict[int, int] = {0: 0}

    def to_local(g: int) -> int:
        if g not in glocal:
            lump = lump_of_global(g)
            if lump not in lump_local:
                raise RunError('global patch %d (lump %d) is not the '
                               'level\'s' % (g, lump))
            glocal[g] = lump_local[lump]
        return glocal[g]
    nfr = sum(info['sprites']['frames_per_sprite'])
    for k in range(nfr):
        a = R.SPRFRS.address(k)
        rec = bytearray(mach.read(R.SPRT, a, R.SPRFR_SIZE))
        for r in range(8):
            at = R.SPRFR['LUMPS'] + 2 * r
            v = rec[at] | rec[at + 1] << 8
            rec[at:at + 2] = lstore.pack16(to_local(v))
        put(R.SPRT, a, bytes(rec))
    # WPRO: WPIDX by the level's index, the profiles where the store has
    # them (their addresses are WPRO's own)
    for kind, bank, address, data in recs:
        if bank != R.WPRO:
            continue
        blob = bytearray(mach.read(R.WPRO, address, len(data)))
        if address != R.WPIDX:
            raise RunError('a WPRO record at $%04X' % address)
        nidx = (R.WPROF - R.WPIDX) // 2
        gidx = mach.read(R.WPRO, R.WPIDX, R.WPROF - R.WPIDX)
        widx = bytearray(b'\xff' * (R.WPROF - R.WPIDX))
        for g in range(nidx):
            v = gidx[2 * g] | gidx[2 * g + 1] << 8
            if v == R.NO_PROFILE:
                continue
            k = to_local(g)
            widx[2 * k:2 * k + 2] = lstore.pack16(v)
        blob[0:len(widx)] = widx
        put(R.WPRO, address, bytes(blob))
    # every byte of the target's records made, and no other
    for bank in sorted(set(want) | set(got)):
        if want.get(bank, set()) != got.get(bank, set()):
            extra = sorted(got.get(bank, set()) - want.get(bank, set()))
            miss = sorted(want.get(bank, set()) - got.get(bank, set()))
            raise RunError('E1M%d bank %d: the read-back %s' % (
                gamemap, bank, 'misses $%04X' % miss[0] if miss else
                'adds $%04X' % extra[0]))
    level_recs = []
    for kind, bank, address, data in recs:
        level_recs.append((1, bank, address, banks.get(bank, address,
                                                       len(data))))
    # the W tables: FLATCM as loaded; TXBANK, TXLO, TXHI to the harness
    # blocks (the machine's pointing at the texture's game block); TXWM
    # of the level's textures; TXHT as loaded
    wb = R.WCODE_BANK
    w = {address: data for kind, bank, address, data in
         LC.Image.parse((target / 'wtables.img').read_bytes())}
    wt = {R.FLATCM: mach.read(wb, R.FLATCM, len(w[R.FLATCM])),
          R.TXHT: mach.read(wb, R.TXHT, 256)}
    txbank, txlo, txhi, txwm = (bytearray(256) for _ in range(4))
    mb = mach.read(wb, R.TXBANK, 256)
    ml = mach.read(wb, R.TXLO, 256)
    mh = mach.read(wb, R.TXHI, 256)
    mw = mach.read(wb, R.TXWM, 256)
    for t_text, e in info['textures'].items():
        t = int(t_text)
        gb, ga, _ = gslots['%d:0' % t]
        if (mb[t] & 0x7F, ml[t] | mh[t] << 8) != (gb, ga):
            raise RunError('E1M%d texture %d: TXBANK, TXLO, TXHI point to '
                           '%d $%04X, its block is %d $%04X' % (
                               gamemap, t, mb[t] & 0x7F, ml[t] | mh[t] << 8,
                               gb, ga))
        txbank[t] = e['bank'] | (mb[t] & 0x80)
        txlo[t], txhi[t] = e['base'] & 0xFF, e['base'] >> 8
        txwm[t] = mw[t]
    wt.update({R.TXBANK: bytes(txbank), R.TXLO: bytes(txlo),
               R.TXHI: bytes(txhi), R.TXWM: bytes(txwm)})
    w_recs = [(0, 0, address, wt[address]) for address in sorted(w)]
    if sorted(w) != sorted(wt):
        raise RunError('wtables.img holds %s' % ['$%04X' % a for a in w])
    # TXMP: global to local
    m_recs = []
    for kind, bank, address, data in LC.Image.parse(
            (target / 'mtables.img').read_bytes()):
        if address != R.TXMP or len(data) != 512:
            raise RunError('mtables.img holds $%04X' % address)
        g = mach.read(R.MCODE_BANK, R.TXMP, 512)
        lo, hi = bytearray(256), bytearray(256)
        for t in range(256):
            v = g[t] | g[256 + t] << 8
            v = v if v == 0xFFFF else to_local(v)
            lo[t], hi[t] = v & 0xFF, v >> 8
        m_recs.append((kind, bank, address, bytes(lo) + bytes(hi)))
    fuzz = bytes(mach.main[0:0]) if False else None
    fuzz = mach.fuzzdark() if hasattr(mach, 'fuzzdark') else \
        bytes(mach.aux[0][LL.AUX0_FUZZ:LL.AUX0_FUZZ + 256])
    result = {'level.img': level_recs, 'wtables.img': w_recs,
              'mtables.img': m_recs, 'fuzzdark.bin': fuzz}
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        for name in ('level.json', 'texmap.json', 'patchmap.json',
                     'sectors-sides.json'):
            if (target / name).exists():
                shutil.copyfile(str(target / name), str(out / name))
        for name in ('level.img', 'wtables.img', 'mtables.img'):
            (out / name).write_bytes(RC.image_bytes(result[name]))
        (out / 'fuzzdark.bin').write_bytes(fuzz)
        (out / 'loaded.json').write_text(json.dumps(
            {'format': 'loaded-level 1', 'map': gamemap,
             'layout_of': str(target)}) + '\n')
    return result


def compare_harness(result: Dict[str, Any], target: Path,
                    named_sprfr: bool = True) -> Dict[str, int]:
    """The read-back against the target directory's own files, byte for
    byte: level.img but the rotate and flipmask bytes of the frames both
    flag as not frames (named), wtables.img, mtables.img, fuzzdark.bin.
    Raises RunError on a difference."""
    info = json.loads((target / 'level.json').read_text())
    skip: Dict[int, set] = {}
    k = 0
    bad = {tuple(x) for x in info['sprites']['not_frames']}
    for s, n in enumerate(info['sprites']['frames_per_sprite']):
        for f in range(n):
            if (s, f) in bad and named_sprfr:
                a = R.SPRFRS.address(k)
                skip.setdefault(R.SPRT, set()).update(
                    (a + R.SPRFR['ROT'], a + R.SPRFR['FLIP']))
            k += 1
    out = {'level_img': 0, 'named': 0}
    ref = LC.Image.parse((target / 'level.img').read_bytes())
    if len(ref) != len(result['level.img']):
        raise RunError('level.img: %d records, the read-back %d' % (
            len(ref), len(result['level.img'])))
    for (k1, b1, a1, d1), (k2, b2, a2, d2) in zip(ref, result['level.img']):
        if (k1, b1, a1, len(d1)) != (k2, b2, a2, len(d2)):
            raise RunError('level.img: the records differ')
        sk = skip.get(b1, set())
        for i in range(len(d1)):
            if d1[i] != d2[i]:
                if a1 + i in sk:
                    out['named'] += 1
                    continue
                raise RunError('level.img bank %d $%04X: %02X, the '
                               'read-back %02X' % (b1, a1 + i, d1[i], d2[i]))
        out['level_img'] += len(d1)
    for name in ('wtables.img', 'mtables.img'):
        ref = LC.Image.parse((target / name).read_bytes())
        if [(k_, b_, a_, d_) for k_, b_, a_, d_ in ref] != \
                [tuple(r) for r in result[name]]:
            for (k1, b1, a1, d1), (k2, b2, a2, d2) in zip(ref, result[name]):
                if d1 != d2:
                    at = next(i for i in range(min(len(d1), len(d2)))
                              if d1[i] != d2[i])
                    raise RunError('%s $%04X: %02X, the read-back %02X' % (
                        name, a1 + at, d1[at], d2[at]))
            raise RunError('%s differs' % name)
    if (target / 'fuzzdark.bin').read_bytes() != result['fuzzdark.bin']:
        raise RunError('fuzzdark.bin differs')
    return out


LOADED = LEVELS / 'loaded'


def loaded_level_hook():
    """framestate.LEVEL_HOOK for frame8.py --levels loaded: levelconv.py's
    directory of a source to the natively loaded level of its map read
    back into that directory's layout (made once a process, in
    build/native/levels/loaded/src/NAME)."""
    made: Dict[str, Path] = {}
    machines: Dict[int, SnapMachine] = {}

    def hook(level_dir: Path, src: str) -> Path:
        try:
            return made[level_dir.name] if level_dir.name in made else \
                make_one(level_dir)
        except RunError as error:
            from native import framestate as FS
            raise FS.FrameError('the loaded level of %s: %s' % (src, error))

    def make_one(level_dir: Path) -> Path:
        info = json.loads((level_dir / 'level.json').read_text())
        m = info['gamemap']
        if m not in machines:
            p = LOADED / ('e1m%d.img' % m)
            if not p.exists():
                raise RunError('%s is missing: run python3 tools/native/'
                               'level_check.py --load' % p)
            machines[m] = SnapMachine.from_image(p)
        out = LOADED / 'src' / level_dir.name
        if out.exists():
            shutil.rmtree(str(out))
        harness_level(machines[m], m, level_dir, out)
        made[level_dir.name] = out
        return out
    return hook


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def sizes(b: RC.Build) -> List[str]:
    seg = b.segments
    out = []
    ms = module_sizes(b)
    for name, budget in BUDGETS.items():
        size = sum(ms.get(n, 0) for n in name.split('+'))
        out.append('%-13s %5d of %5d B (docs/LEVELS.md 4.4)' % (
            name, size, budget))
    lo, hi = seg['LOADW']
    out.append('LOADW    $%04X-$%04X: %d of %d B (W $6600-$9FFF)' % (
        lo, hi, hi + 1 - lo, LL.LW_CODE_END - LL.LW_CODE))
    lo, hi = seg['RLOAD']
    out.append('card bank 1 $DC00-$%04X: %d of 1,024 B (unchanged: the far '
               'layer and the phase loader)' % (hi, hi + 1 - 0xDC00))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--sizes', action='store_true')
    parser.add_argument('--maps', default='1')
    parser.add_argument('--fill', default='a5')
    parser.add_argument('--profile')
    parser.add_argument('--no-build', action='store_true')
    args = parser.parse_args(argv)
    if not args.no_build:
        make()
    if args.sizes:
        for name in ('ltest', 'lcard'):
            if (OBJ / (name + '.map')).exists():
                print(name + ':')
                for line in sizes(load_build(OBJ, name)):
                    print('  ' + line)
        return 0
    b = load_build(OBJ, 'lprof' if args.profile else 'ltest')
    maps = [int(x) for x in args.maps.split(',')]
    work = Path(tempfile.mkdtemp(prefix='tmp-m9-lrun-', dir=str(BUILD)))
    try:
        r = run(b, maps, int(args.fill, 16), work, snapshots=False,
                profile=args.profile, write_log=False)
        print('ended: %s, %d cycles' % (r.ended(), r.state.get('cycles', 0)))
        if r.ended() == 'crash':
            print('stop %s' % status_of(r))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
