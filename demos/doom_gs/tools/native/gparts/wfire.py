#!/usr/bin/env python3
"""Part wfire's checkpoint (milestone 10, wave 6; docs/GAME.md 2.2 ACTTAB,
2.4 row wfire, 3.5; docs/game-parts/wfire.md), lean (the owner's rules of
2026-10-02): its image, a sample of the captured weapon actions, its
synthetic cases, its planted bugs, and build/native/game/wfire/report.json.

Usage:  python3 tools/native/gparts/wfire.py --build
        python3 tools/native/gparts/wfire.py --capture [--jobs 2]
        python3 tools/native/gparts/wfire.py --check [--jobs 2] [--sample K]
                [--synthetic NAME,...] [--profiles f121,fastpath]
        python3 tools/native/gparts/wfire.py --plants [--plant NAME,...]
        python3 tools/native/gparts/wfire.py --report

The weapon actions are ACTTAB's, entered by upstream's JML through
callAction, which ref816's --capture does not count. As part pspr checked
its own actions, they are checked through part pspr's P_MovePsprites (its
args.json entry): a captured or synthetic P_MovePsprites call that reaches
the action through tickPsprite, setPsprite and ACTTAB, run whole natively
(pspr's routines, then the action, gunShot, bulletSlope, part attack's
P_AimLineAttack and P_LineAttack, damage, spawn ...) and compared whole
(gcanon's routine mode, R1-R7; the write log: no stray write, part
mobjstate's shared rule with every built part's scratch block).

The selection (--capture, at most LIMIT calls an action): the survey's
P_MovePsprites calls that reached A_FirePistol (demo1 89, demo2 43,
newgame 2) or A_FireShotgun (demo3 26, demo1 16, demo2 8), eligible (every
dispatch target they reached built in the part's image), spread evenly
over the runs. No run fires the chaingun, the rocket launcher, the fist or
the chainsaw (the survey: 0 calls), so those actions are synthetic.

The synthetic cases (SYNTHETIC): a captured pistol or shotgun call whose
aim found a target (the reference's _g_linetarget after it) with the
player's weapon, its psprite and its place poked, the reference's own
P_MovePsprites run by ref816 --call (gamecap.call_case); each case takes
the first base on which the reference took the case's path (took()):
  punch-berserk   the fist, berserk, the player 24 units from the target's
                  edge facing it: A_Punch's x 10, a hit, the turn
  punch-miss      the fist, facing away: no target
  saw-left, saw-right   the chainsaw beside the target, the player's angle
                  10 degrees right (left) of it: A_Saw's far turns
                  (angle - ANG90/21, angle + ANG90/21)
  saw-near-left, saw-near-right   2 degrees: mo->angle + ANG90/20, - ANG90/20
  saw-miss        the chainsaw facing away: the saw's sound, no turn
  rocket-straight, rocket-left, rocket-right, rocket-none   the rocket
                  launcher at the player's own place, its angle at the
                  target, 1 << 26 right of it (the second aim hits), 1 <<
                  26 left of it (the third), away (none: level, slope 0):
                  P_SpawnPlayerMissile's aim retries
  cgun-second     the chaingun's S_CHAIN1 ending: S_CHAIN2's A_FireCGun,
                  the flash + 1
  cgun-empty      the same with no clip: no shot
Each melee or chaingun case puts its weapon's psprite on the state before
the action's with 1 tic left (S_PUNCH1, S_SAW1, S_MISSILE1, S_CHAIN1), so
P_MovePsprites' tickPsprite reaches the action.

The planted bugs (--plants, PLANTS: GAME.md 2.4's three), each built from a
scratch copy of the part's sources in a temporary directory (deleted) and
run on its check, which must fail.
"""

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE))

from native import gamecap as GC, gameroutine as GR, glayout as GL, \
    grun as G  # noqa: E402
from ref816 import bounded  # noqa: E402
import mobjstate as MS  # noqa: E402  (wave 1's harness: its generic parts)
import pspr as PS  # noqa: E402  (wave 3's: P_MovePsprites' run machinery)

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'wfire'
WAVE = 6
OUT = GL.GAME / PART
MYCASES = OUT / 'cases'
REPORT = OUT / 'report.json'
SYN_FILE = OUT / 'synthetic.json'
FILLS = (0xA5,)
PROFILES = ('f121', 'fastpath')
NAME = 'ptest'
UPSTREAM_BYTES = 964
BUDGET = 1300                   # GAME.md 2.4: upstream 964 x 1.3
MODULES = ('wfire',)
LIMIT = 40
JOBS = 2

