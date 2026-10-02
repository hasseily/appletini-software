#!/usr/bin/env python3
"""Part xymove's checkpoint (milestone 10, docs/GAME.md 2.4 row xymove,
3.5; docs/game-parts/xymove.md): routine mode on P_XYMovement and
slideMove (P_SlideMove, with PTR_SlideTraverse and hitSlideLine inside
it), the random checks of the part's arithmetic helpers (friction,
bestMul, labs) and its planted bugs.

Usage:  python3 tools/native/gparts/xymove.py --capture [--jobs 2]
        python3 tools/native/gparts/xymove.py --check [--jobs 2]
                [--sample K] [--keys KEY,...]
        python3 tools/native/gparts/xymove.py --random [--count N]
        python3 tools/native/gparts/xymove.py --plants [--keys NAME,...]
        python3 tools/native/gparts/xymove.py --eligible
        python3 tools/native/gparts/xymove.py --report

Everything it writes is under build/native/game/xymove/ (the part's own
directory): the cases (cases/RUN/ROUTINE/hNNNNNNNN.case.z and each run's
base.ram.z: tools/native/gamecap.py with its case directory pointed here),
the candidates' paths (paths.json), report.json. The shared outputs are
read only.

The checks are lean (the owner's request of 2026-10-02): at most CHOSEN
(40) calls an entry, chosen to take as many paths as the candidates take
(a greedy cover of the paths, then spread evenly), from the $A5 machine
only, under f121 (and fastpath with --profiles).

--capture: the candidates. P_XYMovement: evenly over demo3, DEMO1, DEMO2
and newgame; every call that reached a dispatch target other than the
slide's (a crossed line's handler, a weapon action); the calls that slid
(they reached PIT_AddLineIntercepts: slideMove's traces), spread; every
call of the tics where explode ran (a missile into a wall) or the tic after
a P_SpawnMissile (a missile in flight). slideMove: spread over its calls
in the four runs. Each candidate's paths come from the reference alone
(path_of): the mover's kind, the clamp and the half steps, the slide and
its line, the missile's end (exploded, removed into the sky), in the air,
the corpse that goes on, the stop (the player's S_PLAY), friction.

--check: the chosen calls on the part's image (make -f game.mk part
P=xymove XY_TEST=1) with part checkpos's run machinery (checkpos.Prep,
run_one): the canonical state after the call equal to ref816's (gcanon's
routine mode, R1-R7), every declared output of
src/native/game/xymove/args.json equal (none: upstream's MV_*, SL_*, HS_*
are its near scratch, R2), no stray write. A call that reaches a routine
of a part not in the image stops at its FCALL or DCALL: it is "waiting",
never counted equal.

--random: friction, bestMul and labs on random inputs (0, +-1, the
extremes, then random), upstream's helper by mathref batch on a captured
slideMove call's machine (AP the mobj: bestMul's momentum) against the
native one (xytest.s xy_bulk), compared.

--plants: each planted bug built from a scratch copy of the part's sources
in a temporary directory (deleted), run on its check (the chosen calls,
$A5, f121), which must fail.
"""

import argparse
import json
import random
import shutil
import struct
import sys
import tempfile
import time
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
PART = 'xymove'
OUT = GL.GAME / PART
CASES = OUT / 'cases'
PATHS_FILE = OUT / 'paths.json'
REPORT = OUT / 'report.json'
ARGS = SRC / 'game' / PART / 'args.json'
PART_SRC = SRC / 'game' / PART
SOURCES = ('part.mk', 'xymove.s', 'slide.s', 'xytest.s', 'xymove.inc')
IMAGE = 'ptest'
GC.CASES = CASES                # the part's own case directory

XYMOVE = 'p_mobj65.s:P_XYMovement'
SLIDE = 'p_mobj65.s:slideMove'
ENTRIES = (XYMOVE, SLIDE)
CHOSEN = 40                     # the lean checks: calls an entry
FILLS = (0xA5,)                 # the lean checks: one machine
PROFILES = SF.PROFILES
EVEN = {XYMOVE: (('demo3', 50), ('demo1', 50), ('demo2', 40),
                 ('newgame', 10)),
        SLIDE: (('demo3', 15), ('demo1', 30), ('demo2', 25),
                ('newgame', 5))}
SLIDES = (('demo3', 15), ('demo1', 20), ('demo2', 15))  # calls that slid
NOHIT = (('demo3', 4), ('demo1', 6))     # slid, nothing hit
MISSILE_TICS = {'demo3': 6, 'demo1': 8, 'demo2': 3}     # explode's tics
FLIGHT_TICS = {'demo3': 4, 'demo1': 6, 'demo2': 2}      # after a missile
TIC_CALLS = 10                  # P_XYMovement calls kept in each such tic
ADDLINE = 'p_trace65.s:PIT_AddLineIntercepts'
SLIDETRV = 'p_mobj65.s:PTR_SlideTraverse'


