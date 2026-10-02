#!/usr/bin/env python3
"""Part attack's checkpoint (milestone 10, docs/GAME.md 2.4 row attack,
3.5; docs/game-parts/attack.md): routine mode on the part's two entries
(P_LineAttack, P_AimLineAttack: their traversers PTR_ShootTraverse and
PTR_AimTraverse, shootSpecial and puffPos run inside them), the random
checks of rangeMul and mul3, and the planted bugs.

Usage:  python3 tools/native/gparts/attack.py --capture
        python3 tools/native/gparts/attack.py --check [--jobs 2]
                [--sample K] [--keys KEY,...]
        python3 tools/native/gparts/attack.py --random [--count N]
        python3 tools/native/gparts/attack.py --plants [--keys NAME,...]
        python3 tools/native/gparts/attack.py --eligible
        python3 tools/native/gparts/attack.py --report

Everything it writes is under build/native/game/attack/ (the part's own
directory): the cases (cases/RUN/ROUTINE/hNNNNNNNN.case.z, each run's
base.ram.z: tools/native/gamecap.py with its case directory pointed here),
the candidates' paths (paths.json), report.json. The shared outputs are
read only.

The checks are lean (the owner's request of 2026-10-02): at most CHOSEN
(40) captured calls an entry, chosen to take as many paths as the
candidates take (a greedy cover of the paths, then spread evenly), plus
the synthetic calls, from the $A5 machine only, under f121 and fastpath.

--capture: the candidates, evenly over demo3, DEMO1, DEMO2 and newgame,
and P_LineAttack's calls in the first tics where shootSpecial ran (a shot
across a special line). Each candidate's path comes from the reference
alone (path_of): the shooter (the player or a monster), the puff, the
blood, no puff (the sky, or nothing within range), a thing damaged or
killed, a door started; the aim's target, its slopes narrowed.

--check: the chosen calls on the part's image (make -f game.mk part
P=attack AK_TEST=1) with part checkpos's run machinery (checkpos.Prep,
run_one, outputs: secfind's and mobjstate's checks): the canonical state
after the call equal to ref816's (gcanon's routine mode, R1-R7), every
declared output of src/native/game/attack/args.json equal (aimslope,
la_damage, attackrange, shootz, shootthing, topslope, bottomslope,
linetarget, P_AimLineAttack's result), no stray write. The synthetic
calls (GAME.md 2.4: a shot into the sky, at a gun-activated line, along a
wall) are captured calls with pokes, upstream's P_LineAttack run alone on
ref816 (gamecap.call_case): the hit line's front sector's ceiling made the
sky and lowered under the shot; the hit line made special 46 with the tag
of a sector; the shooter's angle made the direction of a wall line it is
moved onto.

--random: rangeMul and mul3 on N inputs each (0, +-1, the extremes, the
two shift ranges, random values) through upstream's helpers (mathref
batch on a captured P_LineAttack call's machine) and the native ones
(aktest.s ak_bulk), compared.

--plants: each planted bug built from a scratch copy of the part's
sources in a temporary directory (deleted), run on its check (the chosen
calls, $A5, f121), which must fail.
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
PART = 'attack'
OUT = GL.GAME / PART
CASES = OUT / 'cases'
PATHS_FILE = OUT / 'paths.json'
REPORT = OUT / 'report.json'
ARGS = SRC / 'game' / PART / 'args.json'
PART_SRC = SRC / 'game' / PART
SOURCES = ('part.mk', 'attack.s', 'attack.inc', 'aktest.s')
IMAGE = 'ptest'
GC.CASES = CASES                # the part's own case directory

LINEATTACK = 'p_attack65.s:P_LineAttack'
AIMLINEATTACK = 'p_attack65.s:P_AimLineAttack'
SHOOTSPECIAL = 'p_attack65.s:shootSpecial'
ENTRIES = (LINEATTACK, AIMLINEATTACK)
CHOSEN = 40                     # the lean checks: calls an entry
FILLS = (0xA5,)                 # the lean checks: one machine
PROFILES = SF.PROFILES
EVEN = {LINEATTACK: (('demo3', 30), ('demo1', 30), ('demo2', 20),
                     ('newgame', 3)),
        AIMLINEATTACK: (('demo3', 20), ('demo1', 30), ('demo2', 20),
                        ('newgame', 7))}
SPECIAL_TICS = {'demo3': 3, 'demo2': 2, 'newgame': 1, 'demo1': 1}
TIC_CALLS = 8                   # P_LineAttack calls kept in such a tic
BATCH = 40


class PartError(Exception):
    pass


def say(text: str) -> None:
    print(text, flush=True)


def missing() -> Optional[str]:
    """Why the checkpoint cannot run (None: it can)."""
    return SF.missing()


def build(game: Optional[Path] = None, source: Path = SRC) -> Path:
    """The part's test image (make -f game.mk part P=attack AK_TEST=1); its
    directory."""
    variables = ['P=%s' % PART, 'AK_TEST=1']
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
    return tics[:n]


def candidates(key: str) -> Dict[str, List[Tuple[int, int]]]:
    """run -> [(hit, tic)] of an entry's candidates (the module's text)."""
    out: Dict[str, Dict[int, int]] = {}
    for run, n in EVEN[key]:
        for _, hit, tic in CP.spread(eligible_calls(key, (run,))[0], n):
            out.setdefault(run, {})[hit] = tic
    if key == LINEATTACK:
        for run, ntics in SPECIAL_TICS.items():
            tics = set(_tics_of(run, SHOOTSPECIAL, ntics))
            calls = eligible_calls(key, (run,))[0]
            for t in sorted(tics):
                for _, hit, tic in [c for c in calls
                                    if c[2] == t][:TIC_CALLS]:
                    out.setdefault(run, {})[hit] = tic
    return {r: sorted(d.items()) for r, d in out.items()}


def case_path(run: str, key: str, hit: int) -> Path:
    return GC.case_dir(run, key) / ('h%08d.case.z' % hit)


def capture(keys: Sequence[str] = ENTRIES, batch: int = BATCH) -> int:
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
# A call's path, from the reference alone (the coverage, GAME.md 3.5 step
# 2): its canonical states at the entry and the return, its outputs
# ---------------------------------------------------------------------------

def sym(name: str) -> int:
    return CP.sym(name)


def _s32(b: bytes) -> int:
    return int.from_bytes(b, 'little', signed=True)


TOPSLOPE = 40960


def _live(objs: Dict[str, Any]) -> Dict[Tuple[str, Any], Dict[str, Any]]:
    out = {}
    for kind in ('mobj', 'zmobj'):
        for k, v in objs.get(kind, {}).items():
            if not v.get('free'):
                out[(kind, k)] = v
    return out


def path_of(case: GC.Case, ref: Optional['SF.Ref'] = None) -> List[str]:
    """The paths a P_LineAttack or P_AimLineAttack call took."""
    uc = SF.uconst()
    ref = ref or SF.Ref(case)
    si, so = ref.s_in['objects'], ref.s_out['objects']
    out: List[str] = []
    t1 = ref.ref(int.from_bytes(ref.source('dp:_Dp:4'), 'little'),
                 ('mobj', 'zmobj'))
    player = next(iter(si['player'].values()))
    out.append('player' if player.get('mo') == t1 else 'monster')
    after = case.after
    if case.key == AIMLINEATTACK:
        tgt = int.from_bytes(after.read(sym('_g_linetarget'), 3), 'little')
        top = _s32(after.read(sym('p_attack65.s:AT_TOP'), 4))
        bot = _s32(after.read(sym('p_attack65.s:AT_BOT'), 4))
        out.append('target' if tgt else 'no-target')
        if top != TOPSLOPE:
            out.append('top-narrowed')
        if bot != -TOPSLOPE:
            out.append('bottom-narrowed')
        if tgt and top <= bot:
            out.append('window-closed')
        res = ((case.regs_out['x'] & 0xFFFF) << 16 |
               (case.regs_out['a'] & 0xFFFF))
        if res:
            out.append('slope-up' if res < 0x80000000 else 'slope-down')
        return out
    li, lo = _live(si), _live(so)
    new = [v['type'] for k, v in lo.items() if k not in li]
    puffs = new.count(uc['UC_MT_PUFF'])
    blood = new.count(uc['UC_MT_BLOOD'])
    out.append('puff' if puffs else 'blood' if blood else 'no-spawn')
    hurt = [k for k, v in lo.items() if k in li and
            v['health'] < li[k]['health']]
    gone = [k for k in li if k not in lo]
    dead = [k for k in hurt if lo[k]['health'] <= 0]
    if hurt:
        out.append('damage')
        if puffs:
            out.append('noblood-damage')
    if dead or gone:
        out.append('kill')
    for kind in ('door', 'plat', 'floor'):
        if set(so.get(kind, {})) - set(si.get(kind, {})):
            out.append('started-' + kind)
    slope = _s32(ref.source('s:4:4'))
    out.append('slope-0' if slope == 0 else 'slope')
    run, tic = case.header.get('run'), case.header.get('tic')
    sv = GC.survey_of(run) if run else None
    if sv and SHOOTSPECIAL in sv['routines'] and \
            tic in sv['routines'][SHOOTSPECIAL]['tic']:
        out.append('special-tic')
    note = case.header.get('note', '')
    if note.startswith('synthetic'):
        out.append(note.split(':')[1].split()[0] if ':' in note else note)
    return out


def _path_job(item: Tuple[str, str]) -> Tuple[str, List[str]]:
    key, path = item
    try:
        return path, path_of(GC.load_case(Path(path)))
    except Exception as error:      # reported, never hidden
        return path, ['error: %s: %s' % (type(error).__name__, error)]


def paths(jobs: int = 2) -> Dict[str, Dict[str, List[str]]]:
    """key -> case path -> its paths (the candidates; kept in
    paths.json)."""
    old = json.loads(PATHS_FILE.read_text()) if PATHS_FILE.exists() else {}
    out: Dict[str, Dict[str, List[str]]] = {}
    changed = False
    for key in ENTRIES:
        have = old.get(key, {})
        todo = [(key, str(p)) for _, _, p in captured(key)
                if str(p) not in have]
        got = dict(have)
        if todo:
            changed = True
            if jobs <= 1:
                got.update(map(_path_job, todo))
            else:
                with ProcessPoolExecutor(max_workers=jobs) as pool:
                    got.update(pool.map(_path_job, todo))
        out[key] = got
    if changed or not PATHS_FILE.exists():
        PATHS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PATHS_FILE.write_text(json.dumps(out, indent=1, sort_keys=True) +
                              '\n')
    return out


def selection(key: str, ps: Optional[Dict[str, Dict[str, List[str]]]] = None,
              n: int = CHOSEN) -> List[str]:
    """CHOSEN cases of an entry: a greedy cover of the candidates' paths,
    then spread evenly over the rest (checkpos.selection)."""
    ps = ps if ps is not None else paths()
    return CP.selection(key, ps, n)


# ---------------------------------------------------------------------------
# The synthetic calls (GAME.md 2.4: a shot into the sky, at a gun-activated
# line, along a wall): captured P_LineAttack calls with pokes, upstream's
# routine run alone on ref816 (--call, its registers given with --reg)
# ---------------------------------------------------------------------------

SKY_SLOPES = (0x20000, 0x8000, 0)      # the slope: 2, 1/2, 0
GUN_BASES = 6                           # bases tried for the gun line
WALL_BASES = 2                          # bases for the walls


def synth_case(base: GC.Case, pokes: Sequence[Tuple[int, bytes]],
               regs: Dict[str, int], note: str) -> GC.Case:
    """gamecap.call_case with registers: the base's entry memory with
    pokes, upstream's routine run alone by ref816 --call with --reg."""
    entry = base.entry.copy()
    entry.header = base.entry.header
    for a, d in pokes:
        entry.write(a, d)
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-attack-call-',
                                 dir=str(BUILD)))
    try:
        (work / 'entry.img').write_bytes(entry.image_bytes())
        call, writes = SF.ref_call(GC.CL.Linkmap().address(base.key), [],
                                   regs, work)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    after = entry.copy()
    for a, d in writes:
        after.write(a, d)
    header = dict(base.header, note=note, call=call,
                  writes=GC._ranges(writes))
    return GC.Case(header, entry, after, None)