MOVE = PS.MOVE                  # p_pspr65.s:P_MovePsprites (part pspr's)
PISTOL = 'p_pspr65.s:A_FirePistol'
SHOTGUN = 'p_pspr65.s:A_FireShotgun'
CGUN = 'p_pspr65.s:A_FireCGun'
MISSILE = 'p_pspr65.s:A_FireMissile'
PUNCH = 'p_pspr65.s:A_Punch'
SAW = 'p_pspr65.s:A_Saw'
CAPTURED = (PISTOL, SHOTGUN)
ACTIONS = (PISTOL, SHOTGUN, CGUN, MISSILE, PUNCH, SAW)
LABELS = ('A_FirePistol', 'A_FireShotgun', 'A_FireCGun', 'A_FireMissile',
          'A_Punch', 'A_Saw', 'P_SpawnPlayerMissile', 'bulletSlope',
          'gunShot', 'meleeAngle', 'spread', 'meleeAttack', 'angleToTarget',
          'p_pspr_randMod', 'useAmmo')

FRAC = 1 << 16
ANG = 1 << 32
ANG90_20 = 0x03333333
ANG90_21 = 0x030C30C3
AIM_STEP = 1 << 26


class PartError(Exception):
    pass


def say(text: str) -> None:
    print(text, flush=True)


def missing() -> Optional[str]:
    """None when the shared outputs, the survey, the level bases, ref816
    and a2vm are there; else what is missing and its command."""
    return PS.missing()


def use_cases() -> None:
    MS.use_cases(MYCASES)


# ---------------------------------------------------------------------------
# The image
# ---------------------------------------------------------------------------

def build(game: Path = GL.GAME, bugs: Sequence[Tuple[str, str, str]] = ()
          ) -> Path:
    """The part's image (GAME/wfire/ptest.*) from a scratch copy of the
    build files and of the bugs' files (relative to src/native), each bug
    (file, old, new) applied once; the copy is deleted. Fails on a build
    warning."""
    tmp = Path(tempfile.mkdtemp(prefix='tmp-wfire-build-', dir=str(BUILD)))
    try:
        src = tmp / 'src'
        copy_files = set(G.PLANT_COPY) | {'game/%s/part.mk' % PART}
        copy_files |= {name for name, _, _ in bugs}
        for f in copy_files:
            (src / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(SRC / f), str(src / f))
        for name, old, new in bugs:
            text = (src / name).read_text()
            if text.count(old) != 1:
                raise PartError('%s: the edit no longer applies: %r' % (
                    name, old[:60]))
            (src / name).write_text(text.replace(old, new))
        objs = game / PART / 'game' / PART
        if objs.exists():               # (wfire.inc is no prerequisite)
            for p in objs.glob('*.o'):
                p.unlink()
        cmd = ['make', '-s', '-C', str(src), '-f', 'game.mk', 'part',
               'P=%s' % PART, 'ROOT=%s' % ROOT, 'GAME=%s' % game]
        r = bounded.run(cmd, timeout=600, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, universal_newlines=True)
        if r.returncode:
            raise PartError('the build failed:\n' + r.stdout[-3000:])
        if 'arning' in r.stdout:
            raise PartError('the build warns:\n' + r.stdout[-3000:])
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    return game / PART


def load(obj: Path = OUT):
    return G.load_build(obj, NAME)


def sizes(b) -> Dict[str, Any]:
    """The part's bytes (wfire.o's segments) against its budget."""
    ms = MS.module_ranges(b)
    segs = {seg: hi + 1 - lo for seg, lo, hi in ms.get('wfire', ())}
    total = sum(segs.values())
    return {'part_bytes': total, 'budget': BUDGET,
            'upstream_bytes': UPSTREAM_BYTES,
            'over_budget_pct': round(100.0 * (total - BUDGET) / BUDGET, 1),
            'segments': segs,
            'routines': {n: {'group': G.entry_group(b, n),
                             'address': '%04X' % b.labels[n]}
                         for n in LABELS if n in b.labels}}


# ---------------------------------------------------------------------------
# The selection and the captures
# ---------------------------------------------------------------------------

def action_of(run: str, hit: int) -> Optional[str]:
    """The fire action a P_MovePsprites call reached (None: none)."""
    got = [t for t in PS.reached(run, MOVE, hit) if t in ACTIONS]
    return got[0] if got else None


