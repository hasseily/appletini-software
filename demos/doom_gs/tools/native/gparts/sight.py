#!/usr/bin/env python3
"""Part sight's checkpoint (milestone 10, docs/GAME.md 2.4 row sight, 3.5;
docs/game-parts/sight.md): routine mode on P_CheckSight, zSetup,
sightSlope, interceptFrac and opening, the synthetic cases, the random
checks of the arithmetic helpers and the decision on the side test's log
fast path.

Usage:  python3 tools/native/gparts/sight.py --paths [--runs demo3,...]
        python3 tools/native/gparts/sight.py --capture [--runs ...]
        python3 tools/native/gparts/sight.py --check [--jobs 2]
                [--sample K] [--entries KEY,...]
        python3 tools/native/gparts/sight.py --random [--n 100000]
        python3 tools/native/gparts/sight.py --report

Everything it writes is under build/native/game/sight/ (the part's own
directory): the path logs (paths/RUN.json.z), the cases (cases/RUN/
ROUTINE/hNNNNNNNN.case.z and each run's base.ram.z, through
tools/native/gamecap.py with its case directory pointed here), the
synthetic cases (synthetic/), the results (check.json, random.json) and
report.json. The shared outputs (build/native/game/shared/: the survey,
the includes, the manifests, the placement) are read only.

--paths: a call log of the part's entries in each run (ref816
--call-log, read from a pipe, never stored), with what tells each call's
path: for P_CheckSight the pair and CS_PREV at the entry, validcount at
both ends, sightblocker and TWOBLOCKER at the return; for sightSlope the
fraction; for interceptFrac its num, den and quotient's sign.

--capture: the cases. P_CheckSight: 2,000 calls over the five runs, by
path (the same pair, REJECT, the same subsector, blocked by a one-sided
line, by a two-sided one, seen; the hint hit is a blocked call whose
blocker is t1's hint, told apart on the captured case); the other entries:
every call when fewer than 300, else 300 spread evenly over the runs, plus
one call of each path no chosen call takes.

--check: each case from both poisoned machines: $A5 under f121 and $5A
under fastpath (the cost model does not depend on the fill), through the
test entry sg_timed (the call alone in cost phase 1), with the write log;
the native canonical state after the call against ref816's
(gcanon.py, routine mode: R1-R6 only), every declared output of
src/native/game/sight/args.json, the hit log (a same-pair hit logs (tic,
t1, t2) in GTEST, no other call logs one), GT_HINT (raised by a walk whose
t1 is a zone mobj), no stray write; each P_CheckSight case once more with
the hint planes empty and t1's sightline 0, its answer required equal
(docs/GAME.md 0.3 fact 3). The synthetic cases are run the same way.

--random: the arithmetic helpers against upstream's on ref816
(build/native/math/mathref batch: upstream's own helper, run from its
entry to its return): smul48 and the side test on N random inputs each
(the edges included), the magnitude (upstream's half of 2 |v|) on every
16-bit v; the native helpers run by sg_bulk on a2vm.
"""

import argparse
import json
import os
import random
import re
import shutil
import statistics
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))

from a2vm import costs  # noqa: E402
from bridge import upstream  # noqa: E402
from bridge.port import PortReader, PortWriter  # noqa: E402
from native import gamecap as GC, gameroutine as GR, gcanon, \
    glayout as GL, grun as G, llayout as LL  # noqa: E402
from ref816 import bounded, calls as CL  # noqa: E402

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native' / 'game' / 'sight'
OUT = GL.GAME / 'sight'
CASES = OUT / 'cases'
PATHS = OUT / 'paths'
SYNTH = OUT / 'synthetic'
REPORT = OUT / 'report.json'
CHECK = OUT / 'check.json'
RANDOM_OUT = OUT / 'random.json'
IMAGE = 'ptest'
PART = 'sight'

CHECKSIGHT = 'p_sight65.s:P_CheckSight'
ENTRIES = [CHECKSIGHT, 'p_sight65.s:zSetup', 'p_sight65.s:sightSlope',
           'p_sight65.s:interceptFrac', 'p_sight65.s:opening']
TIMED = {k: i for i, k in enumerate(ENTRIES)}
SIGHT_N = 2000
MINIMUM = 300
BATCH = 60
JOBS = 2
RUNS_FP = ((0xA5, 'f121'), (0x5A, 'fastpath'))
BUDGET = 3600
UPSTREAM_BYTES = 2738
# P_CheckSight's paths (docs/GAME.md 2.4 row sight)
SIGHT_PATHS = ('pair', 'reject', 'samess', 'hint', 'one', 'two', 'seen')
MM_SIGHTHINT = 0x0A0000
MO_SIGHTLINE, MO_X = 118, 12
WRITE_LOG_LIMIT = 200_000


class PartError(Exception):
    pass


def say(text: str) -> None:
    print(text, flush=True)


# ---------------------------------------------------------------------------
# What the checks need
# ---------------------------------------------------------------------------

def missing() -> Optional[str]:
    """None when build/ has everything the checks need, else what is
    missing and the command that makes it."""
    from ref816 import title
    need = [
        (G.A2VM, 'a2vm: make -C tools/a2vm all'),
        (title.MACHINE, 'ref816: make -C tools/ref816'),
        (BUILD / 'linkmap.json', 'the link map: python3 tools/v816/imgmatch.py'),
        (GL.SHARED / 'gen' / 'ggame.inc', 'the shared outputs: make -s -C '
         'src/native -f game.mk shared ROOT=$PWD'),
        (GL.SHARED / 'placement.json', 'the placement: make -s -C src/native '
         '-f game.mk place ROOT=$PWD'),
        (GC.SURVEY / 'demo3.json.z', 'the survey: python3 '
         'tools/native/gamecap.py --survey'),
        (BUILD / 'native' / 'render' / 'tables', 'the render tables '
         '(milestone 7): python3 tools/native/rtables.py'),
    ]
    for path, what in need:
        if not Path(path).exists():
            return '%s is missing (%s)' % (path, what)
    if not GR.have_bases():
        return ('the level bases are missing (python3 '
                'tools/native/level_check.py --setup keeps them)')
    return None


def build(root: Path = ROOT, game: Optional[Path] = None,
          src: Optional[Path] = None) -> Path:
    """The part's test image (make -f game.mk part P=sight): its directory."""
    src = src or ROOT / 'src' / 'native'
    variables = ['P=%s' % PART]
    if game is not None:
        variables.append('GAME=%s' % game)
    result = bounded.run(['make', '-s', '-C', str(src), '-f', 'game.mk',
                          'part', 'ROOT=%s' % root] + variables,
                         timeout=600, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, universal_newlines=True)
    if result.returncode:
        raise PartError('the build failed:\n' + result.stdout[-3000:])
    if 'arning' in result.stdout:
        raise PartError('the build warns:\n' + result.stdout[-3000:])
    return (game or GL.GAME) / PART


def scratch() -> Dict[str, int]:
    """The scratch block's fields (sight.inc) at their addresses."""
    text = (SRC / 'sight.inc').read_text()
    vals = {'SG': GL.scratch_blocks()[PART][0]}
    for m in re.finditer(r'^(SG_\w+)\s*=\s*(SG(?:_U)?)\s*\+\s*(\d+)', text,
                         re.M):
        vals[m.group(1)] = vals[m.group(2)] + int(m.group(3))
    return vals


def args() -> Dict[str, Dict[str, Any]]:
    d = json.loads((SRC / 'args.json').read_text())
    if d.get('format') != GR.ARGS_FORMAT:
        raise PartError('args.json: not %s' % GR.ARGS_FORMAT)
    return d['entries']


_SYMS: Dict[str, int] = {}


def sym(name: str) -> int:
    if name not in _SYMS:
        _SYMS[name] = CL.Linkmap().address(name)
    return _SYMS[name]


def use_cases() -> None:
    """gamecap's cases go to the part's directory."""
    GC.CASES = CASES


