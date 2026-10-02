#!/usr/bin/env python3
"""a2vm runs of milestone 11's first half (docs/SCREENS.md 6.2-6.5, 7.3
part s2lay): the builds of src/native/m11.mk, a 2D image under the test
driver src/native/s2_drv.s, and what a run left. Built on
tools/native/lrun.py (imported: the build's labels and segments, the
bounds, the image records).

A run: the machine poisoned ($A5 or $5A: every main byte below $C000,
every RamWorks bank, the card), the persistent globals main $0300-$03EF 0
(the boot clears them), the card's quarter squares, math and far layer,
the image's stored pages (MATHW and AUXW, then its room) in its code bank
(s2layout.image_banks(), at W's addresses), the card's sound code when the
build has it, the test driver and its descriptors: the loads (far_pload
from a bank: the image's pages, a part's state pages) and the calls (a
routine with A, X, Y; the cost phase 30 around each). Options: a write
log (every CPU write but the stack page's) judged by the code that made
it (`stray`: the driver's set, the phase loader's, each part's), a range
snapshot after each call (`call-000K.img`) and at the stop (`stop.img`),
a whole-machine snapshot at the stop (`whole`: every byte the run changed
must be in a writer's set, the memory API's copies included), the cost
model (`profile`: f121, fastpath, their variants; --cost-timed and the
phases 0, 30 and 31), the AY log and the interrupt bounds (2.3's).

Every run is bounded (cycles, wall time, file sizes) in a directory the
caller gives, under build/ or a tempfile directory, deleted by the caller.

Usage:  python3 tools/native/s2run.py [--fill a5] [--profile f121]
        (the s2lay test image under the driver: an empty call list)
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from a2vm import costs  # noqa: E402
from native import levelconv as LC, lrun, rlayout as R, \
    s2layout as S  # noqa: E402
from ref816 import bounded  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
M11 = BUILD / 'native' / 'm11'
SOURCE = ROOT / 'src' / 'native'
A2VM = lrun.A2VM
TABLES = BUILD / 'native' / 'render' / 'tables'
FILLS = (0xA5, 0x5A)
CYCLE_LIMIT = 400_000_000
RUN_TIMEOUT = 300.0
MAX_FILE = 64 << 20
WRITE_LOG_LIMIT = 4_000_000
# docs/SCREENS.md 2.3: the IRQ contract of every test
IRQ_BOUNDS = '00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF'
# every CPU write but the stack page's (the BRK's and the IRQ's pushes,
# the calls' returns), the I/O ones included
WRITE_LOG = 'main:0000-00FF,main:0200-FFFF,lc,lc1,aux0-127,cpu:C000-C0FF'
STOP_SNAP = 'main:0000-03FF'
IO_DRIVER = {0xC006, 0xC0AE, 0xC0AF}
IO_LOADER = {0xC002, 0xC003, 0xC073}
# a stop the run may end at: the driver's, and pl_vbl's crash stop when a
# build links it (part plclock)
STOP_LABELS = ('s2d_stop', 'pl_crash')


class RunError(Exception):
    pass


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------

def make(part: str = 's2lay', m11: Path = M11, source: Path = SOURCE,
         variables: Sequence[str] = ()) -> None:
    """make -f m11.mk part P=PART into m11 (a copy of the sources in
    `source` takes the others from the tree); fails on a warning."""
    result = bounded.run(['make', '-s', '-C', str(source), '-f', 'm11.mk',
                          'part', 'P=%s' % part, 'M11=%s' % m11,
                          'ROOT=%s' % ROOT] + list(variables),
                         timeout=300, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, universal_newlines=True)
    if result.returncode:
        raise RunError('the build failed:\n' + result.stdout)
    if 'arning' in result.stdout:
        raise RunError('the build warns:\n' + result.stdout)


class Build(NamedTuple):
    obj: Path
    name: str
    image: str                  # s2layout's image whose room it uses
    labels: Dict[str, int]
    segments: Dict[str, Tuple[int, int]]
    areas: Dict[str, Tuple[int, str]]   # MEMORY area: (start, file suffix)

    def rc(self) -> 'lrun.RC.Build':
        return lrun.RC.Build(self.obj, self.name, self.labels, self.segments)


def load_build(obj: Path, name: str, image: str) -> Build:
    b = lrun.load_build(obj, name)
    areas = {}
    cfg = (obj / (name + '.cfg')).read_text()
    for m in re.finditer(r'^\s*(\w+):\s*start = \$([0-9A-F]+), size = '
                         r'\$[0-9A-F]+,(?: type = \w+,)? file = '
                         r'"%O\.(\w+)"', cfg, re.M):
        areas[m.group(1)] = (int(m.group(2), 16), m.group(3))
    return Build(obj, name, image, b.labels, b.segments, areas)


def module_sizes(b: Build) -> S.MapSizes:
    return S.read_map((b.obj / (b.name + '.map')).read_text())


# ---------------------------------------------------------------------------
# The image
# ---------------------------------------------------------------------------

class Call(NamedTuple):
    routine: str                # a label of the build
    a: int = 0
    x: int = 0
    y: int = 0


Record = Tuple[int, int, int, bytes]


def area_bytes(b: Build, area: str) -> bytes:
    path = b.obj / ('%s.%s' % (b.name, b.areas[area][1]))
    return path.read_bytes() if path.exists() else b''


def stored_extent(b: Build) -> Tuple[int, int]:
    """The image's stored bytes [lo, end): MATHW and AUXW from $6000, then
    its room's segments."""
    ends = [b.segments[s][1] + 1 for s in ('MATHW', 'AUXW') +
            S.IMG_SEGMENTS if s in b.segments]
    return S.MATHW_LO, max(ends)