def _player_shots(ps: Dict[str, List[str]], want: str) -> List[str]:
    return [p for p in sorted(ps) if 'player' in ps[p] and want in ps[p]]


def synthetic_plan(ps: Optional[Dict[str, Dict[str, List[str]]]] = None
                   ) -> List[Dict[str, Any]]:
    """The synthetic calls' recipes: (base, kind, parameter)."""
    ps = ps if ps is not None else paths()
    lp = ps.get(LINEATTACK, {})
    plan: List[Dict[str, Any]] = []
    walls = _player_shots(lp, 'puff')
    if walls:
        for s in SKY_SLOPES:
            plan.append({'base': walls[0], 'kind': 'sky', 'slope': s,
                         'note': 'synthetic:sky slope %X' % s})
    for b in CP.spread(_player_shots(lp, 'slope-0'), GUN_BASES):
        plan.append({'base': b, 'kind': 'gun',
                     'note': 'synthetic:gun-line %s' % '/'.join(
                         Path(b).parts[-3:])})
    for b in CP.spread(walls, WALL_BASES):
        for axis in ('vertical', 'horizontal'):
            plan.append({'base': b, 'kind': 'wall', 'axis': axis,
                         'note': 'synthetic:along-wall %s %s' % (
                             axis, '/'.join(Path(b).parts[-3:]))})
    return plan


