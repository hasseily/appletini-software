#!/usr/bin/env python3
"""Part trymove's checkpoint (milestone 10, docs/GAME.md 2.4 row trymove,
3.5; docs/game-parts/trymove.md): routine mode on the part's two entries
(P_TryMove and P_NightmareRespawn), and its planted bugs.

Usage:  python3 tools/native/gparts/trymove.py --capture [--jobs 2]
        python3 tools/native/gparts/trymove.py --check [--jobs 2]
                [--sample K]
        python3 tools/native/gparts/trymove.py --plants [--keys NAME,...]
        python3 tools/native/gparts/trymove.py --eligible
        python3 tools/native/gparts/trymove.py --report

Everything it writes is under build/native/game/trymove/ (the part's own
directory): the cases (cases/RUN/ROUTINE/hNNNNNNNN.case.z, each run's
base.ram.z: tools/native/gamecap.py with its case directory pointed here),
the candidates' paths (paths.json), report.json. The shared outputs are
read only.

The checks are lean (the owner's request of 2026-10-02): at most CHOSEN
(40) calls an entry, chosen to take as many paths as the candidates take
(a greedy cover of the paths, then spread evenly), from the $A5 machine
only, under f121 and fastpath.

--capture: the candidates of P_TryMove: evenly over demo3, DEMO1 and
DEMO2, every call of the tics where `spec` ran (the crossed special lines)
and of the tics where P_TouchSpecialThing ran (PIT_CheckThing's game logic:
MP_CLOB, so mvNodes walks), and every call that reached a dispatch target
(a crossed line's handler, an action of a damage). Each candidate's path comes from the
reference alone (path_of): moved or refused (by the check, the height,
the ceiling, the step or the drop-off), MF_NOCLIP, MP_CLOB, mvNodes'
branch (its shortcut, LR_USE with lines, LR_USE with none, the walk),
the sector list kept or moved, the crossed lines walked, MF_DROPOFF
letting a thing step off a ledge.

P_NightmareRespawn: no run calls it (nightmare is skill 5), so its calls
are synthetic: upstream's routine run alone by ref816 --call on the memory
of a captured P_TryMove call whose thing is a monster (its _Dp[0-3] is
the thing already: P_NightmareRespawn's argument): respawns with room,
one with none (its x, y poked to the player's mobj's, which is solid),
and one at x = y = 0 (poked).

--check: the chosen calls on the part's image (make -f game.mk part
P=trymove) with part checkpos's run machinery (checkpos.Prep, run_one,
outputs: secfind's and mobjstate's checks): the canonical state after the
call equal to ref816's (gcanon's routine mode, R1-R7: the line stamps,
validcount, the line record, the node lists, the sector and block lists),
every declared output of src/native/game/trymove/args.json equal, no
stray write. A call that reaches a routine of a part not in the image
stops at its FCALL or DCALL (GS_UNBUILT, GS_UNBUILTD): it is "waiting",
never counted equal.

--plants: each planted bug built from a scratch copy of the part's
sources in a temporary directory (deleted), run on its check (the chosen
calls, $A5, f121), which must fail.
"""

import argparse
import json
import shutil
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
PART = 'trymove'
OUT = GL.GAME / PART
CASES = OUT / 'cases'
PATHS_FILE = OUT / 'paths.json'
REPORT = OUT / 'report.json'
ARGS = SRC / 'game' / PART / 'args.json'
PART_SRC = SRC / 'game' / PART
SOURCES = ('part.mk', 'trymove.s', 'nightmare.s', 'trymove.inc')
IMAGE = 'ptest'
GC.CASES = CASES                # the part's own case directory