# ---------------------------------------------------------------------------
# --paths: the call logs
# ---------------------------------------------------------------------------

LOGGED = [
    (CHECKSIGHT, 'in=dp:_Dp:8+p_sight65.s:CS_PREV1:8+p_map65.s:validcount:2,'
     'out=p_map65.s:validcount:2+p_sight65.s:sightblocker:2+'
     'p_sight65.s:TWOBLOCKER:2'),
    ('p_sight65.s:sightSlope', 'in=p_sight65.s:PS_FRAC:2'),
    ('p_sight65.s:interceptFrac', 'out=p_sight65.s:PS_FRAC:2+'
     'p_sight65.s:IF_NUM:4+p_sight65.s:IF_E:4+p_sight65.s:IF_QS:2'),
    ('p_sight65.s:zSetup', ''),
    ('p_sight65.s:opening', ''),
]
PATHS_FORMAT = 'sight-paths 1'


def sight_class(mem_in: List[bytes], mem_out: List[bytes], a: int) -> str:
    """P_CheckSight's path from its logged memory (the hint hit is told
    on the captured case: class_of_case)."""
    pair, prev, vc0 = mem_in
    vc1, sb, tb = mem_out
    if pair == prev:
        return 'pair'
    if vc0 == vc1:
        return 'reject' if a & 0xFF == 0 else 'samess'
    if any(sb):
        return 'one'
    if any(tb):
        return 'two'
    return 'seen'


def frac_class(frac: int, num: int, e: int, qs: int) -> str:
    """interceptFrac's path from its results (p_sight65.s:1184-1332)."""
    if num == 0:
        return 'num0'
    if e == 0:
        return 'den0'
    if e >> 16 == 0 and num >> 16 >= e & 0xFFFF:
        return 'big'
    if frac == 0xFFFF and qs & 0x8000:
        return 'neg'
    if e >> 16:
        return 'wide'
    return 'frac'


class PathLog:
    def __init__(self):
        self.tic = -1
        self.out: Dict[str, Dict[str, List[Any]]] = {
            k: {'tic': [], 'class': []} for k, _ in LOGGED}

    def read(self, handle) -> None:
        first = json.loads(handle.readline())
        if first.get('format') != CL.FORMAT:
            raise PartError('not a call log')
        names = [r['name'] for r in first['routines']]
        for raw in handle:
            line = json.loads(raw)
            if line.get('end'):
                break
            name = names[line['routine']]
            if name == GC.TIC_NAME:
                self.tic = int.from_bytes(bytes.fromhex(
                    line['in']['mem'][0]), 'little')
                continue
            d = self.out[name]
            hit = line['hit']
            while len(d['tic']) < hit - 1:
                d['tic'].append(-1)
                d['class'].append('?')
            mi = [bytes.fromhex(x) for x in (line['in'] or {}).get('mem',
                                                                  [])]
            mo = [bytes.fromhex(x) for x in (line.get('out') or {}).get(
                'mem', [])]
            a = (line.get('out') or {}).get('a', 0) or 0
            if name == CHECKSIGHT:
                c = sight_class(mi, mo, a)
            elif name == 'p_sight65.s:sightSlope':
                c = 'frac0' if mi[0] == b'\0\0' else 'slope'
            elif name == 'p_sight65.s:interceptFrac':
                v = [int.from_bytes(x, 'little') for x in mo]
                c = frac_class(*v)
            else:
                c = '-'
            d['tic'].append(self.tic)
            d['class'].append(c)


def path_log(run: str) -> Dict[str, Any]:
    GC.check_disk()
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-sight-paths-',
                                 dir=str(BUILD)))
    try:
        fifo = work / 'calls.fifo'
        os.mkfifo(str(fifo))
        routines = ['%s,name=%s,in=_g_gametic:4,entry=1' % (GC.TICKER,
                                                             GC.TIC_NAME)]
        routines += ['%s,name=%s%s' % (k, k, (',' + extra) if extra else '')
                     for k, extra in LOGGED]
        opts = CL.options(routines, fifo) + ['--call-log-limit',
                                             str(GC.CALL_LOG_LIMIT)]
        log = PathLog()
        r = GC.machine(run, work, opts, reader=log.read, fifo=fifo)
        if r['problems']:
            raise PartError('%s: %s' % (run, '; '.join(r['problems'])))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    res = {'format': PATHS_FORMAT, 'run': run, 'routines': log.out}
    PATHS.mkdir(parents=True, exist_ok=True)
    (PATHS / (run + '.json.z')).write_bytes(zlib.compress(json.dumps(
        res, separators=(',', ':')).encode(), 6))
    return res


def load_paths(run: str) -> Optional[Dict[str, Any]]:
    p = PATHS / (run + '.json.z')
    if not p.exists():
        return None
    d = json.loads(zlib.decompress(p.read_bytes()))
    if d.get('format') != PATHS_FORMAT:
        raise PartError('%s is not a path log' % p)
    return d


# ---------------------------------------------------------------------------
# --capture: the selection and the cases
# ---------------------------------------------------------------------------

def calls_of(key: str) -> List[Tuple[str, int, int, str]]:
    """(run, hit, tic, class) of every call of key in the runs, with the
    survey's count checked against the path log's."""
    out = []
    for run in GC.RUNS:
        p = load_paths(run)
        sv = GC.survey_of(run)
        if p is None or sv is None:
            continue
        d = p['routines'][key]
        n = sv['routines'].get(key, {}).get('calls', 0)
        if len(d['tic']) != n:
            raise PartError('%s %s: %d calls logged, the survey has %d' % (
                run, key, len(d['tic']), n))
        out += [(run, i + 1, d['tic'][i], d['class'][i]) for i in range(n)]
    return out


