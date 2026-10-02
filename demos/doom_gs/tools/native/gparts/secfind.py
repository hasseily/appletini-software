#!/usr/bin/env python3
"""Part secfind's checkpoint (milestone 10, docs/GAME.md 2.4 row secfind,
3.5; docs/game-parts/secfind.md): routine mode on the part's entries, its
synthetic cases, the exhaustive check of its arithmetic helper and its
planted bugs.

Usage:  python3 tools/native/gparts/secfind.py --log [--runs demo3,...]
        python3 tools/native/gparts/secfind.py --capture [--runs ...]
        python3 tools/native/gparts/secfind.py --synthetic [--jobs 2]
        python3 tools/native/gparts/secfind.py --check [--jobs 2]
                [--keys FILE:LABEL,...] [--sample K] [--json FILE]
        python3 tools/native/gparts/secfind.py --mod3
        python3 tools/native/gparts/secfind.py --plants [--keys NAME,...]
        python3 tools/native/gparts/secfind.py --report

Everything it writes is under build/native/game/secfind/ (the part's own
directory): the thinker logs (thinkers/RUN.json.z), the cases
(cases/RUN/ROUTINE/hNNNNNNNN.case.z and each run's base.ram.z, through
tools/native/gamecap.py with its case directory pointed here), report.json.
The shared outputs (build/native/game/shared/: the survey, the includes,
the manifests) are read only.

--log: the thinkers are entered by upstream's walk through `callFn`
(`JML [FN_P]`, p_tick65.s), which ref816's --capture does not count as a
call of the thinker: a call log of callFn (entry and return) with the four
thinkers of the part (entry only, jumps=1) gives the callFn hits that are
light and scroll thinker calls, with their tics.

--capture: the cases, GAME.md 2.4's minimums: every call of an entry with
fewer than 300 calls over the five survey runs, else 300 spread evenly
over them (plus the calls whose path no chosen call takes, by the path
classes of paths()); the thinkers through callFn's hits.

--synthetic: the synthetic calls (synthetic_plan, thinker_plan), run on
ref816 (--call on an in-play state of each of the nine maps, a captured
P_UpdateSpecials of the tour; --load of the arguments, --reg A) and kept
with their writes in synthetic/e1mN.json.z and synthetic/thinkers.json.z:
the four finders on every sector, P_CheckTag, P_FindSectorFromLineTag's
chains (from -1, then from each sector found) and EV_LightTurnOn (bright
0, 35 with lnLight, 255) on the lines with a tag or a special,
P_UpdateSpecials with leveltime from 32,767 up (and a few negative), the
switch timers ending on each place of a texture, the light thinkers at
their limits.

--check: every case of every entry and every synthetic call, from both
poisoned machines ($A5, $5A), under f121 and under fastpath (four runs),
compared with ref816 in gcanon.py's routine mode (exclusions R1-R6 only),
the declared outputs of src/native/game/secfind/args.json compared, the
sound events compared (R6), the write log checked for stray writes; the
routine's cycles from its entry to its return. Writes report.json.

--mod3: upstream's mod3 (p_spec65.s) on every 16-bit input (a 65816 loop
run by ref816 --call) against the native mod3 on every input (the test
routine sf_t_mod3), and the 100,000 seeded random inputs with 0, 1,
$FFFF, $7FFF, $8000 among them.

--plants: each planted bug of GAME.md 2.4 built from a scratch copy of the
part's sources in a temporary directory (deleted), run on its named
check, which must fail.
"""

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, \
    Sequence, Set, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))

from bridge import memory as bmem, upstream  # noqa: E402
from bridge.port import PortReader, PortWriter  # noqa: E402
from native import gamecap as GC, gameroutine as GR, gcanon, \
    glayout as GL, grun as G, llayout as LL, rlayout as RL  # noqa: E402
from ref816 import bounded, calls as CL, title  # noqa: E402

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'secfind'
OUT = GL.GAME / PART
CASES = OUT / 'cases'
LOGS = OUT / 'thinkers'
REPORT = OUT / 'report.json'
ARGS = SRC / 'game' / PART / 'args.json'
PART_SRC = SRC / 'game' / PART
IMAGE = 'ptest'
GC.CASES = CASES                # the part's own case directory

CALLFN = 'p_tick65.s:callFn'
THINKERS = {'p_lights65.s:T_LightFlash': 'lightflash',
            'p_lights65.s:T_StrobeFlash': 'strobe',
            'p_lights65.s:T_Glow': 'glow',
            'p_spec65.s:T_Scroll': 'scroll'}
FINDERS = ('p_spec65.s:P_FindLowestFloorSurrounding',
           'p_spec65.s:P_FindHighestFloorSurrounding',
           'p_spec65.s:P_FindLowestCeilingSurrounding',
           'p_floor65.s:P_FindNextHighestFloor')
DIRECT = ('p_spec65.s:getNextSector',) + FINDERS + (
    'p_spec65.s:P_FindSectorFromLineTag', 'p_spec65.s:P_CheckTag',
    'p_spec65.s:P_UpdateSpecials', 'p_lights65.s:EV_LightTurnOn')
ENTRIES = DIRECT + tuple(THINKERS) + ('p_switch65.s:lnLight',)
MINIMUM = 300
FILLS = (0xA5, 0x5A)
PROFILES = ('f121', 'fastpath')
RUN_CYCLES = 50_000_000         # a routine call's run: far more than any
BATCH = 60                      # captures a ref816 run
LOG_LIMIT = 8 << 30


class PartError(Exception):
    pass


def say(text: str) -> None:
    print(text, flush=True)


# ---------------------------------------------------------------------------
# What the part needs of build/
# ---------------------------------------------------------------------------

def missing() -> Optional[str]:
    """Why the checkpoint cannot run (None: it can)."""
    if not (BUILD / 'upstream' / 'src' / 'iigs').exists():
        return 'no build/upstream (python3 tools/fetch_upstream.py)'
    if not title.MACHINE.exists() or not title.MEMORY.exists():
        return 'no ref816 (make -C tools/ref816; tools/ref816/make_image.py)'
    if not G.A2VM.exists():
        return 'no a2vm (make -C tools/a2vm)'
    for p in (GL.SHARED / 'gen' / 'ggame.inc', GL.SHARED / 'placement.json',
              GL.SHARED / 'native-game-1.json'):
        if not p.exists():
            return ('no %s (make -s -C src/native -f game.mk shared '
                    'ROOT=$PWD)' % p.relative_to(ROOT))
    for run in GC.RUNS:
        if GC.survey_of(run) is None:
            return ('no survey of %s (python3 tools/native/gamecap.py '
                    '--survey)' % run)
    if not GR.have_bases():
        return ('no level bases build/native/levels/setup/ (python3 '
                'tools/native/level_check.py --setup)')
    return None


def build(root: Path = ROOT, game: Optional[Path] = None,
          source: Path = SRC) -> Path:
    """The part's test image (make -f game.mk part P=secfind); its
    directory."""
    variables = ['P=%s' % PART]
    if game is not None:
        variables.append('GAME=%s' % game)
    G.make('part', variables, source)
    return (game or GL.GAME) / PART


# ---------------------------------------------------------------------------
# The thinker logs (--log)
# ---------------------------------------------------------------------------

def thinker_log(run: str) -> Dict[str, Any]:
    """callFn's hits that are calls of the part's thinkers in `run`, by
    kind: [[hit, tic], ...]."""
    table = CL.Linkmap()
    names = {k: k for k in THINKERS}
    found: Dict[str, List[List[int]]] = {k: [] for k in THINKERS}
    state = {'tic': -1, 'calls': 0}

    def reader(handle) -> None:
        first = json.loads(handle.readline())
        if first.get('format') != CL.FORMAT:
            raise PartError('not a call log')
        rnames = [r['name'] for r in first['routines']]
        by_call: Dict[int, str] = {}
        for raw in handle:
            line = json.loads(raw)
            if line.get('end'):
                break
            name = rnames[line['routine']]
            if name == GC.TIC_NAME:
                state['tic'] = int.from_bytes(
                    bytes.fromhex(line['in']['mem'][0]), 'little')
            elif name in names:
                by_call[line['parent']] = name
            elif name == CALLFN:
                state['calls'] += 1
                k = by_call.pop(line['call'], None)
                if k is not None:
                    found[k].append([line['hit'], state['tic']])
    routines = ['%s,name=%s,in=_g_gametic:4,entry=1' % (GC.TICKER,
                                                        GC.TIC_NAME),
                '%s,name=%s' % (CALLFN, CALLFN)]
    routines += ['%s,name=%s,entry=1,jumps=1' % (k, k) for k in THINKERS]
    GC.check_disk()
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-secfind-log-',
                                 dir=str(BUILD)))
    try:
        fifo = work / 'calls.fifo'
        os.mkfifo(str(fifo))
        opts = CL.options(routines, fifo, table) + ['--call-log-limit',
                                                    str(LOG_LIMIT)]
        r = GC.machine(run, work, opts, reader=reader, fifo=fifo)
        if r['problems']:
            raise PartError('%s: %s' % (run, '; '.join(r['problems'])))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    sv = GC.survey_of(run)
    for k, got in found.items():
        want = sv['routines'][k]['calls'] if sv else None
        if want is not None and want != len(got):
            raise PartError('%s %s: %d calls logged, the survey has %d' % (
                run, k, len(got), want))
    out = {'format': 'secfind-thinkers 1', 'run': run,
           'callfn_calls': state['calls'], 'calls': found}
    LOGS.mkdir(parents=True, exist_ok=True)
    (LOGS / (run + '.json.z')).write_bytes(zlib.compress(
        json.dumps(out, separators=(',', ':')).encode(), 6))
    return out