def image_bank(b: Build) -> int:
    return S.image_banks()[b.image]


def image_records(b: Build, bank: Optional[int] = None) -> List[Record]:
    """The image's stored pages in its code bank at W's addresses."""
    bank = image_bank(b) if bank is None else bank
    out = []
    for area in ('W', 'IMG'):
        data = area_bytes(b, area)
        if data:
            out.append((1, bank, b.areas[area][0], data))
    return out


def card_records(b: Build, fill: int) -> List[Record]:
    """The card: bank 1 $D000-$DFFF (the quarter squares, the math, the far
    layer, the phase loader), $C000-$FFFF (S2's player and the effects when
    linked, the test driver, the vectors when linked); the rest the
    fill."""
    lc = bytearray([fill]) * 0x4000
    lc1 = bytearray([fill]) * 0x1000
    squares = (TABLES / 'math' / 'squares.bin').read_bytes()
    lc1[0:len(squares)] = squares
    for area in ('LC1', 'FAR'):
        start = b.areas[area][0]
        data = area_bytes(b, area)
        lc1[start - 0xD000:start - 0xD000 + len(data)] = data
    for area in ('SND', 'FXC', 'LCE', 'VEC'):
        if area not in b.areas:
            continue
        start = b.areas[area][0]
        data = area_bytes(b, area)
        lc[start - 0xC000:start - 0xC000 + len(data)] = data
    return [(2, 0, 0xC000, bytes(lc)), (3, 0, 0xD000, bytes(lc1))]


def base_records(b: Build, fill: int, persistent_zero: bool = True
                 ) -> List[Record]:
    pattern = bytes([fill]) * 0x10000
    recs: List[Record] = [(0, 0, 0x0000, pattern[:0xC000])]
    for bank in range(128):
        recs.append((1, bank, 0, pattern))
    recs += card_records(b, fill)
    recs += image_records(b)
    if persistent_zero:             # the persistent globals: the boot's 0
        recs.append((0, 0, 0x0300, bytes(0xF0)))
    return recs


def runs_of(lo: int, end: int) -> List[Tuple[int, int]]:
    """far_pload's runs for [lo, end): (first page, count) pieces of at
    most 255 pages."""
    first, count = S.page_run(lo, end)
    out = []
    while count:
        n = min(count, 255)
        out.append((first, n))
        first, count = first + n, count - n
    return out