TRYMOVE = 'p_map65.s:P_TryMove'
NIGHTMARE = 'p_spawn65.s:P_NightmareRespawn'
SPEC = 'p_map65.s:spec'
TOUCH = 'p_inter65.s:P_TouchSpecialThing'
ENTRIES = (TRYMOVE, NIGHTMARE)
CHOSEN = 40                     # the lean checks: calls an entry
FILLS = (0xA5,)                 # the lean checks: one machine
PROFILES = SF.PROFILES
EVEN = (('demo3', 80), ('demo1', 40), ('demo2', 20))
SPEC_TICS = {'demo3': 8, 'demo1': 4, 'demo2': 2}      # tics where spec ran
TOUCH_TICS = {'demo3': 4, 'demo1': 2}                 # where a pickup ran
TIC_CALLS = 12                  # P_TryMove calls kept in each such tic
NIGHTMARES = 8                  # synthetic respawns (with and without room)


class PartError(Exception):
    pass


def say(text: str) -> None:
    print(text, flush=True)


def missing() -> Optional[str]:
    """Why the checkpoint cannot run (None: it can)."""
    return SF.missing()


def build(game: Optional[Path] = None, source: Path = SRC) -> Path:
    """The part's test image (make -f game.mk part P=trymove); its
    directory."""
    variables = ['P=%s' % PART]
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
                    if GL.owner_of(targets[i]) not in ('core',) and
                    GL.owner_of(targets[i]) not in ok_parts]
            for m in miss:
                waiting[m] = waiting.get(m, 0) + 1
            if not miss:
                out.append((run, hit, r['tic'][hit - 1]))
    return out, waiting


def _tics_of(run: str, key: str, n: int) -> List[int]:
    sv = GC.survey_of(run)
    if not sv or key not in sv['routines']:
        return []
    tics: List[int] = []
    for t in sv['routines'][key]['tic']:
        if t not in tics:
            tics.append(t)
    return CP.spread(tics, n)


def candidates() -> Dict[str, List[Tuple[int, int]]]:
    """run -> [(hit, tic)] of P_TryMove's candidates (the module's
    text)."""
    out: Dict[str, Dict[int, int]] = {}
    for run, n in EVEN:
        for _, hit, tic in CP.spread(eligible_calls(TRYMOVE, (run,))[0], n):
            out.setdefault(run, {})[hit] = tic
    for key, table in ((SPEC, SPEC_TICS), (TOUCH, TOUCH_TICS)):
        for run, ntics in table.items():
            tics = set(_tics_of(run, key, ntics))
            if not tics:
                continue
            calls = eligible_calls(TRYMOVE, (run,))[0]
            for t in sorted(tics):
                for _, hit, tic in [c for c in calls
                                    if c[2] == t][:TIC_CALLS]:
                    out.setdefault(run, {})[hit] = tic
    for run in ('demo3', 'demo1', 'demo2'):    # every call that reached a
        sv = GC.survey_of(run)                  #   dispatch target (a line
        reached = sv['routines'][TRYMOVE]['reached'] if sv else {}  # handler)
        for _, hit, tic in eligible_calls(TRYMOVE, (run,))[0]:
            if reached.get(str(hit)):
                out.setdefault(run, {})[hit] = tic
    return {r: sorted(d.items()) for r, d in out.items()}


def reached_of(case: GC.Case) -> List[str]:
    """The dispatch targets the reference's call reached (the survey)."""
    run, hit = case.header.get('run'), case.header.get('hit')
    sv = GC.survey_of(run) if run and hit else None
    if not sv or case.key not in sv['routines']:
        return []
    r = sv['routines'][case.key]['reached']
    return [sv['targets'][i] for i in r.get(str(hit), [])]


def case_path(run: str, hit: int) -> Path:
    return GC.case_dir(run, TRYMOVE) / ('h%08d.case.z' % hit)


def capture(batch: int = CP.BATCH) -> int:
    made = 0
    for run, calls in sorted(candidates().items()):
        todo = [h for h, _ in calls if not case_path(run, h).exists()]
        if not todo:
            continue
        sv = GC.survey_of(run)
        tics = sv['routines'][TRYMOVE]['tic']
        start = time.time()
        got = GC.capture(run, TRYMOVE, todo, tics, batch=batch, say=say)
        made += len(got)
        say('%s %s: %d cases (%.0f s)' % (run, TRYMOVE, len(got),
                                          time.time() - start))
    return made