def spread(items: Sequence[Any], n: int) -> List[Any]:
    """n of items, evenly spread (all when fewer)."""
    if len(items) <= n:
        return list(items)
    return [items[(i * len(items)) // n] for i in range(n)]


def selection(key: str) -> List[Tuple[str, int, int, str]]:
    """The calls of key the checkpoint captures (GAME.md 2.4 minimums)."""
    calls = calls_of(key)
    if key == CHECKSIGHT:
        by: Dict[str, List[Tuple[str, int, int, str]]] = {}
        for c in calls:
            by.setdefault(c[3], []).append(c)
        classes = sorted(by)
        quota: Dict[str, int] = {}
        left, todo = SIGHT_N, list(classes)
        while todo:
            share = left // len(todo)
            small = [c for c in todo if len(by[c]) <= share]
            if not small:
                for c in todo:
                    quota[c] = share
                break
            for c in small:
                quota[c] = len(by[c])
                left -= len(by[c])
                todo.remove(c)
        # the rounding's remainder to the largest classes
        rest = SIGHT_N - sum(quota.values())
        for c in sorted(classes, key=lambda c: -len(by[c])):
            if rest <= 0:
                break
            more = min(rest, len(by[c]) - quota[c])
            quota[c] += more
            rest -= more
        out = []
        for c in classes:
            out += spread(by[c], quota[c])
        return sorted(out)
    chosen = spread(calls, MINIMUM)
    have = {c[3] for c in chosen}
    for c in calls:
        if c[3] not in have:
            chosen.append(c)
            have.add(c[3])
    return sorted(chosen)


def capture(keys: Sequence[str] = ENTRIES, runs: Sequence[str] = GC.RUNS,
            jobs: int = JOBS) -> Dict[str, int]:
    use_cases()
    work: List[Tuple[str, str, List[int], List[int]]] = []
    for key in keys:
        sel = selection(key)
        for run in runs:
            hits = [h for r, h, _, _ in sel if r == run]
            if hits:
                tics = GC.survey_of(run)['routines'][key]['tic']
                work.append((run, key, hits, tics))
    made: Dict[str, int] = {}
    # one process a run (each run's base is written by its first batch)
    by_run: Dict[str, List[Tuple[str, str, List[int], List[int]]]] = {}
    for w in work:
        by_run.setdefault(w[0], []).append(w)
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for got in pool.map(_capture_run, list(by_run.values())):
            for k, v in got.items():
                made[k] = made.get(k, 0) + v
    return made


def _capture_run(items) -> Dict[str, int]:
    use_cases()
    made: Dict[str, int] = {}
    for run, key, hits, tics in items:
        paths = GC.capture(run, key, hits, tics, batch=BATCH, say=say)
        made[key] = made.get(key, 0) + len(paths)
    return made


def case_files(key: str, sample: int = 1) -> List[Path]:
    """The captured cases of key in the selection, every sample-th."""
    use_cases()
    out = []
    for run, hit, _, _ in selection(key):
        p = GC.case_dir(run, key) / ('h%08d.case.z' % hit)
        if p.exists():
            out.append(p)
    return out[::sample]


# ---------------------------------------------------------------------------
# A case's reference: its class, the hit, the inputs and outputs
# ---------------------------------------------------------------------------

def dp_address(case: GC.Case, symbol: str) -> int:
    t = CL.Linkmap()
    return (case.regs_in['d'] + t.address(symbol) - t.direct_page) & 0xFFFF


def pair_and_prev(case: GC.Case) -> Tuple[bytes, bytes]:
    return (case.entry.read(dp_address(case, '_Dp'), 8),
            case.entry.read(sym('p_sight65.s:CS_PREV1'), 8))


def hint_of(case: GC.Case) -> int:
    """t1's hint at the call (its sightline, else its SIGHTHINT entry when
    a line of the map), 0 none."""
    pair, _ = pair_and_prev(case)
    t1 = int.from_bytes(pair[0:4], 'little') & 0xFFFFFF
    sl = case.entry.u16(t1 + MO_SIGHTLINE)
    if sl:
        return sl
    h = case.entry.u16(MM_SIGHTHINT + ((t1 >> 2) & 0x7FFE))
    n = case.entry.u16(sym('_g_numlines'))
    return h if 0 < h <= n else 0


def class_of_case(case: GC.Case) -> str:
    pair, prev = pair_and_prev(case)
    if pair == prev:
        return 'pair'
    vc = sym('p_map65.s:validcount')
    if case.entry.u16(vc) == case.after.u16(vc):
        return 'reject' if case.regs_out['a'] & 0xFF == 0 else 'samess'
    sb = case.after.u16(sym('p_sight65.s:sightblocker'))
    tb = case.after.u16(sym('p_sight65.s:TWOBLOCKER'))
    h = hint_of(case)
    if h and (sb or tb) == h:
        return 'hint'
    return 'one' if sb else 'two' if tb else 'seen'


def other_class(key: str, case: GC.Case) -> str:
    if key == 'p_sight65.s:sightSlope':
        return 'frac0' if case.entry.u16(sym('p_sight65.s:PS_FRAC')) == 0 \
            else 'slope'
    if key == 'p_sight65.s:interceptFrac':
        a = case.after
        return frac_class(a.u16(sym('p_sight65.s:PS_FRAC')),
                          a.u32(sym('p_sight65.s:IF_NUM')),
                          a.u32(sym('p_sight65.s:IF_E')),
                          a.u16(sym('p_sight65.s:IF_QS')))
    if key == 'p_sight65.s:opening':
        fs = case.entry.u32(dp_address(case, 'DC_SRC')) & 0xFFFFFF
        bs = case.entry.u32(dp_address(case, 'DC_CMB')) & 0xFFFFFF
        e = case.entry
        ceil = 'cf' if _s32(e.u32(fs + 4)) < _s32(e.u32(bs + 4)) else 'cb'
        floor = 'ff' if _s32(e.u32(bs)) < _s32(e.u32(fs)) else 'fb'
        return ceil + '-' + floor
    return '-'


def _s32(v: int) -> int:
    return v - (1 << 32) if v & 0x80000000 else v


class Prep:
    """A case made ready to run: the reference's states, the image's
    records but the poisoned machine and the code (fill-independent), the
    inputs, what the outputs must be."""

    def __init__(self, case: GC.Case, key: str, spec: Dict[str, Any],
                 sc: Dict[str, int]):
        self.case = case
        self.key = key
        self.spec = spec
        self.up = GR.Upstream(case)
        self.problems = self.up.r_in.problems + self.up.r_out.problems
        if self.problems:
            return
        self.mf, self.header, banks = GR.manifest(self.up.gamemap)
        self.banks = sorted(set(banks) | {LL.GTEST})
        self.skip = gcanon.skips('routine', self.up.s_in)
        self.sc = sc
        self.recs = self.records(self.up.s_in)
        self.inputs = self.input_records()
        self.cls = class_of_case(case) if key == CHECKSIGHT else \
            other_class(key, case)
        self.hit = self.walked = self.zone_t1 = False
        if key != CHECKSIGHT:
            return
        pair, prev = pair_and_prev(case)
        self.hit = pair == prev
        t1 = self.up.ref(int.from_bytes(pair[0:4], 'little'))
        t2 = self.up.ref(int.from_bytes(pair[4:8], 'little'))
        self.t1, self.t2 = t1, t2
        vc = 'p_map65.s:validcount'
        self.walked = self.up.s_in['globals'].get(vc) != \
            self.up.s_out['globals'].get(vc)
        self.zone_t1 = t1.kind == 'zmobj'

    def records(self, state: Dict[str, Any]) -> List[Tuple[int, int, int,
                                                            bytes]]:
        out = list(GR.base_records(self.up.gamemap))
        pm = G.tracked_memory()
        PortWriter(self.mf).write(gcanon.strip(state, self.skip), pm)
        out += G.port_records(pm)
        out += GR.derived(pm, self.header)
        return out

    def hintless(self) -> List[Tuple[int, int, int, bytes]]:
        """The records with the hint planes empty and t1's sightline 0."""
        import copy
        s = copy.deepcopy(self.up.s_in)
        for o in s['objects'].get('sighthint', {}).values():
            o['line'] = 0
        mo = s['objects'][self.t1.kind][self.t1.id]
        mo['sightline'] = 0
        recs = self.records(s)
        zero = bytes(LL.HINT_SLOTS)
        recs += [(1, LL.MOBJP, LL.PL_HINTL, zero),
                 (1, LL.MOBJP, LL.PL_HINTH, zero)]
        return recs

    def convert(self, data: bytes, how: Optional[str]) -> bytes:
        if how is None:
            return data
        v = int.from_bytes(data, 'little') & 0xFFFFFF
        if how == 'mobj':
            return GR.handle_of(self.mf, self.up.ref(v)).to_bytes(2,
                                                                 'little')
        kinds = {'line': ('line',), 'sector': ('sector',)}[how]
        ref, why = self.up.r_in.classify(v, kinds)
        if ref is None:
            raise PartError('$%06X is no %s (%s)' % (v, how, why))
        n = 1 if how == 'sector' else 2
        return ref.id.to_bytes(n, 'little')

    def place(self, to: str) -> int:
        kind, _, name = to.partition(':')
        if kind == 'zp':
            if name in ('M_R', 'M_A', 'M_B'):
                return {'M_A': 0xC0, 'M_B': 0xC4, 'M_R': 0xC8}[name]
            return GR.zp_address(name)
        if kind == 'sb':
            return self.sc[name]
        if kind == 'main':
            return LL.G[name]
        raise PartError('a place %r' % to)

    def input_records(self) -> List[Tuple[int, int, int, bytes]]:
        out = []
        for item in self.spec.get('in', []):
            data = self.convert(self.up.source(item['from']),
                                item.get('as'))
            n = item.get('bytes', len(data))
            out.append((0, 0, self.place(item['to']),
                        data[:n].ljust(n, b'\0')))
        return out


def math_tables() -> List[Tuple[int, int, int, bytes]]:
    """The math's RamWorks tables: grun.Image loads them since wave 1's
    integration (request R3 of docs/game-parts/sight.md, applied); none to
    add here."""
    return []


def write_ranges() -> str:
    """a2vm --write-log ranges: every byte the call may not write
    (complements of the allowed places), so a logged write is stray."""
    main = [(0x0000, 0x0200),               # zero page, the stack
            (LL.BL_BUF, LL.BL_BUF + 0x100),     # bl_get's buffer
            (GL.R.PHASE, GL.R.PHASE + 1),       # the cost phase (sg_timed)
            (LL.G_VALID, LL.G_VALID + 2),       # validcount
            (LL.MOC, LL.MOC + LL.MOC_LINES * LL.MOC_LINE),
            (LL.SCC, LL.SCC + LL.SCC_LINES * LL.SCC_LINE),
            (LL.RT_STATE, LL.RT_END),           # the runtime's state
            (LL.G['CS_PREV1'], LL.G['CS_PREVR'] + 1),
            (LL.G['GT_DIV0'], LL.G['GT_FLAGS'] + 1),    # the test globals
            (0x6000, 0xC000)]                   # W: tic scratch (R1)
    aux = {LL.LVG0: [(0x0200, 0xC000)],         # the lines' stamps
           LL.MOBJC: [(0x0200, 0xC000)],        # the mobjs' sightline
           LL.MOBJP: [(LL.PL_HINTL, LL.PL_HINTH + LL.HINT_SLOTS),
                      (LL.PL_TNL, 0xC000)],     # the hints, the planes
           LL.GTEST: [(GL.GTB['GT_HITS'], GL.GTB['GT_HITS'] + 0x400)]}
    from native import lrun
    items = ['main:%04X-%04X' % r for r in lrun.complement(main)
             if r[0] < 0xC000]
    for bank in range(128):
        if bank in aux:
            items += ['aux%d:%04X-%04X' % ((bank,) + r)
                      for r in lrun.complement(aux[bank])]
        else:
            items.append('aux%d' % bank)
    return ','.join(items)


def stray_writes(path: Path) -> List[str]:
    if not path.exists():
        return ['no write log']
    return [line for line in path.read_text().splitlines()
            if line.startswith('w ')]


def run_one(prep: Prep, b, fill: int, profile: Optional[str],
            hintless: bool = False) -> Dict[str, Any]:
    """One run of the case's call; the comparison."""
    res: Dict[str, Any] = {'fill': '%02x' % fill, 'profile': profile,
                           'hintless': hintless, 'ok': False}
    img = G.Image(b, fill, store=True)
    img.recs += math_tables()
    img.recs += prep.hintless() if hintless else prep.recs
    img.recs += prep.inputs
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-sight-', dir=str(BUILD)))
    try:
        r = G.run(img, work, GL.MODES['ROUTINE'], 'sg_timed',
                  regs=(TIMED[prep.key], 0, 0, 0x34), banks=prep.banks,
                  profile=profile, write_log=None if hintless else
                  write_ranges())
        ls = r.state.get('lowest_s')
        res['lowest_s'] = ls.get('s') if isinstance(ls, dict) else ls
        ended = r.ended()
        res['ended'] = ended
        if ended != 'halt':
            p = work / 'crash.img'
            if p.exists():
                res['stop'] = G.stop_codes(G.load_snapshot(p))
            return res
        if profile:
            text = (work / 'cost.json').read_text()
            cost = json.loads(text[text.rfind('{"final"'):])['cost']
            mhz = costs.parameters(profile)['fabric_mhz']
            res['cycles'] = cost['phase_cycles'][1]
            res['us'] = round(cost['phases'][1] / mhz, 2)
        if not hintless:
            stray = stray_writes(work / 'writes.log')
            res['stray'] = len(stray)
            res['stray_first'] = stray[:3]
        m = G.load_snapshot(work / 'done.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    lab = b.labels

    def rt(name: str) -> int:
        return m.main[GL.RT[name]] | m.main[GL.RT[name] + 1] << 8
    # (the driver's own load of the entry's group is one of FC_LOADS)
    res['loads'] = rt('FC_LOADS')
    res['misses'] = rt('GO_MISS')
    a = G.card_byte(m, lab['dg_ra'])
    diff: List[str] = []
    if hintless:
        ua = prep.case.regs_out['a'] & 0xFF
        if a != ua:
            diff.append('the answer without a hint: %d, upstream %d' % (a,
                                                                        ua))
        res['diff'] = diff
        res['ok'] = not diff
        return res
    from native import setupcheck as SC
    nat = PortReader(prep.mf).read(SC.port_memory(m))
    diff += gcanon.compare(prep.up.s_out, nat, 'routine')
    diff += outputs(prep, m, a)
    diff += hit_log(prep, m)
    gth = m.main[LL.G['GT_HINT']]
    want = 1 if (prep.key == CHECKSIGHT and prep.walked and prep.zone_t1) \
        else 0
    if gth != want:
        diff.append('GT_HINT %d, %d wanted' % (gth, want))
    if res.get('stray'):
        diff.append('%d stray writes: %s' % (res['stray'],
                                             res['stray_first']))
    res['diff'] = diff[:12]
    res['ok'] = not diff
    return res


def outputs(prep: Prep, m, a: int) -> List[str]:
    out = []
    for item in prep.spec.get('out', []):
        n = item.get('bytes', 2)
        nv = item['native']
        if nv == 'a':
            mine = a
        else:
            at = prep.place(nv)
            mine = int.from_bytes(bytes(m.main[at:at + n]), 'little')
        theirs = int.from_bytes(prep.up.source(item['upstream'], 'out'),
                                'little')
        mask = (1 << (8 * n)) - 1
        if mine & mask != theirs & mask:
            out.append('output %s: %X != %X' % (item['upstream'],
                                                mine & mask, theirs & mask))
    return out


def hit_log(prep: Prep, m) -> List[str]:
    """The same-pair hit log (docs/GAME.md 1.8): one record (tic, t1, t2)
    for a hit, none otherwise."""
    n = m.main[LL.G['GT_HITLOG']] | m.main[LL.G['GT_HITLOG'] + 1] << 8
    want = 1 if prep.hit else 0
    if n != want:
        return ['the hit log: %d records, %d wanted' % (n, want)]
    if not n:
        return []
    rec = bytes(m.aux[LL.GTEST][GL.GTB['GT_HITS']:GL.GTB['GT_HITS'] + 6])
    tic = prep.up.s_in['globals']['g_game65.s:_g_gametic'] & 0xFFFF
    t1 = GR.handle_of(prep.mf, prep.t1)
    t2 = GR.handle_of(prep.mf, prep.t2)
    if rec != struct.pack('<HHH', tic, t1, t2):
        return ['the hit log: %s, (%d, %d, %d) wanted' % (rec.hex(), tic, t1,
                                                          t2)]
    return []


def run_prepared(prep: Prep, b, hint_check: bool = True,
                 runs=RUNS_FP) -> List[Dict[str, Any]]:
    out = []
    for fill, profile in runs:
        out.append(run_one(prep, b, fill, profile))
    if hint_check and prep.key == CHECKSIGHT:
        out.append(run_one(prep, b, 0xA5, None, hintless=True))
    return out


def _job(job) -> List[Dict[str, Any]]:
    path, key, obj, synthetic = job[:4]
    one = len(job) > 4 and job[4]
    use_cases()
    b = G.load_build(Path(obj), IMAGE)
    case = load_synthetic(Path(path)) if synthetic else GC.load_case(
        Path(path))
    info = {'case': Path(path).name, 'routine': key,
            'run': case.header.get('run'), 'hit': case.header.get('hit'),
            'note': case.header.get('note')}
    try:
        prep = Prep(case, key, args()[key], scratch())
    except Exception as error:      # reported per case, never hidden
        return [dict(info, ok=False, error='%s: %s' % (type(error).__name__,
                                                       error))]
    if prep.problems:
        return [dict(info, ok=False, cls='undecodable',
                     error='bridge: ' + '; '.join(prep.problems[:3]))]
    out = []
    for r in run_prepared(prep, b, hint_check=not one,
                          runs=RUNS_FP[:1] if one else RUNS_FP):
        r.update(info, cls=prep.cls)
        out.append(r)
    return out


def run_jobs(jobs_list: Sequence[Tuple[str, str, str, bool]],
             jobs: int = JOBS) -> List[List[Dict[str, Any]]]:
    """Each job's results, in the jobs' order."""
    if jobs <= 1:
        return [_job(j) for j in jobs_list]
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(_job, jobs_list))


def run_cases(jobs_list: Sequence[Tuple[str, str, str, bool]],
              jobs: int = JOBS) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if jobs <= 1:
        for j in jobs_list:
            out += _job(j)
        return out
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for got in pool.map(_job, jobs_list, chunksize=2):
            out += got
    return out


# ---------------------------------------------------------------------------
# The synthetic cases
# ---------------------------------------------------------------------------

def save_synthetic(case: GC.Case, name: str) -> Path:
    """A synthetic case (gamecap.call_case's) as a file: the header, the
    entry memory's pages that differ from the run's base, the writes."""
    SYNTH.mkdir(parents=True, exist_ok=True)
    base = GC.load_base(case.header['run'])
    pages = []
    payload = bytearray()
    for bank in GC.RAM_BANKS:
        for p in range(256):
            a = bank << 16 | p << 8
            mine = case.entry.read(a, 256)
            if mine != base.read(a, 256):
                pages.append(a >> 8)
                payload += mine
    writes = bytearray()
    for a, n in case.header['writes']:
        writes += case.after.read(a, n)
    header = dict(case.header, synthetic=name, pages=pages)
    head = json.dumps(header, separators=(',', ':')).encode() + b'\n'
    p = SYNTH / (name + '.case.z')
    p.write_bytes(zlib.compress(head + bytes(payload) + bytes(writes), 6))
    return p


def load_synthetic(path: Path) -> GC.Case:
    raw = zlib.decompress(path.read_bytes())
    nl = raw.index(b'\n')
    header = json.loads(raw[:nl])
    entry = GC.load_base(header['run'])
    entry.header = bytes.fromhex(header['image_header'])
    at = nl + 1
    for p in header['pages']:
        entry.write(p << 8, raw[at:at + 256])
        at += 256
    after = entry.copy()
    for a, n in header['writes']:
        after.write(a, raw[at:at + n])
        at += n
    return GC.Case(header, entry, after, path)


def _poke32(addr: int, value: int) -> Tuple[int, bytes]:
    return (addr, (value & 0xFFFFFFFF).to_bytes(4, 'little'))


def stale_pointer(case: GC.Case) -> int:
    """An address that names no object for the bridge (a CS_PREV left from
    an earlier level)."""
    r = upstream.Reader(case.entry, tic=True)
    r.read()
    for a in range(0x7F0000, 0x7FFFFF, 0x1000):
        ref, why = r.classify(a, ('mobj', 'zmobj'))
        if ref is None and why == 'names no object':
            return a
    raise PartError('no stale address found')


def synthetic(sample_cases: int = 4) -> List[Path]:
    """The synthetic cases, run on ref816 (gamecap.call_case):
    on-node     t1 and t2 on the root node's partition line (whole units):
                the side test's on case (2) at the root
    stale1      a same-pair call whose CS_PREV1 names no object ($FFFE
                natively): no hit
    stale2      the same with CS_PREV2 stale too
    wrapNN      no hint, t1 and t2 moved far apart on one axis (+-32000):
                the whole parts' differences with the nodes and lines wrap
                at 16 bits (p_sight65.s:620-650)"""
    use_cases()
    paths = case_files(CHECKSIGHT)
    walking, pairs = [], []
    for p in paths:
        c = GC.load_case(p)
        k = class_of_case(c)
        if k in ('seen', 'two', 'one', 'hint') and len(walking) < \
                3 * sample_cases:
            walking.append(c)
        elif k == 'pair' and len(pairs) < sample_cases:
            pairs.append(c)
        if len(walking) >= 3 * sample_cases and len(pairs) >= sample_cases:
            break
    out = []
    numnodes_at = sym('numnodes')
    nodes_at = sym('nodes')
    for i, c in enumerate(walking[:sample_cases]):
        pair, _ = pair_and_prev(c)
        t1 = int.from_bytes(pair[0:4], 'little') & 0xFFFFFF
        t2 = int.from_bytes(pair[4:8], 'little') & 0xFFFFFF
        n = c.entry.u16(numnodes_at)
        base = c.entry.u32(nodes_at) & 0xFFFFFF
        node = base + 28 * (n - 1)
        x, y, dx, dy = struct.unpack('<hhhh', c.entry.read(node, 8))
        pokes = [_poke32(t1 + MO_X, x << 16), _poke32(t1 + MO_X + 4, y << 16),
                 _poke32(t2 + MO_X, (x + dx) << 16),
                 _poke32(t2 + MO_X + 4, (y + dy) << 16)]
        s = GC.call_case(c, pokes, 'on-node (synthetic)')
        out.append(save_synthetic(s, 'on-node-%d' % i))
    for i, c in enumerate(pairs):
        st = stale_pointer(c)
        prev = sym('p_sight65.s:CS_PREV1')
        s = GC.call_case(c, [_poke32(prev, st)], 'stale1 (synthetic)')
        out.append(save_synthetic(s, 'stale1-%d' % i))
        s = GC.call_case(c, [_poke32(prev, st), _poke32(prev + 4, st + 4)],
                         'stale2 (synthetic)')
        out.append(save_synthetic(s, 'stale2-%d' % i))
    k = 0
    for c in walking:
        pair, _ = pair_and_prev(c)
        t1 = int.from_bytes(pair[0:4], 'little') & 0xFFFFFF
        t2 = int.from_bytes(pair[4:8], 'little') & 0xFFFFFF
        # no hint (t1's sightline and SIGHTHINT entry 0): the walk from the
        # root, t1 and t2 far apart on one axis: their whole parts' differences
        # with the nodes and lines wrap at 16 bits
        nohint = [(t1 + MO_SIGHTLINE, b'\0\0'),
                  (MM_SIGHTHINT + ((t1 >> 2) & 0x7FFE), b'\0\0')]
        for off, v in ((0, 32000), (4, 32000), (0, -32000), (4, -32000)):
            s = GC.call_case(c, nohint + [_poke32(t1 + MO_X + off, v << 16),
                                         _poke32(t2 + MO_X + off,
                                                 -v << 16)],
                             'wrap (synthetic)')
            out.append(save_synthetic(s, 'wrap-%02d' % k))
            k += 1
            if k >= 4 * sample_cases:
                break
        if k >= 4 * sample_cases:
            break
    return out


FRAC = 'p_sight65.s:interceptFrac'


def frac_synthetic(n: int = 4) -> List[Path]:
    """interceptFrac's paths no run takes (p_sight65.s:1213-1280): den >> 12
    = 0 (the line of sight's dx and dy 0: den 0) and a quotient of $10000
    or more (dx one unit, dy 0, a line with |dy| of 16 or more: den >> 12
    small), on captured calls with los.strace poked, run on ref816; each
    kept when ref816's own results give the path wanted."""
    use_cases()
    los = sym('p_sight65.s:los') + 12
    out: List[Path] = []
    want = {'den0': 0, 'big': 0}
    for p in case_files(FRAC):
        c = GC.load_case(p)
        line = c.entry.u32(dp_address(c, 'p_sight65.s:PS_P')) & 0xFFFFFF
        dy = struct.unpack('<h', c.entry.read(line + 10, 2))[0]
        for name, pokes in (
                ('den0', [_poke32(los + 8, 0), _poke32(los + 12, 0)]),
                ('big', [_poke32(los + 8, 1 << 16), _poke32(los + 12, 0)])):
            if want[name] >= n or (name == 'big' and abs(dy) < 16):
                continue
            s = GC.call_case(c, pokes, 'frac %s (synthetic)' % name)
            if other_class(FRAC, s) != name:
                continue
            out.append(save_synthetic(s, 'frac-%s-%d' % (name, want[name])))
            want[name] += 1
        if all(v >= n for v in want.values()):
            break
    return out


def synthetic_files() -> List[Path]:
    return sorted(SYNTH.glob('*.case.z')) if SYNTH.exists() else []


# ---------------------------------------------------------------------------
# --random: the arithmetic helpers against upstream's (mathref batch)
# ---------------------------------------------------------------------------

MATHREF = BUILD / 'native' / 'math' / 'mathref'
BULK_IN, BULK_OUT = 93, 94
BULK_ROOM = 0xC000 - 0x0200
EDGES16 = (0, 1, -1, 2, -2, 127, -128, 255, 256, -256, 32767, -32767,
           -32768, 16384, -16384)
EDGES32 = (0, 1, -1, 0x7FFFFFFF, -0x80000000, -0x7FFFFFFF, 0x10000,
           -0x10000, 0xFFFF, 0x8000, -0x8000, 0x7FFF0000)


def ram_of(case: GC.Case) -> bytes:
    return GC._ram_bytes(case.entry)


def ref_case() -> GC.Case:
    """A P_CheckSight case whose RAM is upstream's machine for the
    helpers (its registers: D, DBR, P at the call)."""
    use_cases()
    files = case_files(CHECKSIGHT)
    if not files:
        raise PartError('no P_CheckSight case (python3 '
                        'tools/native/gparts/sight.py --capture)')
    return GC.load_case(files[0])


def entry_text(case: GC.Case, pc: int, ret: int = 2) -> str:
    r = case.regs_in
    hdr = bytes.fromhex(case.header['image_header'])
    sw = hdr[26:30]
    return ('pc %06X\ndbr %02X\nd %04X\np %02X\ne 0\ns %04X\na 0\nx 0\n'
            'y 0\nret %d\nstack %s\nswitches %s\n' % (
                pc, r['dbr'], r['d'], r['p'] & ~0x30 & 0xFF, r['s'], ret,
                ' '.join(['00'] * ret), ' '.join('%02X' % v for v in sw)))


def mathref(case: GC.Case, name: str, pc: int, items_in: Sequence[str],
            items_out: Sequence[str], records: bytes, out_size: int
            ) -> List[bytes]:
    """Upstream's routine at pc on each input record (mathref batch): the
    outputs (out_size bytes each)."""
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-sight-ref-',
                                 dir=str(BUILD)))
    try:
        (work / 'base.ram').write_bytes(ram_of(case))
        (work / 'entry').write_text(entry_text(case, pc))
        spec = ['routine %s %06X' % (name, pc)] + \
            ['in %s' % x for x in items_in] + \
            ['out %s' % x for x in items_out]
        (work / 'spec').write_text('\n'.join(spec) + '\n')
        (work / 'cases').write_bytes(records)
        r = bounded.run([str(MATHREF), 'batch', str(work / 'base.ram'),
                         str(work / 'entry'), str(work / 'spec'), name,
                         str(work / 'cases'), str(work / 'out')],
                        timeout=1200, max_bytes=1 << 28,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        universal_newlines=True)
        if r.returncode:
            raise PartError('mathref: %s' % r.stdout[-1000:])
        data = (work / 'out').read_bytes()
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    step = out_size + 4
    return [data[i:i + out_size] for i in range(0, len(data), step)]


