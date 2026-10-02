#!/usr/bin/env python3
"""Part path's checkpoint (milestone 10, docs/GAME.md 0.3 fact 4, 1.9, 2.2
TRVTAB, 2.4 row path, 3.5, 5.2 acceptance 6): P_PathTraverse on a sample of
its captured calls, with the recording traverser and with traversers that
stop at the k-th intercept, on both sides; acceptance 6 (long dense traces
of more than 64 intercepts); a1Shr7's random check; the planted bugs and
report.json.

Usage:  python3 tools/native/gparts/path.py --select
        python3 tools/native/gparts/path.py --capture
        python3 tools/native/gparts/path.py --variants
        python3 tools/native/gparts/path.py --acceptance [--traces N]
        python3 tools/native/gparts/path.py --run [--limit N] [--obj DIR]
        python3 tools/native/gparts/path.py --random [--count N]
        python3 tools/native/gparts/path.py --plants
        python3 tools/native/gparts/path.py --report
        python3 tools/native/gparts/path.py --all

The lean checkpoint (the owner's request of 2026-10-02): at most SAMPLE
(40) calls of P_PathTraverse, chosen to reach the walk's paths (the tics
of ptStuck's and traceLines' calls, the calls whose traverser no wave has
built, each traverser's kind, the rest spread over the runs), from one
poisoned machine ($A5) under f121.

Every captured call reaches a traverser (TRVTAB: parts attack, xymove,
player, waves 5), so none runs as captured unless the traverser it names
is never called ("plain": every intercept beyond the call's reach). Each
chosen call runs as a variant instead: the reference's P_PathTraverse
again on the captured state (ref816 --call) with a recording traverser
(65816, poked into bank $7C) in place of its own, which logs each
intercept it is given and answers stop at its k-th call (0: never); the
native image runs the same call with TRVTAB's harness entry (the
recording traverser of grec.s, through pttest.s's pt_rec_trv: request R2)
stopping at the same k. Stops: 0, then 1, the middle and the last of the
intercepts the never-stopping run delivered.

Compared: the canonical state (gcanon's routine mode, R1-R7 only: the
lines' validcount stamps and validcount among it), the return value (A and
C), the intercepts delivered (frac, and the line or the mobj: in order),
the intercepts left (tracel's form "list": their count, each one's frac
and what, the chain from its head, IC_LAST), the trace's state (tracel's
"trace") and SIDE1's constants (tracet's "sides"), no stray write (a2vm's
write log); the lowest S and the time.

The paths: ref816 --mark at the points of upstream's p_path65.s (POINTS:
source lines, their addresses from our assembler's spans, tools/v816), on
every reference run; report.json lists the points no sampled call reaches.

Acceptance 6 (--acceptance): one state a map (the tour's P_PlayerThink
calls, captured whole: E1M1-E1M9); long traces from things' places, a
host model's count (the lines the segment crosses, the things whose
diagonal it crosses) filtering the candidates, the reference's own run
(never stopping) choosing them: kept when it returns false, more than 64
intercepts (E1's lines give few such traces: docs/game-parts/path.md R6),
and one a map whose walk takes ptStuck's copy; each with the recording
traverser and with stops at k = 1, 8, 32, 64, 65, on both sides.

Captures keep the whole machine (capture_whole): a variant walks blocks
the captured call never reached, and reads pages a gamecap case holds
only from its run's base, another moment's machine.

Everything it writes is under build/native/game/path/ (cases/RUN/NAME/:
gamecap.py's format against a base of its own a run; cases/var/ and
cases/acc6/: the reference's variants), select.json, run.json,
random.json, plants.json, report.json; temporary files in
build/tmp-path-* directories, deleted after each step.
"""

import argparse
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
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
from ref816 import bounded, title  # noqa: E402
import geom_check as GK  # noqa: E402
import tracel as TLM  # noqa: E402
import tracet as TTM  # noqa: E402

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'path'
OUT = GL.GAME / PART
CASES = OUT / 'cases'
VAR = CASES / 'var'
ACC = CASES / 'acc6'
ARGS = SRC / 'game' / PART / 'args.json'
IMAGE = 'ptest'
FILL = 0xA5
PROFILE = 'f121'
JOBS = 2
MIN_FREE = 20 * 10 ** 9
SAMPLE = 40
CAPTURE_BATCH = 250
UPSTREAM_DP = 0x900
REF_CYCLES = 200_000_000         # a reference call's bound
M16, M32 = 0xFFFF, 0xFFFFFFFF

ENTRY = 'p_path65.s:P_PathTraverse'
PLAYER = 'p_user65.s:P_PlayerThink'     # acceptance 6's states (the tour)
ROUTINES = [k for p in GL.PARTS if p['name'] == PART for k in p['routines']]
HELPERS = [k for p in GL.PARTS if p['name'] == PART for k in p['helpers']]
# no native code of its own: upstream's jml [PT_JMP] is traverseTo's DCALL
# (request R3)
NO_CODE = ('p_path65.s:callTrav',)
TRV = GL.DISPATCH['TRVTAB']['targets']
TRV_HARNESS = len(TRV) + 1
UC = GK.UC
PT_ADDLINES, PT_ADDTHINGS = 1, 2

# the reference's recording traverser (65816, poked into bank $7C: zero in
# every run's RAM, checked before each use; geom_check's bank): each call
# appends the intercept_t at [_Dp] (frac 4, isaline 2, d 4: 10 bytes) to
# REC_BUF, counts in REC_N, and answers 0 (false) at call REC_STOP, else 1
REC_CODE = 0x7C0000
REC_STOP = 0x7C00F0
REC_N = 0x7C0100
REC_BUF = 0x7C0102
REC_MAX = 256
REC_SIZE = 10


class CheckError(Exception):
    pass


def check_disk() -> None:
    st = os.statvfs(str(BUILD))
    if st.f_bavail * st.f_frsize < MIN_FREE:
        raise CheckError('less than 20 GB free: stop')


def tmpdir(tag: str) -> Path:
    return Path(tempfile.mkdtemp(prefix='tmp-path-%s-' % tag,
                                 dir=str(BUILD)))


def addr(sym: str) -> int:
    return TLM.addr(sym)


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
    return CASES / run / native_name(key) / ('h%08d.case.z' % hit)


def load_case(path: Path) -> GC.Case:
    with own_cases():
        return GC.load_case(path)


def le(v: int, n: int) -> bytes:
    return (v & ((1 << 8 * n) - 1)).to_bytes(n, 'little')


def s32(v: int) -> int:
    v &= M32
    return v - (1 << 32) if v & 0x80000000 else v


# ---------------------------------------------------------------------------
# Selection: SAMPLE calls of P_PathTraverse, chosen for the walk's paths
# ---------------------------------------------------------------------------

def survey_calls() -> List[Tuple[str, int, int, List[str]]]:
    """Every call of P_PathTraverse in the survey's runs: (run, hit, tic,
    the dispatch targets it reached), the last call of each run left
    out."""
    out = []
    for run in GC.RUNS:
        sv = GC.survey_of(run)
        if sv is None:
            continue
        r = sv['routines'].get(ENTRY)
        if r is None or not r['calls']:
            continue
        targets = sv['targets']
        for hit in range(1, r['calls']):
            reached = [targets[i] for i in r['reached'].get(str(hit), [])]
            out.append((run, hit, r['tic'][hit - 1], reached))
    return out


def tics_of(key: str) -> set:
    out = set()
    for run in GC.RUNS:
        sv = GC.survey_of(run)
        if sv is None:
            continue
        r = sv['routines'].get(key)
        if r:
            out |= {(run, t) for t in r['tic']}
    return out


def eligible(reached: Sequence[str]) -> bool:
    """Every dispatch target the call reached is built (GAME.md 3.5 step
    6): its traverser never ran."""
    built = set(GL.built_set()) | {PART}
    return all(GL.owner_of(k) in built for k in reached)


