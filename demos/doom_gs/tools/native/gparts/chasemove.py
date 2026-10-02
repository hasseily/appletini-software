#!/usr/bin/env python3
"""Part chasemove's checkpoint (milestone 10, docs/GAME.md 2.4 row
chasemove, 3.5; docs/game-parts/chasemove.md): routine mode on pMove and
newChaseDir (P_NewChaseDir's work) as A_Chase calls them, the random checks
of the part's arithmetic helpers, and its planted bugs.

Usage:  python3 tools/native/gparts/chasemove.py --survey
        python3 tools/native/gparts/chasemove.py --capture [--jobs 2]
        python3 tools/native/gparts/chasemove.py --check [--jobs 2]
                [--sample K] [--keys KEY,...]
        python3 tools/native/gparts/chasemove.py --random [--count N]
        python3 tools/native/gparts/chasemove.py --plants [--keys NAME,...]
        python3 tools/native/gparts/chasemove.py --eligible
        python3 tools/native/gparts/chasemove.py --report

Everything it writes is under build/native/game/chasemove/ (the part's own
directory): its own survey of newChaseDir (survey/RUN.json.z), the cases
(cases/RUN/ROUTINE/hNNNNNNNN.case.z, each run's base.ram.z:
tools/native/gamecap.py with its case directory pointed here), the
candidates' paths (paths.json), report.json. The shared outputs are read
only.

The checks are lean (the owner's request of 2026-10-02): at most CHOSEN
(40) calls an entry, chosen to take as many paths as the candidates take
(a greedy cover of the paths, then spread evenly), from the $A5 machine
only, under f121 and fastpath.

--survey: newChaseDir is a helper that A_Chase calls with a jsr (upstream's
public P_NewChaseDir is never called in the release), so the shared survey
does not log it: one ref816 pass a run (demo3, DEMO1, DEMO2) logs it with
G_Ticker's gametic and the dispatch targets it can reach (gamecap's Survey,
passes, survey_options), into the part's own survey/.

--capture: the candidates. pMove (the shared survey: A_Chase's own calls
and tryWalk's): evenly over demo3, DEMO1 and DEMO2, and, for each run and dispatch
target, REACHED (12) of the eligible calls that reached it (a line handler
of P_UseSpecialLine or P_CrossSpecialLine), spread. newChaseDir (the part's survey): evenly over the three
runs, and, for each run and dispatch target, REACHED (12) of the calls that
reached it, spread (DEMO2's drop-offs reach PIT_AvoidDropoff). Each candidate's path comes
from the reference alone (path_of).

--check: the chosen calls on the part's image (make -f game.mk part
P=chasemove CM_TEST=1) with part checkpos's run machinery (checkpos.Prep,
run_one, outputs): the canonical state after the call equal to ref816's
(gcanon's routine mode, R1-R7), every declared output of
src/native/game/chasemove/args.json equal, no stray write. A call that
reaches a routine of a part not in the image stops at its FCALL or DCALL
(GS_UNBUILT, GS_UNBUILTD): it is "waiting", never counted equal.

--random: umul16x, mulSpeed and times32 (GAME.md 2.4 "Arithmetic") on
COUNT inputs each (0, +-1, the extremes, then random), upstream's helper
(mathref batch on a captured pMove call's machine) against the native
(cmtest.s cm_bulk).

--plants: each planted bug built from a scratch copy of the part's sources
in a temporary directory (deleted), run on its check (the chosen
newChaseDir calls, $A5, f121), which must fail.
"""

import argparse
import json
import os
import random
import shutil
import struct
import sys
import tempfile
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE))

import checkpos as CP  # noqa: E402  (wave 3's run machinery)
import secfind as SF  # noqa: E402
from native import gamecap as GC, glayout as GL, grun as G  # noqa: E402

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'chasemove'
OUT = GL.GAME / PART
CASES = OUT / 'cases'
SURVEY = OUT / 'survey'
PATHS_FILE = OUT / 'paths.json'
REPORT = OUT / 'report.json'
ARGS = SRC / 'game' / PART / 'args.json'
PART_SRC = SRC / 'game' / PART
SOURCES = ('part.mk', 'chasemove.inc', 'pmove.s', 'chasedir.s',
           'dropoff.s', 'cmtest.s')
GAME_SOURCES = ('pmove.s', 'chasedir.s', 'dropoff.s')
IMAGE = 'ptest'
GC.CASES = CASES                # the part's own case directory

PMOVE = 'p_enemy65.s:pMove'
NCD = 'p_enemy65.s:newChaseDir'
ENTRIES = (PMOVE, NCD)
SURVEY_RUNS = ('demo3', 'demo1', 'demo2')
CHOSEN = 40                     # the lean checks: calls an entry
FILLS = (0xA5,)                 # the lean checks: one machine
PROFILES = SF.PROFILES
EVEN = {PMOVE: (('demo3', 60), ('demo1', 40), ('demo2', 20)),
        NCD: (('demo3', 60), ('demo1', 40), ('demo2', 20))}
REACHED = 12                    # candidates of each (run, dispatch target)
DI_NODIR = 8


class PartError(Exception):
    pass


def say(text: str) -> None:
    print(text, flush=True)