def captured() -> List[Tuple[str, int, Path]]:
    out = []
    for run, calls in sorted(candidates().items()):
        for hit, _ in calls:
            p = case_path(run, hit)
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


def _wrap(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def path_of(case: GC.Case) -> List[str]:
    """The paths a P_TryMove call took (or a P_NightmareRespawn call)."""
    uc = SF.uconst()
    e, a = case.entry, case.after
    t = CP.table()
    dp = (case.regs_in['d'] + t.address('_Dp') - t.direct_page) & 0xFFFF
    thing = int.from_bytes(e.read(dp, 3), 'little')

    def u16(m, name: str) -> int:
        return int.from_bytes(m.read(sym(name), 2), 'little')

    def field(m, off: int, n: int = 4) -> bytes:
        return m.read(thing + off, n)
    if case.key == NIGHTMARE:
        xy = field(e, uc['UO_MO_X'], 8)
        if not any(xy):
            return ['zero-xy']
        # P_RemoveMobj's P_UnsetThingPosition takes its node list
        respawned = field(a, uc['UO_MO_TOUCHING'], 3) != field(
            e, uc['UO_MO_TOUCHING'], 3)
        return ['respawned' if respawned else 'no-room']
    flags = int.from_bytes(field(a, uc['UO_MO_FLAGS']), 'little')
    moved = case.regs_out['a'] & 0xFF
    out = ['moved' if moved else 'refused']
    out += ['reached-' + n.split(':')[-1] for n in reached_of(case)]
    if flags & (uc['UC_MF_MISSILE_HI'] << 16):
        out.append('missile')
    if flags & uc['UC_MF_NOCLIP']:
        out.append('noclip')
        return out
    clob = u16(a, 'p_map65.s:MP_CLOB') & 0xFF
    if clob:
        out.append('clob')
    fz = _s32(a.read(sym('_g_tmfloorz'), 4))
    cz = _s32(a.read(sym('_g_tmceilingz'), 4))
    dz = _s32(a.read(sym('_g_tmdropoffz'), 4))
    z = _s32(field(e, uc['UO_MO_Z']))
    h = _s32(field(e, uc['UO_MO_HEIGHT']))
    step = 24 << 16
    tests = [('height', _wrap(cz - fz) < h), ('ceiling', _wrap(cz - z) < h),
             ('step', _wrap(fz - z) > step)]
    if not flags & uc['UC_MF_DROPOFF']:
        tests.append(('dropoff', _wrap(fz - dz) > step))
    elif _wrap(fz - dz) > step:
        out.append('dropoff-allowed')
    if _wrap(fz - z) > 0 and not _wrap(fz - z) > step:
        out.append('step-up')
    if not moved:
        first = next((n for n, bad in tests if bad), 'check')
        out.append('refused-' + first)
        if first != 'check' and _s32(field(e, uc['UO_MO_FLOORZ'])) != fz:
            out.append('refused-floorz-differs')
        return out
    mv_sec = int.from_bytes(a.read(sym('p_map65.s:MV_SEC'), 3), 'little')
    sprev = int.from_bytes(field(e, uc['UO_MO_SPREV'], 3), 'little')
    out.append('sector-stays' if sprev == mv_sec + uc['UO_SEC_THINGLIST']
               else 'sector-moves')
    if not flags & uc['UC_MF_NOSECTOR']:
        lr_ok = u16(a, 'p_map65.s:LR_OK') & 0xFF
        lr_n = u16(a, 'p_map65.s:LR_N') & 0xFF
        if clob or not lr_ok:
            out.append('nodes-walk')
        elif lr_n:
            out.append('nodes-lruse')
        else:
            node = int.from_bytes(field(e, uc['UO_MO_TOUCHING'], 3),
                                  'little')
            one = node and not int.from_bytes(
                e.read(node + uc['UO_SN_M_TNEXT'], 3), 'little') and \
                int.from_bytes(e.read(node + uc['UO_SN_M_SECTOR'], 3),
                               'little') == mv_sec
            out.append('nodes-shortcut' if one else 'nodes-lruse-none')
    if u16(a, '_g_numspechit') == 0xFFFF:
        out.append('spec')     # (how many were crossed: not in memory)
    return out


def _path_job(path: str) -> Tuple[str, List[str]]:
    try:
        return path, path_of(GC.load_case(Path(path)))
    except Exception as error:      # reported, never hidden
        return path, ['error: %s: %s' % (type(error).__name__, error)]


def paths(jobs: int = 2) -> Dict[str, List[str]]:
    """case path -> its paths (P_TryMove's candidates; kept in
    paths.json)."""
    old = json.loads(PATHS_FILE.read_text()) if PATHS_FILE.exists() else {}
    have = old.get(TRYMOVE, {})
    todo = [str(p) for _, _, p in captured() if str(p) not in have]
    got = dict(have)
    if todo:
        if jobs <= 1:
            got.update(map(_path_job, todo))
        else:
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                got.update(pool.map(_path_job, todo))
    if todo or not PATHS_FILE.exists():
        PATHS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PATHS_FILE.write_text(json.dumps({TRYMOVE: got}, indent=1,
                                         sort_keys=True) + '\n')
    return got


def selection(ps: Optional[Dict[str, List[str]]] = None,
              n: int = CHOSEN) -> List[str]:
    """CHOSEN cases of P_TryMove: a greedy cover of the candidates' paths,
    then spread evenly over the rest."""
    ps = ps if ps is not None else paths()
    return CP.selection(TRYMOVE, {TRYMOVE: ps}, n)


# ---------------------------------------------------------------------------
# P_NightmareRespawn's synthetic calls
# ---------------------------------------------------------------------------

def nightmare_plan(ps: Optional[Dict[str, List[str]]] = None
                   ) -> List[Dict[str, Any]]:
    """The bases: captured P_TryMove calls of monsters (not the player's
    mobj, not a missile), spread; the first one also with x = y = 0."""
    uc = SF.uconst()
    ps = ps if ps is not None else paths()
    good = []
    for p in sorted(ps):
        if 'missile' in ps[p] or any(x.startswith('error') for x in ps[p]):
            continue
        case = GC.load_case(Path(p))
        t = CP.table()
        dp = (case.regs_in['d'] + t.address('_Dp') - t.direct_page) & 0xFFFF
        thing = int.from_bytes(case.entry.read(dp, 3), 'little')
        mo = int.from_bytes(case.entry.read(sym('_g_player') +
                                            uc['UO_PL_MO'], 3), 'little')
        if thing != mo:
            good.append(p)
    plan = [{'base': p, 'zero': False, 'note': 'nightmare %s' % '/'.join(
        Path(p).parts[-3:])} for p in CP.spread(good, NIGHTMARES)]
    if plan:
        plan.append(dict(plan[0], zero=True, note=plan[0]['note'] + ' x=y=0'))
        plan.append(dict(plan[-2], onplayer=True,
                         note=plan[-2]['note'] + ' at the player'))
    return plan


def nightmare_case(rec: Dict[str, Any]) -> GC.Case:
    """A synthetic call: the base's entry memory (its _Dp[0-3] the thing),
    x = y = 0 poked for a 'zero' one, upstream's P_NightmareRespawn run
    alone on ref816 (gamecap.call_case)."""
    uc = SF.uconst()
    base = GC.load_case(Path(rec['base']))
    t = CP.table()
    dp = (base.regs_in['d'] + t.address('_Dp') - t.direct_page) & 0xFFFF
    thing = int.from_bytes(base.entry.read(dp, 3), 'little')
    pokes: List[Tuple[int, bytes]] = []
    if rec['zero']:
        pokes.append((thing + uc['UO_MO_X'], bytes(8)))
    if rec.get('onplayer'):         # no room: on the player's (solid) mobj
        mo = int.from_bytes(base.entry.read(sym('_g_player') +
                                            uc['UO_PL_MO'], 3), 'little')
        pokes.append((thing + uc['UO_MO_X'],
                      base.entry.read(mo + uc['UO_MO_X'], 8)))
    as_nm = GC.Case(dict(base.header, routine=NIGHTMARE), base.entry,
                    base.after, None)
    return GC.call_case(as_nm, pokes, note=rec['note'])


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
        path: List[str] = []
        try:
            if isinstance(item, dict):
                name = 'synthetic: ' + item['note']
                try:
                    case = nightmare_case(item)
                except GC.CapError as error:
                    # no reference: upstream's call run alone did not
                    # return (zone pages outside the base's footprint):
                    # counted apart, never equal
                    out.append({'case': name, 'entry': key, 'ok': False,
                                'undecodable': ['no reference: %s' % error],
                                'path': []})
                    continue
                path = path_of(case)
            else:
                name = '/'.join(Path(item).parts[-3:])
                case = GC.load_case(Path(item))
                path = ps.get(item, [])
            prep = CP.Prep(case, key, spec_all[key])
        except Exception as error:      # reported per case, never hidden
            out.append({'case': name, 'entry': key, 'ok': False,
                        'error': '%s: %s' % (type(error).__name__, error)})
            continue
        if isinstance(item, dict) and prep.ref.problems:
            # a synthetic call whose reference state the bridge cannot
            # decode: counted apart, never equal (the call's Z_Malloc
            # walked zone pages outside the base case's footprint, which
            # hold the run's base RAM, not that tic's)
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
               profiles: Sequence[str] = PROFILES, chunk: int = 5,
               keys: Sequence[str] = ENTRIES) -> List[Tuple]:
    ps = paths()
    jobs: List[Tuple] = []
    chosen: List[Tuple[str, Any]] = []
    if TRYMOVE in keys:
        chosen += [(TRYMOVE, p) for p in selection(ps)[::sample]]
    if NIGHTMARE in keys:
        chosen += [(NIGHTMARE, r) for r in nightmare_plan(ps)[::sample]]
    for i in range(0, len(chosen), chunk):
        jobs.append((chosen[i:i + chunk], str(obj), tuple(fills),
                     tuple(profiles), ps))
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
        undecodable = [r for r in rs if r.get('undecodable')]
        run = [r for r in rs if not r.get('waiting') and
               not r.get('undecodable')]
        bad = [r for r in run if not r.get('ok')]
        paths_: Set[str] = set()
        for r in run:
            paths_.update(r.get('path', []))
        ls = [r['lowest_s']['s'] for r in run
              if isinstance(r.get('lowest_s'), dict)]
        out[key] = {
            'cases_chosen': len({r['case'] for r in rs}),
            'cases_run': len({r['case'] for r in run}),
            'cases_waiting': sorted({r['case'] for r in waiting}),
            'cases_undecodable': [(r['case'], r['undecodable'])
                                  for r in undecodable],
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
# The planted bugs (each in a scratch copy of the part's sources)
# ---------------------------------------------------------------------------

PLANT_EDITS: Dict[str, Tuple[str, List[Tuple[str, str]]]] = {
    # mvNodes' shortcut without validcount + 1
    'shortcut-no-validcount': ('trymove.s', [(
        '''        jsr gv_inc                      ; the rest that P_CreateSecNodeList''',
        '''        nop                             ; (planted) the rest that P_CreateSecNodeList
        nop
        nop''')]),
    # LR_USE not set: the walk stamps the lines again
    'lruse-not-set': ('trymove.s', [(
        '''@use:   lda #1                          ; the walk takes the record''',
        '''@use:   lda #0                          ; (planted) the walk takes the record''')]),
    # floorz, ceilingz, dropoffz set before the height and step tests
    'floorz-before-step': ('trymove.s', [(
        '''        ; tmceilingz - tmfloorz < height
        ldx #0''',
        '''        ldy #LN_B + MB_FLOORZ + 11      ; (planted) floorz, ceilingz,
        ldx #11                         ;   dropoffz first
:       lda GM_TMFLOORZ,x
        sta (GC_MP),y
        dey
        dex
        bpl :-
        lda #D_B
        jsr mo_dirty
        ; tmceilingz - tmfloorz < height
        ldx #0''')]),
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
        tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-trymove-plant-',
                                    dir=str(BUILD)))
        try:
            obj = plant_build(name, tmp)
            res = run_jobs(check_jobs(obj=obj, sample=sample,
                                      profiles=(PROFILES[0],),
                                      keys=(TRYMOVE,)), workers)
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
        say('%-24s %s' % (name, 'caught: %d of %d runs fail, %s' % (
            len(bad), len(run), out[name]['first']) if bad else
            'NOT CAUGHT (%d runs)' % len(run)))
    return out