class PartError(Exception):
    pass


def say(text: str) -> None:
    print(text, flush=True)


def missing() -> Optional[str]:
    """Why the checkpoint cannot run (None: it can)."""
    return SF.missing()


def build(game: Optional[Path] = None, source: Path = SRC) -> Path:
    """The part's test image (make -f game.mk part P=xymove XY_TEST=1);
    its directory."""
    variables = ['P=%s' % PART, 'XY_TEST=1']
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
# The calls: eligibility (GAME.md 3.5 step 6), candidates, captures
# ---------------------------------------------------------------------------

def eligible_calls(key: str, runs: Sequence[str] = GC.RUNS
                   ) -> Tuple[List[Tuple[str, int, int]], Dict[str, int]]:
    """The eligible calls of an entry over the survey's runs, (run, hit,
    tic), and the waiting ones by the target they wait for."""
    ok_parts = set(GL.built_set(extra=[PART]))
    out: List[Tuple[str, int, int]] = []
    waiting: Dict[str, int] = {}
    for run in runs:
        sv = GC.survey_of(run)
        r = sv['routines'].get(key) if sv else None
        if not r:
            continue
        targets = sv['targets']
        reached = r['reached'] if isinstance(r['reached'], dict) else {}
        for hit in range(1, r['calls'] + 1):
            miss = [targets[i] for i in reached.get(str(hit), [])
                    if GL.owner_of(targets[i]) != 'core' and
                    GL.owner_of(targets[i]) not in ok_parts]
            for m in miss:
                waiting[m] = waiting.get(m, 0) + 1
            if not miss:
                out.append((run, hit, r['tic'][hit - 1]))
    return out, waiting


def _reached(run: str, key: str) -> Dict[int, List[str]]:
    sv = GC.survey_of(run)
    r = sv['routines'].get(key) if sv else None
    if not r or not isinstance(r['reached'], dict):
        return {}
    return {int(h): [sv['targets'][i] for i in v]
            for h, v in r['reached'].items()}


def _tics_of(run: str, key: str, n: int) -> List[int]:
    sv = GC.survey_of(run)
    if not sv or key not in sv['routines']:
        return []
    tics: List[int] = []
    for t in sv['routines'][key]['tic']:
        if t not in tics:
            tics.append(t)
    return CP.spread(tics, n)


def candidates(key: str) -> Dict[str, List[Tuple[int, int]]]:
    """run -> [(hit, tic)] of an entry's candidates (the module's text)."""
    out: Dict[str, Dict[int, int]] = {}
    for run, n in EVEN[key]:
        for _, hit, tic in CP.spread(eligible_calls(key, (run,))[0], n):
            out.setdefault(run, {})[hit] = tic
    if key != XYMOVE:
        return {r: sorted(d.items()) for r, d in out.items()}
    for table, pick in ((SLIDES, lambda t: SLIDETRV in t),
                        (NOHIT, lambda t: ADDLINE in t and
                         SLIDETRV not in t)):
        for run, n in table:
            reached = _reached(run, XYMOVE)
            calls = [c for c in eligible_calls(XYMOVE, (run,))[0]
                     if pick(reached.get(c[1], []))]
            for _, hit, tic in CP.spread(calls, n):
                out.setdefault(run, {})[hit] = tic
    for run in ('demo3', 'demo1', 'demo2', 'newgame'):  # other targets
        reached = _reached(run, XYMOVE)
        for _, hit, tic in eligible_calls(XYMOVE, (run,))[0]:
            if [t for t in reached.get(hit, []) if t not in
                    (ADDLINE, SLIDETRV)]:
                out.setdefault(run, {})[hit] = tic
    for key2, table, step in (('p_mobj65.s:explode', MISSILE_TICS, 0),
                              ('p_spawn65.s:P_SpawnMissile', FLIGHT_TICS,
                               1)):
        for run, ntics in table.items():
            tics = {t + step for t in _tics_of(run, key2, ntics)}
            calls = eligible_calls(XYMOVE, (run,))[0]
            for t in sorted(tics):
                for _, hit, tic in [c for c in calls
                                    if c[2] == t][:TIC_CALLS]:
                    out.setdefault(run, {})[hit] = tic
    return {r: sorted(d.items()) for r, d in out.items()}


def case_path(run: str, key: str, hit: int) -> Path:
    return GC.case_dir(run, key) / ('h%08d.case.z' % hit)


