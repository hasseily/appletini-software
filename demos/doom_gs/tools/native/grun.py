#!/usr/bin/env python3
"""The tic phase's images on a2vm (milestone 10, docs/GAME.md 3.4-3.6), as
tools/native/lrun.py runs the load's: the build of src/native/game.mk, an
image of the machine, a run of the test driver (src/native/gdriver.s),
what it left read back.

Usage:  python3 tools/native/grun.py --sizes
        python3 tools/native/grun.py --selftest

An image (`Image`): the machine after the boot, every byte poisoned ($A5
or $5A) but the persistent globals main $0300-$03EF (0, as the boot leaves
them): the store's bank files (lstore.py) in their banks; the card (the
math's tables and code, the far layer and the phase loader, the test
driver: the tic image's, which must equal the load image's byte for byte
in the products, the far layer and the phase loader); the tic image in
GCODE0 at W's addresses (MATHW, AUXW from $6000, the core from $6600) and
its groups packed after it and in GCODE1, the group directory written into
the core's grp_bank, grp_src, grp_pages, grp_tail (group_entry: each
group's whole pages and the bytes gcall.s's gr_load copies of its last
page, not the page's padding); the load image (level.mk's ltest)
in LCODE at its addresses; the driver's descriptor (DESC: the mode, the
entry, the page runs); then the test's own records (a game state through
the bridge's port writer, GTEST, the planes, hand-made data).

A run: a2vm from drv_game with the mouse card's VBL interrupt, under the
memory API, bounded (cycles, time, file sizes), in a directory under
build/ deleted after it; its snapshots (`snapshot NAME` events at the
driver's points: drv_done, drv_tic, drv_loaded, drv_frame) as range images
or, with --snapshot-stream (a2vm, milestone 10), one bounded stream; the
write log; the lowest S.
"""

import argparse
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from a2vm import costs  # noqa: E402
from native import glayout as GL, levelconv as LC, llayout as LL, \
    render_check as RC, rlayout as R  # noqa: E402
from native import lrun  # noqa: E402
from ref816 import bounded  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
GAME = BUILD / 'native' / 'game'
SOURCE = ROOT / 'src' / 'native'
A2VM = lrun.A2VM
FILLS = (0xA5, 0x5A)
DRV_STACK = 0xEF
CYCLE_LIMIT = 4_000_000_000
RUN_TIMEOUT = 900.0
MAX_FILE = 256 << 20
WRITE_LOG_LIMIT = 4_000_000
IRQ_BOUNDS = lrun.IRQ_BOUNDS
CARD_SEGMENTS = ('MATHLC', 'MATHFAR', 'RFAR', 'RLOAD')
# the tic image's W in GCODE0: MATHW and AUXW from $6000, the core from
# $6600; the groups packed from GROUP_FIRST in GCODE0 (below W's
# addresses), then GCODE1
GROUP_FIRST = 0x0200
GCODE0_GROUP_END = 0x6000


class RunError(Exception):
    pass


# ---------------------------------------------------------------------------
# The builds
# ---------------------------------------------------------------------------

def make(target: str = 'skel', variables: Sequence[str] = (),
         source: Path = SOURCE) -> None:
    result = bounded.run(['make', '-s', '-C', str(source), '-f', 'game.mk',
                          target, 'ROOT=%s' % ROOT] + list(variables),
                         timeout=600, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, universal_newlines=True)
    if result.returncode:
        raise RunError('the build failed:\n' + result.stdout[-4000:])
    if 'arning' in result.stdout:
        raise RunError('the build warns:\n' + result.stdout[-4000:])


# a scratch copy's build files: game.mk, its includes, integrated.txt and
# every part's fragment (game.mk's PARTS come from the copy's fragments,
# while glayout.py counts the integrated waves' parts as built: wave 1 as
# integrated); the sources come from the tree through game.mk's vpath
PLANT_COPY = tuple(['game.mk', 'math.inc', 'game/integrated.txt'] + sorted(
    str(f.relative_to(SOURCE)) for f in SOURCE.glob('game/*/part.mk')))