def missing() -> Optional[str]:
    """Why the checkpoint cannot run (None: it can)."""
    return SF.missing()


def build(game: Optional[Path] = None, source: Path = SRC) -> Path:
    """The part's test image (make -f game.mk part P=chasemove CM_TEST=1:
    cmtest.s in the driver's area); its directory."""
    variables = ['P=%s' % PART, 'CM_TEST=1']
    if game is not None:
        variables.append('GAME=%s' % game)
    G.make('part', variables, source)
    return (game or GL.GAME) / PART


def args() -> Dict[str, Dict[str, Any]]:
    d = json.loads(ARGS.read_text())
    if d.get('format') != CP.GR.ARGS_FORMAT:
        raise PartError('%s is not %s' % (ARGS, CP.GR.ARGS_FORMAT))
    return d['entries']


# ---------------------------------------------------------------------------
# The part's own survey of newChaseDir (the shared survey logs the part
# table's routines, and newChaseDir is a helper)
# ---------------------------------------------------------------------------

def survey_path(run: str) -> Path:
    return SURVEY / (run + '.json.z')


def own_survey(run: str) -> Optional[Dict[str, Any]]:
    p = survey_path(run)
    return GC.load_survey(p) if p.exists() else None


def survey(run: str) -> Dict[str, Any]:
    """newChaseDir's calls in one run: one ref816 pass (gamecap's
    machinery) logging G_Ticker's gametic, newChaseDir (entry and return)
    and the dispatch targets it can reach (entry only)."""
    from ref816 import calls as CL
    table = CL.Linkmap()
    targets = GC._addressable(GC.survey_targets(), table)
    plan = GC.passes([NCD], targets)
    if len(plan) != 1:
        raise PartError('newChaseDir needs %d passes' % len(plan))
    es, ts = plan[0]
    sv = GC.Survey(es, ts, GC.CallerMap())
    start = time.time()
    GC.check_disk()
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-chasemove-survey-',
                                 dir=str(BUILD)))
    try:
        fifo = work / 'calls.fifo'
        os.mkfifo(str(fifo))
        r = GC.machine(run, work, GC.survey_options(fifo, es, ts),
                       reader=sv.read, fifo=fifo)
        if r['problems']:
            raise PartError('%s: %s' % (run, '; '.join(r['problems'])))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    res = sv.result(run)
    res['seconds'] = round(time.time() - start, 1)
    SURVEY.mkdir(parents=True, exist_ok=True)
    survey_path(run).write_bytes(zlib.compress(json.dumps(
        res, separators=(',', ':')).encode(), 6))
    return res


def survey_of(key: str, run: str) -> Optional[Dict[str, Any]]:
    """The survey that logs key in run: the part's own for newChaseDir,
    the shared one for the others."""
    return own_survey(run) if key == NCD else GC.survey_of(run)


# ---------------------------------------------------------------------------
# The calls: eligibility (GAME.md 3.5 step 6), candidates, captures
# ---------------------------------------------------------------------------

def eligible_calls(key: str, runs: Sequence[str] = SURVEY_RUNS
                   ) -> Tuple[List[Tuple[str, int, int]], Dict[str, int]]:
    """The eligible calls of an entry over the runs, (run, hit, tic), and
    the waiting ones by the target they wait for."""
    ok_parts = set(GL.built_set(extra=[PART]))
    out: List[Tuple[str, int, int]] = []
    waiting: Dict[str, int] = {}
    for run in runs:
        sv = survey_of(key, run)
        r = sv['routines'].get(key) if sv else None
        if not r:
            continue
        targets = sv['targets']
        reached = r['reached'] if isinstance(r['reached'], dict) else {}
        for hit in range(1, r['calls'] + 1):
            miss = [targets[i] for i in reached.get(str(hit), [])
                    if GL.owner_of(targets[i]) not in ('core',) and
                    GL.owner_of(targets[i]) not in ok_parts]
            for m in miss:
                waiting[m] = waiting.get(m, 0) + 1
            if not miss:
                out.append((run, hit, r['tic'][hit - 1]))
    return out, waiting


def candidates(key: str) -> Dict[str, List[Tuple[int, int]]]:
    """run -> [(hit, tic)] of the entry's candidates (the module's
    text)."""
    out: Dict[str, Dict[int, int]] = {}
    for run, n in EVEN[key]:
        for _, hit, tic in CP.spread(eligible_calls(key, (run,))[0], n):
            out.setdefault(run, {})[hit] = tic
    for run in SURVEY_RUNS:                 # the calls that reached a
        sv = survey_of(key, run)            #   dispatch target: REACHED
        if not sv or key not in sv['routines']:     # of each (run, target)
            continue
        reached = sv['routines'][key]['reached']
        by: Dict[str, List[Tuple[int, int]]] = {}
        for _, hit, tic in eligible_calls(key, (run,))[0]:
            for i in reached.get(str(hit), []):
                by.setdefault(sv['targets'][i], []).append((hit, tic))
        for calls in by.values():
            for hit, tic in CP.spread(calls, REACHED):
                out.setdefault(run, {})[hit] = tic
    return {r: sorted(d.items()) for r, d in out.items()}