def select(n: int = SAMPLE) -> Dict[str, Any]:
    calls = survey_calls()
    stuck = tics_of('p_path65.s:ptStuck')
    fast = tics_of('p_trace65.s:traceLines')
    chosen: List[Tuple[str, int, int, List[str]]] = []

    def take(pool, k):
        have = {(c[0], c[1]) for c in chosen}
        for c in TLM.spread([c for c in pool if (c[0], c[1]) not in have],
                            k):
            chosen.append(c)
    take([c for c in calls if (c[0], c[2]) in stuck], 8)
    take([c for c in calls if (c[0], c[2]) in fast], 6)
    take([c for c in calls if eligible(c[3])], 6)
    for t in TRV:
        take([c for c in calls if t in c[3]], 2)
    take(calls, n - len(chosen))
    chosen.sort(key=lambda c: (GC.RUNS.index(c[0]), c[1]))
    e: Dict[str, List[List[Any]]] = {}
    for run, hit, tic, reached in chosen[:n]:
        e.setdefault(run, []).append([hit, tic, reached])
    return {'format': 'path-select 1', 'sample': n, 'calls': len(calls),
            'eligible_as_captured': sum(1 for c in calls if eligible(c[3])),
            'chosen': e}


def load_select() -> Dict[str, Any]:
    p = OUT / 'select.json'
    if not p.exists():
        raise CheckError('no %s: run path.py --select' % p)
    return json.loads(p.read_text())


def distil_full(raw: Path, run: str, key: str, tic: int, base) -> bytes:
    """A raw capture (hit-N/) as a case's bytes (gamecap.distil's format)
    with every page of RAM that differs from the run's base: the entry
    machine whole, so that a variant (the reference's call again, with
    another traverser, walking blocks the captured call never reached)
    reads the machine's own bytes, never the base's (whose tables, LN36
    and the rest, can be another load's)."""
    call = json.loads((raw / 'call.json').read_text())
    entry = GC.bmem.Memory.from_image(raw / 'entry.img')
    writes = GC.image_records(raw / 'exit.img')
    reads = GC.image_records(raw / 'reads.img')
    after = entry.copy()
    for a, d in writes:
        after.write(a, d)
    pages = GC.reader_pages(entry) | GC.reader_pages(after) | \
        GC._pages_of(reads) | GC._pages_of(writes)
    for reg in ('d', 's'):
        v = call['call']['start'][reg]
        pages |= {v >> 8, (v + 0xFF) >> 8 & 0xFF}
    zero = bytes(0x10000)
    for bank in GC.RAM_BANKS:
        eb = entry.banks.get(bank)
        if eb is None:
            continue
        bb = base.banks.get(bank) or zero
        for pg in range(256):
            if eb[pg << 8:(pg + 1) << 8] != bb[pg << 8:(pg + 1) << 8]:
                pages.add(bank << 8 | pg)
    pages = sorted(pages)
    payload = bytearray()
    for pg in pages:
        a = pg << 8
        payload += bytes(x ^ y for x, y in zip(entry.read(a, GC.PAGE),
                                               base.read(a, GC.PAGE)))
    wbytes = bytearray()
    for a, d in writes:
        wbytes += d
    header = {'format': GC.CASE_FORMAT, 'run': run, 'routine': key,
              'hit': call['hit'], 'tic': tic, 'note': call.get('note'),
              'cycles': call['cycles'], 'call': call['call'],
              'image_header': entry.header.hex(),
              'pages': GC._compress_pages(pages),
              'writes': GC._ranges(writes), 'reads': GC._ranges(reads),
              'whole': True}
    head = json.dumps(header, separators=(',', ':')).encode() + b'\n'
    return zlib.compress(head + bytes(payload) + bytes(wbytes), 6)


def capture_whole(run: str, key: str, hits: Sequence[int],
                  tics: Optional[Sequence[int]]) -> List[Path]:
    """gamecap.capture of hits of key in run, each case with its whole
    machine (distil_full)."""
    entry = GC.CL.Linkmap().address(key)
    todo = [h for h in hits if not case_file(run, key, h).exists()]
    made: List[Path] = []
    for i in range(0, len(todo), CAPTURE_BATCH):
        part = todo[i:i + CAPTURE_BATCH]
        check_disk()
        work = tmpdir('cap')
        try:
            raw = work / 'raw'
            raw.mkdir()
            opts = ['--capture', str(raw), '--capture-entry', '%06X' % entry]
            for h in part:
                opts += ['--capture-hit', str(h)]
            r = GC.machine(run, work, opts)
            if r['problems']:
                raise CheckError('%s: %s' % (run, '; '.join(r['problems'])))
            with own_cases():
                if not GC.base_path(run).exists():
                    first = GC.bmem.Memory.from_image(
                        raw / ('hit-%08d' % part[0]) / 'entry.img')
                    GC.base_path(run).parent.mkdir(parents=True,
                                                   exist_ok=True)
                    GC.base_path(run).write_bytes(zlib.compress(
                        GC._ram_bytes(first), 6))
                base = GC.load_base(run)
            for h in part:
                d = raw / ('hit-%08d' % h)
                tic = tics[h - 1] if tics is not None and h - 1 < len(tics) \
                    else -1
                p = case_file(run, key, h)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(distil_full(d, run, key, tic, base))
                shutil.rmtree(str(d))
                made.append(p)
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    return made


def _capture_job(job: Tuple[str, str, List[int]]) -> str:
    run, key, hits = job
    check_disk()
    sv = GC.survey_of(run)
    tics = sv['routines'][key]['tic'] if sv else None
    made = capture_whole(run, key, hits, tics)
    return '%s %s: %d cases' % (run, key, len(made))


def player_hits(k: int = 18) -> List[int]:
    """k P_PlayerThink calls spread over the tour (every map's tics)."""
    sv = GC.survey_of('tour')
    r = sv['routines'][PLAYER]
    return TLM.spread(list(range(1, r['calls'])), k)


def capture(jobs: int = JOBS, say=print) -> None:
    sel = load_select()
    work = []
    for run, calls in sel['chosen'].items():
        todo = [h for h, _, _ in calls if not case_file(run, ENTRY,
                                                          h).exists()]
        if todo:
            work.append((run, ENTRY, todo))
    todo = [h for h in player_hits() if not case_file('tour', PLAYER,
                                                       h).exists()]
    if todo:
        work.append(('tour', PLAYER, todo))
    firsts: Dict[str, Any] = {}
    for w in work:
        firsts.setdefault(w[0], w)
    first = list(firsts.values())
    rest = [w for w in work if w not in first]
    for group in (first, rest):     # (each run's base made once)
        if not group:
            continue
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for msg in pool.map(_capture_job, group):
                say(msg, flush=True)


def chosen_cases(sel: Dict[str, Any]) -> List[Tuple[Path, List[str]]]:
    out = []
    for run, calls in sel['chosen'].items():
        for hit, _, reached in calls:
            p = case_file(run, ENTRY, hit)
            if p.exists():
                out.append((p, reached))
    return out


# ---------------------------------------------------------------------------
# The paths: upstream's points (ref816 --mark)
# ---------------------------------------------------------------------------

# name -> the line of build/upstream/src/iigs/p_path65.s whose instruction
# starts the path (the release's TICSTEP 1)
POINTS = {
    'things-kept': 213,         # P_PathTraverse: a shot's _Dp[8-15] kept
    'k': 289,                   # ptBody: K for the early traversal
    'step': 333,                # a block step's lines (PT_ADDLINES)
    'tracelines-lines': 345,    # traceLines (fast sides), lines only: the
                                #   caller's _Dp[8-15] kept around it
    'tracelines-things': 357,   # traceLines (fast sides), with things
    'iterator': 360,            # P_BlockLinesIterator
    'lines-full': 368,          # the intercepts full: false
    'things': 374,              # traceThings (PT_ADDTHINGS)
    'early': 381,               # the early traversal
    'early-false': 383,         # the traverser said false in it
    'step-x': 393,              # yintercept on mapy: x step
    'step-y': 408,              # xintercept on mapx: y step
    'false': 424,               # P_PathTraverse false
    'stuck': 428,               # ptStuck (no step)
    'off-line': 444,            # offLine: + FRACUNIT
    'axis+': 489,               # axisStep: at2 > at1
    'axis-': 504,               # at2 < at1
    'axis0': 535,               # at2 == at1
    'traversal': 578,           # the traversal up to FRACUNIT
    'early-none': 645,          # early: M - 2 <= 0
    'early-limit': 627,         # early: T = (M - 2) K
    'early-cap': 641,           # early: the limit capped at FRACUNIT
    'deliver': 783,             # traverseTo: an intercept to the traverser
    'last-out': 790,            # traverseTo: IC_LAST back to the head
    'trav-false': 805,          # traverseTo: the traverser said false
    'beyond': 813,              # traverseTo: the chain's end or beyond
    'stuck-fresh': 835,         # ptStuck: no traverser in this step
    'stuck-copy': 856,          # ptStuck: the things copied
    'stuck-one': 878,           # ptStuck: the traversal
    'stuck-overflow': 880,      # ptStuck: too many: false
    'stuck-ran': 882,           # ptStuck: the next step as usual
}
_PCS: Optional[Dict[str, int]] = None


