#!/usr/bin/env python3
"""Part tracel's checkpoint (milestone 10, docs/GAME.md 1.9, 2.4 row
tracel, 3.5): the captured calls of its entries, PIT_AddLineIntercepts
through P_BlockLinesIterator on the captured block steps of
P_PathTraverse, the random checks of its pure routines against
upstream's, the synthetic case of two equal fracs, and report.json.

Usage:  python3 tools/native/gparts/tracel.py --select
        python3 tools/native/gparts/tracel.py --paths
        python3 tools/native/gparts/tracel.py --capture [--entries ...]
        python3 tools/native/gparts/tracel.py --synth
        python3 tools/native/gparts/tracel.py --run [--entries ...]
                                             [--limit N] [--obj DIR]
        python3 tools/native/gparts/tracel.py --logs
        python3 tools/native/gparts/tracel.py --rand [--n 1000000]
        python3 tools/native/gparts/tracel.py --report
        python3 tools/native/gparts/tracel.py --all

Everything it writes is under build/native/game/tracel/ (the part's
directory, GAME.md 2.5): its own cases (cases/RUN/NAME/, gamecap.py's
format against a base of its own a run), select.json, the call logs'
inputs (logs/), the results (run.json, logs.json, rand.json) and
report.json; temporary files in build/tmp-tracel-* directories, deleted
after each step.

The selection (GAME.md 3.5 step 2): for each entry, every call of the
survey's runs when there are fewer than 300 (the last call of a run left
out), else 300 spread evenly, plus the calls that take a path no chosen
call takes (PATHS: from the survey's dispatch and from the case's inputs
after the capture, the coverage in the report). The block steps
(P_BlockLinesIterator called by P_PathTraverse's ptBody, whose callback is
PIT_AddLineIntercepts): CHOSEN_STEPS spread over every run. --paths adds
the calls of PIT_AddLineIntercepts' paths no chosen call takes (its call
log with its callees'); --synth makes the synthetic cases (synth_specs)
for the paths no run takes and the equal fracs.

A case runs (--run) on the part's test image (make -f game.mk part
P=tracel) from both poisoned machines ($A5, $5A) under f121 and fastpath:
the map's level base, the case's entry state through the manifest
(gameroutine's method, part geom's run harness: geom_check.run_native's
steps), with this part's args.json. Beyond geom's forms, the trace's
state: "trace" (upstream's _g_trace, TR_LONG, IV_ON, IV_ML, IV_MH,
VT_INVB to TL_TRACE, TL_TRLONG, TL_IVON, TL_IVM, TL_INVB) and "list" (the
intercepts: intercept_p's count, each intercept's frac and its line or
mobj, the chain IC_NEXT and IC_LAST to ICPT, ICHAIN, TL_ICN, TL_ICLAST);
as outputs, the list after the call (every intercept, the chain walked
from its head, IC_LAST) and the trace's state, compared exactly;
"carry" (upstream's A not 0 against the native C). Compared besides: the
canonical state (gcanon's routine mode, R1-R6 only), no stray write, the
time; the lowest S.

The random checks (--rand): interceptVector3 and divlineSide on
1,000,000 inputs each, the arithmetic helpers ivProd and smul on 100,000,
ivTest (FixedDiv with its guards) on 300,000 chosen around its
boundaries, ivAxis, ivSetup and vsC on 100,000 and gOf on all 65,536,
the edges first: upstream's routine by mathref's batch (tools/native/
mathref.c: ref816's machine running the routine from its entry, as
--call does) against the native one through the part's test driver
(tracelt.s) on a2vm; the step model of this file (MODEL) is checked
against both. FixedDiv never returns for one family of inputs (b shifted
to 0 while it is below a): the model names them; they are not sent to
upstream (its batch stops at a call that does not return), RAND_HANG of
them are run alone to show that upstream does not return, and the native
result there ($7FFFFFFF, GT_DIV0 counted: docs/game-parts/tracel.md R4)
is checked.

--logs: every call of interceptVector3 and divlineSide in the survey's
runs (ref816's call log, inputs and results), run natively: "every
captured input" of the checkpoint.
"""

import argparse
import json
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from bridge.port import PortReader, PortWriter  # noqa: E402
from native import gamecap as GC, gcanon, glayout as GL, grun as G, \
    llayout as LL  # noqa: E402
from native import gameroutine as GR  # noqa: E402
from ref816 import bounded, calls as CL, title  # noqa: E402
import geom_check as GK  # noqa: E402

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'tracel'
OUT = GL.GAME / PART
CASES = OUT / 'cases'
SYNTH = CASES / 'synth'
LOGS = OUT / 'logs'
ARGS = SRC / 'game' / PART / 'args.json'
IMAGE = 'ptest'
FILLS = (0xA5, 0x5A)
PROFILES = ('f121', 'fastpath')
COMBOS = [(f, p) for f in FILLS for p in PROFILES]
JOBS = 2
MIN_FREE = 20 * 10 ** 9
CAPTURE_BATCH = 250
CHOSEN = 300
CHOSEN_STEPS = 1000
UPSTREAM_DP = 0x900

ENTRIES = [k for p in GL.PARTS if p['name'] == PART for k in p['routines']]
HELPERS = [k for p in GL.PARTS if p['name'] == PART for k in p['helpers']]
ITER = 'p_map65.s:P_BlockLinesIterator'
PIT = 'p_trace65.s:PIT_AddLineIntercepts'
STEP_PARENT = 'p_path65.s:ptBody'

M32 = 0xFFFFFFFF
M16 = 0xFFFF
MAXINTERCEPTS, SIZEOF_IC = 64, 10
MM_B3F = 0x210000
IC_NEXT = MM_B3F + 0xE800
IC_LAST = MM_B3F + 0xEA84
IV_ML = MM_B3F + 0xF418
IV_ON = MM_B3F + 0xF420
VT_INVB = MM_B3F + 0xF412


class CheckError(Exception):
    pass


def check_disk() -> None:
    st = os.statvfs(str(BUILD))
    if st.f_bavail * st.f_frsize < MIN_FREE:
        raise CheckError('less than 20 GB free: stop')


def tmpdir(tag: str) -> Path:
    return Path(tempfile.mkdtemp(prefix='tmp-tracel-%s-' % tag,
                                 dir=str(BUILD)))


_TABLE = None


def table() -> CL.Linkmap:
    global _TABLE
    if _TABLE is None:
        _TABLE = CL.Linkmap()
    return _TABLE


def addr(sym: str) -> int:
    return table().address(sym)


# ---------------------------------------------------------------------------
# MODEL: upstream's routines step by step (p_trace65.s), for the inputs'
# choice (FixedDiv's inputs that never return) and as a third opinion
# ---------------------------------------------------------------------------

def s32(v: int) -> int:
    v &= M32
    return v - (1 << 32) if v & 0x80000000 else v


def s16(v: int) -> int:
    v &= M16
    return v - 0x10000 if v & 0x8000 else v


def fixed_div(a: int, b: int) -> Optional[int]:
    """fixedDiv (p_trace65.s:405-541, fdLoop 686-742) of a, b (num, den:
    both not 0, one sign): X:C, or None when it never returns."""
    a &= M32
    b &= M32
    if a & 0x80000000:
        a, b = -a & M32, -b & M32
    if b >> 16 < 0x4000 and a < b:                  # fdLoop from 2a
        return _cl_unsigned(2 * a & M32, b, 0)
    ibit, n = 1, 0
    while s32(b) < s32(a):
        if b == 0:
            return None                             # b stays 0 below a
        b = b << 1 & M32
        ibit = ibit << 1 & M16
        n += 1
    cl = 0
    if ibit == 0:
        return _cl_signed(a, b, 0)
    while True:                                     # the bits of ch
        if s32(a) >= s32(b):
            a, c = a - b & M32, 1
        else:
            c = 0
        cl = (cl << 1 | c) & M16
        a = a << 1 & M32
        ibit >>= 1
        if ibit == 0:
            return _cl_signed(a, b, cl)


def _cl_unsigned(a: int, b: int, ch: int) -> int:
    cl = 1
    while True:
        if a >= b:
            a, c = a - b & M32, 1
        else:
            c = 0
        out = cl >> 15
        cl = (cl << 1 | c) & M16
        if out:
            return ch << 16 | cl
        a = a << 1 & M32


def _cl_signed(a: int, b: int, ch: int) -> int:
    cl = 1
    while True:
        if s32(a) >= s32(b):
            a, c = a - b & M32, 1
        else:
            c = 0
        out = cl >> 15
        cl = (cl << 1 | c) & M16
        if out:
            return ch << 16 | cl
        a = a << 1 & M32


def iv_test(num: int, den: int) -> Optional[int]:
    num &= M32
    den &= M32
    if num == 0 or den == 0:
        return 0
    if (num ^ den) & 0x80000000:
        return M32
    return fixed_div(num, den)


def fixed_mul(a: int, b: int) -> int:
    return (s32(a) * s32(b)) >> 16 & M32


def side_prod(a: int, b: int) -> int:
    """SIDEPROD: the low 32 bits of (a >> 8) (b >> 16), signed."""
    return (s32(a) >> 8) * (s32(b) >> 16) & M32


def iv_prod(trace: Sequence[int], dl: Sequence[int], axis: int) -> int:
    """ivProd: FixedMul(trace.d, dl.o >> 8), X the axis (0: dx, dy; 4: dy,
    dx); both of upstream's paths give it."""
    d = trace[2] if axis == 0 else trace[3]
    o = dl[3] if axis == 0 else dl[2]
    return fixed_mul(d, s32(o) >> 8)


def iv_prod_up(trace: Sequence[int], dl: Sequence[int], axis: int,
               ivon: int, ivm: Sequence[int]) -> int:
    """ivProd as upstream decides: in a shot (IV_ON) with dl.o in whole
    units, n = dl.o >> 16 in -4096..4095, ML MB with the correction from
    MH (whatever IV_ML, IV_MH hold), else FixedMul."""
    o = dl[3 if axis == 0 else 2] & M32
    if ivon and not o & M16 and ((o >> 16) + 4096) & M16 < 8192:
        n = (o >> 16) << 3 & M16
        ml, mh = ivm[0 if axis == 0 else 2], ivm[1 if axis == 0 else 3]
        p = ml * n
        c = (mh & n) + (ml if n & 0x8000 else 0)
        return (p & M16) | (((p >> 16) - c) & M16) << 16
    return iv_prod(trace, dl, axis)


def iv3(trace: Sequence[int], dl: Sequence[int], ivon: int = 0,
        ivm: Sequence[int] = (0, 0, 0, 0)) -> Optional[int]:
    """interceptVector3 (trace x, y, dx, dy; dl x, y, dx, dy)."""
    tx, ty = trace[0], trace[1]
    x1, y1, dx, dy = dl
    if dy & M32 == 0 and dx & M32 == 0:
        return 0
    if dy & M32:
        a = side_prod(x1 - tx, dy)
        c = iv_prod_up(trace, dl, 0, ivon, ivm)
        if dx & M32 == 0:
            return iv_test(a, c)
    b = side_prod(ty - y1, dx)
    d = iv_prod_up(trace, dl, 4, ivon, ivm)
    if dy & M32 == 0:
        return iv_test(b, -d)
    return iv_test(a + b, c - d)


def divline_side(trace: Sequence[int], x: int, y: int) -> int:
    tx, ty, tdx, tdy = (s32(v) for v in trace)
    x, y = s32(x), s32(y)
    if tdx == 0:
        if tx < x:
            return 1 if tdy < 0 else 0
        return 1 if tdy > 0 else 0
    if tdy == 0:
        if ty < y:
            return 1 if tdx > 0 else 0
        return 1 if tdx < 0 else 0
    x, y = s32(x - tx), s32(y - ty)
    if (tdy ^ tdx ^ x ^ y) < 0:
        return 1 if (tdy ^ x) < 0 else 0
    left, right = s32(side_prod(y, tdx)), s32(side_prod(x, tdy))
    return 1 if left >= right else 0


def iv_axis(trace: Sequence[int], dl: Sequence[int], iv_on: int
            ) -> Tuple[int, Optional[int]]:
    """ivAxis: (1, frac) decided, (0, None) not; frac None: no return."""
    if not iv_on:
        return 0, None
    x1, y1, dx, dy = (v & M32 for v in dl)
    tr = [v & M32 for v in trace]

    def finish(na: int, nb: int) -> Tuple[int, Optional[int]]:
        na &= M32
        nb &= M32
        if (nb ^ na) & 0x80000000:                 # two signs
            if ((na >> 16) + 4096) & M16 >= 8192:
                return 0, None
        else:
            t = na - nb & M32
            if not (t ^ nb) & 0x80000000:
                return 0, None
            if t == 0:
                return 0, None
        return 1, iv_test(na, nb)

    dxh, dyh = dx >> 16, dy >> 16
    if dxh == 0 or dyh == 0:
        if dxh == 0:
            k, m = 0, dyh
        else:
            k, m = 4, dxh
        if (m + 2047) & M16 >= 4095:
            return 0, None
        o = x1 if k == 0 else y1
        t0 = tr[0] if k == 0 else tr[1]
        f = o - t0 & M32
        if k == 4:
            f = f + 255 & M32       # (rounded up for y)
        f &= 0xFFFFFF00
        dd = tr[2] if k == 0 else tr[3]
        return finish(f, dd)
    if dx & M16 or dy & M16:
        return 0, None
    p, q = abs(s16(dxh)), abs(s16(dyh))
    if p >= 1024 or q != p:
        return 0, None
    fx = (x1 - tr[0] & M32) & 0xFFFFFF00
    fy = (tr[1] - y1 & M32) & 0xFFFFFF00
    if not (dxh ^ dyh) & 0x8000:
        return finish(fx + fy, tr[2] - tr[3])
    return finish(fy - fx, -tr[2] - tr[3])