def eligible(run: str, hit: int) -> List[str]:
    """The dispatch targets the call reached that are not built in the
    part's image: empty when the call is eligible."""
    built = set(GL.built_set(extra=[PART]))
    return [t for t in PS.reached(run, MOVE, hit)
            if (GL.owner_of(t) or 'core') not in built | {'core'}]


def candidates() -> Dict[str, List[Tuple[str, int]]]:
    """action -> its eligible P_MovePsprites calls (run, hit)."""
    out: Dict[str, List[Tuple[str, int]]] = {a: [] for a in CAPTURED}
    for run in GC.RUNS:
        sv = PS.survey(run)
        if not sv:
            continue
        r = sv['routines'].get(MOVE, {})
        for h in sorted(int(k) for k in r.get('reached', {})):
            a = action_of(run, h)
            if a in out and not eligible(run, h):
                out[a].append((run, h))
    return out


def waiting() -> Dict[str, int]:
    """The fire calls not eligible, by the target they wait for."""
    out: Dict[str, int] = {}
    for run in GC.RUNS:
        sv = PS.survey(run)
        if not sv:
            continue
        r = sv['routines'].get(MOVE, {})
        for h in sorted(int(k) for k in r.get('reached', {})):
            if action_of(run, h) in CAPTURED:
                for t in eligible(run, h):
                    out[t] = out.get(t, 0) + 1
    return out


def selection(action: str) -> List[Tuple[str, int]]:
    """At most LIMIT calls of the action, spread evenly over its
    candidates (in the runs' order), each run at least one."""
    cand = candidates()[action]
    by: Dict[str, List[Tuple[str, int]]] = {}
    for c in cand:
        by.setdefault(c[0], []).append(c)
    chosen = [v[0] for v in by.values()]
    rest = [c for c in cand if c not in chosen]
    chosen += PS.spread(rest, max(0, LIMIT - len(chosen)))
    return sorted(chosen, key=lambda c: (GC.RUNS.index(c[0]), c[1]))


def _capture_job(job) -> str:
    run, hits = job
    use_cases()
    tics = GC.survey_of(run)['routines'][MOVE]['tic']
    made = GC.capture(run, MOVE, hits, tics, say=lambda *a: None)
    return '%s: %d made of %d' % (run, len(made), len(hits))


def capture(jobs: int = JOBS) -> None:
    """The selected calls' cases, into the part's own case directory (a
    run's first batch alone, so its base is made once)."""
    use_cases()
    want: Dict[str, List[int]] = {}
    for a in CAPTURED:
        for run, h in selection(a):
            want.setdefault(run, []).append(h)
    todo: List[Tuple[str, List[int]]] = []
    for run, hits in sorted(want.items()):
        d = GC.case_dir(run, MOVE)
        miss = sorted({h for h in hits
                       if not (d / ('h%08d.case.z' % h)).exists()})
        for i in range(0, len(miss), GC.BATCH):
            todo.append((run, miss[i:i + GC.BATCH]))
    first, rest = [], []
    for j in todo:
        (rest if any(f[0] == j[0] for f in first) or
         GC.base_path(j[0]).exists() else first).append(j)
    for batch in (first, rest):
        if batch:
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                for got in pool.map(_capture_job, batch):
                    say(got)


def case_paths(action: str) -> List[Tuple[str, int, Path]]:
    use_cases()
    out = []
    for run, h in selection(action):
        p = GC.case_dir(run, MOVE) / ('h%08d.case.z' % h)
        if p.exists():
            out.append((run, h, p))
    return out


# ---------------------------------------------------------------------------
# A call's path, from the reference's memory (the coverage, GAME.md 3.5
# step 2)
# ---------------------------------------------------------------------------

def uconst(name: str) -> int:
    return PS.uconst(name)


def exported(name: str) -> int:
    return PS.exported(name)


def _ptr(m, a: int) -> int:
    return int.from_bytes(m.read(a, 3), 'little')


def _u32(m, a: int) -> int:
    return int.from_bytes(m.read(a, 4), 'little')


def _s32(m, a: int) -> int:
    return int.from_bytes(m.read(a, 4), 'little', signed=True)


def player_mo(m) -> int:
    return _ptr(m, PS.player() + uconst('UO_PL_MO'))


def mo_angle(m, mo: int) -> int:
    return _u32(m, mo + uconst('UO_MO_ANGLE'))


def linetarget(m) -> int:
    return _ptr(m, exported('_g_linetarget'))