def native_bulk(b, mode: int, in_size: int, out_size: int,
                records: bytes) -> List[bytes]:
    """The native helper (sg_bulk mode) on each input record, as many runs
    as the banks take."""
    per = min(BULK_ROOM // in_size, BULK_ROOM // out_size)
    n = len(records) // in_size
    out: List[bytes] = []
    for start in range(0, n, per):
        k = min(per, n - start)
        img = G.Image(b, 0xA5, store=False)
        img.aux(BULK_IN, 0x0200, records[start * in_size:(start + k) *
                                         in_size])
        work = Path(tempfile.mkdtemp(prefix='tmp-m10-sight-bulk-',
                                     dir=str(BUILD)))
        try:
            r = G.run(img, work, GL.MODES['ROUTINE'], 'sg_bulk',
                      regs=(mode, k & 0xFF, k >> 8, 0x34), banks=[BULK_OUT])
            if r.ended() != 'halt':
                raise PartError('sg_bulk ended %s' % r.ended())
            m = G.load_snapshot(work / 'done.img')
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        data = bytes(m.aux[BULK_OUT][0x0200:0x0200 + k * out_size])
        out += [data[i:i + out_size] for i in range(0, len(data), out_size)]
    return out


def logtab(case: GC.Case) -> List[int]:
    at = 0x1F0000            # memmap.inc MM_LOGTAB
    data = case.entry.read(at, 0x10000)
    return [data[2 * i] | data[2 * i + 1] << 8 for i in range(0x8000)]


def k_of(dx: int, dy: int, off: int, lt: List[int]) -> int:
    """K of a divline as P_InitSightLogs' kOf (and P_CheckSight's KS for
    off 0): log |dx| - log |dy| with its low 4 bits off, the signs, the
    offset of dx / 4 (p_sight65.s:1515-1552, :275-302)."""
    def lg(v: int) -> int:
        return lt[((abs(v) & 0xFFFF) << 1 & 0xFFFF) >> 1]
    b = off + (1 if dx < 0 else 0) + (2 if dy < 0 else 0)
    k = 0 if dx == 0 or dy == 0 else (lg(dx) - lg(dy)) & 0xFFF0
    return (k | b) & 0xFFFF


def exact_side(qa: int, qb: int, qc: int, qd: int) -> int:
    right, left = qa * qb, qc * qd
    return 0 if right < left else 2 if right == left else 1


def side_inputs(n: int, seed: int) -> List[Tuple[int, int, int, int, int]]:
    """(QA, QB, QC, QD, style): style 4 a node or line divline (QB, QD not
    0), 0 the line of sight (QA 0 when QB is, QC 0 when QD is); the edges,
    random 16-bit values, small ones, and pairs of products close to each
    other (the log path's limit)."""
    rnd = random.Random(seed)
    out = []
    for a in EDGES16:
        for b_ in EDGES16:
            out.append((a, b_ or 1, b_, a or 1, 4))
            out.append((a, b_, a, b_, 0))
    while len(out) < n:
        kind = len(out) % 4
        if kind == 0:
            v = [rnd.randint(-32768, 32767) for _ in range(4)]
        elif kind == 1:
            v = [rnd.randint(-300, 300) for _ in range(4)]
        else:
            qa, qb, qd = (rnd.randint(-32768, 32767) for _ in range(3))
            qd = qd or 1
            qc = max(-32768, min(32767, round(qa * qb / qd) +
                                 rnd.randint(-2, 2)))
            v = [qa, qb, qc, qd]
        style = 4 if kind != 3 else 0
        qa, qb, qc, qd = v
        if style == 4:
            qb, qd = qb or 1, qd or -1
        else:
            if qb == 0:
                qa = 0
            if qd == 0:
                qc = 0
        out.append((qa, qb, qc, qd, style))
    return out[:max(n, len(out))]


def random_checks(n: int = 100_000, seed: int = 1, b=None) -> Dict[str, Any]:
    """smul48 and the side test on n inputs, the magnitude on all 65,536,
    upstream against native."""
    case = ref_case()
    b = b or G.load_build(OUT, IMAGE)
    lt = logtab(case)
    rep: Dict[str, Any] = {'seed': seed}
    rnd = random.Random(seed)
    # the magnitude: upstream's half of 2 |v| (its asl of the absolute
    # value) against sg_mag, every v
    # (v = 0 never reaches half: sideTest answers a zero operand by the
    # signs before the products, p_sight65.s:703-722)
    vs = [v for v in range(-32768, 32768) if v]
    up_in = b''.join(struct.pack('<H', ((abs(v) & 0xFFFF) << 1) & 0xFFFF)
                     for v in vs)
    ups = mathref(case, 'half', sym('p_sight65.s:half'), ['a'], ['a'],
                  up_in, 2)
    nat = native_bulk(b, 0, 2, 2, b''.join(struct.pack('<h', v)
                                           for v in vs))
    bad = [(v, u.hex(), m.hex()) for v, u, m in zip(vs, ups, nat) if u != m]
    rep['half'] = {'inputs': len(vs), 'different': len(bad),
                   'first': bad[:5]}
    # smul48: IF_V (4) and C (A)
    v_s = [(v, c) for v in EDGES32 for c in EDGES16]
    while len(v_s) < n:
        v = rnd.randint(-0x80000000, 0x7FFFFFFF) if len(v_s) % 2 else \
            rnd.randint(-0x01000000, 0x01000000)
        v_s.append((v, rnd.randint(-32768, 32767)))
    if_v = sym('p_sight65.s:IF_V')
    if_p = sym('p_sight65.s:IF_P')
    up_in = b''.join(struct.pack('<Hi', c & 0xFFFF, v) for v, c in v_s)
    ups = mathref(case, 'smul48', sym('p_sight65.s:smul48'),
                  ['a', '%06X 4' % if_v], ['%06X 6' % if_p], up_in, 6)
    nat = native_bulk(b, 2, 6, 6, b''.join(struct.pack('<ih', v, _s16(c))
                                           for v, c in v_s))
    model = [((v * c) & 0xFFFFFFFFFFFF).to_bytes(6, 'little')
             for v, c in v_s]
    bad = [(v, c, u.hex(), m.hex()) for (v, c), u, m in zip(v_s, ups, nat)
           if u != m]
    rep['smul48'] = {'inputs': len(v_s), 'different': len(bad),
                     'first': bad[:5],
                     'upstream_is_the_product': sum(
                         1 for u, x in zip(ups, model) if u == x)}
    # the side test: upstream's sideTest (the log fast path, then the
    # products) against the exact signed products (sg_side)
    s_in = side_inputs(n, seed)
    d = case.regs_in['d']
    dln = sym('p_sight65.s:DLN')
    los = sym('p_sight65.s:los')
    rts = sym('p_sight65.s:half') + 6
    if case.entry.u8(rts) != 0x60:
        raise PartError('no RTS at half + 6')
    recs = bytearray()
    for qa, qb, qc, qd, style in s_in:
        k = k_of(qb, qd, style, lt)
        recs += struct.pack('<HHHHIhhhh', qc & 0xFFFF, qa & 0xFFFF, k,
                            rts & 0xFFFF, dln, qb, qd, qb, qd)
    ups = mathref(case, 'sideTest', sym('p_sight65.s:sideTest'),
                  ['x', 'y', '%06X 2' % d, '%06X 2' % (d + 2),
                   '%06X 4' % (d + 0x45), '%06X 2' % (dln + 4),
                   '%06X 2' % (dln + 6), '%06X 2' % (los + 22),
                   '%06X 2' % (los + 26)], ['a'], bytes(recs), 2)
    nat = native_bulk(b, 1, 8, 1, b''.join(struct.pack('<hhhh', qa, qb, qc,
                                                       qd)
                                           for qa, qb, qc, qd, _ in s_in))
    diff_n, diff_ex, by_edge = [], 0, {'32768': 0, 'other': 0}
    for (qa, qb, qc, qd, st), u, m in zip(s_in, ups, nat):
        uv = u[0]
        ex = exact_side(qa, qb, qc, qd)
        if m[0] != ex:
            diff_ex += 1
        if uv != m[0]:
            edge = -32768 in (qa, qb, qc, qd)
            by_edge['32768' if edge else 'other'] += 1
            diff_n.append((qa, qb, qc, qd, st, uv, m[0]))
    rep['side'] = {'inputs': len(s_in), 'native_not_exact': diff_ex,
                   'different': len(diff_n), 'different_by_kind': by_edge,
                   'first': diff_n[:8],
                   'with_32768': sum(1 for x in s_in if -32768 in x[:4])}
    return rep


def _s16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


# ---------------------------------------------------------------------------
# Planted bugs (the test file's): a scratch copy of the part's sources
# ---------------------------------------------------------------------------

PLANT_COPY = G.PLANT_COPY      # (every part's fragment: wave 1 as integrated)


def planted(tmp: Path, bugs: Sequence[Tuple[str, str, str]]) -> Path:
    """The part's test image built from a scratch copy of its sources in
    tmp with each (file of src/native/game/sight, old, new) applied once
    (the rest of the tree through game.mk's vpath): its directory."""
    src = tmp / 'src'
    here = ROOT / 'src' / 'native'
    for f in PLANT_COPY:
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(here / f), str(src / f))
    mine = src / 'game' / PART
    mine.mkdir(parents=True, exist_ok=True)
    for f in SRC.iterdir():
        if f.is_file():
            shutil.copy(str(f), str(mine / f.name))
    for name, old, new in bugs:
        text = (mine / name).read_text()
        if text.count(old) != 1:
            raise PartError('the bug no longer applies: %r' % old[:60])
        (mine / name).write_text(text.replace(old, new))
    return build(game=tmp / 'game', src=src)