def planted(tmp: Path, bugs, target: str = 'skel',
            variables: Sequence[str] = ()) -> Path:
    """A test image built from a scratch copy of the sources with each
    (file, old, new) of bugs applied once (file relative to src/native;
    the copy holds game.mk and the planted files, the rest comes from the
    tree through game.mk's vpath): the image's directory, tmp/game/TARGET.
    """
    src = tmp / 'src'
    for f in set(PLANT_COPY) | {name for name, _, _ in bugs}:
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(SOURCE / f), str(src / f))
    for name, old, new in bugs:
        text = (src / name).read_text()
        if text.count(old) != 1:
            raise RunError('the bug no longer applies: %r' % old)
        (src / name).write_text(text.replace(old, new))
    make(target, ['GAME=%s' % (tmp / 'game')] + list(variables), src)
    return tmp / 'game' / target


def load_build(obj: Path, name: str) -> RC.Build:
    return RC.load_build(obj, name)


def groups_of(b: RC.Build) -> List[Tuple[int, int, int, bytes]]:
    """(group, slot address, end, bytes) of each group file of an image
    (the map's GGRPn segments)."""
    out = []
    for seg, (lo, hi) in sorted(b.segments.items()):
        if not seg.startswith('GGRP'):
            continue
        n = int(seg[4:])
        data = (b.obj / ('%s.g%d' % (b.name, n))).read_bytes()
        out.append((n, lo, hi, data[:hi + 1 - lo]))
    return out


# a group's last page: copied as a whole page when the bytes it uses are
# more than this (part ticloads' threshold for a second far_gcopy window,
# docs/speed-parts/ticloads.md; gr_load has made one window a group since
# wave 2's integration, where the few bytes past it save little either way)
TAIL_MAX = 224


def group_entry(bank: int, page: int, size: int) -> List[Tuple[str, int]]:
    """A group's entry of gcall.s's directory: its bank, its first page, its
    whole pages and the bytes gr_load copies of the page after them: its
    byte length rounded up to an even count (far_gcopy copies two bytes a
    turn), or the page whole when it uses more than TAIL_MAX bytes or the
    group is under a page (gr_load reads a grp_pages of 0 as a group the
    image does not hold)."""
    if not 0 < size <= 0x800:
        raise RunError('a group of %d B' % size)
    pages, tail = size >> 8, size & 0xFF
    tail += tail & 1
    if tail > TAIL_MAX or (tail and not pages):
        pages, tail = pages + 1, 0
    return [('grp_bank', bank), ('grp_src', page), ('grp_pages', pages),
            ('grp_tail', tail)]


def card_bytes(b: RC.Build) -> Dict[str, bytes]:
    """The card's segments of a build (to check two builds share them)."""
    out = {}
    for seg in CARD_SEGMENTS:
        if seg not in b.segments:
            continue
        lo, hi = b.segments[seg]
        part, base = ('lc1', 0xD800) if seg == 'MATHLC' else ('far', 0xDC00)
        data = (b.obj / ('%s.%s' % (b.name, part))).read_bytes()
        out[seg] = data[lo - base:hi + 1 - base]
    return out


# ---------------------------------------------------------------------------
# The image
# ---------------------------------------------------------------------------