# ---------------------------------------------------------------------------
# Sizes (docs/GAME.md 4.7: the part's budget)
# ---------------------------------------------------------------------------

BUDGET = next(p['native'] for p in GL.PARTS if p['name'] == PART)
UPSTREAM_BYTES = next(p['up'] for p in GL.PARTS if p['name'] == PART)
LABELS = ('P_TryMove', 'P_NightmareRespawn')
MODULES = ('trymove', 'nightmare')


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    """The part's bytes (trymove.o, nightmare.o) against its budget; each
    entry's module bytes and group."""
    b = G.load_build(obj, IMAGE)
    text = (obj / (IMAGE + '.map')).read_text()
    mods = text.split('Modules list:', 1)[1].split('Segment list:', 1)[0]
    module = None
    total = 0
    routines: Dict[str, Any] = {}
    nat = SF.Native(obj)
    for line in mods.splitlines():
        if line and not line.startswith(' ') and line.endswith('.o:'):
            module = Path(line[:-1]).stem
            continue
        f = line.split()
        if module in MODULES and f and f[0] in b.segments:
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            total += size
            label = LABELS[MODULES.index(module)]
            routines[label] = {'bytes': size, 'group': nat.group(label),
                               'segment': f[0]}
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
        run = [r for r in results if not r.get('waiting') and
               not r.get('undecodable')]
        rep['runs'] = len(run)
        rep['waiting_runs'] = sum(1 for r in results if r.get('waiting'))
        rep['undecodable_cases'] = sum(1 for r in results
                                       if r.get('undecodable'))
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


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--eligible', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--keys', default=None)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--sample', type=int, default=1)
    parser.add_argument('--json', type=Path)
    a = parser.parse_args(argv)
    why = missing()
    if why:
        print('cannot run: %s' % why, file=sys.stderr)
        return 2
    if a.eligible:
        for key in ENTRIES:
            elig, waiting = eligible_calls(key)
            say('%-34s eligible %d, waiting %s' % (key, len(elig), waiting))
        return 0
    if a.capture:
        say('%d cases made' % capture())
        count: Dict[str, int] = {}
        ps = paths(a.jobs)
        for v in ps.values():
            for x in v:
                count[x] = count.get(x, 0) + 1
        say('%s: %d candidates, %s' % (TRYMOVE, len(ps), json.dumps(
            count, sort_keys=True)))
        return 0
    if a.check:
        start = time.time()
        build()
        keys = a.keys.split(',') if a.keys else ENTRIES
        res = run_jobs(check_jobs(sample=a.sample, keys=keys), a.jobs)
        rep = write_report(res, sizes=sizes(), check_seconds=round(
            time.time() - start), sample=a.sample)
        if a.json:
            a.json.write_text(json.dumps(res, indent=1, default=str) + '\n')
        print_report(rep)
        return 1 if rep['failures'] else 0
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