def case_path(run: str, key: str, hit: int) -> Path:
    return GC.case_dir(run, key) / ('h%08d.case.z' % hit)


def capture(keys: Sequence[str] = ENTRIES, batch: int = CP.BATCH) -> int:
    made = 0
    for key in keys:
        for run, calls in sorted(candidates(key).items()):
            todo = [h for h, _ in calls
                    if not case_path(run, key, h).exists()]
            if not todo:
                continue
            tics = survey_of(key, run)['routines'][key]['tic']
            start = time.time()
            got = GC.capture(run, key, todo, tics, batch=batch, say=say)
            made += len(got)
            say('%s %s: %d cases (%.0f s)' % (run, key, len(got),
                                              time.time() - start))
    return made


def captured(key: str) -> List[Tuple[str, int, Path]]:
    out = []
    for run, calls in sorted(candidates(key).items()):
        for hit, _ in calls:
            p = case_path(run, key, hit)
            if p.exists():
                out.append((run, hit, p))
    return out


# ---------------------------------------------------------------------------
# A call's path, from the reference's memory alone (the coverage, GAME.md
# 3.5 step 2)
# ---------------------------------------------------------------------------

def sym(name: str) -> int:
    return CP.sym(name)


def _s32(b: bytes) -> int:
    return int.from_bytes(b, 'little', signed=True)


def actor_of(case: GC.Case) -> int:
    """upstream's AP (_Dp+8) at the call: the actor's address."""
    t = CP.table()
    dp = (case.regs_in['d'] + t.address('_Dp') - t.direct_page) & 0xFFFF
    return int.from_bytes(case.entry.read(dp + 8, 3), 'little')


def reached_of(case: GC.Case) -> List[str]:
    run, hit = case.header.get('run'), case.header.get('hit')
    sv = survey_of(case.key, run) if run and hit else None
    if not sv or case.key not in sv['routines']:
        return []
    r = sv['routines'][case.key]['reached']
    return [sv['targets'][i] for i in r.get(str(hit), [])]


def directions(dx: int, dy: int, olddir: int) -> Dict[str, int]:
    """upstream's doNewChaseDir's choices before its walks: xdir, ydir,
    turnaround, the diagonal (DI_NODIR when it is not tried)."""
    turn = DI_NODIR if olddir == DI_NODIR else olddir ^ 4
    xdir = 0 if dx > 10 << 16 else 4 if dx < -(10 << 16) else DI_NODIR
    ydir = 6 if dy < -(10 << 16) else 2 if dy > 10 << 16 else DI_NODIR
    diag = DI_NODIR
    if xdir != DI_NODIR and ydir != DI_NODIR:
        if dy < 0:
            diag = 7 if dx > 0 else 5
        else:
            diag = 1 if dx > 0 else 3
    return {'xdir': xdir, 'ydir': ydir, 'turn': turn, 'diag': diag}


def path_of(case: GC.Case) -> List[str]:
    """The paths a call took."""
    uc = SF.uconst()
    e, a = case.entry, case.after
    ap = actor_of(case)

    def field(m, off: int, n: int = 4) -> bytes:
        return m.read(ap + off, n)
    prnd = sym('m_random65.s:prndindex')
    rnd = (a.read(prnd, 1)[0] - e.read(prnd, 1)[0]) & 0xFF
    out = ['rnd-%d' % rnd]
    out += ['reached-' + n.split(':')[-1] for n in reached_of(case)]
    movedir = field(e, uc['UO_MO_MOVEDIR'], 1)[0]
    after_dir = field(a, uc['UO_MO_MOVEDIR'], 1)[0]
    nspec = int.from_bytes(a.read(sym('_g_numspechit'), 2), 'little')
    if case.key == PMOVE:
        if movedir == DI_NODIR:
            return out + ['nodir']
        out.append('diagonal' if movedir & 1 else 'axis')
        moved = case.regs_out['a'] & 0xFF
        if after_dir == DI_NODIR:
            out += ['blocked-specials', 'opened' if moved else 'none-opened']
        elif moved:
            out.append('moved')
            if nspec == 0xFFFF:
                out.append('crossed')
        else:
            out.append('blocked')
        return out
    # newChaseDir
    flags = int.from_bytes(field(e, uc['UO_MO_FLAGS']), 'little')
    floorz = _s32(field(e, uc['UO_MO_FLOORZ']))
    dropz = _s32(field(e, uc['UO_MO_DROPOFFZ']))
    z = _s32(field(e, uc['UO_MO_Z']))
    tall = floorz - dropz > 24 << 16 and z <= floorz and \
        not flags & uc['UC_MF_DROPOFF']
    ddx = _s32(a.read(sym('p_enemy65.s:EN_DDX'), 4))
    ddy = _s32(a.read(sym('p_enemy65.s:EN_DDY'), 4))
    if tall:
        out.append('dropoff-test')
    if tall and (ddx or ddy):
        out.append('dropoff-away')
        dx, dy = ddx, ddy
    else:
        tgt = int.from_bytes(field(e, uc['UO_MO_TARGET'], 3), 'little')
        dx = _s32(e.read(tgt + uc['UO_MO_X'], 4)) - _s32(
            field(e, uc['UO_MO_X']))
        dy = _s32(e.read(tgt + uc['UO_MO_Y'], 4)) - _s32(
            field(e, uc['UO_MO_Y']))
    d = directions(dx, dy, movedir)
    out.append('olddir-none' if movedir == DI_NODIR else 'olddir')
    if d['xdir'] == DI_NODIR:
        out.append('x-none')
    if d['ydir'] == DI_NODIR:
        out.append('y-none')
    if d['diag'] != DI_NODIR and d['diag'] == d['turn']:
        out.append('diag-is-turnaround')
    if after_dir == DI_NODIR:
        out.append('stuck')
    elif d['diag'] != DI_NODIR and after_dir == d['diag'] and rnd == 1:
        out.append('took-diagonal')
    elif after_dir in (d['xdir'], d['ydir']) and rnd == 2:
        out.append('took-straight')
    elif after_dir == movedir and rnd == 2:
        out.append('took-olddir')
    elif after_dir == d['turn']:
        out.append('took-turnaround')
    else:
        out.append('took-search')
    return out