def iv_setup(trace: Sequence[int], ivm: Sequence[int]
             ) -> Tuple[int, List[int]]:
    """ivSetup: (A, IV_ML x, IV_MH x, IV_ML y, IV_MH y) from the trace's
    dx, dy and the old IV_M (16-bit words)."""
    out = list(ivm)
    for k in (1, 0):                                # dy, then dx
        d = trace[2 + k] & M32
        lo, h = d & M16, d >> 16
        if lo & 0x07FF:
            return 0, out
        if (h + 0x0800) & M16 >= 0x1000:
            return 0, out
        out[2 * k] = (h << 5 | lo >> 11) & M16
        out[2 * k + 1] = M16 if h & 0x8000 else 0
    return 1, out


def smul(a: int, b: int) -> int:
    return s16(a) * s16(b) & M32


def g_of(f: int) -> int:
    f &= M16
    if f == 0:
        return 0
    return (((f - 1) >> 8) - 255) & M16


def vs_c(sq: int, axis: int, gy: int, gx: int) -> Tuple[int, int]:
    g = {0: gy & M16, 4: gx & M16}
    sub, main = g[axis ^ 4], g[axis]
    p = smul(sub, sq)
    ty = ((p >> 16) + (p >> 15 & 1)) & M16
    c = (((main + 272) & M16) >> 5) - ty - 8 - 5 & M16
    vjsq = sq * 23 & M16
    ct = (~vjsq - 20) & M16
    cv = (c - vjsq) & M16
    return cv, ct


VJ, VBV, VBTH = 23, 5, 21


# ---------------------------------------------------------------------------
# The part's own case directory (gamecap.py's functions, pointed here)
# ---------------------------------------------------------------------------

@contextmanager
def own_cases() -> Iterator[None]:
    saved = GC.CASES, GC._BASES
    GC.CASES, GC._BASES = CASES, {}
    try:
        yield
    finally:
        GC.CASES, GC._BASES = saved


def native_name(key: str) -> str:
    return GL.native_names().get(key, key.replace(':', '_'))


def case_file(run: str, key: str, hit: int) -> Path:
    return CASES / run / native_name(CAPTURE_AS.get(key, key)) / \
        ('h%08d.case.z' % hit)


def synth_paths(key: str) -> List[Path]:
    d = SYNTH / native_name(key)
    return sorted(d.glob('s*.case.z')) if d.exists() else []


def load_case(path: Path) -> GC.Case:
    with own_cases():
        return GC.load_case(path)


# ---------------------------------------------------------------------------
# Selection (GAME.md 3.5 step 2)
# ---------------------------------------------------------------------------

# PIT_AddLineIntercepts is entered by callLN's JML [LN] (p_map65.s:2786),
# which ref816's --capture does not count: its calls are captured at
# callLN (JSL'd by P_BlockLinesIterator, the same state and return), in
# the runs where every P_BlockLinesIterator call is P_PathTraverse's, so
# that callLN's calls and PIT_AddLineIntercepts' are the same calls
CAPTURE_AS = {PIT: 'p_map65.s:callLN'}


def pit_runs() -> List[str]:
    out = []
    for run in GC.RUNS:
        sv = GC.survey_of(run)
        if sv is None:
            continue
        r = sv['routines'].get(ITER) or {}
        if set(r.get('parents', {})) <= {STEP_PARENT}:
            out.append(run)
    return out


def survey_calls(key: str, only: Optional[Sequence[str]] = None
                 ) -> List[Tuple[str, int, int, bool]]:
    """Every call of key in the survey's runs: (run, hit, tic, eligible),
    the last call of each run left out; only: the calls whose reached
    dispatch targets are all among these (None: any)."""
    built = set(GL.built_set()) | {PART}
    out = []
    runs = pit_runs() if key == PIT else GC.RUNS
    for run in runs:
        sv = GC.survey_of(run)
        if sv is None:
            continue
        r = sv['routines'].get(key)
        if r is None or not r['calls']:
            continue
        targets = sv['targets']
        for hit in range(1, r['calls']):
            reached = [targets[i] for i in r['reached'].get(str(hit), [])]
            if only is not None and not set(reached) <= set(only):
                continue
            ok = all((GL.owner_of(k) or 'core') in built for k in reached)
            out.append((run, hit, r['tic'][hit - 1], ok))
    return out


def spread(items: Sequence[Any], n: int) -> List[Any]:
    if len(items) <= n:
        return list(items)
    return [items[int((i + 0.5) * len(items) / n)] for i in range(n)]


def select() -> Dict[str, Any]:
    """The chosen calls of each entry: {key: {run: [[hit, tic]]}}; the
    block steps under ITER (P_BlockLinesIterator calls whose reached
    targets are PIT_AddLineIntercepts or none: the callback is checked
    on the case)."""
    out: Dict[str, Any] = {'format': 'tracel-select 1', 'entries': {}}
    for key in ENTRIES + [ITER]:
        if key == ITER:
            calls = survey_calls(key, only=[PIT])
            n = CHOSEN_STEPS
        else:
            calls = survey_calls(key)
            n = CHOSEN
        elig = [c for c in calls if c[3]]
        e: Dict[str, List[List[int]]] = {}
        for run, hit, tic, _ in spread(elig, n):
            e.setdefault(run, []).append([hit, tic])
        out['entries'][key] = {'calls': len(calls), 'eligible': len(elig),
                               'chosen': e}
    return out


def load_select() -> Dict[str, Any]:
    p = OUT / 'select.json'
    if not p.exists():
        raise CheckError('no %s: run tracel.py --select' % p)
    return json.loads(p.read_text())


def _capture_job(job: Tuple[str, str, List[int]]) -> str:
    run, key, hits = job
    check_disk()
    sv = GC.survey_of(run)
    tics = sv['routines'][key]['tic'] if sv else None
    with own_cases():
        made = GC.capture(run, CAPTURE_AS.get(key, key), hits, tics,
                          batch=CAPTURE_BATCH, say=lambda *a: None)
    return '%s %s: %d cases made' % (run, key, len(made))


def capture(entries: Sequence[str] = (), jobs: int = JOBS,
            say=print) -> None:
    sel = load_select()
    work = []
    for key, e in sel['entries'].items():
        if entries and key not in entries:
            continue
        for run, calls in e['chosen'].items():
            todo = [h for h, _ in calls if not case_file(run, key,
                                                         h).exists()]
            if todo:
                work.append((run, key, todo))
    firsts: Dict[str, Any] = {}
    for w in work:
        firsts.setdefault(w[0], w)
    first = list(firsts.values())
    rest = [w for w in work if w not in first]
    for group in (first, rest):
        if not group:
            continue
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for msg in pool.map(_capture_job, group):
                say(msg, flush=True)


# ---------------------------------------------------------------------------
# The random checks (--rand): upstream's routine (mathref batch) against
# the native one (tracelt.s on a2vm) and MODEL
# ---------------------------------------------------------------------------

MATHREF = BUILD / 'native' / 'math' / 'mathref'
REC_BANKS = (93, 94, 95, 96, 97)                 # tracelt.s's (spare)
REC_FIRST, REC_END = 0x0200, 0xC000
RAND_SEED = 2026102
RAND_HANG = 6
# kind: (number in tracelt.s, the routine, the return's bytes, upstream's
# inputs (symbol or address, length) and outputs, the record's input and
# output sizes)
KINDS = {
    'interceptVector3': (0, 'p_trace65.s:interceptVector3', 3,
                         [('_g_trace', 16), ('p_trace65.s:TC_X1', 16),
                          (IV_ON, 2), (IV_ML, 8)], ['a', 'x'], 41, 5),
    'divlineSide': (1, 'p_trace65.s:divlineSide', 3,
                    [('_g_trace', 16), ('p_trace65.s:TC_X', 8)], ['a'],
                    24, 1),
    'ivTest': (2, 'p_trace65.s:ivTest', 3, [('p_trace65.s:TC_A', 8)],
               ['a', 'x'], 8, 5),
    'ivAxis': (3, 'p_trace65.s:ivAxis', 3,
               [('_g_trace', 16), ('p_trace65.s:TC_X1', 16), (IV_ON, 2)],
               ['a', 'x', 'p'], 33, 6),
    'ivProd': (4, 'p_trace65.s:ivProd', 2,
               [('x', 2), ('_g_trace', 16), ('p_trace65.s:TC_X1', 16),
                (IV_ON, 2), (IV_ML, 8)], ['a', 'x'], 42, 4),
    'smul': (5, 'p_trace65.s:smul', 2, [('a', 2), ('x', 2)], ['a', 'x'],
             4, 4),
    'ivSetup': (6, 'p_trace65.s:ivSetup', 3,
                [('_g_trace', 16), (IV_ML, 8)], ['a', (IV_ML, 8)], 24, 9),
    'gOf': (7, 'p_trace65.s:gOf', 2, [('a', 2)], ['a'], 2, 2),
    'vsC': (8, 'p_trace65.s:vsC', 2,
            [('p_trace65.s:TC_X', 2), ('p_trace65.s:TC_T', 2),
             ('p_trace65.s:TC_A', 2), ('p_trace65.s:TC_B', 2)],
            [(MM_B3F + 0xF404, 2), (MM_B3F + 0xF406, 2)], 7, 4),
}
RAND_N = {'interceptVector3': 1_000_000, 'divlineSide': 1_000_000,
          'ivTest': 300_000, 'ivAxis': 100_000, 'ivProd': 100_000,
          'smul': 100_000, 'ivSetup': 100_000, 'gOf': 65_536,
          'vsC': 100_000}


def le(v: int, n: int) -> bytes:
    return (v & ((1 << (8 * n)) - 1)).to_bytes(n, 'little')


def u(data: bytes) -> int:
    return int.from_bytes(data, 'little')


def _where(x) -> int:
    return x if isinstance(x, int) else addr(x)


def spec_text(kind: str) -> str:
    _, key, _, ins, outs, _, _ = KINDS[kind]
    lines = ['routine %s %06X' % (kind, addr(key))]
    for w, n in ins:
        if w in ('a', 'x', 'y', 'p'):
            lines.append('in %s' % w)
        else:
            lines.append('in %06X %d' % (_where(w), n))
    for o in outs:
        if isinstance(o, str):
            lines.append('out %s' % o)
        else:
            lines.append('out %06X %d' % (_where(o[0]), o[1]))
    return '\n'.join(lines) + '\n'


def entry_case() -> GC.Case:
    """A captured call of interceptVector3 (its registers, switches and
    direct page: every routine of the batch runs from them)."""
    for run in GC.RUNS:
        d = CASES / run / native_name('p_trace65.s:interceptVector3')
        ps = sorted(d.glob('h*.case.z')) if d.exists() else []
        if ps:
            return load_case(ps[0])
    raise CheckError('no case of interceptVector3 (tracel.py --capture)')


def entry_text(case: GC.Case, kind: str) -> str:
    f = struct.unpack_from(GK.HEADER_FORMAT, case.entry.header, 8)
    names = ('pc', 'pbr', 'dbr', 'a', 'x', 'y', 's', 'd', 'p', 'e')
    r = dict(zip(names, f[:10]))
    ret = KINDS[kind][2]
    stack = case.entry.read((r['s'] + 1) & 0xFFFF, ret)
    return ('pc %06X\ndbr %02X\nd %04X\np %02X\ne %u\ns %04X\na %04X\n'
            'x %04X\ny %04X\nret %u\nstack %s\nswitches %s\n' % (
                addr(KINDS[kind][1]), r['dbr'], r['d'], r['p'], r['e'],
                r['s'], r['a'], r['x'], r['y'], ret,
                ' '.join('%02X' % b for b in stack),
                ' '.join('%02X' % b for b in f[10:14])))


_RAM = None


def ram() -> bytes:
    global _RAM
    if _RAM is None:
        _RAM = GK.ram_of_map(1)
    return _RAM