def load_log(run: str) -> Optional[Dict[str, Any]]:
    p = LOGS / (run + '.json.z')
    if not p.exists():
        return None
    return json.loads(zlib.decompress(p.read_bytes()))


# ---------------------------------------------------------------------------
# The calls and the choice (GAME.md 2.4's minimums)
# ---------------------------------------------------------------------------

def calls_of(key: str) -> List[Tuple[str, int, int]]:
    """Every call of an entry over the survey's runs: (run, hit, tic); a
    thinker's hits are callFn's."""
    out: List[Tuple[str, int, int]] = []
    for run in GC.RUNS:
        if key in THINKERS:
            lg = load_log(run)
            if lg is None:
                raise PartError('no thinker log of %s (--log)' % run)
            out += [(run, h, t) for h, t in lg['calls'][key]]
        else:
            sv = GC.survey_of(run)
            r = sv['routines'].get(key) if sv else None
            if r:
                out += [(run, i + 1, t) for i, t in enumerate(r['tic'])]
    return out


def chosen(key: str, n: int = MINIMUM) -> List[Tuple[str, int, int]]:
    calls = calls_of(key)
    if len(calls) <= n:
        return calls
    return [calls[(i * len(calls)) // n] for i in range(n)]


# beyond the minimum: the tour's P_UpdateSpecials every TOUR_STEP-th call,
# so that every map of the nine has in-play states (the synthetic cases'
# bases, synthetic())
TOUR_STEP = 10


def extras(key: str) -> List[Tuple[str, int, int]]:
    if key != 'p_spec65.s:P_UpdateSpecials':
        return []
    sv = GC.survey_of('tour')
    tics = sv['routines'][key]['tic'] if sv else []
    return [('tour', h, tics[h - 1]) for h in range(1, len(tics) + 1,
                                                    TOUR_STEP)]


def selection(key: str) -> List[Tuple[str, int, int]]:
    """The calls of an entry the checkpoint runs: chosen() and extras()."""
    out = list(chosen(key))
    seen = {(r, h) for r, h, _ in out}
    out += [c for c in extras(key) if (c[0], c[1]) not in seen]
    return out


def case_key(key: str) -> str:
    """The routine whose cases hold an entry's calls (callFn for a
    thinker)."""
    return CALLFN if key in THINKERS else key


def case_path(run: str, key: str, hit: int) -> Path:
    return GC.case_dir(run, case_key(key)) / ('h%08d.case.z' % hit)


def capture(keys: Sequence[str] = ENTRIES, runs: Sequence[str] = GC.RUNS,
            extra: Optional[Dict[str, List[Tuple[str, int, int]]]] = None,
            batch: int = BATCH) -> int:
    """The chosen calls' cases (those already made are kept)."""
    made = 0
    want: Dict[Tuple[str, str], Dict[int, int]] = {}
    for key in keys:
        if key == 'p_switch65.s:lnLight':
            continue
        for run, hit, tic in selection(key) + list((extra or {}).get(key,
                                                                    [])):
            want.setdefault((run, case_key(key)), {})[hit] = tic
    for (run, ck), hits in sorted(want.items()):
        if run not in runs:
            continue
        todo = sorted(h for h in hits if not (GC.case_dir(run, ck) / (
            'h%08d.case.z' % h)).exists())
        if not todo:
            continue
        top = max(todo)
        tics = [hits.get(h, -1) for h in range(1, top + 1)]
        start = time.time()
        got = GC.capture(run, ck, todo, tics, batch=batch, say=say)
        made += len(got)
        say('%s %s: %d cases (%.0f s)' % (run, ck, len(got),
                                          time.time() - start))
    return made


def cases_of(key: str, sample: int = 1) -> List[Path]:
    """The chosen calls' case files that exist (every sample-th)."""
    out = []
    for run, hit, _ in selection(key):
        p = case_path(run, key, hit)
        if p.exists():
            out.append(p)
    return out[::sample]


# ---------------------------------------------------------------------------
# args.json
# ---------------------------------------------------------------------------

def args() -> Dict[str, Dict[str, Any]]:
    d = json.loads(ARGS.read_text())
    if d.get('format') != GR.ARGS_FORMAT:
        raise PartError('%s is not %s' % (ARGS, GR.ARGS_FORMAT))
    return d['entries']


# ---------------------------------------------------------------------------
# One case: the reference's side
# ---------------------------------------------------------------------------

class Ref:
    """A case's reference: its canonical states at the entry and the
    return (the return's decoded only when the call wrote a byte the
    reader reads at the entry: the state is otherwise the entry's)."""

    def __init__(self, case: GC.Case):
        self.case = case
        self.table = CL.Linkmap()
        self.up = GR._Light(case)
        tracked = _ByteTracked(case.entry.banks)
        self.r_in = upstream.Reader(tracked, tic=True)
        self.s_in = self.r_in.read()
        self.read_bytes = tracked.bytes
        wrote = set()
        for a, n in case.header['writes']:
            wrote.update(range(a, a + n))
        self.changed = bool(wrote & self.read_bytes)
        if self.changed:
            self.r_out = upstream.Reader(case.after, tic=True)
            self.s_out = self.r_out.read()
        else:
            self.r_out, self.s_out = self.r_in, self.s_in
        self.gamemap = case.entry.u16(self.table.address(GR.TIC_GAMEMAP))
        self.problems = self.r_in.problems + (self.r_out.problems if
                                              self.changed else [])

    def source(self, text: str, when: str = 'in') -> bytes:
        return GR.Upstream.source(self.up, text, when)

    def ref(self, pointer: int, kinds: Tuple[str, ...], when: str = 'in'):
        r = self.r_in if when == 'in' else self.r_out
        ref, why = r.classify(pointer & 0xFFFFFF, kinds)
        if ref is None and pointer & 0xFFFFFF:
            raise PartError('$%06X is no %s (%s)' % (pointer, kinds, why))
        return ref


class _ByteTracked(bmem.Memory):
    """A memory that records each byte read."""

    def __init__(self, banks):
        super().__init__()
        self.banks = banks
        self.bytes: Set[int] = set()

    def read(self, address: int, length: int) -> bytes:
        self.bytes.update(range(address, address + length))
        return super().read(address, length)

    def u8(self, address: int) -> int:
        self.bytes.add(address)
        return super().u8(address)

    def uint(self, address: int, size: int) -> int:
        self.bytes.update(range(address, address + size))
        return int.from_bytes(super().read(address, size), 'little')


# ---------------------------------------------------------------------------
# One case: the native side
# ---------------------------------------------------------------------------

def native_value(mf, kind: str, ref) -> int:
    """A reference's native value: a sector's or a line's number, a
    special's or a mobj's handle (the manifest's handles); NULL all ones."""
    if ref is None:
        return 0xFFFF
    if kind in ('sector', 'line'):
        return ref.id
    return GR.handle_of(mf, ref)


def kinds_of(kind: str) -> Tuple[str, ...]:
    return ('mobj', 'zmobj') if kind == 'mobj' else (kind,)


class _Seen:
    """Records the bytes a PortReader reads of a PortMemory."""

    def __init__(self, pm):
        self.bytes: Set[int] = set()
        orig_read, orig_u8, orig_uint = pm.read, pm.u8, pm.uint
        seen = self.bytes

        def read(address: int, length: int) -> bytes:
            seen.update(range(address, address + length))
            return orig_read(address, length)

        def u8(address: int) -> int:
            seen.add(address)
            return orig_u8(address)

        def uint(address: int, size: int) -> int:
            seen.update(range(address, address + size))
            return orig_uint(address, size)
        pm.read, pm.u8, pm.uint = read, u8, uint


def read_native(mf, pm) -> Tuple[Dict[str, Any], Set[int]]:
    """The native canonical state of a PortMemory and the bytes read."""
    seen = _Seen(pm)
    return PortReader(mf).read(pm), seen.bytes


def image_memory(img: 'G.Image', banks: Iterable[int]):
    """The machine an Image starts as (main $0000-$BFFF and the aux banks
    `banks`), as the bridge's PortMemory."""
    from bridge.memory import PortMemory
    pm = PortMemory()
    want = set(banks)
    for kind, bank, address, data in img.recs:
        if address >= 0xC000:
            continue
        data = bytes(data[:0xC000 - address])
        if kind == 0:
            pm.write(bmem.MAIN | address, data)
        elif kind == 1 and bank in want:
            pm.write((bank << 16) | address, data)
    return pm


# the part's routines that the part table does not name take the group of
# the one they go with (secfind.s: around, request 4)
ALIAS_GROUP = {'around': 'nextSector'}


class Native:
    """The part's image: its build, the driver's return address after the
    routine (the cycles' end), each routine's group (the build's
    gplace.inc: grun.run takes the first group whose slot range holds the
    entry's address, which is ambiguous for a paged routine, request 7)."""

    def __init__(self, obj: Path, name: str = IMAGE):
        self.obj = obj
        self.b = G.load_build(obj, name)
        self.ret = self._after_call(self.b.labels['call_entry'])
        self.groups: Dict[str, int] = {}
        for line in (obj / 'gen' / 'gplace.inc').read_text().splitlines():
            f = line.split()
            if len(f) == 3 and f[0].startswith('GP_') and \
                    f[0].endswith('_G') and f[1] == '=':
                self.groups[f[0][3:-2]] = int(f[2])

    def group(self, name: str) -> int:
        return self.groups[ALIAS_GROUP.get(name, name)]

    def _after_call(self, target: int) -> int:
        lo, hi = self.b.segments['DRIVER']
        data = (self.b.obj / ('%s.lce' % self.b.name)).read_bytes()
        code = data[lo - 0xE000:hi + 1 - 0xE000]
        pat = bytes([0x20, target & 0xFF, target >> 8])
        at = code.find(pat)
        if at < 0 or code.find(pat, at + 1) >= 0:
            raise PartError('the driver\'s jsr call_entry')
        return lo + at + 3


# the write log: main but W (W is the tic phase's scratch, R1) and every
# aux bank
LOG_RANGES = 'main:0000-5FFF,aux0-127:0000-BFFF'
LOG_MAIN_END = 0x6000
R1_MAIN = [(0x0000, 0x0200)]                    # zero page, the stack
R1_MAIN += [(lo, hi) for _, lo, hi, _ in GL.MAIN_TIC]
R1_MAIN += [(GL.GS_STATUS, GL.GS_ARG + 2)]
# the test state of the globals block (GAME.md 1.5: the lockstep and test
# globals GT_DIV0 .. GT_FLAGS, the sound log's count among them)
R1_MAIN += [(LL.G['GT_DIV0'], LL.G['GT_FLAGS'] + 1)]
# the banks of the cached kinds' records and of the planes: a write-back
# rewrites a whole record or page, so a same-value write there is no stray
RECORD_BANKS = {LL.MOBJ[0], LL.MOBJ[1], LL.MOBJ[2], LL.ZONE0, LL.LVG0,
                LL.LVG1, RL.LVMAP, LL.MOBJP, RL.RTHINGS.bank if hasattr(
                    RL.RTHINGS, 'bank') else LL.MOBJ[0]}


class Writes(NamedTuple):
    canonical: int              # writes that change a canonical byte
    stray: List[str]            # the first strays
    strays: int


def check_writes(log: Path, canon: Set[int], start: int) -> Writes:
    """The run's CPU writes (the whole run, the driver's included): those
    that change a canonical byte (canon: the bytes the native reader reads),
    and the strays: neither scratch (R1: zero page, stack, the tic phase's
    main ranges, the stop codes; W is not logged; GTEST, the test logs), nor
    canonical, nor a same-value write into a record bank."""
    changed = 0
    stray: List[str] = []
    n = 0
    with open(str(log)) as handle:
        for line in handle:
            if not line.startswith('w '):
                continue
            f = line.split()
            storage = f[5]
            old, new = int(f[8], 16), int(f[9], 16)
            before = int(f[1]) < start      # the driver's, before the call
            if storage == 'main':
                off = int(f[7], 16)
                a = bmem.MAIN | off
                if a in canon:
                    changed += old != new
                    continue
                if any(lo <= off < hi for lo, hi in R1_MAIN):
                    continue
            elif storage == 'aux':
                bk, off = int(f[6]), int(f[7], 16)
                a = (bk << 16) | off
                if a in canon:
                    changed += old != new
                    continue
                if bk == LL.GTEST or (bk in RECORD_BANKS and old == new):
                    continue
            if before:
                continue
            n += 1
            if len(stray) < 6:
                stray.append('%s %s %s %02X->%02X pc %s' % (
                    storage, f[6], f[7], old, new, f[3]))
    return Writes(changed, stray, n)


class Prep:
    """A case made ready for its runs: the reference's states, the
    native pre-state's records (the port writer's), the inputs; the
    native pre-state and its canonical places by fill (cached)."""

    def __init__(self, case: GC.Case, key: str, spec: Dict[str, Any],
                 ref: Optional[Ref] = None,
                 port: Optional[Tuple[list, list]] = None,
                 pre: Optional[Dict[int, Any]] = None):
        self.case, self.key, self.spec = case, key, spec
        self.ref = ref or Ref(case)
        self.mf, self.header, self.banks = GR.manifest(self.ref.gamemap)
        self.skip = gcanon.skips('routine', self.ref.s_in)
        if port is None:
            pm = G.tracked_memory()
            PortWriter(self.mf).write(gcanon.strip(self.ref.s_in, self.skip),
                                      pm)
            port = (G.port_records(pm), GR.derived(pm, self.header))
        self.port = port
        self.regs, self.pokes = self.inputs()
        # the native pre-state by fill: shared by the calls of one base
        # when no input reaches main past the zero page (Shared)
        if pre is not None and any(a >= 0x100 for a, _ in self.pokes):
            pre = None
        self.pre: Dict[int, Tuple[Dict[str, Any], Set[int]]] = \
            pre if pre is not None else {}

    def inputs(self) -> Tuple[List[int], List[Tuple[int, bytes]]]:
        regs = [0, 0, 0, 0x34]
        pokes: List[Tuple[int, bytes]] = []
        for item in self.spec.get('in', []):
            data = self.ref.source(item['from'])
            kind = item.get('as')
            if kind:
                r = self.ref.ref(int.from_bytes(data, 'little'),
                                 kinds_of(kind))
                data = native_value(self.mf, kind, r).to_bytes(2, 'little')
            to = item['to']
            n = item.get('bytes', len(data))
            if to in ('a', 'x', 'y'):
                regs['axy'.index(to)] = data[0]
            elif to == 'ax':
                regs[0], regs[1] = data[0], data[1]
            elif to.startswith('zp:'):
                pokes.append((GR.zp_address(to[3:]),
                              data[:n].ljust(n, b'\0')))
            elif to.startswith('main:'):
                pokes.append((LL.G[to[5:]], data[:n].ljust(n, b'\0')))
            else:
                raise PartError('an input destination %r' % to)
        return regs, pokes

    def image(self, nat: Native, fill: int) -> 'G.Image':
        img = G.Image(nat.b, fill, store=True)
        img.recs += GR.base_records(self.ref.gamemap)
        img.recs += self.port[0]
        img.recs += self.port[1]
        for a, d in self.pokes:
            img.main(a, d)
        return img

    def pre_state(self, img: 'G.Image', fill: int
                  ) -> Tuple[Dict[str, Any], Set[int]]:
        if fill not in self.pre:
            st, seen = read_native(self.mf, image_memory(img, self.banks))
            if any(a & bmem.MAIN and (a & 0xFFFF) >= LOG_MAIN_END
                   for a in seen):
                raise PartError('a canonical byte in W, which the write log '
                                'leaves out')
            self.pre[fill] = (st, seen)
        return self.pre[fill]


# the canonical comparisons of the states shared by a base's calls, by the
# states' identities (the states are kept with them, so the ids stay theirs)
_DIFFS: Dict[Tuple[int, int], Tuple[List[str], Any, Any]] = {}


def snapshot_cycles(work: Path, name: str) -> Optional[int]:
    p = work / (name + '.json')
    if not p.exists():
        return None
    return json.loads(p.read_text()).get('cycles')


def run_one(prep: Prep, nat: Native, fill: int, profile: str,
            keep: Optional[Path] = None) -> Dict[str, Any]:
    """One run of a case: its result (equal, the differences, the cycles of
    the routine from its entry to its return, the lowest S, the strays)."""
    spec = prep.spec
    res: Dict[str, Any] = {'case': prep.case.path.name if prep.case.path
                           else prep.case.header.get('note', 'synthetic'),
                           'entry': prep.key, 'fill': '%02x' % fill,
                           'profile': profile, 'ok': False}
    if prep.ref.problems:
        res['error'] = 'bridge: ' + '; '.join(prep.ref.problems[:3])
        return res
    img = prep.image(nat, fill)
    pre, canon = prep.pre_state(img, fill)
    entry = nat.b.labels[spec['native']]
    img.poke_word('dg_entry', entry)
    img.poke_label('dg_grp', bytes([nat.group(spec['native'])]))
    events = ['pc %X@1 snapshot start' % entry,
              'pc %X@1 snapshot ret' % nat.ret]
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-secfind-', dir=str(BUILD)))
    try:
        r = G.run(img, work, GL.MODES['ROUTINE'], None,
                  regs=tuple(prep.regs), events=events,
                  banks=list(prep.banks) + [LL.GTEST],
                  profile=profile, write_log=LOG_RANGES, cycles=RUN_CYCLES)
        ended = r.ended()
        res['ended'] = ended
        res['lowest_s'] = r.state.get('lowest_s')
        if ended != 'halt':
            p = work / 'crash.img'
            if p.exists():
                res['stop'] = G.stop_codes(G.load_snapshot(p))
            return res
        c0, c1 = snapshot_cycles(work, 'start'), snapshot_cycles(work, 'ret')
        res['cycles'] = c1 - c0 if c0 is not None and c1 is not None \
            else None
        if c0 is None:
            raise PartError('no snapshot at the routine\'s entry')
        w = check_writes(work / 'writes.log', canon, c0)
        res['stray'] = w.strays
        res['stray_first'] = w.stray
        m = G.load_snapshot(work / 'done.img')
        if keep is not None:
            shutil.copy(str(work / 'done.img'), str(keep))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    if w.canonical:
        from native import setupcheck as SC
        nat_state = PortReader(prep.mf).read(SC.port_memory(m))
        res['decoded'] = True
    else:
        nat_state = pre
    if prep.ref.changed or w.canonical:
        diff = gcanon.compare(prep.ref.s_out, nat_state, 'routine')
    else:
        # neither side changed a canonical byte: the entry states' diff,
        # the same for every call of a base that shares them
        memo = (id(prep.ref.s_out), id(nat_state))
        if memo not in _DIFFS:
            _DIFFS.clear()
            _DIFFS[memo] = (gcanon.compare(prep.ref.s_out, nat_state,
                                           'routine'),
                            prep.ref.s_out, nat_state)
        diff = list(_DIFFS[memo][0])
    diff += outputs(prep, nat, m)
    got, want = sounds(m), expected_sounds(prep)
    res['sounds'] = len(got)
    if got != want:
        diff.append('sound events %s, expected %s' % (got[:4], want[:4]))
    if w.strays:
        diff.append('%d stray writes: %s' % (w.strays, w.stray))
    res['diff'] = diff[:12]
    res['ok'] = not diff
    return res


def sounds(m) -> List[Tuple[int, int, int, int]]:
    """The native sound events of the call (ghook.s: tic, kind, sound,
    origin; GTEST GT_SOUNDS, the count at GT_SNDLOG)."""
    n = m.main[LL.G['GT_SNDLOG']] | m.main[LL.G['GT_SNDLOG'] + 1] << 8
    log = m.aux.get(LL.GTEST)
    out = []
    for k in range(n):
        a = GL.GTB['GT_SOUNDS'] + GL.SOUND_EVENT * k
        e = bytes(log[a:a + GL.SOUND_EVENT])
        out.append((e[0] | e[1] << 8, e[2], e[3], e[4] | e[5] << 8))
    return out


def expected_sounds(prep: Prep) -> List[Tuple[int, int, int, int]]:
    """The sound events upstream's call makes (R6: the sound channels are
    outside the canonical model, the events are compared instead): one
    S_StartSound2(soundorg, sfx_swtchn) for each switch whose timer ends
    in P_UpdateSpecials, in the buttons' order."""
    if prep.key != 'p_spec65.s:P_UpdateSpecials':
        return []
    s = prep.ref.s_in
    tic = s['globals']['g_game65.s:_g_gametic'] & 0xFFFF
    out = []
    for k in sorted(s['objects']['button']):
        b = s['objects']['button'][k]
        if b['btimer'] == 1:
            org = b['soundorg']
            out.append((tic, 1, uconst()['UC_SFX_SWTCHN'],
                        0x8000 | (org.id if org is not None else 0xFF)))
    return out


def outputs(prep: Prep, nat: Native, m) -> List[str]:
    """The declared outputs against upstream's."""
    lab = nat.b.labels
    regs = {'a': G.card_byte(m, lab['dg_ra']),
            'x': G.card_byte(m, lab['dg_rx']),
            'y': G.card_byte(m, lab['dg_ry'])}
    out = []
    for item in prep.spec.get('out', []):
        nv = item['native']
        n = item.get('bytes', 2)
        if nv == 'ax':
            value = regs['a'] | regs['x'] << 8
        elif nv in regs:
            value = regs[nv]
        elif nv.startswith('zp:'):
            a = GR.zp_address(nv[3:])
            value = int.from_bytes(bytes(m.main[a:a + n]), 'little')
        elif nv.startswith('main:'):
            a = LL.G[nv[5:]]
            value = int.from_bytes(bytes(m.main[a:a + n]), 'little')
        else:
            raise PartError('a native output %r' % nv)
        raw = prep.ref.source(item['upstream'], 'out')
        kind = item.get('as')
        if kind:
            r = prep.ref.ref(int.from_bytes(raw, 'little'), kinds_of(kind),
                             'out')
            want = native_value(prep.mf, kind, r)
        else:
            want = int.from_bytes(raw, 'little')
        mask = (1 << (8 * n)) - 1
        if value & mask != want & mask:
            out.append('output %s (%s): %X, upstream %X' % (
                nv, item['upstream'], value & mask, want & mask))
    return out


def run_case(case: GC.Case, key: str, nat: Native,
             fills: Sequence[int] = FILLS,
             profiles: Sequence[str] = PROFILES,
             spec: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    spec = spec or args()[key]
    try:
        prep = Prep(case, key, spec)
    except Exception as error:          # reported, never hidden
        return [{'case': case.path.name if case.path else 'synthetic',
                 'entry': key, 'ok': False,
                 'error': '%s: %s' % (type(error).__name__, error)}]
    out = []
    for fill in fills:
        for profile in profiles:
            try:
                out.append(run_one(prep, nat, fill, profile))
            except Exception as error:
                out.append({'case': case.path.name if case.path else
                            'synthetic', 'entry': key, 'fill': '%02x' % fill,
                            'profile': profile, 'ok': False,
                            'error': '%s: %s' % (type(error).__name__,
                                                 error)})
    return out


# ---------------------------------------------------------------------------
# The paths a call takes (the coverage of GAME.md 3.5 step 2), from the
# reference's canonical state at its entry
# ---------------------------------------------------------------------------

NOTAGS = (1, 26, 27, 28, 31, 32, 33, 34, 35, 97, 11, 51, 48)


def path_of(key: str, ref: Ref) -> str:
    s = ref.s_in
    o = s['objects']

    def obj(kind_, text):
        r = ref.ref(int.from_bytes(ref.source(text), 'little'), (kind_,))
        return r, (o[kind_][r.id] if r is not None else None)
    if key in THINKERS:
        kind = THINKERS[key]
        _, t = obj(kind, 'dp:_Dp:4')
        if kind == 'scroll':
            return 'scroll'
        light = o['sector'][t['sector'].id]['lightlevel']
        if kind == 'lightflash':
            if t['count'] != 1:
                return 'count'
            return 'max-to-min' if light == t['maxlight'] else 'to-max'
        if kind == 'strobe':
            if t['count'] != 1:
                return 'count'
            return 'min-to-max' if light == t['minlight'] else 'to-min'
        d = t['direction']
        if d == -1:
            v = light - 8
            return 'down-turn-at' if v == t['minlight'] else \
                'down-turn' if v < t['minlight'] else 'down'
        if d == 1:
            v = light + 8
            return 'up-turn-at' if v == t['maxlight'] else \
                'up-turn' if v > t['maxlight'] else 'up'
        return 'still'
    if key == 'p_spec65.s:P_UpdateSpecials':
        b = [x['btimer'] for x in o['button'].values()]
        lt = s['globals']['p_think65.s:_g_leveltime']
        parts = []
        if any(x == 1 for x in b):
            parts.append('button-end')
        elif any(x > 1 for x in b):
            parts.append('button-tick')
        if lt & 0x8000:
            parts.append('leveltime-bit15')
        if lt < 0:
            parts.append('leveltime-negative')
        return '+'.join(parts) or 'plain'
    if key == 'p_spec65.s:getNextSector':
        lr, line = obj('line', 'dp:_Dp:4')
        sr, _ = obj('sector', 'dp:_Dp+4:4')
        front = o['side'][line['sidenum'][0]]['sector'].id
        if front != sr.id:
            return 'front'
        if line['sidenum'][1] == -1:
            return 'none-one-sided'
        back = o['side'][line['sidenum'][1]]['sector'].id
        return 'none-both' if back == sr.id else 'back'
    if key == 'p_spec65.s:P_CheckTag':
        _, line = obj('line', 'dp:_Dp:4')
        if line['tag']:
            return 'tag'
        return 'no-tag-needed' if line['special'] in NOTAGS else 'none'
    if key == 'p_spec65.s:P_FindSectorFromLineTag':
        start = int.from_bytes(ref.source('a'), 'little', signed=True)
        got = int.from_bytes(ref.source('a', 'out'), 'little', signed=True)
        return '%s-%s' % ('first' if start < 0 else 'next',
                          'none' if got < 0 else 'found')
    if key in ('p_lights65.s:EV_LightTurnOn', 'p_switch65.s:lnLight'):
        bright = int.from_bytes(ref.source('a'), 'little')
        return 'bright-0' if bright == 0 else 'bright'
    return 'call'


# ---------------------------------------------------------------------------
# The synthetic cases (ref816 --call on an in-play state of each map)
# ---------------------------------------------------------------------------

SYN = OUT / 'synthetic'
SYN_FORMAT = 'secfind-synthetic 1'
_UC: Dict[str, int] = {}


def uconst() -> Dict[str, int]:
    if not _UC:
        _UC.update(GL.upstream_constants())
    return _UC


def ref_call(address: int, pokes: Sequence[Tuple[int, bytes]],
             regs: Dict[str, int], work: Path
             ) -> Tuple[Dict[str, Any], List[Tuple[int, bytes]]]:
    """ref816 --call of `address` on work/entry.img with pokes (--load)
    and registers (--reg): the call's state and its writes."""
    cmd = [str(title.MACHINE), str(work / 'entry.img')]
    for i, (a, d) in enumerate(pokes):
        f = work / ('poke%d.bin' % i)
        f.write_bytes(d)
        cmd += ['--load', '%06X:%s' % (a, f)]
    for k, v in regs.items():
        cmd += ['--reg', '%s=%X' % (k, v)]
    cmd += ['--call', '%06X' % address, '--call-writes',
            str(work / 'writes.img'), '--state', str(work / 'state.json'),
            '--cycles', str(RUN_CYCLES)]
    r = bounded.run(cmd, timeout=120, max_bytes=1 << 26,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if r.returncode:
        raise PartError('ref816 --call failed: %s' % r.stdout[-600:])
    state = json.loads((work / 'state.json').read_text())
    if not state['call']['returned']:
        raise PartError('the call did not return')
    return state['call'], GC.image_records(work / 'writes.img')


class MapBase:
    """An in-play state of a map (a captured case): its tables' upstream
    addresses."""

    def __init__(self, path: Path):
        self.path = path
        self.case = GC.load_case(path)
        t = CL.Linkmap()
        self.table = t
        m = self.case.entry
        self.m = m
        self.gamemap = m.u16(t.address(GR.TIC_GAMEMAP))
        self.d = self.case.regs_in['d']
        self.dp = (self.d + t.address('_Dp') - t.direct_page) & 0xFFFF
        self.c = uconst()
        self.sectors = m.u32(t.address('_g_sectors')) & 0xFFFFFF
        self.nsectors = m.u16(t.address('_g_numsectors'))
        self.lines = m.u32(t.address('_g_lines')) & 0xFFFFFF
        self.nlines = m.u16(t.address('_g_numlines'))
        self.sides = m.u32(t.address('_g_sides')) & 0xFFFFFF

    def sector(self, i: int) -> int:
        return self.sectors + i * self.c['US_SEC']

    def line(self, i: int) -> int:
        return self.lines + i * self.c['US_LINE']

    def line_tag(self, i: int) -> int:
        return self.m.u16(self.line(i) + self.c['UO_LINE_TAG'])

    def line_special(self, i: int) -> int:
        return self.m.u16(self.line(i) + self.c['UO_LINE_SPECIAL'])

    def line_side0(self, i: int) -> int:
        return self.m.u16(self.line(i) + self.c['UO_LINE_SIDENUM'])

    def side_sector(self, side: int) -> int:
        p = self.m.u32(self.sides + side * self.c['US_SIDE'] +
                       self.c['UO_SIDE_SECTOR']) & 0xFFFFFF
        return (p - self.sectors) // self.c['US_SEC']

    def side_textures(self, side: int) -> List[int]:
        a = self.sides + side * self.c['US_SIDE'] + \
            self.c['UO_SIDE_TOPTEXTURE']
        return [self.m.u16(a + 2 * k) for k in range(3)]


def sector_address(case: GC.Case, i: int) -> int:
    t = CL.Linkmap()
    return (case.entry.u32(t.address('_g_sectors')) & 0xFFFFFF) + \
        i * uconst()['US_SEC']


def map_bases() -> Dict[int, Path]:
    """A captured P_UpdateSpecials case of each map (the tour's first,
    else a demo's): the in-play states of the synthetic calls."""
    out: Dict[int, Path] = {}
    a = CL.Linkmap().address(GR.TIC_GAMEMAP)
    paths = cases_of('p_spec65.s:P_UpdateSpecials')
    paths.sort(key=lambda p: (p.parent.parent.name != 'tour', str(p)))
    for p in paths:
        gm = GC.load_case(p).entry.u16(a)
        if gm not in out:
            out[gm] = p
    return out


LEVELTIMES = (32767, 32768, 32769, 32775, 32776, 40000, 49151, 49152,
              65535, 65536, 65537, 98303, 98304, 131071, 2 ** 31 - 1, -1,
              -8, -32768, -2 ** 31)


def synthetic_plan(base: MapBase) -> List[Dict[str, Any]]:
    """The synthetic calls on a map's base (P_FindSectorFromLineTag's
    chains are followed as they run, make_synthetic): the four finders on
    every sector; P_CheckTag on every line with a tag or a special (and
    the first four); P_FindSectorFromLineTag from -1 on every line with a
    tag (and the first two); EV_LightTurnOn with bright 0 on every line
    with a tag, 35 (and lnLight) on every line of special 35, 255 on two;
    P_UpdateSpecials at LEVELTIMES; the switch timers ending on each
    place of a texture (button_plan)."""
    out: List[Dict[str, Any]] = []

    def dp_ptr(p: int) -> List[Tuple[int, bytes]]:
        return [(base.dp, (p & 0xFFFFFF).to_bytes(4, 'little'))]
    for s in range(base.nsectors):
        for key in FINDERS:
            out.append({'key': key, 'pokes': dp_ptr(base.sector(s)),
                        'regs': {}, 'note': 'sector %d' % s, 'shared': 1})
    for i in range(base.nlines):
        tag, special = base.line_tag(i), base.line_special(i)
        if tag or special or i < 4:
            out.append({'key': 'p_spec65.s:P_CheckTag',
                        'pokes': dp_ptr(base.line(i)), 'regs': {},
                        'note': 'line %d' % i, 'shared': 1})
        if tag or i < 2:
            out.append({'key': 'p_spec65.s:P_FindSectorFromLineTag',
                        'pokes': dp_ptr(base.line(i)),
                        'regs': {'a': 0xFFFF}, 'note': 'line %d' % i,
                        'shared': 1, 'chain': 1})
        if tag:
            out.append({'key': 'p_lights65.s:EV_LightTurnOn',
                        'pokes': dp_ptr(base.line(i)), 'regs': {'a': 0},
                        'note': 'line %d, bright 0' % i})
        if special == 35:
            for key in ('p_lights65.s:EV_LightTurnOn',
                        'p_switch65.s:lnLight'):
                out.append({'key': key, 'pokes': dp_ptr(base.line(i)),
                            'regs': {'a': 35},
                            'note': 'line %d, special 35' % i})
    tagged = [i for i in range(base.nlines) if base.line_tag(i)]
    for i in tagged[:2]:
        out.append({'key': 'p_lights65.s:EV_LightTurnOn',
                    'pokes': dp_ptr(base.line(i)), 'regs': {'a': 255},
                    'note': 'line %d, bright 255' % i})
    lt = base.table.address('_g_leveltime')
    for v in LEVELTIMES:
        out.append({'key': 'p_spec65.s:P_UpdateSpecials',
                    'pokes': [(lt, (v & 0xFFFFFFFF).to_bytes(4, 'little'))],
                    'regs': {}, 'note': 'leveltime %d' % v})
    out += button_plan(base)
    return out


def button_plan(base: MapBase) -> List[Dict[str, Any]]:
    """P_UpdateSpecials with three buttons set: on lines 0 and 2 ending
    (the timer 1), on line 1 ticking (5); the first's place of the texture
    each of top, middle, bottom and none (7), the third's the bottom; each
    texture one its side does not show."""
    c = base.c
    btn = base.table.address('_g_buttonlist')
    out = []
    for where in (c['UC_TOP'], c['UC_MIDDLE'], c['UC_BOTTOM'], 7):
        pokes = []
        for k, (i, timer) in enumerate(((0, 1), (1, 5), (2, 1))):
            side = base.line_side0(i)
            tex = side_texture_not(base, side)
            sec = base.side_sector(side)
            place = where if k != 2 else c['UC_BOTTOM']
            rec = (base.line(i).to_bytes(4, 'little') +
                   place.to_bytes(2, 'little') + tex.to_bytes(2, 'little') +
                   timer.to_bytes(2, 'little') +
                   (base.sector(sec) + c['UO_SEC_SOUNDORG']).to_bytes(
                       4, 'little'))
            if len(rec) != c['US_BTN']:
                raise PartError('a button is %d bytes' % c['US_BTN'])
            pokes.append((btn + k * c['US_BTN'], rec))
        out.append({'key': 'p_spec65.s:P_UpdateSpecials', 'pokes': pokes,
                    'regs': {}, 'note': 'buttons ending, where %d' % where})
    return out


def side_texture_not(base: MapBase, side: int) -> int:
    used = set(base.side_textures(side))
    for t in range(7, 120):
        if t not in used:
            return t
    raise PartError('no texture')


def make_synthetic(base_path: Path) -> List[Dict[str, Any]]:
    """The map's synthetic calls run on ref816: each record with its call
    state and writes (P_FindSectorFromLineTag's chains followed)."""
    base = MapBase(base_path)
    t = base.table
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-secfind-syn-',
                                 dir=str(BUILD)))
    out: List[Dict[str, Any]] = []
    try:
        entry = base.case.entry.copy()
        entry.header = base.case.entry.header
        (work / 'entry.img').write_bytes(entry.image_bytes())
        todo = synthetic_plan(base)
        while todo:
            rec = todo.pop(0)
            address = t.address(rec['key'])
            call, writes = ref_call(address, rec['pokes'], rec['regs'], work)
            out.append(dict(rec, address=address, call=call,
                            pokes=[[a, d.hex()] for a, d in rec['pokes']],
                            writes=[[a, d.hex()] for a, d in writes],
                            base=str(base_path.relative_to(OUT))))
            if rec.get('chain'):
                got = call['end']['a'] & 0xFFFF
                if got != 0xFFFF:
                    todo.insert(0, dict(rec, regs={'a': got},
                                        note=rec['note'] + ', start %d' %
                                        got))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return out


def thinker_plan() -> List[Tuple[Path, Dict[str, Any]]]:
    """The light thinkers at their limits: a glow's minlight poked to its
    light - 8 (direction -1) or its maxlight to its light + 8 (1), so that
    it turns at the limit exactly; a flash's and a strobe's count poked to
    1 with the light at its limit and off it (both ends of the count)."""
    t = CL.Linkmap()
    out: List[Tuple[Path, Dict[str, Any]]] = []
    for key, kind in THINKERS.items():
        if kind == 'scroll':
            continue
        done: Set[str] = set()
        for p in cases_of(key):
            ref = Ref(GC.load_case(p))
            ptr = int.from_bytes(ref.source('dp:_Dp:4'), 'little') & \
                0xFFFFFF
            th = ref.s_in['objects'][kind][ref.ref(ptr, (kind,)).id]
            sid = th['sector'].id
            light = ref.s_in['objects']['sector'][sid]['lightlevel']
            lev = sector_address(ref.case, sid) + \
                uconst()['UO_SEC_LIGHTLEVEL']
            plans = []
            if kind == 'glow':
                d = th['direction']
                if d == -1 and light >= 8 and 'down' not in done:
                    plans.append(('down', [(ptr + t.address(
                        'p_lights65.s:GL_MINLIGHT'), light - 8)]))
                if d == 1 and 'up' not in done:
                    plans.append(('up', [(ptr + t.address(
                        'p_lights65.s:GL_MAXLIGHT'), light + 8)]))
            else:
                cnt = t.address('p_lights65.s:LF_COUNT' if kind ==
                                'lightflash' else 'p_lights65.s:SF_COUNT')
                limit = th['maxlight' if kind == 'lightflash' else
                           'minlight']
                for name, value in (('at', limit), ('off', limit ^ 0x10)):
                    if name in done or not 0 <= value < 256:
                        continue
                    plans.append((name, [(ptr + cnt, 1), (lev, value)]))
            for name, pk in plans:
                done.add(name)
                out.append((p, {'key': key,
                                'pokes': [(a, (v & 0xFFFF).to_bytes(
                                    2, 'little')) for a, v in pk],
                                'regs': {}, 'note': '%s %s' % (kind, name)}))
            if len(done) >= 2:
                break
    return out


def make_thinker_synthetic() -> List[Dict[str, Any]]:
    out = []
    t = CL.Linkmap()
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-secfind-syn-',
                                 dir=str(BUILD)))
    try:
        for p, rec in thinker_plan():
            c = GC.load_case(p)
            entry = c.entry.copy()
            entry.header = c.entry.header
            (work / 'entry.img').write_bytes(entry.image_bytes())
            call, writes = ref_call(t.address(CALLFN), rec['pokes'], {},
                                    work)
            out.append(dict(rec, address=t.address(CALLFN), call=call,
                            pokes=[[a, d.hex()] for a, d in rec['pokes']],
                            writes=[[a, d.hex()] for a, d in writes],
                            base=str(p.relative_to(OUT))))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return out