def plant_run(bugs: Sequence[Tuple[str, str, str]],
              cases: Sequence[Tuple[str, str, bool]],
              jobs: int = JOBS) -> Dict[str, Any]:
    """The cases (path, entry, synthetic) on the planted image, one run
    each ($A5, f121): how many fail, and the first differences."""
    tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-sight-plant-',
                                dir=str(BUILD)))
    try:
        obj = planted(tmp, bugs)
        work = [(p, k, str(obj), s, True) for p, k, s in cases]
        res: List[Dict[str, Any]] = []
        if jobs <= 1:
            for w in work:
                res += _job(w)
        else:
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                for got in pool.map(_job, work):
                    res += got
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    bad = [r for r in res if not r.get('ok')]
    return {'cases': len(cases), 'runs': len(res), 'failed': len(bad),
            'first': [(r.get('case'), (r.get('diff') or [r.get('error'),
                                                         r.get('ended'),
                                                         r.get('stop')])[:2])
                      for r in bad[:3]]}


# ---------------------------------------------------------------------------
# --check and the report
# ---------------------------------------------------------------------------

RESULTS = OUT / 'results'


def _result_path(job) -> Path:
    path, key = job[0], job[1]
    stem = Path(path).name.replace('.case.z', '')
    run = Path(path).parent.parent.name if not job[3] else 'synthetic'
    return RESULTS / key.split(':')[1] / ('%s-%s.json' % (run, stem))