def capture(keys: Sequence[str] = ENTRIES, batch: int = CP.BATCH) -> int:
    made = 0
    for key in keys:
        for run, calls in sorted(candidates(key).items()):
            todo = [h for h, _ in calls if not case_path(run, key,
                                                         h).exists()]
            if not todo:
                continue
            sv = GC.survey_of(run)
            tics = sv['routines'][key]['tic']
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
# A call's paths, from the reference's memory alone (the coverage, GAME.md
# 3.5 step 2)
# ---------------------------------------------------------------------------

def sym(name: str) -> int:
    return CP.sym(name)


def _s32(b: bytes) -> int:
    return int.from_bytes(b, 'little', signed=True)


def _u24(m, at: int) -> int:
    return int.from_bytes(m.read(at, 3), 'little')


def mobj_of(case: GC.Case, name: str) -> int:
    """The mobj pointer in the direct page symbol name (_Dp, AP) at the
    call."""
    t = CP.table()
    dp = (case.regs_in['d'] + t.address(name) - t.direct_page) & 0xFFFF
    return _u24(case.entry, dp)


def reached_of(case: GC.Case) -> List[str]:
    """The dispatch targets the reference's call reached (the survey)."""
    run, hit = case.header.get('run'), case.header.get('hit')
    sv = GC.survey_of(run) if run and hit else None
    if not sv or case.key not in sv['routines']:
        return []
    r = sv['routines'][case.key]['reached']
    return [sv['targets'][i] for i in r.get(str(hit), [])]


def path_of(case: GC.Case) -> List[str]:
    """The paths a P_XYMovement or slideMove call took."""
    uc = SF.uconst()
    e, a = case.entry, case.after
    if case.key == SLIDE:
        return slide_path(case)
    mo = mobj_of(case, '_Dp')

    def f(m, name: str, n: int = 4) -> int:
        return _s32(m.read(mo + uc[name], n))
    flags = f(e, 'UO_MO_FLAGS') & 0xFFFFFFFF
    player = _u24(e, sym('_g_player') + uc['UO_PL_MO'])
    missile = bool(flags & (uc['UC_MF_MISSILE_HI'] << 16))
    out = ['player' if mo == player else 'missile' if missile else
           'corpse' if flags & (uc['UC_MF_CORPSE_HI'] << 16) else 'thing']
    mom = [f(e, 'UO_MO_MOMX'), f(e, 'UO_MO_MOMY')]
    if not any(mom):
        return out + ['no-momentum']
    if any(abs(v) > 30 << 16 for v in mom):
        out.append('clamp')
    if any(abs(max(-30 << 16, min(30 << 16, v))) > 15 << 16 for v in mom):
        out.append('half')
        if any(v < -(15 << 16) and v & 1 for v in mom):
            out.append('half-negative-odd')
    reached = reached_of(case)
    if SLIDETRV in reached:
        out.append('slide-hit')
    elif ADDLINE in reached:
        out.append('slide-nohit')
    out += ['reached-' + n.split(':')[-1] for n in reached
            if n not in (ADDLINE, SLIDETRV)]
    if a.read(mo + uc['UO_TH_FUNCTION'], 3) != \
            e.read(mo + uc['UO_TH_FUNCTION'], 3):
        return out + ['removed']
    if missile:
        if not f(a, 'UO_MO_FLAGS') & (uc['UC_MF_MISSILE_HI'] << 16):
            out.append('exploded')
        return out
    if f(a, 'UO_MO_X', 8) == f(e, 'UO_MO_X', 8):
        out.append('not-moved')
    amom = [f(a, 'UO_MO_MOMX'), f(a, 'UO_MO_MOMY')]
    if f(a, 'UO_MO_FLOORZ') < f(a, 'UO_MO_Z'):
        out.append('air')
    elif not any(amom):
        out.append('stopped')
        st0, st1 = f(e, 'UO_MO_STATE', 3), f(a, 'UO_MO_STATE', 3)
        if mo == player and st0 != st1:
            out.append('play-state')
    elif amom == mom:
        out.append('goes-on')
    else:
        out.append('friction')
    return out