def path_of(case: GC.Case, action: str) -> List[str]:
    """The paths a captured fire call took: the action, the pistol's
    accuracy (refire 0: the first shot), whether the aim found a target,
    whether a thing's health fell (a hit) and a thing died."""
    e, a = case.entry, case.after
    pl = PS.player()
    out = [action.split(':')[1]]
    if action == PISTOL:
        out.append('accurate' if e.u16(pl + uconst('UO_PL_REFIRE')) == 0
                   else 'spread')
    out.append('target' if linetarget(a) else 'no-target')
    hit = died = False
    t = linetarget(a)
    if t:
        h0 = _s32(e, t + uconst('UO_MO_HEALTH'))
        h1 = _s32(a, t + uconst('UO_MO_HEALTH'))
        hit = h1 < h0
        died = h0 > 0 >= h1
    out.append('hit' if hit else 'no-hit')
    if died:
        out.append('kill')
    return out


# ---------------------------------------------------------------------------
# The synthetic cases
# ---------------------------------------------------------------------------

SYNTHETIC = ('punch-berserk', 'punch-miss', 'saw-left', 'saw-right',
             'saw-near-left', 'saw-near-right', 'saw-miss',
             'rocket-straight', 'rocket-left', 'rocket-right', 'rocket-none',
             'cgun-second', 'cgun-empty')
SYN_ACTION = {'punch': PUNCH, 'saw': SAW, 'rocket': MISSILE, 'cgun': CGUN}
# the player's angle against the direction to the target, in degrees
SAW_OFFSET = {'saw-left': -10.0, 'saw-right': 10.0, 'saw-near-left': -2.0,
              'saw-near-right': 2.0}