def check(entries: Sequence[str] = ENTRIES, sample: int = 1,
          jobs: int = JOBS, with_synthetic: bool = True,
          obj: Optional[Path] = None, chunk: int = 64) -> Dict[str, Any]:
    """Every case (or every sample-th), resumable: each case's results are
    kept in results/ENTRY/ (deleted when the image is rebuilt with other
    code: the image's digest is in each file)."""
    obj = obj or OUT
    import hashlib
    digest = hashlib.sha256(b''.join(
        (Path(obj) / f).read_bytes() for f in sorted(
            x.name for x in Path(obj).glob(IMAGE + '.*')
            if x.suffix not in ('.map', '.lbl')))).hexdigest()[:16]
    work = []
    for key in entries:
        for p in case_files(key, sample):
            work.append((str(p), key, str(obj), False))
    if with_synthetic:
        for p in synthetic_files():
            key = synthetic_key(p)
            if key in entries:
                work.append((str(p), key, str(obj), True))
    start = time.time()
    results: List[Dict[str, Any]] = []
    todo = []
    for w in work:
        rp = _result_path(w)
        if rp.exists():
            d = json.loads(rp.read_text())
            if d.get('image') == digest:
                results += d['results']
                continue
        todo.append(w)
    for i in range(0, len(todo), chunk):
        part = todo[i:i + chunk]
        for w, got in zip(part, run_jobs(part, jobs)):
            rp = _result_path(w)
            rp.parent.mkdir(parents=True, exist_ok=True)
            rp.write_text(json.dumps({'image': digest, 'results': got}))
            results += got
        say('%d of %d cases run (%.0f s)' % (min(i + chunk, len(todo)),
                                             len(todo), time.time() - start))
    return {'seconds': round(time.time() - start, 1), 'results': results}