def _path_job(item: Tuple[str, str]) -> Tuple[str, List[str]]:
    key, path = item
    try:
        return path, path_of(GC.load_case(Path(path)))
    except Exception as error:      # reported, never hidden
        return path, ['error: %s: %s' % (type(error).__name__, error)]


def paths(jobs: int = 2) -> Dict[str, Dict[str, List[str]]]:
    """key -> case path -> its paths (kept in paths.json)."""
    old = json.loads(PATHS_FILE.read_text()) if PATHS_FILE.exists() else {}
    out: Dict[str, Dict[str, List[str]]] = {}
    new = False
    for key in ENTRIES:
        have = old.get(key, {})
        todo = [(key, str(p)) for _, _, p in captured(key)
                if str(p) not in have]
        got = dict(have)
        new = new or bool(todo)
        if todo:
            if jobs <= 1:
                got.update(map(_path_job, todo))
            else:
                with ProcessPoolExecutor(max_workers=jobs) as pool:
                    got.update(pool.map(_path_job, todo))
        out[key] = got
    if new or not PATHS_FILE.exists():
        PATHS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PATHS_FILE.write_text(json.dumps(out, indent=1, sort_keys=True) +
                              '\n')
    return out


def selection(key: str, ps: Optional[Dict[str, Dict[str, List[str]]]] = None,
              n: int = CHOSEN) -> List[str]:
    """CHOSEN cases of the entry: a greedy cover of the candidates' paths,
    then spread evenly over the rest (checkpos.selection)."""
    ps = ps if ps is not None else paths()
    return CP.selection(key, ps, n)


# ---------------------------------------------------------------------------
# The runs
# ---------------------------------------------------------------------------

def _check_job(job) -> List[Dict[str, Any]]:
    items, obj, fills, profiles, ps = job
    GC.CASES = CASES
    nat = SF.Native(Path(obj))
    CP.Prep.nat = nat
    spec_all = args()
    out: List[Dict[str, Any]] = []
    for key, item in items:
        name = '/'.join(Path(item).parts[-3:])
        try:
            case = GC.load_case(Path(item))
            prep = CP.Prep(case, key, spec_all[key])
        except Exception as error:      # reported per case, never hidden
            out.append({'case': name, 'entry': key, 'ok': False,
                        'error': '%s: %s' % (type(error).__name__, error)})
            continue
        for fill in fills:
            for profile in profiles:
                try:
                    r = CP.run_one(prep, nat, fill, profile)
                except Exception as error:
                    r = {'entry': key, 'fill': '%02x' % fill,
                         'profile': profile, 'ok': False,
                         'error': '%s: %s' % (type(error).__name__, error)}
                r.update(case=name, path=ps.get(key, {}).get(item, []))
                out.append(r)
    return out


def check_jobs(keys: Sequence[str] = ENTRIES, sample: int = 1,
               obj: Path = OUT, fills: Sequence[int] = FILLS,
               profiles: Sequence[str] = PROFILES, chunk: int = 6
               ) -> List[Tuple]:
    ps = paths()
    jobs: List[Tuple] = []
    for key in keys:
        chosen = selection(key, ps)[::sample]
        for i in range(0, len(chosen), chunk):
            jobs.append(([(key, p) for p in chosen[i:i + chunk]], str(obj),
                         tuple(fills), tuple(profiles), ps))
    return jobs


def run_jobs(jobs: List[Tuple], workers: int = 2) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if workers <= 1:
        for j in jobs:
            out += _check_job(j)
        return out
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for got in pool.map(_check_job, jobs):
            out += got
    return out