ROCKET_OFFSET = {'rocket-straight': 0, 'rocket-left': -AIM_STEP,
                 'rocket-right': AIM_STEP, 'rocket-none': ANG // 2}
ROCKET_RANGE = (260, 1000)      # the target's distance (units) for a base
BASES = 8                       # bases tried a synthetic case


def u16(v: int) -> bytes:
    return PS.u16(v)


def s32(v: int) -> bytes:
    return PS.s32(v)


def bam(dx: float, dy: float) -> int:
    return int(round(math.atan2(dy, dx) / (2 * math.pi) * ANG)) % ANG


def target_bases() -> List[Tuple[str, Path]]:
    """The captured calls whose aim found a live target: (name, path)."""
    use_cases()
    out = []
    for a in CAPTURED:
        for run, h, p in case_paths(a):
            out.append(('%s/h%08d' % (run, h), p))
    return out


def base_info(case: GC.Case) -> Optional[Dict[str, Any]]:
    """The player's and the target's places in the base (None: no live
    target)."""
    e = case.entry
    t = linetarget(case.after)
    if not t or _s32(e, t + uconst('UO_MO_HEALTH')) <= 0:
        return None
    mo = player_mo(e)

    def xyz(m: int) -> Tuple[int, int, int]:
        return tuple(_s32(e, m + uconst('UO_MO_' + k)) for k in 'XYZ')
    px, py, pz = xyz(mo)
    tx, ty, tz = xyz(t)
    dx, dy = (tx - px) / FRAC, (ty - py) / FRAC
    return {'mo': mo, 't': t, 'p': (px, py, pz), 'tp': (tx, ty, tz),
            'dist': math.hypot(dx, dy), 'dir': bam(dx, dy),
            'radius': _s32(e, t + uconst('UO_MO_RADIUS')) / FRAC}


def weapon_pokes(weapon: str, state: str, ammo: Optional[Tuple[str, int]]
                 = None, berserk: bool = False) -> List[Tuple[int, bytes]]:
    """The player alive with weapon ready, its psprite at state with 1
    tic left, no change pending, berserk or not."""
    pl = PS.player()
    out = PS.psp_pokes(uconst('UC_S_' + state), 1)
    out += [(pl + uconst('UO_PL_READYWEAPON'), u16(uconst('UC_WP_' + weapon))),
            (pl + uconst('UO_PL_PENDINGWEAPON'),
             u16(uconst('UC_WP_NOCHANGE'))),
            (pl + uconst('UO_PL_HEALTH'), u16(100)),
            (pl + uconst('UO_PL_PLAYERSTATE'), u16(uconst('UC_PST_LIVE'))),
            (pl + uconst('UO_PL_POWERS') + 2 * uconst('UC_PW_STRENGTH'),
             u16(1 if berserk else 0))]
    if ammo:
        out.append((pl + uconst('UO_PL_AMMO') + 2 * uconst('UC_AM_' + ammo[0]),
                    u16(ammo[1])))
    return out


def place_pokes(info: Dict[str, Any], kind: str) -> List[Tuple[int, bytes]]:
    """The player's place and angle for the case."""
    mo = info['mo']
    px, py, pz = info['p']
    tx, ty, tz = info['tp']
    ang = info['dir']
    if kind.startswith(('punch', 'saw')):
        d = info['radius'] + 16 + 8            # 8 units between the edges
        ux, uy = (tx - px) / FRAC / info['dist'], (ty - py) / FRAC / \
            info['dist']
        px = tx - int(round(d * ux * FRAC))
        py = ty - int(round(d * uy * FRAC))
        pz = tz
        if kind.endswith('miss'):
            ang = (ang + ANG // 2) % ANG
        else:
            ang = (ang + int(round(SAW_OFFSET.get(kind, 0.0) / 360 * ANG))
                   ) % ANG
    elif kind.startswith('rocket'):
        ang = (ang + ROCKET_OFFSET[kind]) % ANG
    return [(mo + uconst('UO_MO_X'), s32(px)), (mo + uconst('UO_MO_Y'), s32(py)),
            (mo + uconst('UO_MO_Z'), s32(pz)),
            (mo + uconst('UO_MO_ANGLE'), s32(ang))]


def synthetic_pokes(kind: str, info: Dict[str, Any]
                    ) -> List[Tuple[int, bytes]]:
    if kind.startswith('punch'):
        w = weapon_pokes('FIST', 'PUNCH1', berserk=kind == 'punch-berserk')
    elif kind.startswith('saw'):
        w = weapon_pokes('CHAINSAW', 'SAW1')
    elif kind.startswith('rocket'):
        w = weapon_pokes('MISSILE', 'MISSILE1', ammo=('MISL', 5))
    elif kind == 'cgun-second':
        w = weapon_pokes('CHAINGUN', 'CHAIN1', ammo=('CLIP', 50))
    elif kind == 'cgun-empty':
        w = weapon_pokes('CHAINGUN', 'CHAIN1', ammo=('CLIP', 0))
    else:
        raise PartError('no synthetic case %s' % kind)
    return w + (place_pokes(info, kind) if not kind.startswith('cgun')
                else [])


def took(kind: str, case: GC.Case) -> List[str]:
    """Why the reference's call is not the case's path (empty: it is)."""
    e, a = case.entry, case.after
    pl = PS.player()
    mo = player_mo(e)
    lt = linetarget(a)
    why = []
    if kind.startswith(('punch', 'saw')):
        if kind.endswith('miss'):
            if lt:
                why.append('a target')
            if mo_angle(e, mo) != mo_angle(a, mo):
                why.append('a turn')
        else:
            if not lt:
                why.append('no target')
            d = (mo_angle(a, mo) - mo_angle(e, mo)) % ANG
            near = d in (ANG90_20, ANG - ANG90_20)
            if kind.startswith('saw-near') and not near:
                why.append('not the near turn')
            if kind in ('saw-left', 'saw-right') and near:
                why.append('not the far turn')
    elif kind.startswith('rocket'):
        an = _u32(a, GC.CL.Linkmap().address('p_spawn65.s:SP_AN'))
        th = _ptr(a, GC.CL.Linkmap().address('p_spawn65.s:SP_TH'))
        want = {'rocket-straight': 0, 'rocket-left': AIM_STEP,
                'rocket-right': ANG - AIM_STEP, 'rocket-none': 0}[kind]
        if (an - mo_angle(e, mo)) % ANG != want:
            why.append('the aim at %X' % ((an - mo_angle(e, mo)) % ANG))
        if bool(lt) == (kind == 'rocket-none'):
            why.append('a target' if lt else 'no target')
        if not th or not any(_s32(a, th + uconst('UO_MO_' + k))
                             for k in ('MOMX', 'MOMY')):
            why.append('the rocket exploded')
    elif kind.startswith('cgun'):
        clip = pl + uconst('UO_PL_AMMO') + 2 * uconst('UC_AM_CLIP')
        used = e.u16(clip) != a.u16(clip)
        if used != (kind == 'cgun-second'):
            why.append('a round used' if used else 'no round used')
    return why


def synthetic_case(kind: str, base: Path) -> Tuple[GC.Case, List[str]]:
    case = GC.load_case(base)
    info = base_info(case)
    if info is None:
        return case, ['no live target']
    if kind.startswith('rocket') and not (
            ROCKET_RANGE[0] <= info['dist'] <= ROCKET_RANGE[1]):
        return case, ['the target %d units away' % info['dist']]
    c = GC.call_case(case, synthetic_pokes(kind, info),
                     '%s on %s' % (kind, base.name))
    return c, took(kind, c)


def synthetic_plan(kinds: Sequence[str] = SYNTHETIC, fresh: bool = False
                   ) -> Dict[str, Optional[str]]:
    """kind -> the base it takes (the first of target_bases() on which the
    reference took the path; kept in synthetic.json)."""
    old = {} if fresh or not SYN_FILE.exists() else \
        json.loads(SYN_FILE.read_text())
    bases = target_bases()
    out = dict(old)
    for kind in kinds:
        if old.get(kind) and Path(old[kind]).exists():
            continue
        out[kind] = None
        tried = 0
        for _, p in bases:
            c = GC.load_case(p)
            info = base_info(c)
            if info is None or (kind.startswith('rocket') and not (
                    ROCKET_RANGE[0] <= info['dist'] <= ROCKET_RANGE[1])):
                continue
            tried += 1
            try:
                _, why = synthetic_case(kind, p)
            except GC.CapError as error:
                why = [str(error)]
            if not why:
                out[kind] = str(p)
                break
            if tried >= BASES:
                break
        say('synthetic %-16s %s' % (kind, out[kind] or 'NO BASE (%d tried)'
                                    % tried))
    SYN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SYN_FILE.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    return out


# ---------------------------------------------------------------------------
# The jobs
# ---------------------------------------------------------------------------

_BUILDS: Dict[str, Any] = {}


def _build(obj: str):
    if obj not in _BUILDS:
        _BUILDS[obj] = load(Path(obj))
    return _BUILDS[obj]


def _job(job) -> List[Dict[str, Any]]:
    """kind ('case' or 'synthetic'), the case file or the synthetic name
    (with its base), the action, the image, fills, profiles."""
    kind, what, action, base, obj, fills, profiles = job
    use_cases()
    b = _build(obj)
    label = ('%s/%s' % (Path(what).parent.parent.name, Path(what).name)
             if kind == 'case' else what)
    try:
        if kind == 'case':
            case = GC.load_case(Path(what))
            path = path_of(case, action)
            why: List[str] = []
        else:
            case, why = synthetic_case(what, Path(base))
            path = ['synthetic: ' + what]
        prep = PS.Prep(case, GR.all_args()[MOVE], b)
    except Exception as error:              # reported, never hidden
        return [{'ok': False, 'kind': kind, 'entry': action, 'case': label,
                 'error': '%s: %s' % (type(error).__name__, error)}]
    out = []
    for fill in fills:
        for prof in profiles:
            try:
                r = PS.run_one(prep, b, fill, prof)
                if why:
                    r['ok'] = False
                    r['diff'] = ['synthetic %s: %s' % (what, x)
                                 for x in why] + r.get('diff', [])
            except Exception as error:      # reported per run
                r = {'ok': False, 'fill': '%02x' % fill, 'profile': prof,
                     'error': '%s: %s' % (type(error).__name__, error)}
            r.update(kind=kind, entry=action, path=' '.join(path),
                     case=label, through=MOVE)
            out.append(r)
    return out


def plan(obj: Path = OUT, fills=FILLS, profiles=PROFILES, sample: int = 1,
         actions: Optional[Sequence[str]] = None,
         synthetic_names: Sequence[str] = SYNTHETIC
         ) -> Tuple[List[Tuple], Dict[str, Any]]:
    o = str(obj)
    jobs: List[Tuple] = []
    elig: Dict[str, Any] = {}
    cand = candidates()
    for a in CAPTURED:
        if actions and a not in actions:
            continue
        cases = case_paths(a)
        elig[a] = {'candidates': len(cand[a]), 'selected': len(selection(a)),
                   'captured': len(cases)}
        for run, h, p in cases[::sample]:
            jobs.append(('case', str(p), a, None, o, tuple(fills),
                         tuple(profiles)))
    if synthetic_names:
        syn = synthetic_plan(synthetic_names)
        for name in synthetic_names:
            a = SYN_ACTION[name.split('-')[0]]
            if actions and a not in actions:
                continue
            if not syn.get(name):
                jobs.append(('synthetic', name, a, None, o, tuple(fills),
                             tuple(profiles)))
                continue
            jobs.append(('synthetic', name, a, syn[name], o, tuple(fills),
                         tuple(profiles)))
    return jobs, elig


def run_jobs(jobs: Sequence[Tuple], workers: int = JOBS
             ) -> List[Dict[str, Any]]:
    good = [j for j in jobs if not (j[0] == 'synthetic' and j[3] is None)]
    out: List[Dict[str, Any]] = [
        {'ok': False, 'kind': 'synthetic', 'entry': j[2], 'case': j[1],
         'error': 'no base on which the reference takes its path'}
        for j in jobs if j[0] == 'synthetic' and j[3] is None]
    if workers <= 1:
        for j in good:
            out += _job(j)
        return out
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for got in pool.map(_job, good, chunksize=1):
            out += got
    return out


def check(jobs: int = JOBS, sample: int = 1, actions=None,
          synthetic_names: Sequence[str] = SYNTHETIC,
          profiles: Sequence[str] = PROFILES, rebuild: bool = True
          ) -> Dict[str, Any]:
    if rebuild:
        build()
    b = load()
    js, elig = plan(OUT, FILLS, profiles, sample, actions, synthetic_names)
    start = time.time()
    res = run_jobs(js, jobs)
    entries = MS.summarize(res)
    rep = {'entries': entries, 'selection': elig, 'waiting': waiting(),
           'runs': len(res),
           'failures': sum(1 for r in res if not r.get('ok')),
           'strays': sum(r.get('strays') or 0 for r in res),
           'seconds': round(time.time() - start),
           'fills': ['%02x' % f for f in FILLS], 'profiles': list(profiles),
           'sizes': sizes(b), 'sample': sample,
           'synthetic': synthetic_plan(synthetic_names)
           if synthetic_names else {}}
    rep['paths_taken'] = {k: sorted(e['paths']) for k, e in entries.items()}
    return rep


# ---------------------------------------------------------------------------
# The planted bugs (GAME.md 2.4's row), each caught by its check
# ---------------------------------------------------------------------------

WF = 'game/%s/' % PART
PLANTS: Dict[str, Dict[str, Any]] = {
    # the shotgun's pellets in another order: a pellet's spread taken
    # before its damage (the P_Random order of each pellet)
    'pellet-order': {'check': SHOTGUN, 'bugs': [
        (WF + 'wfire.s', """        ROUTINE gunShot
        sta WF_ACC
        lda #3                  ; damage = 5 * (P_Random() % 3 + 1)""",
         """        ROUTINE gunShot
        sta WF_ACC
        cmp #0                  ; (planted: the spread first)
        bne :+
        FCALL spread
:       lda #3                  ; damage = 5 * (P_Random() % 3 + 1)"""),
        (WF + 'wfire.s', """        lda WF_ACC              ; not accurate: the spread
        bne :+
        FCALL spread
:       lda PLR + PL_MO         ; P_LineAttack(mo, angle, MISSILERANGE,""",
         """        ; (planted: the spread was taken first)
        lda PLR + PL_MO         ; P_LineAttack(mo, angle, MISSILERANGE,""")]},
    # the spread taken on the first shot (the pistol's accurate shot)
    'spread-first-shot': {'check': PISTOL, 'bugs': [
        (WF + 'wfire.s', """        lda WF_ACC              ; not accurate: the spread
        bne :+
        FCALL spread
:       lda PLR + PL_MO         ; P_LineAttack(mo, angle, MISSILERANGE,""",
         """        FCALL spread            ; (planted: always the spread)
        lda PLR + PL_MO         ; P_LineAttack(mo, angle, MISSILERANGE,""")]},
    # the aim retries' order: right (- 1 << 26) before left
    'aim-order': {'check': None, 'bugs': [
        (WF + 'wfire.s', """@done:  rts
@step:  .byte $04, $F8""", """@done:  rts
@step:  .byte $FC, $08                  ; (planted: right, then left)""")]},
}
PLANT_NAMES = tuple(PLANTS)


def plant_jobs(plant: Dict[str, Any], obj: Path, sample: int = 1
               ) -> List[Tuple]:
    """A planted bug's check: its action's chosen captured calls ($A5,
    f121; every sample-th); for the aim's order every chosen call of both
    actions."""
    acts = [plant['check']] if plant['check'] else list(CAPTURED)
    js, _ = plan(obj, (0xA5,), ('f121',), sample=sample, actions=acts,
                 synthetic_names=())
    return js


def run_plant(name: str, jobs: int = JOBS, sample: int = 1
              ) -> Dict[str, Any]:
    p = PLANTS[name]
    tmp = Path(tempfile.mkdtemp(prefix='tmp-wfire-plant-', dir=str(BUILD)))
    try:
        obj = build(tmp / 'game', p['bugs'])
        res = run_jobs(plant_jobs(p, obj, sample), jobs)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
        _BUILDS.clear()
    bad = [r for r in res if not r.get('ok')]
    return {'check': p['check'] or 'both actions', 'runs': len(res),
            'failed': len(bad), 'caught': bool(bad),
            'first': [{k: r.get(k) for k in ('case', 'path', 'diff', 'error',
                                             'ended', 'stop') if r.get(k)}
                      for r in bad[:2]]}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def write_report(rep: Dict[str, Any], plants: Optional[Dict[str, Any]] = None
                 ) -> Path:
    out: Dict[str, Any] = {}
    if REPORT.exists():
        out = json.loads(REPORT.read_text())
    out.update(rep)
    out['format'] = 'game-part-report 1'
    out['part'] = PART
    out['wave'] = WAVE
    if plants is not None:
        out['plants'] = plants
    out['build_kb'] = MS.du_kb(OUT)
    out['notes'] = [
        'lean checkpoint (the owner\'s rules of 2026-10-02): at most %d '
        'captured calls an action, one fill ($A5); f121 and fastpath' % LIMIT,
        'the actions run inside part pspr\'s P_MovePsprites (ACTTAB); each '
        'entry here is the action the call reached',
        'clock: the call\'s time under the profile (fabric clocks); '
        'cpu_cycles: the W65C02S\'s cycles of the whole P_MovePsprites call',
        'sizes: wfire.o (the part has no test-only code)']
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=1, default=str) + '\n')
    return REPORT