class Image:
    """The records of a run's image (a2vm --image), with the builds'
    labels."""

    def __init__(self, b: RC.Build, fill: int,
                 level: Optional[RC.Build] = None, store: bool = True):
        self.b = b
        self.fill = fill
        self.level = level
        lab = b.labels
        pattern = bytes([fill]) * 0x10000
        self.recs: List[Tuple[int, int, int, bytes]] = [
            (0, 0, 0x0000, pattern[:0xC000])]
        for bank in range(128):
            self.recs.append((1, bank, 0, pattern))
        self.recs += lrun.card_records(_DriverView(b), fill)
        if store:
            self.recs += lrun.store_records()
        self.recs += math_table_records()
        self.recs.append((0, 0, 0x0300, bytes(0xF0)))
        # the tic image: W and the core in GCODE0, the groups packed
        w = (b.obj / ('%s.w' % b.name)).read_bytes()
        core = bytearray((b.obj / ('%s.core' % b.name)).read_bytes())
        core_lo = GL.WR['CORE'][0]
        ends = [b.segments[s][1] for s in ('GCORE', 'LOADW')
                if s in b.segments]
        core_end = max(ends) + 1
        if core_end > GL.WR['CORE'][1]:
            raise RunError('the core passes $%04X' % GL.WR['CORE'][1])
        at = {GL.LL.GCODE0: GROUP_FIRST, GL.LL.GCODE1: GROUP_FIRST}
        directory = {}
        for n, lo, hi, data in groups_of(b):
            pages = (len(data) + 0xFF) >> 8
            bank = GL.LL.GCODE0
            if at[bank] + (pages << 8) > GCODE0_GROUP_END:
                bank = GL.LL.GCODE1
            if at[bank] + (pages << 8) > (LL.ROOM[1] if bank ==
                                           GL.LL.GCODE1 else
                                           GCODE0_GROUP_END):
                raise RunError('the groups pass GCODE1')
            self.recs.append((1, bank, at[bank], data))
            directory[n] = (bank, at[bank] >> 8, len(data))
            at[bank] += pages << 8
        for n, (bank, page, size) in directory.items():
            for name, v in group_entry(bank, page, size):
                a = lab[name] + n - core_lo
                core[a] = v
        self.recs.append((1, GL.LL.GCODE0, 0x6000, w))
        # (the core goes in last, with the pokes into it: bytes())
        self.core = core
        self.core_lo = core_lo
        self.groups = directory
        # the descriptor's page runs
        self.poke_label('dg_core', bytes([0x60, ((core_end + 0xFF) >> 8) -
                                          0x60, 0]))
        self.poke_label('dg_planes', bytes([LL.PL_TNL >> 8,
                                            (LL.PL_TICS + LL.PLANE_SLOTS -
                                             LL.PL_TNL) >> 8, 0]))
        if level is not None:
            if card_bytes(level) != card_bytes(b):
                raise RunError('the load image\'s card differs from the '
                               'tic image\'s')
            self.recs += lrun.load_image(level)
            lo, hi = level.segments['LOADW']
            self.poke_label('dg_lcode', bytes([0x60, ((hi + 0x100) >> 8) -
                                               0x60, 0]))
            self.poke_word('dg_nlsetup', level.labels['nl_setup'])

    # -- writes into the image --
    def main(self, address: int, data: bytes) -> None:
        self.recs.append((0, 0, address, bytes(data)))

    def aux(self, bank: int, address: int, data: bytes) -> None:
        self.recs.append((1, bank, address, bytes(data)))

    def card(self, address: int, data: bytes) -> None:
        """The main card $C000-$FFFF (bank 2 at $D000), the driver's
        part."""
        self.recs.append((2, 0, address, bytes(data)))

    def poke_label(self, name: str, data: bytes) -> None:
        """A label's bytes: in the card (the driver's), in the core image
        (the driver loads it into W from GCODE0 at its start), or main."""
        a = self.b.labels[name]
        if a >= 0xC000:
            self.card(a, data)
        elif self.core_lo <= a < self.core_lo + len(self.core):
            self.core[a - self.core_lo:a - self.core_lo + len(data)] = data
        else:
            self.main(a, data)

    def poke_word(self, name: str, value: int) -> None:
        self.poke_label(name, struct.pack('<H', value))

    def gtest(self, address: int, data: bytes) -> None:
        self.aux(LL.GTEST, address, data)

    def bytes(self) -> bytes:
        return RC.image_bytes(self.recs + [(1, GL.LL.GCODE0, self.core_lo,
                                            bytes(self.core))])