def slide_path(case: GC.Case) -> List[str]:
    uc = SF.uconst()
    e, a = case.entry, case.after
    mo = mobj_of(case, 'AP')

    def f(m, name: str, n: int = 4) -> int:
        return _s32(m.read(mo + uc[name], n))
    hit = int.from_bytes(a.read(sym('p_mobj65.s:SL_HIT'), 2), 'little')
    best = int.from_bytes(a.read(sym('p_mobj65.s:SL_BEST'), 4), 'little')
    out = ['turns-%d' % (3 - hit)]
    if best == 0x10001:
        out.append('nothing-hit')
    if [f(a, 'UO_MO_MOMX'), f(a, 'UO_MO_MOMY')] != \
            [f(e, 'UO_MO_MOMX'), f(e, 'UO_MO_MOMY')]:
        out.append('slid')
    out.append('moved' if f(a, 'UO_MO_X', 8) != f(e, 'UO_MO_X', 8)
               else 'not-moved')
    pl = sym('_g_player')
    for axis, off in (('x', uc['UO_PL_MOMX']), ('y', uc['UO_PL_MOMY'])):
        if a.read(pl + off, 4) != e.read(pl + off, 4):
            out.append('bob-' + axis)
    if 'slid' in out:
        mx, my = f(a, 'UO_MO_MOMX'), f(a, 'UO_MO_MOMY')
        if mx == 0 or my == 0:
            out.append('axis-line')
        else:
            out.append('angled-line')
    return out


def _path_job(item: Tuple[str, str]) -> Tuple[str, str, List[str]]:
    key, path = item
    try:
        return key, path, path_of(GC.load_case(Path(path)))
    except Exception as error:      # reported, never hidden
        return key, path, ['error: %s: %s' % (type(error).__name__, error)]


def paths(jobs: int = 2) -> Dict[str, Dict[str, List[str]]]:
    """entry -> case path -> its paths (kept in paths.json)."""
    old = json.loads(PATHS_FILE.read_text()) if PATHS_FILE.exists() else {}
    got: Dict[str, Dict[str, List[str]]] = {k: dict(old.get(k, {}))
                                            for k in ENTRIES}
    todo = [(k, str(p)) for k in ENTRIES for _, _, p in captured(k)
            if str(p) not in got[k]]
    if todo:
        if jobs <= 1:
            res = list(map(_path_job, todo))
        else:
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                res = list(pool.map(_path_job, todo))
        for k, p, v in res:
            got[k][p] = v
    if todo or not PATHS_FILE.exists():
        PATHS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PATHS_FILE.write_text(json.dumps(got, indent=1, sort_keys=True) +
                              '\n')
    return got


def selection(key: str, ps: Optional[Dict[str, Dict[str, List[str]]]] = None,
              n: int = CHOSEN) -> List[str]:
    """CHOSEN cases of an entry: a greedy cover of the candidates' paths,
    then spread evenly over the rest."""
    ps = ps if ps is not None else paths()
    return CP.selection(key, ps, n)


# ---------------------------------------------------------------------------
# The synthetic calls: big moves (the half steps, the clamp), which no
# candidate takes (a player's momentum stays at or below MAXMOVE / 2 in the
# captured runs): a captured P_XYMovement call of the player or of a
# missile on its way, its momentum poked, upstream's routine run alone on
# that memory (gamecap.call_case: ref816 --call)
# ---------------------------------------------------------------------------

SYN_FILE = OUT / 'synthetic.json'
SYN_MOMS = {    # momx, momy (fixed_t): odd negative halves, the clamp
    'half': (0x00148001, -0x00110001),
    'half-y': (0x00008001, -0x00100003),
    'clamp': (-0x002D0003, 0x00218000),
}
SYN_BASES = {'player': 3, 'missile': 2}


def synthetic_plan(ps: Optional[Dict[str, Dict[str, List[str]]]] = None
                   ) -> List[Dict[str, Any]]:
    """The synthetic calls (kept in synthetic.json once made): base case,
    the poked momentum, a note."""
    if SYN_FILE.exists():
        return json.loads(SYN_FILE.read_text())
    ps = ps if ps is not None else paths()
    out: List[Dict[str, Any]] = []
    cand = ps.get(XYMOVE, {})
    for kind, n in SYN_BASES.items():
        bases = sorted(p for p, v in cand.items() if kind in v and
                       'friction' in v or (kind == 'missile' and kind in v
                                           and 'exploded' not in v and
                                           'removed' not in v))
        for base in CP.spread(bases, n):
            for name, (mx, my) in SYN_MOMS.items():
                if kind == 'missile' and name != 'half':
                    continue
                out.append({'base': base, 'momx': mx, 'momy': my,
                            'note': '%s %s %s' % (name, kind, '/'.join(
                                Path(base).parts[-3:]))})
    SYN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SYN_FILE.write_text(json.dumps(out, indent=1) + '\n')
    return out