def summarize(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in ENTRIES:
        rs = [r for r in results if r.get('entry') == key]
        if not rs:
            continue
        waiting = [r for r in rs if r.get('waiting')]
        run = [r for r in rs if not r.get('waiting')]
        bad = [r for r in run if not r.get('ok')]
        paths_: Set[str] = set()
        for r in run:
            paths_.update(r.get('path', []))
        ls = [r['lowest_s']['s'] for r in run
              if isinstance(r.get('lowest_s'), dict)]
        elig, wait = eligible_calls(key)
        out[key] = {
            'eligible_calls': len(elig), 'waiting_calls': wait,
            'candidates': len(captured(key)),
            'cases_chosen': len({r['case'] for r in rs}),
            'cases_run': len({r['case'] for r in run}),
            'cases_waiting': sorted({r['case'] for r in waiting}),
            'runs': len(run), 'failures': len(bad),
            'stray_writes': sum(r.get('stray') or 0 for r in run),
            'cycles': {p: CP._stats([r['cycles'] for r in run
                                     if r.get('profile') == p and
                                     r.get('cycles')]) for p in PROFILES},
            'lowest_s': min(ls) if ls else None,
            'paths': sorted(paths_),
            'first_failures': [{k: r.get(k) for k in (
                'case', 'fill', 'profile', 'diff', 'error', 'ended', 'stop')}
                for r in bad[:4]]}
    return out


# ---------------------------------------------------------------------------
# The random checks (GAME.md 2.4 "Arithmetic"): umul16x, mulSpeed, times32
# ---------------------------------------------------------------------------

BULK_IN, BULK_OUT = 93, 94
BULK_ROOM = 0xC000 - 0x0200
REC = 12
HELPERS = ('umul16x', 'mulSpeed', 'times32')
EDGES32 = (0, 1, -1, 2, -2, 0x7FFFFFFF, -0x80000000, -0x7FFFFFFF, 0xFFFF,
           0x10000, -0x10000, 0x8000, -0x8000, 0x7FFF, 0x07FFFFFF,
           0x08000000, -0x08000000, 0xFFFFFFF)
EDGES16 = (0, 1, 2, 31, 32, 0x7FFF, 0x8000, 0xFFFF, 0xFFFE, 47000, 8, 10)


def s32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def random_missing() -> Optional[str]:
    """Why the random checks cannot run (None: they can)."""
    import sight as SG
    if not SG.MATHREF.exists():
        return 'no mathref (milestone 6: make -C src/native -f math.mk)'
    return None


def random_inputs(helper: str, n: int, seed: int = 1
                  ) -> List[Tuple[int, int, int]]:
    """(w0, w1, k) by helper: umul16x (a, b, -), mulSpeed (speed,
    coordinate, the speeds index), times32 (v, -, -)."""
    rnd = random.Random('%s-%d' % (helper, seed))
    out: List[Tuple[int, int, int]] = []
    if helper == 'umul16x':
        for a in EDGES16:
            for b in EDGES16:
                out.append((a, b, 0))
        while len(out) < n:
            k = len(out) % 3
            a = rnd.randint(0, 0xFFFF) if k else rnd.randint(0, 64)
            out.append((a, rnd.choice((47000, rnd.randint(0, 0xFFFF))), 0))
    elif helper == 'mulSpeed':
        for v in EDGES32:
            for i in (0, 1, 3, 4, 9, 10, 14):
                out.append((v, rnd.choice(EDGES32), i))
        while len(out) < n:
            k = len(out) % 3
            speed = rnd.randint(-0x80000000, 0x7FFFFFFF) if k == 0 else \
                rnd.randint(0x10000, 0x7FFFFF) if k == 1 else \
                rnd.randint(0, 0xFFFF)
            out.append((s32(speed), rnd.randint(-0x80000000, 0x7FFFFFFF),
                        rnd.randint(0, 15)))
    else:
        out = [(v, 0, 0) for v in EDGES32]
        while len(out) < n:
            k = len(out) % 3
            v = rnd.randint(-0x80000000, 0x7FFFFFFF) if k == 0 else \
                rnd.randint(-0x10000, 0x10000) if k == 1 else \
                rnd.choice((1, -1)) * (1 << rnd.randint(0, 30))
            out.append((s32(v), 0, 0))
    return out[:n]


def native_bulk(b, mode: int, recs: Sequence[Tuple[int, int, int]]
                ) -> List[int]:
    """cm_bulk on the records: the native results (unsigned 32 bits)."""
    per = min(BULK_ROOM // REC, 0xFFFF)
    out: List[int] = []
    for start in range(0, len(recs), per):
        chunk = recs[start:start + per]
        img = G.Image(b, 0xA5, store=False)
        img.aux(BULK_IN, 0x0200, b''.join(
            struct.pack('<IIB3x', w0 & 0xFFFFFFFF, w1 & 0xFFFFFFFF, k)
            for w0, w1, k in chunk))
        work = Path(tempfile.mkdtemp(prefix='tmp-m10-chasemove-bulk-',
                                     dir=str(BUILD)))
        try:
            k = len(chunk)
            r = G.run(img, work, GL.MODES['ROUTINE'], 'cm_bulk',
                      regs=(mode, k & 0xFF, k >> 8, 0x34), banks=[BULK_OUT])
            if r.ended() != 'halt':
                raise PartError('cm_bulk ended %s' % r.ended())
            m = G.load_snapshot(work / 'done.img')
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        data = bytes(m.aux[BULK_OUT][0x0200:0x0200 + 4 * len(chunk)])
        out += [struct.unpack('<I', data[i:i + 4])[0]
                for i in range(0, len(data), 4)]
    return out


def ref_case() -> GC.Case:
    """A captured pMove call: its RAM is upstream's machine for the
    helpers, its registers (D, DBR) theirs at the call."""
    got = captured(PMOVE)
    if not got:
        raise PartError('no pMove case (python3 tools/native/gparts/'
                        'chasemove.py --capture)')
    return GC.load_case(got[0][2])


def mathref(case: GC.Case, name: str, pc: int, items_in: Sequence[str],
            items_out: Sequence[str], records: bytes, out_size: int,
            ret: int = 2) -> List[bytes]:
    """Upstream's routine at pc on each input record (mathref batch, as
    part sight's mathref, with the return's size: 2 for a jsr helper, 3
    for a jsl one): the outputs (out_size bytes each)."""
    import subprocess
    import sight as SG
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-chasemove-ref-',
                                 dir=str(BUILD)))
    try:
        (work / 'base.ram').write_bytes(SG.ram_of(case))
        (work / 'entry').write_text(SG.entry_text(case, pc, ret))
        spec = ['routine %s %06X' % (name, pc)] + \
            ['in %s' % x for x in items_in] + \
            ['out %s' % x for x in items_out]
        (work / 'spec').write_text('\n'.join(spec) + '\n')
        (work / 'cases').write_bytes(records)
        r = SG.bounded.run([str(SG.MATHREF), 'batch', str(work / 'base.ram'),
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


def upstream_bulk(case: GC.Case, helper: str,
                  recs: Sequence[Tuple[int, int, int]]) -> List[int]:
    """Upstream's helper on each record (mathref batch on the case's
    machine): umul16x (jsl: A, X in, A, X out); mulSpeed (jsr: Y the
    coordinate's offset, X 0 or 32, EN_T the direction * 4, the actor's
    coordinate and its type's speed in memory; A, X out); times32 (jsr: A,
    X in, EN_D out)."""
    from ref816 import calls as CL
    t = CL.Linkmap()
    uc = SF.uconst()
    pc = t.address('p_enemy65.s:' + helper)
    if helper == 'umul16x':
        data = b''.join(struct.pack('<HH', a, b) for a, b, _ in recs)
        got = mathref(case, helper, pc, ['a', 'x'], ['a', 'x'], data, 4, 3)
        return [struct.unpack('<HH', g)[0] | struct.unpack('<HH', g)[1] << 16
                for g in got]
    if helper == 'times32':
        data = b''.join(struct.pack('<HH', w & 0xFFFF, (w >> 16) & 0xFFFF)
                        for w, _, _ in recs)
        en_d = t.address('p_enemy65.s:EN_D')
        got = mathref(case, helper, pc, ['a', 'x'], ['%06X 4' % en_d],
                      data, 4)
        return [struct.unpack('<I', g)[0] for g in got]
    # mulSpeed: the actor (AP) and its type's mobjinfo record at the call
    ap = actor_of(case)
    mtype = case.entry.read(ap + uc['UO_MO_TYPE'], 1)[0]
    dbr = case.regs_in['dbr']
    info = (dbr << 16) | ((t.address('mobjinfo') + 64 * mtype +
                           uc['UO_MI_SPEED']) & 0xFFFF)
    en_t = t.address('p_enemy65.s:EN_T')
    ox, oy = uc['UO_MO_X'], uc['UO_MO_Y']
    items = ['y', 'x', '%06X 2' % en_t, '%06X 4' % (ap + ox),
             '%06X 4' % (ap + oy), '%06X 4' % info]
    data = bytearray()
    for speed, coord, k in recs:
        data += struct.pack('<HHHIII', ox if k < 8 else oy,
                            0 if k < 8 else 32, 4 * (k & 7),
                            coord & 0xFFFFFFFF, coord & 0xFFFFFFFF,
                            speed & 0xFFFFFFFF)
    got = mathref(case, helper, pc, items, ['a', 'x'], bytes(data), 4)
    return [struct.unpack('<HH', g)[0] | struct.unpack('<HH', g)[1] << 16
            for g in got]


def model(helper: str, w0: int, w1: int, k: int) -> int:
    """The helper's arithmetic, for the report: a * b; coordinate + speed
    * speeds[k]; v << 5 (modulo 2^32)."""
    if helper == 'umul16x':
        return (w0 & 0xFFFF) * (w1 & 0xFFFF)
    if helper == 'times32':
        return (w0 << 5) & 0xFFFFFFFF
    cls = (2, 1, 0, 3, 4, 3, 0, 1, 0, 1, 2, 1, 0, 3, 4, 3)[k]
    val = (0, 47000, 0x10000, -47000, -0x10000)[cls]
    return (w1 + w0 * val) & 0xFFFFFFFF


def random_check(n: int = 100_000, seed: int = 1, obj: Path = OUT,
                 helpers: Sequence[str] = HELPERS) -> Dict[str, Any]:
    case = ref_case()
    b = G.load_build(obj, IMAGE)
    out: Dict[str, Any] = {}
    for mode, helper in enumerate(HELPERS):
        if helper not in helpers:
            continue
        recs = random_inputs(helper, n, seed)
        ups = upstream_bulk(case, helper, recs)
        nat = native_bulk(b, mode, recs)
        bad = [(r, u, m_) for r, u, m_ in zip(recs, ups, nat) if u != m_]
        agree = sum(1 for r, u in zip(recs, ups) if u == model(helper, *r))
        out[helper] = {'inputs': len(recs),
                       'compared': min(len(ups), len(nat)),
                       'different': len(bad) + abs(len(ups) - len(nat)),
                       'first': bad[:5], 'upstream_is_the_model': agree,
                       'seed': seed}
        say('%-9s %d inputs, %d different (upstream = the model on %d)' % (
            helper, len(recs), out[helper]['different'], agree))
    return out


# ---------------------------------------------------------------------------
# The planted bugs (lean: the three of the row, the most likely mistakes),
# each in a scratch copy of the part's sources, run on newChaseDir's check
# ---------------------------------------------------------------------------

PLANT_EDITS: Dict[str, Tuple[str, List[Tuple[str, str]]]] = {
    # P_Random taken before the direct test (the diagonal) instead of after
    # it: the swap's random number one call early
    'random-before-direct': ('chasedir.s', [(
        '''        ; the direct route: the diagonal
        lda CM_XDIR''',
        '''        ; the direct route: the diagonal
        jsr g_random                    ; (planted: P_Random first)
        sta CM_TDIR
        lda CM_XDIR'''), (
        '''@other: jsr g_random                    ; P_Random() > 200 || |deltay| >''',
        '''@other: lda CM_TDIR                     ; (planted) P_Random() > 200 || |deltay| >''')]),
    # the turnaround table: the opposite direction a quarter turn off
    'turnaround-table': ('chasedir.s', [(
        '''        beq :+
        eor #4
:       sta CM_TURN''',
        '''        beq :+
        eor #2                          ; (planted: not the opposite)
:       sta CM_TURN''')]),
    # the diagonal tried after the straight ones (before the old direction)
    'diagonal-after-straight': ('chasedir.s', [(
        '''        ; the direct route: the diagonal
        lda CM_XDIR''',
        '''        ; the direct route: the diagonal
        lda #UC_DI_NODIR                ; (planted: the diagonal later)
        sta CM_TDIR
        lda CM_XDIR'''), (
        '''@diag:  txa                             ; movedir = the diagonal; walked''',
        '''@diag:  stx CM_TDIR                     ; (planted: kept for later)
        bra @other
        txa                             ; movedir = the diagonal; walked'''), (
        '''@old:   lda CM_OLD                      ; the old direction''',
        '''@old:   lda CM_TDIR                     ; (planted: the diagonal here)
        cmp #UC_DI_NODIR
        beq @old2
        cmp CM_TURN
        beq @old2
        jsr cm_setdir
        jsr cm_try
        jne @ret
@old2:  lda CM_OLD                      ; the old direction''')]),
}
PLANT_NAMES = tuple(PLANT_EDITS)


def plant_build(name: str, tmp: Path) -> Path:
    """The part's image with the planted bug `name`, from a scratch copy of
    its sources in tmp (game.mk and its includes, the parts' fragments,
    this part's sources; the rest from the tree through game.mk's vpath):
    the image's directory."""
    src = tmp / 'src'
    files = list(G.PLANT_COPY) + ['game/%s/%s' % (PART, f) for f in SOURCES]
    for f in files:
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(SRC / f), str(src / f))
    fname, edits = PLANT_EDITS[name]
    target = src / 'game' / PART / fname
    text = target.read_text()
    for old, new in edits:
        if text.count(old) != 1:
            raise PartError('the planted bug %s no longer applies: %r' % (
                name, old[:60]))
        text = text.replace(old, new)
    target.write_text(text)
    return build(game=tmp / 'game', source=src)


def plants(names: Optional[Sequence[str]] = None, sample: int = 1,
           workers: int = 2) -> Dict[str, Any]:
    out = {}
    for name in (names or PLANT_NAMES):
        tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-chasemove-plant-',
                                    dir=str(BUILD)))
        try:
            obj = plant_build(name, tmp)
            res = run_jobs(check_jobs(obj=obj, sample=sample,
                                      profiles=(PROFILES[0],),
                                      keys=(NCD,)), workers)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
        run = [r for r in res if not r.get('waiting')]
        bad = [r for r in run if not r.get('ok')]
        out[name] = {'runs': len(run), 'failed': len(bad),
                     'caught': bool(bad),
                     'first': (bad[0].get('diff') or [bad[0].get('error') or
                                                     bad[0].get('ended')])[:2]
                     if bad else None}
        say('%-24s %s' % (name, 'caught: %d of %d runs fail, %s' % (
            len(bad), len(run), out[name]['first']) if bad else
            'NOT CAUGHT (%d runs)' % len(run)))
    return out