_MATH_TABLES: List[Tuple[int, int, int, bytes]] = []


def math_table_records() -> List[Tuple[int, int, int, bytes]]:
    """The math's RamWorks tables, as the boot leaves them (src/native/
    MATH.md: MT_TBANK the sines, tantoangle and the quarter sine; MT_RLO,
    MT_RHI the reciprocals; render_check.py's records): every tic image
    has them (wave 1 as integrated, docs/game-parts/sight.md R3: without
    them recipsmall, finesine ... read the poison)."""
    if not _MATH_TABLES:
        m = RC.TABLES / 'math'
        t = R.MT_TBANK
        recs = [(1, t, 0x2000, (m / 'sinelo.bin').read_bytes()),
                (1, t, 0x4000, (m / 'sinehi.bin').read_bytes())]
        for k in range(4):
            recs.append((1, t, 0x6000 + 256 * 9 * k,
                         (m / ('tanto%d.bin' % k)).read_bytes()))
        recs += [(1, t, 0x8400, (m / 'quartlo.bin').read_bytes()),
                 (1, t, 0x8C00, (m / 'quarthi.bin').read_bytes()),
                 (1, R.MT_RLO, 0x2000, (m / 'reciplo.bin').read_bytes()),
                 (1, R.MT_RHI, 0x2000, (m / 'reciphi.bin').read_bytes())]
        _MATH_TABLES.extend(recs)
    return list(_MATH_TABLES)


class _DriverView:
    """lrun.card_records' view of a tic build (its driver segment)."""

    def __init__(self, b: RC.Build):
        self.b = b
        self.obj = b.obj
        self.name = b.name
        self.segments = dict(b.segments)
        self.labels = b.labels


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


def snap_ranges(banks: Sequence[int] = ()) -> str:
    return ','.join(['main', 'lc:E000-FFFF'] +
                    ['aux%d:0200-BFFF' % b for b in banks])


def run(img: Image, work: Path, mode: int, entry: Optional[str] = None,
        regs: Tuple[int, int, int, int] = (0, 0, 0, 0x34),
        events: Sequence[str] = (), banks: Sequence[int] = (),
        profile: Optional[str] = None, write_log: Optional[str] = None,
        every_limit: int = 64, cycles: int = CYCLE_LIMIT,
        stream: Optional[Tuple[Path, int]] = None,
        timeout: float = RUN_TIMEOUT, extra: Sequence[str] = ()) -> Run:
    """One run of the driver: mode (GL.MODES), entry (a label: the routine
    of the routine modes); events (a2vm input lines, the snapshot points);
    the snapshots' banks besides main and the driver's card. A snapshot
    "done" at drv_done and "crash" at drv_crash always. stream (path,
    limit): every snapshot into one stream (a2vm --snapshot-stream)."""
    work.mkdir(parents=True, exist_ok=True)
    lab = img.b.labels
    img.poke_label('dg_mode', bytes([mode]))
    if entry is not None:
        addr = lab[entry]
        grp = entry_group(img.b, entry)
        if grp == 0 and GL.WR['SLOT1'][0] <= addr < GL.WR['SLOT2'][1]:
            raise RunError('%s is in a slot but in no group of the '
                           'placement' % entry)
        img.poke_word('dg_entry', addr)
        img.poke_label('dg_grp', bytes([grp]))
    a, x, y, p = regs
    img.poke_label('dg_a', bytes([a, x, y, p]))
    (work / 'image.bin').write_bytes(img.bytes())
    (work / 'rom.bin').write_bytes(bytes(0x4000))
    args = [str(A2VM), '--rom', str(work / 'rom.bin'), '--core', 'w65c02s',
            '--amem', '--image', str(work / 'image.bin'),
            '--switch', 'lc_read=1', '--switch', 'lc_write=1',
            '--switch', 'lc_bank2=0',
            '--reg', 'pc=%X' % lab['drv_game'], '--reg', 's=%X' % DRV_STACK,
            '--reg', 'p=34',
            '--stop-pc', '%X' % lab['drv_halt'],
            '--stop-pc', '%X' % lab['drv_crash'],
            '--cycles', str(cycles), '--speed', '1',
            '--irq-bounds', IRQ_BOUNDS,
            '--lowest-s',
            '--state', str(work / 'state.json'),
            '--snapshot-dir', str(work),
            '--snapshot-ranges', snap_ranges(banks),
            '--every-limit', str(every_limit)]
    ev = ['pc %X snapshot done' % lab['drv_done'],
          'pc %X snapshot crash' % lab['drv_crash']] + list(events)
    (work / 'events.txt').write_text('\n'.join(ev) + '\n')
    args += ['--input', str(work / 'events.txt')]
    if stream is not None:
        args += ['--snapshot-stream', str(stream[0]),
                 '--snapshot-limit', str(stream[1])]
    args += list(extra)
    if write_log:
        args += ['--write-log', write_log, '--write-log-file',
                 str(work / 'writes.log'), '--write-log-limit',
                 str(WRITE_LOG_LIMIT)]
    if profile:
        (work / 'cost.txt').write_text(costs.text(profile))
        args += ['--cost', str(work / 'cost.txt'), '--cost-timed',
                 '--cost-phase', '%X' % R.PHASE,
                 '--cost-report', str(work / 'cost.json')]
    try:
        result = bounded.run(args, timeout=timeout, max_bytes=MAX_FILE,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True)
    except subprocess.TimeoutExpired:
        raise RunError('a2vm did not finish in %d s' % timeout)
    path = work / 'state.json'
    if not path.exists():
        raise RunError('a2vm failed: %s' % result.stdout[-2000:])
    return Run(json.loads(path.read_text()), work, lab)