def synthetic_case(rec: Dict[str, Any]) -> GC.Case:
    uc = SF.uconst()
    base = GC.load_case(Path(rec['base']))
    mo = mobj_of(base, '_Dp')
    pokes = [(mo + uc['UO_MO_MOMX'], struct.pack('<i', rec['momx'])),
             (mo + uc['UO_MO_MOMY'], struct.pack('<i', rec['momy']))]
    as_syn = GC.Case(dict(base.header, hit=0), base.entry, base.after, None)
    return GC.call_case(as_syn, pokes, note=rec['note'])


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
        try:
            if isinstance(item, dict):
                name = 'synthetic: ' + item['note']
                case = synthetic_case(item)
                path = path_of(case)
            else:
                name = '/'.join(Path(item).parts[-3:])
                case = GC.load_case(Path(item))
                path = ps.get(key, {}).get(item, [])
            prep = CP.Prep(case, key, spec_all[key])
        except Exception as error:      # reported per case, never hidden
            out.append({'case': item if not isinstance(item, dict) else
                        item['note'], 'entry': key, 'ok': False,
                        'error': '%s: %s' % (type(error).__name__, error)})
            continue
        if isinstance(item, dict) and prep.ref.problems:
            # a synthetic call whose reference state the bridge cannot
            # decode: counted apart, never equal
            out.append({'case': name, 'entry': key, 'ok': False,
                        'undecodable': prep.ref.problems[:3], 'path': path})
            continue
        for fill in fills:
            for profile in profiles:
                try:
                    r = CP.run_one(prep, nat, fill, profile)
                except Exception as error:
                    r = {'entry': key, 'fill': '%02x' % fill,
                         'profile': profile, 'ok': False,
                         'error': '%s: %s' % (type(error).__name__, error)}
                r.update(case=name, path=path)
                out.append(r)
    return out


def check_jobs(sample: int = 1, obj: Path = OUT,
               fills: Sequence[int] = FILLS,
               profiles: Sequence[str] = PROFILES[:1], chunk: int = 5,
               keys: Sequence[str] = ENTRIES,
               synthetic: bool = True) -> List[Tuple]:
    ps = paths()
    chosen: List[Tuple[str, Any]] = []
    for key in keys:
        chosen += [(key, p) for p in selection(key, ps)[::sample]]
        if synthetic and key == XYMOVE:
            chosen += [(key, r) for r in synthetic_plan(ps)[::sample]]
    return [(chosen[i:i + chunk], str(obj), tuple(fills), tuple(profiles),
             ps) for i in range(0, len(chosen), chunk)]


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


def summarize(results: Sequence[Dict[str, Any]],
              ps: Optional[Dict[str, Dict[str, List[str]]]] = None
              ) -> Dict[str, Any]:
    ps = ps if ps is not None else paths()
    out: Dict[str, Any] = {}
    for key in ENTRIES:
        rs = [r for r in results if r.get('entry') == key]
        if not rs:
            continue
        waiting = [r for r in rs if r.get('waiting')]
        undecodable = [r for r in rs if r.get('undecodable')]
        run = [r for r in rs if not r.get('waiting') and
               not r.get('undecodable')]
        bad = [r for r in run if not r.get('ok')]
        taken: Set[str] = set()
        for r in run:
            taken.update(r.get('path', []))
        every: Set[str] = set()
        for v in ps.get(key, {}).values():
            every.update(x for x in v if not x.startswith('error'))
        ls = [r['lowest_s']['s'] for r in run
              if isinstance(r.get('lowest_s'), dict)]
        out[key] = {
            'candidates': len(ps.get(key, {})),
            'cases_eligible': len(eligible_calls(key)[0]),
            'cases_run': len({r['case'] for r in run}),
            'cases_waiting': sorted({r['case'] for r in waiting}),
            'cases_synthetic': len({r['case'] for r in run
                                    if r['case'].startswith('synthetic')}),
            'cases_undecodable': [(r['case'], r['undecodable'])
                                  for r in undecodable],
            'runs': len(run), 'failures': len(bad),
            'stray_writes': sum(r.get('stray') or 0 for r in run),
            'cycles': {p: CP._stats([r['cycles'] for r in run
                                     if r.get('profile') == p and
                                     r.get('cycles')]) for p in PROFILES},
            'lowest_s': min(ls) if ls else None,
            'paths': sorted(taken),
            'paths_not_run': sorted(every - taken),
            'first_failures': [{k: r.get(k) for k in (
                'case', 'fill', 'profile', 'diff', 'error', 'ended', 'stop')}
                for r in bad[:4]]}
    return out


# ---------------------------------------------------------------------------
# The random checks of the arithmetic helpers (GAME.md 2.4 "Arithmetic")
# ---------------------------------------------------------------------------

BULK_IN, BULK_OUT = 93, 94
BULK_ROOM = 0xC000 - 0x0200
HELPERS = {'friction': 0, 'bestMul': 1, 'labs': 2}
EDGES = (0, 1, -1, 2, -2, 0x7FFFFFFF, -0x80000000, 0x7FFFFFFE,
         -0x7FFFFFFF, 0xFFFF, 0x10000, -0x10000, 0x8000, -0x8000, 0x7FFF,
         -0x7FFF, 0x1000, -0x1000, 0xFFF, -0xFFF, 0x4000, -0x4000,
         0x1E0000, -0x1E0000, 0xF0000, -0xF0000, 0x10001, -0x10001)