class Load(NamedTuple):
    bank: int
    runs: Tuple[Tuple[int, int], ...]   # (first page, count)


def image_load(b: Build) -> Load:
    return Load(image_bank(b), tuple(runs_of(*stored_extent(b))))


def descriptor_record(b: Build, loads: Sequence[Load],
                      calls: Sequence[Call]) -> Record:
    """The driver's DESC segment: the runs page, the loads, the calls."""
    lab = b.labels
    lo, hi = b.segments['DESC']
    desc = bytearray(hi + 1 - lo)
    if len(loads) > S.DRV_LOADS or len(calls) > S.DRV_CALLS:
        raise RunError('%d loads, %d calls' % (len(loads), len(calls)))
    page = bytearray()
    offsets = []
    for ld in loads:
        offsets.append(len(page))
        for first, n in ld.runs:
            if not (1 <= n <= 255 and 0 < first and first + n <= 0xC0):
                raise RunError('a run $%02X x %d' % (first, n))
            page += bytes([first, n])
        page.append(0)
    if len(page) > 256:
        raise RunError('the runs pass their page')

    def put(label: str, data: bytes) -> None:
        at = lab[label] - lo
        desc[at:at + len(data)] = data
    put('s2d_runs', bytes(page))
    put('s2d_nloads', bytes([len(loads)]))
    put('s2d_lbank', bytes(ld.bank for ld in loads))
    put('s2d_lrun', bytes(offsets))
    put('s2d_ncalls', bytes([len(calls)]))
    addr = [lab[c.routine] for c in calls]
    put('s2d_clo', bytes(a & 0xFF for a in addr))
    put('s2d_chi', bytes(a >> 8 for a in addr))
    put('s2d_ca', bytes(c.a & 0xFF for c in calls))
    put('s2d_cx', bytes(c.x & 0xFF for c in calls))
    put('s2d_cy', bytes(c.y & 0xFF for c in calls))
    if lab['s2d_runs'] & 0xFF:
        raise RunError('the runs page is not page aligned')
    return (2, 0, lo, bytes(desc))


# ---------------------------------------------------------------------------
# A run
# ---------------------------------------------------------------------------

class Run(NamedTuple):
    state: Dict[str, Any]
    work: Path
    build: Build
    records: List[Record]
    loads: Tuple[Load, ...]

    def ended(self) -> str:
        """'stop' at the driver's (or pl_vbl's) stop, else a2vm's end."""
        pc = self.state.get('pc')
        if self.state.get('end') == 'stop-pc' and \
                any(self.build.labels.get(n) == pc for n in STOP_LABELS):
            return 'stop'
        return '%s at $%04X%s' % (self.state.get('end'), pc or 0,
                                  (': ' + self.state['halt'])
                                  if self.state.get('halt') else '')

    def status(self) -> Optional[int]:
        """PL_STATUS at the stop."""
        p = self.work / 'stop.img'
        if not p.exists():
            return None
        return read_snapshot(p).main[S.PL_STATUS]

    def calls(self) -> List['Machine']:
        return [read_snapshot(p) for p in
                sorted(self.work.glob('call-*.img'))]

    def writes(self) -> List['Write']:
        return read_writes(self.work / 'writes.log')

    def cost(self) -> Dict[str, Any]:
        text = (self.work / 'cost.json').read_text()
        return json.loads(text[text.rfind('{"final"'):])['cost']