def entry_groups(b: RC.Build) -> Dict[str, int]:
    """Each routine's group in a build (its gen/gplace.inc: GP_name_G; 0
    the core)."""
    out: Dict[str, int] = {}
    for line in (b.obj / 'gen' / 'gplace.inc').read_text().splitlines():
        f = line.split()
        if len(f) == 3 and f[1] == '=' and f[0].startswith('GP_') and \
                f[0].endswith('_G'):
            out[f[0][3:-2]] = int(f[2])
    return out


def entry_group(b: RC.Build, name: str) -> int:
    """The group of a routine of the build: its placement's (gplace.inc),
    never its address (every group of a slot starts at the slot's first
    byte: wave 1 as integrated, geom.md R6, mobjstate.md R3, secfind.md
    request 7, flow.md request 5a); 0 for a label the placement does not
    name (the core, the driver, the harness's own)."""
    return entry_groups(b).get(name, 0)


def load_snapshot(p: Path) -> lrun.SnapMachine:
    """A range snapshot as a SnapMachine, with the main card's bytes too
    (m.lc: $C000-$FFFF, the driver's descriptor)."""
    m = lrun.SnapMachine.from_image(p)
    m.lc = bytearray(0x4000)
    for kind, bank, address, data in LC.Image.parse(p.read_bytes()):
        if kind == 2:
            m.lc[address - 0xC000:address - 0xC000 + len(data)] = data
    return m


def card_byte(m: lrun.SnapMachine, address: int) -> int:
    return m.lc[address - 0xC000]


def snapshot(r: Run, name: str) -> lrun.SnapMachine:
    p = r.work / (name + '.img')
    if not p.exists():
        raise RunError('no snapshot %s (the run ended %s)' % (name,
                                                              r.ended()))
    return load_snapshot(p)


def stop_codes(m: lrun.SnapMachine) -> Tuple[int, int, int]:
    """GS_STATUS, GS_ARG and LV_STATUS of a snapshot."""
    return (m.main[GL.GS_STATUS],
            m.main[GL.GS_ARG] | m.main[GL.GS_ARG + 1] << 8,
            m.main[LL.LV_STATUS])