# ---------------------------------------------------------------------------
# Sizes (docs/GAME.md 4.7: the part's budget)
# ---------------------------------------------------------------------------

BUDGET = next(p['native'] for p in GL.PARTS if p['name'] == PART)
UPSTREAM_BYTES = next(p['up'] for p in GL.PARTS if p['name'] == PART)
LABELS = ('pMove', 'tryWalk', 'P_TryWalk', 'newChaseDir', 'doNewChaseDir',
          'P_NewChaseDir', 'avoidDropoff', 'PIT_AvoidDropoff')
MODULES = ('pmove', 'chasedir', 'dropoff')


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    """The part's bytes (its game modules: the test module cmtest in the
    driver's area left out) against its budget; each routine's bytes (its
    label to the next of the part's labels in its segment) and group."""
    b = G.load_build(obj, IMAGE)
    text = (obj / (IMAGE + '.map')).read_text()
    mods = text.split('Modules list:', 1)[1].split('Segment list:', 1)[0]
    module = None
    total = 0
    segs: List[Tuple[str, int]] = []
    for line in mods.splitlines():
        if line and not line.startswith(' ') and line.endswith('.o:'):
            module = Path(line[:-1]).stem
            continue
        f = line.split()
        if module in MODULES and f and f[0] in b.segments:
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            offs = next(int(x[5:], 16) for x in f if x.startswith('Offs='))
            total += size
            segs.append((f[0], b.segments[f[0]][0] + offs, size))
    nat = SF.Native(obj)
    routines: Dict[str, Any] = {}
    for seg, lo, size in segs:
        grp = 0 if seg == 'GCORE' else int(seg[4:]) if \
            seg.startswith('GGRP') else None
        at = sorted((b.labels[n], n) for n in LABELS
                    if n in b.labels and nat.group(n) == grp and
                    lo <= b.labels[n] < lo + size)
        for i, (a, n) in enumerate(at):
            end = at[i + 1][0] if i + 1 < len(at) else lo + size
            routines[n] = {'bytes': end - a, 'group': grp, 'segment': seg}
    return {'bytes': total, 'budget': BUDGET, 'upstream': UPSTREAM_BYTES,
            'over_10_percent': total > BUDGET * 1.1, 'routines': routines}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def write_report(results: Optional[Sequence[Dict[str, Any]]] = None,
                 **parts) -> Dict[str, Any]:
    rep: Dict[str, Any] = {}
    if REPORT.exists():
        rep = json.loads(REPORT.read_text())
    rep.update(format='game-part-report 1', part=PART,
               wave=next(p['wave'] for p in GL.PARTS if p['name'] == PART),
               exclusions=[n for n, _, _ in CP.gcanon.ROUTINE_EXCLUSIONS],
               fills=['%02x' % f for f in FILLS], profiles=list(PROFILES))
    if results is not None:
        rep['entries'] = summarize(results)
        run = [r for r in results if not r.get('waiting')]
        rep['runs'] = len(run)
        rep['waiting_runs'] = sum(1 for r in results if r.get('waiting'))
        rep['failures'] = sum(1 for r in run if not r.get('ok'))
        rep['stray_writes'] = sum(r.get('stray') or 0 for r in run)
        ls = [r['lowest_s']['s'] for r in run
              if isinstance(r.get('lowest_s'), dict)]
        rep['lowest_s'] = min(ls) if ls else None
    rep.update(parts)
    rep['build_kb'] = CP.du_kb(OUT)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(rep, indent=1, default=str) + '\n')
    return rep