def run(b: Build, calls: Sequence[Call], fill: int, work: Path,
        loads: Optional[Sequence[Load]] = None,
        extra_records: Sequence[Record] = (), write_log: bool = True,
        snap_ranges: Optional[str] = None, whole: bool = False,
        profile: Optional[str] = None, ay_log: bool = False,
        irq_bounds: Optional[str] = IRQ_BOUNDS, mb_only: bool = False,
        persistent_zero: bool = True, cycles: int = CYCLE_LIMIT,
        timeout: float = RUN_TIMEOUT, extra_args: Sequence[str] = ()
        ) -> Run:
    """One run of the driver: `loads` (default: the image's pages from its
    bank), then `calls`. snap_ranges: a range snapshot after each call;
    whole: the stop's snapshot is the whole machine (main, the card, every
    bank) instead of main $0000-$03FF."""
    work.mkdir(parents=True, exist_ok=True)
    loads = tuple(loads) if loads is not None else (image_load(b),)
    recs = base_records(b, fill, persistent_zero) + list(extra_records) + \
        [descriptor_record(b, loads, calls)]
    (work / 'image.bin').write_bytes(lrun.RC.image_bytes(recs))
    (work / 'rom.bin').write_bytes(bytes(0x4000))
    lab = b.labels
    code = code_ranges(b)
    args = [str(A2VM), '--rom', str(work / 'rom.bin'),
            '--core', 'w65c02s', '--amem', '--via-ora-nh',
            '--image', str(work / 'image.bin'),
            '--switch', 'lc_read=1', '--switch', 'lc_write=1',
            '--switch', 'lc_bank2=0',
            '--reg', 'pc=%X' % lab['s2d_start'],
            '--reg', 's=%X' % S.DRV_STACK, '--reg', 'p=34',
            '--cycles', str(cycles), '--speed', '1',
            '--lowest-s-in', ','.join('%X-%X' % r for r in code),
            '--state', str(work / 'state.json'),
            '--snapshot-dir', str(work)]
    for name in STOP_LABELS:
        if name in lab:
            args += ['--stop-pc', '%X' % lab[name]]
    if irq_bounds:
        args += ['--irq-bounds', irq_bounds]
    events = ['pc %X snapshot stop' % lab['s2d_stop']]
    if snap_ranges:
        events.append('pc %X@* snapshot call' % lab['s2d_called'])
    ranges = 'main,lc,lc1,aux0-127' if whole else \
        ','.join(r for r in (STOP_SNAP, snap_ranges) if r)
    args += ['--snapshot-ranges', ranges,
             '--every-limit', str(len(calls) + 2)]
    (work / 'events.txt').write_text('\n'.join(events) + '\n')
    args += ['--input', str(work / 'events.txt')]
    if write_log:
        args += ['--write-log', WRITE_LOG, '--write-log-file',
                 str(work / 'writes.log'), '--write-log-limit',
                 str(WRITE_LOG_LIMIT)]
    if profile:
        (work / 'cost.txt').write_text(costs.text(profile))
        args += ['--cost', str(work / 'cost.txt'), '--cost-timed',
                 '--cost-phase', '%X' % R.PHASE,
                 '--cost-report', str(work / 'cost.json')]
    if ay_log:
        args += ['--ay-log', str(work / 'ay.log')]
    if mb_only:
        args.append('--phasor-mb-only')
    args += list(extra_args)
    try:
        result = bounded.run(args, timeout=timeout, max_bytes=MAX_FILE,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True)
    except subprocess.TimeoutExpired:
        raise RunError('a2vm did not finish in %d s' % timeout)
    state_path = work / 'state.json'
    if not state_path.exists():
        raise RunError('a2vm failed: %s' % result.stdout[-2000:])
    return Run(json.loads(state_path.read_text()), work, b, recs, loads)


def code_ranges(b: Build) -> List[Tuple[int, int]]:
    """The image's code (W) and the far layer it calls, inclusive; then the
    driver's (its handler's depth)."""
    return [b.segments[s] for s in ('MATHW', 'AUXW') + S.IMG_SEGMENTS +
            ('RFAR', 'RLOAD', 'DRIVER') if s in b.segments]


def stack_depth(r: Run) -> Optional[int]:
    """The deepest S below the driver's in the image's code (bytes)."""
    low = r.state.get('lowest_s', {}).get('ranges', [])
    depths = [S.DRV_STACK - x['s'] for x in low[:-1] if x.get('s') is not None]
    return max(depths) if depths else None