def _syn_job(path: str) -> List[Dict[str, Any]]:
    return make_synthetic(Path(path))


def write_synthetic(jobs: int = 2) -> Dict[str, int]:
    """Every synthetic record into SYN/e1mN.json.z and SYN/thinkers.json.z
    (format SYN_FORMAT)."""
    SYN.mkdir(parents=True, exist_ok=True)
    bases = map_bases()
    absent = sorted(set(range(1, 10)) - set(bases))
    if absent:
        raise PartError('no in-play state of E1M%s' % absent)
    counts = {}
    maps = sorted(bases)
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        got = dict(zip(maps, pool.map(_syn_job,
                                      [str(bases[m]) for m in maps])))
    for m, recs in got.items():
        _write_syn('e1m%d' % m, m, recs)
        counts['E1M%d' % m] = len(recs)
    recs = make_thinker_synthetic()
    _write_syn('thinkers', 0, recs)
    counts['thinkers'] = len(recs)
    return counts


def _write_syn(name: str, m: int, recs: List[Dict[str, Any]]) -> None:
    (SYN / (name + '.json.z')).write_bytes(zlib.compress(json.dumps(
        {'format': SYN_FORMAT, 'map': m, 'records': recs},
        separators=(',', ':')).encode(), 6))


def load_synthetic(name: str) -> List[Dict[str, Any]]:
    p = SYN / (name + '.json.z')
    if not p.exists():
        raise PartError('no synthetic cases %s (--synthetic)' % p)
    d = json.loads(zlib.decompress(p.read_bytes()))
    if d.get('format') != SYN_FORMAT:
        raise PartError('%s is not %s' % (p, SYN_FORMAT))
    return d['records']