def path_pcs() -> Dict[str, int]:
    """POINTS' addresses: each line's offset in its fragment (our
    assembler's spans, tools/v816: the unit assembled as the release is
    built), placed by a label of the fragment from the link map."""
    global _PCS
    if _PCS is not None:
        return _PCS
    from v816 import frontend, objfile
    table = TLM.table()
    out: Dict[str, int] = {}
    for src in frontend.sources():
        if src.path.name != 'p_path65.s':
            continue
        o = objfile.assemble(frontend.process(src).unit, 'p_path65.s')
        for name, line in POINTS.items():
            for frag in o.fragments:
                spans = [s for s in frag.spans if s.where.line == line and
                         s.where.file.endswith('/p_path65.s') and
                         not s.where.expansions]
                if not spans:
                    continue
                labels = dict(frag.labels)
                lab = next(lb for lb in labels
                           if not lb.startswith(('PT_', 'G_', 'TI_')))
                out[name] = table.address('p_path65.s:' + lab) + \
                    spans[0].offset - labels[lab]
                break
    missing = set(POINTS) - set(out)
    if missing:
        raise CheckError('path points not found: %s' % sorted(missing))
    _PCS = out
    return out


# ---------------------------------------------------------------------------
# The reference's runs: P_PathTraverse by ref816 --call, with the marks
# ---------------------------------------------------------------------------

def rec_code(dp: int) -> bytes:
    """The recording traverser (dp: _Dp's offset in the direct page; 16-bit
    A, X and Y, as upstream's code calls it)."""
    def long(a: int) -> bytes:
        return le(a, 3)
    c = bytearray()
    c += b'\xAF' + long(REC_N)                      # lda REC_N
    c += b'\x0A'                                    # asl a
    c += b'\x48'                                    # pha
    c += b'\x0A\x0A'                                # asl a; asl a
    c += b'\x18'                                    # clc
    c += b'\x63\x01'                                # adc 1,s (10 n)
    c += b'\xAA'                                    # tax
    c += b'\x68'                                    # pla
    c += b'\xA0\x00\x00'                            # ldy #0
    loop = len(c)
    c += bytes([0xB7, dp])                          # lda [_Dp],y
    c += b'\x9F' + long(REC_BUF)                    # sta REC_BUF,x
    c += b'\xE8\xE8\xC8\xC8'                        # inx; inx; iny; iny
    c += b'\xC0' + le(REC_SIZE, 2)                  # cpy #10
    c += bytes([0xD0, (loop - (len(c) + 2)) & 0xFF])  # bne loop
    c += b'\xAF' + long(REC_N)                      # lda REC_N
    c += b'\x1A'                                    # inc a
    c += b'\x8F' + long(REC_N)                      # sta REC_N
    c += b'\xCF' + long(REC_STOP)                   # cmp REC_STOP
    c += b'\xF0\x04'                                # beq stop
    c += b'\xA9\x01\x00'                            # lda #1
    c += b'\x6B'                                    # rtl
    c += b'\xA9\x00\x00'                            # stop: lda #0
    c += b'\x6B'                                    # rtl
    return bytes(c)