# ---------------------------------------------------------------------------
# Snapshots, the write log
# ---------------------------------------------------------------------------

class Machine:
    """A snapshot (A2VMIMG1 records): main, the card (lc at $C000, lc1 at
    $D000) and the banks it holds."""

    def __init__(self):
        self.main = bytearray(0x10000)
        self.lc = bytearray(0x4000)
        self.lc1 = bytearray(0x1000)
        self.aux: Dict[int, bytearray] = {}

    def put(self, kind: int, bank: int, address: int, data: bytes) -> None:
        if kind == 0:
            self.main[address:address + len(data)] = data
        elif kind == 1:
            self.aux.setdefault(bank, bytearray(0x10000))[
                address:address + len(data)] = data
        elif kind == 2:
            self.lc[address - 0xC000:address - 0xC000 + len(data)] = data
        elif kind == 3:
            self.lc1[address - 0xD000:address - 0xD000 + len(data)] = data

    @classmethod
    def of(cls, recs: Sequence[Record]) -> 'Machine':
        m = cls()
        for rec in recs:
            m.put(*rec)
        return m

    def storage(self, name: str, bank: int = 0) -> bytearray:
        if name == 'main':
            return self.main
        if name == 'aux':
            return self.aux.setdefault(bank, bytearray(0x10000))
        return self.lc if name == 'lc' else self.lc1


def read_snapshot(path: Path) -> Machine:
    return Machine.of(LC.Image.parse(path.read_bytes()))


class Write(NamedTuple):
    clock: int
    pc: int
    address: int
    storage: str                # main, aux, lc, lc1, io
    bank: int
    offset: int
    old: Optional[int]
    new: int


def parse_writes(lines) -> List[Write]:
    out = []
    for line in lines:
        if line.startswith('#') or not line.strip():
            continue
        f = line.split()
        io = f[5] == 'io'
        out.append(Write(int(f[1]), int(f[3], 16), int(f[4], 16), f[5],
                         0 if io else int(f[6]),
                         int(f[4], 16) if io else int(f[7], 16),
                         None if io else int(f[8], 16), int(f[9], 16)))
    return out


def read_writes(path: Path) -> List[Write]:
    with open(str(path)) as handle:
        return parse_writes(handle)


class Owner(NamedTuple):
    """A writer: its code (inclusive PC ranges), the storage it may write
    ((storage, bank, lo, hi) half-open) and the I/O addresses."""
    name: str
    pcs: Tuple[Tuple[int, int], ...]
    allowed: Tuple[Tuple[str, int, int, int], ...]
    io: frozenset


def driver_owner(b: Build) -> Owner:
    desc = b.segments['DESC']
    return Owner('driver', (b.segments['DRIVER'], desc),
                 (('main', 0, R.PHASE, R.PHASE + 1),
                  ('main', 0, S.PL_STATUS, S.PL_STATUS + 1),
                  ('lc', 0, desc[0], desc[1] + 1),
                  ('lc', 0, 0xFFFE, 0x10000)),
                 frozenset(IO_DRIVER))


def loader_owner(b: Build, loads: Sequence[Load]) -> Owner:
    """far_pload: the loads' pages in main, its zero-page pointers."""
    allowed = [('main', 0, R.ZP_FAR[0], R.ZP_FAR[1])]
    for ld in loads:
        for first, n in ld.runs:
            allowed.append(('main', 0, first << 8, (first + n) << 8))
    return Owner('loader', (b.segments['RLOAD'],), tuple(allowed),
                 frozenset(IO_LOADER))


def stray(writes: Sequence[Write], owners: Sequence[Owner],
          limit: int = 20) -> Tuple[int, List[str]]:
    """The writes no owner may make (by the PC that made them): (count, the
    first `limit` described)."""
    count, out = 0, []
    for w in writes:
        owner = next((o for o in owners if any(lo <= w.pc <= hi
                                               for lo, hi in o.pcs)), None)
        if owner is None:
            ok = False
        elif w.storage == 'io':
            ok = w.address in owner.io
        else:
            ok = any(s == w.storage and (s != 'aux' or bank == w.bank) and
                     lo <= w.offset < hi for s, bank, lo, hi in owner.allowed)
        if not ok:
            count += 1
            if len(out) < limit:
                out.append('pc $%04X (%s) wrote %s %d $%04X' % (
                    w.pc, owner.name if owner else 'no owner', w.storage,
                    w.bank, w.offset))
    return count, out