GS_NAMES = {v: k for k, v in GL.GS.items()}


# ---------------------------------------------------------------------------
# The snapshot stream (a2vm --snapshot-stream, tools/a2vm/README.md)
# ---------------------------------------------------------------------------

def read_stream(handle):
    """The snapshots of an a2vm snapshot stream (a binary file object),
    one at a time: (its JSON head, a SnapMachine); the end line last as
    (head, None)."""
    first = json.loads(handle.readline())
    if first.get('format') != 'a2vm-snapshot-stream 1':
        raise RunError('not an a2vm snapshot stream: %r' % first)
    while True:
        line = handle.readline()
        if not line:
            raise RunError('the stream ends with no end line')
        head = json.loads(line)
        if 'end' in head:
            yield head, None
            return
        data = handle.read(head['bytes'])
        if len(data) != head['bytes']:
            raise RunError('a snapshot of %d bytes, %d read' % (
                head['bytes'], len(data)))
        m = lrun.SnapMachine()
        for kind, bank, address, chunk in LC.Image.parse(data):
            if kind == 0:
                m.main[address:address + len(chunk)] = chunk
            elif kind == 1:
                m.aux.setdefault(bank, bytearray(0x10000))[
                    address:address + len(chunk)] = chunk
            else:
                m.__dict__.setdefault('card', {})[(kind, address)] = chunk
        yield head, m


# ---------------------------------------------------------------------------
# The game state through the manifest
# ---------------------------------------------------------------------------

def tracked_memory():
    """A bridge PortMemory that remembers the bytes written (the port
    writer's), so that only they go into an image."""
    from bridge.memory import PortMemory

    class Tracked(PortMemory):
        def __init__(self):
            super().__init__()
            self.written: Dict[int, set] = {}

        def write(self, address: int, data: bytes) -> None:
            super().write(address, data)
            for k in range(len(data)):
                a = address + k
                self.written.setdefault(a >> 16, set()).add(a & 0xFFFF)
    return Tracked()


def port_records(memory) -> List[Tuple[int, int, int, bytes]]:
    """The bytes a tracked PortMemory was written, as image records (main
    and the aux banks), in runs."""
    from bridge.memory import MAIN
    out = []
    for bank, offsets in sorted(memory.written.items()):
        data = memory.banks[bank]
        run: List[int] = []
        for a in sorted(offsets) + [None]:
            if run and (a is None or a != run[-1] + 1):
                lo = run[0]
                rec = bytes(data[lo:run[-1] + 1])
                if bank == MAIN >> 16:
                    out.append((0, 0, lo, rec))
                else:
                    out.append((1, bank, lo, rec))
                run = []
            if a is not None:
                run.append(a)
    return out


# ---------------------------------------------------------------------------
# Sizes (docs/GAME.md 4.7, 5.5)
# ---------------------------------------------------------------------------

BUDGETS = {'gobj': 1200, 'gcall': 300, 'ghook': 200}


def module_sizes(b: RC.Build) -> Dict[str, int]:
    text = (b.obj / (b.name + '.map')).read_text()
    out: Dict[str, int] = {}
    module = None
    text = text.split('Modules list:', 1)[-1].split('Segment list:', 1)[0]
    for line in text.splitlines():
        if line and not line.startswith(' ') and line.endswith('.o:'):
            module = Path(line[:-1]).stem
            continue
        f = line.split()
        if module and f and f[0] in ('LOADW', 'GCORE') or (
                module and f and f[0].startswith('GGRP')):
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            out[module] = out.get(module, 0) + size
    return out