FRACS = (0, 1, -1, 0x800, 0x801, 0x10000, 0x10001, 0xF800, 0x7FFF, 0x8000,
         0xFFFF, -0x800, 0x7FFFFFFF, -0x80000000)


def _wrap(v: int) -> int:
    return ((v + 0x80000000) & 0xFFFFFFFF) - 0x80000000


def random_inputs(name: str, n: int, seed: int = 1) -> List[Tuple[int, ...]]:
    """n inputs of a helper: the edges first, then random values (half of
    them in a momentum's range)."""
    rnd = random.Random('%s-%d' % (name, seed))
    if name == 'bestMul':
        out = [(m, b) for m in EDGES for b in FRACS]
    else:
        out = [(v,) for v in EDGES]
    while len(out) < n:
        k = len(out) % 3
        if k == 0:
            v = rnd.randint(-0x80000000, 0x7FFFFFFF)
        elif k == 1:
            v = rnd.randint(-0x200000, 0x200000)
        else:
            v = rnd.choice((1, -1)) * (1 << rnd.randint(0, 30)) + \
                rnd.randint(-2, 2)
        if name == 'bestMul':
            b = rnd.randint(-0x800, 0x10001) if k else \
                rnd.randint(-0x80000000, 0x7FFFFFFF)
            out.append((_wrap(v), b))
        else:
            out.append((_wrap(v),))
    return out[:n]


def ref_case() -> GC.Case:
    """A captured slideMove call: its machine is upstream's for the
    helpers (AP the mobj for bestMul)."""
    cases = captured(SLIDE)
    if not cases:
        raise PartError('no slideMove case (python3 tools/native/gparts/'
                        'xymove.py --capture)')
    return GC.load_case(cases[0][2])


def upstream_values(name: str, values: Sequence[Tuple[int, ...]],
                    case: GC.Case) -> List[int]:
    import sight as SG
    uc = SF.uconst()
    pc = CP.table().address('p_mobj65.s:' + name)
    if name == 'friction':
        recs = b''.join(struct.pack('<HH', v & 0xFFFF, (v >> 16) & 0xFFFF)
                        for v, in values)
        outs = SG.mathref(case, name, pc, ['a', 'x'], ['a', 'x'], recs, 4)
    elif name == 'labs':
        recs = b''.join(struct.pack('<HH', v & 0xFFFF, (v >> 16) & 0xFFFF)
                        for v, in values)
        outs = SG.mathref(case, name, pc, ['a', 'y'], ['a', 'y'], recs, 4)
    else:
        mo = mobj_of(case, 'AP') + uc['UO_MO_MOMX']
        best = sym('p_mobj65.s:SL_BEST')
        recs = b''.join(struct.pack('<H', uc['UO_MO_MOMX']) +
                        struct.pack('<ii', m, b) for m, b in values)
        outs = SG.mathref(case, name, pc, ['y', '%06X 4' % mo,
                                           '%06X 4' % best], ['a', 'x'],
                          recs, 4)
    return [_s32(o[0:2] + o[2:4]) for o in outs]


def native_values(name: str, values: Sequence[Tuple[int, ...]],
                  obj: Path = OUT) -> List[int]:
    b = G.load_build(obj, IMAGE)
    size = 8 if name == 'bestMul' else 4
    per = BULK_ROOM // size
    out: List[int] = []
    for start in range(0, len(values), per):
        chunk = values[start:start + per]
        img = G.Image(b, 0xA5, store=False)
        img.aux(BULK_IN, 0x0200, b''.join(struct.pack(
            '<' + 'i' * len(v), *v) for v in chunk))
        work = Path(tempfile.mkdtemp(prefix='tmp-m10-xymove-bulk-',
                                     dir=str(BUILD)))
        try:
            k = len(chunk)
            r = G.run(img, work, GL.MODES['ROUTINE'], 'xy_bulk',
                      regs=(HELPERS[name], k & 0xFF, k >> 8, 0x34),
                      banks=[BULK_OUT])
            if r.ended() != 'halt':
                raise PartError('xy_bulk ended %s' % r.ended())
            m = G.load_snapshot(work / 'done.img')
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        data = bytes(m.aux[BULK_OUT][0x0200:0x0200 + 4 * k])
        out += [_s32(data[i:i + 4]) for i in range(0, len(data), 4)]
    return out