def changed_outside(before: Machine, after: Machine,
                    owners: Sequence[Owner], limit: int = 20
                    ) -> Tuple[int, List[str]]:
    """Every byte the run changed (whole-machine snapshots) outside every
    owner's storage and the stack page: (count, the first `limit`)."""
    allowed: Dict[Tuple[str, int], List[Tuple[int, int]]] = {}
    for o in owners:
        for s, bank, lo, hi in o.allowed:
            allowed.setdefault((s, bank if s == 'aux' else 0), []).append(
                (lo, hi))
    allowed.setdefault(('main', 0), []).append((0x0100, 0x0200))
    count, out = 0, []
    pairs = [('main', 0, before.main, after.main, 0),
             ('lc', 0, before.lc, after.lc, 0xC000),
             ('lc1', 0, before.lc1, after.lc1, 0xD000)]
    for bank in sorted(set(before.aux) | set(after.aux)):
        pairs.append(('aux', bank, before.storage('aux', bank),
                      after.storage('aux', bank), 0))
    for s, bank, x, y, base in pairs:
        if x == y:
            continue
        spans = allowed.get((s, bank), [])
        for i in range(len(x)):
            if x[i] != y[i]:
                a = base + i
                if s == 'main' and a >= 0xC000:
                    continue
                if not any(lo <= a < hi for lo, hi in spans):
                    count += 1
                    if len(out) < limit:
                        out.append('%s %d $%04X: $%02X to $%02X' % (
                            s, bank, a, x[i], y[i]))
    return count, out


# ---------------------------------------------------------------------------
# Cost, the AY log
# ---------------------------------------------------------------------------

def phase_ms(r: Run, profile: str) -> Dict[int, float]:
    """Each cost phase's time in ms (the phases with any)."""
    mhz = costs.parameters(profile)['fabric_mhz']
    return {k: v / (mhz * 1000.0) for k, v in enumerate(r.cost()['phases'])
            if v}


def ay_events(r: Run) -> List[Tuple]:
    """The AY log (tools/sound/run65.read_log's tuples)."""
    from sound import run65
    return run65.read_log(r.work / 'ay.log')


def irq_lengths(r: Run) -> List[int]:
    """Each complete interrupt's length in the AY log's clock (fabric
    clocks with a cost model, else CPU cycles)."""
    out, entry = [], None
    for e in ay_events(r):
        if e[0] == 'irq':
            entry = e[3] if e[3] is not None else e[2]
        elif e[0] == 'rti' and entry is not None:
            out.append((e[2] if e[2] is not None else e[1]) - entry)
            entry = None
    return out


# ---------------------------------------------------------------------------
# The command line: the s2lay test image under the driver
# ---------------------------------------------------------------------------

S2LAY = M11 / 's2lay'


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--fill', default='a5')
    parser.add_argument('--profile')
    parser.add_argument('--no-build', action='store_true')
    args = parser.parse_args(argv)
    if not args.no_build:
        make()
    b = load_build(S2LAY, 's2lt', 'P2DW')
    work = Path(tempfile.mkdtemp(prefix='tmp-m11-s2run-', dir=str(BUILD)))
    try:
        r = run(b, [], int(args.fill, 16), work, profile=args.profile)
        print('ended: %s, status $%02X, %d cycles' % (
            r.ended(), r.status() or 0, r.state.get('cycles', 0)))
        n, shown = stray(r.writes(), [driver_owner(b),
                                      loader_owner(b, r.loads)])
        print('stray writes: %d %s' % (n, shown[:4]))
        if args.profile:
            print(phase_ms(r, args.profile))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