def contributions(b: RC.Build) -> List[Tuple[str, str, int, int]]:
    """(module, segment, start, end) of each module's part of each segment
    (the map's modules list; end exclusive)."""
    text = (b.obj / (b.name + '.map')).read_text()
    text = text.split('Modules list:', 1)[-1].split('Segment list:', 1)[0]
    out = []
    module = None
    for line in text.splitlines():
        if line and not line.startswith(' ') and line.endswith('.o:'):
            module = Path(line[:-1]).stem
            continue
        f = line.split()
        if not (module and f and f[0] in b.segments):
            continue
        offs = next(int(x[5:], 16) for x in f if x.startswith('Offs='))
        size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
        if size:
            lo = b.segments[f[0]][0] + offs
            out.append((module, f[0], lo, lo + size))
    return out


CODE_SEGMENTS = ('GCORE', 'LOADW')


def module_bytes(b: RC.Build, module: str) -> int:
    """A module's bytes in every segment, the card's driver area
    included (the parts' test-only code is there since wave 1's
    integration)."""
    return sum(hi - lo for m, _, lo, hi in contributions(b) if m == module)


def routine_sizes(b: RC.Build) -> Tuple[Dict[str, int], Dict[str, int]]:
    """The bytes of each routine of the part table and the core (its
    native label to the next such label in its module's part of a code
    segment, or that part's end), by file:label; and the core's bytes
    that no such routine holds, by module (the runtime, milestone 9's
    core, the parts' code outside the table: g_resume, test code)."""
    names = GL.native_names()
    # (an inlined helper has no code of its own: a local label of its
    # name, as trymove's overStep, is its caller's bytes; wave 4 as
    # integrated)
    keys = [k for p in GL.PARTS for k in p['routines'] + p['helpers']
            if not GL.inlined(k)]
    by_name = {names[k]: k for k in keys}
    lab = b.labels
    group = entry_groups(b)
    sizes: Dict[str, int] = {}
    rest: Dict[str, int] = {}
    for module, seg, lo, hi in contributions(b):
        if not (seg in CODE_SEGMENTS or seg.startswith('GGRP')):
            continue
        g = 0 if seg in CODE_SEGMENTS else int(seg[4:])
        # (the groups of a slot share their addresses: a label is this
        # segment's when its routine's group is)
        at = sorted({(a, n) for n, a in lab.items()
                     if n in by_name and group.get(n, 0) == g and
                     lo <= a < hi})
        first = at[0][0] if at else hi
        if seg in CODE_SEGMENTS:
            rest[module] = rest.get(module, 0) + first - lo
        for i, (a, n) in enumerate(at):
            end = hi
            for a2, _ in at[i + 1:]:
                if a2 > a:
                    end = a2
                    break
            sizes[by_name[n]] = sizes.get(by_name[n], 0) + end - a
    return sizes, rest


def sizes(b: RC.Build) -> List[str]:
    out = []
    ms = module_sizes(b)
    for name, budget in BUDGETS.items():
        out.append('%-8s %5d of %5d B (docs/GAME.md 4.7)' % (
            name, ms.get(name, 0), budget))
    core = [b.segments[s] for s in ('GCORE', 'LOADW') if s in b.segments]
    lo, hi = min(c[0] for c in core), max(c[1] for c in core)
    out.append('the core $%04X-$%04X: %d of %d B' % (
        lo, hi, hi + 1 - lo, GL.WR['CORE'][1] - GL.WR['CORE'][0]))
    for n, glo, ghi, data in groups_of(b):
        slot = 1 if glo == GL.WR['SLOT1'][0] else 2
        room = GL.SLOTS[slot][1] - GL.SLOTS[slot][0]
        out.append('group %d (slot %d) %d of %d B' % (n, slot, len(data),
                                                      room))
    lo, hi = b.segments['DRIVER']
    out.append('the driver $%04X-$%04X: %d of %d B (card $E000-$EDFF)' % (
        lo, hi, hi + 1 - lo, 0x0E00))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--sizes', action='store_true')
    parser.add_argument('--image', default='skel')
    args = parser.parse_args(argv)
    if args.sizes:
        b = load_build(GAME / args.image, args.image)
        print('\n'.join(sizes(b)))
        return 0
    parser.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