def _wall_line(ref: 'SF.Ref', axis: str) -> Optional[Tuple[int, int, int]]:
    """A one-sided line along the axis, at least 64 units long: (x, y) of
    a point a quarter of the way along it (whole units), and the angle
    from it toward its second vertex."""
    best = None
    for k, ln in sorted(ref.s_in['objects']['line'].items()):
        if ln['sidenum'][1] not in (65535, -1, None):
            continue
        dx, dy = ln['dx'], ln['dy']
        if axis == 'vertical' and dx == 0 and abs(dy) >= 64:
            ang = 0x40000000 if dy > 0 else 0xC0000000
        elif axis == 'horizontal' and dy == 0 and abs(dx) >= 64:
            ang = 0 if dx > 0 else 0x80000000
        else:
            continue
        x0, y0 = ln['v1']
        best = (x0 + dx // 4, y0 + dy // 4, ang)
        break
    return best


def synthetic_case(rec: Dict[str, Any]) -> GC.Case:
    uc = SF.uconst()
    base = GC.load_case(Path(rec['base']))
    mb = SF.MapBase(Path(rec['base']))
    regs = {k: base.regs_in[k] for k in ('a', 'x', 'y')}
    pokes: List[Tuple[int, bytes]] = []
    if rec['kind'] == 'sky':        # every ceiling the sky, the slope
        for i in range(mb.nsectors):
            pokes.append((mb.sector(i) + uc['UO_SEC_CEILINGPIC'],
                          struct.pack('<H', 0xFFFE)))
        pokes.append((base.regs_in['s'] + 4,
                      struct.pack('<i', rec['slope'])))
    elif rec['kind'] == 'gun':      # every tagged line special 46
        for i in range(mb.nlines):
            if mb.line_tag(i):
                pokes.append((mb.line(i) + uc['UO_LINE_SPECIAL'],
                              struct.pack('<H', 46)))
    elif rec['kind'] == 'wall':     # the shooter on a wall, along it
        ref = SF.Ref(base)
        w = _wall_line(ref, rec['axis'])
        if w is None:
            raise PartError('no %s one-sided line' % rec['axis'])
        x, y, ang = w
        t1 = int.from_bytes(ref.source('dp:_Dp:4'), 'little') & 0xFFFFFF
        pokes.append((t1 + uc['UO_MO_X'], struct.pack('<ii', x << 16,
                                                      y << 16)))
        regs['a'], regs['x'] = ang & 0xFFFF, ang >> 16
    return synth_case(base, pokes, regs, rec['note'])


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
                name = item['note']
                case = synthetic_case(item)
                prep = CP.Prep(case, key, spec_all[key])
                path = path_of(case, prep.ref)
            else:
                name = '/'.join(Path(item).parts[-3:])
                case = GC.load_case(Path(item))
                path = ps.get(item, [])
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
                r.update(case=name, path=path)
                out.append(r)
    return out


def check_jobs(sample: int = 1, obj: Path = OUT,
               fills: Sequence[int] = FILLS,
               profiles: Sequence[str] = PROFILES, chunk: int = 6,
               keys: Sequence[str] = ENTRIES, synthetic: bool = True
               ) -> List[Tuple]:
    ps = paths()
    jobs: List[Tuple] = []
    for key in keys:
        chosen: List[Any] = selection(key, ps)[::sample]
        if synthetic and key == LINEATTACK:
            chosen += synthetic_plan(ps)[::sample]
        for i in range(0, len(chosen), chunk):
            jobs.append(([(key, p) for p in chosen[i:i + chunk]], str(obj),
                         tuple(fills), tuple(profiles), ps[key]))
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
        out[key] = {
            'cases_chosen': len({r['case'] for r in rs}),
            'cases_run': len({r['case'] for r in run}),
            'cases_synthetic': len({r['case'] for r in run
                                    if r['case'].startswith('synthetic')}),
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
# rangeMul's and mul3's random checks (GAME.md 2.4 "Arithmetic")
# ---------------------------------------------------------------------------

BULK_IN, BULK_OUT = 93, 94
BULK_ROOM = 0xC000 - 0x0200
RANGES = (0x08000000, 0x04000000, 0x00400000, 0x00800000, 0x07FFFFFF,
          0x08000001, 0x08010000, 0x04010000, 0, 1, 0x7FFFFFFF)
EDGES = (0, 1, -1, 2, -2, 0x7FFFFFFF, -0x80000000, 0xFFFF, 0x10000,
         -0x10000, 0x8000, -0x8000, 0x7FFF, 0x10001, -0x10001, 0x1FFFFF,
         -0x200000, 0x200000)


def _w(v: int) -> int:
    return ((v + 0x80000000) & 0xFFFFFFFF) - 0x80000000


def random_inputs(n: int, seed: int = 1) -> List[Tuple[int, int, int]]:
    """(v, attackrange, aimslope): every edge v with every listed range and
    the aims 0, +-1, the extremes, then random ones (the ranges mostly the
    two shift ranges, the values mostly fracs and slopes)."""
    rnd = random.Random(seed)
    aims = (0, 1, -1, 0x7FFFFFFF, -0x80000000, 40960, -40960)
    out = []
    for v in EDGES:
        for r in RANGES:
            out.append((v, r, aims[len(out) % len(aims)]))
    while len(out) < n:
        k = len(out) % 4
        r = rnd.choice(RANGES) if k == 3 else rnd.choice(
            (0x08000000, 0x04000000, rnd.randint(-0x80000000, 0x7FFFFFFF)))
        if k == 0:
            v = rnd.randint(-0x80000000, 0x7FFFFFFF)
        elif k == 1:
            v = rnd.randint(0, 0x10000)             # a frac
        else:
            v = rnd.randint(-0x400000, 0x400000)
        a = rnd.choice((0, rnd.randint(-0x20000, 0x20000),
                        rnd.randint(-0x80000000, 0x7FFFFFFF)))
        out.append((v, r, a))
    return [(_w(v), _w(r), _w(a)) for v, r, a in out[:n]]


def native_bulk(b, mode: int, inputs: Sequence[Tuple[int, int, int]]
                ) -> List[int]:
    per = BULK_ROOM // 12
    out: List[int] = []
    for start in range(0, len(inputs), per):
        chunk = inputs[start:start + per]
        img = G.Image(b, 0xA5, store=False)
        img.aux(BULK_IN, 0x0200, b''.join(struct.pack('<iii', *t)
                                          for t in chunk))
        work = Path(tempfile.mkdtemp(prefix='tmp-m10-attack-bulk-',
                                     dir=str(BUILD)))
        try:
            k = len(chunk)
            r = G.run(img, work, GL.MODES['ROUTINE'], 'ak_bulk',
                      regs=(mode, k & 0xFF, k >> 8, 0x34), banks=[BULK_OUT])
            if r.ended() != 'halt':
                raise PartError('ak_bulk ended %s' % r.ended())
            m = G.load_snapshot(work / 'done.img')
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        data = bytes(m.aux[BULK_OUT][0x0200:0x0200 + 4 * len(chunk)])
        out += [int.from_bytes(data[i:i + 4], 'little', signed=True)
                for i in range(0, len(data), 4)]
    return out


def model(name: str, v: int, r: int, a: int) -> int:
    """FixedMul, FixedMul3 in Python (floor, the low 32 bits)."""
    def fm(x: int, y: int) -> int:
        return _w((x * y) >> 16)
    if name == 'rangeMul':
        return fm(r, v)
    return 0 if a == 0 else fm(fm(r, v), a)


def random_check(n: int = 100_000, seed: int = 1,
                 obj: Path = OUT) -> Dict[str, Any]:
    """rangeMul and mul3 on n inputs each: upstream's (mathref batch on a
    captured P_LineAttack call's machine: A the high word, X the low word
    in, X:C out, AT_RANGE and AT_AIM poked) against the native (ak_bulk)
    and against the Python model."""
    import sight as SG
    cases = [p for _, _, p in captured(LINEATTACK)]
    if not cases:
        raise PartError('no P_LineAttack case (python3 '
                        'tools/native/gparts/attack.py --capture)')
    case = GC.load_case(cases[0])
    b = G.load_build(obj, IMAGE)
    vals = random_inputs(n, seed)
    rng, aim = sym('p_attack65.s:AT_RANGE'), sym('p_attack65.s:AT_AIM')
    recs = b''.join(struct.pack('<HHii', (v >> 16) & 0xFFFF, v & 0xFFFF,
                                r, a) for v, r, a in vals)
    out: Dict[str, Any] = {}
    for mode, name in enumerate(('rangeMul', 'mul3')):
        pc = GC.CL.Linkmap().address('p_attack65.s:' + name)
        ups = SG.mathref(case, name, pc,
                         ['a', 'x', '%06X 4' % rng, '%06X 4' % aim],
                         ['a', 'x'], recs, 4)
        upv = []
        for u in ups:               # out: A the low word, X the high
            lo, hi = struct.unpack('<HH', u)
            upv.append(_w(hi << 16 | lo))
        nat = native_bulk(b, mode, vals)
        bad = [(t, u, m_) for t, u, m_ in zip(vals, upv, nat) if u != m_]
        mod = sum(1 for t, u in zip(vals, upv) if u == model(name, *t))
        out[name] = {'inputs': len(vals), 'compared': min(len(upv),
                                                          len(nat)),
                     'different': len(bad) + abs(len(upv) - len(nat)),
                     'first': bad[:5], 'upstream_is_the_model': mod,
                     'seed': seed}
        say('%s: %d inputs, %d different (upstream = the model on %d)' % (
            name, len(vals), out[name]['different'], mod))
    return out


# ---------------------------------------------------------------------------
# The planted bugs (each in a scratch copy of the part's sources)
# ---------------------------------------------------------------------------

PLANT_EDITS: Dict[str, Tuple[str, List[Tuple[str, str]]]] = {
    # the aim's top and bottom slopes swapped (the window's start)
    'aim-slopes-swapped': ('attack.s', [(
        '''        lda #<AK_TOPSLOPE       ; topslope = 40960, bottomslope = -40960
        sta AK_TOP
        lda #>AK_TOPSLOPE
        sta AK_TOP+1
        stz AK_TOP+2
        stz AK_TOP+3
        lda #<(-AK_TOPSLOPE)
        sta AK_BOT
        lda #>(-AK_TOPSLOPE)
        sta AK_BOT+1
        lda #$FF
        sta AK_BOT+2
        sta AK_BOT+3''',
        '''        lda #<AK_TOPSLOPE       ; (planted) the slopes swapped
        sta AK_BOT
        lda #>AK_TOPSLOPE
        sta AK_BOT+1
        stz AK_BOT+2
        stz AK_BOT+3
        lda #<(-AK_TOPSLOPE)
        sta AK_TOP
        lda #>(-AK_TOPSLOPE)
        sta AK_TOP+1
        lda #$FF
        sta AK_TOP+2
        sta AK_TOP+3''')]),
    # the puff 4 units early taken as 10 (or the line's puff at the frac)
    'puff-4-units-early': ('attack.s', [(
        '''        lda #4
        FCALL puffPos''',
        '''        lda #0                  ; (planted) the puff at the frac
        FCALL puffPos''')]),
    # a gun special on a line that is not one: any special starts a door
    'gun-special-any-line': ('attack.s', [(
        '''        cmp #AK_GUNDOOR
        bne @r''',
        '''        cmp #AK_GUNDOOR         ; (planted) any special
        nop
        nop''')]),
    # damage before blood
    'damage-before-blood': ('attack.s', [(
        '''@blood: lda AK_DMG              ; P_SpawnBlood(x, y, z, la_damage)
        sta GA_12
        lda AK_DMG+1
        sta GA_13
        FCALL P_SpawnBlood
@dmg:   lda AK_DMG              ; P_DamageMobj(th, shootthing, shootthing,
        ora AK_DMG+1            ;   la_damage) when la_damage is not 0
        jeq stop''',
        '''@blood: ldx #11                 ; (planted) the damage first
:       lda GA_X,x
        pha
        dex
        bpl :-
        jsr @hurt
        ldx #0
:       pla
        sta GA_X,x
        inx
        cpx #12
        bne :-
        lda AK_DMG
        sta GA_12
        lda AK_DMG+1
        sta GA_13
        FCALL P_SpawnBlood
        jmp stop
@hurt:  lda AK_DMG
        ora AK_DMG+1
        bne :+
        rts
:       lda AK_LI
        sta GA_0
        lda AK_LI+1
        sta GA_1
        lda AK_SHOOT
        sta GA_2
        sta GA_4
        lda AK_SHOOT+1
        sta GA_3
        sta GA_5
        lda AK_DMG
        sta GA_6
        lda AK_DMG+1
        sta GA_7
        FCALL P_DamageMobj
        rts
@dmg:   lda AK_DMG              ; P_DamageMobj(th, shootthing, shootthing,
        ora AK_DMG+1            ;   la_damage) when la_damage is not 0
        jeq stop''')]),
}
PLANT_NAMES = tuple(PLANT_EDITS)
# the lean rules: at most 3 planted bugs in the test file (the ones most
# likely to happen); the fourth runs with --plants
DEFAULT_PLANTS = ('aim-slopes-swapped', 'puff-4-units-early',
                  'gun-special-any-line')


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


# the calls that show each planted bug (the targeted runs: a few of the
# chosen calls, by their paths, for the default test's time)
PLANT_PATHS = {'aim-slopes-swapped': (AIMLINEATTACK, 'target'),
               'puff-4-units-early': (LINEATTACK, 'puff'),
               'gun-special-any-line': (LINEATTACK, 'special-tic'),
               'damage-before-blood': (LINEATTACK, 'blood')}
TARGETED = 4


def plant_jobs(name: str, obj: Path, n: int = TARGETED) -> List[Tuple]:
    """The first n chosen calls of the plant's entry that take its path
    (demo3's first: they run fastest), $A5, f121."""
    ps = paths()
    key, want = PLANT_PATHS[name]
    sel = [p for p in selection(key, ps) if want in ps[key][p]]
    sel.sort(key=lambda p: (Path(p).parts[-3] != 'demo3', p))
    return [([(key, p)], str(obj), (FILLS[0],), (PROFILES[0],), ps[key])
            for p in sel[:n]]


def plants(names: Optional[Sequence[str]] = None, sample: int = 1,
           workers: int = 2, targeted: bool = False) -> Dict[str, Any]:
    """Each planted bug on the checkpoint's calls (every sample-th, $A5,
    f121), or with targeted on plant_jobs' few calls."""
    out = {}
    for name in (names or PLANT_NAMES):
        tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-attack-plant-',
                                    dir=str(BUILD)))
        try:
            obj = plant_build(name, tmp)
            jobs = plant_jobs(name, obj) if targeted else check_jobs(
                obj=obj, sample=sample, profiles=(PROFILES[0],))
            res = run_jobs(jobs, workers)
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
LABELS = ('P_LineAttack', 'P_AimLineAttack', 'PTR_AimTraverse',
          'PTR_ShootTraverse', 'shootSpecial', 'puffPos', 'mul3',
          'rangeMul')


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    """The part's bytes (attack.o; aktest.o is test-only, in the driver's
    area) against its budget; each routine's bytes (to the next of the
    part's routines in its segment) and group."""
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
        if module == PART and f and f[0] in b.segments:
            off = next(int(x[5:], 16) for x in f if x.startswith('Offs='))
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            lo = b.segments[f[0]][0] + off
            chunks.append((f[0], lo, lo + size))
    nat = SF.Native(obj)
    routines = {}
    for seg, lo, hi in chunks:
        g = int(seg[4:]) if seg.startswith('GGRP') else 0
        inside = sorted((b.labels[n], n) for n in LABELS
                        if lo <= b.labels[n] < hi and nat.group(n) == g)
        for k, (a, n) in enumerate(inside):
            end = inside[k + 1][0] if k + 1 < len(inside) else hi
            routines[n] = {'bytes': end - a, 'group': g, 'segment': seg}
    total = sum(hi - lo for _, lo, hi in chunks)
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
        rep['waiting_runs'] = len(results) - len(run)
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
    for name, r in rep.get('random', {}).items():
        say('random %-9s %d inputs, %d different' % (
            name, r['inputs'], r['different']))


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
        ps = paths(a.jobs)
        for key in ENTRIES:
            count: Dict[str, int] = {}
            for v in ps.get(key, {}).values():
                for x in v:
                    count[x] = count.get(x, 0) + 1
            say('%s: %d candidates, %s' % (key, len(ps.get(key, {})),
                                           json.dumps(count, sort_keys=True)))
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