def upstream_batch(kind: str, inputs: Sequence[bytes], case: GC.Case
                   ) -> List[bytes]:
    """upstream's outputs of each input record (in spec order: registers
    as 2 bytes), by mathref's batch."""
    outs = KINDS[kind][4]
    n = sum(2 if isinstance(o, str) else o[1] for o in outs)
    work = tmpdir('ref')
    try:
        (work / 'ram.bin').write_bytes(ram())
        (work / 'entry.txt').write_text(entry_text(case, kind))
        (work / 'spec.txt').write_text(spec_text(kind))
        (work / 'cases.bin').write_bytes(b''.join(inputs))
        r = bounded.run([str(MATHREF), 'batch', str(work / 'ram.bin'),
                         str(work / 'entry.txt'), str(work / 'spec.txt'),
                         kind, str(work / 'cases.bin'),
                         str(work / 'out.bin')],
                        timeout=1800, max_bytes=256 << 20,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r.returncode:
            raise CheckError('mathref batch %s: %s' % (kind,
                                                      r.stdout[-600:]))
        data = (work / 'out.bin').read_bytes()
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    k = n + 4
    return [data[i:i + n] for i in range(0, len(data), k)]


def upstream_returns(kind: str, record: bytes, case: GC.Case) -> bool:
    """Whether upstream's routine returns on one input (mathref's batch
    gives up after 100,000,000 cycles)."""
    try:
        upstream_batch(kind, [record], case)
    except CheckError as error:
        if 'did not return' in str(error):
            return False
        raise
    return True


def per_run(kind: str) -> int:
    size = KINDS[kind][5] + KINDS[kind][6]
    return (REC_END - REC_FIRST) // size * len(REC_BANKS)


def native_batch(b, kind: str, records: Sequence[bytes], fill: int
                 ) -> List[bytes]:
    """The records (inputs) through tl_t_run on the part's image: each
    record's outputs."""
    num, _, _, _, _, isz, osz = KINDS[kind]
    size = isz + osz
    per = (REC_END - REC_FIRST) // size
    if len(records) > per * len(REC_BANKS):
        raise CheckError('too many records for a run')
    img = G.Image(b, fill, store=True)
    img.recs += GR.base_records(1)
    for i, bank in enumerate(REC_BANKS):
        chunk = b''.join(r + bytes(osz) for r in
                         records[i * per:(i + 1) * per])
        if chunk:
            img.aux(bank, REC_FIRST, chunk)
    img.poke_label('tl_t_kind', bytes([num]))
    img.poke_word('tl_t_count', len(records))
    work = tmpdir('nat')
    try:
        r = GK.run_entry(img, work, 'tl_t_run', banks=REC_BANKS,
                         cycles=200_000_000_000)
        if r.ended() != 'halt':
            stop = None
            if (work / 'crash.img').exists():
                stop = G.stop_codes(G.load_snapshot(work / 'crash.img'))
            raise CheckError('the native batch ended %s (stop %s)' % (
                r.ended(), stop))
        m = G.load_snapshot(work / 'done.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    out = []
    for i in range(len(records)):
        bank = REC_BANKS[i // per]
        at = REC_FIRST + size * (i % per) + isz
        out.append(bytes(m.aux[bank][at:at + osz]))
    return out


# The inputs: each kind's generator gives dicts; up_record and nat_record
# pack them for mathref's spec and for tracelt.s

def _fx(rng: random.Random, units: int) -> int:
    """A fixed_t within +-units, any fraction."""
    return rng.randrange(-units << 16, units << 16) & M32


def _whole(rng: random.Random, units: int) -> int:
    return (rng.randrange(-units, units + 1) << 16) & M32


SHOT_K = (2048, 2048, 2048, 64, 1024, 128)
COS_EDGE = (0, 1, -1, 65536, -65536, 65535, -65535, 32768, -32768)


def rand_trace(rng: random.Random) -> List[int]:
    """x, y, dx, dy: a shot's (range times a cosine: the 11 low bits of a
    2048-unit range's deltas are 0), an axis trace, a use or slide trace,
    a long one, or any 32 bits."""
    k = rng.random()
    x, y = _fx(rng, 4096), _fx(rng, 4096)
    if k < 0.45:
        r = rng.choice(SHOT_K)
        cs = [rng.choice(COS_EDGE) if rng.random() < 0.1 else
              rng.randrange(-65536, 65537) for _ in range(2)]
        dx, dy = r * cs[0] & M32, r * cs[1] & M32
    elif k < 0.6:
        d = _fx(rng, rng.choice((16, 64, 2048, 8192)))
        dx, dy = (d, 0) if rng.random() < 0.5 else (0, d)
    elif k < 0.85:
        u_ = rng.choice((1, 16, 64, 128, 2048))
        dx, dy = _fx(rng, u_), _fx(rng, u_)
    elif k < 0.95:
        dx, dy = _fx(rng, 32767), _fx(rng, 32767)
    else:
        x, y, dx, dy = (rng.getrandbits(32) for _ in range(4))
    return [x, y, dx, dy]


def rand_dl(rng: random.Random, trace: Sequence[int]) -> List[int]:
    """x1, y1, dx, dy: a line's (whole units: axis, 45 degrees, any, long,
    none), a thing's diagonal (fractions), or any 32 bits."""
    k = rng.random()
    tx, ty = s32(trace[0]) >> 16, s32(trace[1]) >> 16
    near = rng.choice((64, 512, 4096))
    x1 = (tx + rng.randrange(-near, near + 1)) << 16 & M32
    y1 = (ty + rng.randrange(-near, near + 1)) << 16 & M32
    if k < 0.3:
        m = rng.choice((rng.randrange(-2047, 2048), 2047, -2047, 2048,
                        -2048, 2049, 0, 1, -1))
        dx, dy = (0, m << 16 & M32) if rng.random() < 0.5 else \
            (m << 16 & M32, 0)
    elif k < 0.45:
        p = rng.choice((rng.randrange(1, 1024), 1023, 1024, 1025))
        dx = p << 16 if rng.random() < 0.5 else -p << 16
        dy = p << 16 if rng.random() < 0.5 else -p << 16
        if rng.random() < 0.1:
            dy = (p + rng.choice((1, -1))) << 16
        dx, dy = dx & M32, dy & M32
    elif k < 0.7:
        dx, dy = _whole(rng, 2048), _whole(rng, 2048)
    elif k < 0.8:
        n = rng.choice((4095, 4096, -4096, -4097, 4097, 8191, -8192))
        dx, dy = (n << 16 & M32, _whole(rng, 4096)) if rng.random() < 0.5 \
            else (_whole(rng, 4096), n << 16 & M32)
    elif k < 0.9:
        r = rng.choice((16, 20, 24, 32, 64, 128))
        x1 = (trace[0] + _fx(rng, 512)) & M32
        y1 = (trace[1] + _fx(rng, 512)) & M32
        dx = (2 * r << 16) & M32 if rng.random() < 0.5 else -(2 * r << 16) \
            & M32
        dy = (2 * r << 16) & M32 if rng.random() < 0.5 else -(2 * r << 16) \
            & M32
    elif k < 0.93:
        dx, dy = 0, 0
    else:
        x1, y1, dx, dy = (rng.getrandbits(32) for _ in range(4))
    return [x1, y1, dx, dy]


def rand_ivon(rng: random.Random, trace: Sequence[int]
              ) -> Tuple[int, List[int]]:
    """IV_ON and IV_ML, IV_MH (four words) as sideSetup leaves them for a
    shot: ivSetup's; else off (old words); 3% on with any words."""
    old = [rng.getrandbits(16) for _ in range(4)]
    k = rng.random()
    if k < 0.03:
        return 1, old
    on, ivm = iv_setup(trace, old)
    if k < 0.6:
        return on, ivm
    return 0, old


def gen(kind: str, n: int, seed: int = RAND_SEED) -> List[Dict[str, Any]]:
    rng = random.Random('%s-%d' % (kind, seed))
    out: List[Dict[str, Any]] = []
    edges = EDGES.get(kind, lambda: [])()
    out += edges[:n]
    while len(out) < n:
        out.append(GENS[kind](rng))
    return out


def _g_iv3(rng):
    tr = rand_trace(rng)
    on, ivm = rand_ivon(rng, tr)
    return {'trace': tr, 'dl': rand_dl(rng, tr), 'ivon': on, 'ivm': ivm}


def _g_side(rng):
    tr = rand_trace(rng)
    k = rng.random()
    if k < 0.2:                                     # on the trace's line
        t = rng.random() * 2 - 0.5
        x = tr[0] + int(s32(tr[2]) * t) & M32
        y = tr[1] + int(s32(tr[3]) * t) & M32
    elif k < 0.3:
        x, y = tr[0], tr[1]
    elif k < 0.9:
        x = (tr[0] + _fx(rng, rng.choice((1, 64, 4096)))) & M32
        y = (tr[1] + _fx(rng, rng.choice((1, 64, 4096)))) & M32
    else:
        x, y = rng.getrandbits(32), rng.getrandbits(32)
    if rng.random() < 0.3:                          # whole units (vertices)
        x &= 0xFFFF0000
        y &= 0xFFFF0000
    return {'trace': tr, 'x': x, 'y': y}


def _g_test(rng):
    k = rng.random()
    if k < 0.25:                    # b around 2^30: the guard
        b = (1 << 30) + rng.randrange(-(1 << 25), 1 << 25)
        a = rng.choice((rng.randrange(1, b), b - 1, b, b + 1,
                        rng.randrange(1, 1 << 31), (1 << 30) + rng.randrange(
                            -(1 << 20), 1 << 20)))
    elif k < 0.4:                   # a around b
        b = rng.getrandbits(rng.randrange(1, 32)) or 1
        a = max(1, b + rng.randrange(-4, 5))
    elif k < 0.6:                   # a about b 2^k
        b = rng.getrandbits(rng.randrange(1, 31)) or 1
        a = (b << rng.randrange(0, 18)) + rng.randrange(-3, 4)
    elif k < 0.85:
        a = rng.getrandbits(rng.randrange(1, 32)) or 1
        b = rng.getrandbits(rng.randrange(1, 32)) or 1
    elif k < 0.9:                   # the guards: zeros and signs
        a = rng.choice((0, rng.getrandbits(32)))
        b = rng.choice((0, rng.getrandbits(32)))
        return {'num': a & M32, 'den': b & M32}
    else:
        a, b = rng.getrandbits(32), rng.getrandbits(32)
        return {'num': a, 'den': b}
    a &= 0x7FFFFFFF
    b &= 0x7FFFFFFF
    a = a or 1
    b = b or 1
    if rng.random() < 0.5:
        a, b = -a & M32, -b & M32
    return {'num': a, 'den': b}


def _g_axis(rng):
    tr = rand_trace(rng)
    on = 1 if rng.random() < 0.9 else 0
    dl = rand_dl(rng, tr)
    if rng.random() < 0.15:         # N - D near 0 (one sign)
        dl[0] = (tr[0] + tr[2]) & 0xFFFF0000
        dl[1] = (tr[1] - tr[3]) & 0xFFFF0000
    return {'trace': tr, 'dl': dl, 'ivon': on}


def _g_prod(rng):
    d = _g_iv3(rng)
    d['axis'] = rng.choice((0, 4))
    return d


def _g_smul(rng):
    e = (0, 1, 0xFFFF, 0x7FFF, 0x8000, 0x8001, 0x00FF, 0xFF00)
    a = rng.choice(e) if rng.random() < 0.1 else rng.getrandbits(16)
    b = rng.choice(e) if rng.random() < 0.1 else rng.getrandbits(16)
    return {'a': a, 'b': b}


def _g_setup(rng):
    tr = rand_trace(rng)
    if rng.random() < 0.3:          # H at its edges, 11 low bits 0
        for i in (2, 3):
            h = rng.choice((-2049, -2048, -2047, 2046, 2047, 2048, 0, -1))
            tr[i] = (h << 16 | rng.randrange(32) << 11) & M32
    return {'trace': tr, 'ivm': [rng.getrandbits(16) for _ in range(4)]}


def _g_vsc(rng):
    sq = rng.randrange(-2048, 2049) if rng.random() < 0.8 else \
        rng.getrandbits(16)
    g = [g_of(rng.getrandbits(16)) if rng.random() < 0.8 else
         rng.getrandbits(16) for _ in range(2)]
    return {'sq': sq & M16, 'axis': rng.choice((0, 4)), 'gy': g[0],
            'gx': g[1]}


GENS = {'interceptVector3': _g_iv3, 'divlineSide': _g_side,
        'ivTest': _g_test, 'ivAxis': _g_axis, 'ivProd': _g_prod,
        'smul': _g_smul, 'ivSetup': _g_setup, 'vsC': _g_vsc}
EDGE32 = (0, 1, M32, 0x7FFFFFFF, 0x80000000, 0x40000000, 0x3FFFFFFF,
          0x40000001, 0xC0000000, 0xBFFFFFFF, 0x00010000, 0xFFFF0000)


def _edges_test():
    return [{'num': a, 'den': b} for a in EDGE32 for b in EDGE32]


def _edges_smul():
    e = (0, 1, 0xFFFF, 0x7FFF, 0x8000)
    return [{'a': a, 'b': b} for a in e for b in e]


EDGES = {'ivTest': _edges_test, 'smul': _edges_smul,
         'gOf': lambda: [{'f': f} for f in range(65536)]}
GENS['gOf'] = lambda rng: {'f': rng.getrandbits(16)}


def w32s(vs: Sequence[int]) -> bytes:
    return b''.join(le(v, 4) for v in vs)


def up_record(kind: str, d: Dict[str, Any]) -> bytes:
    if kind == 'interceptVector3':
        return w32s(d['trace']) + w32s(d['dl']) + le(d['ivon'], 2) + \
            b''.join(le(v, 2) for v in d['ivm'])
    if kind == 'divlineSide':
        return w32s(d['trace']) + le(d['x'], 4) + le(d['y'], 4)
    if kind == 'ivTest':
        return le(d['num'], 4) + le(d['den'], 4)
    if kind == 'ivAxis':
        return w32s(d['trace']) + w32s(d['dl']) + le(d['ivon'], 2)
    if kind == 'ivProd':
        return le(d['axis'], 2) + w32s(d['trace']) + w32s(d['dl']) + \
            le(d['ivon'], 2) + b''.join(le(v, 2) for v in d['ivm'])
    if kind == 'smul':
        return le(d['a'], 2) + le(d['b'], 2)
    if kind == 'ivSetup':
        return w32s(d['trace']) + b''.join(le(v, 2) for v in d['ivm'])
    if kind == 'gOf':
        return le(d['f'], 2)
    if kind == 'vsC':
        return le(d['sq'], 2) + le(d['axis'], 2) + le(d['gy'], 2) + \
            le(d['gx'], 2)
    raise CheckError(kind)


def nat_record(kind: str, d: Dict[str, Any]) -> bytes:
    if kind == 'interceptVector3':
        return w32s(d['trace']) + w32s(d['dl']) + le(d['ivon'], 1) + \
            b''.join(le(v, 2) for v in d['ivm'])
    if kind == 'ivAxis':
        return w32s(d['trace']) + w32s(d['dl']) + le(d['ivon'], 1)
    if kind == 'ivProd':
        return w32s(d['trace']) + w32s(d['dl']) + le(d['ivon'], 1) + \
            b''.join(le(v, 2) for v in d['ivm']) + le(d['axis'], 1)
    if kind == 'vsC':
        return le(d['sq'], 2) + le(d['axis'], 1) + le(d['gy'], 2) + \
            le(d['gx'], 2)
    return up_record(kind, d)


def model_out(kind: str, d: Dict[str, Any]) -> Any:
    """MODEL's result in the form both sides are read into."""
    if kind == 'interceptVector3':
        return iv3(d['trace'], d['dl'], d['ivon'], d['ivm'])
    if kind == 'divlineSide':
        return divline_side(d['trace'], d['x'], d['y'])
    if kind == 'ivTest':
        return iv_test(d['num'], d['den'])
    if kind == 'ivAxis':
        c, f = iv_axis(d['trace'], d['dl'], d['ivon'])
        return (c, f) if c else (0, None)
    if kind == 'ivProd':
        return iv_prod_up(d['trace'], d['dl'], d['axis'], d['ivon'],
                          d['ivm'])
    if kind == 'smul':
        return smul(d['a'], d['b'])
    if kind == 'ivSetup':
        a, ivm = iv_setup(d['trace'], d['ivm'])
        return (a, tuple(ivm))
    if kind == 'gOf':
        return g_of(d['f'])
    if kind == 'vsC':
        return vs_c(d['sq'], d['axis'], d['gy'], d['gx'])
    raise CheckError(kind)


def read_up(kind: str, data: bytes) -> Any:
    if kind in ('interceptVector3', 'ivTest', 'ivProd', 'smul'):
        return u(data[0:2]) | u(data[2:4]) << 16
    if kind == 'divlineSide':
        return u(data[0:2])
    if kind == 'ivAxis':
        c = data[4] & 1
        return (c, u(data[0:2]) | u(data[2:4]) << 16) if c else (0, None)
    if kind == 'ivSetup':
        return (u(data[0:2]), tuple(u(data[2 + 2 * i:4 + 2 * i])
                                    for i in range(4)))
    if kind == 'gOf':
        return u(data[0:2])
    if kind == 'vsC':
        return (u(data[0:2]), u(data[2:4]))
    raise CheckError(kind)


def read_nat(kind: str, data: bytes) -> Tuple[Any, int]:
    """(the result, GT_DIV0's count)."""
    if kind in ('interceptVector3', 'ivTest'):
        return u(data[0:4]), data[4]
    if kind == 'ivAxis':
        c = data[0] & 1
        return ((c, u(data[1:5])) if c else (0, None)), data[5]
    if kind in ('ivProd', 'smul'):
        return u(data[0:4]), 0
    if kind == 'divlineSide':
        return data[0], 0
    if kind == 'ivSetup':
        return (data[0], tuple(u(data[1 + 2 * i:3 + 2 * i])
                               for i in range(4))), 0
    if kind == 'gOf':
        return u(data[0:2]), 0
    if kind == 'vsC':
        return (u(data[0:2]), u(data[2:4])), 0
    raise CheckError(kind)


RAND = OUT / 'rand'


def hangs(kind: str, want: Any) -> bool:
    return want is None or (isinstance(want, tuple) and want[0] == 1 and
                            want[1] is None)


def upstream_results(kind: str, xs: Sequence[Dict[str, Any]],
                     keep: Sequence[int], case: GC.Case) -> List[Any]:
    """upstream's results of xs[i] for i in keep (cached in rand/KIND.z by
    the inputs' digest)."""
    import hashlib
    recs = [up_record(kind, xs[i]) for i in keep]
    h = hashlib.sha256(b''.join(recs) + spec_text(kind).encode() +
                       entry_text(case, kind).encode()).hexdigest()[:16]
    p = RAND / ('%s-%d-%s.z' % (kind, len(recs), h))
    if p.exists():
        data = zlib.decompress(p.read_bytes())
        n = len(data) // len(recs)
        outs = [data[i * n:(i + 1) * n] for i in range(len(recs))]
    else:
        outs = upstream_batch(kind, recs, case)
        RAND.mkdir(parents=True, exist_ok=True)
        for old in RAND.glob('%s-*.z' % kind):
            old.unlink()
        p.write_bytes(zlib.compress(b''.join(outs), 6))
    return [read_up(kind, o) for o in outs]


def _nat_job(job) -> List[bytes]:
    obj, kind, recs, fill = job
    b = G.load_build(Path(obj), IMAGE)
    return native_batch(b, kind, recs, fill)


def native_results(kind: str, xs: Sequence[Dict[str, Any]], obj: Path,
                   jobs: int, fill: int) -> List[Tuple[Any, int]]:
    per = per_run(kind)
    recs = [nat_record(kind, d) for d in xs]
    work = [(str(obj), kind, recs[i:i + per], fill)
            for i in range(0, len(recs), per)]
    out: List[bytes] = []
    if jobs > 1 and len(work) > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for got in pool.map(_nat_job, work):
                out += got
    else:
        for w in work:
            out += _nat_job(w)
    return [read_nat(kind, o) for o in out]


def _fmt(v: Any) -> Any:
    if isinstance(v, int):
        return '%X' % v
    if isinstance(v, tuple):
        return [_fmt(x) for x in v]
    return v


def rand_kind(kind: str, n: int, obj: Path = OUT, jobs: int = JOBS,
              fill: int = FILLS[0], hang_checks: int = RAND_HANG,
              case: Optional[GC.Case] = None, say=print) -> Dict[str, Any]:
    """n inputs of kind: upstream (the ones it returns from) against the
    native routine; MODEL against both; the inputs upstream never returns
    from (MODEL's): the native result $7FFFFFFF with GT_DIV0 counted, and
    hang_checks of them run on upstream alone to show it does not
    return."""
    case = case or entry_case()
    t0 = time.time()
    xs = gen(kind, n)
    model = [model_out(kind, d) for d in xs]
    keep = [i for i, m in enumerate(model) if not hangs(kind, m)]
    hung = [i for i, m in enumerate(model) if hangs(kind, m)]
    ups = upstream_results(kind, xs, keep, case)
    t1 = time.time()
    nats = native_results(kind, xs, obj, jobs, fill)
    t2 = time.time()
    bad, model_bad, div0_bad = [], [], []
    for i, up in zip(keep, ups):
        got, div0 = nats[i]
        if got != up:
            bad.append(i)
        if div0:
            div0_bad.append(i)
        if model[i] != up:
            model_bad.append(i)
    hang_bad = []
    exp = (1, 0x7FFFFFFF) if kind == 'ivAxis' else 0x7FFFFFFF
    for i in hung:
        got, div0 = nats[i]
        if got != exp or div0 != 1:
            hang_bad.append(i)
    confirmed = 0
    for i in hung[:hang_checks]:
        if upstream_returns(kind, up_record(kind, xs[i]), case):
            hang_bad.append(i)
        else:
            confirmed += 1
    paths: Dict[str, int] = {}
    for d, m in zip(xs, model):
        if kind == 'interceptVector3':
            ps = _iv3_paths(d['trace'], d['dl'], d['ivon'], d['ivm'])
        elif kind == 'ivTest':
            ps = _test_paths(d['num'], d['den'])
        elif kind == 'ivAxis':
            ps = ['decided' if m[0] else 'not decided']
        elif kind == 'divlineSide':
            ps = [_side_path(d['trace'], d['x'], d['y'])]
        elif kind == 'ivProd':
            o = d['dl'][3 if d['axis'] == 0 else 2] & M32
            ps = ['fast' if d['ivon'] and not o & M16 and
                  ((o >> 16) + 4096) & M16 < 8192 else 'slow']
        else:
            ps = []
        for p in ps:
            paths[p] = paths.get(p, 0) + 1
    res = {'inputs': n, 'upstream_ran': len(keep), 'failed': len(bad),
           'paths': paths,
           'div0_raised': len(div0_bad), 'model_differs': len(model_bad),
           'no_return': len(hung), 'no_return_confirmed': confirmed,
           'no_return_native_bad': len(hang_bad),
           'fill': '%02X' % fill, 'edges': len(EDGES.get(kind,
                                                       lambda: [])()),
           'seconds_upstream': round(t1 - t0, 1),
           'seconds_native': round(t2 - t1, 1),
           'first': [{'input': {k: _fmt(v) if not isinstance(v, list) else
                                [_fmt(x) for x in v]
                                for k, v in xs[i].items()},
                      'upstream': _fmt(up), 'native': _fmt(nats[i][0])}
                     for i, up in zip(keep, ups) if i in set(bad[:5])]}
    say('%s: %d inputs, %d failed, %d with GT_DIV0, model %d different; '
        '%d never return upstream (%d confirmed, %d native bad)' % (
            kind, n, len(bad), len(div0_bad), len(model_bad), len(hung),
            confirmed, len(hang_bad)), flush=True)
    return res


def rand_failures(r: Dict[str, Any]) -> int:
    return r['failed'] + r['div0_raised'] + r['model_differs'] + \
        r['no_return_native_bad']


def rand_all(obj: Path = OUT, n: Optional[int] = None, jobs: int = JOBS,
             kinds: Sequence[str] = (), say=print) -> Dict[str, Any]:
    case = entry_case()
    out: Dict[str, Any] = {'format': 'tracel-rand 1', 'kinds': {}}
    for i, kind in enumerate(kinds or list(RAND_N)):
        k = RAND_N[kind] if n is None else min(n, RAND_N[kind])
        out['kinds'][kind] = rand_kind(kind, k, obj, jobs, FILLS[i % 2],
                                       case=case, say=say)
    out['failures'] = sum(rand_failures(r) for r in out['kinds'].values())
    return out


# ---------------------------------------------------------------------------
# Building: the part's image, and a planted one from a scratch copy
# ---------------------------------------------------------------------------

def build(source: Path = SRC, game: Optional[Path] = None) -> Path:
    """make -f game.mk part P=tracel (source: the tree's src/native or a
    scratch copy; game: its GAME directory): the image's directory. A
    warning fails it."""
    # (TL_TEST=1: tracelt.s, the random checks' driver, is linked in the
    # part's own image only: the final integration's part.mk)
    cmd = ['make', '-s', '-C', str(source), '-f', 'game.mk', 'part',
           'P=%s' % PART, 'ROOT=%s' % ROOT, 'TL_TEST=1']
    if game is not None:
        cmd.append('GAME=%s' % game)
    r = bounded.run(cmd, timeout=600, max_bytes=16 << 20,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    universal_newlines=True)
    if r.returncode:
        raise CheckError('the build failed:\n' + r.stdout[-3000:])
    if 'arning' in r.stdout:
        raise CheckError('the build warns:\n' + r.stdout[-3000:])
    return (game or GL.GAME) / PART


def planted(tmp: Path, bugs: Sequence[Tuple[str, str, str]]) -> Path:
    """The part's image from a scratch copy in tmp (game.mk, the
    fragments, the part's own files, each (file, old, new) of bugs applied
    once; the rest through game.mk's vpath): its directory."""
    src = tmp / 'src'
    for f in G.PLANT_COPY:
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(SRC / f), str(src / f))
    part = SRC / 'game' / PART
    (src / 'game' / PART).mkdir(parents=True, exist_ok=True)
    for f in part.iterdir():
        if f.is_file():
            shutil.copy(str(f), str(src / 'game' / PART / f.name))
    for name, old, new in bugs:
        path = src / name
        text = path.read_text()
        if text.count(old) != 1:
            raise CheckError('the bug no longer applies: %r' % old)
        path.write_text(text.replace(old, new))
    return build(src, tmp / 'game')


# The planted bugs (docs/GAME.md 2.4 row tracel), each (file, old, new) in
# src/native/ and the check that must fail
PLANTS = {
    # FixedDiv's guard one off: b's top byte below $41 (not $40) taken as
    # "b < 2^30", so the fast loop's unsigned compares run where upstream's
    # signed ones do (random inputs of ivTest)
    'fixeddiv-guard': ([('game/tracel/tracel.s', """@pos:   lda TL_B+3
        cmp #$40""", """@pos:   lda TL_B+3
        cmp #$41                        ; (planted)""")], 'rand:ivTest'),
    # the fast product path deciding where upstream's does not: n up to
    # 4351 (not 4095) taken as -4096..4095 (random inputs of ivProd)
    'fast-product': ([('game/tracel/tracel.s', """        adc #$10
        cmp #$20
        bcs @slow""", """        adc #$10
        cmp #$21                        ; (planted)
        bcs @slow""")], 'rand:ivProd'),
    # an equal frac inserted before the old one: the walk stops at the
    # first frac above or equal (synthetic: two intercepts of equal frac)
    'equal-before': ([('game/tracel/tracel.s', """        FRACLT TL_P1, TL_P2
        bpl @walk2""", """        FRACLT TL_P2, TL_P1             ; (planted)
        bmi @walk2""")], 'synth:equal'),
}


# ---------------------------------------------------------------------------
# The trace's state and the intercepts: upstream's, in the native form
# ---------------------------------------------------------------------------

ICPT, ICHAIN = LL.GWA['ICPT'], LL.GWA['ICHAIN']


def up_trace(mem) -> Dict[str, Any]:
    """The trace's state of a memory (a case's entry or return) as the
    native holds it."""
    return {'trace': bytes(mem.read(addr('_g_trace'), 16)),
            'trlong': mem.u16(addr('TR_LONG')) & 0xFF,
            'ivon': 1 if mem.u16(IV_ON) else 0,
            'ivm': bytes(mem.read(IV_ML, 8)),
            'invb': mem.u16(VT_INVB) >> 8 & 0x80}


def nat_trace(b, m) -> Dict[str, Any]:
    lab = b.labels

    def rd(name: str, n: int) -> bytes:
        return bytes(m.main[lab[name]:lab[name] + n])
    return {'trace': rd('TL_TRACE', 16), 'trlong': rd('TL_TRLONG', 1)[0],
            'ivon': 1 if rd('TL_IVON', 1)[0] else 0,
            'ivm': rd('TL_IVM', 8), 'invb': rd('TL_INVB', 1)[0] & 0x80}


def trace_pokes(b, t: Dict[str, Any]) -> List[Tuple[int, bytes]]:
    lab = b.labels
    return [(lab['TL_TRACE'], t['trace']), (lab['TL_TRLONG'],
                                             bytes([t['trlong']])),
            (lab['TL_IVON'], bytes([t['ivon']])), (lab['TL_IVM'], t['ivm']),
            (lab['TL_INVB'], bytes([t['invb']]))]


def _link(v: int) -> int:
    """An IC_NEXT word (an offset, bit 15 the end) as a native link: the
    index, $FF the end, $FE no intercept's offset."""
    if v & 0x8000:
        return 0xFF
    if v % SIZEOF_IC or v // SIZEOF_IC > MAXINTERCEPTS:
        return 0xFE
    return v // SIZEOF_IC


UNNAMED = 0xFFFE


def what_of(up: GR.Upstream, mf, isaline: int, ptr: int, when: str) -> int:
    if isaline:
        return GK.classify(up, ptr, ('line',), when).id
    r = up.r_in if when == 'in' else up.r_out
    ref, why = r.classify(ptr & 0xFFFFFF, ('mobj', 'zmobj'))
    if ref is None:
        raise CheckError('intercept $%06X is no mobj (%s)' % (ptr, why))
    return 0x8000 | GR.handle_of(mf, ref)


def up_list(up: GR.Upstream, mf, when: str) -> Dict[str, Any]:
    """The intercepts of a case (at the entry or the return): their count,
    each one's frac and what, every link and the last one in (native
    indexes)."""
    mem = up.case.entry if when == 'in' else up.case.after
    base = addr('intercepts')
    ip = mem.u16(addr('intercept_p'))
    off = ip - (base & 0xFFFF)
    if off < 0 or off % SIZEOF_IC or off // SIZEOF_IC > MAXINTERCEPTS:
        raise CheckError('intercept_p $%04X' % ip)
    n = off // SIZEOF_IC
    # icInsert never reads intercept_p, so its case may not hold it: the
    # list then reaches at least the new intercept (Y) and every one the
    # chain names (upstream's own links, from the head)
    if up.case.key in ('p_trace65.s:icInsert',):
        y = up.case.regs_in['y'] & 0xFFFF
        n = max(n, y // SIZEOF_IC + 1)
        v = mem.u16(IC_NEXT + SIZEOF_IC * MAXINTERCEPTS)
        for _ in range(MAXINTERCEPTS + 1):
            if v & 0x8000 or v % SIZEOF_IC or v // SIZEOF_IC >= \
                    MAXINTERCEPTS:
                break
            n = max(n, v // SIZEOF_IC + 1)
            v = mem.u16(IC_NEXT + v)
    ents = []
    for i in range(n):
        a = base + SIZEOF_IC * i
        frac = u(mem.read(a, 4))
        isaline = mem.u16(a + 4)
        ptr = u(mem.read(a + 6, 3))
        try:
            what = what_of(up, mf, isaline, ptr, when)
        except (CheckError, GK.CheckError, GR.HarnessError):
            # (an intercept whose page the call never read: the case
            # holds the run's base there, which names nothing; the same
            # placeholder on both sides, so the native must leave it as
            # it is, as upstream does)
            what = UNNAMED
        ents.append((frac, what))
    links = [_link(mem.u16(IC_NEXT + SIZEOF_IC * i)) for i in range(n)]
    head = _link(mem.u16(IC_NEXT + SIZEOF_IC * MAXINTERCEPTS))
    last = _link(mem.u16(IC_LAST))
    return {'n': n, 'entries': ents, 'links': links, 'head': head,
            'last': last}


def list_pokes(lst: Dict[str, Any], b) -> List[Tuple[int, bytes]]:
    lab = b.labels
    out = [(lab['TL_ICN'], bytes([lst['n']])),
           (lab['TL_ICLAST'], bytes([lst['last']])),
           (ICHAIN + MAXINTERCEPTS, bytes([lst['head']]))]
    for i, (frac, what) in enumerate(lst['entries']):
        out.append((ICPT + 6 * i, le(frac, 4) + le(what, 2)))
    if lst['links']:
        out.append((ICHAIN, bytes(lst['links'])))
    return out


def nat_list(b, m) -> Dict[str, Any]:
    lab = b.labels
    n = m.main[lab['TL_ICN']]
    ents = []
    for i in range(min(n, MAXINTERCEPTS)):
        e = bytes(m.main[ICPT + 6 * i:ICPT + 6 * i + 6])
        ents.append((u(e[:4]), u(e[4:])))
    return {'n': n, 'entries': ents,
            'links': list(m.main[ICHAIN:ICHAIN + min(n, MAXINTERCEPTS)]),
            'head': m.main[ICHAIN + MAXINTERCEPTS],
            'last': m.main[lab['TL_ICLAST']]}


def walk(lst: Dict[str, Any]) -> List[int]:
    """The chain from its head (at most 65 steps; an index past the count
    or an invalid link ends it with -1)."""
    out = []
    v = lst['head']
    for _ in range(MAXINTERCEPTS + 1):
        if v == 0xFF:
            return out
        if v >= lst['n']:
            out.append(-1)
            return out
        out.append(v)
        v = lst['links'][v]
    out.append(-2)
    return out


def compare_list(want: Dict[str, Any], got: Dict[str, Any]) -> List[str]:
    out = []
    if want['n'] != got['n']:
        out.append('intercepts: %d, upstream %d' % (got['n'], want['n']))
    for i, (w, g) in enumerate(zip(want['entries'], got['entries'])):
        if w != g:
            out.append('intercept %d: frac %08X what %04X, upstream '
                       '%08X %04X' % (i, g[0], g[1], w[0], w[1]))
    ww, gw = walk(want), walk(got)
    if ww != gw:
        out.append('chain %s, upstream %s' % (gw[:16], ww[:16]))
    if want['last'] != got['last']:
        out.append('IC_LAST %d, upstream %d' % (got['last'], want['last']))
    return out[:6]


def compare_trace(want: Dict[str, Any], got: Dict[str, Any]) -> List[str]:
    return ['trace %s: %s, upstream %s' % (k, _fmt(got[k]) if not
                                           isinstance(got[k], bytes) else
                                           got[k].hex(),
                                           _fmt(want[k]) if not
                                           isinstance(want[k], bytes) else
                                           want[k].hex())
            for k in want if want[k] != got[k]]


# ---------------------------------------------------------------------------
# A case on the native image (geom_check.run_native's steps, with the
# trace's state)
# ---------------------------------------------------------------------------

def args() -> Dict[str, Any]:
    d = json.loads(ARGS.read_text())
    if d.get('format') != GR.ARGS_FORMAT:
        raise CheckError('%s: not %s' % (ARGS, GR.ARGS_FORMAT))
    return d


def spec_of(key: str) -> Dict[str, Any]:
    d = args()
    if key in d['entries']:
        return d['entries'][key]
    bs = d['block_steps']
    if key != bs['base']:
        raise CheckError('no spec for %s' % key)
    base = json.loads((ROOT / bs['args']).read_text())['entries'][key]
    return {'native': base['native'], 'in': base['in'] + bs['in'],
            'out': base['out'] + bs['out']}


SPECIAL_IN = ('trace', 'list', 'what', 'icoffset')


def run_native(case: GC.Case, spec: Dict[str, Any], b, fill: int,
               profile: Optional[str], pokes_native=()) -> Dict[str, Any]:
    up = GR.Upstream(case)
    res: Dict[str, Any] = {'case': case.path.name if case.path else
                           case.header.get('note'), 'routine': case.key,
                           'hit': case.header.get('hit'),
                           'fill': '%02x' % fill, 'profile': profile,
                           'ok': False}
    probs = up.r_in.problems + up.r_out.problems
    if probs:
        res['error'] = 'bridge: ' + '; '.join(probs[:3])
        return res
    if case.regs_in['d'] != UPSTREAM_DP:
        res['error'] = 'D $%04X' % case.regs_in['d']
        return res
    mf, header, banks = GR.manifest(up.gamemap)
    skip = gcanon.skips('routine', up.s_in)
    img = G.Image(b, fill, store=True)
    img.recs += GR.base_records(up.gamemap)
    pm = G.tracked_memory()
    PortWriter(mf).write(gcanon.strip(up.s_in, skip), pm)
    img.recs += G.port_records(pm)
    img.recs += GR.derived(pm, header)
    regs = [0, 0, 0, 0x34]
    for item in spec.get('in', []):
        src, to = item['from'], item['to']
        if src == 'trace':
            for a, d in trace_pokes(b, up_trace(case.entry)):
                img.main(a, d)
            continue
        if src == 'list':
            for a, d in list_pokes(up_list(up, mf, 'in'), b):
                img.main(a, d)
            continue
        if src == 'what':
            ptr = u(up.source('dp:_Dp+12:3', 'in'))
            w = what_of(up, mf, case.regs_in['a'] & 0xFFFF, ptr, 'in')
            regs[0], regs[1] = w & 0xFF, w >> 8
            continue
        if src == 'icoffset':
            y = case.regs_in['y'] & 0xFFFF
            if y % SIZEOF_IC or y // SIZEOF_IC >= MAXINTERCEPTS:
                raise CheckError('icInsert at offset %d' % y)
            regs[0] = y // SIZEOF_IC
            continue
        data = GK.convert_in(up, mf, item, GK.up_source(up, src, 'in'))
        n = item.get('bytes', len(data))
        data = data[:n].ljust(n, b'\0')
        if to in ('a', 'x', 'y'):
            regs['axy'.index(to)] = data[0]
        elif to == 'ax':
            regs[0], regs[1] = data[0], data[1]
        elif to.startswith(('zp:', 'main:', 'geo:', 'math:')):
            img.main(GK.native_address(b, to.split(':', 1)[1]), data)
        else:
            raise CheckError('an input destination %r' % to)
    for address, data in pokes_native:
        img.main(address, data)
    work = tmpdir('run')
    try:
        r = GK.run_entry(img, work, spec['native'], regs=tuple(regs),
                         banks=list(banks) + [LL.GTEST], profile=profile,
                         write_log=GK.write_log_ranges())
        res['lowest_s'] = (r.state.get('lowest_s') or {}).get('s')
        ended = r.ended()
        res['ended'] = ended
        if ended != 'halt':
            p = work / 'crash.img'
            if p.exists():
                res['stop'] = G.stop_codes(G.load_snapshot(p))
            return res
        m = G.load_snapshot(work / 'done.img')
        lines = GK.read_write_log(work / 'writes.log')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    win, t = GK.call_window(lines, b)
    if t is not None:
        res['clocks'], res['cycles'] = t
    res['writes'] = len(win)
    stray = GK.stray_writes(win, b, banks)
    res['stray'] = stray[:6]
    res['stray_n'] = len(stray)
    from native import setupcheck as SC
    nat = PortReader(mf).read(SC.port_memory(m))
    diff = gcanon.compare(up.s_out, nat, 'routine')
    plain = {'in': [], 'out': []}
    regs_n = GK.native_regs(b, m)
    for item in spec.get('out', []):
        nv, uv = item['native'], item['upstream']
        if nv == 'list':
            diff += compare_list(up_list(up, mf, 'out'), nat_list(b, m))
        elif nv == 'trace':
            diff += compare_trace(up_trace(case.after), nat_trace(b, m))
        elif item.get('as') == 'bool':
            got = regs_n['p'] & 1
            want = 1 if u(GK.up_source(up, uv, 'out')) else 0
            if got != want:
                diff.append('output %s: C %d, upstream %d' % (uv, got,
                                                               want))
        else:
            plain['out'].append(item)
    diff += GK.compare_outputs(up, mf, plain, b, m, nat)
    res['diff'] = diff[:12]
    res['ok'] = not diff and not stray
    return res


# ---------------------------------------------------------------------------
# The paths of each entry (MODEL on the case's inputs: upstream's branches)
# ---------------------------------------------------------------------------

PATHS = {
    PIT: ['short', 'long', 'not-crossed', 'crossed', 'axis', 'iv3',
          'behind', 'added', 'full'],
    'p_trace65.s:interceptVector3': ['dl-0', 'dx-0', 'dy-0', 'both',
                                     'prod-fast', 'prod-slow', 'test-0',
                                     'test-sign', 'fd-fast', 'fd-slow',
                                     'fd-noreturn'],
    'p_trace65.s:divlineSide': ['dx-0', 'dy-0', 'signs', 'products'],
    'p_trace65.s:addIntercept': ['line', 'thing', 'added', 'full'],
    'p_trace65.s:icInsert': ['from-last', 'from-head', 'at-end', 'inside',
                             'equal'],
    'p_trace65.s:ivSetup': ['both', 'dy-fails', 'dx-fails'],
    ITER: ['off-map', 'lines', 'all-stamped', 'stop'],
}


def _iv3_paths(trace, dl, ivon, ivm) -> List[str]:
    out = []
    x1, y1, dx, dy = dl
    if dx & M32 == 0 and dy & M32 == 0:
        return ['dl-0']
    out.append('dx-0' if dx & M32 == 0 else 'dy-0' if dy & M32 == 0
               else 'both')
    for axis in ((0,) if dx & M32 == 0 else (4,) if dy & M32 == 0
                 else (0, 4)):
        o = dl[3 if axis == 0 else 2] & M32
        fast = ivon and not o & M16 and ((o >> 16) + 4096) & M16 < 8192
        out.append('prod-fast' if fast else 'prod-slow')
    if dy & M32:
        a = side_prod(x1 - trace[0], dy)
        c = iv_prod_up(trace, dl, 0, ivon, ivm)
    else:
        a = c = 0
    if dx & M32:
        a = a + side_prod(trace[1] - y1, dx) & M32
        c = c - iv_prod_up(trace, dl, 4, ivon, ivm) & M32
    out += _test_paths(a, c)
    return sorted(set(out))


def _test_paths(num: int, den: int) -> List[str]:
    num &= M32
    den &= M32
    if num == 0 or den == 0:
        return ['test-0']
    if (num ^ den) & 0x80000000:
        return ['test-sign']
    if fixed_div(num, den) is None:
        return ['fd-noreturn']
    a, b = (-num & M32, -den & M32) if num & 0x80000000 else (num, den)
    return ['fd-fast' if b >> 16 < 0x4000 and a < b else 'fd-slow']


def _side_path(tr: Sequence[int], x: int, y: int) -> str:
    if tr[2] & M32 == 0:
        return 'dx-0'
    if tr[3] & M32 == 0:
        return 'dy-0'
    return 'signs' if s32(tr[3] ^ tr[2] ^ (x - tr[0]) ^ (y - tr[1])) < 0 \
        else 'products'


def _trace_of(mem) -> List[int]:
    t = mem.read(addr('_g_trace'), 16)
    return [u(t[i:i + 4]) for i in range(0, 16, 4)]


def _ivm_of(mem) -> List[int]:
    return [mem.u16(IV_ML + 2 * i) for i in range(4)]


def paths_of(case: GC.Case, key: str) -> List[str]:
    mem, regs = case.entry, case.regs_in
    tr = _trace_of(mem)
    ivon = 1 if mem.u16(IV_ON) else 0
    ivm = _ivm_of(mem)
    t = table()
    dp = regs['d'] + t.address('_Dp') - t.direct_page
    if key == 'p_trace65.s:interceptVector3':
        dl = [u(mem.read(addr('p_trace65.s:TC_X1') + 4 * i, 4))
              for i in range(4)]
        return _iv3_paths(tr, dl, ivon, ivm)
    if key == 'p_trace65.s:divlineSide':
        return [_side_path(tr, u(mem.read(addr('p_trace65.s:TC_X'), 4)),
                           u(mem.read(addr('p_trace65.s:TC_Y'), 4)))]
    if key == 'p_trace65.s:addIntercept':
        out = ['line' if regs['a'] & 0xFFFF else 'thing']
        n = (mem.u16(addr('intercept_p')) - (addr('intercepts') & 0xFFFF)
             ) // SIZEOF_IC
        out.append('full' if n >= MAXINTERCEPTS else 'added')
        return out
    if key == 'p_trace65.s:icInsert':
        y = regs['y'] & 0xFFFF
        base = addr('intercepts')
        frac = s32(u(mem.read(base + y, 4)))
        last = mem.u16(IC_LAST)
        out = []
        x = 640
        if last != 640 and frac >= s32(u(mem.read(base + last, 4))):
            out.append('from-last')
            x = last
        else:
            out.append('from-head')
        nxt = mem.u16(IC_NEXT + x)
        seen = 0
        while not nxt & 0x8000 and seen < 70:
            f = s32(u(mem.read(base + nxt, 4)))
            if f == frac:
                out.append('equal')
            if frac < f:
                break
            nxt = mem.u16(IC_NEXT + nxt)
            seen += 1
        out.append('at-end' if nxt & 0x8000 else 'inside')
        return sorted(set(out))
    if key == 'p_trace65.s:ivSetup':
        a, _ = iv_setup(tr, ivm)
        if a:
            return ['both']
        d = tr[3]
        ok_dy = not d & 0x07FF and ((d >> 16) + 0x0800) & M16 < 0x1000
        return ['dx-fails' if ok_dy else 'dy-fails']
    if key == PIT:
        out = ['long' if mem.u16(addr('TR_LONG')) else 'short']
        ln = GK._line(mem, u(mem.read(dp, 3)))
        if out[0] == 'long':
            s1 = divline_side(tr, ln['v1x'] << 16, ln['v1y'] << 16)
            s2 = divline_side(tr, ln['v1x'] + ln['dx'] << 16,
                              ln['v1y'] + ln['dy'] << 16)
        else:
            s1 = GK.side_model(tr[0], tr[1], ln)[0]
            s2 = GK.side_model(tr[0] + tr[2] & M32, tr[1] + tr[3] & M32,
                               ln)[0]
        if s1 == s2:
            return out + ['not-crossed']
        out.append('crossed')
        dl = [ln['v1x'] << 16 & M32, ln['v1y'] << 16 & M32,
              ln['dx'] << 16 & M32, ln['dy'] << 16 & M32]
        c, f = iv_axis(tr, dl, ivon)
        if c:
            out.append('axis')
        else:
            out.append('iv3')
            f = iv3(tr, dl, ivon, ivm)
        if f is not None and s32(f) < 0:
            return out + ['behind']
        n = (mem.u16(addr('intercept_p')) - (addr('intercepts') & 0xFFFF)
             ) // SIZEOF_IC
        return out + ['full' if n >= MAXINTERCEPTS else 'added']
    if key == ITER:
        x, y = s16(regs['a']), s16(mem.u16(dp))
        w, h = mem.u16(addr('_g_bmapwidth')), mem.u16(addr('_g_bmapheight'))
        if not (0 <= x < w and 0 <= y < h):
            return ['off-map']
        out = []
        if case.regs_out['a'] & 0xFFFF == 0:
            out.append('stop')
        sv = GC.survey_of(case.header['run']) or {}
        r = sv.get('routines', {}).get(ITER, {})
        reached = [sv['targets'][i] for i in
                   r.get('reached', {}).get(str(case.header['hit']), [])]
        out.append('lines' if PIT in reached else 'all-stamped')
        return out
    return []


# ---------------------------------------------------------------------------
# The checkpoint's runs (--run)
# ---------------------------------------------------------------------------

def _strip(r: Dict[str, Any]) -> Dict[str, Any]:
    r.pop('_m', None)
    return r


def case_for(path: Path, key: str) -> GC.Case:
    c = load_case(path)
    c.header['routine'] = key           # (PIT_AddLineIntercepts: callLN's)
    return c


def classify_result(r: Dict[str, Any]) -> str:
    if r.get('ok'):
        return 'equal'
    if (r.get('error') or '').startswith('bridge:'):
        return 'undecodable'
    return 'failed'


def failed(r: Dict[str, Any]) -> bool:
    return r.get('class', 'failed' if not r.get('ok') else 'equal') == \
        'failed'


def _run_job(job) -> List[Dict[str, Any]]:
    path, key, obj, combos = job
    b = G.load_build(Path(obj), IMAGE)
    spec = spec_of(key)
    case = case_for(Path(path), key)
    try:
        paths = paths_of(case, key)
    except Exception as error:
        paths = ['? %s' % error]
    out = []
    for fill, prof in combos:
        try:
            r = _strip(run_native(case, spec, b, fill, prof))
        except Exception as error:
            r = {'case': Path(path).name, 'routine': key, 'ok': False,
                 'fill': '%02x' % fill, 'profile': prof,
                 'error': '%s: %s' % (type(error).__name__, error)}
        r['paths'] = paths
        r['synthetic'] = bool(case.header.get('synthetic'))
        r['run'] = case.header['run']
        r['class'] = classify_result(r)
        out.append(r)
    return out


def chosen_paths(key: str, sel: Dict[str, Any]) -> List[Path]:
    e = sel['entries'].get(key, {'chosen': {}})
    out = []
    for run, calls in e['chosen'].items():
        for hit, _ in calls:
            p = case_file(run, key, hit)
            if p.exists():
                out.append(p)
    return out


def check_cases(entries: Sequence[str] = (), obj: Path = OUT,
                jobs: int = JOBS, limit: Optional[int] = None,
                sample: int = 1, combos=COMBOS, say=print
                ) -> Dict[str, List[Dict[str, Any]]]:
    """Every chosen case of the entries and of the block steps, and every
    synthetic case, on the image in obj: {key: results}."""
    sel = load_select()
    work = []
    for key in ENTRIES + [ITER]:
        if entries and key not in entries:
            continue
        paths = chosen_paths(key, sel)[::sample] + synth_paths(key)
        if limit:
            paths = paths[:limit]
        work += [(str(p), key, str(obj), combos) for p in paths]
    out: Dict[str, List[Dict[str, Any]]] = {}
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for got in pool.map(_run_job, work, chunksize=2):
            for r in got:
                out.setdefault(r['routine'], []).append(r)
    for key, res in out.items():
        bad = [r for r in res if failed(r)]
        classes: Dict[str, int] = {}
        for r in res:
            classes[r['class']] = classes.get(r['class'], 0) + 1
        say('%s: %d runs, %d failed %s' % (key, len(res), len(bad),
                                           classes), flush=True)
        for r in bad[:3]:
            say('  %s' % json.dumps(r)[:600], flush=True)
    return out


# ---------------------------------------------------------------------------
# Synthetic cases (--synth): a captured case's entry state with pokes, the
# call run alone on ref816 (--call): upstream's own result
# ---------------------------------------------------------------------------

def call_synth(case: GC.Case, key: str, pokes: Sequence[Tuple[int, bytes]],
               note: str) -> GC.Case:
    entry = case.entry.copy()
    entry.header = case.entry.header
    for a, d in pokes:
        entry.write(a, d)
    work = tmpdir('call')
    try:
        (work / 'entry.img').write_bytes(entry.image_bytes())
        cmd = [str(title.MACHINE), str(work / 'entry.img'), '--call',
               '%06X' % addr(key), '--call-writes', str(work / 'writes.img'),
               '--call-reads', str(work / 'reads.img'),
               '--state', str(work / 'state.json')]
        r = bounded.run(cmd, timeout=120, max_bytes=GC.MAX_FILE,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r.returncode:
            raise CheckError('ref816 --call failed: %s' % r.stdout[-800:])
        state = json.loads((work / 'state.json').read_text())
        if not state['call']['returned']:
            raise CheckError('the call did not return')
        writes = GC.image_records(work / 'writes.img')
        reads = GC.image_records(work / 'reads.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    after = entry.copy()
    for a, d in writes:
        after.write(a, d)
    header = dict(case.header, routine=key, note=note, call=state['call'],
                  writes=GC._ranges(writes), reads=GC._ranges(reads),
                  synthetic=True,
                  pokes=[[a, len(d)] for a, d in pokes])
    return GC.Case(header, entry, after, None)


def save_case(case: GC.Case, path: Path) -> None:
    """A synthetic case as a case file against the part's base of its
    run."""
    with own_cases():
        base = GC.load_base(case.header['run'])
    pages = GC.reader_pages(case.entry) | GC.reader_pages(case.after)
    for key in ('writes', 'reads', 'pokes'):
        for a, n in case.header.get(key, []):
            pages |= set(range(a >> 8, (a + n + 0xFF) >> 8))
    for reg in ('d', 's'):
        v = case.header['call']['start'][reg]
        pages |= {v >> 8, (v + 0xFF) >> 8 & 0xFF}
    pages = sorted(pages)
    payload = bytearray()
    for p in pages:
        a = p << 8
        payload += bytes(x ^ y for x, y in zip(case.entry.read(a, GC.PAGE),
                                               base.read(a, GC.PAGE)))
    wbytes = bytearray()
    for a, n in case.header['writes']:
        wbytes += case.after.read(a, n)
    header = dict(case.header, format=GC.CASE_FORMAT,
                  pages=GC._compress_pages(pages),
                  image_header=case.entry.header.hex())
    head = json.dumps(header, separators=(',', ':')).encode() + b'\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(zlib.compress(head + bytes(payload) + bytes(wbytes), 6))


def _chain(mem) -> List[int]:
    """upstream's chain from its head: the intercepts' offsets."""
    out = []
    v = mem.u16(IC_NEXT + SIZEOF_IC * MAXINTERCEPTS)
    while not v & 0x8000 and len(out) < 70:
        out.append(v)
        v = mem.u16(IC_NEXT + v)
    return out


def _count(mem) -> int:
    return (mem.u16(addr('intercept_p')) - (addr('intercepts') & 0xFFFF)
            ) // SIZEOF_IC


def synth_specs() -> List[Tuple[str, GC.Case, List[Tuple[int, bytes]],
                                str]]:
    """(key, base case, pokes, note) of every synthetic case: two
    intercepts of equal frac (GAME.md 2.4: the list's order) through
    addIntercept and icInsert (equal to the last one in: the search from
    IC_LAST; to the chain's first: from the head; to two equal ones), and
    the full list (64 intercepts: addIntercept's and lineCross's "full",
    which no run reaches)."""
    sel = load_select()
    out = []
    base = addr('intercepts')
    tc_t = addr('p_trace65.s:TC_T')
    key = 'p_trace65.s:addIntercept'
    want = {'last': None, 'first': None, 'two': None, 'full': None}
    for p in chosen_paths(key, sel):
        c = load_case(p)
        ch = _chain(c.entry)
        last = c.entry.u16(IC_LAST)
        if want['last'] is None and ch and last != 640:
            f = c.entry.read(base + last, 4)
            want['last'] = (c, [(tc_t, f)], 'a frac equal to IC_LAST\'s')
        if want['first'] is None and len(ch) >= 2 and last != ch[0] \
                and last != 640:
            f = c.entry.read(base + ch[0], 4)
            want['first'] = (c, [(tc_t, f)],
                             'a frac equal to the chain\'s first (below '
                             'IC_LAST\'s: the search from the head)')
        if want['two'] is None and len(ch) >= 3:
            f = c.entry.read(base + ch[1], 4)
            want['two'] = (c, [(base + ch[0], f), (tc_t, f)],
                           'a frac equal to two chained ones')
        if want['full'] is None and _count(c.entry) >= 1:
            n = _count(c.entry)
            ent = c.entry.read(base, SIZEOF_IC)
            pokes = [(base + SIZEOF_IC * i, ent)
                     for i in range(n, MAXINTERCEPTS)]
            pokes += [(IC_NEXT + SIZEOF_IC * i, b'\xff\xff')
                      for i in range(n, MAXINTERCEPTS)]
            pokes.append((addr('intercept_p'),
                          le((base & 0xFFFF) + SIZEOF_IC * MAXINTERCEPTS,
                             2)))
            want['full'] = (c, pokes, 'the list full (64)')
    for name, v in want.items():
        if v is None:
            raise CheckError('no addIntercept case for the synthetic %s'
                             % name)
        out.append((key, v[0], v[1], v[2]))
    # icInsert: the new one's frac equal to IC_LAST's and to the first's
    key = 'p_trace65.s:icInsert'
    got = 0
    for p in chosen_paths(key, sel):
        c = load_case(p)
        y = c.regs_in['y'] & 0xFFFF
        ch = _chain(c.entry)
        last = c.entry.u16(IC_LAST)
        if got == 0 and last != 640 and last != y:
            out.append((key, c, [(base + y, c.entry.read(base + last, 4))],
                        'the new frac equal to IC_LAST\'s'))
            got = 1
        elif got == 1 and len(ch) >= 2 and ch[0] != y:
            out.append((key, c, [(base + y, c.entry.read(base + ch[0], 4))],
                        'the new frac equal to the chain\'s first'))
            got = 2
            break
    if got < 2:
        raise CheckError('no icInsert cases for the synthetic ones')
    # PIT_AddLineIntercepts with the list full: a crossed line in front
    key = PIT
    for p in chosen_paths(key, sel):
        c = case_for(p, key)
        if 'added' not in paths_of(c, key) or _count(c.entry) < 1:
            continue
        n = _count(c.entry)
        ent = c.entry.read(base, SIZEOF_IC)
        pokes = [(base + SIZEOF_IC * i, ent) for i in range(n,
                                                             MAXINTERCEPTS)]
        pokes += [(IC_NEXT + SIZEOF_IC * i, b'\xff\xff')
                  for i in range(n, MAXINTERCEPTS)]
        pokes.append((addr('intercept_p'),
                      le((base & 0xFFFF) + SIZEOF_IC * MAXINTERCEPTS, 2)))
        out.append((key, c, pokes, 'a crossed line with the list full'))
        break
    # PIT_AddLineIntercepts on paths no run takes (its shots and long
    # traces go through tracet's traceLines): a long trace (TR_LONG 1: the
    # vertices' sides by divlineSide), crossed and not; a shot (IV_ON and
    # ivSetup's M of the trace rounded to 2048 units' steps: ivAxis decides)
    long_n = {'crossed': 0, 'not-crossed': 0}
    shot_n = 0
    for p in chosen_paths(key, sel):
        c = case_for(p, key)
        ps = paths_of(c, key)
        k = 'crossed' if 'crossed' in ps else 'not-crossed'
        if long_n[k] < 3:
            out.append((key, c, [(addr('TR_LONG'), b'\x01\x00')],
                        'a long trace (TR_LONG 1), %s' % k))
            long_n[k] += 1
        if k == 'crossed' and shot_n < 4:
            tr = _trace_of(c.entry)
            new_tr = list(tr[:2]) + [s32(v) // 0x800 * 0x800 & M32
                                     for v in tr[2:]]
            on, ivm = iv_setup(new_tr, [0, 0, 0, 0])
            dp = c.regs_in['d'] + table().address('_Dp') - \
                table().direct_page
            ln = GK._line(c.entry, u(c.entry.read(dp, 3)))
            dl = [ln['v1x'] << 16 & M32, ln['v1y'] << 16 & M32,
                  ln['dx'] << 16 & M32, ln['dy'] << 16 & M32]
            if on and iv_axis(new_tr, dl, 1)[0]:
                out.append((key, c, [
                    (addr('_g_trace') + 8, w32s(new_tr[2:])),
                    (IV_ON, b'\x01\x00'),
                    (IV_ML, b''.join(le(v, 2) for v in ivm))],
                    'a shot (IV_ON): ivAxis decides'))
                shot_n += 1
    # the block steps: off the map, and stopped by a full list
    key = ITER
    got = set()
    for p in chosen_paths(key, sel):
        c = load_case(p)
        ps = paths_of(c, key)
        dp = c.regs_in['d'] + table().address('_Dp') - table().direct_page
        if 'off' not in got:
            h = c.entry.u16(addr('_g_bmapheight'))
            out.append((key, c, [(dp, le(h, 2))], 'block y off the map '
                        '(the map\'s height)'))
            out.append((key, c, [(dp, le(-1, 2))], 'block y -1'))
            got.add('off')
        if 'stop' not in got and 'lines' in ps and _count(c.entry) >= 1 \
                and _count(c.after) > _count(c.entry):
            n = _count(c.entry)
            ent = c.entry.read(base, SIZEOF_IC)
            pokes = [(base + SIZEOF_IC * i, ent)
                     for i in range(n, MAXINTERCEPTS)]
            pokes += [(IC_NEXT + SIZEOF_IC * i, b'\xff\xff')
                      for i in range(n, MAXINTERCEPTS)]
            pokes.append((addr('intercept_p'),
                          le((base & 0xFFFF) + SIZEOF_IC * MAXINTERCEPTS,
                             2)))
            out.append((key, c, pokes, 'the list full: the callback '
                        'stops the walk'))
            got.add('stop')
        if got == {'off', 'stop'}:
            break
    return out


def make_synth(say=print) -> int:
    n = 0
    if SYNTH.exists():
        shutil.rmtree(str(SYNTH))
    for i, (key, c, pokes, note) in enumerate(synth_specs()):
        s = call_synth(c, key, pokes, note)
        p = SYNTH / native_name(key) / ('s%03d.case.z' % i)
        save_case(s, p)
        say('%s: %s (%s)' % (key, p.name, note), flush=True)
        n += 1
    return n


# ---------------------------------------------------------------------------
# Every captured input (--logs): every call of interceptVector3 and
# divlineSide in the survey's runs, from ref816's call log (inputs at the
# entry, the result at the return), run natively
# ---------------------------------------------------------------------------

LOG_KINDS = {
    'interceptVector3': ('p_trace65.s:interceptVector3',
                         '_g_trace:16+p_trace65.s:TC_X1:16+%06X:2+%06X:8' %
                         (IV_ON, IV_ML)),
    'divlineSide': ('p_trace65.s:divlineSide',
                    '_g_trace:16+p_trace65.s:TC_X:8'),
}
LOG_RUNS = ('demo3', 'demo1', 'demo2', 'newgame')
LOG_LIMIT = 256 << 20


def _parse_up(kind: str, rec: bytes) -> Dict[str, Any]:
    w = [u(rec[i:i + 4]) for i in range(0, len(rec) - 10 if kind ==
                                        'interceptVector3' else len(rec), 4)]
    if kind == 'interceptVector3':
        return {'trace': w[0:4], 'dl': w[4:8], 'ivon': 1 if u(rec[32:34])
                else 0, 'ivm': [u(rec[34 + 2 * i:36 + 2 * i])
                                for i in range(4)]}
    return {'trace': w[0:4], 'x': w[4], 'y': w[5]}


def log_run(run: str, say=print) -> Dict[str, Any]:
    """The run's calls of LOG_KINDS (ref816's call log through gamecap's
    machine, in a temporary directory): logs/RUN.json.z, each call's
    input record (mathref's spec order) and upstream's result."""
    check_disk()
    t = table()
    work = tmpdir('log')
    try:
        log = work / 'calls.log'
        opts = ['--call-log-file', str(log), '--call-log-limit',
                str(LOG_LIMIT)]
        for kind, (key, mem) in LOG_KINDS.items():
            opts += ['--call-log', CL.resolve('%s,name=%s,in=%s' % (
                key, kind, mem), t)]
        r = GC.machine(run, work, opts)
        if r['problems']:
            raise CheckError('%s: %s' % (run, '; '.join(r['problems'])))
        out: Dict[str, List[List[Any]]] = {k: [] for k in LOG_KINDS}
        for c in CL.calls(log):
            ro = c.registers_out
            if ro is None or not c.line.get('returned'):
                continue
            res = (ro['a'] & 0xFFFF) | (ro['x'] & 0xFFFF) << 16 if \
                c.name == 'interceptVector3' else ro['a'] & 0xFFFF
            out[c.name].append([b''.join(c.memory_in).hex(), res])
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    (LOGS / ('%s.json.z' % run)).write_bytes(zlib.compress(json.dumps(
        {'format': 'tracel-log 1', 'run': run, 'calls': out}).encode(), 6))
    say('%s: %s' % (run, ', '.join('%s %d calls' % (k, len(v))
                                   for k, v in out.items())), flush=True)
    return out


def load_log(run: str) -> Dict[str, List[List[Any]]]:
    p = LOGS / ('%s.json.z' % run)
    if not p.exists():
        raise CheckError('no %s (tracel.py --logs)' % p)
    return json.loads(zlib.decompress(p.read_bytes()))['calls']


def check_logs(obj: Path = OUT, jobs: int = JOBS, say=print
               ) -> Dict[str, Any]:
    """Every logged call run natively (and MODEL): its result equal."""
    out: Dict[str, Any] = {'format': 'tracel-logs 1', 'kinds': {}}
    for i, kind in enumerate(LOG_KINDS):
        xs, ups, runs = [], [], {}
        for run in LOG_RUNS:
            calls = load_log(run)[kind]
            runs[run] = len(calls)
            for rec, res in calls:
                xs.append(_parse_up(kind, bytes.fromhex(rec)))
                ups.append(res)
        nats = native_results(kind, xs, obj, jobs, FILLS[i % 2])
        bad = [j for j, (n, up) in enumerate(zip(nats, ups))
               if n[0] != up or n[1]]
        mbad = [j for j, (d, up) in enumerate(zip(xs, ups))
                if model_out(kind, d) != up]
        paths: Dict[str, int] = {}
        for d in xs:
            for p in (_iv3_paths(d['trace'], d['dl'], d['ivon'], d['ivm'])
                      if kind == 'interceptVector3' else
                      [_side_path(d['trace'], d['x'], d['y'])]):
                paths[p] = paths.get(p, 0) + 1
        out['kinds'][kind] = {
            'calls': len(xs), 'runs': runs, 'failed': len(bad),
            'model_differs': len(mbad), 'paths': paths,
            'first': [{'input': {k: _fmt(v) if not isinstance(v, list) else
                                 [_fmt(x) for x in v]
                                 for k, v in xs[j].items()},
                       'upstream': _fmt(ups[j]), 'native': _fmt(nats[j][0])}
                      for j in bad[:5]]}
        say('%s: every logged call, %d, %d failed, model %d different' % (
            kind, len(xs), len(bad), len(mbad)), flush=True)
    out['failures'] = sum(k['failed'] + k['model_differs']
                          for k in out['kinds'].values())
    return out


# ---------------------------------------------------------------------------
# The report (report.json)
# ---------------------------------------------------------------------------

BUDGET = {'up': 2136, 'native': 2800}
GAME_MODULES = ('tracel',)


def load_build(obj: Path = OUT):
    return G.load_build(obj, IMAGE)


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    b = load_build(obj)
    ms = G.module_sizes(b)
    game = sum(ms.get(m, 0) for m in GAME_MODULES)
    return {'modules': {m: ms.get(m, 0) for m in GAME_MODULES + ('tracelt',)},
            'native_bytes': game, 'budget': BUDGET['native'],
            'upstream_bytes': BUDGET['up'],
            'over_budget_pct': round(100.0 * (game - BUDGET['native']) /
                                     BUDGET['native'], 1),
            'test_driver_bytes': G.module_bytes(b, 'tracelt'),
            'routines': routine_sizes(b)}


def routine_sizes(b) -> Dict[str, int]:
    """Each routine's bytes: the module's bytes in each segment, split
    among the routines placed there by their addresses."""
    text = (b.obj / (b.name + '.map')).read_text()
    text = text.split('Modules list:', 1)[-1].split('Segment list:', 1)[0]
    module, segs = None, []
    for line in text.splitlines():
        if line and not line.startswith(' ') and line.endswith('.o:'):
            module = Path(line[:-1]).stem
            continue
        f = line.split()
        if module in GAME_MODULES and f and (f[0] == 'GCORE' or
                                              f[0].startswith('GGRP')):
            start = next(int(x[5:], 16) for x in f if x.startswith('Offs='))
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            segs.append((f[0], b.segments[f[0]][0] + start, size))
    names = [native_name(k) for k in ENTRIES + HELPERS]
    out = {}
    for seg, lo, size in segs:
        here = sorted((b.labels[n], n) for n in names if n in b.labels and
                      GK.seg_of(b, n) == seg and lo <= b.labels[n] <
                      lo + size)
        for i, (a, n) in enumerate(here):
            out[n] = (here[i + 1][0] if i + 1 < len(here) else lo + size) - a
    return out


def _stats(xs: Sequence[Optional[float]]) -> Optional[Dict[str, float]]:
    ys = sorted(x for x in xs if x is not None)
    if not ys:
        return None
    return {'median': ys[len(ys) // 2], 'worst': ys[-1], 'n': len(ys)}


def summarise(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    from a2vm import costs
    mhz = {p: costs.parameters(p)['fabric_mhz'] for p in PROFILES}
    classes: Dict[str, int] = {}
    for r in results:
        classes[r.get('class', '?')] = classes.get(r.get('class', '?'), 0) \
            + 1
    out: Dict[str, Any] = {
        'runs': len(results),
        'cases': len({(r.get('case'), r.get('run')) for r in results}),
        'synthetic_cases': len({r.get('case') for r in results
                                if r.get('synthetic')}),
        'failures': sum(1 for r in results if failed(r)),
        'classes': classes,
        'stray_writes': sum(r.get('stray_n', 0) for r in results),
        'lowest_s': min((r['lowest_s'] for r in results
                         if r.get('lowest_s') is not None), default=None),
        'cycles': {p: _stats([r.get('cycles') for r in results
                              if r.get('profile') == p]) for p in PROFILES},
        'us': {p: _stats([round(r['clocks'] / mhz[p], 2) for r in results
                          if r.get('profile') == p and r.get('clocks')])
               for p in PROFILES}}
    paths: Dict[str, int] = {}
    for r in results:
        if r.get('profile') == PROFILES[0] and r.get('fill') == '%02x' % \
                FILLS[0]:
            for p in r.get('paths', []):
                paths[p] = paths.get(p, 0) + 1
    out['paths'] = paths
    out['first_failures'] = [{k: v for k, v in r.items() if k != 'paths'}
                             for r in results if failed(r)][:5]
    return out


def report(run_res: Dict[str, List[Dict[str, Any]]],
           logs_res: Optional[Dict[str, Any]],
           rand_res: Optional[Dict[str, Any]], obj: Path = OUT
           ) -> Dict[str, Any]:
    sel = load_select()
    rep: Dict[str, Any] = {'format': 'game-part-report 1', 'part': PART,
                           'wave': 2, 'entries': {}, 'sizes': sizes(obj),
                           'fills': ['%02X' % f for f in FILLS],
                           'profiles': list(PROFILES),
                           'exclusions': [n for n, _, _ in
                                          gcanon.ROUTINE_EXCLUSIONS]}
    for key in ENTRIES + [ITER]:
        e = sel['entries'].get(key, {})
        s = summarise(run_res.get(key, []))
        s['survey_calls'] = e.get('calls', 0)
        s['eligible'] = e.get('eligible', 0)
        s['chosen'] = sum(len(c) for c in e.get('chosen', {}).values())
        s['paths_declared'] = PATHS.get(key, [])
        s['paths_not_taken'] = [p for p in PATHS.get(key, [])
                                if p not in s['paths']]
        if key == ITER:
            s['about'] = ('P_BlockLinesIterator (part geom) with the '
                          'callback PIT_AddLineIntercepts: the block steps '
                          'of P_PathTraverse')
        rep['entries'][key] = s
    if logs_res is not None:
        rep['every_captured_input'] = logs_res
    if rand_res is not None:
        rep['random'] = rand_res
    rep['failures'] = sum(v['failures'] for v in rep['entries'].values()) \
        + (logs_res or {}).get('failures', 0) + \
        (rand_res or {}).get('failures', 0)
    rep['stray_writes'] = sum(v['stray_writes']
                              for v in rep['entries'].values())
    rep['lowest_s'] = min((v['lowest_s'] for v in rep['entries'].values()
                           if v['lowest_s'] is not None), default=None)
    return rep


# ---------------------------------------------------------------------------
# What the checkpoint needs
# ---------------------------------------------------------------------------

def need() -> Optional[str]:
    """What build/ lacks for the checkpoint (None: all there)."""
    for p, cmd in (
            (GL.SHARED / 'gen' / 'ggame.inc',
             'make -s -C src/native -f game.mk shared ROOT=$PWD'),
            (GL.SHARED / 'native-game-1.json',
             'make -s -C src/native -f game.mk shared ROOT=$PWD'),
            (GL.SHARED / 'survey.json',
             'python3 tools/native/gamecap.py --survey'),
            (G.A2VM, 'make -C tools/a2vm'),
            (title.MACHINE, 'make -C tools/ref816'),
            (MATHREF, 'make -C tools/native')):
        if not Path(p).exists():
            return '%s is missing (%s)' % (p, cmd)
    if not GR.have_bases():
        return 'the level bases are missing (python3 tools/native/' \
            'level_check.py --setup)'
    return None


def save(name: str, data: Any) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    p.write_text(json.dumps(data, indent=1) + '\n')
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ('select', 'paths', 'capture', 'synth', 'run', 'logs',
                 'rand', 'report', 'all'):
        parser.add_argument('--' + flag, action='store_true')
    parser.add_argument('--entries', default='')
    parser.add_argument('--kinds', default='')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--sample', type=int, default=1)
    parser.add_argument('--n', type=int)
    parser.add_argument('--jobs', type=int, default=JOBS)
    parser.add_argument('--obj', type=Path, default=OUT)
    a = parser.parse_args(argv)
    import tracel as M          # (the workers import the module by name)
    missing = need()
    if missing:
        print('tracel: %s' % missing)
        return 2
    entries = [e if ':' in e else 'p_trace65.s:' + e
               for e in a.entries.split(',') if e]
    bad = 0
    if a.select or a.all:
        p = save('select.json', M.select())
        print('the selection: %s' % p)
    if a.paths or a.all:
        M.extend_selection()
    if a.capture or a.all:
        M.capture(entries, a.jobs)
    if a.synth or a.all:
        M.make_synth()
    if a.run or a.all:
        res = M.check_cases(entries, a.obj, a.jobs, a.limit, a.sample)
        save('run.json', res)
        bad += sum(1 for rs in res.values() for r in rs if failed(r))
    if a.logs or a.all:
        for run in LOG_RUNS:
            if not (LOGS / ('%s.json.z' % run)).exists():
                M.log_run(run)
        lr = M.check_logs(a.obj, a.jobs)
        save('logs.json', lr)
        bad += lr['failures']
    if a.rand or a.all:
        rr = M.rand_all(a.obj, a.n, a.jobs,
                        [k for k in a.kinds.split(',') if k])
        save('rand.json', rr)
        bad += rr['failures']
    if a.report or a.all:
        def load(name):
            p = OUT / name
            return json.loads(p.read_text()) if p.exists() else None
        rep = M.report(load('run.json') or {}, load('logs.json'),
                       load('rand.json'), a.obj)
        p = save('report.json', rep)
        print('the report: %s (%d failures)' % (p, rep['failures']))
        bad += rep['failures']
    return 1 if bad else 0



# ---------------------------------------------------------------------------
# The paths no chosen call takes (--paths): PIT_AddLineIntercepts' calls
# by path from a call log of it (JML-entered: jumps=1) and its callees,
# in the runs where its calls are callLN's; the first PATH_EXTRA calls of
# each path the chosen ones miss join the selection (role "path")
# ---------------------------------------------------------------------------

PATH_EXTRA = 4


def pit_call_paths(run: str) -> Dict[int, List[str]]:
    """PIT_AddLineIntercepts' hit -> its paths, from the children each call
    logged: divlineSide (a long trace), ivAxis with C set (axis),
    interceptVector3 or ivAxis (crossed), addIntercept (added; C clear:
    full; crossed without it: behind)."""
    check_disk()
    t = table()
    work = tmpdir('paths')
    try:
        log = work / 'calls.log'
        opts = ['--call-log-file', str(log), '--call-log-limit',
                str(LOG_LIMIT)]
        for spec in ('PIT_AddLineIntercepts,name=pit,jumps=1',
                     'p_trace65.s:divlineSide,name=side',
                     'p_trace65.s:ivAxis,name=axis',
                     'p_trace65.s:interceptVector3,name=iv3',
                     'p_trace65.s:addIntercept,name=add'):
            opts += ['--call-log', CL.resolve(spec, t)]
        r = GC.machine(run, work, opts)
        if r['problems']:
            raise CheckError('%s: %s' % (run, '; '.join(r['problems'])))
        head, lines, _ = CL.read(log)
        names = [x['name'] for x in head['routines']]
        hit_of: Dict[int, int] = {}
        kids: Dict[int, List[Tuple[str, Dict]]] = {}
        for ln in lines:
            n = names[ln['routine']]
            if n == 'pit':
                hit_of[ln['call']] = ln['hit']
            else:
                kids.setdefault(ln['parent'], []).append((n, ln))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    out: Dict[int, List[str]] = {}
    for call, hit in hit_of.items():
        ks = kids.get(call, [])
        names_ = [n for n, _ in ks]
        p = ['long' if 'side' in names_ else 'short']
        crossed = 'axis' in names_ or 'iv3' in names_
        p.append('crossed' if crossed else 'not-crossed')
        for n, ln in ks:
            if n == 'axis' and ln['out'] and ln['out']['p'] & 1:
                p.append('axis')
        if crossed and 'axis' not in p:
            p.append('iv3')
        adds = [ln for n, ln in ks if n == 'add']
        if crossed and not adds:
            p.append('behind')
        for ln in adds:
            p.append('added' if ln['out'] and ln['out']['p'] & 1 else
                     'full')
        out[hit] = p
    return out


def extend_selection(say=print) -> Dict[str, Any]:
    """The calls of each PIT_AddLineIntercepts path the chosen ones miss
    (the first PATH_EXTRA of each run), added to select.json."""
    sel = load_select()
    e = sel['entries'][PIT]
    chosen = {(run, h) for run, cs in e['chosen'].items() for h, _ in cs}
    by_run = {run: pit_call_paths(run) for run in pit_runs()
              if GC.survey_of(run) and
              GC.survey_of(run)['routines'].get(PIT, {}).get('calls')}
    taken = set()
    for run, paths in by_run.items():
        for h, ps in paths.items():
            if (run, h) in chosen:
                taken |= set(ps)
    extra = []
    counts: Dict[str, int] = {}
    for run, paths in by_run.items():
        for p in PATHS[PIT]:
            if p in taken:
                continue
            hs = [h for h in sorted(paths) if p in paths[h]][:PATH_EXTRA]
            counts[p] = counts.get(p, 0) + len([h for h in sorted(paths)
                                                if p in paths[h]])
            extra += [(run, h) for h in hs if (run, h) not in chosen]
    sv = {run: GC.survey_of(run) for run in by_run}
    for run, h in sorted(set(extra)):
        e['chosen'].setdefault(run, []).append(
            [h, sv[run]['routines'][PIT]['tic'][h - 1]])
    e['path_calls'] = {'taken_by_chosen': sorted(taken),
                       'calls_of_missing_paths': counts,
                       'added': len(set(extra))}
    save('select.json', sel)
    say('PIT_AddLineIntercepts: paths of the chosen calls %s; added %d '
        'calls for %s' % (sorted(taken), len(set(extra)), counts),
        flush=True)
    return e['path_calls']


if __name__ == '__main__':
    sys.exit(main())