def ref_call(case: GC.Case, pokes: Sequence[Tuple[int, bytes]], note: str,
             regs: Optional[Dict[str, int]] = None) -> GC.Case:
    """P_PathTraverse alone on ref816 (--call) from case's entry memory
    with pokes and registers, the points marked: its return state is
    upstream's own; header['marks'] counts each point."""
    entry = case.entry.copy()
    entry.header = GK.with_registers(case.entry.header, **(regs or {}))
    for a, d in pokes:
        entry.write(a, d)
    pcs = path_pcs()
    work = tmpdir('call')
    try:
        (work / 'entry.img').write_bytes(entry.image_bytes())
        cmd = [str(title.MACHINE), str(work / 'entry.img'), '--call',
               '%06X' % addr(ENTRY), '--call-writes', str(work / 'w.img'),
               '--call-reads', str(work / 'r.img'),
               '--state', str(work / 'state.json'), '--cycles',
               str(REF_CYCLES), '--marks', str(work / 'marks.txt')]
        for pc in sorted(set(pcs.values())):
            cmd += ['--mark', '%06X' % pc]
        r = bounded.run(cmd, timeout=180, max_bytes=GC.MAX_FILE,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r.returncode:
            raise CheckError('ref816 --call failed: %s' % r.stdout[-800:])
        state = json.loads((work / 'state.json').read_text())
        if not state['call']['returned']:
            raise CheckError('the call did not return')
        writes = GC.image_records(work / 'w.img')
        reads = GC.image_records(work / 'r.img')
        counts: Dict[int, int] = {}
        with open(str(work / 'marks.txt')) as handle:
            for line in handle:
                f = line.split()
                if f and f[0] == 'mark':
                    a = int(f[1], 16)
                    counts[a] = counts.get(a, 0) + 1
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    after = entry.copy()
    for a, d in writes:
        after.write(a, d)
    marks = {name: counts.get(pc, 0) for name, pc in pcs.items()}
    header = dict(case.header, routine=ENTRY, note=note, call=state['call'],
                  writes=GC._ranges(writes), reads=GC._ranges(reads),
                  synthetic=True, pokes=[[a, len(d)] for a, d in pokes],
                  marks={k: v for k, v in marks.items() if v})
    return GC.Case(header, entry, after, None)


def dp_of(case: GC.Case) -> int:
    t = TLM.table()
    return case.regs_in['d'] + t.address('_Dp') - t.direct_page


def record_pokes(case: GC.Case, stop: int) -> List[Tuple[int, bytes]]:
    """The recording traverser in place of the call's (the trav argument
    at 10,s), answering false at call stop (0: never)."""
    t = TLM.table()
    if any(case.entry.read(REC_CODE, 0x800)):
        raise CheckError('bank $7C is not free in %s' % (
            case.path or case.header.get('note')))
    return [(REC_CODE, rec_code(t.address('_Dp') - t.direct_page)),
            (REC_STOP, le(stop, 2)), (REC_N, b'\0\0'),
            ((case.regs_in['s'] + 10) & M16, le(REC_CODE, 4))]


def recorded_up(case: GC.Case, up: GR.Upstream, mf) -> List[Tuple[int, int]]:
    """The intercepts the reference's recording traverser was given: (frac,
    what) in the native form (a line, or $8000 + a mobj's slot)."""
    mem = case.after
    n = mem.u16(REC_N)
    out = []
    for k in range(min(n, REC_MAX)):
        a = REC_BUF + REC_SIZE * k
        frac = TLM.u(mem.read(a, 4))
        isaline = mem.u16(a + 4)
        ptr = TLM.u(mem.read(a + 6, 3))
        out.append((frac, TLM.what_of(up, mf, isaline, ptr, 'in')))
    return out


def save_case(case: GC.Case, path: Path) -> None:
    """A variant as a case file against this part's base of its run
    (tracet.save_case's format)."""
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
    for pg in pages:
        a = pg << 8
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


def variant(case: GC.Case, stop: int, pokes=(), regs=None,
            note: str = '') -> GC.Case:
    c = ref_call(case, list(pokes) + record_pokes(case, stop),
                 '%srecord stop %d of %s' % (note, stop, case.path.name if
                                             case.path else
                                             case.header.get('note')),
                 regs)
    c.header['stop'] = stop
    c.header['source'] = case.path.name if case.path else None
    return c


def stops_of(n: int) -> List[int]:
    """The k-stops of a call whose never-stopping run delivered n."""
    return sorted({k for k in (1, (n + 1) // 2, n) if k >= 1})


def _variant_job(job) -> List[str]:
    path, = job
    check_disk()
    case = load_case(Path(path))
    tag = '%s-%s' % (case.header['run'], Path(path).name.split('.')[0])
    out = []
    v0 = variant(case, 0)
    save_case(v0, VAR / ('%s-k0.case.z' % tag))
    out.append(tag + ' k0')
    n = v0.after.u16(REC_N)
    for k in stops_of(n):
        save_case(variant(case, k), VAR / ('%s-k%d.case.z' % (tag, k)))
        out.append('%s k%d' % (tag, k))
    return out


# synthetic: the start on a block line (x, y, both): offLine's path, which
# no captured call takes (GAME.md 2.4 row path's planted bug)
def offline_specs(case: GC.Case) -> List[Tuple[str, List[Tuple[int, bytes]],
                                               Dict[str, int]]]:
    """(name, pokes, registers): case's call with x1 and/or y1 moved onto
    the nearest block line (origin + 128 n, whole units)."""
    mem = case.entry
    ox = s32(TLM.u(mem.read(addr('_g_bmaporgx'), 4)))
    oy = s32(TLM.u(mem.read(addr('_g_bmaporgy'), 4)))
    r = case.regs_in
    x1 = s32((r['x'] & M16) << 16 | (r['a'] & M16))
    dp = dp_of(case)
    y1 = s32(TLM.u(mem.read(dp, 4)))

    def snap(v: int, o: int) -> int:
        return o + round((v - o) / (128 << 16)) * (128 << 16)
    nx, ny = snap(x1, ox), snap(y1, oy)
    out = []
    for name, x, y in (('x', nx, y1), ('y', x1, ny), ('xy', nx, ny)):
        out.append((name, [(dp, le(y, 4))], {'a': x & M16,
                                            'x': (x >> 16) & M16}))
    return out


def make_variants(jobs: int = JOBS, limit: Optional[int] = None,
                  say=print) -> int:
    sel = load_select()
    paths = [p for p, _ in chosen_cases(sel)]
    if limit:
        paths = TLM.spread(paths, limit)
    work = [(str(p),) for p in paths
            if not (VAR / ('%s-%s-k0.case.z' % (p.parent.parent.name,
                                                 p.name.split('.')[0]))
                    ).exists()]
    n = 0
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for got in pool.map(_variant_job, work):
            n += len(got)
            say('variants: %s' % ', '.join(got), flush=True)
    # offLine's synthetic cases, from the first chosen call with things
    base = None
    for p in paths:
        c = load_case(p)
        if TLM.u(c.entry.read((c.regs_in['s'] + 8) & M16, 2)) & \
                PT_ADDTHINGS:
            base = c
            break
    base = base or load_case(paths[0])
    for name, pokes, regs in offline_specs(base):
        for k in (0, 1):
            f = VAR / ('synth-offline-%s-k%d.case.z' % (name, k))
            if f.exists():
                continue
            v = variant(base, k, pokes, regs, 'the start on a block line '
                        '(%s): ' % name)
            v.header['synthetic_name'] = 'offline-' + name
            save_case(v, f)
            n += 1
    say('variants: %d made' % n)
    return n


# ---------------------------------------------------------------------------
# Acceptance 6: long dense traces of more than 64 intercepts on every map
# ---------------------------------------------------------------------------

ACC_STOPS = (0, 1, 8, 32, 64, 65)
# the walk's paths that no chosen call reaches, hunted among acceptance
# 6's candidates (a trace that takes one is kept beside the long ones)
HUNT = ('lines-full', 'early-cap', 'stuck-copy')


def map_states() -> Dict[int, Path]:
    """One P_PlayerThink case a map of the tour (its first)."""
    out: Dict[int, Path] = {}
    d = CASES / 'tour' / native_name(PLAYER)
    for p in sorted(d.glob('h*.case.z')):
        up = GR.Upstream(load_case(p))
        out.setdefault(up.gamemap, p)
    return out


def model_count(state: Dict[str, Any], x1: float, y1: float, x2: float,
                y2: float) -> int:
    """The host model's intercepts of a trace (map units): the lines whose
    segment it crosses and the things (on the block map) whose diagonal
    crosses it. For the choice of traces only: the truth is the
    reference's."""
    def cross(ax, ay, bx, by, cx, cy, dx, dy) -> bool:
        def side(px, py, qx, qy, rx, ry):
            return (qx - px) * (ry - py) - (qy - py) * (rx - px)
        d1 = side(ax, ay, bx, by, cx, cy)
        d2 = side(ax, ay, bx, by, dx, dy)
        d3 = side(cx, cy, dx, dy, ax, ay)
        d4 = side(cx, cy, dx, dy, bx, by)
        return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)
    n = 0
    for ln in state['objects']['line'].values():
        (vx1, vy1), (vx2, vy2) = ln['v1'], ln['v2']
        if cross(x1, y1, x2, y2, vx1, vy1, vx2, vy2):
            n += 1
    noblock = UC['UC_MF_NOBLOCKMAP']
    for mo in state['objects']['mobj'].values():
        if mo.get('free') or mo['flags'] & noblock:
            continue
        x, y, r = mo['x'] / 65536, mo['y'] / 65536, mo['radius'] / 65536
        if (cross(x1, y1, x2, y2, x - r, y - r, x + r, y + r) or
                cross(x1, y1, x2, y2, x - r, y + r, x + r, y - r)):
            n += 1
    return n


def trace_call(case: GC.Case, t: Tuple[int, int, int, int, int],
               flags: int) -> Tuple[List[Tuple[int, bytes]],
                                    Dict[str, int]]:
    """The pokes and registers of P_PathTraverse(x1, y1, x2, y2, flags) on
    case's state (a P_PlayerThink entry: the stack's arguments past S)."""
    x1, y1, x2, y2, _ = t
    dp = dp_of(case)
    s = case.regs_in['s']
    pokes = [(dp, le(y1, 4)), (dp + 4, le(x2, 4)),
             ((s + 4) & M16, le(y2, 4)), ((s + 8) & M16, le(flags, 2))]
    regs = {'a': x1 & M16, 'x': (x1 >> 16) & M16,
            'p': case.regs_in['p'] & ~0x30 & 0xFF}
    return pokes, regs


def overflowed(v: GC.Case) -> bool:
    """The reference's never-stopping run (stop 0) returned false: its
    intercepts passed MAXINTERCEPTS (the lines' or the things' list full,
    or ptStuck's copies past it): what the C calls more than 64
    intercepts (the recording traverser itself never says false)."""
    return v.header.get('stop') == 0 and not v.regs_out['a'] & M16


def acc_candidates(case: GC.Case, k: int, seed: int
                   ) -> List[Tuple[int, int, int, int, int]]:
    """k long traces from things' places (a thing's block is where a
    stuck walk copies intercepts), 1,500-6,000 units in a random
    direction, with the host model's count (lines crossed, things'
    diagonals crossed) at least 20."""
    st = GR.Upstream(case).s_in
    noblock = UC['UC_MF_NOBLOCKMAP']
    things = [(mo['x'] / 65536, mo['y'] / 65536)
              for mo in st['objects']['mobj'].values()
              if not mo.get('free') and not mo['flags'] & noblock]
    rnd = random.Random(seed)
    out = []
    for _ in range(40 * k):
        if len(out) >= k or not things:
            break
        x, y = rnd.choice(things)
        x1, y1 = x + rnd.uniform(-60, 60), y + rnd.uniform(-60, 60)
        a = rnd.uniform(0, 2 * math.pi)
        d = rnd.uniform(1500, 6000)
        x2, y2 = x1 + d * math.cos(a), y1 + d * math.sin(a)
        n = model_count(st, x1, y1, x2, y2)
        if n >= 20:
            out.append((int(x1 * 65536) + rnd.randrange(1, 0xFFFF),
                        int(y1 * 65536) + rnd.randrange(1, 0xFFFF),
                        int(x2 * 65536) + rnd.randrange(1, 0xFFFF),
                        int(y2 * 65536) + rnd.randrange(1, 0xFFFF), n))
    return out


def _acc_map_job(job) -> Dict[str, Any]:
    """One map: candidates run on the reference (stop 0) until per traces
    passed 64 intercepts there; each kept with its ACC_STOPS runs."""
    path, gamemap, per, seed, tries = job
    check_disk()
    case = load_case(Path(path))
    kept, tried, counts = 0, 0, []
    stuck: List[Dict[str, Any]] = []
    found: set = set()
    for i, t in enumerate(acc_candidates(case, tries, seed)):
        if kept >= per and found >= set(HUNT):
            break
        flags = PT_ADDLINES | PT_ADDTHINGS
        pokes, regs = trace_call(case, t, flags)
        note = 'E1M%d trace %d (model %d): ' % (gamemap, i, t[4])
        tried += 1
        try:
            v0 = variant(case, 0, pokes, regs, note)
        except CheckError as error:
            stuck.append({'trace': list(t), 'error': str(error)[:300]})
            continue
        over = overflowed(v0)
        hunt = [h for h in HUNT if v0.header['marks'].get(h) and
                h not in found]
        if over:
            if kept >= per:
                continue
            kept += 1
            counts.append(t[4])
        elif hunt:
            found.update(hunt)
        else:
            continue
        for k in ACC_STOPS:
            v = v0 if k == 0 else variant(case, k, pokes, regs, note)
            v.header['acceptance'] = {'map': gamemap, 'trace': i,
                                      'model': t[4], 'flags': flags,
                                      'over_64': over, 'paths': hunt}
            save_case(v, ACC / ('e1m%d-%s%03d-k%d.case.z' % (
                gamemap, 't' if over else 'p', i, k)))
    return {'map': gamemap, 'tried': tried, 'kept': kept, 'model': counts,
            'paths': sorted(found), 'reference_failed': stuck}


def make_acceptance(traces: int = 27, jobs: int = JOBS, seed: int = 6,
                    tries: int = 300, say=print) -> int:
    """traces long traces of more than 64 intercepts (the reference's
    count) spread over the maps' states, each run on the reference with
    ACC_STOPS (acceptance 6)."""
    states = map_states()
    if len(states) < 9:
        say('acceptance 6: states of %d maps only (%s)' % (
            len(states), sorted(states)))
    per = max(1, -(-traces // max(1, len(states))))
    work = [(str(p), gamemap, per, seed * 100 + gamemap, tries)
            for gamemap, p in sorted(states.items())]
    out = []
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for got in pool.map(_acc_map_job, work):
            out.append(got)
            say('acceptance 6: E1M%(map)d: %(kept)d of %(tried)d tried '
                'passed 64 intercepts' % got, flush=True)
    save('acc6.json', out)
    return sum(g['kept'] for g in out)


# The final integration's acceptance 6 (docs/GAME.md "Acceptance": the
# owner's lean target of 200 traces of more than 64 intercepts): the same
# method as make_acceptance, more candidates a map (a new seed), only the
# traces past 64 intercepts kept, in a directory of their own
ACCF = CASES / 'acc6-final'


def _accf_map_job(job) -> Dict[str, Any]:
    path, gamemap, per, seed, tries = job
    check_disk()
    case = load_case(Path(path))
    kept, tried = 0, 0
    for i, t in enumerate(acc_candidates(case, tries, seed)):
        if kept >= per:
            break
        flags = PT_ADDLINES | PT_ADDTHINGS
        pokes, regs = trace_call(case, t, flags)
        note = 'E1M%d trace %d (model %d): ' % (gamemap, i, t[4])
        tried += 1
        try:
            v0 = variant(case, 0, pokes, regs, note)
        except CheckError:
            continue                    # (upstream's fixedDiv loop: T8)
        if not overflowed(v0):
            continue
        kept += 1
        for k in ACC_STOPS:
            v = v0 if k == 0 else variant(case, k, pokes, regs, note)
            v.header['acceptance'] = {'map': gamemap, 'trace': i,
                                      'model': t[4], 'flags': flags,
                                      'over_64': True, 'paths': []}
            save_case(v, ACCF / ('e1m%d-t%04d-k%d.case.z' % (gamemap, i,
                                                             k)))
    return {'map': gamemap, 'tried': tried, 'kept': kept}


def make_acceptance_final(traces: int = 200, jobs: int = JOBS,
                          seed: int = 60, tries: int = 12000,
                          say=print) -> List[Dict[str, Any]]:
    """At least `traces` traces of more than 64 intercepts over the maps
    that have them (E1M1 and E1M4 gave none at wave 4: path.md R6), each
    with ACC_STOPS on the reference."""
    states = map_states()
    maps = [m for m in sorted(states) if m not in (1, 4)]
    per = -(-traces // len(maps))
    work = [(str(states[m]), m, per, seed * 100 + m, tries) for m in maps]
    out = []
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for got in pool.map(_accf_map_job, work):
            out.append(got)
            say('acceptance 6 (final): E1M%(map)d: %(kept)d of %(tried)d '
                'tried passed 64 intercepts' % got, flush=True)
    save('acc6-final.json', out)
    return out


def check_final(obj: Path = OUT, jobs: int = JOBS, say=print
                ) -> Dict[str, Any]:
    """The final acceptance 6's cases on the native image."""
    work = [(str(p), str(obj), 'acc6f')
            for p in sorted(ACCF.glob('*.case.z'))]
    out: List[Dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for r in pool.map(_run_job, work, chunksize=2):
            out.append(r)
    bad = [r for r in out if failed(r)]
    traces = {(r['acceptance']['map'], r['acceptance']['trace'])
              for r in out if r.get('acceptance')}
    rep = {'runs': len(out), 'traces': len(traces), 'failures': len(bad),
           'undecodable': sum(1 for r in out
                              if r['class'] == 'undecodable'),
           'intercepts': sum(r.get('delivered') or 0
                             for r in out if r.get('stop') == 0),
           'first_failures': [{k: v for k, v in r.items() if k != 'marks'}
                              for r in bad[:4]]}
    save('acc6-final-run.json', rep)
    say('acceptance 6 (final): %(runs)d runs, %(traces)d traces, '
        '%(failures)d failed, %(undecodable)d undecodable' % rep)
    return rep


# ---------------------------------------------------------------------------
# A case on the native image
# ---------------------------------------------------------------------------

def args() -> Dict[str, Any]:
    d = json.loads(ARGS.read_text())
    if d.get('format') != GR.ARGS_FORMAT:
        raise CheckError('%s: not %s' % (ARGS, GR.ARGS_FORMAT))
    return d


def spec_of(key: str = ENTRY) -> Dict[str, Any]:
    return args()['entries'][key]


# A built traverser's context: what its caller set before P_PathTraverse
# and the traverser reads (upstream's near scratch, natively the caller's
# part's scratch block or GW). A captured call that runs its own traverser
# (a "plain" case, once the traverser's part is built: wave 5 as
# integrated) takes it from the reference's state at the call, as the
# traverser's own parts' checkpoints take it from their entries' setups.
# Each: the part's include (its places), then (upstream source, native
# place, conversion).
TRV_CONTEXT = {
    'attack': ('game/attack/attack.inc', (
        ('abs:p_attack65.s:AT_SHOOT:3', 'AK_SHOOT', 'mobj'),
        ('abs:p_attack65.s:AT_Z:4', 'AK_Z', None),
        ('abs:p_attack65.s:AT_DAMAGE:2', 'AK_DMG', None),
        ('abs:p_attack65.s:AT_TOP:4', 'AK_TOP', None),
        ('abs:p_attack65.s:AT_BOT:4', 'AK_BOT', None),
        ('abs:p_attack65.s:AT_AIM:4', 'AK_AIM', None),
        ('abs:p_attack65.s:AT_RANGE:4', 'GM_ATRANGE', None),
        ('abs:_g_linetarget:3', 'GM_LINETARGET', 'mobj'))),
    'player': ('game/player/player.inc', (
        ('abs:p_use65.s:usething:3', 'PY_THING', 'mobj'),)),
    'xymove': ('game/xymove/xymove.inc', (
        ('abs:p_mobj65.s:SL_MO:3', 'XY_MO', 'mobj'),
        ('abs:p_mobj65.s:SL_BEST:4', 'XY_BEST', None))),
}


def inc_symbols(b, inc: str) -> Dict[str, int]:
    """The symbols of the image's ggame.inc and of a part's include
    (NAME = value, NAME = OTHER, NAME = OTHER + n, NAME = OTHER - n)."""
    exprs: Dict[str, str] = {}
    for path in (b.obj / 'gen' / 'ggame.inc', SRC / inc):
        for line in path.read_text().splitlines():
            m = re.match(r'^\s*([A-Za-z_]\w*)\s*=\s*([^;]+)', line)
            if m:
                exprs.setdefault(m.group(1), m.group(2).strip())
    out: Dict[str, int] = {}

    def val(name: str, depth: int = 0) -> int:
        if name in out:
            return out[name]
        if depth > 20 or name not in exprs:
            raise CheckError('no symbol %s for a traverser context' % name)
        total = 0
        for sign, term in re.findall(r'([+-]?)\s*([$\w]+)',
                                     exprs[name]):
            if term.startswith('$'):
                v = int(term[1:], 16)
            elif term[0].isdigit():
                v = int(term, 0)
            else:
                v = val(term, depth + 1)
            total += -v if sign == '-' else v
        out[name] = total
        return total
    for n in exprs:
        if re.fullmatch(r'[$\w\s+-]+', exprs[n]):
            try:
                val(n)
            except CheckError:      # (a name of another include)
                pass
    return out


def context_pokes(case: GC.Case, up: GR.Upstream, mf, b, n: int
                  ) -> List[Tuple[int, bytes]]:
    """The context of TRVTAB's traverser n from the reference's state at
    the call (TRV_CONTEXT; none for the recording traverser)."""
    if not 1 <= n <= len(TRV):
        return []
    part = GL.owner_of(TRV[n - 1])
    if part not in TRV_CONTEXT:
        return []
    inc, items = TRV_CONTEXT[part]
    syms = inc_symbols(b, inc)
    out = []
    for src, place, kind in items:
        data = GK.up_source(up, src, 'in')
        if kind == 'mobj':
            v = int.from_bytes(data, 'little') & 0xFFFFFF
            h = 0xFFFF if v == 0 else GR.handle_of(mf, up.ref(v))
            data = h.to_bytes(2, 'little')
        if place not in syms:
            raise CheckError('no place %s for traverser %s' % (place,
                                                               TRV[n - 1]))
        out.append((syms[place], data))
    return out


def trv_number(v: int) -> int:
    """An upstream traverser's address as its TRVTAB number (the recording
    traverser: the harness's entry)."""
    v &= 0xFFFFFF
    if v == REC_CODE:
        return TRV_HARNESS
    t = TLM.table()
    for n, k in enumerate(TRV, 1):
        if t.address(k) == v:
            return n
    raise CheckError('traverser $%06X is no TRVTAB target' % v)


def recorded_native(b, m) -> List[Tuple[int, int]]:
    lab = b.labels
    n = G.card_byte(m, lab['rec_n']) | G.card_byte(m, lab['rec_n'] + 1) << 8 \
        if lab['rec_n'] >= 0xC000 else m.main[lab['rec_n']] | \
        m.main[lab['rec_n'] + 1] << 8
    g = m.aux.get(LL.GTEST, bytearray(0x10000))
    out = []
    for k in range(min(n, 256)):
        a = GL.GTB['GT_RECORD'] + 8 * k
        e = bytes(g[a:a + 6])
        out.append((TLM.u(e[:4]), TLM.u(e[4:])))
    return out


def core_poke(img, address: int, data: bytes) -> None:
    if not img.core_lo <= address < img.core_lo + len(img.core):
        raise CheckError('$%04X is not in the core image' % address)
    img.core[address - img.core_lo:address - img.core_lo + len(data)] = data


def run_native(case: GC.Case, b, fill: int = FILL,
               profile: Optional[str] = PROFILE) -> Dict[str, Any]:
    spec = spec_of()
    up = GR.Upstream(case)
    res: Dict[str, Any] = {'case': case.path.name if case.path else
                           case.header.get('note'), 'routine': case.key,
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
    recording = False
    for item in spec.get('in', []):
        src, to = item['from'], item['to']
        if src == 'trace':
            for a, d in TLM.trace_pokes(b, TLM.up_trace(case.entry)):
                img.main(a, d)
            continue
        if src == 'list':
            # (a state where no trace ran since the load holds no list:
            # intercept_p 0; P_PathTraverse starts its own, and only what
            # it writes is compared)
            try:
                lst = TLM.up_list(up, mf, 'in')
            except TLM.CheckError:
                continue
            for a, d in TLM.list_pokes(lst, b):
                img.main(a, d)
            continue
        if src == 'sides':
            for a, d in TTM.sides_pokes(b, TTM.up_sides(case.entry)):
                img.main(a, d)
            continue
        data = GK.up_source(up, src, 'in')
        if item.get('as') == 'trvtab':
            n = trv_number(TLM.u(data))
            recording = n == TRV_HARNESS
            data = bytes([n])
            for a, d in context_pokes(case, up, mf, b, n):
                img.main(a, d)
        else:
            data = GK.convert_in(up, mf, item, data)
        n = item.get('bytes', len(data))
        img.main(GK.native_address(b, to.split(':', 1)[1]),
                 data[:n].ljust(n, b'\0'))
    if recording:
        # TRVTAB's harness entry: pt_rec_trv (GA_0 the intercept: a jump
        # to grec.s's gt_record_trv, request R2 as integrated)
        lab = b.labels
        core_poke(img, lab['TRVTAB'] + 3 * (TRV_HARNESS - 1),
                  bytes([0]) + le(lab['pt_rec_trv'], 2))
        img.poke_label('rec_n', b'\0\0')
        img.poke_label('rec_stop', le(case.header.get('stop', 0), 2))
    work = tmpdir('run')
    try:
        r = GK.run_entry(img, work, spec['native'], regs=(0, 0, 0, 0x34),
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
    regs_n = GK.native_regs(b, m)
    for item in spec.get('out', []):
        nv, uv = item['native'], item['upstream']
        if nv == 'list':
            diff += TLM.compare_list(TLM.up_list(up, mf, 'out'),
                                     TLM.nat_list(b, m))
        elif nv == 'trace':
            diff += TLM.compare_trace(TLM.up_trace(case.after),
                                      TLM.nat_trace(b, m))
        elif nv == 'sides':
            diff += TTM.compare_sides(TTM.up_sides(case.after),
                                      TTM.nat_sides(b, m))
        elif item.get('as') == 'bool':
            want = 1 if TLM.u(GK.up_source(up, uv, 'out')) else 0
            if regs_n['p'] & 1 != want:
                diff.append('result: C %d, upstream %d' % (regs_n['p'] & 1,
                                                           want))
            if regs_n['a'] != want:
                diff.append('result: A %d, upstream %d' % (regs_n['a'],
                                                           want))
            res['result'] = want
        else:
            raise CheckError('an output %r' % nv)
    if recording:
        want = recorded_up(case, up, mf)
        got = recorded_native(b, m)
        res['delivered'] = len(want)
        if got != want:
            k = next((i for i, (g, w) in enumerate(zip(got, want))
                      if g != w), min(len(got), len(want)))
            diff.append('delivered %d, upstream %d; first difference at %d: '
                        '%s, upstream %s' % (
                            len(got), len(want), k,
                            ['%08X %04X' % e for e in got[k:k + 2]],
                            ['%08X %04X' % e for e in want[k:k + 2]]))
    res['intercepts'] = TLM.up_list(up, mf, 'out')['n']
    res['diff'] = diff[:12]
    res['ok'] = not diff and not stray
    return res


def classify_result(r: Dict[str, Any]) -> str:
    if r.get('ok'):
        return 'equal'
    if (r.get('error') or '').startswith('bridge:'):
        return 'undecodable'
    return 'failed'


def failed(r: Dict[str, Any]) -> bool:
    return r.get('class', 'failed' if not r.get('ok') else 'equal') == \
        'failed'


def _run_job(job) -> Dict[str, Any]:
    path, obj, kind = job
    b = G.load_build(Path(obj), IMAGE)
    case = load_case(Path(path))
    try:
        r = run_native(case, b)
    except Exception as error:
        r = {'case': Path(path).name, 'routine': ENTRY, 'ok': False,
             'fill': '%02x' % FILL, 'profile': PROFILE,
             'error': '%s: %s' % (type(error).__name__, error)}
    r['kind'] = kind
    r['run'] = case.header.get('run')
    r['stop'] = case.header.get('stop')
    r['marks'] = case.header.get('marks')
    if case.header.get('acceptance'):
        r['acceptance'] = case.header['acceptance']
    r['class'] = classify_result(r)
    return r


def work_items(limit: Optional[int] = None, kinds=('plain', 'record',
                                                   'synth', 'acc6')
               ) -> List[Tuple[str, str]]:
    """(case file, kind): the chosen calls that are eligible as captured
    (plain), their variants (record), offLine's synthetic ones (synth),
    acceptance 6's (acc6)."""
    out = []
    if 'plain' in kinds:
        ps = [p for p, reached in chosen_cases(load_select())
              if eligible(reached)]
        out += [(str(p), 'plain') for p in (TLM.spread(ps, limit)
                                            if limit else ps)]
    if 'record' in kinds:
        vs = sorted(VAR.glob('[!s]*.case.z')) if VAR.exists() else []
        if limit:
            tags = sorted({v.name.rsplit('-k', 1)[0] for v in vs})
            keep = set(TLM.spread(tags, limit))
            vs = [v for v in vs if v.name.rsplit('-k', 1)[0] in keep]
        out += [(str(v), 'record') for v in vs]
    if 'synth' in kinds and VAR.exists():
        out += [(str(v), 'synth') for v in sorted(VAR.glob('synth-*'))]
    if 'acc6' in kinds and ACC.exists():
        # (e1mN-tI: a trace of more than 64 intercepts; e1mN-pI: one kept
        # for a path no chosen call takes; a sample takes the former)
        vs = sorted(ACC.glob('*.case.z'))
        if limit:
            tags = sorted({v.name.rsplit('-k', 1)[0] for v in vs
                           if '-t' in v.name})
            keep = set(TLM.spread(tags, max(1, limit // 4)))
            vs = [v for v in vs if v.name.rsplit('-k', 1)[0] in keep]
        out += [(str(v), 'acc6') for v in vs]
    return out


def check_cases(obj: Path = OUT, jobs: int = JOBS,
                limit: Optional[int] = None, kinds=('plain', 'record',
                                                    'synth', 'acc6'),
                say=print) -> List[Dict[str, Any]]:
    work = [(p, str(obj), k) for p, k in work_items(limit, kinds)]
    out: List[Dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for r in pool.map(_run_job, work, chunksize=2):
            out.append(r)
    for kind in kinds:
        rs = [r for r in out if r['kind'] == kind]
        bad = [r for r in rs if failed(r)]
        say('%s: %d runs, %d failed, %d undecodable' % (
            kind, len(rs), len(bad),
            sum(1 for r in rs if r['class'] == 'undecodable')), flush=True)
        for r in bad[:3]:
            say('  %s' % json.dumps({k: v for k, v in r.items()
                                     if k != 'marks'})[:700], flush=True)
    return out


# ---------------------------------------------------------------------------
# a1Shr7's random check (GAME.md 2.4 "Arithmetic")
# ---------------------------------------------------------------------------

BULK_IN, BULK_OUT = 93, 94
BULK_ROOM = 0xC000 - 0x0200
EDGES = (0, 1, -1, 2, -2, 0x7F, 0x80, 0xFF, 0x100, -0x80, -0x81,
         0x7FFFFFFF, -0x80000000, 0x7FFFFF, 0x800000, -0x800000, 0x7FFF80,
         0xFFFF, 0x10000, -0x10000, 0x8000, -0x8000, 0x3FFFFF, 0x400000,
         0x7FFFFF80, -0x7FFFFF80)


def a1_inputs(n: int, seed: int = 1) -> List[int]:
    rnd = random.Random(seed)
    out = [v & M32 for v in EDGES]
    while len(out) < n:
        k = len(out) % 3
        if k == 0:
            out.append(rnd.getrandbits(32))
        elif k == 1:        # coordinates from the block map's origin
            out.append(rnd.randint(-0x8000000, 0x8000000) & M32)
        else:
            out.append(((rnd.choice((1, -1)) << rnd.randint(0, 30)) +
                        rnd.randint(-0x80, 0x80)) & M32)
    return out[:n]


def native_bulk(b, values: Sequence[int]) -> List[int]:
    per = BULK_ROOM // 4
    out: List[int] = []
    for start in range(0, len(values), per):
        chunk = values[start:start + per]
        img = G.Image(b, FILL, store=False)
        img.aux(BULK_IN, 0x0200, b''.join(le(v, 4) for v in chunk))
        work = tmpdir('bulk')
        try:
            k = len(chunk)
            r = G.run(img, work, GL.MODES['ROUTINE'], 'pt_bulk',
                      regs=(0, k & 0xFF, k >> 8, 0x34), banks=[BULK_OUT])
            if r.ended() != 'halt':
                raise CheckError('pt_bulk ended %s' % r.ended())
            m = G.load_snapshot(work / 'done.img')
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        data = bytes(m.aux[BULK_OUT][0x0200:0x0200 + 2 * k])
        out += [data[i] | data[i + 1] << 8 for i in range(0, len(data), 2)]
    return out


def upstream_a1(case: GC.Case, values: Sequence[int]) -> List[int]:
    """upstream's a1Shr7 on each value (mathref batch on a captured call's
    machine: PT_X1 in, AX_A 0, A out)."""
    import sight as SG
    pc = addr('p_path65.s:a1Shr7')
    mem = case.entry.copy()
    mem.header = case.entry.header
    mem.write(addr('p_path65.s:AX_A'), b'\0\0')
    c = GC.Case(dict(case.header), mem, mem, None)
    recs = b''.join(le(v, 4) for v in values)
    outs = SG.mathref(c, 'a1Shr7', pc, ['%06X 4' % addr('p_path65.s:PT_X1')],
                      ['a'], recs, 2)
    return [o[0] | o[1] << 8 for o in outs]


def random_check(n: int = 100_000, seed: int = 1, b=None) -> Dict[str, Any]:
    paths = [p for p, _ in chosen_cases(load_select())]
    if not paths:
        raise CheckError('no P_PathTraverse case (path.py --capture)')
    case = load_case(paths[0])
    b = b or G.load_build(OUT, IMAGE)
    vals = a1_inputs(n, seed)
    ups = upstream_a1(case, vals)
    nat = native_bulk(b, vals)
    bad = [(v, u, m) for v, u, m in zip(vals, ups, nat) if u != m]
    model = sum(1 for v, u in zip(vals, ups) if u == (v >> 7) & M16)
    return {'helper': 'p_path65.s:a1Shr7', 'inputs': len(vals),
            'compared': min(len(ups), len(nat)),
            'different': len(bad) + abs(len(ups) - len(nat)),
            'first': bad[:5], 'edges': len(EDGES),
            'upstream_is_bits_7_22': model, 'seed': seed}


# ---------------------------------------------------------------------------
# Builds and planted bugs
# ---------------------------------------------------------------------------

def build(source: Path = SRC, game: Optional[Path] = None) -> Path:
    """make -f game.mk part P=path PT_TEST=1 (source: the tree's
    src/native or a scratch copy; game: its GAME directory): the image's
    directory. A warning fails it."""
    cmd = ['make', '-s', '-C', str(source), '-f', 'game.mk', 'part',
           'P=%s' % PART, 'PT_TEST=1', 'ROOT=%s' % ROOT]
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


S = 'game/path/path.s'
# The planted bugs (docs/GAME.md 2.4 row path; the lean rules: the three
# most likely), each (file, old, new) in src/native/ and the runs that must
# catch it
PLANTS = {
    # the early limit one block late: (M - 1) K, not (M - 2) K: the early
    # traversal gives intercepts before the blocks that can come before
    # them are walked; a stop then leaves other blocks unwalked (the
    # lines' stamps), and the delivered order can change
    'early-late': {'bugs': [(S, """        sbc #2
        sta M_A""", """        sbc #1                          ; (planted)
        sta M_A""")], 'kinds': ('record', 'acc6'),
        'check': 'the k-stop runs (stamps, deliveries)'},
    # more than 64 intercepts handled as the C does (none): no early
    # traversal, so a trace that fills the list gives the traverser
    # nothing, where upstream gave it the intercepts the early traversal
    # reached
    'c-overflow': {'bugs': [(S, """@early: lda PT_K                        ; the early traversal
        ora PT_K+1
        beq @last""", """@early: bra @last                       ; (planted: the C's)
        ora PT_K+1
        beq @last""")], 'kinds': ('acc6',), 'check': 'acceptance 6'},
    # the start not moved off a block line (offLine never adds FRACUNIT)
    'no-offline': {'bugs': [(S, """        inc GA_2,x                      ; the high word + 1 (16 bits)
        bne @r
        inc GA_3,x""", """        bra @r                          ; (planted)
        bne @r
        inc GA_3,x""")], 'kinds': ('synth',),
        'check': 'the start on a block line (synthetic)'},
}


def plant_check(name: str, jobs: int = JOBS, limit: Optional[int] = None,
                say=print) -> Dict[str, Any]:
    p = PLANTS[name]
    check_disk()
    tmp = tmpdir('plant')
    try:
        obj = planted(tmp, p['bugs'])
        rs = check_cases(obj, jobs, limit=limit, kinds=p['kinds'],
                         say=lambda *a, **k: None)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    caught = sum(1 for r in rs if failed(r))
    out = {'plant': name, 'check': p['check'], 'runs': len(rs),
           'caught': caught,
           'first': next((r.get('diff') or r.get('error') or r.get('stop')
                          for r in rs if failed(r)), None)}
    say('plant %s: %d of %d runs fail' % (name, caught, len(rs)))
    return out


# ---------------------------------------------------------------------------
# Sizes and the report
# ---------------------------------------------------------------------------

BUDGET = {'up': 1239, 'native': 1600}
GAME_MODULES = ('path',)


def routine_sizes(b) -> Dict[str, int]:
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
    names = [native_name(k) for k in ROUTINES + HELPERS]
    out = {}
    for seg, lo, size in segs:
        here = sorted((b.labels[n], n) for n in names if n in b.labels and
                      GK.seg_of(b, n) == seg and lo <= b.labels[n] <
                      lo + size)
        for i, (a, n) in enumerate(here):
            out[n] = (here[i + 1][0] if i + 1 < len(here) else lo + size) - a
    return out


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    b = G.load_build(obj, IMAGE)
    rs = routine_sizes(b)
    game = sum(rs.values())
    return {'native_bytes': game, 'budget': BUDGET['native'],
            'upstream_bytes': BUDGET['up'],
            'over_budget_pct': round(100.0 * (game - BUDGET['native']) /
                                     BUDGET['native'], 1),
            'routines': rs,
            'test_only': {'pttest.s': driver_bytes(b, 'pttest')}}


def driver_bytes(b, module: str) -> int:
    """A module's bytes in segment DRIVER (the card's driver area: test
    builds only)."""
    text = (b.obj / (b.name + '.map')).read_text()
    text = text.split('Modules list:', 1)[-1].split('Segment list:', 1)[0]
    cur, n = None, 0
    for line in text.splitlines():
        if line and not line.startswith(' ') and line.endswith('.o:'):
            cur = Path(line[:-1]).stem
            continue
        f = line.split()
        if cur == module and f and f[0] == 'DRIVER':
            n += next(int(x[5:], 16) for x in f if x.startswith('Size='))
    return n


def _stats(xs: Sequence[Optional[float]]) -> Optional[Dict[str, float]]:
    ys = sorted(x for x in xs if x is not None)
    if not ys:
        return None
    return {'median': ys[len(ys) // 2], 'worst': ys[-1], 'n': len(ys)}


def summarise(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    from a2vm import costs
    mhz = costs.parameters(PROFILE)['fabric_mhz']
    classes: Dict[str, int] = {}
    for r in results:
        classes[r.get('class', '?')] = classes.get(r.get('class', '?'), 0) \
            + 1
    return {'runs': len(results),
            'failures': sum(1 for r in results if failed(r)),
            'classes': classes,
            'stray_writes': sum(r.get('stray_n', 0) for r in results),
            'lowest_s': min((r['lowest_s'] for r in results
                             if r.get('lowest_s') is not None),
                            default=None),
            'cycles': {PROFILE: _stats([r.get('cycles') for r in results])},
            'us': {PROFILE: _stats([round(r['clocks'] / mhz, 2)
                                    for r in results if r.get('clocks')])},
            'delivered': sum(r.get('delivered', 0) for r in results),
            'first_failures': [{k: v for k, v in r.items() if k != 'marks'}
                               for r in results if failed(r)][:5]}


def coverage(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    seen: Dict[str, int] = {}
    for r in results:
        for k, v in (r.get('marks') or {}).items():
            seen[k] = seen.get(k, 0) + v
    return {'points': {k: seen.get(k, 0) for k in POINTS},
            'not_reached': [k for k in POINTS if not seen.get(k)]}


def report(results: List[Dict[str, Any]],
           rnd: Optional[Dict[str, Any]],
           plants: Optional[List[Dict[str, Any]]], obj: Path = OUT
           ) -> Dict[str, Any]:
    sel = load_select()
    by = {k: [r for r in results if r['kind'] == k]
          for k in ('plain', 'record', 'synth', 'acc6')}
    acc = by['acc6']
    rep: Dict[str, Any] = {
        'format': 'game-part-report 1', 'part': PART, 'wave': 4,
        'lean': 'the owner\'s request of 2026-10-02: at most %d calls of '
                'the entry, one fill ($%02X), one profile (%s)' % (
                    SAMPLE, FILL, PROFILE),
        'fills': ['%02X' % FILL], 'profiles': [PROFILE],
        'exclusions': [n for n, _, _ in gcanon.ROUTINE_EXCLUSIONS],
        'no_native_code': list(NO_CODE),
        'entries': {ENTRY: {
            'survey_calls': sel['calls'],
            'eligible_as_captured': sel['eligible_as_captured'],
            'chosen': sum(len(c) for c in sel['chosen'].values()),
            'as_captured': summarise(by['plain']),
            'recording_and_k_stops': summarise(by['record']),
            'synthetic': summarise(by['synth'])}},
        'acceptance_6': dict(summarise(acc), traces=len({
            (r['acceptance']['map'], r['acceptance']['trace'])
            for r in acc if r.get('acceptance')}),
            maps=sorted({r['acceptance']['map'] for r in acc
                         if r.get('acceptance')}),
            over_64=len({(r['acceptance']['map'], r['acceptance']['trace'])
                         for r in acc if r.get('acceptance') and
                         r.get('stop') == 0 and r.get('result') == 0}),
            path_traces=len({(r['acceptance']['map'],
                              r['acceptance']['trace'])
                             for r in acc if r.get('acceptance') and
                             not r['acceptance'].get('over_64')})),
        'paths': coverage(by['record'] + by['synth'] + acc),
        'sizes': sizes(obj)}
    if rnd is not None:
        rep['random'] = rnd
    if plants is not None:
        rep['plants'] = plants
    allr = [r for v in by.values() for r in v]
    rep['failures'] = sum(1 for r in allr if failed(r))
    rep['stray_writes'] = sum(r.get('stray_n', 0) for r in allr)
    rep['lowest_s'] = min((r['lowest_s'] for r in allr
                           if r.get('lowest_s') is not None), default=None)
    return rep


def need() -> Optional[str]:
    """What build/ lacks for the checkpoint (None: all there)."""
    for p, cmd in (
            (GL.SHARED / 'gen' / 'ggame.inc',
             'make -s -C src/native -f game.mk shared ROOT=$PWD'),
            (GL.SHARED / 'native-game-1.json',
             'make -s -C src/native -f game.mk shared ROOT=$PWD'),
            (GL.SHARED / 'survey.json',
             'python3 tools/native/gamecap.py --survey'),
            (GL.SHARED / 'placement.json',
             'make -s -C src/native -f game.mk place ROOT=$PWD'),
            (G.A2VM, 'make -C tools/a2vm'),
            (title.MACHINE, 'make -C tools/ref816'),
            (BUILD / 'native' / 'math' / 'mathref',
             'make -C src/native -f math.mk (milestone 6)')):
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


def load(name: str) -> Any:
    p = OUT / name
    return json.loads(p.read_text()) if p.exists() else None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ('select', 'capture', 'variants', 'acceptance', 'run',
                 'random', 'plants', 'report', 'all', 'acceptance-final',
                 'run-final'):
        parser.add_argument('--' + flag, action='store_true')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--traces', type=int, default=27)
    parser.add_argument('--count', type=int, default=100_000)
    parser.add_argument('--obj', type=Path, default=OUT)
    parser.add_argument('--jobs', type=int, default=JOBS)
    a = parser.parse_args(argv)
    missing = need()
    if missing:
        print(missing, file=sys.stderr)
        return 2
    if a.all:
        a.select = a.capture = a.variants = a.acceptance = a.run = \
            a.random = a.plants = a.report = True
    if a.select:
        save('select.json', select())
    if a.capture:
        capture(a.jobs)
    if a.variants:
        make_variants(a.jobs)
    if a.acceptance:
        make_acceptance(a.traces, a.jobs)
    if a.acceptance_final:
        make_acceptance_final(a.traces, a.jobs)
    if a.run_final:
        build()
        check_final(a.obj, a.jobs)
    if a.run:
        build()
        save('run.json', check_cases(a.obj, a.jobs, a.limit))
    if a.random:
        r = random_check(a.count)
        print('a1Shr7: %d inputs, %d different' % (r['inputs'],
                                                     r['different']))
        save('random.json', r)
    if a.plants:
        save('plants.json', [plant_check(n, a.jobs) for n in PLANTS])
    if a.report:
        rep = report(load('run.json') or [], load('random.json'),
                     load('plants.json'), a.obj)
        save('report.json', rep)
        print('report: %d failures, %d stray writes, %d B of %d' % (
            rep['failures'], rep['stray_writes'],
            rep['sizes']['native_bytes'], BUDGET['native']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