def print_report(rep: Dict[str, Any]) -> None:
    CP.print_report(rep)
    for helper, r in rep.get('random', {}).items():
        say('random %-9s %s inputs, %s different' % (
            helper, r['inputs'], r['different']))


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--survey', action='store_true')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--random', action='store_true')
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--eligible', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--keys', default=None)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--sample', type=int, default=1)
    parser.add_argument('--count', type=int, default=100_000)
    parser.add_argument('--runs', default=','.join(SURVEY_RUNS))
    parser.add_argument('--json', type=Path)
    a = parser.parse_args(argv)
    why = missing()
    if why:
        print('cannot run: %s' % why, file=sys.stderr)
        return 2
    if a.survey:
        for run in a.runs.split(','):
            r = survey(run)
            say('%s: newChaseDir %d calls (%s s)' % (
                run, r['routines'][NCD]['calls'], r['seconds']))
        return 0
    if a.eligible:
        for key in ENTRIES:
            elig, waiting = eligible_calls(key)
            say('%-28s eligible %d, waiting %s' % (key, len(elig), waiting))
        return 0
    if a.capture:
        say('%d cases made' % capture())
        for key, ps in paths(a.jobs).items():
            count: Dict[str, int] = {}
            for v in ps.values():
                for x in v:
                    count[x] = count.get(x, 0) + 1
            say('%s: %d candidates, %s' % (key, len(ps), json.dumps(
                count, sort_keys=True)))
        return 0
    if a.check:
        start = time.time()
        build()
        keys = a.keys.split(',') if a.keys else ENTRIES
        res = run_jobs(check_jobs(keys=keys, sample=a.sample), a.jobs)
        rep = write_report(res, sizes=sizes(), check_seconds=round(
            time.time() - start), sample=a.sample)
        if a.json:
            a.json.write_text(json.dumps(res, indent=1, default=str) + '\n')
        print_report(rep)
        return 1 if rep['failures'] else 0
    if a.random:
        build()
        r = random_check(a.count)
        write_report(random=r)
        return 0 if all(x['different'] == 0 for x in r.values()) else 1
    if a.plants:
        r = plants(a.keys.split(',') if a.keys else None, workers=a.jobs)
        write_report(plants=r)
        return 0 if all(x['caught'] for x in r.values()) else 1
    if a.report:
        print_report(json.loads(REPORT.read_text()))
        return 0
    parser.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