def model(name: str, v: Tuple[int, ...]) -> int:
    """The helper's arithmetic in Python, an independent statement of
    upstream's documented result (p_mobj65.s's comments)."""
    if name == 'labs':
        return _wrap(abs(v[0]))
    if name == 'friction':
        x = v[0] & 0xFFFFFFFF
        lo, hi = x & 0xFFFF, _wrap(x) >> 16
        return _wrap(((lo * 0xE800) >> 16) + hi * 0xE800)
    m, b = v
    return _wrap((m * b) >> 16)


def random_check(n: int = 100_000, seed: int = 1, obj: Path = OUT,
                 names: Sequence[str] = tuple(HELPERS)) -> Dict[str, Any]:
    case = ref_case()
    out: Dict[str, Any] = {}
    for name in names:
        vals = random_inputs(name, n, seed)
        ups = upstream_values(name, vals, case)
        nat = native_values(name, vals, obj)
        bad = [(v, u, x) for v, u, x in zip(vals, ups, nat) if u != x]
        out[name] = {'inputs': len(vals),
                     'compared': min(len(ups), len(nat)),
                     'different': len(bad) + abs(len(ups) - len(nat)),
                     'first': bad[:5],
                     'upstream_is_the_model': sum(
                         1 for v, u in zip(vals, ups) if u == model(name, v)),
                     'seed': seed}
    return out


# ---------------------------------------------------------------------------
# The planted bugs (each in a scratch copy of the part's sources)
# ---------------------------------------------------------------------------

PLANT_EDITS: Dict[str, Tuple[str, str, List[Tuple[str, str]]]] = {
    # friction in the air: the floorz < z test does not end the move
    'friction-in-air': (XYMOVE, 'xymove.s', [(
        '''        jsr slt
        bpl :+
        rts''',
        '''        jsr slt
        bra :+                          ; (planted) friction in the air
        rts''')]),
    # the second trace from the other corner: the trailing x with the
    # trailing y
    'second-trace-other-corner': (SLIDE, 'slide.s', [(
        '''        lda #1                          ; trail x, lead y''',
        '''        lda #3                          ; (planted) trail x, trail y''')]),
    # the half step of a negative move rounded down (>> 1), not toward 0
    # as C's / 2 (upstream's + 1 first)
    'half-step-rounded-down': (XYMOVE, 'xymove.s', [(
        '''        bpl @shr
        inc GT_0''',
        '''        bra @shr                        ; (planted) no + 1
        inc GT_0''')]),
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
    _, fname, edits = PLANT_EDITS[name]
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
        tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-xymove-plant-',
                                    dir=str(BUILD)))
        try:
            obj = plant_build(name, tmp)
            res = run_jobs(check_jobs(obj=obj, sample=sample,
                                      keys=(PLANT_EDITS[name][0],)), workers)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
        run = [r for r in res if not r.get('waiting') and
               not r.get('undecodable')]
        bad = [r for r in run if not r.get('ok')]
        out[name] = {'runs': len(run), 'failed': len(bad),
                     'caught': bool(bad),
                     'first': (bad[0].get('diff') or [bad[0].get('error') or
                                                     bad[0].get('ended')])[:2]
                     if bad else None}
        say('%-28s %s' % (name, 'caught: %d of %d runs fail, %s' % (
            len(bad), len(run), out[name]['first']) if bad else
            'NOT CAUGHT (%d runs)' % len(run)))
    return out


# ---------------------------------------------------------------------------
# Sizes (docs/GAME.md 4.7: the part's budget)
# ---------------------------------------------------------------------------

BUDGET = next(p['native'] for p in GL.PARTS if p['name'] == PART)
UPSTREAM_BYTES = next(p['up'] for p in GL.PARTS if p['name'] == PART)
MODULES = ('xymove', 'slide')
LABELS = ('P_XYMovement', 'slideMove', 'PTR_SlideTraverse', 'hitSlideLine',
          'friction', 'bestMul', 'labs', 'clampMove', 'skyHit',
          'quarterOut', 'slow', 'frictionAP', 'frictionNear', 'slideTrace',
          'bobClip')


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    """The part's bytes (xymove.o, slide.o; xytest.o is test-only, in the
    driver's area) against its budget, by segment (group), and each
    routine's group."""
    b = G.load_build(obj, IMAGE)
    text = (obj / (IMAGE + '.map')).read_text()
    mods = text.split('Modules list:', 1)[1].split('Segment list:', 1)[0]
    module = None
    total = 0
    segs: Dict[str, int] = {}
    for line in mods.splitlines():
        if line and not line.startswith(' ') and line.endswith('.o:'):
            module = Path(line[:-1]).stem
            continue
        f = line.split()
        if module in MODULES and f and f[0] in b.segments:
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            total += size
            segs['%s:%s' % (module, f[0])] = size
    nat = SF.Native(obj)
    groups = {n: nat.group(n) for n in LABELS}
    fill = {}
    for seg, (lo, hi) in b.segments.items():
        if seg.startswith('GGRP') and int(seg[4:]) in groups.values():
            fill[seg] = hi - lo + 1
    return {'bytes': total, 'budget': BUDGET, 'upstream': UPSTREAM_BYTES,
            'over_10_percent': total > BUDGET * 1.1, 'segments': segs,
            'groups': groups, 'group_fill': fill,
            'test_only_driver_bytes': CP_driver_bytes(text)}