def synthetic_key(p: Path) -> str:
    raw = zlib.decompress(p.read_bytes())
    return json.loads(raw[:raw.index(b'\n')])['routine']


def paging(sample: int = 10, jobs: int = JOBS) -> Dict[str, Any]:
    """The paging under the current placement: the group loads (FC_LOADS,
    gcall.s, less the driver's own load of the entry's group) a
    P_CheckSight call makes, over every sample-th case, by path, with its
    cycles (f121); the groups' sizes in this image."""
    work = [(str(p), CHECKSIGHT, str(OUT), False, True)
            for p in case_files(CHECKSIGHT, sample)]
    rs = [r for got in run_jobs(work, jobs) for r in got
          if r.get('ok') and r.get('cycles')]
    by: Dict[str, List[Tuple[int, int]]] = {}
    for r in rs:
        by.setdefault(r['cls'], []).append((r['loads'] - 1, r['cycles']))
    out: Dict[str, Any] = {'cases': len(rs), 'by_path': {}}
    for c, v in sorted(by.items()):
        loads = sorted(x for x, _ in v)
        cyc = sorted(y for _, y in v)
        out['by_path'][c] = {
            'calls': len(v), 'loads_median': statistics.median(loads),
            'loads_worst': loads[-1],
            'cycles_median': statistics.median(cyc), 'cycles_worst': cyc[-1],
            'cycles_median_no_load': statistics.median(
                [y for x, y in v if x == 0]) if any(x == 0 for x, _ in v)
            else None}
    b = G.load_build(OUT, IMAGE)
    out['groups'] = {'%d (slot %d)' % (n, 1 if lo == GL.WR['SLOT1'][0]
                                       else 2): len(d)
                     for n, lo, hi, d in G.groups_of(b)}
    return out