def print_check(rep: Dict[str, Any]) -> None:
    for k, e in sorted(rep['entries'].items()):
        n = len(e['cases']) if isinstance(e['cases'], (list, set)) \
            else e['cases']
        say('%-28s %3d cases %3d runs %2d failed  cycles %s  S %s' % (
            k, n, e['runs'], e['failures'], e['cpu_cycles'], e['lowest_s']))
        for f in e['first_failures'][:3]:
            say('    ' + json.dumps(f, default=str)[:700])
    say('runs %d, failures %d, stray writes %d, %d s' % (
        rep['runs'], rep['failures'], rep['strays'], rep['seconds']))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--jobs', type=int, default=JOBS)
    parser.add_argument('--sample', type=int, default=1)
    parser.add_argument('--actions', default='')
    parser.add_argument('--synthetic', default=None,
                        help='only these synthetic cases (comma list)')
    parser.add_argument('--plant', default='')
    parser.add_argument('--profiles', default=','.join(PROFILES))
    args = parser.parse_args(argv)
    why = missing()
    if why:
        print('cannot run: %s' % why, file=sys.stderr)
        return 2
    status = 0
    if args.build:
        print(json.dumps(sizes(load(build())), indent=1))
    if args.capture:
        capture(args.jobs)
    if args.check:
        names = SYNTHETIC if args.synthetic is None else tuple(
            x for x in args.synthetic.split(',') if x)
        acts = ['p_pspr65.s:' + a if ':' not in a else a
                for a in args.actions.split(',') if a] or None
        rep = check(args.jobs, args.sample, acts, names,
                    tuple(args.profiles.split(',')))
        write_report(rep)
        print_check(rep)
        status |= 1 if rep['failures'] or rep['strays'] else 0
    if args.plants:
        pl = {}
        for n in [x for x in args.plant.split(',') if x] or PLANT_NAMES:
            pl[n] = run_plant(n, args.jobs)
            say('%-20s %s' % (n, ('caught: %d of %d runs fail: %s' % (
                pl[n]['failed'], pl[n]['runs'], str(pl[n]['first'])[:300]))
                if pl[n]['caught'] else 'NOT CAUGHT (%d runs)' %
                pl[n]['runs']))
        write_report({}, plants=pl)
        status |= 0 if all(p['caught'] for p in pl.values()) else 1
    if args.report:
        print(REPORT.read_text() if REPORT.exists() else 'no report yet')
    return status


if __name__ == '__main__':
    sys.exit(main())