def CP_driver_bytes(text: str) -> int:
    mods = text.split('Modules list:', 1)[1].split('Segment list:', 1)[0]
    module = None
    for line in mods.splitlines():
        if line and not line.startswith(' ') and line.endswith('.o:'):
            module = Path(line[:-1]).stem
            continue
        f = line.split()
        if module == 'xytest' and f and f[0] == 'DRIVER':
            return next(int(x[5:], 16) for x in f if x.startswith('Size='))
    return 0


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
               fills=['%02x' % f for f in FILLS])
    if results is not None:
        rep['entries'] = summarize(results)
        run = [r for r in results if not r.get('waiting') and
               not r.get('undecodable')]
        rep['runs'] = len(run)
        rep['waiting_runs'] = sum(1 for r in results if r.get('waiting'))
        rep['failures'] = sum(1 for r in run if not r.get('ok'))
        rep['stray_writes'] = sum(r.get('stray') or 0 for r in run)
        rep['profiles'] = sorted({r.get('profile') for r in run
                                  if r.get('profile')})
        ls = [r['lowest_s']['s'] for r in run
              if isinstance(r.get('lowest_s'), dict)]
        rep['lowest_s'] = min(ls) if ls else None
    rep.update(parts)
    rep['build_kb'] = CP.du_kb(OUT)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(rep, indent=1, default=str) + '\n')
    return rep


def print_report(rep: Dict[str, Any]) -> None:
    for key, e in rep.get('entries', {}).items():
        say('%-28s run %d of %d candidates (%d runs), failures %d, strays '
            '%d, lowest S %s' % (key, e['cases_run'], e['candidates'],
                                 e['runs'], e['failures'],
                                 e['stray_writes'], e['lowest_s']))
        say('    cycles %s' % json.dumps(e['cycles']))
        say('    paths %s' % ', '.join(e['paths']))
        if e['paths_not_run']:
            say('    candidates\' paths not run: %s' % ', '.join(
                e['paths_not_run']))
        for f in e['first_failures']:
            say('    FAIL %s' % json.dumps(f, default=str)[:600])
    if 'sizes' in rep:
        s = rep['sizes']
        say('sizes: %d of %d B (upstream %d)' % (s['bytes'], s['budget'],
                                                 s['upstream']))
    if 'random' in rep:
        for name, r in rep['random'].items():
            say('random %-9s %d inputs, %d different' % (
                name, r['inputs'], r['different']))
    if 'plants' in rep:
        for name, r in rep['plants'].items():
            say('plant %-28s %s' % (name, 'caught' if r['caught'] else
                                    'NOT CAUGHT'))


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
    parser.add_argument('--profiles', default=PROFILES[0])
    parser.add_argument('--json', type=Path)
    a = parser.parse_args(argv)
    why = missing()
    if why:
        print('cannot run: %s' % why, file=sys.stderr)
        return 2
    if a.eligible:
        for key in ENTRIES:
            elig, waiting = eligible_calls(key)
            say('%-30s eligible %d, waiting %s' % (key, len(elig), waiting))
        return 0
    if a.capture:
        say('%d cases made' % capture())
        ps = paths(a.jobs)
        for key in ENTRIES:
            count: Dict[str, int] = {}
            for v in ps[key].values():
                for x in v:
                    count[x] = count.get(x, 0) + 1
            say('%s: %d candidates, %s' % (key, len(ps[key]), json.dumps(
                count, sort_keys=True)))
        return 0
    if a.check:
        start = time.time()
        build()
        keys = a.keys.split(',') if a.keys else ENTRIES
        res = run_jobs(check_jobs(sample=a.sample, keys=keys,
                                  profiles=a.profiles.split(',')), a.jobs)
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
        for name, x in r.items():
            say('%-9s %d inputs, %d different, upstream = the model on %d, '
                'first %s' % (name, x['inputs'], x['different'],
                              x['upstream_is_the_model'], x['first'][:2]))
        return 1 if any(x['different'] for x in r.values()) else 0
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