def synthetic_names() -> List[str]:
    return ['e1m%d' % m for m in range(1, 10)] + ['thinkers']


_BASE_CASES: Dict[str, GC.Case] = {}


def synthetic_case(rec: Dict[str, Any]) -> GC.Case:
    base = rec['base']
    if base not in _BASE_CASES:
        _BASE_CASES.clear()
        _BASE_CASES[base] = GC.load_case(OUT / base)
    b = _BASE_CASES[base]
    entry = b.entry.copy()
    entry.header = b.entry.header
    for a, d in rec['pokes']:
        entry.write(a, bytes.fromhex(d))
    after = entry.copy()
    for a, d in rec['writes']:
        after.write(a, bytes.fromhex(d))
    header = dict(b.header, routine=rec['key'], note=rec['note'],
                  call=rec['call'], hit=0,
                  writes=[[a, len(d) // 2] for a, d in rec['writes']])
    return GC.Case(header, entry, after, None)


# ---------------------------------------------------------------------------
# The checkpoint (--check)
# ---------------------------------------------------------------------------

def derive_ref(base: Ref, case: GC.Case) -> Ref:
    """A Ref of case from base's entry state: their canonical states are
    the same when base.read_bytes holds no byte where they differ."""
    r = Ref.__new__(Ref)
    r.case = case
    r.table = base.table
    r.up = GR._Light(case)
    r.r_in, r.s_in, r.read_bytes = base.r_in, base.s_in, base.read_bytes
    wrote: Set[int] = set()
    for a, n in case.header['writes']:
        wrote.update(range(a, a + n))
    r.changed = bool(wrote & r.read_bytes)
    if r.changed:
        r.r_out = upstream.Reader(case.after, tic=True)
        r.s_out = r.r_out.read()
    else:
        r.r_out, r.s_out = r.r_in, r.s_in
    r.gamemap = base.gamemap
    r.problems = base.problems + (r.r_out.problems if r.changed else [])
    return r


class Shared:
    """The reference's entry state and the port writer's records shared by
    the synthetic calls of one base whose pokes the reader does not read
    (the finders and the tags: only the direct page's arguments differ)."""

    def __init__(self):
        self.base: Optional[str] = None
        self.ref: Optional[Ref] = None
        self.port = None
        self.pre: Dict[int, Any] = {}

    def get(self, rec: Dict[str, Any], case: GC.Case):
        if not rec.get('shared'):
            return None, None, None
        if self.base != rec['base']:
            self.base, self.ref, self.port = rec['base'], Ref(case), None
            self.pre = {}
        pokes: Set[int] = set()
        for a, d in rec['pokes']:
            pokes.update(range(a, a + len(d) // 2))
        if pokes & self.ref.read_bytes:
            return None, None, None
        return derive_ref(self.ref, case), self.port, self.pre


def _check_job(job) -> List[Dict[str, Any]]:
    kind, items, obj, fills, profiles = job
    nat = Native(Path(obj))
    spec_all = args()
    out: List[Dict[str, Any]] = []
    shared = Shared()
    for item in items:
        if kind == 'case':
            key, path = item
            name = '/'.join(Path(path).parts[-3:])
            ref = port = pre = None
            try:
                case = GC.load_case(Path(path))
            except Exception as error:
                out.append({'case': name, 'entry': key, 'ok': False,
                            'error': '%s: %s' % (type(error).__name__,
                                                 error)})
                continue
        else:
            key = item['key']
            name = '%s: %s' % (item['base'], item['note'])
            case = synthetic_case(item)
            ref, port, pre = shared.get(item, case)
        try:
            prep = Prep(case, key, spec_all[key], ref=ref, port=port,
                        pre=pre)
            if kind != 'case' and item.get('shared') and ref is not None:
                shared.port = prep.port
            path = path_of(key, prep.ref)
        except Exception as error:      # reported per case, never hidden
            out.append({'case': name, 'entry': key, 'ok': False,
                        'synthetic': kind != 'case',
                        'error': '%s: %s' % (type(error).__name__, error)})
            continue
        for fill in fills:
            for profile in profiles:
                try:
                    r = run_one(prep, nat, fill, profile)
                except Exception as error:
                    r = {'entry': key, 'fill': '%02x' % fill,
                         'profile': profile, 'ok': False,
                         'error': '%s: %s' % (type(error).__name__, error)}
                r.update(case=name, path=path, synthetic=kind != 'case')
                out.append(r)
    return out


def check_jobs(keys: Sequence[str] = ENTRIES, sample: int = 1,
               synthetic: bool = True, obj: Path = OUT,
               fills: Sequence[int] = FILLS,
               profiles: Sequence[str] = PROFILES,
               names: Optional[Sequence[str]] = None, captured: bool = True,
               select=None, chunk: int = 12) -> List[Tuple]:
    """The checkpoint's jobs: the captured cases of keys (every sample-th)
    and the synthetic records (of names, select(record) true)."""
    jobs: List[Tuple] = []
    if captured:
        for key in keys:
            if key == 'p_switch65.s:lnLight':
                continue
            paths = cases_of(key, sample)
            for i in range(0, len(paths), chunk):
                jobs.append(('case', [(key, str(p)) for p in
                                      paths[i:i + chunk]], str(obj),
                             tuple(fills), tuple(profiles)))
    if synthetic:
        for name in (names or synthetic_names()):
            recs = []
            for key in keys:                # every sample-th of each entry
                recs += [r for r in load_synthetic(name) if r['key'] == key
                         and (select is None or select(r))][::sample]
            for i in range(0, len(recs), 4 * chunk):
                jobs.append(('synthetic', recs[i:i + 4 * chunk], str(obj),
                             tuple(fills), tuple(profiles)))
    return jobs


def run_jobs(jobs: List[Tuple], workers: int = 2,
             progress: bool = True) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    start = time.time()
    if workers <= 1:
        for j in jobs:
            out += _check_job(j)
        return out
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, got in enumerate(pool.map(_check_job, jobs)):
            out += got
            if progress and (i + 1) % 20 == 0:
                say('  %d of %d jobs, %d runs, %d failed (%.0f s)' % (
                    i + 1, len(jobs), len(out),
                    sum(1 for r in out if not r.get('ok')),
                    time.time() - start))
    return out


def fabric_mhz(profile: str) -> float:
    from a2vm import costs
    return costs.parameters(profile)['fabric_mhz']


def summarize(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Per entry: the cases (captured, synthetic), runs, failures, stray
    writes, paths, cycles (median and worst a profile), the lowest S."""
    entries: Dict[str, Any] = {}
    spec_all = args()
    for key in ENTRIES:
        rs = [r for r in results if r.get('entry') == key]
        cases = {(r.get('case'), bool(r.get('synthetic'))) for r in rs}
        e: Dict[str, Any] = {
            'native': spec_all[key]['native'],
            'cases_captured': sum(1 for _, s in cases if not s),
            'cases_synthetic': sum(1 for _, s in cases if s),
            'cases_eligible': len(cases), 'cases_waiting': 0,
            'runs': len(rs),
            'failures': sum(1 for r in rs if not r.get('ok')),
            'stray_writes': sum(r.get('stray') or 0 for r in rs),
            'paths': {}, 'cycles': {}}
        for r in rs:
            if 'path' in r and r.get('fill') == '%02x' % FILLS[0] and \
                    r.get('profile') == PROFILES[0]:
                p = ('synthetic ' if r.get('synthetic') else '') + r['path']
                e['paths'][p] = e['paths'].get(p, 0) + 1
        for profile in PROFILES:
            cyc = sorted(r['cycles'] for r in rs if r.get('profile') ==
                         profile and r.get('cycles') is not None)
            if cyc:
                mhz = fabric_mhz(profile)
                e['cycles'][profile] = {
                    'median': cyc[len(cyc) // 2], 'worst': cyc[-1],
                    'median_us': round(cyc[len(cyc) // 2] / mhz, 1),
                    'worst_us': round(cyc[-1] / mhz, 1),
                    'unit': 'fabric clocks (%g MHz), from the routine\'s '
                            'entry to its return' % mhz}
        ls = [r['lowest_s']['s'] for r in rs if isinstance(
            r.get('lowest_s'), dict)]
        e['lowest_s'] = min(ls) if ls else None
        e['first_failures'] = [r for r in rs if not r.get('ok')][:3]
        entries[key] = e
    return entries


# ---------------------------------------------------------------------------
# mod3 on every input (--mod3)
# ---------------------------------------------------------------------------

def mod3_upstream() -> bytes:
    """Upstream's mod3 (p_spec65.s) of every word, by ref816 --call of a
    65816 loop in bank $7E of a captured state: it calls mod3 by JML, with
    mod3's RTS landing on an RTL of mod3's bank that returns to the loop
    (two JSLs a call keep --call's depth above 0); the results' low bytes
    at $7D0000, the high bytes at $7C0000. Two bytes a word."""
    t = CL.Linkmap()
    mod3 = t.address('p_spec65.s:mod3')
    case = GC.load_case(cases_of('p_spec65.s:P_UpdateSpecials')[0])
    mem = case.entry.copy()
    mem.header = case.entry.header
    bank = mem.read(mod3 & 0xFF0000, 0x10000)
    rtl = (mod3 & 0xFF0000) | bank.index(0x6B, 0x100)
    base = 0x7E0000
    code = bytearray()

    def emit(*b):
        code.extend(b)
    emit(0x18, 0xFB)                    # clc; xce
    emit(0xC2, 0x30)                    # rep #$30
    emit(0xA2, 0x00, 0x00)              # ldx #0
    loop = len(code)
    emit(0xDA)                          # phx
    emit(0x22)                          # jsl d1
    j1 = len(code)
    emit(0, 0, 0)
    d1 = len(code)
    emit(0x22)                          # jsl d2
    j2 = len(code)
    emit(0, 0, 0)
    d2 = len(code)
    emit(0x3B, 0x18, 0x69, 6, 0, 0x1B)  # tsc; clc; adc #6; tcs
    emit(0xA3, 0x01)                    # lda 1,s (the word)
    emit(0x4B)                          # phk
    emit(0x62)                          # per ret - 1
    per = len(code)
    emit(0, 0)
    emit(0xF4, (rtl - 1) & 0xFF, ((rtl - 1) >> 8) & 0xFF)   # pea rtl - 1
    emit(0x5C, mod3 & 0xFF, (mod3 >> 8) & 0xFF, mod3 >> 16)  # jml mod3
    ret = len(code)
    emit(0xFA)                          # plx
    emit(0xE2, 0x20)                    # sep #$20
    emit(0x9F, 0, 0, 0x7D)              # sta $7D0000,x
    emit(0xEB)                          # xba
    emit(0x9F, 0, 0, 0x7C)              # sta $7C0000,x
    emit(0xC2, 0x20)                    # rep #$20
    emit(0xE8)                          # inx
    off = loop - (len(code) + 2)
    if off < -128:
        raise PartError('the loop')
    emit(0xD0, off & 0xFF)              # bne loop
    emit(0x6B)                          # rtl
    for at, target in ((j1, d1), (j2, d2)):
        a = base + target
        code[at:at + 3] = bytes([a & 0xFF, (a >> 8) & 0xFF, a >> 16])
    code[per:per + 2] = (((ret - 1) - (per + 2)) & 0xFFFF).to_bytes(
        2, 'little')
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-secfind-mod3-',
                                 dir=str(BUILD)))
    try:
        mem.write(base, bytes(code))
        (work / 'entry.img').write_bytes(mem.image_bytes())
        cmd = [str(title.MACHINE), str(work / 'entry.img'), '--call',
               '%06X' % base, '--save', '7D0000:65536:%s' % (work / 'lo'),
               '--save', '7C0000:65536:%s' % (work / 'hi'),
               '--state', str(work / 'state.json'), '--cycles', '400000000']
        r = bounded.run(cmd, timeout=600, max_bytes=1 << 26,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r.returncode:
            raise PartError('ref816: %s' % r.stdout[-600:])
        st = json.loads((work / 'state.json').read_text())
        if not st['call']['returned']:
            raise PartError('the loop did not return')
        lo, hi = (work / 'lo').read_bytes(), (work / 'hi').read_bytes()
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return bytes(x for pair in zip(lo, hi) for x in pair)


def mod3_native(obj: Path = OUT, fill: int = 0xA5) -> bytes:
    """The native mod3 of every word (the test routine sf_t_mod3, four runs
    of 16,384): a byte each."""
    nat = Native(obj)
    out = bytearray()
    for start in range(0, 0x10000, 0x4000):
        img = G.Image(nat.b, fill, store=False)
        img.main(GR.zp_address('GA_0'), start.to_bytes(2, 'little'))
        img.poke_word('dg_entry', nat.b.labels['sf_t_mod3'])
        img.poke_label('dg_grp', bytes([0]))
        work = Path(tempfile.mkdtemp(prefix='tmp-m10-secfind-mod3n-',
                                     dir=str(BUILD)))
        try:
            r = G.run(img, work, GL.MODES['ROUTINE'], None,
                      cycles=400_000_000)
            if r.ended() != 'halt':
                raise PartError('sf_t_mod3: %s' % r.ended())
            m = G.load_snapshot(work / 'done.img')
            out += bytes(m.main[0x2000:0x6000])
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    return bytes(out)


MOD3_EDGES = (0, 1, 2, 3, 0xFFFF, 0xFFFE, 0xFFFD, 0x7FFF, 0x8000, 0x8001,
              0xFF, 0x100)
MOD3_SEED = 10


def mod3_check(obj: Path = OUT, up: Optional[bytes] = None
               ) -> Dict[str, Any]:
    """Every word, and 100,000 seeded random ones with the edges (0, 1,
    $FFFF = -1, $7FFF, $8000 ...): the native mod3 against upstream's."""
    up = up if up is not None else mod3_upstream()
    nat = mod3_native(obj)
    bad = [v for v in range(0x10000)
           if nat[v] != up[2 * v] or up[2 * v + 1] != 0]
    rnd = random.Random(MOD3_SEED)
    draws = [rnd.randrange(0x10000) for _ in range(100_000)] + \
        list(MOD3_EDGES)
    bad_draws = [v for v in draws if nat[v] != up[2 * v]]
    return {'inputs': 0x10000, 'random_draws': len(draws),
            'random_seed': MOD3_SEED, 'edges': list(MOD3_EDGES),
            'different': len(bad), 'first': bad[:5],
            'random_different': len(bad_draws),
            'upstream_is_mod3': all(up[2 * v] == v % 3 and up[2 * v + 1] == 0
                                    for v in range(0x10000))}


# ---------------------------------------------------------------------------
# The planted bugs (--plants)
# ---------------------------------------------------------------------------

# name -> (the check that must catch it, [(old, new)] edits of secfind.s)
PLANTS = {
    # P_FindSectorFromLineTag's search from sector 0 whatever the start
    'tag-search-from-0': ('finders', [(
        '''        ldx Q0
@sec:   inx''',
        '''        ldx #$FF                ; (planted: the search from 0)
@sec:   inx''')]),
    # T_Glow dimming: no turn when it reaches minlight exactly (a step late)
    'glow-turn-late': ('thinkers', [(
        '''        ora Q2                  ; (V kept)
        beq @turnup''',
        '''        ora Q2                  ; (planted: no turn at the limit)
        nop
        nop''')]),
    # P_UpdateAnimatedFlat's shift signed
    'nukage-signed-shift': ('leveltime', [(
        '''        lda G_LEVELTIME
        lsr Q0
        ror a
        lsr Q0
        ror a
        lsr Q0
        ror a''',
        '''        lda G_LEVELTIME         ; (planted: a signed shift)
        ldx #3
:       pha
        lda Q0
        cmp #$80
        ror Q0
        pla
        ror a
        dex
        bne :-''')]),
    # buttonDone: the top's texture to the bottom and the bottom's to the
    # top
    'button-other-texture': ('buttons', [(
        '''        ldy #SIDE_TOP
        cmp #UC_TOP''',
        '''        ldy #SIDE_BOTTOM        ; (planted: the other place)
        cmp #UC_TOP'''), (
        '''        ldy #SIDE_BOTTOM
        cmp #UC_BOTTOM''',
        '''        ldy #SIDE_TOP           ; (planted)
        cmp #UC_BOTTOM''')]),
    # mod3 leaving 3 (the arithmetic helper's check)
    'mod3-off': ('mod3', [(
        ''':       cmp #3
        bcc :+''',
        ''':       cmp #4                  ; (planted: 3 kept)
        bcc :+''')]),
}


def plant_build(name: str, tmp: Path) -> Path:
    """The part's test image with the planted bug `name`, from a scratch
    copy of its sources in tmp (game.mk and its includes, the part's
    fragment and sources; the rest from the tree through game.mk's
    vpath): the image's directory."""
    _, edits = PLANTS[name]
    src = tmp / 'src'
    files = list(G.PLANT_COPY) + ['game/%s/%s' % (PART, f) for f in
                                  ('part.mk', 'secfind.s', 'sftest.s')]
    for f in files:
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(SRC / f), str(src / f))
    target = src / 'game' / PART / 'secfind.s'
    text = target.read_text()
    for old, new in edits:
        if text.count(old) != 1:
            raise PartError('the planted bug %s no longer applies: %r' % (
                name, old[:60]))
        text = text.replace(old, new)
    target.write_text(text)
    return build(game=tmp / 'game', source=src)


def plant_check(check: str, obj: Path) -> Dict[str, Any]:
    """A planted image on its named check (fill $A5 under f121, the cases
    that take the planted path): the runs and how many failed."""
    one = dict(fills=(FILLS[0],), profiles=(PROFILES[0],))
    if check == 'mod3':
        r = mod3_check(obj)
        return {'runs': r['inputs'], 'failed': r['different'],
                'first': r['first']}
    if check == 'finders':
        jobs = check_jobs(keys=('p_spec65.s:P_FindSectorFromLineTag',),
                          captured=False, obj=obj, names=('e1m1', 'e1m3'),
                          select=lambda r: r['regs'].get('a', 0) != 0xFFFF,
                          **one)
    elif check == 'thinkers':
        jobs = check_jobs(keys=('p_lights65.s:T_Glow',), captured=False,
                          obj=obj, names=('thinkers',), **one)
        jobs += [j for j in check_jobs(keys=('p_lights65.s:T_Glow',),
                                       synthetic=False, obj=obj, **one)]
    elif check == 'leveltime':
        jobs = check_jobs(keys=('p_spec65.s:P_UpdateSpecials',),
                          captured=False, obj=obj, names=('e1m1',),
                          select=lambda r: r['note'].startswith('leveltime'),
                          **one)
    elif check == 'buttons':
        jobs = check_jobs(keys=('p_spec65.s:P_UpdateSpecials',),
                          captured=False, obj=obj, names=('e1m1',),
                          select=lambda r: r['note'].startswith('buttons'),
                          **one)
    else:
        raise PartError('no check %s' % check)
    res = run_jobs(jobs, workers=2, progress=False)
    bad = [r for r in res if not r.get('ok')]
    return {'runs': len(res), 'failed': len(bad),
            'first': (bad[0].get('diff') or [bad[0].get('error') or
                                             bad[0].get('ended')])[:2]
            if bad else None}


def plants(names: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    out = {}
    for name in (names or list(PLANTS)):
        check = PLANTS[name][0]
        tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-secfind-plant-',
                                    dir=str(BUILD)))
        try:
            obj = plant_build(name, tmp)
            r = plant_check(check, obj)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
        r['check'] = check
        r['caught'] = r['failed'] > 0
        out[name] = r
        say('%-22s %-10s %s' % (name, check, 'caught: %d of %d runs fail, '
                                '%s' % (r['failed'], r['runs'], r['first'])
                                if r['caught'] else 'NOT CAUGHT (%d runs)' %
                                r['runs']))
    return out


# ---------------------------------------------------------------------------
# Sizes (docs/GAME.md 4.7: the part's budget)
# ---------------------------------------------------------------------------

BUDGET = next(p['native'] for p in GL.PARTS if p['name'] == PART)
UPSTREAM_BYTES = next(p['up'] for p in GL.PARTS if p['name'] == PART)


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    """The part's bytes (secfind.o, without the test routine of sftest.o)
    against its budget; each routine's bytes and group."""
    b = G.load_build(obj, IMAGE)
    text = (obj / (IMAGE + '.map')).read_text()
    mods = text.split('Modules list:', 1)[1].split('Segment list:', 1)[0]
    chunks: List[Tuple[str, int, int]] = []
    module = None
    for line in mods.splitlines():
        if line and not line.startswith(' ') and line.endswith('.o:'):
            module = Path(line[:-1]).stem
            continue
        f = line.split()
        if module == 'secfind' and f and f[0] in b.segments:
            off = next(int(x[5:], 16) for x in f if x.startswith('Offs='))
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            lo = b.segments[f[0]][0] + off
            chunks.append((f[0], lo, lo + size))
    exports = [n for n in ('getNextSector', 'nextSector', 'around',
                           'P_FindLowestFloorSurrounding',
                           'P_FindHighestFloorSurrounding',
                           'P_FindLowestCeilingSurrounding',
                           'P_FindNextHighestFloor',
                           'P_FindSectorFromLineTag', 'P_CheckTag',
                           'P_UpdateSpecials', 'P_UpdateAnimatedFlat',
                           'mod3', 'buttonDone', 'T_Scroll', 'T_LightFlash',
                           'T_StrobeFlash', 'T_Glow', 'EV_LightTurnOn',
                           'lnLight')]
    nat = Native(obj)
    routines = {}
    for seg, lo, hi in chunks:
        inside = sorted((b.labels[n], n) for n in exports
                        if lo <= b.labels[n] < hi and
                        _seg_of(b, seg, n, nat))
        for k, (a, n) in enumerate(inside):
            end = inside[k + 1][0] if k + 1 < len(inside) else hi
            routines[n] = {'bytes': end - a, 'group': nat.group(n),
                           'segment': seg}
    total = sum(hi - lo for _, lo, hi in chunks)
    return {'bytes': total, 'budget': BUDGET, 'upstream': UPSTREAM_BYTES,
            'over_10_percent': total > BUDGET * 1.1,
            'routines': routines,
            'test_only': G.module_bytes(b, 'sftest')}


def _seg_of(b, seg: str, name: str, nat: Native) -> bool:
    g = nat.group(name)
    return seg == ('GGRP%d' % g if g else 'GCORE')


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def du_kb(path: Path) -> int:
    r = subprocess.run(['du', '-sk', str(path)], stdout=subprocess.PIPE,
                       universal_newlines=True)
    return int(r.stdout.split()[0]) if r.returncode == 0 else -1


def write_report(results: Optional[Sequence[Dict[str, Any]]] = None,
                 **parts) -> Dict[str, Any]:
    rep: Dict[str, Any] = {}
    if REPORT.exists():
        rep = json.loads(REPORT.read_text())
    rep.update(format='game-part-report 1', part=PART,
               wave=next(p['wave'] for p in GL.PARTS if p['name'] == PART),
               exclusions=[n for n, _, _ in gcanon.ROUTINE_EXCLUSIONS])
    if results is not None:
        rep['entries'] = summarize(results)
        rep['runs'] = len(results)
        rep['failures'] = sum(1 for r in results if not r.get('ok'))
        rep['stray_writes'] = sum(r.get('stray') or 0 for r in results)
        ls = [r['lowest_s']['s'] for r in results
              if isinstance(r.get('lowest_s'), dict)]
        rep['lowest_s'] = min(ls) if ls else None
    rep.update(parts)
    rep['build_kb'] = du_kb(OUT)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(rep, indent=1, default=str) + '\n')
    return rep


def print_report(rep: Dict[str, Any]) -> None:
    for key, e in rep.get('entries', {}).items():
        cyc = '; '.join('%s %s/%s us' % (p, c['median_us'], c['worst_us'])
                        for p, c in e['cycles'].items())
        say('%-45s %4d+%-4d cases %5d runs %d failed %d stray, S %s; %s' % (
            key, e['cases_captured'], e['cases_synthetic'], e['runs'],
            e['failures'], e['stray_writes'], e['lowest_s'], cyc))
    if 'sizes' in rep:
        sz = rep['sizes']
        say('bytes %d of %d (upstream %d)' % (sz['bytes'], sz['budget'],
                                             sz['upstream']))
    if 'mod3' in rep:
        say('mod3: %s' % rep['mod3'])
    for name, r in rep.get('plants', {}).items():
        say('planted %-22s %s' % (name, 'caught' if r['caught'] else
                                  'NOT CAUGHT'))


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--log', action='store_true')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--synthetic', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--mod3', action='store_true')
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--runs', default=','.join(GC.RUNS))
    parser.add_argument('--keys', default=None)
    parser.add_argument('--batch', type=int, default=BATCH)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--sample', type=int, default=1)
    parser.add_argument('--json', type=Path)
    args_ = parser.parse_args(argv)
    runs = [r for r in args_.runs.split(',') if r]
    keys = args_.keys.split(',') if args_.keys else list(ENTRIES)
    why = missing()
    if why:
        print('cannot run: %s' % why, file=sys.stderr)
        return 2
    if args_.log:
        for run in runs:
            start = time.time()
            lg = thinker_log(run)
            say('%s: %d callFn calls; %s (%.0f s)' % (
                run, lg['callfn_calls'], ', '.join(
                    '%s %d' % (k.split(':')[1], len(v))
                    for k, v in lg['calls'].items()), time.time() - start))
        return 0
    if args_.capture:
        n = capture(keys, runs, batch=args_.batch)
        say('%d cases made' % n)
        return 0
    if args_.synthetic:
        start = time.time()
        counts = write_synthetic(args_.jobs)
        say('synthetic calls: %s (%.0f s)' % (counts, time.time() - start))
        return 0
    if args_.check:
        start = time.time()
        build()
        jobs = check_jobs(keys, args_.sample)
        say('%d jobs' % len(jobs))
        res = run_jobs(jobs, args_.jobs)
        rep = write_report(res, sizes=sizes(), check_seconds=round(
            time.time() - start), sample=args_.sample)
        if args_.json:
            args_.json.write_text(json.dumps(res, indent=1) + '\n')
        print_report(rep)
        return 1 if rep['failures'] else 0
    if args_.mod3:
        build()
        r = mod3_check()
        write_report(mod3=r)
        say('mod3: %s' % r)
        return 1 if r['different'] or not r['upstream_is_mod3'] else 0
    if args_.plants:
        build()
        r = plants(keys if args_.keys else None)
        write_report(plants=r)
        return 0 if all(x['caught'] for x in r.values()) else 1
    if args_.report:
        print_report(json.loads(REPORT.read_text()))
        return 0
    parser.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