def summarize(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in ENTRIES:
        rs = [r for r in results if r.get('routine') == key]
        if not rs:
            continue
        cases = {(r.get('run'), r['case'], r.get('note')) for r in rs}
        synth = {r['case'] for r in rs if (r.get('note') or '').endswith(
            '(synthetic)')}
        main = [r for r in rs if not r.get('hintless')]
        hint = [r for r in rs if r.get('hintless')]
        e: Dict[str, Any] = {
            'cases': len(cases), 'synthetic_cases': len(synth),
            'runs': len(main), 'failed': sum(1 for r in main
                                             if not r.get('ok')),
            'stray_writes': sum(r.get('stray', 0) for r in main),
            'lowest_s': min((r['lowest_s'] for r in main
                             if r.get('lowest_s') is not None),
                            default=None)}
        if hint:
            e['hintless_runs'] = len(hint)
            e['hintless_failed'] = sum(1 for r in hint if not r.get('ok'))
        for prof in ('f121', 'fastpath'):
            cyc = sorted(r['cycles'] for r in main
                         if r.get('profile') == prof and r.get('cycles'))
            us = sorted(r['us'] for r in main
                        if r.get('profile') == prof and r.get('us'))
            if cyc:
                e[prof] = {'cycles_median': statistics.median(cyc),
                           'cycles_worst': cyc[-1],
                           'us_median': statistics.median(us),
                           'us_worst': us[-1]}
        classes: Dict[str, int] = {}
        for c in {(r.get('run'), r['case'], r.get('note'), r.get('cls'))
                  for r in main}:
            classes[c[3]] = classes.get(c[3], 0) + 1
        e['paths'] = classes
        e['first_failures'] = [
            {k: r.get(k) for k in ('case', 'run', 'hit', 'cls', 'fill',
                                   'hintless', 'ended', 'stop', 'diff',
                                   'error')}
            for r in rs if not r.get('ok')][:5]
        out[key] = e
    return out


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    b = G.load_build(obj, IMAGE)
    ms = G.module_sizes(b)
    lab = b.labels
    end13 = None
    for seg, (lo, hi) in b.segments.items():
        if lo <= lab['sg_timed'] <= hi:
            end13 = hi + 1
    test_only = end13 - lab['sg_timed'] if end13 else 0
    if lab['sg_timed'] >= 0xC000:   # (the test code is in the card's
        test_only = 0               #   driver area since wave 1's
                                    #   integration: not in module_sizes)
    total = ms.get('sight', 0) + ms.get('sfrac', 0)
    return {'sight.s': ms.get('sight', 0), 'sfrac.s': ms.get('sfrac', 0),
            'test_only': test_only, 'release': total - test_only,
            'test_build': total, 'budget': BUDGET,
            'upstream': UPSTREAM_BYTES}


def report(check_res: Optional[Dict[str, Any]] = None,
           rand: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if check_res is None and CHECK.exists():
        check_res = json.loads(CHECK.read_text())
    if rand is None and RANDOM_OUT.exists():
        rand = json.loads(RANDOM_OUT.read_text())
    rep: Dict[str, Any] = {'format': 'game-part-report 1', 'part': PART,
                           'wave': 1}
    sel = {}
    for key in ENTRIES:
        try:
            calls = calls_of(key)
            sel[key] = {'calls': len(calls), 'eligible': len(calls),
                        'selected': len(selection(key)),
                        'captured': len(case_files(key))}
        except PartError as error:
            sel[key] = {'error': str(error)}
    rep['selection'] = sel
    if check_res:
        rep['entries'] = summarize(check_res['results'])
        rep['check_seconds'] = check_res.get('seconds')
    rep['sizes'] = sizes()
    if rand:
        rep['random'] = rand
    pg = OUT / 'paging.json'
    if pg.exists():
        rep['paging'] = json.loads(pg.read_text())
    rep['eligibility'] = 'every call: P_CheckSight and its helpers reach no '\
        'dispatch target (gameroutine.eligibility)'
    REPORT.write_text(json.dumps(rep, indent=1) + '\n')
    return rep


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--paths', action='store_true')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--synthetic', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--random', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--paging', action='store_true')
    parser.add_argument('--runs', default=','.join(GC.RUNS))
    parser.add_argument('--entries', default=','.join(ENTRIES))
    parser.add_argument('--jobs', type=int, default=JOBS)
    parser.add_argument('--sample', type=int, default=1)
    parser.add_argument('--n', type=int, default=100_000)
    a = parser.parse_args(argv)
    why = missing()
    if why:
        say('cannot run: ' + why)
        return 2
    runs = [r for r in a.runs.split(',') if r]
    entries = [e for e in a.entries.split(',') if e]
    if a.paths:
        for run in runs:
            t = time.time()
            p = path_log(run)
            n = {k: len(v['tic']) for k, v in p['routines'].items()}
            say('%s: %s (%.0f s)' % (run, n, time.time() - t))
    if a.capture:
        made = capture(entries, runs, a.jobs)
        say('cases made: %s' % made)
    if a.synthetic:
        made = synthetic() + frac_synthetic()
        say('%d synthetic cases' % len(made))
    if a.check:
        build()
        res = check(entries, a.sample, a.jobs)
        CHECK.write_text(json.dumps(res) + '\n')
        s = summarize(res['results'])
        for k, v in s.items():
            say('%s: %d cases, %d runs, %d failed, %d stray; hintless %s; %s'
                % (k, v['cases'], v['runs'], v['failed'], v['stray_writes'],
                   v.get('hintless_failed'), v['paths']))
    if a.random:
        build()
        rep = random_checks(a.n)
        RANDOM_OUT.write_text(json.dumps(rep, indent=1) + '\n')
        say(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != 'first'}
                        if isinstance(v, dict) else v
                        for k, v in rep.items()}))
    if a.paging:
        build()
        pg = paging()
        (OUT / 'paging.json').write_text(json.dumps(pg, indent=1) + '\n')
        say(json.dumps(pg))
    if a.report:
        report()
        say('wrote %s' % REPORT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
